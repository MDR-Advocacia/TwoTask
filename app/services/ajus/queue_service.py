"""
Serviço de fila do módulo AJUS — enfileira intakes, despacha em lote,
maneja cópias do PDF.

Fluxo:
  1. Intake recebido (status RECEBIDO) → `enqueue_for_intake(intake)`
     copia o PDF da habilitação pra storage AJUS e cria registro
     em `ajus_andamento_queue` com status "pendente". Idempotente
     via UNIQUE em intake_id.
  2. Operador acumula e clica "Enviar lote" → `dispatch_pending_batch`
     pega N pendentes, monta payload AJUS, envia via AjusClient,
     atualiza fila com resultado (sucesso/erro) item a item.
  3. Item com `inserido=true` → status="sucesso", PDF apagado da
     storage AJUS (cleanup), `cod_informacao_judicial` salvo.
  4. Item com `inserido=false` → status="erro", PDF mantido pra retry,
     `error_message` salvo.

Storage do PDF:
  - Original: `prazos_iniciais_storage_path` (gerenciado por `prazos_iniciais/storage.py`)
  - Cópia AJUS: `ajus_storage_path` (gerenciado aqui)
  - Layout idêntico: `YYYY/MM/DD/{uuid}.pdf`
  - A cópia é feita NO ENFILEIRAMENTO pra sobreviver ao cleanup dos PDFs
    de prazos iniciais (que pode rodar antes do operador disparar AJUS).
"""

from __future__ import annotations

import logging
import shutil
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.ajus import (
    AJUS_QUEUE_ENVIANDO,
    AJUS_QUEUE_ERRO,
    AJUS_QUEUE_PENDENTE,
    AJUS_QUEUE_SUCESSO,
    AjusAndamentoQueue,
    AjusCodAndamento,
)
from app.models.prazo_inicial import PrazoInicialIntake
from app.services.ajus.ajus_client import (
    MAX_ITENS_POR_REQUEST,
    AjusApiError,
    AjusClient,
    AjusConfigError,
    encode_pdf_base64,
    format_date_brl,
    validate_arquivo_size,
)
from app.services.prazos_iniciais.prazo_calculator import add_business_days

logger = logging.getLogger(__name__)


# ─── Storage helpers ─────────────────────────────────────────────────


def _ajus_storage_root() -> Path:
    return Path(settings.ajus_storage_path)


def _ajus_storage_abs(relative_path: str) -> Path:
    """Resolve caminho absoluto a partir do path relativo gravado no DB."""
    return _ajus_storage_root() / relative_path


def _copy_pdf_to_ajus_storage(source_relative_path: str) -> Optional[str]:
    """
    Copia PDF do storage de prazos iniciais pro storage próprio do AJUS.

    Retorna o `relative_path` dentro do storage AJUS, ou None se a
    fonte não existir (intake sem PDF físico — cleanup já rodou).
    """
    if not source_relative_path:
        return None

    source_root = Path(settings.prazos_iniciais_storage_path)
    source_abs = source_root / source_relative_path
    if not source_abs.exists():
        logger.warning(
            "AJUS enqueue: PDF de origem não existe: %s — item será "
            "enfileirado sem anexo.",
            source_abs,
        )
        return None

    # Layout YYYY/MM/DD/{uuid}.pdf — espelha o storage de prazos iniciais
    now = datetime.now(timezone.utc)
    rel_dir = f"{now.year:04d}/{now.month:02d}/{now.day:02d}"
    filename = f"{uuid.uuid4().hex}.pdf"
    rel_path = f"{rel_dir}/{filename}"
    dest_abs = _ajus_storage_root() / rel_path
    dest_abs.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_abs, dest_abs)
    logger.info(
        "AJUS enqueue: PDF copiado %s → %s",
        source_abs, dest_abs,
    )
    return rel_path


def _delete_ajus_pdf_copy(relative_path: Optional[str]) -> None:
    """Apaga a cópia do PDF do storage AJUS. Silencioso se não existir."""
    if not relative_path:
        return
    abs_path = _ajus_storage_abs(relative_path)
    try:
        if abs_path.exists():
            abs_path.unlink()
            logger.info("AJUS cleanup: PDF apagado %s", abs_path)
    except OSError as exc:  # noqa: BLE001
        logger.warning(
            "AJUS cleanup: falha apagando %s: %s — segue (cron defensivo "
            "pode pegar depois)", abs_path, exc,
        )


