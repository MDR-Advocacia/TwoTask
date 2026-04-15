import argparse
import json
import logging
import sys
import unicodedata
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.legal_one_client import LegalOneApiClient


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
LOGGER = logging.getLogger("fix_main_client_position")

CNJ_COLUMN_CANDIDATES = ("cnj", "processo", "identifiernumber")
LAWSUIT_ID_COLUMN_CANDIDATES = ("lawsuitid", "lawsuit_id", "idprocesso", "processid", "lawsuit")


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(text.lower().split())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fix main-client participant positions in Legal One lawsuits."
    )
    parser.add_argument("--input", help="Path to a .xlsx, .csv or .txt file with CNJs or lawsuit ids.")
    parser.add_argument(
        "--cnj",
        action="append",
        default=[],
        help="Single CNJ to process. Can be used multiple times.",
    )
    parser.add_argument(
        "--lawsuit-id",
        action="append",
        default=[],
        type=int,
        help="Single lawsuit id to process. Can be used multiple times.",
    )
    parser.add_argument("--cnj-column", help="Column name that contains CNJs in the input file.")
    parser.add_argument("--lawsuit-id-column", help="Column name that contains lawsuit ids in the input file.")
    parser.add_argument(
        "--participant-type",
        default="Customer",
        help="Participant type to patch. Default: Customer.",
    )
    parser.add_argument(
        "--include-non-main",
        action="store_true",
        help="Also consider participants where isMainParticipant is false.",
    )
    parser.add_argument("--from-position-id", type=int, help="Only patch participants currently in this position id.")
    parser.add_argument(
        "--from-position-name",
        help="Only patch participants currently in this position name.",
    )
    parser.add_argument("--to-position-id", type=int, help="Target position id.")
    parser.add_argument("--to-position-name", help="Target position name.")
    parser.add_argument(
        "--show-positions",
        action="store_true",
        help="List available litigation participant positions and exit.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Max number of lawsuits to inspect from the input payload.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Apply PATCH requests. Without this flag the script runs as dry-run.",
    )
    return parser.parse_args()


def load_client() -> LegalOneApiClient:
    load_dotenv(dotenv_path=ROOT_DIR / ".env", override=True)
    return LegalOneApiClient()


