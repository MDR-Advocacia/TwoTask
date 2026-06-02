"""
Probe one-shot pra validar viabilidade de listar e baixar documentos do
GED do Legal One via API. Roda 3 testes em sequencia:

  Teste 1 (H1): GET /documents?$filter=relationships/any(r: r/link eq
    'Litigation' and r/linkItem/id eq {id}) and typeId eq 'type_17'
    -> hipotese mais provavel (mesmo padrao usado em /tasks no nosso codigo)

  Teste 2 (H2, fallback): GET /documents?$filter=litigationId eq {id}
    -> so roda se Teste 1 falhar com 400 (property not found)

  Teste 3 (download oficial TR, 2 passos):
    a) GET /documents/{doc_id}?$select=generateUrlDownload,archive
    b) GET na URL retornada (com Bearer) -> bytes do arquivo

Uso:
    python scripts/probe_l1_documents.py --cnj <CNJ>
    python scripts/probe_l1_documents.py --lawsuit-id <id>
    python scripts/probe_l1_documents.py --lawsuit-id <id> --type-id type_17
    python scripts/probe_l1_documents.py --doc-id <id>   # pula pro Teste 3

Resultado salva PDF baixado em /tmp/probe_l1_doc_<doc_id>.<ext> pra inspecao.

Como rodar dentro do container:
    docker exec onetask-api-1 sh -c "cd /app && python scripts/probe_l1_documents.py --cnj 0001234-56.7890.1.12.3456"
"""
import argparse
import json
import os
import sys
from urllib.parse import quote, urlparse

# Make sure project root is on sys.path so `app.*` imports resolve
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.legal_one_client import LegalOneApiClient


def banner(title: str) -> None:
    print()
    print("=" * 78)
    print(f"  {title}")
    print("=" * 78)


def pretty_json(payload, limit_chars: int = 3000) -> str:
    try:
        s = json.dumps(payload, indent=2, ensure_ascii=False)
    except Exception:
        s = str(payload)
    if len(s) > limit_chars:
        s = s[:limit_chars] + f"\n... [truncado em {limit_chars} chars]"
    return s


def resolve_lawsuit_id_from_cnj(client: LegalOneApiClient, cnj: str) -> int | None:
    banner(f"Resolvendo CNJ -> lawsuit_id ({cnj})")
    try:
        result = client.search_lawsuits_by_cnj_numbers([cnj])
    except Exception as exc:
        print(f"  ERRO ao resolver CNJ: {exc}")
        return None
    if not result:
        print("  Nenhum lawsuit encontrado pra esse CNJ.")
        return None
    for key, ls in result.items():
        lid = ls.get("id")
        print(f"  Encontrado: cnj_normalized={key}  lawsuit_id={lid}  identifierNumber={ls.get('identifierNumber')}")
        if lid:
            return int(lid)
    return None


def run_h1_relationships(
    client: LegalOneApiClient, lawsuit_id: int, type_id: str | None
) -> tuple[int, list[dict]]:
    banner(f"TESTE 1 (H1) — relationships/any  lawsuit={lawsuit_id}  type_id={type_id}")
    filter_parts = [
        f"relationships/any(r: r/link eq 'Litigation' and r/linkItem/id eq {int(lawsuit_id)})"
    ]
    if type_id:
        filter_parts.append(f"typeId eq '{type_id}'")
    filter_str = " and ".join(filter_parts)
    qs = (
        f"$filter={quote(filter_str, safe='')}"
        f"&$select=id,archive,typeId"
        f"&$top=20"
    )
    url = f"{client.base_url}/documents?{qs}"
    print(f"  URL: {url}")
    try:
        resp = client._authenticated_request("GET", url)
    except Exception as exc:
        print(f"  EXCEPTION: {exc}")
        return 0, []
    print(f"  HTTP {resp.status_code}")
    if resp.status_code >= 400:
        print(f"  Body (truncado): {resp.text[:1500]}")
        return resp.status_code, []
    payload = resp.json() or {}
    items = payload.get("value") or payload.get("items") or []
    print(f"  {len(items)} item(ns) retornado(s). Amostra:")
    print(pretty_json(items[:5]))
    return resp.status_code, items


