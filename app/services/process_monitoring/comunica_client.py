from datetime import date
from typing import Any

import httpx

from app.core.config import settings

from .contracts import ComunicaPublicationRecord


class ComunicaClient:
    def __init__(
        self,
        base_url: str | None = None,
        timeout_seconds: int | None = None,
    ) -> None:
        self.base_url = (base_url or settings.comunica_base_url).rstrip("/")
        self.timeout_seconds = timeout_seconds or settings.comunica_timeout_seconds

    def fetch_caderno(self, tribunal_code: str, publication_date: date, meio: str | None = None) -> dict[str, Any]:
        endpoint = (
            f"{self.base_url}/api/v1/caderno/"
            f"{tribunal_code}/{publication_date.isoformat()}/{meio or settings.djen_default_meio}"
        )
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.get(endpoint)
            response.raise_for_status()
            return response.json()

    def list_communications(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        endpoint = f"{self.base_url}/api/v1/comunicacao"
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.get(endpoint, params=params or {})
            response.raise_for_status()
            return response.json()

    def fetch_certificate(self, communication_hash: str) -> dict[str, Any]:
        endpoint = f"{self.base_url}/api/v1/comunicacao/{communication_hash}/certidao"
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.get(endpoint)
            response.raise_for_status()
            return response.json()

    def normalize_publications(self, payload: list[dict[str, Any]]) -> list[ComunicaPublicationRecord]:
        return [
            ComunicaPublicationRecord(
                hash=item.get("hash"),
                numeroProcesso=item.get("numeroProcesso"),
                siglaTribunal=item.get("siglaTribunal"),
                dataDisponibilizacao=item.get("dataDisponibilizacao"),
                dataPublicacao=item.get("dataPublicacao"),
                meio=item.get("meio"),
                titulo=item.get("titulo"),
                texto=item.get("texto"),
                certificate_url=item.get("urlCertidao") or item.get("certidaoUrl"),
                raw_payload=item,
            )
            for item in payload
        ]
