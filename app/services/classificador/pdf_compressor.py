"""Motor de compressao de PDF (Classificador).

Pipeline:
1. Se PDF < classificador_compression_min_kb → skip (nao vale a pena)
2. Pikepdf abre + salva recomprimindo streams + deduplicando objetos.
3. Se resultado < original → usa o comprimido.
4. Se resultado >= original (raro, ja comprimido) → volta ao original.
5. Se pikepdf falha (PDF corrompido / encrypted) → volta ao original.

NUNCA bloqueia o intake — compressao e' best-effort, sempre devolve
bytes utilizaveis + stats pra auditoria.

Importante: NAO recomprime imagens embutidas (isso exigiria ghostscript).
Pra PDFs nativos com muito texto, reduz 20-40%. Pra PDFs scaneados
(imagem pura), reducao tipica < 10% (mas mantem qualidade da imagem
intacta).
"""

from __future__ import annotations

import io
import logging
import time
from dataclasses import dataclass
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CompressionResult:
    """Resultado da compressao + stats pra auditoria."""

    output_bytes: bytes
    original_size: int
    compressed_size: int  # == len(output_bytes)
    saved_bytes: int      # original_size - compressed_size (>= 0)
    saved_pct: float       # saved_bytes / original_size * 100
    tool: str             # "pikepdf" | "skipped_small" | "skipped_disabled" | "fallback_no_gain" | "fallback_error"
    error: Optional[str]   # mensagem quando tool == fallback_error
    duration_ms: int

    def to_dict(self) -> dict:
        return {
            "original_size": self.original_size,
            "compressed_size": self.compressed_size,
            "saved_bytes": self.saved_bytes,
            "saved_pct": round(self.saved_pct, 2),
            "tool": self.tool,
            "error": self.error,
            "duration_ms": self.duration_ms,
        }


def _no_op(pdf_bytes: bytes, tool: str, error: Optional[str] = None,
           start: float = 0) -> CompressionResult:
    n = len(pdf_bytes)
    return CompressionResult(
        output_bytes=pdf_bytes,
        original_size=n,
        compressed_size=n,
        saved_bytes=0,
        saved_pct=0.0,
        tool=tool,
        error=error,
        duration_ms=int((time.time() - start) * 1000) if start else 0,
    )


def compress_pdf(pdf_bytes: bytes) -> CompressionResult:
    """Comprime PDF best-effort. Sempre retorna bytes utilizaveis."""
    if not pdf_bytes:
        return _no_op(pdf_bytes, tool="skipped_empty")

    if not settings.classificador_compression_enabled:
        return _no_op(pdf_bytes, tool="skipped_disabled")

    threshold_bytes = settings.classificador_compression_min_kb * 1024
    if len(pdf_bytes) < threshold_bytes:
        return _no_op(pdf_bytes, tool="skipped_small")

    start = time.time()
    try:
        import pikepdf  # noqa: WPS433 — import lazy pra nao pesar startup
    except ImportError as exc:
        logger.warning("pdf_compressor: pikepdf nao instalado: %s", exc)
        return _no_op(pdf_bytes, tool="fallback_error",
                      error=f"pikepdf indisponivel: {exc}", start=start)

    try:
        out_buf = io.BytesIO()
        with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
            # compress_streams + object_stream_mode=generate +
            # remove_unreferenced_resources deduplica e reaproveita.
            pdf.save(
                out_buf,
                compress_streams=True,
                object_stream_mode=pikepdf.ObjectStreamMode.generate,
                stream_decode_level=pikepdf.StreamDecodeLevel.generalized,
                normalize_content=False,
                linearize=False,
            )
        compressed = out_buf.getvalue()
    except Exception as exc:  # noqa: BLE001
        # PDF encrypted / corrupted / formato exotico → volta ao original.
        # Log no level warning porque acontece em produto (PDFs ruins).
        logger.warning(
            "pdf_compressor: pikepdf falhou (%s) — usando original (%d bytes)",
            exc, len(pdf_bytes),
        )
        return _no_op(pdf_bytes, tool="fallback_error",
                      error=f"{type(exc).__name__}: {exc}", start=start)

    duration_ms = int((time.time() - start) * 1000)
    n_in = len(pdf_bytes)
    n_out = len(compressed)

    # Se compressao nao gerou ganho real (raro, PDF ja muito comprimido),
    # devolve o original — economia de 1-2% nao compensa risco de algum
    # bug raro do pikepdf que tira coisa.
    if n_out >= n_in:
        return CompressionResult(
            output_bytes=pdf_bytes,
            original_size=n_in,
            compressed_size=n_in,
            saved_bytes=0,
            saved_pct=0.0,
            tool="fallback_no_gain",
            error=None,
            duration_ms=duration_ms,
        )

    saved = n_in - n_out
    saved_pct = (saved / n_in) * 100
    logger.info(
        "pdf_compressor: %d -> %d bytes (-%.1f%% / -%d KB) em %dms",
        n_in, n_out, saved_pct, saved // 1024, duration_ms,
    )
    return CompressionResult(
        output_bytes=compressed,
        original_size=n_in,
        compressed_size=n_out,
        saved_bytes=saved,
        saved_pct=saved_pct,
        tool="pikepdf",
        error=None,
        duration_ms=duration_ms,
    )
