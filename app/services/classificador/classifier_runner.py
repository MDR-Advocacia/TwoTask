"""Orquestrador da classificacao em batch do Classificador.

Clone enxuto de `PrazosIniciaisBatchClassifier`, adaptado pro modulo:
- Sem template matching (nao gera tarefas, gera diagnostico)
- Sem prazo_calculator (nao classifica prazo)
- Materializa pedidos + patrocinio + contestacao + sentenca + transito
  + primeira_habilitacao_master direto no `ClassificadorProcesso`

Fluxo (espelhado do PI):
1. `collect_pending(lote_id)` -> processos em PRONTO_PARA_CLASSIFICAR
2. `submit_batch(processos)` -> cria batch na Anthropic + move pra
   EM_CLASSIFICACAO
3. `refresh_batch_status(batch)` -> polling
4. `apply_batch_results(batch)` -> baixa JSONL, parseia, materializa
   campos + move pra CLASSIFICADO/ERRO_CLASSIFICACAO

Reusa `AnthropicClassifierClient` do PI (Batches API + retry + repair).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, List, Optional

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.classificador import (
    BATCH_STATUS_APPLIED,
    BATCH_STATUS_FAILED,
    BATCH_STATUS_IN_PROGRESS,
    BATCH_STATUS_READY,
    BATCH_STATUS_SUBMITTED,
    ClassificadorBatch,
    ClassificadorLote,
    ClassificadorPedido,
    ClassificadorProcesso,
    LOTE_STATUS_CLASSIFIED,
    LOTE_STATUS_CLASSIFYING,
    PROC_STATUS_CLASSIFIED,
    PROC_STATUS_ERROR_CLASSIFICATION,
    PROC_STATUS_READY,
)
from app.models.classification_taxonomy import (
    ClassificationCategory,
    ClassificationSubcategory,
)
from app.services.classificador.classifier_prompts import (
    SYSTEM_PROMPT,
    build_user_message,
)
from app.services.classificador.classifier_schema import (
    ClassificadorClassificationResponse,
)
from app.services.classifier.ai_client import AnthropicClassifierClient

logger = logging.getLogger(__name__)

# Status retornado pela Anthropic quando o batch terminou.
ANTHROPIC_STATUS_ENDED = "ended"


class ClassificadorBatchClassifier:
    """Orquestra classificacao em lote dos processos do Classificador."""

    def __init__(
        self,
        db: Session,
        ai_client: Optional[AnthropicClassifierClient] = None,
    ):
        self.db = db
        # Reusa settings do PI (mesmo modelo/limite) — em Fase 5 pode
        # ganhar settings dedicados se quiser tunar separado.
        self.ai = ai_client or AnthropicClassifierClient(
            model=settings.prazos_iniciais_classifier_model,
            max_tokens=settings.prazos_iniciais_classifier_max_tokens,
        )

    # ──────────────────────────────────────────────────────────────────
    # Submit
    # ──────────────────────────────────────────────────────────────────

    def collect_pending_processos(
        self, lote_id: int, limit: Optional[int] = None,
    ) -> List[ClassificadorProcesso]:
        """Processos do lote em PRONTO_PARA_CLASSIFICAR com capa+integra."""
        query = (
            self.db.query(ClassificadorProcesso)
            .filter(ClassificadorProcesso.lote_id == lote_id)
            .filter(ClassificadorProcesso.status == PROC_STATUS_READY)
            .filter(ClassificadorProcesso.capa_json.isnot(None))
            .filter(ClassificadorProcesso.integra_json.isnot(None))
            .order_by(ClassificadorProcesso.id.asc())
        )
        if limit:
            query = query.limit(limit)
        return query.all()

    async def submit_batch(
        self,
        lote_id: int,
        processos: List[ClassificadorProcesso],
        requested_by_email: Optional[str] = None,
        requested_by_user_id: Optional[int] = None,
    ) -> ClassificadorBatch:
        """Submete 1 batch Anthropic com N processos do lote.

        Move processos pra EM_CLASSIFICACAO (status PRONTO_PARA_CLASSIFICAR
        ja foi setado pelo pdf_intake; aqui amarra o batch_id).
        """
        if not processos:
            raise ValueError("Nenhum processo pra classificar.")

        # Pre-busca catalogos pra incluir no prompt (1x por batch)
        tipos_pedido = self._fetch_tipos_pedido_ativos()
        master_vinculadas = self._fetch_master_vinculadas()
        categorias_tax = self._fetch_taxonomy_v2()

        batch_requests = []
        processo_ids: list[int] = []
        custom_id_to_processo: dict[str, int] = {}

        for proc in processos:
            user_msg = build_user_message(
                cnj_number=proc.cnj_number,
                capa_json=proc.capa_json,
                integra_json=proc.integra_json,
                tipos_pedido_disponiveis=tipos_pedido,
                master_vinculadas=master_vinculadas,
                categorias_taxonomy=categorias_tax,
            )
            custom_id = f"processo-{proc.id}"
            batch_requests.append(
                self.ai.build_batch_request(
                    custom_id=custom_id,
                    system_prompt=SYSTEM_PROMPT,
                    user_message=user_msg,
                )
            )
            processo_ids.append(proc.id)
            custom_id_to_processo[custom_id] = proc.id

        logger.info(
            "Classificador: submetendo batch lote=%s, processos=%d, modelo=%s",
            lote_id, len(batch_requests), self.ai.model,
        )

        # Cria registro de batch ANTES do submit (rastreabilidade)
        batch = ClassificadorBatch(
            lote_id=lote_id,
            status=BATCH_STATUS_SUBMITTED,
            total_records=len(batch_requests),
            processo_ids=processo_ids,
            batch_metadata={"custom_id_to_processo": custom_id_to_processo},
            model_used=self.ai.model,
            requested_by_email=requested_by_email,
            requested_by_user_id=requested_by_user_id,
            submitted_at=datetime.now(timezone.utc),
        )
        self.db.add(batch)
        self.db.flush()  # garante batch.id

        try:
            response = await self.ai.submit_batch(batch_requests)
        except Exception as exc:
            batch.status = BATCH_STATUS_FAILED
            batch.error_message = f"{type(exc).__name__}: {exc}"
            self.db.commit()
            logger.exception("Classificador: falha no submit do batch")
            raise

        batch.anthropic_batch_id = response.get("id")
        batch.anthropic_status = response.get("processing_status")

        # Amarra processos ao batch + move lote
        for proc in processos:
            proc.classification_batch_id = batch.id
            proc.error_message = None
            # status PRONTO_PARA_CLASSIFICAR fica — quando o batch terminar
            # e apply_batch_results rodar, vira CLASSIFICADO

        # Move lote pra CLASSIFICANDO
        lote = self.db.query(ClassificadorLote).filter(
            ClassificadorLote.id == lote_id
        ).first()
        if lote:
            lote.status = LOTE_STATUS_CLASSIFYING
            lote.classificacao_started_at = datetime.now(timezone.utc)

        self.db.commit()
        self.db.refresh(batch)

        logger.info(
            "Classificador: batch criado local_id=%s anthropic_id=%s",
            batch.id, batch.anthropic_batch_id,
        )
        return batch

    # ──────────────────────────────────────────────────────────────────
    # Polling
    # ──────────────────────────────────────────────────────────────────

    async def refresh_batch_status(
        self, batch: ClassificadorBatch
    ) -> ClassificadorBatch:
        """Consulta status atual e atualiza contadores + results_url."""
        if not batch.anthropic_batch_id:
            raise ValueError(f"Batch {batch.id} sem anthropic_batch_id.")

        try:
            data = await self.ai.get_batch_status(batch.anthropic_batch_id)
        except Exception as exc:
            logger.warning("Classificador: falha polling batch %s: %s", batch.id, exc)
            raise

        batch.anthropic_status = data.get("processing_status")
        counts = data.get("request_counts", {}) or {}
        batch.succeeded_count = counts.get("succeeded", 0)
        batch.errored_count = counts.get("errored", 0)
        batch.expired_count = counts.get("expired", 0)
        batch.canceled_count = counts.get("canceled", 0)

        if data.get("processing_status") == ANTHROPIC_STATUS_ENDED:
            batch.results_url = data.get("results_url")
            if batch.status in (BATCH_STATUS_SUBMITTED, BATCH_STATUS_IN_PROGRESS):
                batch.status = BATCH_STATUS_READY
            if not batch.ended_at:
                ended_at_str = data.get("ended_at")
                if ended_at_str:
                    try:
                        batch.ended_at = datetime.fromisoformat(
                            ended_at_str.replace("Z", "+00:00")
                        )
                    except Exception:
                        batch.ended_at = datetime.now(timezone.utc)
                else:
                    batch.ended_at = datetime.now(timezone.utc)
        else:
            if batch.status == BATCH_STATUS_SUBMITTED:
                batch.status = BATCH_STATUS_IN_PROGRESS

        self.db.commit()
        self.db.refresh(batch)
        return batch

    # ──────────────────────────────────────────────────────────────────
    # Apply
    # ──────────────────────────────────────────────────────────────────

    async def apply_batch_results(self, batch: ClassificadorBatch) -> dict:
        """Baixa JSONL e materializa nos ClassificadorProcesso."""
        if not batch.results_url:
            await self.refresh_batch_status(batch)
            if not batch.results_url:
                raise ValueError(
                    f"Batch {batch.id} ainda nao tem results_url. "
                    f"Status: {batch.anthropic_status}"
                )

        logger.info(
            "Classificador: baixando resultados batch=%s (%d itens)",
            batch.anthropic_batch_id, batch.total_records,
        )
        results = await self.ai.get_batch_results(batch.results_url)

        succeeded = 0
        failed = 0
        skipped = 0

        for item in results:
            custom_id = item.get("custom_id") or ""
            processo_id = self._processo_id_from_custom(custom_id)
            if processo_id is None:
                skipped += 1
                continue

            proc = (
                self.db.query(ClassificadorProcesso)
                .filter(ClassificadorProcesso.id == processo_id)
                .first()
            )
            if not proc:
                skipped += 1
                continue

            try:
                response_obj = self._extract_response(item)
            except Exception as exc:
                err_msg = str(exc)[:1000]
                logger.warning(
                    "Classificador: falha extract response proc=%s: %s",
                    processo_id, exc,
                )
                proc.status = PROC_STATUS_ERROR_CLASSIFICATION
                proc.error_message = err_msg
                failed += 1
                continue

            # Materializa
            try:
                self._materialize(proc, response_obj)
                succeeded += 1
            except Exception as exc:
                logger.exception(
                    "Classificador: falha materialize proc=%s: %s", processo_id, exc,
                )
                proc.status = PROC_STATUS_ERROR_CLASSIFICATION
                proc.error_message = f"materialize: {type(exc).__name__}: {exc}"
                failed += 1

        # Atualiza batch
        batch.status = BATCH_STATUS_APPLIED
        batch.applied_at = datetime.now(timezone.utc)
        self.db.commit()

        # Atualiza lote — se todos os processos terminaram, lote vai pra CLASSIFICADO
        lote = (
            self.db.query(ClassificadorLote)
            .filter(ClassificadorLote.id == batch.lote_id)
            .first()
        )
        if lote:
            self._update_lote_aggregates(lote)
            # Move lote pra CLASSIFICADO se nao tem mais processos pendentes
            pending = (
                self.db.query(ClassificadorProcesso)
                .filter(ClassificadorProcesso.lote_id == lote.id)
                .filter(ClassificadorProcesso.status == PROC_STATUS_READY)
                .count()
            )
            if pending == 0:
                lote.status = LOTE_STATUS_CLASSIFIED
                lote.classificacao_finished_at = datetime.now(timezone.utc)
            self.db.commit()

            # Dispara webhook callback se lote transicionou pra CLASSIFICADO
            # (fire-and-forget em thread separada — nao bloqueia)
            if lote.status == LOTE_STATUS_CLASSIFIED:
                try:
                    from app.services.classificador.webhook import (
                        send_lote_classified_webhook,
                    )
                    send_lote_classified_webhook(lote.id)
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "Classificador.runner: falha disparando webhook lote=%s",
                        lote.id,
                    )

        logger.info(
            "Classificador: apply concluido batch=%s succeeded=%d failed=%d skipped=%d",
            batch.id, succeeded, failed, skipped,
        )
        return {
            "succeeded": succeeded,
            "failed": failed,
            "skipped": skipped,
        }

    # ──────────────────────────────────────────────────────────────────
    # Internals
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _processo_id_from_custom(custom_id: str) -> Optional[int]:
        if not custom_id.startswith("processo-"):
            return None
        try:
            return int(custom_id.split("-", 1)[1])
        except (ValueError, IndexError):
            return None

    def _extract_response(
        self, batch_item: dict[str, Any]
    ) -> ClassificadorClassificationResponse:
        """Extrai JSON do item do batch + valida via Pydantic."""
        result = batch_item.get("result", {})
        result_type = result.get("type")
        if result_type != "succeeded":
            error_info = result.get("error", {}) or {}
            msg = error_info.get("message") or f"type={result_type}"
            raise ValueError(f"Item nao processado: {msg}")

        message = result.get("message", {}) or {}
        content_blocks = message.get("content", [])
        if not content_blocks:
            raise ValueError("Mensagem sem conteudo.")

        raw_text = content_blocks[0].get("text", "")
        # Remove fences se vier
        text = raw_text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines).strip()

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSON invalido: {text[:200]}") from exc

        try:
            return ClassificadorClassificationResponse.model_validate(parsed)
        except ValidationError as exc:
            raise ValueError(f"Schema invalido: {exc}") from exc

    def _materialize(
        self,
        proc: ClassificadorProcesso,
        resp: ClassificadorClassificationResponse,
    ) -> None:
        """Persiste a resposta da IA no ClassificadorProcesso."""
        # Guarda response cruo (auditoria + rerun)
        proc.classificacao_response_json = resp.model_dump(mode="json")

        # Classificacao taxonomy (resolve IDs por nome)
        if resp.categoria_nome:
            cat = (
                self.db.query(ClassificationCategory)
                .filter(ClassificationCategory.name == resp.categoria_nome)
                .filter(ClassificationCategory.taxonomy_version == "v2")
                .filter(ClassificationCategory.is_active == True)  # noqa: E712
                .first()
            )
            if cat:
                proc.categoria_id = cat.id
                if resp.subcategoria_nome:
                    sub = (
                        self.db.query(ClassificationSubcategory)
                        .filter(ClassificationSubcategory.category_id == cat.id)
                        .filter(ClassificationSubcategory.name == resp.subcategoria_nome)
                        .filter(ClassificationSubcategory.taxonomy_version == "v2")
                        .filter(ClassificationSubcategory.is_active == True)  # noqa: E712
                        .first()
                    )
                    if sub:
                        proc.subcategoria_id = sub.id

        proc.polo = resp.polo
        proc.natureza_processo = resp.natureza_processo
        proc.produto = resp.produto

        # Agregados
        proc.valor_estimado = resp.valor_estimado_total
        proc.pcond_sugerido = resp.pcond_total
        proc.prob_exito = resp.prob_exito_global
        proc.analise_estrategica = resp.analise_estrategica
        # confianca: high/media/baixa -> 1.0/0.66/0.33
        confianca_map = {"alta": 1.0, "media": 0.66, "baixa": 0.33}
        proc.confianca = confianca_map.get(resp.confianca_geral, 1.0)
        proc.justificativa = resp.observacoes

        # Patrocinio
        if resp.patrocinio:
            proc.patrocinio_json = resp.patrocinio.model_dump(mode="json")

        # Contestacao existente — espelho do PI
        if resp.contestacao_existente:
            proc.contestacao_existente_json = resp.contestacao_existente.model_dump(
                mode="json"
            )

        # Pedidos — limpa antigos + recria
        for old in list(proc.pedidos):
            self.db.delete(old)
        for ped in resp.pedidos:
            new_ped = ClassificadorPedido(
                processo_id=proc.id,
                tipo_pedido=ped.tipo_pedido,
                natureza=ped.natureza,
                valor_indicado=ped.valor_indicado,
                valor_estimado=ped.valor_estimado,
                fundamentacao_valor=ped.fundamentacao_valor,
                probabilidade_perda=ped.probabilidade_perda,
                aprovisionamento=ped.aprovisionamento,
                fundamentacao_risco=ped.fundamentacao_risco,
            )
            self.db.add(new_ped)

        proc.status = PROC_STATUS_CLASSIFIED
        proc.data_classificacao = datetime.now(timezone.utc)
        proc.error_message = None

    def _update_lote_aggregates(self, lote: ClassificadorLote) -> None:
        """Recalcula contadores agregados do lote (valor_total, pcond_total)."""
        from sqlalchemy import func

        result = (
            self.db.query(
                func.count(ClassificadorProcesso.id),
                func.count(ClassificadorProcesso.id).filter(
                    ClassificadorProcesso.status == PROC_STATUS_CLASSIFIED
                ),
                func.count(ClassificadorProcesso.id).filter(
                    ClassificadorProcesso.status == PROC_STATUS_ERROR_CLASSIFICATION
                ),
                func.sum(ClassificadorProcesso.valor_estimado),
                func.sum(ClassificadorProcesso.pcond_sugerido),
                func.avg(ClassificadorProcesso.prob_exito),
            )
            .filter(ClassificadorProcesso.lote_id == lote.id)
            .first()
        )
        if result:
            (total, classified, errored, val_total, pcond_total, prob_avg) = result
            lote.total_processos_classificados = classified or 0
            lote.total_processos_com_erro = errored or 0
            lote.valor_total_estimado = val_total
            lote.pcond_total = pcond_total
            lote.prob_exito_medio = prob_avg

    # ── Catalogos pra user message ────────────────────────────────────

    def _fetch_tipos_pedido_ativos(self) -> list[dict]:
        """Tipos de pedido ativos (reusa tabela do PI)."""
        from app.models.prazo_inicial_tipo_pedido import PrazoInicialTipoPedido

        rows = (
            self.db.query(PrazoInicialTipoPedido)
            .filter(PrazoInicialTipoPedido.is_active == True)  # noqa: E712
            .order_by(PrazoInicialTipoPedido.codigo)
            .all()
        )
        return [
            {"codigo": r.codigo, "nome": r.nome, "naturezas": r.naturezas}
            for r in rows
        ]

    def _fetch_master_vinculadas(self) -> list[dict]:
        """Vinculadas Master ativas (reusa tabela do PI). Campo: `ativo` (nao `is_active`)."""
        from app.models.master_vinculada import MasterVinculada

        rows = (
            self.db.query(MasterVinculada)
            .filter(MasterVinculada.ativo == True)  # noqa: E712
            .order_by(MasterVinculada.nome)
            .all()
        )
        return [
            {
                "cnpj": r.cnpj,
                "nome": r.nome,
                "estado": getattr(r, "estado", None),
            }
            for r in rows
        ]

    def _fetch_taxonomy_v2(self) -> list[dict]:
        """Categorias v2 + subcategorias (pra IA escolher)."""
        cats = (
            self.db.query(ClassificationCategory)
            .filter(ClassificationCategory.taxonomy_version == "v2")
            .filter(ClassificationCategory.is_active == True)  # noqa: E712
            .order_by(ClassificationCategory.display_order)
            .all()
        )
        out = []
        for cat in cats:
            subs = (
                self.db.query(ClassificationSubcategory)
                .filter(ClassificationSubcategory.category_id == cat.id)
                .filter(ClassificationSubcategory.taxonomy_version == "v2")
                .filter(ClassificationSubcategory.is_active == True)  # noqa: E712
                .order_by(ClassificationSubcategory.display_order)
                .all()
            )
            out.append({
                "nome": cat.name,
                "polo_scope": getattr(cat, "polo_scope", None),
                "subcategorias": [{"nome": s.name} for s in subs],
            })
        return out


__all__ = ["ClassificadorBatchClassifier", "ANTHROPIC_STATUS_ENDED"]