def build_position_maps(client: LegalOneApiClient) -> tuple[Dict[int, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    positions = client.get_litigation_participant_positions()
    by_id = {int(item["id"]): item for item in positions if item.get("id") is not None}
    by_name = {normalize_text(item.get("name")): item for item in positions if item.get("name")}
    return by_id, by_name


def print_positions(by_id: Dict[int, Dict[str, Any]]) -> None:
    for position_id in sorted(by_id):
        item = by_id[position_id]
        print(
            json.dumps(
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "availableForMainClient": item.get("availableForMainClient"),
                    "availableForOtherParticipants": item.get("availableForOtherParticipants"),
                    "availableForResponsible": item.get("availableForResponsible"),
                    "availableForLawsuit": item.get("availableForLawsuit"),
                },
                ensure_ascii=False,
            )
        )


def resolve_position_id(
    *,
    position_id: Optional[int],
    position_name: Optional[str],
    by_id: Dict[int, Dict[str, Any]],
    by_name: Dict[str, Dict[str, Any]],
    field_label: str,
) -> Optional[int]:
    if position_id is not None:
        if position_id not in by_id:
            raise ValueError(f"{field_label} id {position_id} nao existe em LitigationParticipantPositions.")
        return position_id
    if position_name:
        normalized = normalize_text(position_name)
        item = by_name.get(normalized)
        if not item:
            raise ValueError(f"{field_label} name '{position_name}' nao existe em LitigationParticipantPositions.")
        return int(item["id"])
    return None


def read_targets_from_txt(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            if line.isdigit():
                rows.append({"lawsuit_id": int(line)})
            else:
                rows.append({"cnj": line})
    return rows


def resolve_dataframe_column(columns: Iterable[str], explicit_name: Optional[str], candidates: Iterable[str]) -> Optional[str]:
    columns_by_normalized = {normalize_text(column): column for column in columns}
    if explicit_name:
        explicit_key = normalize_text(explicit_name)
        if explicit_key not in columns_by_normalized:
            raise ValueError(f"Coluna '{explicit_name}' nao encontrada no arquivo de entrada.")
        return columns_by_normalized[explicit_key]

    for candidate in candidates:
        if candidate in columns_by_normalized:
            return columns_by_normalized[candidate]
    return None


def read_targets_from_file(path: Path, args: argparse.Namespace) -> List[Dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".txt":
        return read_targets_from_txt(path)

    if suffix == ".csv":
        dataframe = pd.read_csv(path)
    elif suffix in {".xlsx", ".xls"}:
        dataframe = pd.read_excel(path)
    else:
        raise ValueError("Formato de arquivo nao suportado. Use .xlsx, .xls, .csv ou .txt.")

    cnj_column = resolve_dataframe_column(dataframe.columns, args.cnj_column, CNJ_COLUMN_CANDIDATES)
    lawsuit_id_column = resolve_dataframe_column(
        dataframe.columns,
        args.lawsuit_id_column,
        LAWSUIT_ID_COLUMN_CANDIDATES,
    )

    if not cnj_column and not lawsuit_id_column:
        raise ValueError(
            "Nao encontrei uma coluna de CNJ ou de lawsuit id. "
            "Use --cnj-column ou --lawsuit-id-column para apontar a coluna certa."
        )

    rows: List[Dict[str, Any]] = []
    for _, row in dataframe.iterrows():
        item: Dict[str, Any] = {}
        if lawsuit_id_column and pd.notna(row[lawsuit_id_column]):
            try:
                item["lawsuit_id"] = int(row[lawsuit_id_column])
            except (TypeError, ValueError):
                LOGGER.warning("Ignorando linha com lawsuit id invalido: %s", row[lawsuit_id_column])
                continue
        if cnj_column and pd.notna(row[cnj_column]):
            item["cnj"] = str(row[cnj_column]).strip()
        if item:
            rows.append(item)
    return rows


def read_targets(args: argparse.Namespace) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []

    for lawsuit_id in args.lawsuit_id:
        items.append({"lawsuit_id": lawsuit_id})

    for cnj in args.cnj:
        items.append({"cnj": cnj.strip()})

    if args.input:
        items.extend(read_targets_from_file(Path(args.input), args))

    if args.limit is not None:
        items = items[: args.limit]

    if not items:
        raise ValueError("Nenhum processo informado. Use --input, --cnj ou --lawsuit-id.")

    return items


def resolve_lawsuit(item: Dict[str, Any], client: LegalOneApiClient) -> Optional[Dict[str, Any]]:
    lawsuit_id = item.get("lawsuit_id")
    if lawsuit_id is not None:
        try:
            lawsuit = client.get_lawsuit_by_id(int(lawsuit_id), params={"$select": "id,identifierNumber"})
        except Exception as exc:
            LOGGER.warning("Falha ao buscar processo por id %s: %s", lawsuit_id, exc)
            return None
        return {"id": lawsuit["id"], "identifierNumber": lawsuit.get("identifierNumber")}

    cnj = item.get("cnj")
    if not cnj:
        return None

    try:
        lawsuit = client.search_lawsuit_by_cnj(cnj)
    except Exception as exc:
        LOGGER.warning("Falha ao buscar processo por CNJ %s: %s", cnj, exc)
        return None
    if not lawsuit:
        return None
    return {"id": int(lawsuit["id"]), "identifierNumber": lawsuit.get("identifierNumber")}


def build_lawsuit_resolution_cache(
    targets: List[Dict[str, Any]],
    client: LegalOneApiClient,
) -> Dict[str, Dict[str, Any]]:
    cache: Dict[str, Dict[str, Any]] = {}
    cnjs = []
    seen_cnjs = set()

    for item in targets:
        cnj = item.get("cnj")
        if not cnj:
            continue
        normalized = str(cnj).strip()
        if not normalized or normalized in seen_cnjs:
            continue
        seen_cnjs.add(normalized)
        cnjs.append(normalized)

    if not cnjs:
        return cache

    LOGGER.info("Resolvendo %s CNJs em lote.", len(cnjs))
    try:
        matches = client.search_lawsuits_by_cnj_numbers(cnjs)
    except Exception as exc:
        LOGGER.warning("Falha na resolucao em lote de CNJs: %s", exc)
        return cache

    for cnj, lawsuit in matches.items():
        cache[str(cnj).strip()] = {
            "id": int(lawsuit["id"]),
            "identifierNumber": lawsuit.get("identifierNumber"),
        }

    return cache


def build_patch_payload(participant: Dict[str, Any], target_position_id: int) -> Dict[str, Any]:
    return {
        "type": participant["type"],
        "contactId": participant["contactId"],
        "positionId": target_position_id,
        "isMainParticipant": participant["isMainParticipant"],
    }


def main() -> int:
    args = parse_args()
    client = load_client()
    positions_by_id, positions_by_name = build_position_maps(client)

    if args.show_positions:
        print_positions(positions_by_id)
        return 0

    target_position_id = resolve_position_id(
        position_id=args.to_position_id,
        position_name=args.to_position_name,
        by_id=positions_by_id,
        by_name=positions_by_name,
        field_label="Target position",
    )
    if target_position_id is None:
        raise ValueError("Informe --to-position-id ou --to-position-name.")

    source_position_id = resolve_position_id(
        position_id=args.from_position_id,
        position_name=args.from_position_name,
        by_id=positions_by_id,
        by_name=positions_by_name,
        field_label="Source position",
    )

    targets = read_targets(args)
    lawsuit_cache = build_lawsuit_resolution_cache(targets, client)
    summary = {
        "lawsuits_checked": 0,
        "lawsuits_not_found": 0,
        "participants_matched": 0,
        "participants_patched": 0,
        "participants_skipped_same_position": 0,
        "lawsuits_without_match": 0,
    }
    dry_run = not args.execute

    for raw_item in targets:
        summary["lawsuits_checked"] += 1
        cached_lawsuit = None
        if raw_item.get("cnj"):
            cached_lawsuit = lawsuit_cache.get(str(raw_item["cnj"]).strip())
        lawsuit = cached_lawsuit or resolve_lawsuit(raw_item, client)
        if not lawsuit:
            summary["lawsuits_not_found"] += 1
            print(json.dumps({"input": raw_item, "status": "lawsuit_not_found"}, ensure_ascii=False))
            continue

        try:
            participants = client.get_lawsuit_participants(lawsuit["id"])
        except Exception as exc:
            print(
                json.dumps(
                    {
                        "lawsuitId": lawsuit["id"],
                        "cnj": lawsuit.get("identifierNumber"),
                        "status": "participants_fetch_failed",
                        "error": str(exc),
                    },
                    ensure_ascii=False,
                )
            )
            continue
        matches = []
        for participant in participants:
            if participant.get("type") != args.participant_type:
                continue
            if not args.include_non_main and not participant.get("isMainParticipant"):
                continue
            if source_position_id is not None and participant.get("positionId") != source_position_id:
                continue
            matches.append(participant)

        if not matches:
            summary["lawsuits_without_match"] += 1
            print(
                json.dumps(
                    {
                        "lawsuitId": lawsuit["id"],
                        "cnj": lawsuit.get("identifierNumber"),
                        "status": "no_matching_participant",
                    },
                    ensure_ascii=False,
                )
            )
            continue

        for participant in matches:
            summary["participants_matched"] += 1
            current_position_id = participant.get("positionId")
            if current_position_id == target_position_id:
                summary["participants_skipped_same_position"] += 1
                print(
                    json.dumps(
                        {
                            "lawsuitId": lawsuit["id"],
                            "cnj": lawsuit.get("identifierNumber"),
                            "participantId": participant.get("id"),
                            "contactName": participant.get("contactName"),
                            "status": "already_in_target_position",
                            "positionId": current_position_id,
                        },
                        ensure_ascii=False,
                    )
                )
                continue

            payload = build_patch_payload(participant, target_position_id)
            result = {
                "lawsuitId": lawsuit["id"],
                "cnj": lawsuit.get("identifierNumber"),
                "participantId": participant.get("id"),
                "contactId": participant.get("contactId"),
                "contactName": participant.get("contactName"),
                "participantType": participant.get("type"),
                "isMainParticipant": participant.get("isMainParticipant"),
                "fromPositionId": current_position_id,
                "fromPositionName": positions_by_id.get(current_position_id, {}).get("name"),
                "toPositionId": target_position_id,
                "toPositionName": positions_by_id.get(target_position_id, {}).get("name"),
                "dryRun": dry_run,
                "payload": payload,
            }
            if dry_run:
                result["status"] = "would_patch"
                print(json.dumps(result, ensure_ascii=False))
                continue

            success = client.patch_lawsuit_participant(lawsuit["id"], participant["id"], payload)
            result["status"] = "patched" if success else "patch_failed"
            print(json.dumps(result, ensure_ascii=False))
            if success:
                summary["participants_patched"] += 1

    print(json.dumps({"summary": summary, "dryRun": dry_run}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
