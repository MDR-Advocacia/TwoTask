"""Acesso ao DataJud para o módulo Citações BM.

Reaproveita o ``DataJudClient`` da casa (app/services/process_monitoring)
só pra o transporte HTTP/auth, mas monta a query do jeito que foi
VALIDADO contra a base real: busca por `numeroProcesso` (só dígitos) via
`match`. O `build_process_lookup_query` daquele módulo usa
`numeroProcesso.keyword` com máscara, que não casa com o valor indexado
(o DataJud guarda o número só com dígitos).

A chave da API pública do CNJ é gratuita e compartilhada; mantemos um
fallback embutido pra o módulo funcionar mesmo sem env configurada
(mesmo padrão do projeto Lake). Em produção, setar DATAJUD_API_KEY no
Coolify (com ou sem o prefixo "APIKey ").
"""

import logging
import time
from typing import Any

import httpx

from app.core.config import settings
from app.services.process_monitoring.datajud_client import DataJudClient

logger = logging.getLogger(__name__)

# A API pública do DataJud throttla em rajada (HTTP 429). Retry com backoff
# absorve isso sem perder o processo na varredura.
_MAX_TENTATIVAS = 4
_BACKOFF_BASE_SECONDS = 1.5

# Chave pública do CNJ (mesma usada no Lake). É pública por design —
# qualquer um pode consultar a API aberta do DataJud com ela.
_DATAJUD_PUBLIC_KEY = (
    "cDZHYzlZa0JadVREZDJCendQbXY6SkJlTzNjLV9TRENyQk1RdnFKZGRQdw=="
)


def _resolve_api_key() -> str:
    raw = (settings.datajud_api_key or "").strip() or _DATAJUD_PUBLIC_KEY
    # O header do DataJudClient usa o valor cru em Authorization, e o CNJ
    # exige o esquema "APIKey <chave>". Prefixamos se vier sem.
    if not raw.lower().startswith("apikey "):
        raw = f"APIKey {raw}"
    return raw


def get_client() -> DataJudClient:
    return DataJudClient(api_key=_resolve_api_key())


def buscar_movimentos(
    cnj_digits: str, tribunal_alias: str, client: DataJudClient | None = None
) -> dict[str, Any]:
    """Consulta o processo no DataJud e devolve os movimentos brutos.

    Retorna um dict:
      {
        "status": "OK" | "SEM_HITS",
        "classe": str | None,
        "movimentos": [ {grau, codigo, nome, dataHora, complementos, orgao}, ... ],
      }

    Levanta exceção em erro de transporte/HTTP (o chamador trata como ERRO).
    """
    client = client or get_client()
    payload = {
        "query": {"match": {"numeroProcesso": cnj_digits}},
        # Um processo pode vir em mais de um grau (vários docs); 30 cobre
        # com folga e respeita o teto de paginação do DataJud.
        "size": 30,
    }

    resp = None
    ultimo_erro: Exception | None = None
    for tentativa in range(_MAX_TENTATIVAS):
        try:
            resp = client.search_processes(
                tribunal_alias=tribunal_alias, payload=payload
            )
            break
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else None
            # 429 (throttle) e 5xx (servidor) valem retry; 4xx restante não.
            if status != 429 and not (status and 500 <= status < 600):
                raise
            ultimo_erro = exc
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            ultimo_erro = exc
        if tentativa < _MAX_TENTATIVAS - 1:
            time.sleep(_BACKOFF_BASE_SECONDS * (2 ** tentativa))
    if resp is None:
        raise ultimo_erro or RuntimeError("DataJud: falha sem exceção registrada.")
    hits = resp.get("hits", {}).get("hits", []) or []
    if not hits:
        return {"status": "SEM_HITS", "classe": None, "movimentos": []}

    classe: str | None = None
    movimentos: list[dict[str, Any]] = []
    for hit in hits:
        src = hit.get("_source", {}) or {}
        grau = src.get("grau")
        if classe is None:
            cl = src.get("classe")
            classe = cl.get("nome") if isinstance(cl, dict) else cl
        for mov in src.get("movimentos", []) or []:
            orgao = mov.get("orgaoJulgador")
            if isinstance(orgao, dict):
                orgao = orgao.get("nome")
            movimentos.append(
                {
                    "grau": grau,
                    "codigo": mov.get("codigo"),
                    "nome": mov.get("nome") or "Movimento sem nome",
                    "dataHora": mov.get("dataHora"),
                    "complementos": mov.get("complementosTabelados") or [],
                    "orgao": orgao,
                }
            )
    return {"status": "OK", "classe": classe, "movimentos": movimentos}
