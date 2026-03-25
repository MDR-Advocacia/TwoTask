from pathlib import Path


def validate_spreadsheet_file_metadata(
    filename: str | None,
    content_type: str | None,
    file_size: int,
    *,
    max_size_bytes: int,
    allowed_content_types: set[str],
) -> None:
    if not filename:
        raise ValueError("Nome do arquivo nao informado.")

    if Path(filename).suffix.lower() != ".xlsx":
        raise ValueError("Formato de arquivo invalido. Envie um arquivo .xlsx.")

    if file_size <= 0:
        raise ValueError("O arquivo enviado esta vazio.")

    if file_size > max_size_bytes:
        max_size_mb = max_size_bytes // (1024 * 1024)
        raise ValueError(f"Arquivo muito grande. O limite atual e de {max_size_mb} MB.")

    normalized_content_type = (content_type or "").strip().lower()
    if normalized_content_type and normalized_content_type not in allowed_content_types:
        raise ValueError("Tipo de arquivo invalido para uma planilha .xlsx.")