def run_h2_litigation_id(
    client: LegalOneApiClient, lawsuit_id: int, type_id: str | None
) -> tuple[int, list[dict]]:
    banner(f"TESTE 2 (H2 fallback) — litigationId direto  lawsuit={lawsuit_id}  type_id={type_id}")
    filter_parts = [f"litigationId eq {int(lawsuit_id)}"]
    if type_id:
        filter_parts.append(f"typeId eq '{type_id}'")
    filter_str = " and ".join(filter_parts)
    qs = (
        f"$filter={quote(filter_str, safe='')}"
        f"&$select=id,archive,typeId"
        f"&$top=20"
    )
    url = f"{client.base_url}/documents?{qs}"
    print(f"  URL: {url}")
    try:
        resp = client._authenticated_request("GET", url)
    except Exception as exc:
        print(f"  EXCEPTION: {exc}")
        return 0, []
    print(f"  HTTP {resp.status_code}")
    if resp.status_code >= 400:
        print(f"  Body (truncado): {resp.text[:1500]}")
        return resp.status_code, []
    payload = resp.json() or {}
    items = payload.get("value") or payload.get("items") or []
    print(f"  {len(items)} item(ns) retornado(s). Amostra:")
    print(pretty_json(items[:5]))
    return resp.status_code, items


def run_h3_litigation_navigation(
    client: LegalOneApiClient, lawsuit_id: int
) -> tuple[int, list[dict]]:
    banner(f"TESTE EXTRA (H3) — navegacao OData /Litigations({lawsuit_id})/Documents")
    url = f"{client.base_url}/Litigations({int(lawsuit_id)})/Documents?$top=20"
    print(f"  URL: {url}")
    try:
        resp = client._authenticated_request("GET", url)
    except Exception as exc:
        print(f"  EXCEPTION: {exc}")
        return 0, []
    print(f"  HTTP {resp.status_code}")
    if resp.status_code >= 400:
        print(f"  Body (truncado): {resp.text[:1500]}")
        return resp.status_code, []
    payload = resp.json() or {}
    items = payload.get("value") or payload.get("items") or []
    print(f"  {len(items)} item(ns) retornado(s). Amostra:")
    print(pretty_json(items[:5]))
    return resp.status_code, items


def run_download(client: LegalOneApiClient, doc_id: int) -> None:
    banner(f"TESTE 3 — Download oficial TR (2 passos)  doc_id={doc_id}")

    # 3a — pegar generateUrlDownload
    url_a = (
        f"{client.base_url}/documents/{int(doc_id)}"
        f"?$select={quote('generateUrlDownload,archive', safe='')}"
    )
    print(f"  [3a] GET {url_a}")
    try:
        resp_a = client._authenticated_request("GET", url_a)
    except Exception as exc:
        print(f"  EXCEPTION em 3a: {exc}")
        return
    print(f"  [3a] HTTP {resp_a.status_code}")
    if resp_a.status_code >= 400:
        print(f"  Body: {resp_a.text[:1500]}")
        return
    info = resp_a.json() or {}
    print(f"  [3a] Resposta:\n{pretty_json(info)}")

    download_url = info.get("generateUrlDownload")
    archive = info.get("archive") or f"doc_{doc_id}.bin"
    if not download_url:
        print("  [3a] ERRO: payload nao tem 'generateUrlDownload'. Abortando download.")
        return

    # 3b — baixar bytes
    print(f"  [3b] GET {download_url}  (Bearer)")
    try:
        resp_b = client._authenticated_request("GET", download_url, stream=True)
    except Exception as exc:
        print(f"  EXCEPTION em 3b: {exc}")
        return
    print(f"  [3b] HTTP {resp_b.status_code}")
    if resp_b.status_code >= 400:
        print(f"  Body: {resp_b.text[:1500] if resp_b.content else '<vazio>'}")
        return

    content = resp_b.content
    content_type = resp_b.headers.get("Content-Type", "?")
    content_length = resp_b.headers.get("Content-Length", "?")
    print(f"  [3b] Content-Type={content_type}  Content-Length={content_length}  bytes_real={len(content)}")

    # detecta extensao a partir do archive ou do content-type
    ext = "bin"
    if "." in archive:
        ext = archive.rsplit(".", 1)[-1].lower()
    elif "pdf" in content_type.lower():
        ext = "pdf"

    out_path = f"/tmp/probe_l1_doc_{doc_id}.{ext}"
    try:
        with open(out_path, "wb") as f:
            f.write(content)
        print(f"  [3b] Salvo em: {out_path}")
        # checa magic bytes pra confirmar que e' o que diz ser
        if ext == "pdf":
            magic_ok = content[:4] == b"%PDF"
            print(f"  [3b] Magic bytes PDF (%PDF): {'OK' if magic_ok else 'FALHA'}")
    except Exception as exc:
        print(f"  ERRO ao salvar: {exc}")


