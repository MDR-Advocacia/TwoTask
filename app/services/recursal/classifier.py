"""
Orquestra a Análise Recursal em lote via Anthropic Batches API.

Espelha `PrazosIniciaisBatchClassifier` (submit → refresh → apply), mas:
  - input: capa + íntegra já estruturadas (reusa o extractor mecânico);
  - output: 1 veredito (`RecursalVerdict`) por processo, persistido nas
    colunas da própria `analise_recursal`;
  - custo do preparo é calculado FORA da IA (lookup determinístico).

Reusa `AnthropicClassifierClient` (mesmo cliente HTTP do classifier de
publicações/prazos), com o modelo Sonnet configurado em settings.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, List, Optional

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.analise_recursal import (
    RCR_BATCH_STATUS_APPLIED,
    RCR_BATCH_STATUS_FAILED,
    RCR_BATCH_STATUS_IN_PROGRESS,
    RCR_BATCH_STATUS_READY,
    RCR_BATCH_STATUS_SUBMITTED,
    RCR_STATUS_ANALISADO,
    RCR_STATUS_EM_ANALISE,
    RCR_STATUS_ERRO,
    RCR_STATUS_RECEBIDO,
    AnaliseRecursal,
    AnaliseRecursalBatch,
)
from app.services.classifier.ai_client import AnthropicClassifierClient
from app.services.recursal.cost_calculator import calcular_custo, derive_uf_from_cnj
from app.services.recursal.produtos import normalize_produto
from app.services.recursal.prompts import SYSTEM_PROMPT, build_user_message
from app.services.recursal.schema import RecursalVerdict

logger = logging.getLogger(__name__)

ANTHROPIC_STATUS_ENDED = "ended"


class RecursalBatchClassifier:
    """Orquestra a análise recursal em lote."""

    def __init__(self, db: Session, ai_client: Optional[AnthropicClassifierClient] = None):
        self.db = db
        self.ai = ai_client or AnthropicClassifierClient(
            model=settings.recursal_classifier_model,
            max_tokens=settings.recursal_classifier_max_tokens,
        )

    # ── Submit ────────────────────────────────────────────────────────

    def collect_pending(self, limit: Optional[int] = None) -> List[AnaliseRecursal]:
        """Análises em RECEBIDO com íntegra preenchida, por ordem de chegada."""
        query = (
            self.db.query(AnaliseRecursal)
            .filter(AnaliseRecursal.status == RCR_STATUS_RECEBIDO)
            .filter(AnaliseRecursal.integra_json.isnot(None))
            .order_by(AnaliseRecursal.created_at)
        )
        if limit:
            query = query.limit(limit)
        return query.all()

    async def submit_batch(
        self,
        analises: List[AnaliseRecursal],
        requested_by_email: Optional[str] = None,
    ) -> AnaliseRecursalBatch:
        """Monta o lote (1 item por análise) e envia para a Anthropic."""
        if not analises:
            raise ValueError("Nenhuma análise para processar.")

        batch_requests = []
        analise_ids: list[int] = []
        custom_id_to_analise: dict[str, int] = {}

        for an in analises:
            user_msg = build_user_message(
                processo_numero=an.processo_numero,
                cnj_number=an.cnj_number,
                capa_json=an.capa_json,
                integra_json=an.integra_json,
            )
            custom_id = f"recursal-{an.id}"
            batch_requests.append(
                self.ai.build_batch_request(
                    custom_id=custom_id,
                    system_prompt=SYSTEM_PROMPT,
                    user_message=user_msg,
                )
            )
            analise_ids.append(an.id)
            custom_id_to_analise[custom_id] = an.id

        logger.info(
            "Enviando batch de análise recursal: %d processos (solicitante=%s, modelo=%s)",
            len(batch_requests),
            requested_by_email or "-",
            self.ai.model,
        )

        try:
            response = await self.ai.submit_batch(batch_requests)
        except Exception as exc:
            batch = AnaliseRecursalBatch(
                status=RCR_BATCH_STATUS_FAILED,
                total_records=len(batch_requests),
                analise_ids=analise_ids,
                batch_metadata={"custom_id_to_analise": custom_id_to_analise},
                model_used=self.ai.model,
                requested_by_email=requested_by_email,
            )
            self.db.add(batch)
            self.db.commit()
            self.db.refresh(batch)
            logger.exception("Falha ao submeter batch de análise recursal: %s", exc)
            raise

        batch = AnaliseRecursalBatch(
            anthropic_batch_id=response.get("id"),
            anthropic_status=response.get("processing_status"),
            status=RCR_BATCH_STATUS_SUBMITTED,
            total_records=len(batch_requests),
            analise_ids=analise_ids,
            batch_metadata={"custom_id_to_analise": custom_id_to_analise},
            model_used=self.ai.model,
            requested_by_email=requested_by_email,
            submitted_at=datetime.now(timezone.utc),
        )
        self.db.add(batch)
        self.db.flush()

        for an in analises:
            an.status = RCR_STATUS_EM_ANALISE
            an.analysis_batch_id = batch.id
            an.error_message = None

        self.db.commit()
        self.db.refresh(batch)
        logger.info(
            "Batch recursal criado: local_id=%s, anthropic_id=%s, processos=%d",
            batch.id, batch.anthropic_batch_id, batch.total_records,
        )
        return batch

    # ── Status & polling ──────────────────────────────────────────────

    async def refresh_batch_status(
        self, batch: AnaliseRecursalBatch
    ) -> AnaliseRecursalBatch:
        if not batch.anthropic_batch_id:
            raise ValueError(f"Batch {batch.id} sem anthropic_batch_id.")

        data = await self.ai.get_batch_status(batch.anthropic_batch_id)
        batch.anthropic_status = data.get("processing_status")

        counts = data.get("request_counts", {}) or {}
        batch.succeeded_count = counts.get("succeeded", 0)
        batch.errored_count = counts.get("errored", 0)
        batch.expired_count = counts.get("expired", 0)
        batch.canceled_count = counts.get("canceled", 0)

        if data.get("processing_status") == ANTHROPIC_STATUS_ENDED:
            batch.results_url = data.get("results_url")
            if batch.status in (RCR_BATCH_STATUS_SUBMITTED, RCR_BATCH_STATUS_IN_PROGRESS):
                batch.status = RCR_BATCH_STATUS_READY
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
            if batch.status == RCR_BATCH_STATUS_SUBMITTED:
                batch.status = RCR_BATCH_STATUS_IN_PROGRESS

        self.db.commit()
        self.db.refresh(batch)
        return batch

    # ── Apply ─────────────────────────────────────────────────────────

    async def apply_batch_results(self, batch: AnaliseRecursalBatch) -> dict:
        if not batch.results_url:
            await self.refresh_batch_status(batch)
            if not batch.results_url:
                raise ValueError(
                    f"Batch {batch.id} ainda não tem results_url. "
                    f"Status Anthropic: {batch.anthropic_status}"
                )

        logger.info(
            "Baixando resultados do batch recursal %s (%d itens)",
            batch.anthropic_batch_id, batch.total_records,
        )
        results = await self.ai.get_batch_results(batch.results_url)

        succeeded = 0
        failed = 0
        skipped = 0

        for item in results:
            custom_id = item.get("custom_id") or ""
            analise_id = self._analise_id_from_custom(custom_id)
            if analise_id is None:
                skipped += 1
                continue

            an = (
                self.db.query(AnaliseRecursal)
                .filter(AnaliseRecursal.id == analise_id)
                .first()
            )
            if not an:
                skipped += 1
                continue

            try:
                verdict = self._extract_verdict(item)
            except Exception as exc:
                an.status = RCR_STATUS_ERRO
                an.error_message = str(exc)[:1000]
                failed += 1
                logger.warning("Falha ao extrair veredito da análise %s: %s", analise_id, exc)
                continue

            try:
                self._apply_verdict(an, verdict)
                an.status = RCR_STATUS_ANALISADO
                an.error_message = None
                an.analyzed_at = datetime.now(timezone.utc)
                succeeded += 1
            except Exception as exc:
                an.status = RCR_STATUS_ERRO
                an.error_message = f"Falha ao aplicar veredito: {exc}"[:1000]
                failed += 1
                logger.exception("Erro aplicando veredito da análise %s: %s", analise_id, exc)

        self.db.commit()

        batch.status = RCR_BATCH_STATUS_APPLIED
        batch.applied_at = datetime.now(timezone.utc)
        batch.succeeded_count = succeeded
        batch.errored_count = failed
        self.db.commit()

        summary = {
            "succeeded": succeeded,
            "failed": failed,
            "skipped": skipped,
            "total_results": len(results),
        }
        logger.info("Batch recursal %s aplicado: %s", batch.anthropic_batch_id, summary)
        return summary

    def _apply_verdict(self, an: AnaliseRecursal, verdict: RecursalVerdict) -> None:
        """Persiste o veredito + calcula o custo determinístico."""
        # Identificação (cabeçalho do parecer).
        an.nome_autor = verdict.nome_autor
        an.cpf = verdict.cpf
        # Produto: normaliza pro vocabulário controlado. Se a IA mandou um
        # OBJETO (superendividamento/negativação/...) em produto, vira None;
        # nesse caso, se objeto veio vazio, aproveita o texto como objeto.
        produto_norm, _cat = normalize_produto(verdict.produto)
        an.produto = produto_norm
        an.objeto = verdict.objeto or (
            verdict.produto if produto_norm is None else None
        )

        # Decisão + conteúdo do parecer.
        an.resultado_decisao = verdict.resultado_decisao
        an.tipo_decisao = verdict.tipo_decisao
        an.resumo_topicos = verdict.resumo_topicos or None
        an.destaque = verdict.destaque
        an.fundamentacao_juiz = verdict.fundamentacao_juiz
        an.pontos_analise = verdict.pontos_analise or None
        an.probabilidade_reversao = verdict.probabilidade_reversao
        an.recorrer = verdict.recorrer
        an.tipo_recurso = verdict.tipo_recurso
        an.fundamentacao = verdict.fundamentacao
        an.valor_causa = verdict.valor_causa
        an.valor_condenacao = verdict.valor_condenacao
        an.data_intimacao = verdict.data_intimacao
        # Prazo fatal DETERMINÍSTICO: +N dias úteis a partir da intimação
        # (15 apelação/agravo/RESP/RE; 5 embargos de declaração).
        an.prazo_fatal = self._calc_prazo_fatal(
            verdict.data_intimacao, verdict.tipo_recurso, verdict.prazo_fatal
        )
        an.confianca = verdict.confianca

        # UF: respeita a que o operador já setou; senão deriva do CNJ.
        uf = an.uf or derive_uf_from_cnj(an.cnj_number)
        if uf and not an.uf:
            an.uf = uf
        # Tribunal estadual (TJ + UF) — usado no assunto do parecer.
        if uf and not an.tribunal:
            an.tribunal = f"TJ{uf}"

        custo, detalhe = calcular_custo(
            self.db,
            uf=uf,
            tipo_recurso=verdict.tipo_recurso,
            valor_causa=verdict.valor_causa,
        )
        an.custo_estimado = custo
        an.custo_detalhe = detalhe

    # ── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _calc_prazo_fatal(data_intimacao, tipo_recurso, fallback):
        """+N dias úteis a partir da intimação (feriados nacionais). Sem
        intimação, cai no que a IA achou pronto (fallback)."""
        if data_intimacao is None:
            return fallback
        from app.services.prazos_iniciais.prazo_calculator import add_business_days

        dias = 5 if tipo_recurso == "EMB_DECLARACAO" else 15
        try:
            return add_business_days(data_intimacao, dias)
        except Exception:
            return fallback

    @staticmethod
    def _analise_id_from_custom(custom_id: str) -> Optional[int]:
        if not custom_id:
            return None
        try:
            if custom_id.startswith("recursal-"):
                return int(custom_id.split("-", 1)[1])
            return int(custom_id)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _strip_code_fence(text: str) -> str:
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines).strip()
        return text

    @classmethod
    def _extract_verdict(cls, batch_result: dict[str, Any]) -> RecursalVerdict:
        result = batch_result.get("result", {}) or {}
        if result.get("type") != "succeeded":
            error_info = result.get("error") or {}
            msg = error_info.get("message") or f"type={result.get('type')}"
            raise Exception(f"Item não processado: {msg}")

        message = result.get("message") or {}
        content_blocks = message.get("content") or []
        if not content_blocks:
            raise Exception("Mensagem sem conteúdo.")

        raw_text = content_blocks[0].get("text", "") or ""
        clean_text = cls._strip_code_fence(raw_text)
        # A IA às vezes anexa prosa antes/depois do JSON — reusa o
        # extrator balanceado do ai_client.
        extracted = AnthropicClassifierClient._extract_first_json(clean_text)
        if extracted is not None:
            clean_text = extracted

        try:
            parsed = json.loads(clean_text)
        except json.JSONDecodeError as exc:
            stop_reason = message.get("stop_reason")
            if stop_reason == "max_tokens":
                raise Exception(
                    "Resposta truncada (max_tokens) — aumente recursal_classifier_max_tokens."
                ) from exc
            raise Exception(f"Resposta não é JSON válido: {clean_text[:200]}") from exc

        try:
            return RecursalVerdict.model_validate(parsed)
        except ValidationError as exc:
            raise Exception(
                f"Veredito não casa com o schema: {exc.errors()[:3]}"
            ) from exc

    # ── Consultas auxiliares ──────────────────────────────────────────

    def get_batch(self, batch_id: int) -> Optional[AnaliseRecursalBatch]:
        return (
            self.db.query(AnaliseRecursalBatch)
            .filter(AnaliseRecursalBatch.id == batch_id)
            .first()
        )

    def list_batches(
        self, limit: int = 50, offset: int = 0
    ) -> List[AnaliseRecursalBatch]:
        return (
            self.db.query(AnaliseRecursalBatch)
            .order_by(AnaliseRecursalBatch.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

    def count_batches(self) -> int:
        return self.db.query(AnaliseRecursalBatch).count()

    @staticmethod
    def batch_to_dict(batch: AnaliseRecursalBatch) -> dict:
        return {
            "id": batch.id,
            "anthropic_batch_id": batch.anthropic_batch_id,
            "status": batch.status,
            "anthropic_status": batch.anthropic_status,
            "total_records": batch.total_records,
            "succeeded_count": batch.succeeded_count or 0,
            "errored_count": batch.errored_count or 0,
            "model_used": batch.model_used,
            "requested_by_email": batch.requested_by_email,
            "analise_ids": batch.analise_ids,
            "created_at": batch.created_at.isoformat() if batch.created_at else None,
            "submitted_at": batch.submitted_at.isoformat() if batch.submitted_at else None,
            "ended_at": batch.ended_at.isoformat() if batch.ended_at else None,
            "applied_at": batch.applied_at.isoformat() if batch.applied_at else None,
        }
