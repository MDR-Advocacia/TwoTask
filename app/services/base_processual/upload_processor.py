"""Pipeline de upload do XLSX de Base Processual.

Fluxo:
1. validate_file (sha256, header check)
2. dry_run (opcional): parse + diff sem persistir, devolve preview
3. apply: parse + diff + persist + eventos numa transacao atomica

Idempotencia: file_sha256 UNIQUE — reupload identico devolve resultado
anterior com status=IDEMPOTENTE.

Dry-run: executa pipeline real, captura summaries, da rollback e cria
uma linha DRY_RUN separada com os summaries + eventos_preview pra UI.
Commit posterior re-le o XLSX do disco e executa pipeline real.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from app.models.base_processual import (
    BaseProcessualEvento,
    BaseProcessualProcesso,
    BaseProcessualSnapshot,
    BaseProcessualUpload,
    EVENTO_ATUALIZADO,
    EVENTO_ENTROU,
    EVENTO_SAIU,
    PRESENCA_ATIVO,
    PRESENCA_REMOVIDO,
    UPLOAD_STATUS_CONCLUIDO,
    UPLOAD_STATUS_DRY_RUN,
    UPLOAD_STATUS_FALHOU,
    UPLOAD_STATUS_IDEMPOTENTE,
    UPLOAD_STATUS_PROCESSANDO,
)
from app.services.base_processual.diff import (
    compute_changed_fields,
    compute_diff_hash,
)
from app.services.base_processual.parsers import (
    normalize_str,
    parse_bool_sim_nao,
    parse_cnj_digits,
    parse_date_br,
    parse_date_only_br,
    parse_decimal_br,
    parse_int,
    parse_partes_bloco,
)
from app.services.base_processual.xlsx_reader import (
    XlsxHeaderError,
    read_xlsx_rows,
)

logger = logging.getLogger(__name__)


# Cap em 5% das linhas com erro de parsing -> aborta o upload inteiro.
MAX_PARSING_FAILURE_RATIO = 0.05
# TTL de dry-runs antes de commit (planning: 30min)
DRY_RUN_TTL_MINUTES = 30
# Cap pra preview de eventos no dry-run (UI nao precisa carregar tudo)
EVENTOS_PREVIEW_CAP = 200


@dataclass
class UploadResult:
    upload_id: int
    status: str  # CONCLUIDO | DRY_RUN | IDEMPOTENTE | FALHOU
    summary_novos: int = 0
    summary_removidos: int = 0
    summary_atualizados: int = 0
    summary_inalterados: int = 0
    error_message: Optional[str] = None
    is_idempotente: bool = False
    eventos_preview: Optional[list[dict]] = None


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def find_existing_concluido(
    db: Session, file_sha256: str
) -> Optional[BaseProcessualUpload]:
    """Busca um upload CONCLUIDO com mesmo sha — idempotencia."""
    return (
        db.query(BaseProcessualUpload)
        .filter(BaseProcessualUpload.file_sha256 == file_sha256)
        .filter(BaseProcessualUpload.status == UPLOAD_STATUS_CONCLUIDO)
        .first()
    )


def normalize_row(raw: dict) -> dict:
    """Aplica todos os parsers e devolve dict canonico pronto pra persistir.

    Chaves casam com colunas do model BaseProcessualProcesso.
    """
    cod_ajus = normalize_str(raw.get("cod_ajus"))
    empresa = normalize_str(raw.get("empresa")) or "banco_master"
    mascarado = normalize_str(raw.get("numero_processo_mascarado"))
    digits = parse_cnj_digits(mascarado)
    uf_raw = normalize_str(raw.get("uf")) or ""
    return {
        "cod_ajus": cod_ajus,
        "numero_processo": digits,
        "numero_processo_mascarado": mascarado,
        "numero_interno": normalize_str(raw.get("numero_interno")),
        "numero_pasta": normalize_str(raw.get("numero_pasta")),
        "acao_principal": normalize_str(raw.get("acao_principal")),
        "materia": normalize_str(raw.get("materia")),
        "risco_prob_perda": normalize_str(raw.get("risco_prob_perda")),
        "tipo_acao": normalize_str(raw.get("tipo_acao")),
        "polo": normalize_str(raw.get("polo")),
        "natureza": normalize_str(raw.get("natureza")),
        "numero_vara": normalize_str(raw.get("numero_vara")),
        "foro": normalize_str(raw.get("foro")),
        "comarca": normalize_str(raw.get("comarca")),
        "uf": (uf_raw[:2].upper() if uf_raw else None) or None,
        "empresa": empresa,
        "grupo_responsavel": normalize_str(raw.get("grupo_responsavel")),
        "usuario_responsavel": normalize_str(raw.get("usuario_responsavel")),
        "escritorio_responsavel": normalize_str(raw.get("escritorio_responsavel")),
        "situacao_processo": normalize_str(raw.get("situacao_processo")) or "Ativo",
        "justica_honorario": normalize_str(raw.get("justica_honorario")),
        "valor_causa": parse_decimal_br(raw.get("valor_causa")),
        "valor_prev_acordo": parse_decimal_br(raw.get("valor_prev_acordo")),
        "valor_acordo": parse_decimal_br(raw.get("valor_acordo")),
        "valor_discutido": parse_decimal_br(raw.get("valor_discutido")),
        "valor_exito": parse_decimal_br(raw.get("valor_exito")),
        "valor_condenacao": parse_decimal_br(raw.get("valor_condenacao")),
        "valor_contingencia": parse_decimal_br(raw.get("valor_contingencia")),
        "ult_andamento": normalize_str(raw.get("ult_andamento")),
        "data_ult_andamento": parse_date_br(raw.get("data_ult_andamento")),
        "dias_ult_atualizacao": parse_int(raw.get("dias_ult_atualizacao")),
        "distribuido_em": parse_date_only_br(raw.get("distribuido_em")),
        "processo_virtual": parse_bool_sim_nao(raw.get("processo_virtual")),
        "numero_contrato": normalize_str(raw.get("numero_contrato")),
        "usuario_cadastro_acao": normalize_str(raw.get("usuario_cadastro_acao")),
        "data_cadastro_acao": parse_date_br(raw.get("data_cadastro_acao")),
        "autores_raw": normalize_str(raw.get("autores_raw")),
        "reus_raw": normalize_str(raw.get("reus_raw")),
        "autores_json": parse_partes_bloco(raw.get("autores_raw")),
        "reus_json": parse_partes_bloco(raw.get("reus_raw")),
    }


def _serialize_for_payload(value):
    """Serializa Decimal/datetime/date pra JSON-safe (string ISO)."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _payload_normalized_json(normalized: dict) -> dict:
    return {k: _serialize_for_payload(v) for k, v in normalized.items()}