def resolve_office_by_path(path_query: str) -> tuple[int | None, str | None]:
    """Busca office no DB local por path (hierarquia, ex: 'Master / Réu')."""
    from app.db.session import SessionLocal
    from app.models.legal_one import LegalOneOffice

    db = SessionLocal()
    try:
        # tenta path exato primeiro
        office = (
            db.query(LegalOneOffice)
            .filter(LegalOneOffice.path == path_query)
            .first()
        )
        if office:
            return int(office.external_id), office.path
        # fallback: ILIKE com fragmento, lista candidatos
        candidates = (
            db.query(LegalOneOffice)
            .filter(LegalOneOffice.path.ilike(f"%{path_query}%"))
            .limit(15)
            .all()
        )
        if candidates:
            print(f"  Nenhum office com path EXATO '{path_query}'. Candidatos parciais:")
            for o in candidates:
                print(
                    f"    external_id={o.external_id}  path={o.path!r}  active={o.is_active}"
                )
        return None, None
    finally:
        db.close()


def list_documents_global_by_type(
    client: LegalOneApiClient, type_name: str, max_pages: int = 2000
) -> tuple[int, list[dict]]:
    """
    Lista TODOS os documents do tenant cujo campo `type` == type_name.
    Importante: filter por `typeId` retorna 500 (typeId vem null no GET
    apesar de ser exigido no POST). Usar `type` (string descritiva) funciona.
    Ex: type_name = 'Peça processual / Contestação'

    L1 limita $top=30 e NAO retorna @odata.nextLink, entao paginamos via $skip.
    Usa _request_with_retry (que respeita o rate limiter global e retenta em 429).
    """
    import time as _t
    import requests

    items_all: list[dict] = []
    skip = 0
    top = 30
    first_status = 200
    t0 = _t.monotonic()
    page = 0
    for page in range(max_pages):
        filter_q = quote(f"type eq '{type_name}'", safe="")
        url = (
            f"{client.base_url}/documents"
            f"?$filter={filter_q}"
            f"&$expand=relationships"
            f"&$top={top}"
            f"&$skip={skip}"
            f"&$count=true"
        )
        try:
            resp = client._request_with_retry("GET", url)
        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else 0
            body = exc.response.text[:500] if exc.response is not None else ""
            if page == 0:
                first_status = status
                print(f"    pagina 1 HTTP {status} (terminal): {body}")
                return status, []
            print(f"    pagina {page+1} HTTP {status} (terminal): {body}")
            return first_status, items_all
        except Exception as exc:
            print(f"    EXCEPTION na pagina {page+1}: {exc}")
            return first_status, items_all
        if page == 0:
            try:
                total_server = (resp.json() or {}).get("@odata.count")
                if total_server is not None:
                    print(f"    @odata.count (servidor diz): {total_server}")
            except Exception:
                pass
        items = (resp.json() or {}).get("value", [])
        items_all.extend(items)
        if len(items) < top:
            break
        skip += top
        if (page + 1) % 20 == 0:
            print(f"    ...pagina {page+1}, acumulado={len(items_all)} ({_t.monotonic()-t0:.1f}s)")
    print(f"    total paginas processadas={page+1}, total docs={len(items_all)} ({_t.monotonic()-t0:.1f}s)")
    return first_status, items_all


