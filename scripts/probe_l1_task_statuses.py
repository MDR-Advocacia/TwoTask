"""
Probe que lista as tasks de processos no Legal One com seus statusIds
reais, pra validar/derivar o mapeamento ID -> label do dropdown da UI L1.

Uso:
    python scripts/probe_l1_task_statuses.py <lawsuit_id> [<lawsuit_id> ...]

Pra cada processo, imprime:
- Uma linha por task (task_id, statusId, descricao truncada, datas).
- Resumo dos statusIds encontrados nesse processo + label atual no
  sistema (que pode estar errada — esse é o ponto).

No final, imprime um resumo global cobrindo todos os processos.

Como usar o resultado:
1. Roda esse script com 3-5 processos que você conhece e que tenham
   tasks em estados variados (algumas Cumpridas, algumas Pendentes,
   algumas Canceladas, etc.).
2. Abre o L1 web em paralelo (uma aba por processo) e olha o status
   real renderizado em cada task.
3. Pra cada statusId que aparecer no script, anota o label real que o
   L1 mostra. Se o mesmo statusId aparece em tasks com labels
   diferentes no L1, o mapeamento é por outro campo (não é statusId).
4. Manda o resultado pra o agente atualizar L1_STATUS_LABELS_FULL e
   L1_BLOCKING_STATUS_IDS com base em dados reais.
"""
import sys
from collections import defaultdict
from typing import Iterable

# Make sure project root is on sys.path so `app.*` imports resolve
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.legal_one_client import LegalOneApiClient
from app.services.publication_search_service import L1_STATUS_LABELS_FULL


def fetch_tasks_for_lawsuit(client: LegalOneApiClient, lawsuit_id: int) -> list[dict]:
    filter_expr = (
        f"relationships/any(r: r/linkType eq 'Litigation' "
        f"and r/linkId eq {int(lawsuit_id)})"
    )
    return client.search_tasks(
        filter_expression=filter_expr,
        top=30,
        orderby="creationDate desc",
    )


def truncate(text: str | None, n: int) -> str:
    if not text:
        return ""
    text = text.replace("\n", " ").replace("\r", " ").strip()
    return text[: n - 1] + "…" if len(text) > n else text


def print_lawsuit_block(lawsuit_id: int, tasks: list[dict]) -> dict[int, int]:
    print()
    print("=" * 78)
    print(f"Lawsuit {lawsuit_id} — {len(tasks)} task(s)")
    print("=" * 78)
    if not tasks:
        print("  (nenhuma task retornada do L1)")
        return {}

    print(
        f"{'task_id':>8}  {'sId':>3}  {'creation':<19}  {'effEnd':<19}  description"
    )
    counts: dict[int, int] = defaultdict(int)
    for t in tasks:
        sid = t.get("statusId")
        counts[sid] += 1
        print(
            f"{t.get('id', ''):>8}  "
            f"{sid if sid is not None else '?':>3}  "
            f"{(t.get('creationDate') or '')[:19]:<19}  "
            f"{(t.get('effectiveEndDateTime') or '')[:19]:<19}  "
            f"{truncate(t.get('description'), 60)}"
        )

    print()
    print(f"  Resumo statusIds desse processo:")
    for sid, n in sorted(counts.items(), key=lambda kv: (kv[0] is None, kv[0])):
        cur = L1_STATUS_LABELS_FULL.get(sid, "(fora do mapa)")
        print(f"    statusId={sid}  label_atual={cur!r}  ocorrencias={n}")
    return dict(counts)


def main(lawsuit_ids: Iterable[int]) -> int:
    client = LegalOneApiClient()
    global_counts: dict[int, int] = defaultdict(int)
    any_failure = False
    for lid in lawsuit_ids:
        try:
            tasks = fetch_tasks_for_lawsuit(client, lid)
        except Exception as exc:  # noqa: BLE001
            print(f"[ERRO] lawsuit {lid}: {exc}", file=sys.stderr)
            any_failure = True
            continue
        local = print_lawsuit_block(int(lid), tasks)
        for sid, n in local.items():
            global_counts[sid] += n

    print()
    print("=" * 78)
    print("Resumo global (todos os processos)")
    print("=" * 78)
    if not global_counts:
        print("  (nenhuma task retornada)")
    else:
        for sid, n in sorted(
            global_counts.items(), key=lambda kv: (kv[0] is None, kv[0])
        ):
            cur = L1_STATUS_LABELS_FULL.get(sid, "(fora do mapa)")
            print(
                f"  statusId={sid}  label_atual={cur!r}  total={n}"
            )
    print()
    print(
        "Proximo passo: abre o L1 web em paralelo, olha o status real de "
        "cada task e me passa o id->label correto."
    )
    return 0 if not any_failure else 1


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(
            "Uso: python scripts/probe_l1_task_statuses.py <lawsuit_id> [<lawsuit_id> ...]",
            file=sys.stderr,
        )
        sys.exit(2)
    raw_ids: list[int] = []
    for arg in sys.argv[1:]:
        try:
            raw_ids.append(int(arg))
        except ValueError:
            print(f"Ignorando arg nao numerico: {arg!r}", file=sys.stderr)
    if not raw_ids:
        print("Nenhum lawsuit_id valido informado.", file=sys.stderr)
        sys.exit(2)
    sys.exit(main(raw_ids))