def _payload_raw_json(raw: dict) -> dict:
    return {k: _serialize_for_payload(v) for k, v in raw.items()}


# Campos gerenciados internamente — nao vem do XLSX. Skip em CREATE e em UPDATE.
_PROCESSO_INTERNAL_FIELDS = {
    "first_seen_upload_id",
    "last_seen_upload_id",
    "removed_at_upload_id",
    "current_snapshot_id",
    "presenca_status",
    "created_at",
    "updated_at",
    "id",
}

# Em UPDATE, alem dos internos, nao toca cod_ajus (chave natural).
# Em CREATE, cod_ajus SIM precisa entrar (vem do norm).
_PROCESSO_SKIP_ON_UPDATE = _PROCESSO_INTERNAL_FIELDS | {"cod_ajus"}


def _apply_normalized_to_processo(
    processo: BaseProcessualProcesso, normalized: dict
) -> None:
    for k, v in normalized.items():
        if k in _PROCESSO_SKIP_ON_UPDATE:
            continue
        if hasattr(processo, k):
            setattr(processo, k, v)


def process_upload(
    db: Session,
    *,
    filename: str,
    content: bytes,
    uploaded_by_user_id: Optional[int],
    dry_run: bool = False,
    storage_path: Optional[str] = None,
) -> UploadResult:
    """Pipeline principal de upload. Idempotente via file_sha256.

    Args:
        db: SQLAlchemy session aberta. Commit/rollback feito aqui.
        filename: nome original (so' pra registro).
        content: bytes do XLSX.
        uploaded_by_user_id: id do operador (nullable).
        dry_run: se True, executa pipeline e da rollback no fim, persistindo
            apenas uma linha DRY_RUN com summaries + eventos_preview.
        storage_path: caminho do XLSX em disco (preenchido pelo caller).
    """
    file_sha = sha256_bytes(content)

    # Idempotencia: pra commit real (dry-run sempre processa)
    if not dry_run:
        existing = find_existing_concluido(db, file_sha)
        if existing:
            # Placeholder com file_sha256=NULL — UNIQUE constraint permite
            # multiplos NULLs em PG e nao colide com o CONCLUIDO existente.
            placeholder = BaseProcessualUpload(
                filename=filename,
                file_sha256=None,
                file_bytes=len(content),
                total_rows_in_file=existing.total_rows_in_file,
                summary_novos=0,
                summary_removidos=0,
                summary_atualizados=0,
                summary_inalterados=0,
                status=UPLOAD_STATUS_IDEMPOTENTE,
                error_message=(
                    f"Reupload identico ao upload #{existing.id} "
                    f"(processado em {existing.committed_at or existing.processed_at})."
                ),
                uploaded_by_user_id=uploaded_by_user_id,
                storage_path=None,
                processed_at=datetime.now(timezone.utc),
            )
            db.add(placeholder)
            db.commit()
            return UploadResult(
                upload_id=placeholder.id,
                status=UPLOAD_STATUS_IDEMPOTENTE,
                summary_novos=existing.summary_novos,
                summary_removidos=existing.summary_removidos,
                summary_atualizados=existing.summary_atualizados,
                summary_inalterados=existing.summary_inalterados,
                is_idempotente=True,
            )

    # Cria a linha de upload em PROCESSANDO. Em dry-run essa linha sera
    # rolled-back ao fim — o dry-run "official" e' uma linha separada
    # criada pos-rollback.
    upload = BaseProcessualUpload(
        filename=filename,
        file_sha256=file_sha,
        file_bytes=len(content),
        status=UPLOAD_STATUS_PROCESSANDO,
        uploaded_by_user_id=uploaded_by_user_id,
        storage_path=storage_path,
    )
    db.add(upload)
    db.flush()
    upload_id = upload.id

    try:
        # 1) Parse XLSX
        try:
            _warnings, rows_iter = read_xlsx_rows(content)
        except XlsxHeaderError as exc:
            db.rollback()
            return _persist_failure(
                db,
                filename=filename,
                file_sha=file_sha,
                content_len=len(content),
                uploaded_by_user_id=uploaded_by_user_id,
                storage_path=storage_path,
                error_message=str(exc),
            )

        # 2) Normaliza todas as linhas, coletando falhas
        normalized_rows: list[tuple[dict, dict]] = []
        parsing_errors: list[str] = []
        total_rows = 0
        for raw in rows_iter:
            total_rows += 1
            try:
                norm = normalize_row(raw)
                if not norm["cod_ajus"]:
                    parsing_errors.append(f"linha {total_rows}: cod_ajus vazio")
                    continue
                normalized_rows.append((raw, norm))
            except Exception as exc:  # noqa: BLE001
                parsing_errors.append(f"linha {total_rows}: {exc}")

        upload.total_rows_in_file = total_rows
        if total_rows > 0 and (
            len(parsing_errors) / total_rows > MAX_PARSING_FAILURE_RATIO
        ):
            db.rollback()
            return _persist_failure(
                db,
                filename=filename,
                file_sha=file_sha,
                content_len=len(content),
                uploaded_by_user_id=uploaded_by_user_id,
                storage_path=storage_path,
                error_message=(
                    f"Mais de {MAX_PARSING_FAILURE_RATIO * 100:.0f}% das linhas "
                    f"falharam no parsing. Primeiros erros: {parsing_errors[:5]}"
                ),
            )

        cods_no_arquivo = {n["cod_ajus"] for _, n in normalized_rows}

        # Pre-carrega processos existentes que vao casar — evita N+1.
        existing_by_cod: dict[str, BaseProcessualProcesso] = {}
        if cods_no_arquivo:
            for p in (
                db.query(BaseProcessualProcesso)
                .filter(BaseProcessualProcesso.cod_ajus.in_(cods_no_arquivo))
                .all()
            ):
                existing_by_cod[p.cod_ajus] = p

        novos = removidos = atualizados = inalterados = 0
        eventos_preview: list[dict] = []

        # 3) Loop principal — ENTROU / RESSURGIDO / ATUALIZADO / INALTERADO
        for raw, norm in normalized_rows:
            cod = norm["cod_ajus"]
            diff_hash = compute_diff_hash(norm)
            processo = existing_by_cod.get(cod)
            normalized_json = _payload_normalized_json(norm)
            raw_json = _payload_raw_json(raw)

            if processo is None:
                # ENTROU — usa _INTERNAL_FIELDS (nao _SKIP_ON_UPDATE) pra
                # NAO filtrar cod_ajus no INSERT.
                processo = BaseProcessualProcesso(
                    **{
                        k: v
                        for k, v in norm.items()
                        if k not in _PROCESSO_INTERNAL_FIELDS
                        and hasattr(BaseProcessualProcesso, k)
                    }
                )
                processo.presenca_status = PRESENCA_ATIVO
                processo.first_seen_upload_id = upload_id
                processo.last_seen_upload_id = upload_id
                db.add(processo)
                db.flush()
                snapshot = BaseProcessualSnapshot(
                    processo_id=processo.id,
                    upload_id=upload_id,
                    cod_ajus=cod,
                    payload_normalized=normalized_json,
                    payload_raw=raw_json,
                    diff_hash=diff_hash,
                )
                db.add(snapshot)
                db.flush()
                processo.current_snapshot_id = snapshot.id
                evento = BaseProcessualEvento(
                    upload_id=upload_id,
                    processo_id=processo.id,
                    cod_ajus=cod,
                    tipo_evento=EVENTO_ENTROU,
                    changed_fields=None,
                    snapshot_before_id=None,
                    snapshot_after_id=snapshot.id,
                )
                db.add(evento)
                novos += 1
                if len(eventos_preview) < EVENTOS_PREVIEW_CAP:
                    eventos_preview.append(
                        {"tipo": EVENTO_ENTROU, "cod_ajus": cod, "changed_fields": None}
                    )
                existing_by_cod[cod] = processo
            elif processo.presenca_status == PRESENCA_REMOVIDO:
                # RESSURGIMENTO — reabre como ENTROU com flag _ressurgimento
                _apply_normalized_to_processo(processo, norm)
                processo.presenca_status = PRESENCA_ATIVO
                processo.removed_at_upload_id = None
                processo.last_seen_upload_id = upload_id
                db.flush()
                snapshot = BaseProcessualSnapshot(
                    processo_id=processo.id,
                    upload_id=upload_id,
                    cod_ajus=cod,
                    payload_normalized=normalized_json,
                    payload_raw=raw_json,
                    diff_hash=diff_hash,
                )
                db.add(snapshot)
                db.flush()
                prev_snapshot_id = processo.current_snapshot_id
                processo.current_snapshot_id = snapshot.id
                evento = BaseProcessualEvento(
                    upload_id=upload_id,
                    processo_id=processo.id,
                    cod_ajus=cod,
                    tipo_evento=EVENTO_ENTROU,
                    changed_fields={"_ressurgimento": True},
                    snapshot_before_id=prev_snapshot_id,
                    snapshot_after_id=snapshot.id,
                )
                db.add(evento)
                novos += 1
                if len(eventos_preview) < EVENTOS_PREVIEW_CAP:
                    eventos_preview.append(
                        {
                            "tipo": EVENTO_ENTROU,
                            "cod_ajus": cod,
                            "changed_fields": {"_ressurgimento": True},
                        }
                    )
            else:
                # ATIVO + ja existe — checa diff
                current_snapshot = None
                if processo.current_snapshot_id:
                    current_snapshot = (
                        db.query(BaseProcessualSnapshot)
                        .filter(
                            BaseProcessualSnapshot.id == processo.current_snapshot_id
                        )
                        .first()
                    )
                old_hash = current_snapshot.diff_hash if current_snapshot else None
                if old_hash == diff_hash:
                    # INALTERADO — atualiza so' campos volateis
                    processo.last_seen_upload_id = upload_id
                    processo.dias_ult_atualizacao = norm.get("dias_ult_atualizacao")
                    processo.data_ult_andamento = norm.get("data_ult_andamento")
                    inalterados += 1
                else:
                    # ATUALIZADO
                    before_payload = (
                        current_snapshot.payload_normalized
                        if current_snapshot
                        else {}
                    ) or {}
                    changed = compute_changed_fields(before_payload, normalized_json)
                    _apply_normalized_to_processo(processo, norm)
                    processo.last_seen_upload_id = upload_id
                    db.flush()
                    snapshot = BaseProcessualSnapshot(
                        processo_id=processo.id,
                        upload_id=upload_id,
                        cod_ajus=cod,
                        payload_normalized=normalized_json,
                        payload_raw=raw_json,
                        diff_hash=diff_hash,
                    )
                    db.add(snapshot)
                    db.flush()
                    prev_snapshot_id = processo.current_snapshot_id
                    processo.current_snapshot_id = snapshot.id
                    evento = BaseProcessualEvento(
                        upload_id=upload_id,
                        processo_id=processo.id,
                        cod_ajus=cod,
                        tipo_evento=EVENTO_ATUALIZADO,
                        changed_fields=changed,
                        snapshot_before_id=prev_snapshot_id,
                        snapshot_after_id=snapshot.id,
                    )
                    db.add(evento)
                    atualizados += 1
                    if len(eventos_preview) < EVENTOS_PREVIEW_CAP:
                        eventos_preview.append(
                            {
                                "tipo": EVENTO_ATUALIZADO,
                                "cod_ajus": cod,
                                "changed_fields": changed,
                            }
                        )

        # 4) Detecta SAIDAS — processos ATIVOS hoje que nao vieram no arquivo
        if cods_no_arquivo:
            ativos_query = (
                db.query(BaseProcessualProcesso)
                .filter(BaseProcessualProcesso.presenca_status == PRESENCA_ATIVO)
                .filter(~BaseProcessualProcesso.cod_ajus.in_(cods_no_arquivo))
            )
            for proc in ativos_query.all():
                proc.presenca_status = PRESENCA_REMOVIDO
                proc.removed_at_upload_id = upload_id
                evento = BaseProcessualEvento(
                    upload_id=upload_id,
                    processo_id=proc.id,
                    cod_ajus=proc.cod_ajus,
                    tipo_evento=EVENTO_SAIU,
                    changed_fields=None,
                    snapshot_before_id=proc.current_snapshot_id,
                    snapshot_after_id=None,
                )
                db.add(evento)
                removidos += 1
                if len(eventos_preview) < EVENTOS_PREVIEW_CAP:
                    eventos_preview.append(
                        {
                            "tipo": EVENTO_SAIU,
                            "cod_ajus": proc.cod_ajus,
                            "changed_fields": None,
                        }
                    )

        upload.summary_novos = novos
        upload.summary_removidos = removidos
        upload.summary_atualizados = atualizados
        upload.summary_inalterados = inalterados
        upload.processed_at = datetime.now(timezone.utc)

        if dry_run:
            # Em dry-run: rollback TUDO, depois insere uma row DRY_RUN
            # standalone com summaries + preview. file_sha256=NULL pra nao
            # colidir com o futuro commit (que vai gravar o sha real).
            db.rollback()
            dry_record = BaseProcessualUpload(
                filename=filename,
                file_sha256=None,
                file_bytes=len(content),
                total_rows_in_file=total_rows,
                summary_novos=novos,
                summary_removidos=removidos,
                summary_atualizados=atualizados,
                summary_inalterados=inalterados,
                status=UPLOAD_STATUS_DRY_RUN,
                eventos_preview_json=eventos_preview,
                uploaded_by_user_id=uploaded_by_user_id,
                storage_path=storage_path,
                expires_at=datetime.now(timezone.utc)
                + timedelta(minutes=DRY_RUN_TTL_MINUTES),
                processed_at=datetime.now(timezone.utc),
            )
            db.add(dry_record)
            db.commit()
            return UploadResult(
                upload_id=dry_record.id,
                status=UPLOAD_STATUS_DRY_RUN,
                summary_novos=novos,
                summary_removidos=removidos,
                summary_atualizados=atualizados,
                summary_inalterados=inalterados,
                eventos_preview=eventos_preview,
            )

        upload.status = UPLOAD_STATUS_CONCLUIDO
        upload.committed_at = datetime.now(timezone.utc)
        db.commit()
        return UploadResult(
            upload_id=upload_id,
            status=UPLOAD_STATUS_CONCLUIDO,
            summary_novos=novos,
            summary_removidos=removidos,
            summary_atualizados=atualizados,
            summary_inalterados=inalterados,
        )

    except Exception:
        db.rollback()
        logger.exception(
            "Falha inesperada processando upload de base processual "
            "(sha=%s, filename=%s).",
            file_sha,
            filename,
        )
        return _persist_failure(
            db,
            filename=filename,
            file_sha=file_sha,
            content_len=len(content),
            uploaded_by_user_id=uploaded_by_user_id,
            storage_path=storage_path,
            error_message="Erro inesperado no processamento. Veja logs do servidor.",
        )


