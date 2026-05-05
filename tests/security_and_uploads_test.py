from app.core.uploads import validate_spreadsheet_file_metadata
from app.services.batch_task_creation_service import BatchTaskCreationService


def test_protected_routes_require_authentication(client):
    # /sectors foi removido em sqd003 (squads agora ficam por escritorio,
    # nao por setor). Trocamos pelo /squads que tambem e protegido.
    response = client.get("/api/v1/squads")

    assert response.status_code == 401


def test_validate_spreadsheet_file_metadata_accepts_valid_xlsx():
    validate_spreadsheet_file_metadata(
        "tarefas.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        1024,
        max_size_bytes=5 * 1024 * 1024,
        allowed_content_types={
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/octet-stream",
        },
    )


def test_validate_spreadsheet_file_metadata_rejects_invalid_extension():
    try:
        validate_spreadsheet_file_metadata(
            "tarefas.csv",
            "text/csv",
            1024,
            max_size_bytes=5 * 1024 * 1024,
            allowed_content_types={"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
        )
    except ValueError as exc:
        assert ".xlsx" in str(exc)
    else:
        raise AssertionError("Esperava ValueError para extensao invalida.")


def test_validate_spreadsheet_file_metadata_rejects_large_files():
    try:
        validate_spreadsheet_file_metadata(
            "tarefas.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            6 * 1024 * 1024,
            max_size_bytes=5 * 1024 * 1024,
            allowed_content_types={"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
        )
    except ValueError as exc:
        assert "limite" in str(exc)
    else:
        raise AssertionError("Esperava ValueError para arquivo acima do limite.")


def test_interactive_deadline_uses_supplied_time():
    deadline_iso = BatchTaskCreationService._build_interactive_deadline_iso("2026-03-18", "08:30")

    assert deadline_iso == "2026-03-18T11:30:00Z"
