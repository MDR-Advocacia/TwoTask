"""Orquestrador de intake por PDF do Classificador.

Recebe bytes do PDF (de upload manual ou — futuramente — do adapter do
robo de entrega), persiste no volume, roda a extracao mecanica do PI
(reuso direto de `prazos_iniciais.pdf_extractor`), e cria um
`ClassificadorProcesso` com capa_json + integra_json preenchidos e
status PRONTO_PARA_CLASSIFICAR (ou ERRO_CAPTURA quando o PDF nao tem
texto extraivel).

NAO chama IA — isso fica pra `classifier_runner.py` quando o operador
disparar `POST /lotes/{id}/classify`.

Pattern:
  PDF -> save_pdf (storage PI, volume compartilhado)
       -> pdf_extractor.extract (mecanico, PI)
       -> ClassificadorProcesso persistido

Idempotencia: pdf_sha256 e' indexado mas NAO unique — operador pode
querer subir o mesmo PDF em 2 lotes diferentes intencionalmente (raro
mas valido). Dedup explicito acontece dentro do MESMO lote (constraint
de aplicacao, nao SQL).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models.classificador import (
    ClassificadorLote,
    ClassificadorProcesso,
    EXTRACTION_CONFIDENCE_LOW,
    PROC_STATUS_PENDENTE,
    PROC_STATUS_READY,
    PROC_STATUS_ERROR_CAPTURE,
    SOURCE_API_JSON,
    SOURCE_UPLOAD_XLSX,
)
from app.core.config import settings
from app.services.classificador.pdf_compressor import compress_pdf
from app.services.prazos_iniciais.pdf_extractor import (
    ExtractionResult,
    extract,
)
from app.services.prazos_iniciais.storage import (
    PdfValidationError,
    delete_pdf,
    save_pdf,
)

logger = logging.getLogger(__name__)


# Source padrao quando o PDF chega pelo adapter do robo (fase futura).
# Upload manual via UI usa SOURCE_UPLOAD_XLSX (mesmo lote pode misturar
# fontes, vide memory project_classificador).
SOURCE_PDF_UPLOAD = "PDF_UPLOAD"
SOURCE_PDF_ROBOT_API = "PDF_ROBOT_API"


class PdfIntakeError(Exception):
    """Erro de regra de negocio do intake por PDF (bubble pro endpoint)."""


def ingest_pdf(
    db: Session,
    *,
    lote_id: int,
    pdf_bytes: bytes,
    pdf_filename: str,
    source: str = SOURCE_PDF_UPLOAD,
    cnj_hint: Optional[str] = None,
    external_id: Optional[str] = None,
    produto: Optional[str] = None,
    metadata: Optional[dict] = None,
    created_by_user_id: Optional[int] = None,
) -> ClassificadorProcesso:
    """Persiste PDF + extracao mecanica como ClassificadorProcesso.

    Args:
        db: sessao SQLAlchemy aberta
        lote_id: lote ao qual o processo pertence (FK obrigatoria)
        pdf_bytes: conteudo do PDF (validado por magic bytes + tamanho)
        pdf_filename: nome original do arquivo (auditoria)
        source: PDF_UPLOAD (manual) ou PDF_ROBOT_API (adapter futuro)
        cnj_hint: CNJ que o operador/robo afirma ser do processo. Usado
                  como fallback se o extractor mecanico nao detectar.
                  Quando ambos vem, prevalece o do extractor (mais
                  confiavel — sai do texto da capa).
        external_id: id externo opcional (do cliente / robo)
        produto: produto que o operador afirma (ex.: "Cartao Credito").
                 IA pode sobrescrever na classificacao.
        metadata: dict livre — origem, observacao, etc.
        created_by_user_id: usuario logado (opcional)

    Returns:
        ClassificadorProcesso persistido + commitado

    Raises:
        PdfIntakeError: lote nao existe / lote em status incompativel
        PdfValidationError: PDF invalido (vazio, sem magic, ou muito grande)
    """
    # 1. Valida lote
    lote = db.query(ClassificadorLote).filter(ClassificadorLote.id == lote_id).first()
    if lote is None:
        raise PdfIntakeError(f"Lote #{lote_id} nao encontrado.")

    # Lotes ja CLASSIFICADOS sao imutaveis — nao aceita novos PDFs.
    # Demais status (RASCUNHO/CAPTURANDO_L1/PRONTO/ERRO/CANCELADO) aceitam
    # — operador pode estar montando o lote incrementalmente.
    if lote.status == "CLASSIFICADO":
        raise PdfIntakeError(
            f"Lote #{lote_id} ja foi CLASSIFICADO — nao aceita novos PDFs. "
            "Crie um novo lote pra continuar."
        )

    # 2. Comprime PDF (best-effort). Skip pra arquivos muito grandes
    # (>20MB default) — pikepdf demora 20-40s e como cleanup imediato
    # vai apagar de qualquer jeito, e' desperdicio.
    import time
    t0 = time.time()
    compression = compress_pdf(pdf_bytes)
    final_bytes = compression.output_bytes
    t_compress = time.time() - t0

    # 3. Persiste PDF (comprimido se houve ganho) no volume.
    t0 = time.time()
    try:
        stored = save_pdf(final_bytes)
    except PdfValidationError:
        raise  # bubble pro endpoint (vai retornar 400)
    t_save = time.time() - t0

    logger.info(
        "Classificador.intake_pdf: lote=%s sha=%s size=%dB filename=%r "
        "[compress=%s -%.1f%% (%.1fs) save=%.1fs]",
        lote_id, stored.sha256[:8], stored.size_bytes, pdf_filename,
        compression.tool, compression.saved_pct, t_compress, t_save,
    )

    # 4. Extracao mecanica (reusa motor do PI) — usa bytes comprimidos
    # ja que sao identicos textualmente ao original (pikepdf nao mexe
    # em texto). Economia: 1 leitura a mais nao tem.
    t0 = time.time()
    try:
        result: ExtractionResult = extract(final_bytes)
    except Exception as exc:  # noqa: BLE001
        # Defesa em profundidade — `extract` nunca deveria levantar
        # (`__init__.py` ja captura tudo e devolve fallback). Mas se
        # acontecer, persiste como ERRO_CAPTURA pra operador investigar.
        logger.exception("Classificador.intake_pdf: extract() levantou: %s", exc)
        result = ExtractionResult(
            success=False,
            extractor_used=None,
            confidence=None,
            error_message=f"Erro inesperado no extractor: {type(exc).__name__}",
        )

    t_extract = time.time() - t0
    logger.info(
        "Classificador.intake_pdf: extract done lote=%s sha=%s [extract=%.1fs "
        "tool=%s conf=%s success=%s]",
        lote_id, stored.sha256[:8], t_extract,
        result.extractor_used, result.confidence, result.success,
    )

    # 5. Resolve CNJ final — extractor > hint > None
    cnj_final = result.cnj_number or cnj_hint or None

    # 6. Decide status inicial do processo
    if result.success:
        status_inicial = PROC_STATUS_READY  # PRONTO_PARA_CLASSIFICAR
        error_msg = None
        pdf_extraction_failed = False
    else:
        status_inicial = PROC_STATUS_ERROR_CAPTURE
        error_msg = result.error_message
        pdf_extraction_failed = True

    # 7. Persiste processo — inclui stats de compressao no metadata
    meta_final = dict(metadata or {})
    meta_final["compression"] = compression.to_dict()
    meta_final["timings"] = {
        "compress_seconds": round(t_compress, 2),
        "save_seconds": round(t_save, 2),
        "extract_seconds": round(t_extract, 2),
    }

    proc = ClassificadorProcesso(
        lote_id=lote_id,
        source=source,
        source_intake_id=None,

        cnj_number=cnj_final,
        external_id=external_id,
        produto=produto,

        capa_json=result.capa_json or {},
        integra_json=result.integra_json or {},
        metadata_json=meta_final,

        pdf_path=stored.relative_path,
        pdf_sha256=stored.sha256,
        pdf_bytes=stored.size_bytes,
        pdf_filename_original=pdf_filename,

        pdf_extraction_failed=pdf_extraction_failed,
        extractor_used=result.extractor_used,
        extraction_confidence=result.confidence or (
            EXTRACTION_CONFIDENCE_LOW if not result.success else None
        ),

        status=status_inicial,
        error_message=error_msg,

        data_captura_l1=datetime.utcnow(),  # captura "L1" = leitura do PDF
    )
    db.add(proc)
    db.flush()  # garante proc.id

    # 8. Atualiza contadores desnormalizados do lote
    lote.total_processos = (lote.total_processos or 0) + 1
    if result.success:
        lote.total_processos_capturados = (lote.total_processos_capturados or 0) + 1
    else:
        lote.total_processos_com_erro = (lote.total_processos_com_erro or 0) + 1

    # Atualiza source_summary (counts por origem)
    source_summary = dict(lote.source_summary or {})
    source_summary[source] = source_summary.get(source, 0) + 1
    lote.source_summary = source_summary

    db.commit()

    # 9. CLEANUP — se extracao OK e flag de retencao desligada (default),
    # descarta o PDF binario do volume. capa_json + integra_json no DB
    # sao tudo que precisamos pra reclassificar/reprocessar. Mantem
    # sha256+bytes como auditoria.
    if result.success and not settings.classificador_keep_pdf_after_success:
        try:
            delete_pdf(stored.relative_path)
            # Marca no metadata + zera pdf_path no DB
            meta_after = dict(proc.metadata_json or {})
            meta_after["pdf_discarded_at"] = datetime.utcnow().isoformat()
            meta_after["pdf_discarded_reason"] = "auto_after_extraction_success"
            proc.metadata_json = meta_after
            proc.pdf_path = None
            db.commit()
            logger.info(
                "Classificador.intake_pdf: PDF descartado proc=#%s sha=%s "
                "(%d KB liberados)",
                proc.id, stored.sha256[:8], stored.size_bytes // 1024,
            )
        except Exception as exc:  # noqa: BLE001
            # Falha no cleanup nao bloqueia — PDF fica orfao no volume mas
            # processo segue normalmente. Worker periodico futuro pode
            # varrer pdf_path != None pra processos com sucesso.
            logger.warning(
                "Classificador.intake_pdf: falha descartando PDF proc=#%s: %s",
                proc.id, exc,
            )

    db.refresh(proc)

    logger.info(
        "Classificador.intake_pdf: processo #%s criado (status=%s, "
        "extractor=%s, confidence=%s, cnj=%s, pdf_kept=%s)",
        proc.id, proc.status, proc.extractor_used,
        proc.extraction_confidence, cnj_final, proc.pdf_path is not None,
    )
    return proc
