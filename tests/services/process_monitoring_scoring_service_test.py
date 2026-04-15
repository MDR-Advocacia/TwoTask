from datetime import datetime, timedelta, timezone

from app.services.process_monitoring import (
    ComunicaPublicationRecord,
    DataJudProcessSnapshot,
    NormalizedMovement,
    ProcessAnalyticalStatus,
    ProcessCorrelationService,
    ProcessMonitoringService,
    ProcessScoringService,
)


def _build_snapshot(movements: list[NormalizedMovement]) -> DataJudProcessSnapshot:
    return DataJudProcessSnapshot(
        numeroProcesso="00012345620248160001",
        tribunal="TJCE",
        tribunal_alias="api_publica_tjce",
        grau="G1",
        classe="Cumprimento de Sentenca",
        orgaoJulgador="1a Vara Civel",
        movimentos=movements,
        raw_payload={"numeroProcesso": "00012345620248160001"},
    )


def test_explicit_transit_generates_operational_closure_queue() -> None:
    now = datetime.now(timezone.utc)
    snapshot = _build_snapshot(
        [
            NormalizedMovement(
                code=123,
                name="Transito em julgado certificado",
                dataHora=now - timedelta(days=20),
            ),
            NormalizedMovement(
                code=456,
                name="Sentenca homologatoria",
                dataHora=now - timedelta(days=40),
            ),
        ]
    )
    publications = [
        ComunicaPublicationRecord(
            hash="abc123",
            numeroProcesso="00012345620248160001",
            siglaTribunal="TJCE",
            dataPublicacao=now - timedelta(days=19),
            titulo="Certidao de transito em julgado",
            texto="Certidao expedida nos autos.",
            certificate_url="https://example.com/certidao",
            raw_payload={"hash": "abc123"},
        )
    ]

    correlation = ProcessCorrelationService(recency_window_days=10)
    evidence = correlation.build_evidence_bundle(snapshot=snapshot, publications=publications, reference_now=now)
    assessment = ProcessScoringService(idle_window_days=15).assess(evidence)
    evaluation = ProcessMonitoringService(correlation_service=correlation).evaluate_process(snapshot, publications)

    assert evidence.days_without_relevant_impulse == 20
    assert assessment.status == ProcessAnalyticalStatus.ELIGIBLE_FOR_OPERATIONAL_CLOSURE
    assert assessment.maturity_level == 5
    assert evaluation.operational_queue.queue_name == "VALIDACAO_BAIXA"


def test_confirmed_closure_moves_process_to_level_six() -> None:
    now = datetime.now(timezone.utc)
    snapshot = _build_snapshot(
        [
            NormalizedMovement(
                code=999,
                name="Arquivamento definitivo",
                dataHora=now - timedelta(days=5),
            )
        ]
    )

    evaluation = ProcessMonitoringService().evaluate_process(snapshot, [])

    assert evaluation.assessment.status == ProcessAnalyticalStatus.CLOSURE_CONFIRMED
    assert evaluation.assessment.maturity_level == 6
    assert evaluation.operational_queue.queue_name == "BAIXA_CONFIRMADA"


def test_decision_with_recursal_signal_stays_in_attention_queue() -> None:
    now = datetime.now(timezone.utc)
    snapshot = _build_snapshot(
        [
            NormalizedMovement(
                code=321,
                name="Sentenca proferida",
                dataHora=now - timedelta(days=3),
            ),
            NormalizedMovement(
                code=654,
                name="Apelacao interposta",
                dataHora=now - timedelta(days=1),
            ),
        ]
    )

    evaluation = ProcessMonitoringService().evaluate_process(snapshot, [])

    assert evaluation.assessment.status == ProcessAnalyticalStatus.RECURSAL_ATTENTION
    assert evaluation.assessment.maturity_level == 2
    assert evaluation.operational_queue.queue_name == "ATENCAO_RECURSAL"
