"""Endpoint de conversao Listagem AJUS -> XLSX de migracao Legal One.

POST /admin/base-processual/conversao-l1 recebe o XLSX da
"Listagem de Acoes Judiciais" (saida do RPA AJUS) e devolve o XLSX
no formato do MODELO LEGAL ONE pronto pra importacao.

Sincrono — a carteira tipica (~6k linhas) processa em <3s.
"""

from __future__ import annotations

import logging
from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response

from app.api.v1.endpoints.base_processual import (
    _ensure_xlsx_file,
    require_admin,
)
from app.models.legal_one import LegalOneUser
from app.services.base_processual.conversao_l1 import (
    gerar_planilha_l1,
    nome_saida,
)

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/admin/base-processual", tags=["Base Processual"]
)

XLSX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)


@router.post("/conversao-l1")
async def converter_listagem_para_l1(
    file: UploadFile = File(...),
    user: LegalOneUser = Depends(require_admin),
):
    """Converte a Listagem AJUS em planilha de migracao L1.

    Retorna o XLSX gerado como anexo. Levanta 400 se a planilha de
    entrada nao for reconhecida (cabecalho 'Polo' ausente, formato
    incompativel, etc).
    """
    content = await file.read()
    _ensure_xlsx_file(file, content)

    agora = datetime.now()
    try:
        xlsx_bytes = gerar_planilha_l1(content, agora=agora)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Falha ao gerar planilha de migracao L1")
        raise HTTPException(
            status_code=500,
            detail=f"Falha ao gerar planilha: {exc}",
        ) from exc

    filename = nome_saida(agora)
    logger.info(
        "Conversao L1 concluida — input=%r linhas_geradas=? saida=%r user=%s",
        file.filename,
        filename,
        user.id,
    )
    return Response(
        content=xlsx_bytes,
        media_type=XLSX_MEDIA_TYPE,
        headers={
            # RFC 5987: filename* permite UTF-8/espacos sem mojibake
            "Content-Disposition": (
                f'attachment; filename="{filename}"; '
                f"filename*=UTF-8''{quote(filename)}"
            ),
        },
    )
