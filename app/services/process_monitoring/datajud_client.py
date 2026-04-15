from typing import Any

import httpx

from app.core.config import settings
from app.core.utils import format_cnj

from .contracts import DataJudProcessSnapshot, NormalizedMovement


class DataJudClient:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout_seconds: int | None = None,
    ) -> None:
        self.base_url = (base_url or settings.datajud_base_url).rstrip("/")
        self.api_key = api_key or settings.datajud_api_key
        self.timeout_seconds = timeout_seconds or settings.datajud_timeout_seconds

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise RuntimeError("DATAJUD_API_KEY nao configurada.")
        return {
            "Authorization": self.api_key,
            "Content-Type": "application/json",
        }

    def build_process_lookup_query(self, process_number: str) -> dict[str, Any]:
        return {
            "query": {
                "term": {
                    "numeroProcesso.keyword": format_cnj(process_number),
                }
            },
            "size": 1,
            "sort": [
                {"@timestamp": "desc"},
                {"_id": "asc"},
            ],
        }

    def build_incremental_sync_query(
        self,
        query: dict[str, Any] | None = None,
        search_after: list[Any] | None = None,
        size: int | None = None,
    ) -> dict[str, Any]:
        payload = {
            "query": query or {"match_all": {}},
            "size": size or settings.datajud_default_page_size,
            "sort": [
                {"@timestamp": "asc"},
                {"_id": "asc"},
            ],
        }
        if search_after:
            payload["search_after"] = search_after
        return payload

    def search_processes(self, tribunal_alias: str, payload: dict[str, Any]) -> dict[str, Any]:
        endpoint = f"{self.base_url}/{tribunal_alias}/_search"
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(endpoint, headers=self._headers(), json=payload)
            response.raise_for_status()
            return response.json()

    def fetch_process_by_number(self, tribunal_alias: str, process_number: str) -> DataJudProcessSnapshot | None:
        payload = self.build_process_lookup_query(process_number)
        response = self.search_processes(tribunal_alias=tribunal_alias, payload=payload)
        hits = response.get("hits", {}).get("hits", [])
        if not hits:
            return None
        return self._hit_to_snapshot(tribunal_alias=tribunal_alias, hit=hits[0])

    def fetch_incremental_batch(
        self,
        tribunal_alias: str,
        query: dict[str, Any] | None = None,
        search_after: list[Any] | None = None,
        size: int | None = None,
    ) -> tuple[list[DataJudProcessSnapshot], list[Any] | None, dict[str, Any]]:
        payload = self.build_incremental_sync_query(query=query, search_after=search_after, size=size)
        response = self.search_processes(tribunal_alias=tribunal_alias, payload=payload)
        hits = response.get("hits", {}).get("hits", [])
        snapshots = [self._hit_to_snapshot(tribunal_alias=tribunal_alias, hit=hit) for hit in hits]
        next_cursor = hits[-1].get("sort") if hits else None
        return snapshots, next_cursor, response

    def _hit_to_snapshot(self, tribunal_alias: str, hit: dict[str, Any]) -> DataJudProcessSnapshot:
        source = hit.get("_source", {})
        movements = [
            NormalizedMovement(
                code=movement.get("codigo"),
                name=movement.get("nome", "Movimento sem nome"),
                dataHora=movement.get("dataHora"),
                complement=movement.get("complementosTabelados", {}) or {},
                judging_body=movement.get("orgaoJulgador"),
                raw_payload=movement,
            )
            for movement in source.get("movimentos", []) or []
        ]
        procedural_class = source.get("classe")
        if isinstance(procedural_class, dict):
            procedural_class = procedural_class.get("nome")

        judging_body = source.get("orgaoJulgador")
        if isinstance(judging_body, dict):
            judging_body = judging_body.get("nome")

        return DataJudProcessSnapshot(
            numeroProcesso=source.get("numeroProcesso"),
            tribunal=source.get("tribunal"),
            tribunal_alias=tribunal_alias,
            grau=source.get("grau"),
            classe=procedural_class,
            orgaoJulgador=judging_body,
            sistema=source.get("sistema"),
            nivelSigilo=source.get("nivelSigilo"),
            dataAjuizamento=source.get("dataAjuizamento"),
            dataHoraUltimaAtualizacao=source.get("dataHoraUltimaAtualizacao"),
            **{"@timestamp": source.get("@timestamp")},
            movimentos=movements,
            raw_payload=source,
        )
