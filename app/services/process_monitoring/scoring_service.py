from app.core.config import settings

from .contracts import ProcessEvidenceBundle, ProcessMaturityAssessment
from .enums import ProcessAnalyticalStatus


class ProcessScoringService:
    def __init__(self, idle_window_days: int | None = None) -> None:
        self.idle_window_days = idle_window_days or settings.process_monitoring_idle_window_days

    def assess(self, evidence: ProcessEvidenceBundle) -> ProcessMaturityAssessment:
        score = 0.0
        triggered_rules: list[str] = []

        has_decision = bool(evidence.decision_events)
        has_publication = bool(evidence.publication_events)
        has_certificate = bool(evidence.certificate_events)
        has_recursal = bool(evidence.recursal_signals)
        has_explicit_transit = bool(evidence.explicit_transit_events)
        has_closure_signal = bool(evidence.closure_events)
        has_confirmed_closure = any(item.metadata.get("closure_confirmed") for item in evidence.closure_events)
        idle_window_satisfied = (
            evidence.days_without_relevant_impulse is not None
            and evidence.days_without_relevant_impulse >= self.idle_window_days
        )

        if has_decision:
            score += 18
            triggered_rules.append("HAS_DECISION_EVENT")
        if has_publication:
            score += 12
            triggered_rules.append("HAS_RELEVANT_PUBLICATION")
        if has_certificate:
            score += 10
            triggered_rules.append("HAS_CERTIFICATE")
        if has_explicit_transit:
            score += 34
            triggered_rules.append("HAS_EXPLICIT_TRANSIT")
        if has_closure_signal:
            score += 18
            triggered_rules.append("HAS_CLOSURE_SIGNAL")
        if has_confirmed_closure:
            score += 20
            triggered_rules.append("HAS_CONFIRMED_CLOSURE")
        if idle_window_satisfied:
            score += 12
            triggered_rules.append("IDLE_WINDOW_SATISFIED")
        if has_recursal:
            score -= 16
            triggered_rules.append("HAS_RECURSAL_SIGNAL")
        if evidence.recent_impulses and not idle_window_satisfied:
            score -= 8
            triggered_rules.append("HAS_RECENT_IMPULSE")

        score = round(min(max(score, 0), 100), 2)
        status, maturity_level = self._resolve_status(
            has_decision=has_decision,
            has_publication=has_publication,
            has_certificate=has_certificate,
            has_recursal=has_recursal,
            has_explicit_transit=has_explicit_transit,
            has_confirmed_closure=has_confirmed_closure,
            idle_window_satisfied=idle_window_satisfied,
            score=score,
        )

        confidence = round(min(0.97, 0.38 + (score / 100) * 0.45 + (len(triggered_rules) * 0.015)), 2)

        return ProcessMaturityAssessment(
            process_number=evidence.process_number,
            status=status,
            maturity_level=maturity_level,
            score=score,
            confidence=confidence,
            suggested_action=self._suggested_action(status),
            triggered_rules=triggered_rules,
            evidence=evidence.flattened_evidence(),
        )

    def _resolve_status(
        self,
        *,
        has_decision: bool,
        has_publication: bool,
        has_certificate: bool,
        has_recursal: bool,
        has_explicit_transit: bool,
        has_confirmed_closure: bool,
        idle_window_satisfied: bool,
        score: float,
    ) -> tuple[ProcessAnalyticalStatus, int]:
        if has_confirmed_closure:
            return ProcessAnalyticalStatus.CLOSURE_CONFIRMED, 6
        if has_explicit_transit and (idle_window_satisfied or has_certificate or score >= 75) and not has_recursal:
            return ProcessAnalyticalStatus.ELIGIBLE_FOR_OPERATIONAL_CLOSURE, 5
        if has_explicit_transit or (has_decision and has_publication and has_certificate):
            return ProcessAnalyticalStatus.STRONG_TRANSIT_INDICATIVE, 4
        if has_decision and has_publication and idle_window_satisfied:
            return ProcessAnalyticalStatus.NEAR_TRANSIT, 3
        if has_decision and has_recursal:
            return ProcessAnalyticalStatus.RECURSAL_ATTENTION, 2
        if has_decision:
            return ProcessAnalyticalStatus.DECISION_EVENT, 1
        return ProcessAnalyticalStatus.MONITORED, 0

    def _suggested_action(self, status: ProcessAnalyticalStatus) -> str:
        mapping = {
            ProcessAnalyticalStatus.MONITORED: "Manter monitoramento continuo e aguardar novo evento relevante.",
            ProcessAnalyticalStatus.DECISION_EVENT: "Abrir janela de acompanhamento e aguardar maturacao recursal.",
            ProcessAnalyticalStatus.RECURSAL_ATTENTION: "Direcionar para fila recursal e validar eventual providencia pendente.",
            ProcessAnalyticalStatus.NEAR_TRANSIT: "Priorizar validacao de proximidade de transito em julgado.",
            ProcessAnalyticalStatus.STRONG_TRANSIT_INDICATIVE: "Validar evidencias convergentes antes de encaminhar baixa.",
            ProcessAnalyticalStatus.ELIGIBLE_FOR_OPERATIONAL_CLOSURE: "Encaminhar para fila de baixa operacional com trilha de auditoria.",
            ProcessAnalyticalStatus.CLOSURE_CONFIRMED: "Registrar baixa confirmada e retroalimentar os indicadores de BI.",
        }
        return mapping[status]
