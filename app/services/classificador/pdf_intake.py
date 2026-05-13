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
from app.services.prazos_iniciais.pdf_extractor import (
    ExtractionResult,
    extract,
)
from app.services.prazos_iniciais.storage import (
    PdfValidationError,
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

    # 2. Persiste PDF no volume (validacao de magic bytes + tamanho)
    try:
        stored = save_pdf(pdf_bytes)
    except PdfValidationError:
        raise  # bubble pro endpoint (vai retornar 400)

    logger.info(
        "Classificador.intake_pdf: lote=%s, sha256=%s, size=%dB, filename=%r",
        lote_id, stored.sha256[:8], stored.size_bytes, pdf_filename,
    )

    # 3. Extracao mecanica (reusa motor do PI)
    try:
        result: ExtractionResult = extract(pdf_bytes)
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

    # 4. Resolve CNJ final — extractor > hint > None
    cnj_final = result.cnj_number or cnj_hint or None

    # 5. Decide status inicial do processo
    if result.success:
        status_inicial = PROC_STATUS_READY  # PRONTO_PARA_CLASSIFICAR
        error_msg = None
        pdf_extraction_failed = False
    else:
        status_inicial = PROC_STATUS_ERROR_CAPTURE
        error_msg = result.error_message
        pdf_extraction_failed = True

    # 6. Persiste processo
    proc = ClassificadorProcesso(
        lote_id=lote_id,
        source=source,
        source_intake_id=None,

        cnj_number=cnj_final,
        external_id=external_id,
        produto=produto,

        capa_json=result.capa_json or {},
        integra_json=result.integra_json or {},
        metadata_json=metadata,

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

    # 7. Atualiza contadores desnormalizados do lote
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
    db.refresh(proc)

    logger.info(
        "Classificador.intake_pdf: processo #%s criado (status=%s, "
        "extractor=%s, confidence=%s, cnj=%s)",
        proc.id, proc.status, proc.extractor_used,
        proc.extraction_confidence, cnj_final,
    )
    return proc