def _persist_failure(
    db: Session,
    *,
    filename: str,
    file_sha: str,
    content_len: int,
    uploaded_by_user_id: Optional[int],
    storage_path: Optional[str],
    error_message: str,
) -> UploadResult:
    """Grava uma linha FALHOU standalone (apos rollback) com sha NULL."""
    _ = file_sha  # mantido pra logs/futuro
    fail = BaseProcessualUpload(
        filename=filename,
        file_sha256=None,
        file_bytes=content_len,
        status=UPLOAD_STATUS_FALHOU,
        error_message=error_message,
        uploaded_by_user_id=uploaded_by_user_id,
        storage_path=storage_path,
        processed_at=datetime.now(timezone.utc),
    )
    db.add(fail)
    db.commit()
    return UploadResult(
        upload_id=fail.id,
        status=UPLOAD_STATUS_FALHOU,
        error_message=error_message,
    )


def commit_dry_run(db: Session, dry_run_id: int) -> UploadResult:
    """Re-processa o XLSX original do dry-run em modo persist (commit real).

    Erros:
    - 404: dry_run_id nao existe
    - 400: nao e' DRY_RUN, expirou, ou nao tem storage_path
    """
    dry = (
        db.query(BaseProcessualUpload)
        .filter(BaseProcessualUpload.id == dry_run_id)
        .first()
    )
    if dry is None:
        raise ValueError(f"Dry-run #{dry_run_id} nao encontrado.")
    if dry.status != UPLOAD_STATUS_DRY_RUN:
        raise ValueError(
            f"Upload #{dry_run_id} nao e' um dry-run (status={dry.status})."
        )
    if dry.expires_at and dry.expires_at < datetime.now(timezone.utc):
        raise ValueError(f"Dry-run #{dry_run_id} expirou. Faca um novo upload.")
    if not dry.storage_path:
        raise ValueError(
            f"Dry-run #{dry_run_id} nao tem arquivo persistido — refaca o upload."
        )

    content = Path(dry.storage_path).read_bytes()
    result = process_upload(
        db=db,
        filename=dry.filename,
        content=content,
        uploaded_by_user_id=dry.uploaded_by_user_id,
        dry_run=False,
        storage_path=dry.storage_path,
    )
    # Marca o dry-run como commitado (rastreabilidade)
    dry.dry_run_of_upload_id = result.upload_id
    dry.committed_at = datetime.now(timezone.utc)
    db.commit()
    return result