def fetch_all_lawsuit_ids_by_office_manual(
    client: LegalOneApiClient, office_id: int, max_pages: int = 2000
) -> set[int]:
    """
    Versao independente: pagina manualmente via $skip ja' que o
    _paginated_catalog_loader do client depende de @odata.nextLink (que L1 nao
    retorna). Usa _request_with_retry (rate limit + retry em 429).
    """
    import time as _t
    import requests

    ids: set[int] = set()
    top = 30
    t0 = _t.monotonic()
    page = 0
    for endpoint in ("/Lawsuits", "/Litigations"):
        skip = 0
        endpoint_ids_before = len(ids)
        endpoint_first_status = 200
        for page in range(max_pages):
            filter_q = quote(f"responsibleOfficeId eq {int(office_id)}", safe="")
            url = (
                f"{client.base_url}{endpoint}"
                f"?$filter={filter_q}"
                f"&$select=id"
                f"&$top={top}"
                f"&$skip={skip}"
                f"&$count=true"
            )
            try:
                resp = client._request_with_retry("GET", url)
            except requests.exceptions.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else 0
                if page == 0:
                    endpoint_first_status = status
                    print(f"    {endpoint} pagina 1 HTTP {status} (terminal) — tentando proximo endpoint")
                else:
                    print(f"    {endpoint} pagina {page+1} HTTP {status} (terminal). Stop.")
                break
            except Exception as exc:
                print(f"    EXCEPTION em {endpoint} pagina {page+1}: {exc}")
                break
            if page == 0 and endpoint == "/Lawsuits":
                try:
                    total_server = (resp.json() or {}).get("@odata.count")
                    if total_server is not None:
                        print(f"    @odata.count em {endpoint}: {total_server}")
                except Exception:
                    pass
            items = (resp.json() or {}).get("value", [])
            for it in items:
                lid = it.get("id")
                if lid is not None:
                    try:
                        ids.add(int(lid))
                    except (TypeError, ValueError):
                        pass
            if len(items) < top:
                break
            skip += top
            if (page + 1) % 20 == 0:
                print(f"    ...{endpoint} pagina {page+1}, acumulado={len(ids)} ({_t.monotonic()-t0:.1f}s)")
        if len(ids) > endpoint_ids_before:
            break
    print(f"    total IDs do office: {len(ids)} ({_t.monotonic()-t0:.1f}s)")
    return ids


def extract_litigation_id_from_relationships(rels) -> int | None:
    """Pega o linkItem.id onde link == 'Litigation' (case-insensitive)."""
    for r in rels or []:
        link = (r.get("link") or r.get("linkType") or "").lower()
        if link == "litigation":
            li = r.get("linkItem") or {}
            lid = li.get("id") or r.get("linkId")
            if lid:
                try:
                    return int(lid)
                except (TypeError, ValueError):
                    pass
    return None


