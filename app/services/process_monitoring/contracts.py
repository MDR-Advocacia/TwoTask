from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.utils import format_cnj

from .enums import EvidenceSource, ProcessAnalyticalStatus


class NormalizedMovement(BaseModel):
    code: int | str | None = None
    name: str
    occurred_at: datetime | None = Field(default=None, alias="dataHora")
    complement: dict[str, Any] = Field(default_factory=dict)
    judging_body: str | None = None
    raw_payload: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(populate_by_name=True)


class DataJudProcessSnapshot(BaseModel):
    process_number: str = Field(alias="numeroProcesso")
    tribunal: str | None = None
    tribunal_alias: str | None = None
    instance_level: str | None = Field(default=None, alias="grau")
    procedural_class: str | None = Field(default=None, alias="classe")
    judging_body: str | None = Field(default=None, alias="orgaoJulgador")
    system_name: str | None = Field(default=None, alias="sistema")
    secrecy_level: int | None = Field(default=None, alias="nivelSigilo")
    filed_at: datetime | None = Field(default=None, alias="dataAjuizamento")
    last_update_at: datetime | None = Field(default=None, alias="dataHoraUltimaAtualizacao")
    indexed_at: datetime | None = Field(default=None, alias="@timestamp")
    movements: list[NormalizedMovement] = Field(default_factory=list, alias="movimentos")
    raw_payload: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("process_number")
    @classmethod
    def normalize_process_number(cls, value: str) -> str:
        return format_cnj(value)


class ComunicaPublicationRecord(BaseModel):
    communication_hash: str | None = Field(default=None, alias="hash")
    process_number: str | None = Field(default=None, alias="numeroProcesso")
    tribunal: str | None = Field(default=None, alias="siglaTribunal")
    publication_date: date | None = Field(default=None, alias="dataDisponibilizacao")
    publication_datetime: datetime | None = Field(default=None, alias="dataPublicacao")
    medium: str | None = Field(default=None, alias="meio")
    title: str | None = Field(default=None, alias="titulo")
    text: str | None = Field(default=None, alias="texto")
    certificate_url: str | None = None
    raw_payload: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("process_number")
    @classmethod
    def normalize_process_number(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return format_cnj(value)


class DetectedEvidence(BaseModel):
    source: EvidenceSource
    event_type: str
    description: str
    occurred_at: datetime | None = None
    confidence: float = 0.5
    reference: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProcessEvidenceBundle(BaseModel):
    process_number: str
    tribunal: str | None = None
    decision_events: list[DetectedEvidence] = Field(default_factory=list)
    publication_events: list[DetectedEvidence] = Field(default_factory=list)
    certificate_events: list[DetectedEvidence] = Field(default_factory=list)
    recursal_signals: list[DetectedEvidence] = Field(default_factory=list)
    explicit_transit_events: list[DetectedEvidence] = Field(default_factory=list)
    closure_events: list[DetectedEvidence] = Field(default_factory=list)
    recent_impulses: list[DetectedEvidence] = Field(default_factory=list)
    days_without_relevant_impulse: int | None = None
    raw_sources: dict[str, Any] = Field(default_factory=dict)

    def flattened_evidence(self) -> list[DetectedEvidence]:
        return [
            *self.decision_events,
            *self.publication_events,
            *self.certificate_events,
            *self.recursal_signals,
            *self.explicit_transit_events,
            *self.closure_events,
            *self.recent_impulses,
        ]


class ProcessMaturityAssessment(BaseModel):
    process_number: str
    status: ProcessAnalyticalStatus
    maturity_level: int
    score: float
    confidence: float
    suggested_action: str
    triggered_rules: list[str] = Field(default_factory=list)
    evidence: list[DetectedEvidence] = Field(default_factory=list)


class OperationalQueueSnapshot(BaseModel):
    queue_name: str
    priority: str
    status: str
    suggested_action: str
    maturity_level: int
    score: float
    evidence_snapshot: dict[str, Any] = Field(default_factory=dict)


class MonitoringEvaluation(BaseModel):
    snapshot: DataJudProcessSnapshot
    evidence_bundle: ProcessEvidenceBundle
    assessment: ProcessMaturityAssessment
    operational_queue: OperationalQueueSnapshot
