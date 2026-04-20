"""
Serviço de classificação em lote do fluxo "Agendar Prazos Iniciais".

Espelha `app/services/publication_batch_classifier.py`, mas adaptado pra:
  - input: capa + íntegra de processo (vindas da API externa) em vez de
    texto plano de publicação;
  - modelo: Claude Sonnet (não Haiku) — classificação mais sensível;
  - output: N sugestões em `prazo_inicial_sugestao` por intake (1 por
    bloco com `aplica=True`), em vez de 1 categoria por registro;
  - parser próprio (Pydantic), porque o schema é diferente do das
    publicações e não tem campo `categoria`.

Fluxo:
  1. submit_pending() → coleta intakes em PRONTO_PARA_CLASSIFICAR e cria
     batch na Anthropic.
  2. refresh_batch_status() → polling do batch (igual ao de publicações).
  3. apply_batch_results() → baixa o JSONL, parseia cada item via
     `PrazoInicialClassificationResponse`, materializa N sugestões por
     intake e move o intake pra CLASSIFICADO ou ERRO_CLASSIFICACAO.

`task_type_id` / `task_subtype_id` ficam NULL — o mapeamento taxonômico
será feito em sessão dedicada (ver memória
`project_taxonomia_prazos_iniciais_pendente.md`).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, List, Optional

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.prazo_inicial import (
    INTAKE_STATUS_CLASSIFICATION_ERROR,
    INTAKE_STATUS_CLASSIFIED,
    INTAKE_STATUS_IN_CLASSIFICATION,
    INTAKE_STATUS_READY_TO_CLASSIFY,
    PIN_BATCH_STATUS_APPLIED,
    PIN_BATCH_STATUS_FAILED,
    PIN_BATCH_STATUS_IN_PROGRESS,
    PIN_BATCH_STATUS_READY,
    PIN_BATCH_STATUS_SUBMITTED,
    PrazoInicialBatch,
    PrazoInicialIntake,
    PrazoInicialSugestao,
)
from app.services.classifier.ai_client import AnthropicClassifierClient
from app.services.classifier.prazos_iniciais_prompts import (
    SYSTEM_PROMPT,
    build_user_message,
)
from app.services.classifier.prazos_iniciais_schema import (
    TIPO_PRAZO_AUDIENCIA,
    TIPO_PRAZO_CONTESTAR,
    TIPO_PRAZO_JULGAMENTO,
    TIPO_PRAZO_LIMINAR,
    TIPO_PRAZO_MANIFESTACAO_AVULSA,
    TIPO_PRAZO_SEM_DETERMINACAO,
    BlocoAudiencia,
    BlocoContestar,
    BlocoJulgamento,
    BlocoLiminar,
    BlocoManifestacaoAvulsa,
    PrazoInicialClassificationResponse,
)
from app.services.prazos_iniciais.prazo_calculator import calcular_prazo_seguro

logger = logging.getLogger(__name__)


# Status retornado pela Anthropic quando o batch terminou (mesma constante
# usada no fluxo de publicações).
ANTHROPIC_STATUS_ENDED = "ended"


class PrazosIniciaisBatchClassifier:
    """Orquestra a classificação em lote de intakes via Anthropic Batch API."""

    def __init__(self, db: Session, ai_client: Optional[AnthropicClassifierClient] = None):
        self.db = db
        # Override do modelo/limite via settings dedicados do fluxo de prazos.
        self.ai = ai_client or AnthropicClassifierClient(
            model=settings.prazos_iniciais_classifier_model,
            max_tokens=settings.prazos_iniciais_classifier_max_tokens,
        )

    # ──────────────────────────────────────────────────────────────────
    # Submit
    # ──────────────────────────────────────────────────────────────────

    def collect_pending_intakes(
        self, limit: Optional[int] = None
    ) -> List[PrazoInicialIntake]:
        """
        Retorna intakes em status PRONTO_PARA_CLASSIFICAR (com capa e
        íntegra preenchidas), em ordem de chegada.
        """
        query = (
            self.db.query(PrazoInicialIntake)
            .filter(PrazoInicialIntake.status == INTAKE_STATUS_READY_TO_CLASSIFY)
            .filter(PrazoInicialIntake.capa_json.isnot(None))
            .filter(PrazoInicialIntake.integra_json.isnot(None))
            .order_by(PrazoInicialIntake.received_at)
        )
        if limit:
            query = query.limit(limit)
        return query.all()

    async def submit_batch(
        self,
        intakes: List[PrazoInicialIntake],
        requested_by_email: Optional[str] = None,
    ) -> PrazoInicialBatch:
        """
        Monta o lote (1 item por intake) e envia para a Anthropic Batch API.
        Move os intakes incluídos para EM_CLASSIFICACAO e amarra o
        `classification_batch_id`.
        """
        if not intakes:
            raise ValueError("Nenhum intake para classificar.")

        batch_requests = []
        intake_ids: list[int] = []
        custom_id_to_intake: dict[str, int] = {}

        for intake in intakes:
            user_msg = build_user_message(
                cnj_number=intake.cnj_number,
                capa_json=intake.capa_json,
                integra_json=intake.integra_json,
            )
            custom_id = f"intake-{intake.id}"
            batch_requests.append(
                self.ai.build_batch_request(
                    custom_id=custom_id,
                    system_prompt=SYSTEM_PROMPT,
                    user_message=user_msg,
                )
            )
            intake_ids.append(intake.id)
            custom_id_to_intake[custom_id] = intake.id

        if not batch_requests:
            raise ValueError("Nenhum intake com payload válido.")

        logger.info(
            "Enviando batch de prazos iniciais: %d intakes (solicitante=%s, modelo=%s)",
            len(batch_requests),
            requested_by_email or "-",
            self.ai.model,
        )

        try:
            response = await self.ai.submit_batch(batch_requests)
        except Exception as exc:
            # Persiste registro de falha pra rastreabilidade.
            batch = PrazoInicialBatch(
                status=PIN_BATCH_STATUS_FAILED,
                total_records=len(batch_requests),
                intake_ids=intake_ids,
                batch_metadata={"custom_id_to_intake": custom_id_to_intake},
                model_used=self.ai.model,
                requested_by_email=requested_by_email,
            )
            self.db.add(batch)
            self.db.commit()
            self.db.refresh(batch)
            logger.exception("Falha ao submeter batch de prazos iniciais: %s", exc)
            raise

        batch = PrazoInicialBatch(
            anthropic_batch_id=response.get("id"),
            anthropic_status=response.get("processing_status"),
            status=PIN_BATCH_STATUS_SUBMITTED,
            total_records=len(batch_requests),
            intake_ids=intake_ids,
            batch_metadata={"custom_id_to_intake": custom_id_to_intake},
            model_used=self.ai.model,
            requested_by_email=requested_by_email,
            submitted_at=datetime.now(timezone.utc),
        )
        self.db.add(batch)
        self.db.flush()  # garante batch.id antes de amarrar nos intakes

        # Move intakes para EM_CLASSIFICACAO.
        for intake in intakes:
            intake.status = INTAKE_STATUS_IN_CLASSIFICATION
            intake.classification_batch_id = batch.id
            intake.error_message = None

        self.db.commit()
        self.db.refresh(batch)

        logger.info(
            "Batch criado: local_id=%s, anthropic_id=%s, intakes=%d",
            batch.id,
            batch.anthropic_batch_id,
            batch.total_records,
        )
        return batch

    # ──────────────────────────────────────────────────────────────────
    # Status & polling
    # ──────────────────────────────────────────────────────────────────

    async def refresh_batch_status(
        self, batch: PrazoInicialBatch
    ) -> PrazoInicialBatch:
        """
        Consulta o status atual do batch na Anthropic e atualiza o registro
        local. Não baixa nem aplica resultados — apenas atualiza contadores
        e o `results_url` quando o batch termina.
        """
        if not batch.anthropic_batch_id:
            raise ValueError(f"Batch {batch.id} sem anthropic_batch_id.")

        try:
            data = await self.ai.get_batch_status(batch.anthropic_batch_id)
        except Exception as exc:
            logger.warning("Falha ao consultar batch %s: %s", batch.anthropic_batch_id, exc)
            raise

        batch.anthropic_status = data.get("processing_status")

        counts = data.get("request_counts", {}) or {}
        batch.succeeded_count = counts.get("succeeded", 0)
        batch.errored_count = counts.get("errored", 0)
        batch.expired_count = counts.get("expired", 0)
        batch.canceled_count = counts.get("canceled", 0)

        if data.get("processing_status") == ANTHROPIC_STATUS_ENDED:
            batch.results_url = data.get("results_url")
            if batch.status in (PIN_BATCH_STATUS_SUBMITTED, PIN_BATCH_STATUS_IN_PROGRESS):
                batch.status = PIN_BATCH_STATUS_READY
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
            if batch.status == PIN_BATCH_STATUS_SUBMITTED:
                batch.status = PIN_BATCH_STATUS_IN_PROGRESS

        self.db.commit()
        self.db.refresh(batch)
        return batch

    # ──────────────────────────────────────────────────────────────────
    # Apply results
    # ──────────────────────────────────────────────────────────────────

    async def apply_batch_results(self, batch: PrazoInicialBatch) -> dict:
        """
        Baixa os resultados do batch, parseia o JSON de cada intake,
        materializa as sugestões e atualiza o status do intake.
        """
        if not batch.results_url:
            await self.refresh_batch_status(batch)
            if not batch.results_url:
                raise ValueError(
                    f"Batch {batch.id} ainda não tem results_url. "
                    f"Status Anthropic: {batch.anthropic_status}"
                )

        logger.info(
            "Baixando resultados do batch de prazos iniciais %s (%d itens)",
            batch.anthropic_batch_id,
            batch.total_records,
        )
        results = await self.ai.get_batch_results(batch.results_url)

        succeeded = 0
        failed = 0
        skipped = 0
        total_sugestoes = 0

        for item in results:
            custom_id = item.get("custom_id") or ""
            intake_id = self._intake_id_from_custom(custom_id)
            if intake_id is None:
                skipped += 1
                logger.warning("Resultado sem custom_id válido: %s", custom_id)
                continue

            intake = (
                self.db.query(PrazoInicialIntake)
                .filter(PrazoInicialIntake.id == intake_id)
                .first()
            )
            if not intake:
                skipped += 1
                logger.warning("Intake %s não encontrado pra resultado.", intake_id)
                continue

            try:
                response_obj = self._extract_response(item)
            except Exception as exc:
                err_msg = str(exc)[:1000]
                logger.warning(
                    "Falha ao extrair resposta do intake %s: %s", intake_id, exc
                )
                intake.status = INTAKE_STATUS_CLASSIFICATION_ERROR
                intake.error_message = err_msg
                failed += 1
                continue

            # Limpa sugestões antigas (caso seja reprocessamento).
            for old in list(intake.sugestoes):
                self.db.delete(old)

            # Materializa novas sugestões.
            try:
                created = self._materialize_sugestoes(intake, response_obj)
            except Exception as exc:
                err_msg = f"Falha ao materializar sugestões: {exc}"[:1000]
                logger.exception("Erro materializando intake %s: %s", intake_id, exc)
                intake.status = INTAKE_STATUS_CLASSIFICATION_ERROR
                intake.error_message = err_msg
                failed += 1
                continue

            intake.status = INTAKE_STATUS_CLASSIFIED
            intake.error_message = None
            total_sugestoes += created
            succeeded += 1
            logger.debug(
                "Intake %s classificado → %d sugestão(ões) criadas.",
                intake_id, created,
            )

        self.db.commit()

        batch.status = PIN_BATCH_STATUS_APPLIED
        batch.applied_at = datetime.now(timezone.utc)
        batch.succeeded_count = succeeded
        batch.errored_count = failed
        self.db.commit()

        summary = {
            "succeeded": succeeded,
            "failed": failed,
            "skipped": skipped,
            "total_results": len(results),
            "total_sugestoes": total_sugestoes,
        }
        logger.info("Batch %s aplicado: %s", batch.anthropic_batch_id, summary)
        return summary

    # ──────────────────────────────────────────────────────────────────
    # Helpers internos
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _intake_id_from_custom(custom_id: str) -> Optional[int]:
        """Decodifica `intake-<id>` → int. Aceita também id puro como fallback."""
        if not custom_id:
            return None
        try:
            if custom_id.startswith("intake-"):
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
    def _extract_response(
        cls, batch_result: dict[str, Any]
    ) -> PrazoInicialClassificationResponse:
        """
        Extrai e valida o JSON da resposta de um item do batch.
        Levanta Exception se o item não foi bem-sucedido ou se o JSON
        não casa com o schema esperado.
        """
        result = batch_result.get("result", {}) or {}
        result_type = result.get("type")
        if result_type != "succeeded":
            error_info = result.get("error") or {}
            msg = error_info.get("message") or f"type={result_type}"
            raise Exception(f"Item não processado: {msg}")

        message = result.get("message") or {}
        content_blocks = message.get("content") or []
        if not content_blocks:
            raise Exception("Mensagem sem conteúdo.")

        raw_text = content_blocks[0].get("text", "") or ""
        clean_text = cls._strip_code_fence(raw_text)

        try:
            parsed = json.loads(clean_text)
        except json.JSONDecodeError as exc:
            stop_reason = message.get("stop_reason")
            if stop_reason == "max_tokens":
                raise Exception(
                    "Resposta truncada (max_tokens atingido) — aumente "
                    "prazos_iniciais_classifier_max_tokens."
                ) from exc
            raise Exception(
                f"Resposta não é JSON válido: {clean_text[:200]}"
            ) from exc

        try:
            return PrazoInicialClassificationResponse.model_validate(parsed)
        except ValidationError as exc:
            raise Exception(
                f"Resposta não casa com o schema esperado: {exc.errors()[:3]}"
            ) from exc

    def _materialize_sugestoes(
        self,
        intake: PrazoInicialIntake,
        response: PrazoInicialClassificationResponse,
    ) -> int:
        """
        Cria as N sugestões na tabela `prazo_inicial_sugestoes` a partir
        da resposta da IA. Retorna a quantidade criada.

        `task_type_id` / `task_subtype_id` ficam NULL — serão preenchidos
        em sessão dedicada à taxonomia.
        `data_final_calculada` também fica NULL — preenchida pelo
        calculador de prazo (módulo separado).
        """
        confianca = response.confianca_geral
        observacoes = response.observacoes
        criadas = 0

        for tipo_prazo, bloco in response.blocos_aplicaveis():
            sugestao = self._build_sugestao(
                intake_id=intake.id,
                tipo_prazo=tipo_prazo,
                bloco=bloco,
                confianca_geral=confianca,
                observacoes=observacoes,
            )
            self.db.add(sugestao)
            criadas += 1

        return criadas

    @staticmethod
    def _build_sugestao(
        intake_id: int,
        tipo_prazo: str,
        bloco: Any,
        confianca_geral: str,
        observacoes: Optional[str],
    ) -> PrazoInicialSugestao:
        """
        Mapeia um bloco da resposta da IA para uma linha de
        `prazo_inicial_sugestao`. Cada tipo tem campos extras próprios
        (objeto, assunto, audiência) — guardados em `payload_proposto`
        pra revisão humana.
        """
        sugestao = PrazoInicialSugestao(
            intake_id=intake_id,
            tipo_prazo=tipo_prazo,
            confianca=confianca_geral,
            justificativa=getattr(bloco, "justificativa", None) or None,
        )

        payload: dict[str, Any] = {}
        if observacoes:
            payload["observacoes_ia"] = observacoes

        if tipo_prazo == TIPO_PRAZO_SEM_DETERMINACAO:
            # Bloco aqui é a própria response — só registra a flag.
            payload["sem_determinacao"] = True
            sugestao.payload_proposto = payload
            return sugestao

        if tipo_prazo == TIPO_PRAZO_AUDIENCIA and isinstance(bloco, BlocoAudiencia):
            sugestao.audiencia_data = bloco.data
            sugestao.audiencia_hora = bloco.hora
            sugestao.audiencia_link = bloco.link
            sugestao.subtipo = bloco.tipo
            payload["tipo_audiencia"] = bloco.tipo
            payload["endereco"] = bloco.endereco
            payload["link"] = bloco.link
            sugestao.payload_proposto = payload
            return sugestao

        if tipo_prazo == TIPO_PRAZO_JULGAMENTO and isinstance(bloco, BlocoJulgamento):
            # Julgamento não tem prazo no sentido contagem; usamos `data_base`
            # pra registrar a data da sentença/acórdão.
            sugestao.data_base = bloco.data
            sugestao.subtipo = bloco.tipo
            payload["tipo_julgamento"] = bloco.tipo
            sugestao.payload_proposto = payload
            return sugestao

        # Blocos com prazo (Contestar / Liminar / Manifestação Avulsa).
        prazo_dias = getattr(bloco, "prazo_dias", None)
        prazo_tipo = getattr(bloco, "prazo_tipo", None)
        data_base = getattr(bloco, "data_base", None)
        sugestao.prazo_dias = prazo_dias
        sugestao.prazo_tipo = prazo_tipo
        sugestao.data_base = data_base
        sugestao.data_final_calculada = calcular_prazo_seguro(
            data_base, prazo_dias, prazo_tipo
        )

        if isinstance(bloco, BlocoLiminar) and bloco.objeto:
            payload["objeto"] = bloco.objeto
            sugestao.subtipo = (bloco.objeto or "")[:128] or None
        elif isinstance(bloco, BlocoManifestacaoAvulsa) and bloco.assunto:
            payload["assunto"] = bloco.assunto
            sugestao.subtipo = (bloco.assunto or "")[:128] or None
        elif isinstance(bloco, BlocoContestar):
            # Sem campos extras específicos — payload vazio é ok.
            pass

        sugestao.payload_proposto = payload or None
        return sugestao

    # ──────────────────────────────────────────────────────────────────
    # Consultas auxiliares
    # ──────────────────────────────────────────────────────────────────

    def get_batch(self, batch_id: int) -> Optional[PrazoInicialBatch]:
        return (
            self.db.query(PrazoInicialBatch)
            .filter(PrazoInicialBatch.id == batch_id)
            .first()
        )

    def list_batches(self, limit: int = 50) -> List[PrazoInicialBatch]:
        return (
            self.db.query(PrazoInicialBatch)
            .order_by(PrazoInicialBatch.created_at.desc())
            .limit(limit)
            .all()
        )

    @staticmethod
    def batch_to_dict(batch: PrazoInicialBatch) -> dict:
        return {
            "id": batch.id,
            "anthropic_batch_id": batch.anthropic_batch_id,
            "status": batch.status,
            "anthropic_status": batch.anthropic_status,
            "total_records": batch.total_records,
            "succeeded_count": batch.succeeded_count or 0,
            "errored_count": batch.errored_count or 0,
            "expired_count": batch.expired_count or 0,
            "canceled_count": batch.canceled_count or 0,
            "model_used": batch.model_used,
            "requested_by_email": batch.requested_by_email,
            "intake_ids": batch.intake_ids,
            "created_at": batch.created_at.isoformat() if batch.created_at else None,
            "submitted_at": batch.submitted_at.isoformat() if batch.submitted_at else None,
            "ended_at": batch.ended_at.isoformat() if batch.ended_at else None,
            "applied_at": batch.applied_at.isoformat() if batch.applied_at else None,
        }
