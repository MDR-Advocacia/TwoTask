from sqlalchemy.orm import Session

from app.models.batch_execution import BatchExecutionItem


def build_task_fingerprint(
    *,
    process_number: str,
    subtype_identifier: str | int,
    responsible_identifier: str | int,
    due_datetime_iso: str,
    origin_identifier: str | int | None = None,
) -> str:
    normalized_parts = [
        str(process_number or "").strip().lower(),
        str(subtype_identifier or "").strip().lower(),
        str(responsible_identifier or "").strip().lower(),
        str(due_datetime_iso or "").strip().lower(),
        str(origin_identifier or "").strip().lower(),
    ]
    return "|".join(normalized_parts)


def load_successful_fingerprints(db: Session) -> set[str]:
    rows = (
        db.query(BatchExecutionItem.fingerprint)
        .filter(
            BatchExecutionItem.status == "SUCESSO",
            BatchExecutionItem.fingerprint.isnot(None),
        )
        .all()
    )
    return {row[0] for row in rows if row[0]}
