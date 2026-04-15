import unicodedata
from datetime import datetime, timedelta, timezone

from app.core.config import settings

from .contracts import ComunicaPublicationRecord, DataJudProcessSnapshot, DetectedEvidence, ProcessEvidenceBundle
from .enums import EvidenceSource


class ProcessCorrelationService:
    DECISION_KEYWORDS = ("SENTENCA", "ACORDAO", "HOMOLOGACAO", "DECISAO", "JULGAMENTO")
    RECURSAL_KEYWORDS = ("APELACAO", "EMBARGOS", "AGRAVO", "RECURSO", "IMPUGNACAO", "CONTRARRAZOES")
    TRANSIT_KEYWORDS = ("TRANSITO EM JULGADO", "TRANSITADO EM JULGADO")
    CLOSURE_SIGNAL_KEYWORDS = ("ARQUIVAMENTO", "ARQUIVADO", "BAIXA", "EXTINCAO")
    CLOSURE_CONFIRMED_KEYWORDS = (
        "ARQUIVAMENTO DEFINITIVO",
        "ARQUIVADO DEFINITIVAMENTE",
        "BAIXA DEFINITIVA",
        "PROCESSO BAIXADO",
    )

    def __init__(self, recency_window_days: int | None = None) -> None:
        self.recency_window_days = recency_window_days or settings.process_monitoring_recency_window_days

    def build_evidence_bundle(
        self,
        snapshot: DataJudProcessSnapshot,
        publications: list[ComunicaPublicationRecord],
        reference_now: datetime | None = None,
    ) -> ProcessEvidenceBundle:
        now = reference_now or datetime.now(timezone.utc)
        bundle = ProcessEvidenceBundle(
            process_number=snapshot.process_number,
            tribunal=snapshot.tribunal,
            raw_sources={
                "datajud": snapshot.raw_payload,
                "publications_count": len(publications),
            },
        )

        latest_movement_at: datetime | None = None
        recent_cutoff = now - timedelta(days=self.recency_window_days)

        for movement in snapshot.movements:
            normalized_name = self._normalize_text(movement.name)
            latest_movement_at = self._latest_date(latest_movement_at, movement.occurred_at)

            if self._contains_any(normalized_name, self.DECISION_KEYWORDS):
                bundle.decision_events.append(
                    self._build_movement_evidence(
                        event_type="DECISION_EVENT",
                        description=movement.name,
                        occurred_at=movement.occurred_at,
                        movement_code=movement.code,
                        source=EvidenceSource.DATAJUD,
                    )
                )

            if self._contains_any(normalized_name, self.RECURSAL_KEYWORDS):
                bundle.recursal_signals.append(
                    self._build_movement_evidence(
                        event_type="RECURSAL_SIGNAL",
                        description=movement.name,
                        occurred_at=movement.occurred_at,
                        movement_code=movement.code,
                        source=EvidenceSource.DATAJUD,
                    )
                )

            if self._contains_any(normalized_name, self.TRANSIT_KEYWORDS):
                bundle.explicit_transit_events.append(
                    self._build_movement_evidence(
                        event_type="EXPLICIT_TRANSIT",
                        description=movement.name,
                        occurred_at=movement.occurred_at,
                        movement_code=movement.code,
                        source=EvidenceSource.DATAJUD,
                    )
                )

            closure_keyword = self._matched_keyword(normalized_name, self.CLOSURE_SIGNAL_KEYWORDS)
            if closure_keyword:
                bundle.closure_events.append(
                    self._build_movement_evidence(
                        event_type="CLOSURE_SIGNAL",
                        description=movement.name,
                        occurred_at=movement.occurred_at,
                        movement_code=movement.code,
                        source=EvidenceSource.DATAJUD,
                        metadata={
                            "matched_keyword": closure_keyword,
                            "closure_confirmed": self._contains_any(
                                normalized_name,
                                self.CLOSURE_CONFIRMED_KEYWORDS,
                            ),
                        },
                    )
                )

            if movement.occurred_at and movement.occurred_at >= recent_cutoff:
                bundle.recent_impulses.append(
                    self._build_movement_evidence(
                        event_type="RECENT_IMPULSE",
                        description=movement.name,
                        occurred_at=movement.occurred_at,
                        movement_code=movement.code,
                        source=EvidenceSource.DATAJUD,
                    )
                )

        for publication in publications:
            combined_text = self._normalize_text(" ".join(filter(None, [publication.title, publication.text])))
            publication_source = EvidenceSource.DJEN if publication.medium else EvidenceSource.COMUNICA
            occurred_at = publication.publication_datetime

            if self._contains_any(combined_text, self.DECISION_KEYWORDS):
                bundle.publication_events.append(
                    DetectedEvidence(
                        source=publication_source,
                        event_type="PUBLICATION_EVENT",
                        description=publication.title or "Publicacao relevante",
                        occurred_at=occurred_at,
                        confidence=0.62,
                        reference=publication.communication_hash,
                        metadata=publication.raw_payload,
                    )
                )

            if "CERTIDAO" in combined_text or publication.certificate_url:
                bundle.certificate_events.append(
                    DetectedEvidence(
                        source=publication_source,
                        event_type="CERTIFICATE_EVENT",
                        description=publication.title or "Certidao correlacionada",
                        occurred_at=occurred_at,
                        confidence=0.74,
                        reference=publication.communication_hash,
                        metadata={
                            **publication.raw_payload,
                            "certificate_url": publication.certificate_url,
                        },
                    )
                )

            if self._contains_any(combined_text, self.RECURSAL_KEYWORDS):
                bundle.recursal_signals.append(
                    DetectedEvidence(
                        source=publication_source,
                        event_type="RECURSAL_PUBLICATION",
                        description=publication.title or "Publicacao recursal",
                        occurred_at=occurred_at,
                        confidence=0.58,
                        reference=publication.communication_hash,
                        metadata=publication.raw_payload,
                    )
                )

            if self._contains_any(combined_text, self.TRANSIT_KEYWORDS):
                bundle.explicit_transit_events.append(
                    DetectedEvidence(
                        source=publication_source,
                        event_type="TRANSIT_PUBLICATION",
                        description=publication.title or "Publicacao com indicio de transito em julgado",
                        occurred_at=occurred_at,
                        confidence=0.8,
                        reference=publication.communication_hash,
                        metadata=publication.raw_payload,
                    )
                )

            closure_keyword = self._matched_keyword(combined_text, self.CLOSURE_SIGNAL_KEYWORDS)
            if closure_keyword:
                bundle.closure_events.append(
                    DetectedEvidence(
                        source=publication_source,
                        event_type="CLOSURE_PUBLICATION",
                        description=publication.title or "Publicacao com indicio de baixa",
                        occurred_at=occurred_at,
                        confidence=0.72,
                        reference=publication.communication_hash,
                        metadata={
                            **publication.raw_payload,
                            "matched_keyword": closure_keyword,
                            "closure_confirmed": self._contains_any(
                                combined_text,
                                self.CLOSURE_CONFIRMED_KEYWORDS,
                            ),
                        },
                    )
                )

        if latest_movement_at:
            bundle.days_without_relevant_impulse = max((now.date() - latest_movement_at.date()).days, 0)

        return bundle

    def _build_movement_evidence(
        self,
        event_type: str,
        description: str,
        occurred_at: datetime | None,
        movement_code: int | str | None,
        source: EvidenceSource,
        metadata: dict | None = None,
    ) -> DetectedEvidence:
        return DetectedEvidence(
            source=source,
            event_type=event_type,
            description=description,
            occurred_at=occurred_at,
            confidence=0.68,
            reference=str(movement_code) if movement_code is not None else None,
            metadata=metadata or {},
        )

    def _normalize_text(self, value: str | None) -> str:
        if not value:
            return ""
        normalized = unicodedata.normalize("NFKD", value)
        ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
        return " ".join(ascii_only.upper().split())

    def _contains_any(self, haystack: str, needles: tuple[str, ...]) -> bool:
        return any(needle in haystack for needle in needles)

    def _matched_keyword(self, haystack: str, needles: tuple[str, ...]) -> str | None:
        for needle in needles:
            if needle in haystack:
                return needle
        return None

    def _latest_date(self, current: datetime | None, candidate: datetime | None) -> datetime | None:
        if current is None:
            return candidate
        if candidate is None:
            return current
        return max(current, candidate)
