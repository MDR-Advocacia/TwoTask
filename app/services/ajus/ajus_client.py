"""
Cliente HTTP para a API AJUS — escopo: SÓ inserir-prazos.

A AJUS oferece outros endpoints (capa-processo, listar-prazos,
agenda-prazos, listar-honorarios, agenda-concluir-prazos), mas o uso
do MDR é apenas mandar andamentos. Por isso essa classe expõe somente
`inserir_prazos`. Se um dia precisar dos outros, basta adicionar
métodos correspondentes no mesmo padrão.

Auth (dupla camada — exigência da AJUS):
  - Header `Authorization: Bearer <JWT>` (env AJUS_BEARER_TOKEN)
  - Header `cliente: <identificador>` (env AJUS_CLIENTE)
  - Body de cada request: `login` + `senha` (env AJUS_LOGIN/AJUS_SENHA)

Importante:
  - Datas no payload em formato dd/MM/yyyy (NÃO ISO).
  - Limite de 20 itens por request — caller particiona se for maior.
  - Resposta retorna 200 mesmo com falhas individuais. Cada item da
    resposta tem `inserido: true|false`. Iterar e tratar parcialmente.
  - PDF anexado vai como base64 dentro de `arquivos[].base64`.
  - Limite por arquivo: 10MB. Limite total por prazo: 30MB.
  - Limite de arquivos por prazo: 10.
  - Logs NÃO incluem login/senha em claro.
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from typing import Any, Optional

import requests

from app.core.config import settings

logger = logging.getLogger(__name__)


# Limites da AJUS (doc oficial)
MAX_ITENS_POR_REQUEST = 20
MAX_ARQUIVOS_POR_PRAZO = 10
MAX_BYTES_POR_ARQUIVO = 10 * 1024 * 1024
MAX_BYTES_TOTAL_POR_PRAZO = 30 * 1024 * 1024

# Timeout default — AJUS pode demorar pra processar payloads com PDF.
DEFAULT_TIMEOUT_SECONDS = 60


class AjusConfigError(RuntimeError):
    """Credenciais ou config faltando — env vars não setadas."""


class AjusApiError(RuntimeError):
    """Falha de comunicação ou resposta inesperada da AJUS."""


@dataclass(frozen=True)
class AjusInsertResultItem:
    """Resultado individual da inserção de um prazo."""

    inserido: bool
    cod_informacao_judicial: Optional[str]
    msg: Optional[str]
    identificador_acao: dict[str, Any]


class AjusClient:
    """
    Cliente HTTP isolado pra POST /inserir-prazos.

    Uso típico:
        client = AjusClient()
        results = client.inserir_prazos([
            {
                "identificadorAcao": {"numeroProcesso": "0000123-45.2026..."},
                "codAndamento": "1234",
                "situacao": "A",
                "dataEvento": "28/04/2026",
                "dataAgendamento": "30/04/2026",
                "dataFatal": "15/05/2026",
                "informacao": "Recebimento de habilitação",
                "arquivos": [{"nome": "habilitacao.pdf", "base64": "..."}],
            },
        ])
        for r in results:
            if r.inserido:
                logger.info("OK %s", r.cod_informacao_judicial)
            else:
                logger.warning("FALHA: %s", r.msg)
    """

    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        bearer_token: Optional[str] = None,
        cliente: Optional[str] = None,
        login: Optional[str] = None,
        senha: Optional[str] = None,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._base_url = (base_url or settings.ajus_base_url).rstrip("/")
        self._bearer = bearer_token or settings.ajus_bearer_token
        self._cliente = cliente or settings.ajus_cliente
        self._login = login or settings.ajus_login
        self._senha = senha or settings.ajus_senha
        self._timeout = timeout

        missing = [
            name
            for name, value in [
                ("AJUS_BEARER_TOKEN", self._bearer),
                ("AJUS_CLIENTE", self._cliente),
                ("AJUS_LOGIN", self._login),
                ("AJUS_SENHA", self._senha),
            ]
            if not value
        ]
        if missing:
            raise AjusConfigError(
                "Credenciais AJUS não configuradas. Variáveis ausentes: "
                + ", ".join(missing)
            )

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._bearer}",
            "cliente": self._cliente or "",
            "Content-Type": "application/json",
        }

    def inserir_prazos(
        self, itens: list[dict[str, Any]],
    ) -> list[AjusInsertResultItem]:
        """
        Envia até 20 itens em uma única chamada à API AJUS.

        Args:
            itens: lista de dicts já no formato do payload AJUS (ver
                docstring da classe). Caller é responsável por validar
                e formatar (datas dd/MM/yyyy, identificador, etc.).

        Returns:
            Lista de `AjusInsertResultItem` na MESMA ORDEM dos itens
            enviados. Cada item indica sucesso ou falha individual.

        Raises:
            ValueError: se itens vazio ou mais de 20.
            AjusApiError: falha de rede, status HTTP != 200, ou
                resposta com formato inesperado.
        """
        if not itens:
            raise ValueError("inserir_prazos: lista de itens vazia.")
        if len(itens) > MAX_ITENS_POR_REQUEST:
            raise ValueError(
                f"inserir_prazos: máximo de {MAX_ITENS_POR_REQUEST} itens "
                f"por request — recebeu {len(itens)}. Particione no caller."
            )

        body = {
            "login": self._login,
            "senha": self._senha,
            "prazos": itens,
        }
        url = f"{self._base_url}/inserir-prazos"

        logger.info(
            "AJUS inserir-prazos: enviando %d item(s) — base_url=%s cliente=%s",
            len(itens), self._base_url, self._cliente,
        )

        try:
            response = requests.post(
                url, json=body, headers=self._headers(), timeout=self._timeout,
            )
        except requests.RequestException as exc:
            raise AjusApiError(f"Falha de rede ao chamar AJUS: {exc}") from exc

        if response.status_code == 401:
            raise AjusApiError(
                "AJUS retornou 401 — token ou login/senha inválidos. "
                "Verifique AJUS_BEARER_TOKEN e AJUS_LOGIN/AJUS_SENHA."
            )
        if response.status_code == 403:
            raise AjusApiError("AJUS retornou 403 — acesso negado.")
        if response.status_code >= 500:
            raise AjusApiError(
                f"AJUS retornou {response.status_code}: {response.text[:500]}"
            )
        if response.status_code != 200:
            raise AjusApiError(
                f"AJUS retornou status inesperado {response.status_code}: "
                f"{response.text[:500]}"
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise AjusApiError(
                f"AJUS retornou body não-JSON: {response.text[:500]}",
            ) from exc

        if not isinstance(data, list):
            raise AjusApiError(
                f"AJUS deveria retornar uma lista de resultados, "
                f"mas retornou {type(data).__name__}: {str(data)[:300]}"
            )

        out: list[AjusInsertResultItem] = []
        for raw in data:
            if not isinstance(raw, dict):
                logger.warning("AJUS item de resposta não-dict: %r", raw)
                continue
            out.append(
                AjusInsertResultItem(
                    inserido=bool(raw.get("inserido")),
                    cod_informacao_judicial=raw.get("codInformacaoJudicial"),
                    msg=raw.get("msg"),
                    identificador_acao=raw.get("identificadorAcao") or {},
                )
            )

        logger.info(
            "AJUS inserir-prazos: respondeu %d resultado(s); sucessos=%d falhas=%d",
            len(out),
            sum(1 for r in out if r.inserido),
            sum(1 for r in out if not r.inserido),
        )
        return out


# ─── Helpers de formatação ───────────────────────────────────────────

def format_date_brl(value) -> str:
    """Formata datetime.date / datetime / string ISO em dd/MM/yyyy."""
    if value is None:
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%d/%m/%Y")
    s = str(value)
    # Tenta YYYY-MM-DD → dd/MM/yyyy
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return f"{s[8:10]}/{s[5:7]}/{s[0:4]}"
    return s


def encode_pdf_base64(pdf_bytes: bytes) -> str:
    """Codifica bytes em base64 ASCII pro campo `arquivos[].base64`."""
    return base64.b64encode(pdf_bytes).decode("ascii")


def validate_arquivo_size(size_bytes: int) -> None:
    """Valida tamanho individual do PDF antes do encode (bail early)."""
    if size_bytes > MAX_BYTES_POR_ARQUIVO:
        raise ValueError(
            f"PDF excede limite AJUS por arquivo "
            f"({size_bytes} bytes > {MAX_BYTES_POR_ARQUIVO} bytes / 10MB)"
        )
