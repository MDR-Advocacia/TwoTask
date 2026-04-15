from .contracts import (
    ComunicaPublicationRecord,
    DataJudProcessSnapshot,
    MonitoringEvaluation,
    OperationalQueueSnapshot,
)
from .correlation_service import ProcessCorrelationService
from .enums import ProcessAnalyticalStatus, QueuePriority, QueueStatus
from .scoring_service import ProcessScoringService


class ProcessMonitoringService:
    def __init__(
        self,
        correlation_service: ProcessCorrelationService | None = None,
        scoring_service: ProcessScoringService | None = None,
    ) -> None:
        self.correlation_service = correlation_service or ProcessCorrelationService()
        self.scoring_service = scoring_service or ProcessScoringService()

    def evaluate_process(
        self,
        snapshot: DataJudProcessSnapshot,
        publications: list[ComunicaPublicationRecord],
    ) -> MonitoringEvaluation:
        evidence_bundle = self.correlation_service.build_evidence_bundle(snapshot=snapshot, publications=publications)
        assessment = self.scoring_service.assess(evidence_bundle)
        operational_queue = self._build_operational_queue(assessment)

        return MonitoringEvaluation(
            snapshot=snapshot,
            evidence_bundle=evidence_bundle,
            assessment=assessment,
            operational_queue=operational_queue,
        )

    def _build_operational_queue(self, assessment) -> OperationalQueueSnapshot:
        if assessment.status == ProcessAnalyticalStatus.CLOSURE_CONFIRMED:
            queue_name = "BAIXA_CONFIRMADA"
            priority = QueuePriority.LOW
        elif assessment.status == ProcessAnalyticalStatus.ELIGIBLE_FOR_OPERATIONAL_CLOSURE:
            queue_name = "VALIDACAO_BAIXA"
            priority = QueuePriority.HIGH
        elif assessment.status == ProcessAnalyticalStatus.STRONG_TRANSIT_INDICATIVE:
            queue_name = "VALIDACAO_TRANSITO"
            priority = QueuePriority.HIGH
        elif assessment.status == ProcessAnalyticalStatus.NEAR_TRANSIT:
            queue_name = "MONITORAMENTO_INTENSIVO"
            priority = QueuePriority.MEDIUM
        elif assessment.status == ProcessAnalyticalStatus.RECURSAL_ATTENTION:
            queue_name = "ATENCAO_RECURSAL"
            priority = QueuePriority.HIGH
        elif assessment.status == ProcessAnalyticalStatus.DECISION_EVENT:
            queue_name = "ACOMPANHAMENTO_DECISORIO"
            priority = QueuePriority.MEDIUM
        else:
            queue_name = "MONITORAMENTO_CONTINUO"
            priority = QueuePriority.LOW

        return OperationalQueueSnapshot(
            queue_name=queue_name,
            priority=priority.value,
            status=QueueStatus.PENDING_REVIEW.value,
            suggested_action=assessment.suggested_action,
            maturity_level=assessment.maturity_level,
            score=assessment.score,
            evidence_snapshot={
                "triggered_rules": assessment.triggered_rules,
                "confidence": assessment.confidence,
            },
        )
