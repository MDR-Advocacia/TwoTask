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
import re
import shutil
import uuid
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.ajus import (
    AJUS_QUEUE_CANCELADO,
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


# ─── Helpers de CNJ ──────────────────────────────────────────────────

# CNJ padrao: NNNNNNN-DD.AAAA.J.TR.OOOO (20 digitos). Aceita com/sem
# mascara — capturamos a sequencia conhecida de tamanhos.
_CNJ_REGEX = re.compile(
    r"(\d{7})[-.\s]?(\d{2})[-.\s]?(\d{4})[-.\s]?(\d{1})[-.\s]?(\d{2})[-.\s]?(\d{4})",
)


def extract_cnj_from_filename(filename: str) -> Optional[str]:
    """
    Tenta extrair um CNJ do nome do arquivo. Retorna so' digitos (20)
    ou None se nao bater. Aceita variacoes com ou sem mascara — pega o
    primeiro match.
    """
    if not filename:
        return None
    base = filename.rsplit(".", 1)[0] if "." in filename else filename
    match = _CNJ_REGEX.search(base)
    if not match:
        return None
    return "".join(match.groups())


def normalize_cnj_basic(raw: str) -> Optional[str]:
    """
    Normaliza CNJ aceitando entrada com ou sem mascara. Retorna so'
    digitos se a contagem for 20, None caso contrario. Mais estrito
    que o normalize_cnj do intake_service (que tolera 15..25) — aqui
    queremos rejeitar CNJ truncado pra o operador rever.
    """
    if not raw:
        return None
    digits = "".join(c for c in str(raw) if c.isdigit())
    if len(digits) != 20:
        return None
    return digits


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


def _save_pdf_bytes_to_ajus_storage(pdf_bytes: bytes) -> Optional[str]:
    """
    Persiste bytes de um PDF (vindo de upload em lote) direto no storage
    AJUS. Retorna o `relative_path` gravado, mesmo layout do
    `_copy_pdf_to_ajus_storage` (YYYY/MM/DD/{uuid}.pdf).
    """
    if not pdf_bytes:
        return None
    now = datetime.now(timezone.utc)
    rel_dir = f"{now.year:04d}/{now.month:02d}/{now.day:02d}"
    filename = f"{uuid.uuid4().hex}.pdf"
    rel_path = f"{rel_dir}/{filename}"
    dest_abs = _ajus_storage_root() / rel_path
    dest_abs.parent.mkdir(parents=True, exist_ok=True)
    dest_abs.write_bytes(pdf_bytes)
    logger.info(
        "AJUS bulk: PDF salvo em %s (%d bytes)", dest_abs, len(pdf_bytes),
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


def _resolve_pdf_bytes_with_fallback(
    db: Session,
    item: "AjusAndamentoQueue",
) -> Optional[bytes]:
    """
    Le os bytes do PDF do item da fila, com fallback retroativo:

    1. Tenta `item.pdf_path` (cópia AJUS feita no enqueue) — caso normal.
    2. Se nao existir, busca no intake associado e usa
       `habilitacao_pdf_path` ou `pdf_path` — caso retroativo pra itens
       enfileirados antes do bug do PDF errado ser corrigido (2026-05-06)
       OU casos onde a copia AJUS foi feita mas o arquivo sumiu do volume.
    3. Se achar via fallback, copia JIT pra storage AJUS pra proximas
       tentativas terem `item.pdf_path` valido.
    4. None se nada bate — caller decide se segue sem anexo ou erra.
    """
    # Caso normal: cópia AJUS existe.
    if item.pdf_path:
        bytes_ = _read_ajus_pdf(item.pdf_path)
        if bytes_:
            logger.info(
                "AJUS dispatch: item %d usando PDF copia local (%s, %d bytes).",
                item.id, item.pdf_path, len(bytes_),
            )
            return bytes_
        logger.warning(
            "AJUS dispatch: item %d tem pdf_path=%r mas arquivo sumiu — "
            "tentando fallback pelo intake.",
            item.id, item.pdf_path,
        )
    else:
        logger.info(
            "AJUS dispatch: item %d sem pdf_path (cópia AJUS nao foi feita "
            "no enqueue) — tentando fallback pelo intake.",
            item.id,
        )

    # Fallback: tenta pelo intake.
    intake = db.query(PrazoInicialIntake).filter(
        PrazoInicialIntake.id == item.intake_id,
    ).one_or_none()
    if intake is None:
        logger.warning(
            "AJUS dispatch: item %d sem intake associado — sem fallback de PDF.",
            item.id,
        )
        return None

    source_path = (
        getattr(intake, "habilitacao_pdf_path", None) or intake.pdf_path
    )
    if not source_path:
        logger.warning(
            "AJUS dispatch: item %d e intake %d sem PDF disponivel "
            "(item.pdf_path=%r, habilitacao_pdf_path=%r, pdf_path=%r).",
            item.id, intake.id, item.pdf_path,
            getattr(intake, "habilitacao_pdf_path", None), intake.pdf_path,
        )
        return None

    source_root = Path(settings.prazos_iniciais_storage_path)
    source_abs = source_root / source_path
    if not source_abs.exists():
        logger.warning(
            "AJUS dispatch: PDF de origem do intake %d sumiu do volume: %s",
            intake.id, source_abs,
        )
        return None

    pdf_bytes = source_abs.read_bytes()
    if not pdf_bytes:
        return None

    # Re-cria a cópia AJUS pra que tentativas futuras tenham item.pdf_path
    # valido. NAO commit aqui — o caller comita junto com o resto.
    try:
        new_rel = _copy_pdf_to_ajus_storage(source_path)
        if new_rel:
            item.pdf_path = new_rel
            logger.info(
                "AJUS dispatch: item %d ganhou cópia AJUS retroativa em %s",
                item.id, new_rel,
            )
    except OSError as exc:  # noqa: BLE001
        logger.warning(
            "AJUS dispatch: fallback nao conseguiu re-copiar pra "
            "storage AJUS (segue com bytes em memoria mesmo): %s", exc,
        )

    return pdf_bytes


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

        # Resolucao do PDF da habilitacao a anexar. Cascade:
        #   1) intake.habilitacao_pdf_path (USER_UPLOAD: campo dedicado).
        #   2) intake.pdf_path (EXTERNAL_API: PDF principal eh ja a
        #      habilitacao — vide intake_service:113-118).
        # Sem isso, AJUS rejeita com "Para concluir o andamento
        # HABILITAÇÃO DE ADVOGADO eh necessario anexar o documento".
        pdf_rel: Optional[str] = None
        source_path = (
            getattr(intake, "habilitacao_pdf_path", None)
            or intake.pdf_path
        )
        if source_path:
            try:
                pdf_rel = _copy_pdf_to_ajus_storage(source_path)
            except OSError as exc:  # noqa: BLE001
                logger.warning(
                    "AJUS enqueue: falha copiando habilitacao PDF do "
                    "intake %d: %s — item será enfileirado sem anexo.",
                    intake.id, exc,
                )
        else:
            logger.warning(
                "AJUS enqueue: intake %d sem PDF de habilitacao "
                "(pdf_path E habilitacao_pdf_path NULL) — item vai "
                "entrar na fila sem anexo. AJUS provavelmente vai "
                "rejeitar.",
                intake.id,
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

    # ── Bulk enqueue (upload manual em lote sem intake) ─────────────

    # Reasons agregadas no `skipped` do bulk_enqueue. Frontend pode
    # tratar com mensagens diferentes; backend sempre devolve a string
    # explicativa em PT-BR pra log/console.
    BULK_SKIP_CNJ_INVALIDO = "cnj_invalido"
    BULK_SKIP_JA_TINHA_PDF = "ja_tinha_pdf"
    BULK_SKIP_JA_PROCESSADO = "ja_processado"
    BULK_SKIP_EM_ENVIO = "em_envio"
    BULK_SKIP_CANCELADO_ANTES = "cancelado_anteriormente"

    def bulk_enqueue(
        self,
        *,
        cod_andamento: AjusCodAndamento,
        entries: Iterable[dict],
        situacao: Optional[str] = None,
        data_evento: Optional[date] = None,
        data_agendamento: Optional[date] = None,
        data_fatal: Optional[date] = None,
        hora_agendamento: Optional[time] = None,
        informacao_template_override: Optional[str] = None,
    ) -> dict:
        """
        Smart-merge: cria itens novos OU atualiza itens existentes na
        fila pelos mesmos CNJs.

        Comportamento por CNJ (olhando o item mais recente, se houver):
          - Inexistente -> cria novo item (comportamento original).
          - PENDENTE/ERRO sem PDF -> ATUALIZA: anexa o PDF, remove o
            prefixo BACKFILL_NO_PDF_PREFIX do `informacao` se estiver
            presente, mantem demais campos. Caso de uso principal:
            operador roda backfill (cria itens sem PDF marcados) e
            depois sobe os PDFs em lote pra completar.
          - PENDENTE/ERRO com PDF -> skip "ja_tinha_pdf" (operador
            provavelmente subiu duplicado por engano).
          - SUCESSO -> skip "ja_processado" (AJUS ja registrou o
            andamento -- reabrir geraria duplicacao no Master).
          - ENVIANDO -> skip "em_envio" (worker pegou esse item
            agora; nao mexer pra evitar race).
          - CANCELADO -> skip "cancelado_anteriormente" (operador
            cancelou de proposito; criar de novo via bulk parece
            descuido -- se quiser mesmo, retry/cancel manual).

        Cada `entry` deve ter pelo menos:
          - `cnj` (str): 20 digitos. Origem livre (nome de arquivo,
            textarea, etc.). Caller normaliza.
          - `pdf_bytes` (Optional[bytes]): conteudo do PDF a anexar
            (None = sem anexo).
          - `filename` (Optional[str]): nome de origem, so' pra log.

        Variaveis comuns (situacao/datas/hora) e o template do
        `informacao` se aplicam APENAS aos itens criados do zero.
        Atualizacoes preservam os campos do item existente -- so' o
        PDF e o `informacao` (limpando o prefixo) sao tocados.

        Returns:
            dict com:
              - created (int): itens novos enfileirados.
              - updated (int): itens existentes que ganharam PDF.
              - skipped (list[dict]): rejeitados ({cnj, filename, reason}).
              - item_ids (list[int]): created_ids + updated_ids juntos
                (compat com frontend antigo que so' olha esse campo).
              - created_ids (list[int])
              - updated_ids (list[int])
        """
        eff_situacao = situacao or cod_andamento.situacao or "A"
        eff_data_evento = data_evento or date.today()
        eff_data_agend = data_agendamento or add_business_days(
            eff_data_evento, cod_andamento.dias_agendamento_offset_uteis,
        )
        eff_data_fatal = data_fatal or add_business_days(
            eff_data_evento, cod_andamento.dias_fatal_offset_uteis,
        )
        info_template = (
            informacao_template_override
            if informacao_template_override is not None
            else (cod_andamento.informacao_template or "")
        )

        created_ids: list[int] = []
        updated_ids: list[int] = []
        skipped: list[dict] = []
        for entry in entries:
            raw_cnj = entry.get("cnj")
            filename = entry.get("filename")
            pdf_bytes = entry.get("pdf_bytes")

            cnj = normalize_cnj_basic(raw_cnj or "")
            if cnj is None:
                skipped.append({
                    "cnj": str(raw_cnj or ""),
                    "filename": filename,
                    "reason": (
                        f"CNJ invalido ou nao encontrado no nome do arquivo "
                        f"({raw_cnj!r})."
                    ),
                })
                continue

            # Smart-merge: pega o item mais recente desse CNJ pra decidir
            # entre criar/atualizar/skipar. Em geral so' tem 1 ativo, mas
            # operador pode ter cancelado um e ressuscitado depois -- por
            # isso ordenamos por created_at desc.
            existing = (
                self.db.query(AjusAndamentoQueue)
                .filter(AjusAndamentoQueue.cnj_number == cnj)
                .order_by(AjusAndamentoQueue.created_at.desc())
                .first()
            )

            if existing is not None:
                if existing.status == AJUS_QUEUE_SUCESSO:
                    skipped.append({
                        "cnj": cnj,
                        "filename": filename,
                        "reason": (
                            f"CNJ ja' tem andamento enviado com sucesso ao AJUS "
                            f"(item #{existing.id})."
                        ),
                    })
                    continue
                if existing.status == AJUS_QUEUE_ENVIANDO:
                    skipped.append({
                        "cnj": cnj,
                        "filename": filename,
                        "reason": (
                            f"CNJ tem item em envio ativo no momento "
                            f"(item #{existing.id}). Tente novamente depois."
                        ),
                    })
                    continue
                if existing.status == AJUS_QUEUE_CANCELADO:
                    skipped.append({
                        "cnj": cnj,
                        "filename": filename,
                        "reason": (
                            f"CNJ teve item cancelado anteriormente "
                            f"(item #{existing.id}). Reactive via retry "
                            f"manual se quiser reenviar."
                        ),
                    })
                    continue
                # Restam: PENDENTE ou ERRO -- candidatos a UPDATE.
                if existing.pdf_path:
                    skipped.append({
                        "cnj": cnj,
                        "filename": filename,
                        "reason": (
                            f"CNJ ja' tem item na fila com PDF anexado "
                            f"(item #{existing.id}, status={existing.status})."
                        ),
                    })
                    continue

                # Aqui: PENDENTE/ERRO sem PDF -> anexa.
                if not pdf_bytes:
                    # Sem PDF pra anexar e existente tambem nao tem -- nada
                    # a fazer. Skip, mas com reason diferente (usuario
                    # tentou subir entry sem arquivo, ex.: bulk-cnj sobre
                    # CNJ ja' enfileirado pelo backfill).
                    skipped.append({
                        "cnj": cnj,
                        "filename": filename,
                        "reason": (
                            f"CNJ ja' esta na fila sem PDF (item #{existing.id}). "
                            f"Suba a habilitacao via 'Upload em lote' pra anexar."
                        ),
                    })
                    continue

                pdf_rel: Optional[str] = None
                try:
                    pdf_rel = _save_pdf_bytes_to_ajus_storage(pdf_bytes)
                except OSError as exc:  # noqa: BLE001
                    logger.warning(
                        "AJUS bulk update: falha gravando PDF do CNJ %s "
                        "(filename=%r): %s",
                        cnj, filename, exc,
                    )
                    skipped.append({
                        "cnj": cnj,
                        "filename": filename,
                        "reason": f"Falha ao gravar PDF: {exc}",
                    })
                    continue

                existing.pdf_path = pdf_rel
                # Limpa o prefixo de "sem anexo" (deixado pelo backfill)
                # se estiver presente, pra a observacao voltar ao normal.
                if (
                    existing.informacao
                    and existing.informacao.startswith(self.BACKFILL_NO_PDF_PREFIX)
                ):
                    existing.informacao = existing.informacao[
                        len(self.BACKFILL_NO_PDF_PREFIX):
                    ]
                # Se o item estava em ERRO por falta de anexo, volta pra
                # pendente pra re-disparar com o PDF agora. Em PENDENTE
                # mantem o status (ja estava esperando).
                if existing.status == AJUS_QUEUE_ERRO:
                    existing.status = AJUS_QUEUE_PENDENTE
                    existing.error_message = None
                self.db.flush()
                updated_ids.append(existing.id)
                logger.info(
                    "AJUS bulk update: item id=%d ganhou PDF (cnj=%s, status=%s)",
                    existing.id, cnj, existing.status,
                )
                continue

            # Caminho normal: nao tem item, cria do zero.
            new_pdf_rel: Optional[str] = None
            if pdf_bytes:
                try:
                    new_pdf_rel = _save_pdf_bytes_to_ajus_storage(pdf_bytes)
                except OSError as exc:  # noqa: BLE001
                    logger.warning(
                        "AJUS bulk create: falha gravando PDF do CNJ %s "
                        "(filename=%r): %s -- segue sem anexo",
                        cnj, filename, exc,
                    )

            ctx = {
                "cnj": cnj,
                "data_recebimento": format_date_brl(eff_data_evento),
                "motivo": "",
            }
            try:
                informacao = info_template.format(**ctx)
            except (KeyError, IndexError) as exc:
                logger.warning(
                    "AJUS bulk: placeholder desconhecido em template "
                    "(cod=%s): %s -- usando template raw",
                    cod_andamento.codigo, exc,
                )
                informacao = info_template

            item = AjusAndamentoQueue(
                intake_id=None,
                cnj_number=cnj,
                cod_andamento_id=cod_andamento.id,
                situacao=eff_situacao,
                data_evento=eff_data_evento,
                data_agendamento=eff_data_agend,
                data_fatal=eff_data_fatal,
                hora_agendamento=hora_agendamento,
                informacao=informacao,
                pdf_path=new_pdf_rel,
                status=AJUS_QUEUE_PENDENTE,
            )
            self.db.add(item)
            self.db.flush()
            created_ids.append(item.id)
            logger.info(
                "AJUS bulk create: item id=%d criado (cnj=%s, cod=%s, has_pdf=%s)",
                item.id, cnj, cod_andamento.codigo, bool(new_pdf_rel),
            )

        self.db.commit()
        return {
            "created": len(created_ids),
            "updated": len(updated_ids),
            "skipped": skipped,
            "item_ids": created_ids + updated_ids,
            "created_ids": created_ids,
            "updated_ids": updated_ids,
        }

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
            # Fallback robusto: se item.pdf_path eh None ou arquivo
            # sumiu, busca pelo intake.habilitacao_pdf_path | pdf_path
            # e re-copia JIT. Cobre itens enfileirados antes do fix de
            # 2026-05-06 (que copiavam pdf da integra ou nada).
            pdf_bytes = _resolve_pdf_bytes_with_fallback(self.db, item)
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
                # Habilitacao na storage AJUS preservada (regra "salvar
                # tudo" — feedback_nao_apagar_habilitacao.md). O campo
                # `item.pdf_path` aponta pro arquivo, mantemos pra rastreio.
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
        # Mesma logica de fallback do batch — itens com pdf_path None
        # ou arquivo sumido tentam ler do intake associado.
        pdf_bytes = _resolve_pdf_bytes_with_fallback(self.db, item)
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
            # Habilitacao copiada preservada (regra "salvar tudo").
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
        """Cancela um item pendente/erro. PDF copiado preservado (regra
        "salvar tudo" — feedback_nao_apagar_habilitacao.md). Operador
        gerencia limpeza do estoque manualmente depois."""
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

    # -- Backfill retroativo (intakes antigos) -----------------------

    # Status considerados "ja classificados" -- ponto de corte do
    # backfill. RECEBIDO/PRONTO_PARA_CLASSIFICAR/EM_CLASSIFICACAO/
    # PROCESSO_NAO_ENCONTRADO/ERRO_CLASSIFICACAO ainda nao chegaram a
    # ser classificados, entao ficam de fora. CANCELADO tambem (foi
    # cancelado intencionalmente). DEVOLUCAO_* tem fluxo proprio.
    BACKFILL_DEFAULT_STATUSES = (
        "CLASSIFICADO",
        "AGUARDANDO_CONFIG_TEMPLATE",
        "EM_REVISAO",
        "AGENDADO",
        "CONCLUIDO_SEM_PROVIDENCIA",
        "GED_ENVIADO",
        "CONCLUIDO",
        "ERRO_AGENDAMENTO",
        "ERRO_GED",
    )

    BACKFILL_NO_PDF_PREFIX = (
        "[SEM ANEXO - ANEXAR PDF DA HABILITACAO ANTES DO ENVIO] "
    )

    def backfill_completed_intakes(
        self,
        *,
        statuses: Optional[Iterable[str]] = None,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        dry_run: bool = False,
        limit: Optional[int] = None,
    ) -> dict:
        """
        Enfileira no AJUS todos os intakes "ja classificados" que ainda
        nao tem item na fila -- pra cobrir os processos antigos
        anteriores ao auto-enqueue (intake_service:215).

        Reusa `enqueue_for_intake`, que ja eh idempotente via UNIQUE
        (intake_id), entao rodar 2x nao duplica. Tambem usa o
        `cod_andamento` default -- se nao tiver default cadastrado,
        nada eh enfileirado e o resumo traz contadores zerados +
        `error`.

        Intakes SEM PDF da habilitacao tambem entram na fila. Nesse
        caso, o campo `informacao` do item recebe o prefixo
        `BACKFILL_NO_PDF_PREFIX` pra o operador ver na listagem que
        precisa anexar manualmente antes do dispatch. A lista desses
        casos volta no campo `enqueued_without_pdf` da resposta pra
        o frontend alertar.

        Args:
            statuses: lista de status do intake a considerar. Default =
                BACKFILL_DEFAULT_STATUSES (qualquer estado pos-classificacao).
            from_date / to_date: filtro opcional por created_at do
                intake (inclusivo nos dois lados).
            dry_run: se True, so conta candidatos sem mexer na fila.
            limit: corta o numero de intakes processados nessa chamada
                (None = sem limite).

        Returns:
            dict {
                "candidates": int,             # intakes que passaram no filtro
                "enqueued": int,               # itens AJUS criados de fato (com ou sem PDF)
                "skipped_already": int,        # ja tinham item na fila
                "skipped_other": int,          # enqueue retornou None por outro motivo
                "intake_ids_enqueued": list[int],
                "enqueued_without_pdf": list[{"intake_id": int, "cnj_number": str}],
                "dry_run": bool,
                "error": Optional[str],
            }
        """
        eff_statuses = list(statuses) if statuses else list(
            self.BACKFILL_DEFAULT_STATUSES,
        )

        # Pre-checa cod default -- se nao tem, sai cedo com mensagem
        # explicativa. Evita iterar centenas de intakes sem necessidade.
        cod_default = (
            self.db.query(AjusCodAndamento)
            .filter(
                AjusCodAndamento.is_default.is_(True),
                AjusCodAndamento.is_active.is_(True),
            )
            .one_or_none()
        )
        if cod_default is None:
            return {
                "candidates": 0,
                "enqueued": 0,
                "skipped_already": 0,
                "skipped_other": 0,
                "intake_ids_enqueued": [],
                "enqueued_without_pdf": [],
                "dry_run": dry_run,
                "error": (
                    "Nenhum cod_andamento default ativo cadastrado. "
                    "Cadastre em /ajus/cod-andamento antes de rodar o backfill."
                ),
            }

        q = (
            self.db.query(PrazoInicialIntake)
            .filter(PrazoInicialIntake.status.in_(eff_statuses))
        )
        if from_date is not None:
            q = q.filter(PrazoInicialIntake.received_at >= from_date)
        if to_date is not None:
            # to_date inclusivo: pega ate o fim do dia.
            q = q.filter(
                PrazoInicialIntake.received_at < (to_date + timedelta(days=1)),
            )
        q = q.order_by(PrazoInicialIntake.received_at.asc())
        if limit is not None and limit > 0:
            q = q.limit(limit)
        intakes = q.all()

        candidates = len(intakes)
        enqueued = 0
        skipped_already = 0
        skipped_other = 0
        enqueued_ids: list[int] = []
        enqueued_without_pdf: list[dict] = []

        # Pre-carrega ids ja na fila pra contar "skipped_already" sem
        # custar 1 SELECT por iteracao em dry_run.
        existing_intake_ids: set[int] = set()
        if intakes:
            existing_intake_ids = {
                row[0]
                for row in (
                    self.db.query(AjusAndamentoQueue.intake_id)
                    .filter(AjusAndamentoQueue.intake_id.in_(
                        [i.id for i in intakes],
                    ))
                    .all()
                )
            }

        for intake in intakes:
            if intake.id in existing_intake_ids:
                skipped_already += 1
                continue

            has_pdf = bool(
                getattr(intake, "habilitacao_pdf_path", None)
                or intake.pdf_path
            )

            if dry_run:
                # Conta como "enqueued" no preview pra o operador ter o
                # numero real do que sairia daqui. Tambem reporta os
                # sem-PDF pra o frontend ja conseguir alertar antes do
                # disparo real.
                enqueued += 1
                enqueued_ids.append(intake.id)
                if not has_pdf:
                    enqueued_without_pdf.append({
                        "intake_id": intake.id,
                        "cnj_number": intake.cnj_number or "",
                    })
                continue

            try:
                item = self.enqueue_for_intake(
                    intake, cod_andamento=cod_default,
                )
            except Exception:  # noqa: BLE001
                logger.exception(
                    "Backfill AJUS: falha enfileirando intake %d -- pulado.",
                    intake.id,
                )
                skipped_other += 1
                continue

            if item is None:
                # enqueue_for_intake devolve None em 2 casos: ja existia
                # (race com outro processo) ou faltou cod default. O
                # cod default ja foi checado, entao atribui a "ja
                # existia" -- incrementa skipped_already.
                skipped_already += 1
                continue

            enqueued += 1
            enqueued_ids.append(intake.id)

            # Sem PDF anexado -- prefixa a observacao do item pra o
            # operador ver na listagem que precisa anexar antes do
            # dispatch (AJUS rejeita andamento de habilitacao sem
            # arquivo). Reporta no resultado pra o frontend exibir
            # alerta agregado.
            if not item.pdf_path:
                if not (item.informacao or "").startswith(
                    self.BACKFILL_NO_PDF_PREFIX,
                ):
                    item.informacao = (
                        self.BACKFILL_NO_PDF_PREFIX + (item.informacao or "")
                    )
                    self.db.commit()
                enqueued_without_pdf.append({
                    "intake_id": intake.id,
                    "cnj_number": intake.cnj_number or "",
                })

        logger.info(
            "Backfill AJUS concluido: candidates=%d enqueued=%d "
            "skipped_already=%d skipped_other=%d sem_pdf=%d dry_run=%s",
            candidates, enqueued, skipped_already, skipped_other,
            len(enqueued_without_pdf), dry_run,
        )

        return {
            "candidates": candidates,
            "enqueued": enqueued,
            "skipped_already": skipped_already,
            "skipped_other": skipped_other,
            "intake_ids_enqueued": enqueued_ids,
            "enqueued_without_pdf": enqueued_without_pdf,
            "dry_run": dry_run,
            "error": None,
        }