def run_office_contestacao_count(
    client: LegalOneApiClient, office_id: int, type_name: str
) -> None:
    """KPI: quantos processos do office tem documento com type=type_name."""
    import time as _t

    banner(f"CONTAGEM POR ESCRITORIO  office_id={office_id}  type='{type_name}'")

    # Passo 1 — lawsuit_ids do escritorio (paginacao manual independente, ja
    # que client.fetch_lawsuit_ids_by_office esta sub-relatando: depende de
    # @odata.nextLink que L1 nao retorna, entao para na pagina 1 com so 30 IDs).
    print("  [1/3] Buscando TODOS os lawsuit_ids do escritorio (paginacao manual)...")
    t1 = _t.monotonic()
    try:
        office_lawsuits = fetch_all_lawsuit_ids_by_office_manual(client, office_id)
    except Exception as exc:
        print(f"    ERRO: {exc}")
        return
    if not office_lawsuits:
        print("    Escritorio sem processos. Abortando.")
        return

    # Passo 2 — Estrategia A: lista TODOS docs do tenant com type_id
    print(f"  [2/3] Listando documents type='{type_name}' do tenant (paginado)...")
    status, docs = list_documents_global_by_type(client, type_name)
    if status >= 400 or not docs:
        print()
        print("  Estrategia A (1 query global) falhou ou trouxe vazio.")
        print("  Caminho alternativo (estrategia B = chunked OR por lawsuit_id) nao foi")
        print("  implementado nesse probe — se A falhar com 400, vale evoluir o script.")
        return

    # Passo 3 — extrair lawsuit_ids do relationships e cruzar
    print("  [3/3] Cruzando relationships com lawsuit_ids do escritorio...")
    docs_lawsuits: set[int] = set()
    docs_sem_rel = 0
    for d in docs:
        lid = extract_litigation_id_from_relationships(d.get("relationships"))
        if lid is None:
            docs_sem_rel += 1
        else:
            docs_lawsuits.add(lid)
    print(f"    lawsuit_ids distintos com type='{type_name}' no tenant todo: {len(docs_lawsuits)}")
    if docs_sem_rel:
        print(f"    documents sem relationships parseavel: {docs_sem_rel}")

    intersect = office_lawsuits & docs_lawsuits
    total = len(office_lawsuits)
    com = len(intersect)
    sem = total - com
    pct = (com / total * 100) if total else 0.0

    print()
    print(f"  ┌─ RESULTADO ─────────────────────────────────────")
    print(f"  │ Total processos do escritorio:          {total:>6}")
    print(f"  │ Processos COM contestacao ({type_name[:30]}):    {com:>6}")
    print(f"  │ Processos SEM contestacao:              {sem:>6}")
    print(f"  │ Cobertura:                              {pct:>5.1f}%")
    print(f"  └─────────────────────────────────────────────────")

    # Salva lista completa em arquivo pra nao perder
    out_json = f"/tmp/contestacao_office_{office_id}_lawsuit_ids.json"
    try:
        import json as _json
        with open(out_json, "w") as f:
            _json.dump(sorted(intersect), f)
        print()
        print(f"  Lista completa salva em: {out_json}")
    except Exception as exc:
        print(f"  Falha ao salvar lista: {exc}")

    # Resolve lawsuit_id -> CNJ via fetch_lawsuits_by_ids (batch, cache 24h)
    intersect_list = list(intersect)
    if intersect_list:
        print()
        print(f"  Resolvendo {len(intersect_list)} lawsuit_ids -> CNJ...")
        t_resolve = _t.monotonic()
        try:
            enriched = client.fetch_lawsuits_by_ids(intersect_list)
        except Exception as exc:
            enriched = {}
            print(f"    ERRO na resolucao: {exc}")
        print(f"    Resolvidos: {len(enriched)} ({_t.monotonic()-t_resolve:.1f}s)")

        print()
        print(f"  ┌─ CNJs DOS PROCESSOS COM CONTESTAÇÃO ────────────────────────────────")
        # Ordena por CNJ pra ficar legivel
        rows = []
        for lid in intersect_list:
            info = enriched.get(int(lid)) or {}
            cnj = info.get("identifierNumber") or "<sem identifierNumber>"
            rows.append((cnj, lid))
        rows.sort(key=lambda r: r[0])
        for i, (cnj, lid) in enumerate(rows, 1):
            print(f"  │ {i:3d}. {cnj:<30s}  lawsuit_id={lid}")
        print(f"  └─────────────────────────────────────────────────────────────────────")

        # Salva CSV pra abrir no Excel se quiser
        try:
            out_csv = f"/tmp/contestacao_office_{office_id}_cnjs.csv"
            with open(out_csv, "w", encoding="utf-8") as f:
                f.write("cnj,lawsuit_id\n")
                for cnj, lid in rows:
                    f.write(f"{cnj},{lid}\n")
            print()
            print(f"  CSV salvo em: {out_csv}  (use 'docker cp' pra extrair)")
        except Exception as exc:
            print(f"  Falha ao salvar CSV: {exc}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Probe Legal One Documents API")
    ap.add_argument("--cnj", help="CNJ do processo (sera resolvido pra lawsuit_id)")
    ap.add_argument("--lawsuit-id", type=int, help="lawsuit_id direto (pula resolucao por CNJ)")
    ap.add_argument(
        "--type-id",
        default="type_17",
        help="typeId do GED a filtrar (default: type_17 = Contestacao). Use '' pra nao filtrar.",
    )
    ap.add_argument(
        "--doc-id",
        type=int,
        help="Se fornecido, pula direto pro Teste 3 (download) com esse doc_id.",
    )
    ap.add_argument(
        "--office-path",
        help="Path hierarquico do escritorio (ex: 'Master / Reu') — resolve no DB local.",
    )
    ap.add_argument(
        "--office-id",
        type=int,
        help="external_id do escritorio direto (pula resolucao por path).",
    )
    ap.add_argument(
        "--type-name",
        default="Peça processual / Contestação",
        help="Campo `type` (string descritiva) pra filtrar /documents. Default: 'Peça processual / Contestação'.",
    )
    args = ap.parse_args()

    client = LegalOneApiClient()
    print(f"base_url = {client.base_url}")

    # Modo "contagem por escritorio"
    if args.office_path or args.office_id:
        office_id = args.office_id
        if not office_id and args.office_path:
            banner(f"Resolvendo office '{args.office_path}' no DB local")
            office_id, resolved_path = resolve_office_by_path(args.office_path)
            if not office_id:
                print("ERRO: office nao encontrado. Tente outro --office-path ou use --office-id.")
                sys.exit(2)
            print(f"  Resolvido: external_id={office_id}  path='{resolved_path}'")
        run_office_contestacao_count(client, office_id, args.type_name)
        return

    # Modo "so download": pula direto pro Teste 3
    if args.doc_id:
        run_download(client, args.doc_id)
        return

    # Resolve lawsuit_id
    lawsuit_id = args.lawsuit_id
    if not lawsuit_id and args.cnj:
        lawsuit_id = resolve_lawsuit_id_from_cnj(client, args.cnj)
    if not lawsuit_id:
        print("ERRO: passe --cnj <CNJ> ou --lawsuit-id <id> ou --doc-id <id>.")
        sys.exit(2)

    type_id = args.type_id or None

    # Teste 1 — H1
    status1, items1 = run_h1_relationships(client, lawsuit_id, type_id)

    # Teste 2 — H2 (so se H1 deu 4xx)
    items2 = []
    if status1 >= 400:
        _, items2 = run_h2_litigation_id(client, lawsuit_id, type_id)

    # Teste extra — H3 (so se nenhuma das duas anteriores trouxe itens)
    items3 = []
    if not items1 and not items2:
        _, items3 = run_h3_litigation_navigation(client, lawsuit_id)

    # Decide qual lista de itens usar pra puxar 1 doc_id e tentar download
    found = items1 or items2 or items3
    banner("RESUMO")
    print(f"  H1 (relationships): status={status1}  items={len(items1)}")
    if status1 >= 400:
        print(f"  H2 (litigationId):  items={len(items2)}")
    if not items1 and not items2:
        print(f"  H3 (navigation):    items={len(items3)}")

    if not found:
        print()
        print("  Nenhum documento encontrado pelas 3 hipoteses.")
        print("  Possiveis causas:")
        print("   - processo nao tem documento desse tipo no GED (tenta --type-id '' pra ver TODOS)")
        print("   - o L1 desse tenant nao expoe /documents pra leitura")
        print("   - tenta com outro lawsuit_id que voce sabe que tem contestacao no GED L1")
        sys.exit(1)

    # Download do primeiro
    first = found[0]
    first_id = first.get("id")
    if first_id:
        print(f"\n  Pegando primeiro doc_id={first_id} pra testar download...")
        run_download(client, int(first_id))


if __name__ == "__main__":
    main()