def _read_ajus_pdf(relative_path: str) -> Optional[bytes]:
    """Lê bytes do PDF copiado. Retorna None se sumiu (caller decide)."""
    if not relative_path:
        return None
    abs_path = _ajus_storage_abs(relative_path)
    if not abs_path.exists():
        return None
    try:
        return abs_path.read_bytes()
    except OSError as exc:  # noqa: BLE001
        logger.warning("AJUS dispatch: erro lendo PDF %s: %s", abs_path, exc)
        return None


# ─── Lógica de fila ──────────────────────────────────────────────────


class AjusQueueService:
    """
    Operações de fila do AJUS — enfileiramento + dispatch + retry.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    # ── Enfileiramento ──────────────────────────────────────────────

    def enqueue_for_intake(
        self,
        intake: PrazoInicialIntake,
        *,
        cod_andamento: Optional[AjusCodAndamento] = None,
    ) -> Optional[AjusAndamentoQueue]:
        """
        Cria um item na fila AJUS pro intake recebido. Idempotente
        (intake_id é UNIQUE — se já existe item, retorna None).

        Se não tiver `cod_andamento` cadastrado como `is_default=True`,
        loga warning e devolve None (não enfileira). Operador precisa
        cadastrar pelo menos um código default antes.

        Args:
            intake: instância de PrazoInicialIntake (idealmente em
                status RECEBIDO — não validamos aqui pra permitir
                re-enfileiramento manual via endpoint, se necessário).
            cod_andamento: opcional — se omitido, usa o `is_default`.

        Returns:
            O item criado, ou None se já existia ou se faltou config.
        """
        # Idempotência — se já tem item pra esse intake, não duplica
        existing = (
            self.db.query(AjusAndamentoQueue)
            .filter(AjusAndamentoQueue.intake_id == intake.id)
            .one_or_none()
        )
        if existing is not None:
            logger.debug(
                "AJUS enqueue: intake %d já tem item id=%d (status=%s) — pulando",
                intake.id, existing.id, existing.status,
            )
            return None

        if cod_andamento is None:
            cod_andamento = (
                self.db.query(AjusCodAndamento)
                .filter(
                    AjusCodAndamento.is_default.is_(True),
                    AjusCodAndamento.is_active.is_(True),
                )
                .one_or_none()
            )
        if cod_andamento is None:
            logger.warning(
                "AJUS enqueue: intake %d (cnj=%s) — nenhum código de "
                "andamento default ativo cadastrado. Operador precisa "
                "configurar em /ajus/cod-andamento antes do enfileiramento.",
                intake.id, intake.cnj_number,
            )
            return None

        # Cópia do PDF (se houver)
        pdf_rel: Optional[str] = None
        if intake.pdf_path:
            try:
                pdf_rel = _copy_pdf_to_ajus_storage(intake.pdf_path)
            except OSError as exc:  # noqa: BLE001
                logger.warning(
                    "AJUS enqueue: falha copiando PDF do intake %d: %s — "
                    "item será enfileirado sem anexo (operador pode subir "
                    "depois ou disparar mesmo assim).",
                    intake.id, exc,
                )

        # Datas: data_evento = hoje (data do recebimento). Agendamento e
        # fatal somam offsets em dias úteis (CPC) a partir do evento.
        data_evento = date.today()
        data_agendamento = add_business_days(
            data_evento, cod_andamento.dias_agendamento_offset_uteis,
        )
        data_fatal = add_business_days(
            data_evento, cod_andamento.dias_fatal_offset_uteis,
        )

        # Render do `informacao` com placeholders simples.
        # `motivo` (pin019) — preenchido apenas no fluxo de devolução
        # automática (vem em intake.metadata_json["motivo"]). Pra o
        # fluxo principal vira string vazia, então o template pode usar
        # `{motivo}` sem quebrar — só fica vazio quando não aplica.
        motivo = ""
        if intake.metadata_json and isinstance(intake.metadata_json, dict):
            raw_motivo = intake.metadata_json.get("motivo")
            if raw_motivo:
                motivo = str(raw_motivo).strip()
        ctx = {
            "cnj": intake.cnj_number or "",
            "data_recebimento": format_date_brl(data_evento),
            "motivo": motivo,
        }
        try:
            informacao = (cod_andamento.informacao_template or "").format(**ctx)
        except (KeyError, IndexError) as exc:
            logger.warning(
                "AJUS enqueue: placeholder desconhecido em informacao_template "
                "(cod=%s): %s — usando template raw",
                cod_andamento.codigo, exc,
            )
            informacao = cod_andamento.informacao_template

        item = AjusAndamentoQueue(
            intake_id=intake.id,
            cnj_number=intake.cnj_number,
            cod_andamento_id=cod_andamento.id,
            situacao=cod_andamento.situacao,
            data_evento=data_evento,
            data_agendamento=data_agendamento,
            data_fatal=data_fatal,
            hora_agendamento=None,
            informacao=informacao,
            pdf_path=pdf_rel,
            status=AJUS_QUEUE_PENDENTE,
        )
        self.db.add(item)
        self.db.commit()
        self.db.refresh(item)
        logger.info(
            "AJUS enqueue: item id=%d criado pra intake %d (cnj=%s, cod=%s)",
            item.id, intake.id, intake.cnj_number, cod_andamento.codigo,
        )
        return item

    # ── Dispatch ────────────────────────────────────────────────────

    def dispatch_pending_batch(
        self, *, batch_limit: int = MAX_ITENS_POR_REQUEST,
    ) -> dict:
        """
        Pega até `batch_limit` itens em status `pendente`, monta payload
        AJUS, dispara em UMA request (limite AJUS = 20 itens por
        request), atualiza cada item com resultado.

        Returns:
            dict com summary: candidates, success_count, error_count,
            success_ids, errored. Idempotente em re-execuções (itens
            sucesso saem da fila pendente).
        """
        batch_limit = min(batch_limit, MAX_ITENS_POR_REQUEST)

        pending = (
            self.db.query(AjusAndamentoQueue)
            .filter(AjusAndamentoQueue.status == AJUS_QUEUE_PENDENTE)
            .order_by(AjusAndamentoQueue.created_at.asc())
            .limit(batch_limit)
            .all()
        )
        if not pending:
            return {
                "candidates": 0,
                "success_count": 0,
                "error_count": 0,
                "success_ids": [],
                "errored": [],
            }

        # Marca como enviando (lock soft) antes do POST
        for item in pending:
            item.status = AJUS_QUEUE_ENVIANDO
        self.db.commit()

        # Monta payload por item — 1 item da fila → 1 prazo no payload
        payload_itens: list[dict] = []
        index_to_item: dict[int, AjusAndamentoQueue] = {}
        for idx, item in enumerate(pending):
            entry: dict = {
                "identificadorAcao": {"numeroProcesso": item.cnj_number},
                "codAndamento": item.cod_andamento.codigo,
                "situacao": item.situacao,
                "dataEvento": format_date_brl(item.data_evento),
                "dataAgendamento": format_date_brl(item.data_agendamento),
                "dataFatal": format_date_brl(item.data_fatal),
                "informacao": item.informacao,
            }
            if item.hora_agendamento:
                entry["horaAgendamento"] = item.hora_agendamento.strftime("%H:%M")
            if item.pdf_path:
                pdf_bytes = _read_ajus_pdf(item.pdf_path)
                if pdf_bytes:
                    try:
                        validate_arquivo_size(len(pdf_bytes))
                        entry["arquivos"] = [{
                            "nome": "habilitacao.pdf",
                            "base64": encode_pdf_base64(pdf_bytes),
                        }]
                    except ValueError as exc:
                        logger.warning(
                            "AJUS dispatch: PDF do item %d ultrapassa "
                            "limite — segue sem anexo: %s",
                            item.id, exc,
                        )
            payload_itens.append(entry)
            index_to_item[idx] = item

        # Chama AJUS
        try:
            client = AjusClient()
            results = client.inserir_prazos(payload_itens)
        except (AjusConfigError, AjusApiError) as exc:
            # Falha global: volta todos pra "erro" com mensagem explicativa
            for item in pending:
                item.status = AJUS_QUEUE_ERRO
                item.error_message = f"Falha global no envio: {exc}"
            self.db.commit()
            logger.exception("AJUS dispatch: falha global ao enviar lote")
            return {
                "candidates": len(pending),
                "success_count": 0,
                "error_count": len(pending),
                "success_ids": [],
                "errored": [
                    {"id": item.id, "msg": str(exc)} for item in pending
                ],
            }

        # Match resposta x itens (mesma ordem)
        success_ids: list[int] = []
        errored: list[dict] = []
        now = datetime.now(timezone.utc)
        for idx, result in enumerate(results):
            item = index_to_item.get(idx)
            if item is None:
                logger.warning(
                    "AJUS dispatch: resposta no índice %d sem item correspondente",
                    idx,
                )
                continue
            item.dispatched_at = now
            if result.inserido:
                item.status = AJUS_QUEUE_SUCESSO
                item.cod_informacao_judicial = result.cod_informacao_judicial
                item.error_message = None
                success_ids.append(item.id)
                # Cleanup do PDF copiado — não precisa mais
                _delete_ajus_pdf_copy(item.pdf_path)
                item.pdf_path = None
                # Pin019: se o intake é de DEVOLUÇÃO, avança status pra
                # ENVIADA (operador vê na listagem que o andamento já
                # rolou e o caso pode sair da nossa base).
                from app.models.prazo_inicial import (
                    INTAKE_STATUS_DEVOLUCAO_PENDING,
                    INTAKE_STATUS_DEVOLUCAO_SENT,
                    PrazoInicialIntake,
                )
                intake_obj = (
                    self.db.query(PrazoInicialIntake)
                    .filter(PrazoInicialIntake.id == item.intake_id)
                    .first()
                )
                if (
                    intake_obj is not None
                    and intake_obj.status == INTAKE_STATUS_DEVOLUCAO_PENDING
                ):
                    intake_obj.status = INTAKE_STATUS_DEVOLUCAO_SENT
                    logger.info(
                        "Devolução[intake=%d]: AJUS enviado, status DEVOLUCAO_PENDENTE→DEVOLUCAO_ENVIADA",
                        intake_obj.id,
                    )
            else:
                item.status = AJUS_QUEUE_ERRO
                item.error_message = result.msg or "Falha sem mensagem da AJUS."
                errored.append({"id": item.id, "msg": item.error_message})
        self.db.commit()

        return {
            "candidates": len(pending),
            "success_count": len(success_ids),
            "error_count": len(errored),
            "success_ids": success_ids,
            "errored": errored,
        }

    # ── Dispatch pontual (1 item soh) ───────────────────────────────

    def dispatch_one(self, item_id: int) -> dict:
        """
        Dispatcha UM item especifico da fila (qualquer item_id) pro AJUS,
        em uma request isolada. Util pra debug ("disparar este aqui agora")
        e pra reenvio pontual depois de operador corrigir manualmente algum
        dado no item.

        Aceita item nos status:
          - PENDENTE: caminho normal, marca enviando -> sucesso/erro.
          - ERRO: tenta de novo (parecido com retry+dispatch num passo soh,
            evita o ciclo extra de marcar pendente antes).

        Rejeita SUCESSO/CANCELADO/ENVIANDO (409). ENVIANDO eh um caso
        suspeito (worker ja' pegou esse item) — operador clicaria 2x sem
        perceber.

        Returns:
            dict com {item_id, status_final, success, msg, cod_informacao_judicial}.
            Campo `success` = True se inserido com sucesso. `msg` traz a
            mensagem de erro do AJUS quando success=False.

        Raises:
            ValueError em item_id invalido.
            RuntimeError em status nao elegivel.
            AjusConfigError / AjusApiError em falha de conexao ou auth
              (operador ve via HTTP 502 no endpoint).
        """
        item = (
            self.db.query(AjusAndamentoQueue)
            .filter(AjusAndamentoQueue.id == item_id)
            .one_or_none()
        )
        if item is None:
            raise ValueError(f"Item AJUS {item_id} nao encontrado.")
        if item.status not in (AJUS_QUEUE_PENDENTE, AJUS_QUEUE_ERRO):
            raise RuntimeError(
                f"Dispatch pontual permitido apenas em 'pendente' ou 'erro'. "
                f"Status atual: {item.status}."
            )

        # Marca como enviando (idem batch — lock soft contra clique duplo).
        item.status = AJUS_QUEUE_ENVIANDO
        item.error_message = None
        self.db.commit()

        # Monta payload (1 entrada).
        entry: dict = {
            "identificadorAcao": {"numeroProcesso": item.cnj_number},
            "codAndamento": item.cod_andamento.codigo,
            "situacao": item.situacao,
            "dataEvento": format_date_brl(item.data_evento),
            "dataAgendamento": format_date_brl(item.data_agendamento),
            "dataFatal": format_date_brl(item.data_fatal),
            "informacao": item.informacao,
        }
        if item.hora_agendamento:
            entry["horaAgendamento"] = item.hora_agendamento.strftime("%H:%M")
        if item.pdf_path:
            pdf_bytes = _read_ajus_pdf(item.pdf_path)
            if pdf_bytes:
                try:
                    validate_arquivo_size(len(pdf_bytes))
                    entry["arquivos"] = [{
                        "nome": "habilitacao.pdf",
                        "base64": encode_pdf_base64(pdf_bytes),
                    }]
                except ValueError as exc:
                    logger.warning(
                        "AJUS dispatch_one: PDF do item %d ultrapassa "
                        "limite — segue sem anexo: %s",
                        item.id, exc,
                    )

        try:
            client = AjusClient()
            results = client.inserir_prazos([entry])
        except (AjusConfigError, AjusApiError) as exc:
            item.status = AJUS_QUEUE_ERRO
            item.error_message = f"Falha global no envio: {exc}"
            self.db.commit()
            self.db.refresh(item)
            logger.exception(
                "AJUS dispatch_one: falha global ao enviar item %d", item.id,
            )
            # Re-levanta pra o endpoint converter em 502.
            raise

        if not results:
            # Resposta vazia (defensivo — AJUS deveria sempre devolver 1
            # entrada por item enviado).
            item.status = AJUS_QUEUE_ERRO
            item.error_message = "AJUS devolveu resposta vazia."
            self.db.commit()
            self.db.refresh(item)
            return {
                "item_id": item.id,
                "status_final": item.status,
                "success": False,
                "msg": item.error_message,
                "cod_informacao_judicial": None,
            }

        result = results[0]
        now = datetime.now(timezone.utc)
        item.dispatched_at = now
        if result.inserido:
            item.status = AJUS_QUEUE_SUCESSO
            item.cod_informacao_judicial = result.cod_informacao_judicial
            item.error_message = None
            _delete_ajus_pdf_copy(item.pdf_path)
            item.pdf_path = None
            # Espelho do branch de devolucao do batch (mantem
            # status do intake sincronizado quando o item eh DEVOLUCAO).
            from app.models.prazo_inicial import (
                INTAKE_STATUS_DEVOLUCAO_PENDING,
                INTAKE_STATUS_DEVOLUCAO_SENT,
                PrazoInicialIntake,
            )
            intake_obj = (
                self.db.query(PrazoInicialIntake)
                .filter(PrazoInicialIntake.id == item.intake_id)
                .first()
            )
            if (
                intake_obj is not None
                and intake_obj.status == INTAKE_STATUS_DEVOLUCAO_PENDING
            ):
                intake_obj.status = INTAKE_STATUS_DEVOLUCAO_SENT
                logger.info(
                    "Devolucao[intake=%d]: AJUS enviado via dispatch_one, "
                    "status DEVOLUCAO_PENDENTE->DEVOLUCAO_ENVIADA",
                    intake_obj.id,
                )
        else:
            item.status = AJUS_QUEUE_ERRO
            item.error_message = result.msg or "Falha sem mensagem da AJUS."
        self.db.commit()
        self.db.refresh(item)

        return {
            "item_id": item.id,
            "status_final": item.status,
            "success": item.status == AJUS_QUEUE_SUCESSO,
            "msg": item.error_message,
            "cod_informacao_judicial": item.cod_informacao_judicial,
        }

    # ── Ações por item ──────────────────────────────────────────────

    def cancel(self, item_id: int) -> AjusAndamentoQueue:
        """Cancela um item pendente/erro — apaga PDF copiado e marca cancelado."""
        item = (
            self.db.query(AjusAndamentoQueue)
            .filter(AjusAndamentoQueue.id == item_id)
            .one_or_none()
        )
        if item is None:
            raise ValueError(f"Item AJUS {item_id} não encontrado.")
        if item.status not in (AJUS_QUEUE_PENDENTE, AJUS_QUEUE_ERRO):
            raise RuntimeError(
                f"Cancelamento permitido apenas em pendente ou erro. "
                f"Status atual: {item.status}."
            )
        _delete_ajus_pdf_copy(item.pdf_path)
        item.pdf_path = None
        item.status = "cancelado"
        self.db.commit()
        self.db.refresh(item)
        return item

    def retry(self, item_id: int) -> AjusAndamentoQueue:
        """Volta um item em erro pra pendente, pra ser disparado de novo."""
        item = (
            self.db.query(AjusAndamentoQueue)
            .filter(AjusAndamentoQueue.id == item_id)
            .one_or_none()
        )
        if item is None:
            raise ValueError(f"Item AJUS {item_id} não encontrado.")
        if item.status != AJUS_QUEUE_ERRO:
            raise RuntimeError(
                f"Retry permitido apenas em status 'erro'. Atual: {item.status}."
            )
        item.status = AJUS_QUEUE_PENDENTE
        item.error_message = None
        self.db.commit()
        self.db.refresh(item)
        return item
