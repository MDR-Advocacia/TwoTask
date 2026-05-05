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
    INTAKE_STATUS_AWAITING_TEMPLATE_CONFIG,
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
from app.models.prazo_inicial_pedido import PrazoInicialPedido
from app.models.prazo_inicial_task_template import PrazoInicialTaskTemplate
from app.services.classifier.ai_client import AnthropicClassifierClient
from app.services.classifier.prazos_iniciais_prompts import (
    SYSTEM_PROMPT,
    build_user_message,
)
from app.services.classifier.prazos_iniciais_schema import (
    TIPO_PRAZO_AUDIENCIA,
    TIPO_PRAZO_CONTESTAR,
    TIPO_PRAZO_CONTRARRAZOES,
    TIPO_PRAZO_INDETERMINADO,
    TIPO_PRAZO_JULGAMENTO,
    TIPO_PRAZO_LIMINAR,
    TIPO_PRAZO_MANIFESTACAO_AVULSA,
    TIPO_PRAZO_SEM_DETERMINACAO,
    TIPO_PRAZO_SEM_PRAZO_EM_ABERTO,
    BlocoAudiencia,
    BlocoContestar,
    BlocoContrarrazoes,
    BlocoJulgamento,
    BlocoLiminar,
    BlocoManifestacaoAvulsa,
    PrazoInicialClassificationResponse,
)
from app.services.prazos_iniciais.prazo_calculator import calcular_prazo_seguro
from app.services.prazos_iniciais.template_matching_service import match_templates

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
            user_msg = build_user_message(cnj_number=intake.cnj_number,
                capa_json=intake.capa_json,
                integra_json=intake.integra_json,
                tipos_pedido_disponiveis=self._fetch_tipos_pedido_ativos(),
                master_vinculadas=self._fetch_master_vinculadas(),
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

            # Fase 3c — persiste classificação preliminar no intake.
            # `natureza_processo` entra como filtro no template matching
            # (mais abaixo); `produto` é puramente informativo.
            intake.natureza_processo = response_obj.natureza_processo
            intake.produto = response_obj.produto

            # Info de agravo só faz sentido quando natureza=AGRAVO_INSTRUMENTO.
            # Fora desse ramo, limpa pra não vazar dados de classificações
            # anteriores caso um mesmo intake seja reprocessado.
            if response_obj.natureza_processo == "AGRAVO_INSTRUMENTO" and response_obj.agravo:
                intake.agravo_processo_origem_cnj = response_obj.agravo.processo_origem_cnj
                intake.agravo_decisao_agravada_resumo = response_obj.agravo.decisao_agravada_resumo
            else:
                intake.agravo_processo_origem_cnj = None
                intake.agravo_decisao_agravada_resumo = None

            # Materializa pedidos (Bloco D2) antes das sugestões — um falha
            # não deve impedir a outra, mas a ordem deixa pedidos no banco
            # primeiro pra análise global ficar consistente.
            try:
                self._materialize_pedidos(intake, response_obj)
            except Exception as exc:
                logger.exception(
                    "Erro materializando pedidos do intake %s: %s",
                    intake.id, exc,
                )

            # Analise estratégica global (Bloco E) — texto livre da IA.
            intake.analise_estrategica = response_obj.analise_estrategica

            # Patrocínio (pin018) — análise paralela. Persiste só quando
            # a IA marcou aplicavel=true (polo passivo bate com vinculada
            # Master). Falhas aqui NÃO interrompem o intake — só logam.
            try:
                self._materialize_patrocinio(intake, response_obj)
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "Erro materializando patrocínio do intake %s: %s",
                    intake.id, exc,
                )

            # Precisamos commitar pedidos antes de agregar (senão o
            # flush ainda não gravou). O classifier já usa flush
            # implicito via session; força aqui pra garantir que
            # intake.pedidos reflete os inserts desta iteração.
            try:
                self.db.flush()
                self._compute_intake_globals(intake)
            except Exception as exc:
                logger.exception(
                    "Erro computando agregados globais do intake %s: %s",
                    intake.id, exc,
                )

            # Materializa novas sugestões.
            try:
                mat = self._materialize_sugestoes(intake, response_obj)
            except Exception as exc:
                err_msg = f"Falha ao materializar sugestões: {exc}"[:1000]
                logger.exception("Erro materializando intake %s: %s", intake_id, exc)
                intake.status = INTAKE_STATUS_CLASSIFICATION_ERROR
                intake.error_message = err_msg
                failed += 1
                continue

            created = mat["created"]
            # Se NENHUM bloco casou template (todas as sugestões ficaram
            # com task_subtype_id NULL), trava o intake em
            # AGUARDANDO_CONFIG_TEMPLATE até o operador cadastrar
            # template ou resolver manualmente.
            if mat["blocks_with_templates"] == 0 and created > 0:
                intake.status = INTAKE_STATUS_AWAITING_TEMPLATE_CONFIG
            else:
                intake.status = INTAKE_STATUS_CLASSIFIED
            intake.error_message = None
            total_sugestoes += created
            succeeded += 1
            logger.debug(
                "Intake %s %s → %d sugestão(ões) criadas (%d com template, %d sem).",
                intake_id,
                intake.status,
                created,
                mat["blocks_with_templates"],
                mat["blocks_without_templates"],
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



    def _materialize_patrocinio(
        self, intake, response_obj
    ) -> None:
        """
        Cria/atualiza o registro `prazo_inicial_patrocinio` 1:1 com o
        intake quando a IA marcou `patrocinio.aplicavel=true`. Quando
        false, REMOVE o registro existente (caso seja reprocessamento
        e a vinculada saiu do polo passivo) — mantém o estado coerente
        com a última classificação.
        """
        from app.models.prazo_inicial_patrocinio import (
            PATROCINIO_DECISOES_VALIDAS,
            PATROCINIO_NATUREZAS_VALIDAS,
            PATROCINIO_REVIEW_PENDING,
            PrazoInicialPatrocinio,
        )

        patrocinio_resp = getattr(response_obj, "patrocinio", None)
        existing = (
            self.db.query(PrazoInicialPatrocinio)
            .filter(PrazoInicialPatrocinio.intake_id == intake.id)
            .first()
        )

        if patrocinio_resp is None or not patrocinio_resp.aplicavel:
            # Reprocessamento que não bate mais com vinculada — limpa
            # o registro pra não ficar dado obsoleto.
            if existing is not None:
                self.db.delete(existing)
            return

        decisao = patrocinio_resp.decisao
        if decisao not in PATROCINIO_DECISOES_VALIDAS:
            logger.warning(
                "patrocinio: decisão inválida %r no intake %s — pulando.",
                decisao, intake.id,
            )
            return

        natureza = patrocinio_resp.natureza_acao
        if natureza is not None and natureza not in PATROCINIO_NATUREZAS_VALIDAS:
            natureza = None  # IA emitiu valor fora do enum — ignora

        if existing is None:
            existing = PrazoInicialPatrocinio(
                intake_id=intake.id,
                review_status=PATROCINIO_REVIEW_PENDING,
            )
            self.db.add(existing)
        else:
            # Reprocessamento — reseta status pra pendente porque os
            # campos da IA foram regenerados.
            existing.review_status = PATROCINIO_REVIEW_PENDING
            existing.reviewed_by_user_id = None
            existing.reviewed_by_email = None
            existing.reviewed_by_name = None
            existing.reviewed_at = None

        existing.decisao = decisao
        existing.outro_escritorio_nome = patrocinio_resp.outro_escritorio_nome
        existing.outro_advogado_nome = patrocinio_resp.outro_advogado_nome
        existing.outro_advogado_oab = patrocinio_resp.outro_advogado_oab
        existing.outro_advogado_data_habilitacao = (
            patrocinio_resp.outro_advogado_data_habilitacao
        )
        existing.suspeita_devolucao = bool(patrocinio_resp.suspeita_devolucao)
        existing.motivo_suspeita = patrocinio_resp.motivo_suspeita
        existing.natureza_acao = natureza
        existing.polo_passivo_confirmado = bool(
            patrocinio_resp.polo_passivo_confirmado
        )
        existing.polo_passivo_observacao = patrocinio_resp.polo_passivo_observacao
        existing.confianca = patrocinio_resp.confianca
        existing.fundamentacao = patrocinio_resp.fundamentacao


    def _fetch_master_vinculadas(self) -> list[dict]:
        """
        Lista das empresas vinculadas Master ATIVAS — entregue ao Sonnet
        como gatilho da análise de patrocínio. Quando algum CNPJ desta
        lista aparece no polo passivo, a IA preenche `patrocinio.aplicavel
        = true` + decisão.
        """
        from app.models.master_vinculada import MasterVinculada
        rows = (
            self.db.query(MasterVinculada)
            .filter(MasterVinculada.ativo.is_(True))
            .order_by(MasterVinculada.cnpj.asc())
            .all()
        )
        return [
            {"cnpj": r.cnpj, "nome": r.nome, "estado": r.estado}
            for r in rows
        ]


    def _fetch_tipos_pedido_ativos(self) -> list[dict]:
        """
        Busca os tipos de pedido ativos pra entregar ao Sonnet como
        contexto — garante que a IA escolhe apenas dentre os códigos
        cadastrados na tabela (operador pode desativar via admin).
        """
        from app.models.prazo_inicial_tipo_pedido import PrazoInicialTipoPedido
        rows = (
            self.db.query(PrazoInicialTipoPedido)
            .filter(PrazoInicialTipoPedido.is_active.is_(True))
            .order_by(
                PrazoInicialTipoPedido.display_order.asc(),
                PrazoInicialTipoPedido.nome.asc(),
            )
            .all()
        )
        return [
            {
                "codigo": r.codigo,
                "nome": r.nome,
                "naturezas": r.naturezas or "",
            }
            for r in rows
        ]


    def _compute_intake_globals(self, intake: "PrazoInicialIntake") -> None:
        """
        Recalcula os campos agregados do intake a partir dos pedidos
        atuais. Chamado no fluxo de classificação e também após PATCH
        de pedido (via endpoint) pra manter coerência.

        Regras:
          - valor_total_pedido    = sum(pedidos.valor_indicado)
          - valor_total_estimado  = sum(pedidos.valor_estimado)
          - aprovisionamento      = sum(pedidos.aprovisionamento)
          - probabilidade_exito_global = "menos favorável ao banco":
                pior prob_perda entre pedidos é remota   → exito=provavel
                pior prob_perda                 possivel → exito=possivel
                pior prob_perda                 provavel → exito=remota
          - Se NÃO há pedidos, tudo fica NULL (não força zero).

        `analise_estrategica` é preservado — vem direto da IA ou do
        operador via PATCH; não é computado aqui.
        """
        from app.models.prazo_inicial_pedido import (
            PROB_PERDA_RANK,
            PROB_PERDA_REMOTA,
            PROB_PERDA_POSSIVEL,
            PROB_PERDA_PROVAVEL,
        )

        pedidos = list(intake.pedidos or [])
        if not pedidos:
            intake.valor_total_pedido = None
            intake.valor_total_estimado = None
            intake.aprovisionamento_sugerido = None
            intake.probabilidade_exito_global = None
            return

        # Somas — só soma quando o campo não é None; soma de Nones vira None.
        def _sum(attr):
            valores = [getattr(p, attr) for p in pedidos if getattr(p, attr) is not None]
            if not valores:
                return None
            total = 0
            for v in valores:
                total += float(v)
            return total

        intake.valor_total_pedido = _sum("valor_indicado")
        intake.valor_total_estimado = _sum("valor_estimado")
        intake.aprovisionamento_sugerido = _sum("aprovisionamento")

        # Pior prob_perda (rank maior) → menor êxito.
        ranks = [
            PROB_PERDA_RANK.get(p.probabilidade_perda, -1)
            for p in pedidos
            if p.probabilidade_perda
        ]
        if not ranks:
            intake.probabilidade_exito_global = None
            return

        pior_rank = max(ranks)
        # Inverso: rank(perda)=0 remota → exito=provavel(rank 2)
        #          rank(perda)=1 possivel → exito=possivel(rank 1)
        #          rank(perda)=2 provavel → exito=remota(rank 0)
        inverso = {0: PROB_PERDA_PROVAVEL, 1: PROB_PERDA_POSSIVEL, 2: PROB_PERDA_REMOTA}
        intake.probabilidade_exito_global = inverso.get(pior_rank)

    def _materialize_pedidos(
        self,
        intake: "PrazoInicialIntake",
        response: "PrazoInicialClassificationResponse",
    ) -> int:
        """
        Persiste na tabela `prazo_inicial_pedidos` os pedidos extraídos
        da petição inicial pela IA. Em reprocessamento, apaga os antigos
        antes de criar os novos (cascade delete-orphan cuidaria se a
        sessão soubesse da relação — aqui fazemos explicitamente pra
        ser seguro).
        """
        if not hasattr(intake, "pedidos"):
            return 0

        # Limpa pedidos antigos (reprocessamento).
        for old in list(intake.pedidos):
            self.db.delete(old)

        created = 0
        for pedido in response.pedidos or []:
            self.db.add(
                PrazoInicialPedido(
                    intake_id=intake.id,
                    tipo_pedido=pedido.tipo_pedido,
                    natureza=pedido.natureza,
                    valor_indicado=pedido.valor_indicado,
                    valor_estimado=pedido.valor_estimado,
                    fundamentacao_valor=pedido.fundamentacao_valor,
                    probabilidade_perda=pedido.probabilidade_perda,
                    aprovisionamento=pedido.aprovisionamento,
                    fundamentacao_risco=pedido.fundamentacao_risco,
                )
            )
            created += 1
        return created

    def _materialize_sugestoes(
        self,
        intake: PrazoInicialIntake,
        response: PrazoInicialClassificationResponse,
    ) -> dict[str, int]:
        """
        Cria as N sugestões na tabela `prazo_inicial_sugestoes` a partir
        da resposta da IA.

        Para cada bloco com `aplica=True`:
          1. Monta uma sugestão "base" com dados vindos da IA (prazo,
             data_base, data_final_calculada, audiência, etc.).
          2. Deriva `subtipo` a partir do bloco (AUDIENCIA.tipo |
             JULGAMENTO.tipo | None para os demais).
          3. Casa templates ativos em `prazo_inicial_task_templates` via
             `match_templates(tipo_prazo, subtipo, intake.office_id)`.
          4. Se N templates casaram → cria N sugestões, cada uma com
             task_subtype_id / responsavel_sugerido_id / priority /
             due_business_days vindos do template e os templates de
             descrição/notas renderizados em `payload_proposto`.
          5. Se zero casou → cria UMA sugestão "fallback" com
             task_subtype_id NULL.

        Retorna um dict de métricas:
            {
              "created": total de sugestões persistidas,
              "blocks_with_templates": quantos blocos tiveram ao menos 1
                  template casando,
              "blocks_without_templates": quantos blocos ficaram no
                  fallback (NULL).
            }
        """
        confianca = response.confianca_geral
        observacoes = response.observacoes
        criadas = 0
        blocks_with = 0
        blocks_without = 0

        for tipo_prazo, bloco in response.blocos_aplicaveis():
            base = self._build_sugestao_base(
                intake_id=intake.id,
                tipo_prazo=tipo_prazo,
                bloco=bloco,
                confianca_geral=confianca,
                observacoes=observacoes,
            )
            subtipo_match = _derive_subtipo_for_matching(tipo_prazo, bloco)
            templates = match_templates(
                self.db,
                tipo_prazo=tipo_prazo,
                subtipo=subtipo_match,
                office_external_id=intake.office_id,
                natureza_processo=intake.natureza_processo,
            )

            if templates:
                blocks_with += 1
                for template in templates:
                    sugestao = _clone_sugestao(base)
                    _apply_template_to_sugestao(
                        sugestao=sugestao,
                        template=template,
                        intake=intake,
                        tipo_prazo=tipo_prazo,
                        bloco=bloco,
                    )
                    self.db.add(sugestao)
                    criadas += 1
            else:
                blocks_without += 1
                # Fallback sem template — marca o payload pra UI de revisão
                # saber que ainda precisa de configuração.
                payload = dict(base.payload_proposto or {})
                payload["template_match"] = "not_found"
                base.payload_proposto = payload or None
                self.db.add(base)
                criadas += 1

        return {
            "created": criadas,
            "blocks_with_templates": blocks_with,
            "blocks_without_templates": blocks_without,
        }

    @staticmethod
    def _build_sugestao_base(
        intake_id: int,
        tipo_prazo: str,
        bloco: Any,
        confianca_geral: str,
        observacoes: Optional[str],
    ) -> PrazoInicialSugestao:
        """
        Mapeia um bloco da resposta da IA para uma linha "base" de
        `prazo_inicial_sugestao`, SEM aplicar template. Cada tipo tem
        campos extras próprios (objeto, assunto, audiência) guardados em
        `payload_proposto`.

        O chamador (`_materialize_sugestoes`) depois clona essa base por
        template casado e aplica o mapeamento L1 em cima.
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
            payload["sem_determinacao"] = True
            sugestao.payload_proposto = payload
            return sugestao

        if tipo_prazo == TIPO_PRAZO_SEM_PRAZO_EM_ABERTO:
            # Persiste motivo + descricao da IA no payload pra UI mostrar.
            # `bloco` aqui e o proprio response (passado por `blocos_aplicaveis`),
            # nao um sub-bloco.
            payload["sem_prazo_em_aberto"] = True
            motivo = getattr(bloco, "motivo_sem_prazo", None)
            motivo_desc = getattr(bloco, "motivo_descricao", None)
            if motivo:
                payload["motivo_sem_prazo"] = motivo
                sugestao.subtipo = motivo  # facilita filtro por motivo na UI
            if motivo_desc:
                payload["motivo_descricao"] = motivo_desc
                sugestao.justificativa = motivo_desc
            sugestao.payload_proposto = payload
            return sugestao

        if tipo_prazo == TIPO_PRAZO_INDETERMINADO:
            # Indeterminado nao tem motivo categorico (a IA nao soube),
            # so a descricao explicando o que confundiu.
            payload["indeterminado"] = True
            motivo_desc = getattr(bloco, "motivo_descricao", None)
            if motivo_desc:
                payload["motivo_descricao"] = motivo_desc
                sugestao.justificativa = motivo_desc
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
            sugestao.data_base = bloco.data
            sugestao.subtipo = bloco.tipo
            payload["tipo_julgamento"] = bloco.tipo
            sugestao.payload_proposto = payload
            return sugestao

        # Blocos com prazo (Contestar / Liminar / Manifestação Avulsa / Contrarrazoes).
        prazo_dias = getattr(bloco, "prazo_dias", None)
        prazo_tipo = getattr(bloco, "prazo_tipo", None)
        data_base = getattr(bloco, "data_base", None)
        sugestao.prazo_dias = prazo_dias
        sugestao.prazo_tipo = prazo_tipo
        sugestao.data_base = data_base
        sugestao.data_final_calculada = calcular_prazo_seguro(
            data_base, prazo_dias, prazo_tipo
        )

        # Prazo fatal: a IA informa uma data_limit absoluta (considerando
        # PI + últimas decisões) + artigo/fundamento que sustenta +
        # resumo da decisão que originou. Pode ser NULL se a IA não
        # conseguiu derivar com segurança — operador revisa no HITL.
        sugestao.prazo_fatal_data = getattr(bloco, "prazo_fatal_data", None)
        sugestao.prazo_fatal_fundamentacao = getattr(bloco, "prazo_fatal_fundamentacao", None)
        sugestao.prazo_base_decisao = getattr(bloco, "prazo_base_decisao", None)

        if isinstance(bloco, BlocoLiminar) and bloco.objeto:
            payload["objeto"] = bloco.objeto
            sugestao.subtipo = (bloco.objeto or "")[:128] or None
        elif isinstance(bloco, BlocoManifestacaoAvulsa) and bloco.assunto:
            payload["assunto"] = bloco.assunto
            sugestao.subtipo = (bloco.assunto or "")[:128] or None
        elif isinstance(bloco, BlocoContrarrazoes):
            # CONTRARRAZOES não tem subtipo categorizado. `recurso` entra
            # no payload só pra contextualização na UI de revisão.
            if bloco.recurso:
                payload["recurso"] = bloco.recurso
        elif isinstance(bloco, BlocoContestar):
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


# ─────────────────────────────────────────────────────────────────────
# Helpers de materialização (casamento de template → sugestão)
# ─────────────────────────────────────────────────────────────────────


def _derive_subtipo_for_matching(tipo_prazo: str, bloco: Any) -> Optional[str]:
    """
    Subtipo usado no `match_templates`. Só AUDIENCIA e JULGAMENTO têm
    subtipo categorizado no schema — os demais casam apenas pelo
    `tipo_prazo`, então retornam None (template com subtipo=NULL).
    """
    if tipo_prazo == TIPO_PRAZO_AUDIENCIA and isinstance(bloco, BlocoAudiencia):
        return bloco.tipo
    if tipo_prazo == TIPO_PRAZO_JULGAMENTO and isinstance(bloco, BlocoJulgamento):
        return bloco.tipo
    return None


def _clone_sugestao(base: PrazoInicialSugestao) -> PrazoInicialSugestao:
    """
    Clona os campos da sugestão "base" (vindos da IA) para uma nova
    instância — uma por template casado. Campos de mapeamento L1 ficam
    em branco para serem preenchidos por `_apply_template_to_sugestao`.
    """
    payload = dict(base.payload_proposto) if base.payload_proposto else None
    return PrazoInicialSugestao(
        intake_id=base.intake_id,
        tipo_prazo=base.tipo_prazo,
        subtipo=base.subtipo,
        data_base=base.data_base,
        prazo_dias=base.prazo_dias,
        prazo_tipo=base.prazo_tipo,
        data_final_calculada=base.data_final_calculada,
        audiencia_data=base.audiencia_data,
        audiencia_hora=base.audiencia_hora,
        audiencia_link=base.audiencia_link,
        confianca=base.confianca,
        justificativa=base.justificativa,
        payload_proposto=payload,
    )


def _apply_template_to_sugestao(
    *,
    sugestao: PrazoInicialSugestao,
    template: PrazoInicialTaskTemplate,
    intake: PrazoInicialIntake,
    tipo_prazo: str,
    bloco: Any,
) -> None:
    """
    Preenche os campos L1 da sugestão com dados do template e renderiza
    os placeholders dos campos `description_template` / `notes_template`.
    """
    # Template "no-op" (pin014): casa normal, mas NAO cria tarefa no L1.
    # task_subtype_id e responsavel_sugerido_id ficam NULL — a sugestao
    # eh materializada com `skip_task_creation` no payload pra que a
    # confirmacao no scheduling_service pule a criacao no L1 e finalize
    # o intake como CONCLUIDO_SEM_PROVIDENCIA.
    skip = bool(getattr(template, "skip_task_creation", False))
    if not skip:
        sugestao.task_subtype_id = template.task_subtype_external_id
        sugestao.responsavel_sugerido_id = template.responsible_user_external_id

    payload: dict[str, Any] = dict(sugestao.payload_proposto or {})
    payload["template_id"] = template.id
    payload["template_name"] = template.name
    payload["priority"] = template.priority
    payload["due_business_days"] = template.due_business_days
    payload["due_date_reference"] = template.due_date_reference
    payload["template_match"] = (
        "specific" if template.office_external_id is not None else "global"
    )
    if skip:
        payload["skip_task_creation"] = True

    render_ctx = _build_render_context(
        intake=intake,
        sugestao=sugestao,
        tipo_prazo=tipo_prazo,
        bloco=bloco,
    )
    if template.description_template:
        payload["description"] = _render_template(
            template.description_template, render_ctx
        )
    if template.notes_template:
        payload["notes"] = _render_template(template.notes_template, render_ctx)

    sugestao.payload_proposto = payload or None


def _build_render_context(
    *,
    intake: PrazoInicialIntake,
    sugestao: PrazoInicialSugestao,
    tipo_prazo: str,
    bloco: Any,
) -> dict[str, str]:
    """
    Monta o dict de placeholders para substituição em description_template
    e notes_template. Todos os valores são string (ISO p/ datas), e valores
    ausentes caem em string vazia via `defaultdict` no `_render_template`.
    """
    def _iso(value: Any) -> str:
        return value.isoformat() if value is not None else ""

    ctx: dict[str, str] = {
        "cnj": intake.cnj_number or "",
        "tipo_prazo": tipo_prazo or "",
        "subtipo": sugestao.subtipo or "",
        "data_base": _iso(sugestao.data_base),
        "data_final": _iso(sugestao.data_final_calculada),
        "prazo_dias": str(sugestao.prazo_dias) if sugestao.prazo_dias is not None else "",
        "prazo_tipo": sugestao.prazo_tipo or "",
        "audiencia_data": _iso(sugestao.audiencia_data),
        "audiencia_hora": _iso(sugestao.audiencia_hora),
        "audiencia_link": sugestao.audiencia_link or "",
    }

    if isinstance(bloco, BlocoLiminar):
        ctx["objeto"] = bloco.objeto or ""
    if isinstance(bloco, BlocoManifestacaoAvulsa):
        ctx["assunto"] = bloco.assunto or ""
    if isinstance(bloco, BlocoAudiencia):
        ctx["audiencia_tipo"] = bloco.tipo or ""
        ctx["audiencia_endereco"] = bloco.endereco or ""
    if isinstance(bloco, BlocoJulgamento):
        ctx["julgamento_tipo"] = bloco.tipo or ""
        ctx["julgamento_data"] = _iso(bloco.data)
    if isinstance(bloco, BlocoContrarrazoes):
        ctx["recurso"] = bloco.recurso or ""
    return ctx


def _render_template(text: str, ctx: dict[str, str]) -> str:
    """
    Renderiza `text` com placeholders `{nome}` usando `ctx`. Placeholders
    ausentes viram string vazia (via defaultdict) em vez de levantar
    KeyError — operador ajusta depois na tela de revisão.
    """
    from collections import defaultdict

    safe = defaultdict(str, ctx)
    try:
        return text.format_map(safe)
    except (IndexError, ValueError):
        # format_map cospe erro quando o texto tem chaves malformadas
        # (ex: "{" sozinho). Retorna como está — melhor do que quebrar.
        return text
