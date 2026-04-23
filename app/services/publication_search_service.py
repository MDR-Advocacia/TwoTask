"""
Serviço de busca e gestão de publicações do Legal One.

Responsabilidades:
- Disparar buscas de publicações via API
- Enriquecer publicações com escritório responsável (via lookup de processos)
- Auto-classificar cada publicação via IA
- Auto-montar proposta de tarefa baseada em template
- Persistir resultados com deduplicação
- Fornecer CRUD, agrupamento e contagens para o painel de controle
- Ponte para o agendamento (enviar proposta para o LegalOne após revisão do operador)
"""

import asyncio
import logging
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, List, Optional

import sqlalchemy as sa
from sqlalchemy import func as sa_func, literal_column, case, or_
from sqlalchemy.orm import Session, joinedload

from app.models.publication_search import (
    RECORD_STATUS_CLASSIFIED,
    RECORD_STATUS_ERROR,
    RECORD_STATUS_IGNORED,
    RECORD_STATUS_NEW,
    RECORD_STATUS_OBSOLETE,
    RECORD_STATUS_SCHEDULED,
    RECORD_STATUS_DISCARDED_DUPLICATE,
    SEARCH_STATUS_CANCELLED,
    SEARCH_STATUS_COMPLETED,
    SEARCH_STATUS_FAILED,
    SEARCH_STATUS_RUNNING,
    VALID_POLOS,
    PublicationRecord,
    PublicationSearch,
)
from app.services.legal_one_client import LegalOneApiClient

logger = logging.getLogger(__name__)


# ── UF derivation from CNJ ──────────────────────────────────────────────
# Espelha a lógica de frontend/src/pages/PublicationsPage.tsx::ufFromCnj.
# Formato CNJ: NNNNNNN-DD.AAAA.J.TR.OOOO (20 dígitos sem pontuação).
_UF_ESTADUAL = {
    "01": "AC", "02": "AL", "03": "AP", "04": "AM", "05": "BA", "06": "CE",
    "07": "DF", "08": "ES", "09": "GO", "10": "MA", "11": "MT", "12": "MS",
    "13": "MG", "14": "PA", "15": "PB", "16": "PR", "17": "PE", "18": "PI",
    "19": "RJ", "20": "RN", "21": "RS", "22": "RO", "23": "RR", "24": "SC",
    "25": "SP", "26": "SE", "27": "TO",
}


def uf_from_cnj(cnj: Optional[str]) -> Optional[str]:
    """Extrai UF/região a partir do CNJ. Retorna None se padrão não bate."""
    if not cnj:
        return None
    digits = "".join(c for c in cnj if c.isdigit())
    if len(digits) != 20:
        return None
    j = digits[13]
    tr = digits[14:16]
    if j == "8":
        return _UF_ESTADUAL.get(tr)
    if j == "4":
        try:
            return f"TRF{int(tr)}"
        except ValueError:
            return f"TRF{tr}"
    if j == "7":
        try:
            return f"TRT{int(tr)}"
        except ValueError:
            return f"TRT{tr}"
    if j == "5":
        try:
            return f"JME{int(tr)}"
        except ValueError:
            return f"JME{tr}"
    if j == "6":
        base = _UF_ESTADUAL.get(tr, tr)
        return f"TRE-{base}"
    return None


# ── Extração de CNJ a partir do texto da publicação ────────────────────
# Fallback usado quando a publicação não vem com `Litigation` relationship
# no Legal One (publicações avulsas). O DJE quase sempre imprime o CNJ
# no cabeçalho ou no corpo — varremos ambos.
#
# Formato canônico CNJ: NNNNNNN-DD.AAAA.J.TR.OOOO
#   N = número sequencial (7)  D = DV (2)  A = ano (4)
#   J = segmento do Judiciário (1)  T = tribunal (2)  O = origem (4)
_CNJ_FORMATTED_RE = re.compile(r"\b\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}\b")
_CNJ_DIGITS_RE = re.compile(r"(?<!\d)\d{20}(?!\d)")
# Aceita variações comuns com espaços estranhos entre os grupos (ex.: PDF mal
# transcrito). Mantemos separado do canônico pra não encarecer o caso comum.
_CNJ_LOOSE_RE = re.compile(
    r"\b\d{7}\s*-\s*\d{2}\s*\.\s*\d{4}\s*\.\s*\d\s*\.\s*\d{2}\s*\.\s*\d{4}\b"
)


def _format_cnj_digits(digits: str) -> str:
    """Formata 20 dígitos no padrão canônico NNNNNNN-DD.AAAA.J.TR.OOOO."""
    return (
        f"{digits[0:7]}-{digits[7:9]}.{digits[9:13]}."
        f"{digits[13]}.{digits[14:16]}.{digits[16:20]}"
    )


def extract_cnj_from_text(text: Optional[str]) -> Optional[str]:
    """
    Tenta extrair um CNJ do texto livre de uma publicação (cabeçalho ou corpo).
    Retorna o CNJ no formato canônico (NNNNNNN-DD.AAAA.J.TR.OOOO) ou None.

    Estratégia em camadas:
      1. Match no formato canônico (mais seguro, menos falso positivo).
      2. Match com whitespace entre os grupos (PDFs com OCR sujo).
      3. 20 dígitos consecutivos — valida que o 14º dígito (segmento J) é
         1-9, eliminando sequências numéricas aleatórias.

    Em todos os casos, retorna-se sempre o primeiro match encontrado, que
    costuma ser o do cabeçalho / referência principal da publicação.
    """
    if not text:
        return None

    m = _CNJ_FORMATTED_RE.search(text)
    if m:
        return m.group(0)

    m = _CNJ_LOOSE_RE.search(text)
    if m:
        digits = re.sub(r"\D", "", m.group(0))
        if len(digits) == 20 and digits[13] in "123456789":
            return _format_cnj_digits(digits)

    m = _CNJ_DIGITS_RE.search(text)
    if m:
        digits = m.group(0)
        if digits[13] in "123456789":
            return _format_cnj_digits(digits)

    return None


class PublicationSearchService:

    def __init__(self, db: Session, client: LegalOneApiClient):
        self.db = db
        self.client = client

    # ──────────────────────────────────────────────
    # Progress helper
    # ──────────────────────────────────────────────

    def _update_search_progress(self, search, step: str, detail: str, pct: int):
        """Atualiza progresso intermediário da busca (commit imediato)."""
        search.progress_step = step
        search.progress_detail = detail
        search.progress_pct = min(pct, 100)
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()

    # ──────────────────────────────────────────────
    # Disparo de busca
    # ──────────────────────────────────────────────

    def create_and_run_search(
        self,
        date_from: str,
        date_to: Optional[str] = None,
        origin_type: str = "OfficialJournalsCrawler",
        responsible_office_id: Optional[int] = None,
        auto_classify: bool = False,
        requested_by: Optional[str] = None,
        only_unlinked: bool = False,
    ) -> dict[str, Any]:
        """Cria um registro de busca, executa, enriquece e persiste resultados."""

        search = PublicationSearch(
            status=SEARCH_STATUS_RUNNING,
            date_from=date_from,
            date_to=date_to,
            origin_type=origin_type,
            office_filter=str(responsible_office_id) if responsible_office_id else None,
            requested_by_email=requested_by,
        )
        self.db.add(search)
        self.db.commit()
        self.db.refresh(search)

        try:
            # 1) Busca TODAS as publicações (paginação automática)
            self._update_search_progress(search, "FETCH", "Buscando publicações na API Legal One...", 5)
            publications = self.client.fetch_all_publications(
                date_from=date_from,
                date_to=date_to,
                origin_type=origin_type,
            )
            self._update_search_progress(
                search, "FETCH",
                f"{len(publications)} publicações encontradas na API",
                15,
            )

            # 1.5) Pré-filtro por escritório (otimização):
            # Usa o índice persistente (office_lawsuit_index). Se o índice
            # existir e estiver fresh, é consulta de banco — sem API. Se estiver
            # stale/inexistente, dispara sync em background e segue com o que
            # tiver (inclusive vazio — nesse caso pulamos o pré-filtro pra não
            # perder dados na primeira busca).
            if responsible_office_id is not None:
                office_lawsuit_ids: Optional[set[int]] = None
                try:
                    from app.services.office_lawsuit_index_service import (
                        OfficeLawsuitIndexService,
                    )
                    idx_svc = OfficeLawsuitIndexService(self.db, self.client)
                    idx_svc.ensure_sync(responsible_office_id)
                    ids = idx_svc.get_lawsuit_ids(responsible_office_id)
                    if ids:
                        office_lawsuit_ids = ids
                        logger.info(
                            "Índice persistente: %s processos pro escritório %s.",
                            len(ids), responsible_office_id,
                        )
                    else:
                        logger.info(
                            "Índice persistente vazio/em construção pro escritório %s — "
                            "pulando pré-filtro nessa busca.",
                            responsible_office_id,
                        )
                except Exception as exc:
                    logger.warning(
                        "Pré-filtro por escritório falhou, caindo para o fluxo antigo: %s",
                        exc,
                    )
                    office_lawsuit_ids = None

                if office_lawsuit_ids:
                    before_prefilter = len(publications)
                    kept = []
                    for _p in publications:
                        rels = _p.get("relationships") or []
                        lit = next(
                            (r for r in rels if r.get("linkType") == "Litigation"),
                            None,
                        )
                        if not lit:
                            # sem processo vinculado — mantém pra não perder
                            # publicações "avulsas" do período; serão descartadas
                            # no filtro posterior se não baterem
                            kept.append(_p)
                            continue
                        try:
                            lid = int(lit.get("linkId"))
                        except (TypeError, ValueError):
                            continue
                        if lid in office_lawsuit_ids:
                            # já sabemos o escritório — grava e evita lookup depois
                            _p["_responsible_office_id"] = responsible_office_id
                            kept.append(_p)
                    logger.info(
                        "Pré-filtro escritório %s: %s → %s publicações (antes do enriquecimento).",
                        responsible_office_id, before_prefilter, len(kept),
                    )
                    publications = kept

            # 2) Enriquece com responsibleOfficeId via lookup de processos
            self._update_search_progress(
                search, "ENRICH",
                f"Enriquecendo {len(publications)} publicações com dados de processos...",
                25,
            )
            publications = self._enrich_with_lawsuit_data(publications)
            self._update_search_progress(
                search, "FILTER",
                f"Filtrando {len(publications)} publicações...",
                40,
            )

            # 3) Filtra por escritório responsável (se especificado)
            if responsible_office_id is not None:
                before = len(publications)

                # Diagnóstico: distribuição de responsibleOfficeId nos processos
                # vinculados, para descobrir qual ID realmente bate com o
                # escritório selecionado no frontend.
                from collections import Counter
                office_counter: Counter = Counter()
                sem_processo = 0
                sem_office = 0
                for _p in publications:
                    relationships = _p.get("relationships") or []
                    has_lit = any(r.get("linkType") == "Litigation" for r in relationships)
                    if not has_lit:
                        sem_processo += 1
                        continue
                    oid = _p.get("_responsible_office_id")
                    if oid is None:
                        sem_office += 1
                        continue
                    office_counter[oid] += 1

                top = office_counter.most_common(20)
                logger.info(
                    "Diagnóstico escritórios (procurado=%s) | total=%s | sem processo vinculado=%s | processo sem responsibleOfficeId=%s | top responsibleOfficeId: %s",
                    responsible_office_id, before, sem_processo, sem_office, top,
                )

                publications = [
                    p for p in publications
                    if p.get("_responsible_office_id") == responsible_office_id
                ]
                logger.info(
                    "Filtro por escritório %s: %s → %s publicações.",
                    responsible_office_id, before, len(publications),
                )

            # 3.5) Filtra apenas publicações sem processo vinculado (se solicitado)
            if only_unlinked:
                before_unlinked = len(publications)
                publications = [
                    p for p in publications
                    if not any(
                        r.get("linkType") == "Litigation"
                        for r in (p.get("relationships") or [])
                    )
                ]
                logger.info(
                    "Filtro only_unlinked: %s → %s publicações.",
                    before_unlinked, len(publications),
                )

            # 4) Deduplica e persiste os novos
            self._update_search_progress(
                search, "PERSIST",
                f"Deduplicando e persistindo {len(publications)} publicações...",
                50,
            )
            #
            # Dedup em duas camadas:
            #   (a) legal_one_update_id (id único do Legal One) → duplicata exata
            #   (b) (linked_lawsuit_id, publication_date) → mesma publicação de um
            #       mesmo processo no mesmo dia é tratada uma única vez,
            #       economizando tokens de classificação e chamadas à API do L1.
            existing_ids = set(
                row[0]
                for row in self.db.query(PublicationRecord.legal_one_update_id).all()
            )

            # Chaves (lawsuit_id, publication_date) já presentes em registros
            # "vivos" (não descartados). Mesmo conjunto coberto pelo índice
            # único parcial uq_pub_lawsuit_date.
            existing_keys = set(
                (row[0], row[1])
                for row in self.db.query(
                    PublicationRecord.linked_lawsuit_id,
                    PublicationRecord.publication_date,
                )
                .filter(PublicationRecord.linked_lawsuit_id.isnot(None))
                .filter(PublicationRecord.publication_date.isnot(None))
                .filter(PublicationRecord.publication_date != "")
                .filter(PublicationRecord.status != RECORD_STATUS_DISCARDED_DUPLICATE)
                .filter(PublicationRecord.is_duplicate == False)  # noqa: E712
                .all()
            )

            new_records: List[PublicationRecord] = []
            duplicate_records: List[PublicationRecord] = []
            obsolete_records: List[PublicationRecord] = []
            new_count = 0
            dup_count = 0
            discarded_count = 0
            obsolete_count = 0

            # Commit em lote: evita perder TODO o trabalho se o worker uvicorn
            # for killed (OOM/restart) no meio do PERSIST. Também dá progresso
            # visível na UI via total_new/total_duplicate incrementais e
            # permite o watchdog distinguir "rodando lento" de "morta" pelo
            # MAX(created_at) em publicacao_registros.
            #
            # 500 ≈ sweet spot: inserts agrupados suficientes pra ser rápido
            # e granular o bastante pra não perder muito em caso de crash.
            PERSIST_BATCH_SIZE = 500
            pending_in_batch = 0
            total_processed = 0
            total_pubs = len(publications)

            for pub in publications:
                update_id = pub.get("id")
                if not update_id:
                    continue

                if update_id in existing_ids:
                    dup_count += 1
                    continue

                relationships = pub.get("relationships") or []
                lawsuit_rel = next(
                    (r for r in relationships if r.get("linkType") == "Litigation"),
                    None,
                )
                lawsuit_id = lawsuit_rel.get("linkId") if lawsuit_rel else None
                publication_date = pub.get("date")

                # Guarda (lawsuit_id, publication_date): se já temos uma
                # publicação viva do mesmo processo no mesmo dia, descartamos
                # — insere marcada para rastreabilidade sem consumir recursos
                # de classificação nem colidir com o índice único parcial.
                dedup_key = (
                    (lawsuit_id, publication_date)
                    if lawsuit_id and publication_date
                    else None
                )
                is_lawsuit_date_duplicate = (
                    dedup_key is not None and dedup_key in existing_keys
                )

                # ── Detecção de publicação obsoleta ─────────────────
                # Se a data da publicação é anterior à data de criação
                # da pasta do processo no Legal One, a publicação já
                # foi auditada na esteira de admissão → obsoleta.
                is_obsolete = False
                if not is_lawsuit_date_duplicate and publication_date:
                    lawsuit_creation = pub.get("_lawsuit_creation_date")
                    if lawsuit_creation:
                        try:
                            # Datas podem vir como ISO completo ou só "YYYY-MM-DD"
                            pub_dt = publication_date[:10]
                            law_dt = lawsuit_creation[:10]
                            if pub_dt < law_dt:
                                is_obsolete = True
                        except (TypeError, IndexError):
                            pass

                # Decide o status final do registro
                if is_lawsuit_date_duplicate:
                    record_status = RECORD_STATUS_DISCARDED_DUPLICATE
                elif is_obsolete:
                    record_status = RECORD_STATUS_OBSOLETE
                else:
                    record_status = RECORD_STATUS_NEW

                cnj = pub.get("_cnj")
                # Fallback: se não veio processo vinculado pelo L1, tenta extrair
                # o CNJ direto do texto da publicação (cabeçalho ou corpo).
                if not cnj:
                    fallback_cnj = extract_cnj_from_text(
                        (pub.get("description") or "")
                        + "\n"
                        + (pub.get("notes") or "")
                    )
                    if fallback_cnj:
                        cnj = fallback_cnj
                        logger.debug(
                            "CNJ extraído do texto (publicação #%s): %s",
                            update_id, cnj,
                        )
                record = PublicationRecord(
                    search_id=search.id,
                    legal_one_update_id=update_id,
                    origin_type=pub.get("originType"),
                    update_type_id=pub.get("typeId"),
                    description=pub.get("description"),
                    notes=pub.get("notes"),
                    publication_date=publication_date,
                    creation_date=pub.get("creationDate"),
                    linked_lawsuit_id=lawsuit_id,
                    linked_lawsuit_cnj=cnj,
                    linked_office_id=pub.get("_responsible_office_id"),
                    raw_relationships=relationships,
                    status=record_status,
                    is_duplicate=is_lawsuit_date_duplicate,
                    uf=uf_from_cnj(cnj),
                )
                self.db.add(record)
                existing_ids.add(update_id)

                # Atualiza existing_keys ASSIM QUE registramos a primeira
                # publicação com esse par (lawsuit_id, publication_date) —
                # independente do status final (NOVO, OBSOLETA, etc.). Sem
                # isso, duas publicações diferentes com o mesmo par dentro
                # do MESMO batch geravam UniqueViolation no índice parcial
                # uq_pub_lawsuit_date. Foi a causa real do travamento das
                # Buscas #2 e #3 em 22/04/2026 (a #2 ficou órfã porque o
                # except subsequente não conseguia commitar a marca de FALHA
                # com a session em estado "transaction rolled back").
                if dedup_key is not None and not is_lawsuit_date_duplicate:
                    existing_keys.add(dedup_key)

                if is_lawsuit_date_duplicate:
                    discarded_count += 1
                    duplicate_records.append(record)
                elif is_obsolete:
                    obsolete_count += 1
                    obsolete_records.append(record)
                else:
                    new_records.append(record)
                    new_count += 1

                pending_in_batch += 1
                total_processed += 1

                # Commit parcial: sobrevive a OOM/SIGKILL e dá progresso real
                # pra UI. Progress vai de 50 → 70% proporcional ao processado.
                if pending_in_batch >= PERSIST_BATCH_SIZE:
                    # Cancelamento cooperativo: cancel_search() roda em outra
                    # session (request do endpoint) e apenas seta status=
                    # CANCELADO no DB. O loop aqui não vê essa mudança sem
                    # consultar. Granularidade de 500 registros (~segundos)
                    # é aceitável e evita hit a cada publicação.
                    current_status = (
                        self.db.query(PublicationSearch.status)
                        .filter(PublicationSearch.id == search.id)
                        .scalar()
                    )
                    if current_status == SEARCH_STATUS_CANCELLED:
                        self.db.rollback()  # descarta o lote pendente
                        logger.warning(
                            "Busca #%s cancelada pelo usuário no PERSIST "
                            "(%d/%d processados antes do cancelamento, %d novas commitadas).",
                            search.id, total_processed, total_pubs, new_count,
                        )
                        self.db.refresh(search)
                        return self._search_to_dict(search)

                    search.total_found = new_count + discarded_count + obsolete_count
                    search.total_new = new_count
                    search.total_duplicate = dup_count + discarded_count + obsolete_count
                    search.progress_step = "PERSIST"
                    search.progress_detail = (
                        f"Persistindo... {total_processed}/{total_pubs} "
                        f"({new_count} novas, {discarded_count} duplicatas, "
                        f"{obsolete_count} obsoletas)"
                    )
                    search.progress_pct = 50 + min(
                        20, int(20 * total_processed / max(total_pubs, 1))
                    )
                    self.db.commit()
                    logger.info(
                        "Busca #%s: lote persistido (%d/%d processados, %d novas)",
                        search.id, total_processed, total_pubs, new_count,
                    )
                    pending_in_batch = 0

            # Commit final: pega o resto do último lote (<500 registros).
            self.db.commit()

            self._update_search_progress(
                search, "PERSIST",
                f"{new_count} novas, {dup_count} duplicatas, {discarded_count} descartadas, {obsolete_count} obsoletas",
                70,
            )

            # 5) Classificação agora é EXCLUSIVAMENTE via Batch API
            # (mais barato, sem rate limit). A busca apenas persiste os registros.
            # O operador envia o lote manualmente via painel de classificação em lote.

            # 6) Tenta construir proposta de tarefa para cada publicação classificada
            if new_records:
                self._update_search_progress(
                    search, "PROPOSALS",
                    f"Montando propostas de tarefa para {len(new_records)} publicações...",
                    80,
                )
                self._build_task_proposals(new_records)

            # 7) Duplicatas e obsoletas vão direto pra fila do RPA
            # com target_status="sem providência": o RPA só marca a
            # publicação como tratada no Legal One.
            rpa_records = duplicate_records + obsolete_records
            if rpa_records:
                try:
                    from app.services.publication_treatment_service import (
                        PublicationTreatmentService,
                    )
                    treatment_service = PublicationTreatmentService(self.db)
                    for rec in rpa_records:
                        treatment_service.sync_item_from_record(rec, commit=False)
                    self.db.commit()
                    logger.info(
                        "Busca #%s: %s duplicatas + %s obsoletas enfileiradas pro RPA (sem providência).",
                        search.id, len(duplicate_records), len(obsolete_records),
                    )
                except Exception as exc:
                    logger.exception(
                        "Falha ao enfileirar duplicatas/obsoletas da busca #%s: %s",
                        search.id, exc,
                    )
                    self.db.rollback()

            # `total_found` = registros que ESTA busca efetivamente vinculou
            # ao sistema (novos + descartados + obsoletas).
            search.total_found = new_count + discarded_count + obsolete_count
            search.total_new = new_count
            # total_duplicate agrega: duplicata por update_id +
            # descartadas pelo dedup (lawsuit_id, publication_date) + obsoletas.
            search.total_duplicate = dup_count + discarded_count + obsolete_count
            search.status = SEARCH_STATUS_COMPLETED
            search.progress_step = "DONE"
            search.progress_detail = f"Concluída — {new_count} novas publicações"
            search.progress_pct = 100
            search.finished_at = datetime.now(timezone.utc)
            self.db.commit()

            logger.info(
                "Busca #%s concluida: %s api-total, %s vinculadas, %s novas, "
                "%s dup update_id, %s descartadas (processo/data), %s obsoletas",
                search.id, len(publications),
                new_count + discarded_count + obsolete_count,
                new_count, dup_count, discarded_count, obsolete_count,
            )

            return self._search_to_dict(search)

        except Exception as exc:
            logger.error("Erro na busca #%s: %s", search.id, exc)
            # A session pode estar em "transaction rolled back due to previous
            # exception" (caso típico: UniqueViolation em flush — foi o que
            # aconteceu com as Buscas #2/#3 em 22/04/2026). Sem um rollback
            # explícito antes, o commit abaixo falha silenciosamente e a
            # busca fica eternamente com status='EXECUTANDO' e error_message
            # NULL, exigindo intervenção manual no DB.
            try:
                self.db.rollback()
            except Exception:
                pass
            try:
                fresh_search = (
                    self.db.query(PublicationSearch)
                    .filter(PublicationSearch.id == search.id)
                    .first()
                )
                if fresh_search is not None:
                    fresh_search.status = SEARCH_STATUS_FAILED
                    fresh_search.error_message = str(exc)[:500]
                    fresh_search.finished_at = datetime.now(timezone.utc)
                    fresh_search.progress_step = "FAILED"
                    self.db.commit()
            except Exception:
                logger.exception(
                    "Falha ao marcar busca #%s como FALHA após erro principal.",
                    search.id,
                )
                try:
                    self.db.rollback()
                except Exception:
                    pass
            raise

    # ──────────────────────────────────────────────
    # Enriquecimento via lookup de processos
    # ──────────────────────────────────────────────

    def _enrich_with_lawsuit_data(self, publications: list) -> list:
        """
        Extrai lawsuit_ids das relationships e busca em batch no Legal One para obter
        responsibleOfficeId + identifierNumber (CNJ). Anexa nas publicações como
        _responsible_office_id e _cnj (chaves privadas).
        """
        lawsuit_ids: List[int] = []
        for pub in publications:
            relationships = pub.get("relationships") or []
            for rel in relationships:
                if rel.get("linkType") == "Litigation" and rel.get("linkId"):
                    try:
                        lawsuit_ids.append(int(rel["linkId"]))
                    except (TypeError, ValueError):
                        pass

        if not lawsuit_ids:
            return publications

        try:
            lawsuits_map = self.client.fetch_lawsuits_by_ids(lawsuit_ids)
        except Exception as exc:
            logger.warning("Falha ao enriquecer publicações com dados do processo: %s", exc)
            return publications

        for pub in publications:
            relationships = pub.get("relationships") or []
            lawsuit_rel = next(
                (r for r in relationships if r.get("linkType") == "Litigation"),
                None,
            )
            if not lawsuit_rel:
                continue
            try:
                lid = int(lawsuit_rel.get("linkId"))
            except (TypeError, ValueError):
                continue
            lawsuit = lawsuits_map.get(lid)
            if lawsuit:
                pub["_responsible_office_id"] = lawsuit.get("responsibleOfficeId")
                pub["_cnj"] = lawsuit.get("identifierNumber")
                pub["_lawsuit_creation_date"] = lawsuit.get("creationDate")

        return publications

    # ──────────────────────────────────────────────
    # Auto-classificação
    # ──────────────────────────────────────────────

    def _auto_classify_records(self, records: List[PublicationRecord]) -> None:
        """
        Classifica cada publicação nova via IA (Claude).

        Limita a concorrência com Semaphore para não extrapolar os rate limits
        da Anthropic API (requests e tokens por minuto).
        """
        try:
            from app.services.classifier.ai_client import AnthropicClassifierClient
            from app.services.classifier.prompts import (
                SYSTEM_PROMPT,
                build_feedback_examples,
                build_system_prompt_for_office,
                build_user_message,
                load_office_overrides,
            )
            from app.services.classifier.taxonomy import validate_classification, repair_classification
        except Exception as exc:
            logger.warning("Classifier indisponível: %s", exc)
            return

        try:
            ai = AnthropicClassifierClient()
        except Exception as exc:
            logger.warning("AI client não inicializado (ANTHROPIC_API_KEY?): %s", exc)
            return

        # Classifica apenas NOVO com texto — pula duplicatas/já classificados
        to_classify = [
            r for r in records
            if r.status == RECORD_STATUS_NEW and (r.description or "").strip()
        ]
        if not to_classify:
            logger.info("Nenhum registro novo com texto para classificar.")
            return

        logger.info("Classificando %d registros via IA (sequencial, 12s delay)...", len(to_classify))

        # SEQUENCIAL: máximo 1 chamada por vez
        # 60 segundos ÷ 12 segundos = 5 requests/minuto (exatamente o limite)
        # Garante que NUNCA peguemos 429 por RPM ou token limit
        CONCURRENCY = 1

        # Cache de prompts por escritório (evita recarregar overrides a cada chamada)
        office_prompts: dict[int, str] = {}

        # Pré-carrega exemplos de feedback por escritório
        feedback_cache: dict[int, str] = {}

        def _feedback_for(office_id: int | None) -> str:
            oid = office_id or 0
            if oid not in feedback_cache:
                try:
                    feedback_cache[oid] = build_feedback_examples(
                        self.db, office_id,
                    )
                except Exception as exc:
                    logger.warning("Falha ao carregar feedbacks do escritório %s: %s", oid, exc)
                    feedback_cache[oid] = ""
            return feedback_cache[oid]

        def _prompt_for(rec: PublicationRecord) -> str:
            is_unlinked = rec.linked_lawsuit_id is None
            oid = rec.linked_office_id
            # Cache key inclui o flag de unlinked pra não misturar prompts
            cache_key = (oid or 0, is_unlinked)
            if cache_key not in office_prompts:
                try:
                    if oid:
                        excluded, custom = load_office_overrides(self.db, oid)
                    else:
                        excluded, custom = set(), []
                    office_prompts[cache_key] = build_system_prompt_for_office(
                        excluded or None,
                        custom or None,
                        is_unlinked=is_unlinked,
                        feedback_examples=_feedback_for(oid),
                    )
                except Exception as exc:
                    logger.warning("Falha ao carregar overrides do escritório %s: %s", oid, exc)
                    office_prompts[cache_key] = build_system_prompt_for_office(
                        is_unlinked=is_unlinked,
                        feedback_examples=_feedback_for(oid),
                    )
            return office_prompts[cache_key]

        async def _classify_all():
            sem = asyncio.Semaphore(CONCURRENCY)

            async def _one(rec: PublicationRecord):
                async with sem:
                    text = rec.description or ""
                    try:
                        user_msg = build_user_message(rec.linked_lawsuit_cnj or "", text)
                        result = await ai.classify(_prompt_for(rec), user_msg)
                        cat = result.get("categoria")
                        sub = result.get("subcategoria")
                        cat_fixed, sub_fixed = repair_classification(cat or "", sub or "")
                        if (cat_fixed, sub_fixed) != (cat, sub):
                            logger.info(
                                "Classificação auto-corrigida #%s: (%s/%s) → (%s/%s)",
                                rec.id, cat, sub, cat_fixed, sub_fixed,
                            )
                            cat, sub = cat_fixed, sub_fixed
                        polo_raw = (result.get("polo") or "").strip().lower()
                        polo = polo_raw if polo_raw in VALID_POLOS else None
                        if cat and validate_classification(cat, sub):
                            rec.category = cat
                            rec.subcategory = sub
                            rec.polo = polo
                            # Audiência: extrair data/hora se presente
                            rec.audiencia_data = result.get("audiencia_data") or None
                            rec.audiencia_hora = result.get("audiencia_hora") or None
                            # Natureza do processo: só pra publicações sem pasta vinculada
                            if rec.linked_lawsuit_id is None:
                                rec.natureza_processo = result.get("natureza_processo") or None
                            rec.status = RECORD_STATUS_CLASSIFIED
                            logger.debug(
                                "Classificado #%s → %s / %s (polo=%s, aud=%s %s, nat=%s)",
                                rec.id, cat, sub, polo,
                                rec.audiencia_data, rec.audiencia_hora,
                                rec.natureza_processo if rec.linked_lawsuit_id is None else "-",
                            )
                        else:
                            logger.warning(
                                "Classificação inválida para #%s: cat=%s sub=%s",
                                rec.id, cat, sub,
                            )
                    except Exception as exc:
                        logger.warning("Falha ao classificar publicação #%s: %s", rec.id, exc)
                    # Aguarda 12 segundos entre requisições (garante limite de 5 RPM)
                    # Combinado com CONCURRENCY=1, isso respeita perfeitamente:
                    # - 5 requests/minuto (RPM)
                    # - 10,000 tokens/minuto (TPM)
                    await asyncio.sleep(12.0)

            await asyncio.gather(*[_one(r) for r in to_classify], return_exceptions=True)

        # Executa no loop correto (compatível com background thread e async context)
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Estamos dentro de um loop assíncrono — usa run_in_executor via novo loop
                import concurrent.futures
                def _run_in_new_loop():
                    new_loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(new_loop)
                    try:
                        new_loop.run_until_complete(_classify_all())
                    finally:
                        new_loop.close()
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(_run_in_new_loop)
                    future.result()  # aguarda conclusão
            else:
                loop.run_until_complete(_classify_all())
        except Exception:
            # Fallback: cria loop limpo
            new_loop = asyncio.new_event_loop()
            try:
                new_loop.run_until_complete(_classify_all())
            finally:
                new_loop.close()

        try:
            self.db.commit()
            classified = sum(1 for r in to_classify if r.status == RECORD_STATUS_CLASSIFIED)
            logger.info(
                "Classificação concluída: %d/%d registros classificados.",
                classified, len(to_classify),
            )
        except Exception as exc:
            logger.error("Erro ao salvar classificações: %s", exc)

    # ──────────────────────────────────────────────
    # Construção de propostas de tarefa
    # ──────────────────────────────────────────────

    def _build_task_proposals(
        self,
        records: List[PublicationRecord],
        skip_responsible_lookup: bool = False,
    ) -> None:
        """
        Para cada record classificado, tenta achar um template correspondente
        (categoria/subcategoria + escritório responsável) e monta uma proposta
        de payload de tarefa que ficará pendente de aprovação pelo operador.

        A proposta é armazenada como campo JSON em `raw_relationships` sob a chave
        interna `_proposed_task` (usando o campo já existente para evitar migrações
        extras nesta iteração).

        Parâmetros:
            skip_responsible_lookup: Se True, pula a busca de responsável de pasta
                na API Legal One (útil para reconstrução em massa, evitando rate-limit).
                O operador pode definir o responsável manualmente no momento do agendamento.
        """
        try:
            from app.models.task_template import TaskTemplate
        except Exception:
            return  # Template model ainda não existe

        # Pré-busca de responsáveis por pasta em batch para evitar N+1
        lawsuit_responsibles: dict = {}
        if not skip_responsible_lookup:
            lawsuit_ids = list({
                r.linked_lawsuit_id for r in records
                if r.linked_lawsuit_id and r.category and r.linked_office_id
            })
            if lawsuit_ids:
                try:
                    from app.services.legal_one_client import LegalOneApiClient
                    lo_client = LegalOneApiClient()
                    lawsuit_responsibles = lo_client.fetch_lawsuit_responsibles_batch(lawsuit_ids)
                    logger.info(
                        "Responsáveis de pasta obtidos: %d de %d processos.",
                        len(lawsuit_responsibles), len(lawsuit_ids),
                    )
                except Exception as exc:
                    logger.warning("Falha ao buscar responsáveis de pasta: %s", exc)

        for rec in records:
            if not rec.category:
                continue

            # Responsável da pasta para este registro
            lawsuit_resp = lawsuit_responsibles.get(rec.linked_lawsuit_id) if rec.linked_lawsuit_id else None

            # Coleta todas as classificações do registro (primária + extras)
            classifications_to_process = [
                {"category": rec.category, "subcategory": rec.subcategory}
            ]
            if rec.classifications and isinstance(rec.classifications, list):
                for clf in rec.classifications[1:]:  # [1:] pois a primeira já é a primária
                    cat = clf.get("categoria")
                    sub = clf.get("subcategoria")
                    if cat:
                        classifications_to_process.append(
                            {"category": cat, "subcategory": sub}
                        )

            proposals = []
            for clf_info in classifications_to_process:
                # Busca templates correspondentes:
                #   - Se o registro tem escritório: busca templates do escritório OU templates globais (office IS NULL)
                #   - Se o registro não tem escritório (sem processo): busca APENAS templates globais (office IS NULL)
                office_filter = (
                    (
                        (TaskTemplate.office_external_id == rec.linked_office_id)
                        | (TaskTemplate.office_external_id.is_(None))
                    )
                    if rec.linked_office_id
                    else TaskTemplate.office_external_id.is_(None)
                )
                templates = (
                    self.db.query(TaskTemplate)
                    .filter(TaskTemplate.is_active == True)
                    .filter(TaskTemplate.category == clf_info["category"])
                    .filter(office_filter)
                    .filter(
                        (TaskTemplate.subcategory == clf_info["subcategory"])
                        | (TaskTemplate.subcategory.is_(None))
                    )
                    .order_by(TaskTemplate.subcategory.nullslast())
                    .all()
                )

                for tmpl in templates:
                    try:
                        proposal = self._render_proposal(rec, tmpl, lawsuit_responsible=lawsuit_resp)
                        proposals.append(proposal)
                    except Exception as exc:
                        logger.warning(
                            "Falha ao montar proposta p/ record %s, tmpl %s: %s",
                            rec.id, tmpl.id, exc,
                        )

            if not proposals:
                continue

            # Guarda as propostas no raw_relationships
            raw = dict(rec.raw_relationships or {}) if isinstance(rec.raw_relationships, dict) else {
                "_relationships": rec.raw_relationships
            }
            # Primeira proposta mantém compatibilidade; extras ficam em lista
            raw["_proposed_task"] = proposals[0]
            if len(proposals) > 1:
                raw["_proposed_tasks"] = proposals
            rec.raw_relationships = raw

        self.db.commit()

    # Limite máximo de caracteres aceito pela API Legal One no campo description.
    _DESCRIPTION_MAX_CHARS = 250

    def _enforce_description_limit(self, payload: dict) -> None:
        """
        Trava de segurança: garante que `description` ≤ 250 chars (limite da
        API Legal One). NÃO concatena textos de outras publicações nem move
        conteúdo para notes — usa exclusivamente o que o template renderizou.

        Modifica o `payload` in-place.
        """
        desc = (payload.get("description") or "").strip()
        if not desc:
            payload["description"] = "Publicação judicial"
            return
        if len(desc) > self._DESCRIPTION_MAX_CHARS:
            desc = desc[: self._DESCRIPTION_MAX_CHARS - 1].rstrip() + "…"
        payload["description"] = desc

    def _render_proposal(self, rec: PublicationRecord, tmpl, lawsuit_responsible: dict = None) -> dict:
        """Monta o dict de payload de tarefa baseado no template + record."""
        from datetime import date as date_cls, timedelta

        # Calcula prazo a partir da data de publicação (ou hoje)
        base_date = None
        if rec.publication_date:
            try:
                base_date = datetime.fromisoformat(
                    rec.publication_date.replace("Z", "+00:00")
                ).date()
            except Exception:
                pass
        if not base_date:
            base_date = date_cls.today()

        # ── Data/hora da tarefa ─────────────────────────────────────
        # Se for audiência com data extraída, usa EXATAMENTE a data/hora
        # da publicação sem qualquer conversão de fuso horário.
        if rec.audiencia_data:
            # Formata ISO: YYYY-MM-DDTHH:MM:SSZ
            if rec.audiencia_hora:
                due_iso = f"{rec.audiencia_data}T{rec.audiencia_hora}:00Z"
            else:
                # Sem horário: usa 23:59:59 como fallback
                due_iso = f"{rec.audiencia_data}T23:59:59Z"
        else:
            # Sem audiência: usa prazo padrão
            # Se due_date_reference == "today", conta a partir da data atual
            due_ref = getattr(tmpl, "due_date_reference", "publication") or "publication"
            due_base = date_cls.today() if due_ref == "today" else base_date
            due_date = due_base + timedelta(days=tmpl.due_business_days or 5)
            due_iso = due_date.strftime("%Y-%m-%dT23:59:59Z")

        publish_iso = base_date.strftime("%Y-%m-%dT00:00:00Z")

        # Interpolação simples de variáveis na descrição/notas
        ctx = {
            "cnj": rec.linked_lawsuit_cnj or "",
            "publication_date": base_date.isoformat(),
            "description": (rec.description or "")[:300],
            "category": rec.category or "",
            "subcategory": rec.subcategory or "",
            "audiencia_data": rec.audiencia_data or "",
            "audiencia_hora": rec.audiencia_hora or "",
            "audiencia_link": rec.audiencia_link or "",
        }
        description_tpl = tmpl.description_template or "Publicação judicial — processo {cnj} em {publication_date}."
        notes_tpl = tmpl.notes_template or ""
        try:
            description = description_tpl.format(**ctx)
        except Exception:
            description = description_tpl
        try:
            notes = notes_tpl.format(**ctx) if notes_tpl else None
        except Exception:
            notes = notes_tpl or None

        # Adiciona link de audiência nas observações quando presente
        if rec.audiencia_link:
            link_note = f"\n\n🔗 Link da audiência virtual: {rec.audiencia_link}"
            notes = (notes or "") + link_note

        # Campos do template via external_id (os FKs são external_id)
        from app.models.legal_one import LegalOneTaskSubType, LegalOneUser, LegalOneOffice

        subtype = self.db.query(LegalOneTaskSubType).options(
            joinedload(LegalOneTaskSubType.parent_type)
        ).filter(LegalOneTaskSubType.external_id == tmpl.task_subtype_external_id).first()
        user = self.db.query(LegalOneUser).filter(
            LegalOneUser.external_id == tmpl.responsible_user_external_id
        ).first()

        if not (subtype and subtype.parent_type and user):
            raise ValueError("Template com referências inválidas (subtype/user).")

        # office pode ser None para templates globais (publicações sem processo)
        office = None
        if tmpl.office_external_id:
            office = self.db.query(LegalOneOffice).filter(
                LegalOneOffice.external_id == tmpl.office_external_id
            ).first()
            if not office:
                raise ValueError(f"Escritório {tmpl.office_external_id} não encontrado.")

        # Para publicações sem escritório vinculado, usa o escritório do próprio record se disponível
        effective_office_id = (
            office.external_id if office
            else rec.linked_office_id  # pode ainda ser None
        )

        payload = {
            "description": description,
            "priority": tmpl.priority or "Normal",
            "startDateTime": due_iso,
            "endDateTime": due_iso,
            "publishDate": publish_iso,
            "notes": notes,
            "status": {"id": 0},
            "typeId": subtype.parent_type.external_id,
            "subTypeId": subtype.external_id,
            "participants": [
                {
                    "contact": {"id": user.external_id},
                    "isResponsible": True,
                    "isExecuter": True,
                    "isRequester": True,
                }
            ],
        }
        # Só inclui escritório se disponível
        if effective_office_id:
            payload["responsibleOfficeId"] = effective_office_id
            payload["originOfficeId"] = effective_office_id

        result = {
            "template_id": tmpl.id,
            "template_name": tmpl.name,
            "payload": payload,
            "built_at": datetime.now(timezone.utc).isoformat(),
        }

        # Inclui sugestão de responsável da pasta (puxado da API Legal One)
        if lawsuit_responsible:
            result["suggested_responsible"] = {
                "id": lawsuit_responsible.get("id"),
                "name": lawsuit_responsible.get("name"),
                "email": lawsuit_responsible.get("email"),
                "source": "Legal One - Responsável da pasta",
            }

        return result

    def list_novo_with_text(
        self, linked_office_id: Optional[int] = None
    ) -> List[PublicationRecord]:
        """Retorna todos os registros com status NOVO que têm descrição preenchida."""
        query = (
            self.db.query(PublicationRecord)
            .filter(PublicationRecord.status == RECORD_STATUS_NEW)
            .filter(PublicationRecord.is_duplicate == False)
            .filter(PublicationRecord.description.isnot(None))
            .filter(PublicationRecord.description != "")
        )
        if linked_office_id is not None:
            query = query.filter(PublicationRecord.linked_office_id == linked_office_id)
        return query.order_by(PublicationRecord.id).all()

    # ──────────────────────────────────────────────
    # Listagem e status de buscas
    # ──────────────────────────────────────────────

    def list_searches(self, limit: int = 20) -> list[dict[str, Any]]:
        searches = (
            self.db.query(PublicationSearch)
            .order_by(PublicationSearch.created_at.desc())
            .limit(limit)
            .all()
        )
        return [self._search_to_dict(s) for s in searches]

    def get_search(self, search_id: int) -> dict[str, Any]:
        search = self.db.query(PublicationSearch).filter_by(id=search_id).first()
        if not search:
            raise ValueError(f"Busca #{search_id} não encontrada.")
        return self._search_to_dict(search)

    # ──────────────────────────────────────────────
    # CRUD de registros de publicação
    # ──────────────────────────────────────────────

    def list_records(
        self,
        search_id: Optional[int] = None,
        status: Optional[str] = None,
        linked_office_id: Optional[int] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        query = self.db.query(PublicationRecord).filter(PublicationRecord.is_duplicate == False)

        if search_id:
            query = query.filter(PublicationRecord.search_id == search_id)
        if status:
            query = query.filter(PublicationRecord.status == status)
        if linked_office_id is not None:
            query = query.filter(PublicationRecord.linked_office_id == linked_office_id)

        total = query.count()
        records = (
            query
            .order_by(PublicationRecord.publication_date.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

        return {
            "total": total,
            "offset": offset,
            "limit": limit,
            "records": [self._record_to_dict(r) for r in records],
        }

    # ── Helpers para query base filtrada ──────────────────────────────

    def _base_publication_query(
        self,
        search_id: Optional[int] = None,
        status: Optional[str] = None,
        linked_office_id: Optional[int] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        category: Optional[str] = None,
        uf: Optional[str] = None,
        vinculo: Optional[str] = None,
        natureza: Optional[str] = None,
        polo: Optional[str] = None,
    ):
        """Query base reutilizada por list_records_grouped e contagens."""
        query = self.db.query(PublicationRecord).filter(PublicationRecord.is_duplicate == False)  # noqa: E712
        if search_id is not None:
            query = query.filter(PublicationRecord.search_id == search_id)
        if status:
            query = query.filter(PublicationRecord.status == status)
        else:
            # Sem filtro explícito, esconde obsoletas (não poluem a listagem principal).
            query = query.filter(PublicationRecord.status != RECORD_STATUS_OBSOLETE)
        if linked_office_id is not None:
            query = query.filter(PublicationRecord.linked_office_id == linked_office_id)
        if date_from:
            query = query.filter(PublicationRecord.creation_date >= date_from)
        if date_to:
            query = query.filter(PublicationRecord.creation_date < date_to + "T99")
        if category:
            query = query.filter(PublicationRecord.category == category)
        if uf:
            query = query.filter(PublicationRecord.uf == uf.strip().upper())
        # Filtro de vínculo: com_processo / sem_processo
        if vinculo == "sem_processo":
            query = query.filter(PublicationRecord.linked_lawsuit_id.is_(None))
        elif vinculo == "com_processo":
            query = query.filter(PublicationRecord.linked_lawsuit_id.isnot(None))
        if natureza:
            query = query.filter(PublicationRecord.natureza_processo == natureza)
        if polo:
            query = query.filter(PublicationRecord.polo == polo.strip().lower())
        return query

    @staticmethod
    def _build_group(items: list) -> dict[str, Any]:
        """Constrói o dict de um grupo a partir de seus records."""
        first = items[0]

        proposed_task = None
        proposed_tasks: list = []
        if isinstance(first.raw_relationships, dict):
            raw_proposal = first.raw_relationships.get("_proposed_task")
            if raw_proposal:
                payload = raw_proposal.get("payload") if "payload" in raw_proposal else raw_proposal
                if isinstance(payload, dict):
                    if raw_proposal.get("template_name"):
                        payload["template_name"] = raw_proposal["template_name"]
                    if raw_proposal.get("suggested_responsible"):
                        payload["suggested_responsible"] = raw_proposal["suggested_responsible"]
                proposed_task = payload
            raw_proposals = first.raw_relationships.get("_proposed_tasks")
            if raw_proposals and isinstance(raw_proposals, list):
                for rp in raw_proposals:
                    p = rp.get("payload") if isinstance(rp, dict) and "payload" in rp else rp
                    if isinstance(p, dict) and isinstance(rp, dict):
                        if rp.get("template_name"):
                            p["template_name"] = rp["template_name"]
                        if rp.get("suggested_responsible"):
                            p["suggested_responsible"] = rp["suggested_responsible"]
                    if p:
                        proposed_tasks.append(p)
            elif proposed_task:
                proposed_tasks = [proposed_task]

        all_classifications: list = []
        for r in items:
            if isinstance(r.raw_relationships, dict):
                cls_list = r.raw_relationships.get("classifications") or []
                if cls_list:
                    all_classifications.extend(cls_list)
            if hasattr(r, "classifications") and r.classifications:
                for c in r.classifications:
                    if c not in all_classifications:
                        all_classifications.append(c)

        return {
            "lawsuit_id": first.linked_lawsuit_id,
            "lawsuit_cnj": first.linked_lawsuit_cnj,
            "office_id": first.linked_office_id,
            "records": [PublicationSearchService._record_to_dict(r) for r in items],
            "proposed_task": proposed_task,
            "proposed_tasks": proposed_tasks,
            "classifications": all_classifications,
        }

    # ── Endpoint principal ────────────────────────────────────────

    def list_records_grouped(
        self,
        search_id: Optional[int] = None,
        status: Optional[str] = None,
        linked_office_id: Optional[int] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        category: Optional[str] = None,
        uf: Optional[str] = None,
        vinculo: Optional[str] = None,
        natureza: Optional[str] = None,
        polo: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """
        Lista registros agrupados por processo (linked_lawsuit_id).

        Fase 2: filtro UF via SQL (coluna materializada) e paginação de
        grupos no banco em 2 etapas — primeiro busca os lawsuit_ids da
        página, depois carrega apenas os records desses grupos.
        """
        base = self._base_publication_query(
            search_id=search_id, status=status,
            linked_office_id=linked_office_id,
            date_from=date_from, date_to=date_to,
            category=category, uf=uf,
            vinculo=vinculo, natureza=natureza,
            polo=polo,
        )

        # ─── Etapa 1: contar e paginar grupos (lawsuit_ids distintos) ───
        # Calcula uma group_key: lawsuit_id quando existe, senão uma chave
        # sintética. A paginação é sobre essa chave.
        group_key = case(
            (
                PublicationRecord.linked_lawsuit_id.isnot(None),
                sa_func.cast(PublicationRecord.linked_lawsuit_id, sa.String),
            ),
            else_=(
                literal_column("'no-lawsuit|'")
                + sa_func.cast(PublicationRecord.id, sa.String)
            ),
        ).label("group_key")

        groups_subq = (
            base
            .with_entities(group_key, sa_func.count().label("cnt"))
            .group_by(literal_column("group_key"))
            .order_by(literal_column("group_key"))
            .subquery()
        )

        total_groups = self.db.query(sa_func.count()).select_from(groups_subq).scalar() or 0
        total_records = self.db.query(sa_func.sum(groups_subq.c.cnt)).scalar() or 0

        # Busca as group_keys da página atual
        page_keys_rows = (
            self.db.query(groups_subq.c.group_key)
            .order_by(groups_subq.c.group_key)
            .offset(offset)
            .limit(limit)
            .all()
        )
        page_keys = {row[0] for row in page_keys_rows}

        if not page_keys:
            return {
                "total_groups": total_groups,
                "total_records": total_records,
                "offset": offset,
                "limit": limit,
                "groups": [],
            }

        # ─── Etapa 2: carrega records só dos grupos da página ───────
        # Separa lawsuit_ids numéricos de chaves sintéticas (no-lawsuit).
        lawsuit_ids: set[int] = set()
        synthetic_keys: set[str] = set()
        for k in page_keys:
            try:
                lawsuit_ids.add(int(k))
            except (ValueError, TypeError):
                synthetic_keys.add(k)

        page_query = self._base_publication_query(
            search_id=search_id, status=status,
            linked_office_id=linked_office_id,
            date_from=date_from, date_to=date_to,
            category=category, uf=uf,
            vinculo=vinculo, natureza=natureza,
            polo=polo,
        )

        # Filtro: records que pertencem aos grupos da página
        conditions = []
        if lawsuit_ids:
            conditions.append(PublicationRecord.linked_lawsuit_id.in_(lawsuit_ids))
        if synthetic_keys:
            # Para grupos sem processo, temos que carregar os registros
            # que NÃO têm lawsuit_id e reconstruir a chave em Python.
            conditions.append(PublicationRecord.linked_lawsuit_id.is_(None))
        if conditions:
            page_query = page_query.filter(or_(*conditions))

        records = (
            page_query
            .order_by(
                PublicationRecord.linked_lawsuit_id,
                PublicationRecord.publication_date.desc(),
            )
            .all()
        )

        # Agrupa em Python (apenas os records da página — conjunto pequeno)
        groups_map: dict = defaultdict(list)
        for r in records:
            if r.linked_lawsuit_id:
                key = str(r.linked_lawsuit_id)
            else:
                key = f"no-lawsuit|{r.id}"

            # Só inclui se pertence à página
            if key in page_keys:
                groups_map[key].append(r)

        # Mantém a ordem da paginação
        grouped_list = []
        for k in sorted(groups_map.keys()):
            items = groups_map[k]
            if items:
                grouped_list.append(self._build_group(items))

        return {
            "total_groups": total_groups,
            "total_records": total_records,
            "offset": offset,
            "limit": limit,
            "groups": grouped_list,
        }

    def get_record(self, record_id: int) -> dict[str, Any]:
        record = self.db.query(PublicationRecord).filter_by(id=record_id).first()
        if not record:
            raise ValueError(f"Registro #{record_id} não encontrado.")
        return self._record_to_dict(record, include_full_text=True)

    # ──────────────────────────────────────────────
    # Busca por CNJ (diagnóstico)
    # ──────────────────────────────────────────────

    def lookup_by_cnj(self, cnj: str) -> dict[str, Any]:
        """
        Dado um CNJ (com ou sem formatação), retorna tudo que o sistema tem
        sobre aquele processo: buscas que o alcançaram, publicações encontradas,
        classificações atribuídas e estado atual na fila de tratamento (RPA).

        Serve para o operador diagnosticar "o robô já pegou esse processo?
        como classificou? está na fila pra tratar?".
        """
        from app.models.publication_treatment import PublicationTreatmentItem

        raw = (cnj or "").strip()
        digits = "".join(c for c in raw if c.isdigit())
        if not digits:
            raise ValueError("CNJ inválido: informe ao menos os dígitos.")

        # Match tolerante a formatação: compara a forma só-dígitos dos dois lados.
        records = (
            self.db.query(PublicationRecord)
            .filter(
                sa_func.regexp_replace(
                    sa_func.coalesce(PublicationRecord.linked_lawsuit_cnj, ""),
                    r"\D", "", "g",
                )
                == digits
            )
            .order_by(
                PublicationRecord.publication_date.desc().nullslast(),
                PublicationRecord.id.desc(),
            )
            .all()
        )

        # Recupera treatment_items numa query só (evita N+1)
        record_ids = [r.id for r in records]
        treatment_by_record: dict[int, PublicationTreatmentItem] = {}
        if record_ids:
            items = (
                self.db.query(PublicationTreatmentItem)
                .filter(PublicationTreatmentItem.publication_record_id.in_(record_ids))
                .all()
            )
            treatment_by_record = {it.publication_record_id: it for it in items}

        # Buscas distintas que originaram esses registros
        search_ids = sorted({r.search_id for r in records if r.search_id})
        searches: list[dict[str, Any]] = []
        if search_ids:
            search_rows = (
                self.db.query(PublicationSearch)
                .filter(PublicationSearch.id.in_(search_ids))
                .order_by(PublicationSearch.id.desc())
                .all()
            )
            for s in search_rows:
                searches.append({
                    "id": s.id,
                    "status": s.status,
                    "date_from": s.date_from,
                    "date_to": s.date_to,
                    "office_filter": s.office_filter,
                    "requested_by_email": s.requested_by_email,
                    "created_at": s.created_at.isoformat() if s.created_at else None,
                    "finished_at": s.finished_at.isoformat() if s.finished_at else None,
                    "total_found": s.total_found,
                    "total_new": s.total_new,
                    "total_duplicate": s.total_duplicate,
                })

        # Monta payload de cada publicação com detalhe de classificação + RPA
        records_payload: list[dict[str, Any]] = []
        status_counts: dict[str, int] = {}
        category_counts: dict[str, int] = {}
        queue_counts: dict[str, int] = {}
        duplicate_count = 0

        for r in records:
            base = self._record_to_dict(r, include_full_text=True)
            status_counts[r.status] = status_counts.get(r.status, 0) + 1
            if r.category:
                key = r.category + (f" / {r.subcategory}" if r.subcategory and r.subcategory != "-" else "")
                category_counts[key] = category_counts.get(key, 0) + 1
            if r.is_duplicate:
                duplicate_count += 1

            item = treatment_by_record.get(r.id)
            if item is not None:
                queue_counts[item.queue_status] = queue_counts.get(item.queue_status, 0) + 1
                base["treatment"] = {
                    "id": item.id,
                    "queue_status": item.queue_status,
                    "target_status": item.target_status,
                    "source_record_status": item.source_record_status,
                    "attempt_count": item.attempt_count,
                    "last_run_id": item.last_run_id,
                    "last_error": item.last_error,
                    "treated_at": item.treated_at.isoformat() if item.treated_at else None,
                    "last_attempt_at": item.last_attempt_at.isoformat() if item.last_attempt_at else None,
                    "created_at": item.created_at.isoformat() if item.created_at else None,
                    "updated_at": item.updated_at.isoformat() if item.updated_at else None,
                }
            else:
                base["treatment"] = None

            base["is_duplicate"] = r.is_duplicate
            records_payload.append(base)

        lawsuit_id = next(
            (r.linked_lawsuit_id for r in records if r.linked_lawsuit_id is not None),
            None,
        )
        cnj_display = next(
            (r.linked_lawsuit_cnj for r in records if r.linked_lawsuit_cnj),
            raw,
        )

        # Mapeia search_id → requested_by_email para cada publicação
        search_by_id = {s["id"]: s for s in searches}
        for rec in records_payload:
            sid = rec.get("search_id")
            s_info = search_by_id.get(sid, {})
            rec["requested_by_email"] = s_info.get("requested_by_email")

        # Enriquece com dados do processo no Legal One (se tiver lawsuit_id)
        lawsuit_info: dict[str, Any] | None = None
        if lawsuit_id is not None:
            try:
                lawsuit_map = self.client.fetch_lawsuits_by_ids([lawsuit_id])
                raw_lawsuit = lawsuit_map.get(lawsuit_id)
                if raw_lawsuit:
                    # Resolve nome do escritório
                    office_id = raw_lawsuit.get("responsibleOfficeId")
                    office_name = None
                    if office_id is not None:
                        from app.models.legal_one import LegalOneOffice
                        office = (
                            self.db.query(LegalOneOffice)
                            .filter(LegalOneOffice.external_id == office_id)
                            .first()
                        )
                        office_name = office.name if office else None

                    lawsuit_info = {
                        "id": raw_lawsuit.get("id"),
                        "cnj": raw_lawsuit.get("identifierNumber"),
                        "creation_date": raw_lawsuit.get("creationDate"),
                        "responsible_office_id": office_id,
                        "responsible_office_name": office_name,
                    }
            except Exception as exc:
                logger.warning("Falha ao buscar dados do processo %s no Legal One: %s", lawsuit_id, exc)

        # Constrói timeline de eventos a partir dos timestamps disponíveis
        timeline: list[dict[str, Any]] = []
        for rec in records_payload:
            pub_id = rec.get("id")
            # 1) Captura
            if rec.get("created_at"):
                timeline.append({
                    "timestamp": rec["created_at"],
                    "event": "captura",
                    "label": "Publicação capturada pelo robô",
                    "detail": f"Busca #{rec.get('search_id')} · Publicação de {rec.get('publication_date') or '?'}",
                    "user": rec.get("requested_by_email"),
                    "record_id": pub_id,
                })
            # 2) Classificação
            if rec.get("category") and rec.get("updated_at"):
                cls_detail = rec.get("category", "")
                if rec.get("subcategory") and rec["subcategory"] != "-":
                    cls_detail += f" / {rec['subcategory']}"
                if rec.get("polo"):
                    cls_detail += f" · polo: {rec['polo']}"
                timeline.append({
                    "timestamp": rec["updated_at"],
                    "event": "classificacao",
                    "label": "Classificada pela IA",
                    "detail": cls_detail,
                    "user": None,
                    "record_id": pub_id,
                })
            # 3) Status terminal (agendado, ignorado, obsoleta)
            status = rec.get("status", "")
            if status in ("AGENDADO", "IGNORADO", "DESCARTADO_OBSOLETA") and rec.get("updated_at"):
                label_map = {
                    "AGENDADO": "Tarefa agendada no Legal One",
                    "IGNORADO": "Publicação ignorada pelo operador",
                    "DESCARTADO_OBSOLETA": "Descartada como obsoleta (anterior à criação da pasta)",
                }
                timeline.append({
                    "timestamp": rec["updated_at"],
                    "event": "status_change",
                    "label": label_map.get(status, f"Status → {status}"),
                    "detail": None,
                    "user": None,
                    "record_id": pub_id,
                })
            # 4) Tratamento RPA
            treatment = rec.get("treatment")
            if treatment:
                if treatment.get("created_at"):
                    timeline.append({
                        "timestamp": treatment["created_at"],
                        "event": "rpa_enfileirada",
                        "label": f"Enfileirada pro RPA ({treatment.get('target_status') or '?'})",
                        "detail": None,
                        "user": None,
                        "record_id": pub_id,
                    })
                if treatment.get("treated_at"):
                    timeline.append({
                        "timestamp": treatment["treated_at"],
                        "event": "rpa_concluida",
                        "label": "RPA tratou no Legal One",
                        "detail": f"Tentativas: {treatment.get('attempt_count', 0)}",
                        "user": None,
                        "record_id": pub_id,
                    })
                if treatment.get("last_error"):
                    timeline.append({
                        "timestamp": treatment.get("last_attempt_at") or treatment.get("updated_at") or "",
                        "event": "rpa_erro",
                        "label": "Erro no RPA",
                        "detail": treatment["last_error"],
                        "user": None,
                        "record_id": pub_id,
                    })

        # Ordena timeline cronologicamente (mais recente primeiro)
        timeline.sort(key=lambda e: e.get("timestamp") or "", reverse=True)

        return {
            "cnj_input": raw,
            "cnj_normalized": digits,
            "cnj_display": cnj_display,
            "lawsuit_id": lawsuit_id,
            "lawsuit_info": lawsuit_info,
            "found": len(records) > 0,
            "totals": {
                "records": len(records),
                "duplicates": duplicate_count,
                "by_status": status_counts,
                "by_category": category_counts,
                "by_queue_status": queue_counts,
            },
            "timeline": timeline,
            "searches": searches,
            "records": records_payload,
        }

    def update_record_status(self, record_id: int, new_status: str) -> dict[str, Any]:
        valid_statuses = {
            RECORD_STATUS_NEW, RECORD_STATUS_CLASSIFIED,
            RECORD_STATUS_SCHEDULED, RECORD_STATUS_IGNORED, RECORD_STATUS_ERROR,
        }
        if new_status not in valid_statuses:
            raise ValueError(f"Status inválido: {new_status}")

        record = self.db.query(PublicationRecord).filter_by(id=record_id).first()
        if not record:
            raise ValueError(f"Registro #{record_id} não encontrado.")

        record.status = new_status
        record.updated_at = datetime.now(timezone.utc)
        from app.services.publication_treatment_service import PublicationTreatmentService
        treatment_service = PublicationTreatmentService(self.db)
        treatment_service.sync_item_from_record(record, commit=False)
        self.db.commit()
        return self._record_to_dict(record)

    def reclassify_records(
        self,
        record_ids: List[int],
        category: str,
        subcategory: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Aplica manualmente uma classificação (category/subcategory) a um conjunto
        de registros. Preserva polo / audiência / classificações secundárias do JSON
        `classifications` — só altera a classificação primária (index 0).

        Em seguida, reconstrói as propostas de tarefa para esses registros usando
        `_build_task_proposals` (com `skip_responsible_lookup=True` para não bater
        na API de participantes e evitar 429 em edições em série).
        """
        if not record_ids:
            raise ValueError("Nenhum registro informado.")
        category = (category or "").strip()
        if not category:
            raise ValueError("Categoria obrigatória.")
        subcategory = (subcategory or "").strip() or None

        records = (
            self.db.query(PublicationRecord)
            .filter(PublicationRecord.id.in_(record_ids))
            .all()
        )
        if not records:
            raise ValueError("Nenhum registro encontrado.")

        # Captura feedback implícito: se a classificação mudou, registra
        from app.models.classification_feedback import ClassificationFeedback
        for rec in records:
            if rec.category and rec.category != category or (rec.subcategory or None) != subcategory:
                excerpt = (rec.description or "")[:500]
                if excerpt:
                    fb = ClassificationFeedback(
                        record_id=rec.id,
                        feedback_type="implicit",
                        original_category=rec.category,
                        original_subcategory=rec.subcategory,
                        corrected_category=category,
                        corrected_subcategory=subcategory,
                        corrected_polo=rec.polo,
                        text_excerpt=excerpt,
                        office_external_id=rec.linked_office_id,
                    )
                    self.db.add(fb)

        for rec in records:
            rec.category = category
            rec.subcategory = subcategory
            # Atualiza a classificação primária (index 0) do array JSON mantendo
            # campos adicionais (polo, confianca, justificativa, audiencia_*).
            existing = rec.classifications if isinstance(rec.classifications, list) else []
            if existing:
                primary = dict(existing[0])
                primary["categoria"] = category
                primary["subcategoria"] = subcategory
                # Flag para auditoria
                primary["origem"] = "manual_override"
                new_list = [primary] + list(existing[1:])
            else:
                new_list = [{
                    "categoria": category,
                    "subcategoria": subcategory,
                    "polo": rec.polo,
                    "audiencia_data": rec.audiencia_data,
                    "audiencia_hora": rec.audiencia_hora,
                    "audiencia_link": rec.audiencia_link,
                    "confianca": None,
                    "justificativa": "Classificação manual do operador.",
                    "origem": "manual_override",
                }]
            rec.classifications = new_list
            # Se estiver NOVO, promove para CLASSIFICADO
            if rec.status == RECORD_STATUS_NEW:
                rec.status = RECORD_STATUS_CLASSIFIED
            rec.updated_at = datetime.now(timezone.utc)

        self.db.commit()

        # Reconstrói a proposta de tarefa com o template correspondente à
        # nova classificação (se houver template cadastrado).
        self._build_task_proposals(records, skip_responsible_lookup=True)

        return {
            "updated_record_ids": [r.id for r in records],
            "category": category,
            "subcategory": subcategory,
        }

    # ──────────────────────────────────────────────
    # Agendamento (criação de tarefa no LegalOne)
    # ──────────────────────────────────────────────

    def schedule_group(
        self,
        lawsuit_id: int,
        payload_override: Optional[dict] = None,
        payload_overrides: Optional[list[dict]] = None,
    ) -> dict[str, Any]:
        """
        Executa o agendamento de um grupo de publicações (mesmo processo) no LegalOne.

        Aceita 1 ou N payloads numa única chamada. N tarefas são criadas e
        vinculadas ao processo; os registros só são marcados como SCHEDULED
        depois de TODAS as tarefas serem criadas com sucesso.
        """
        records = (
            self.db.query(PublicationRecord)
            .filter(PublicationRecord.linked_lawsuit_id == lawsuit_id)
            .filter(PublicationRecord.status.in_([RECORD_STATUS_NEW, RECORD_STATUS_CLASSIFIED, RECORD_STATUS_IGNORED]))
            .all()
        )
        if not records:
            raise ValueError("Nenhuma publicação pendente para este processo.")

        first = records[0]
        proposals = []
        if isinstance(first.raw_relationships, dict):
            pt = first.raw_relationships.get("_proposed_tasks")
            if isinstance(pt, list):
                proposals = pt
            else:
                p = first.raw_relationships.get("_proposed_task")
                if p:
                    proposals = [p]

        # Determina a lista de payloads a criar
        if payload_overrides:
            payloads = list(payload_overrides)
        elif payload_override:
            payloads = [payload_override]
        else:
            payloads = [p.get("payload") for p in proposals if p and p.get("payload")]

        if not payloads:
            raise ValueError("Proposta de tarefa inexistente. Configure um template.")

        created_task_ids: list[int] = []
        for payload in payloads:
            self._enforce_description_limit(payload)
            created = self.client.create_task(payload)
            if not created or not created.get("id"):
                raise ValueError("Falha ao criar tarefa no Legal One.")
            task_id = created["id"]
            self.client.link_task_to_lawsuit(
                task_id,
                {"linkType": "Litigation", "linkId": lawsuit_id},
            )
            created_task_ids.append(task_id)

        from app.services.publication_treatment_service import PublicationTreatmentService
        treatment_service = PublicationTreatmentService(self.db)
        for r in records:
            r.status = RECORD_STATUS_SCHEDULED
            r.updated_at = datetime.now(timezone.utc)
            treatment_service.sync_item_from_record(r, commit=False)
        self.db.commit()

        return {
            "created_task_id": created_task_ids[0],
            "created_task_ids": created_task_ids,
            "scheduled_publication_ids": [r.id for r in records],
            "lawsuit_id": lawsuit_id,
        }

    def schedule_records(
        self,
        record_ids: List[int],
        payload_override: Optional[dict] = None,
        payload_overrides: Optional[list[dict]] = None,
    ) -> dict[str, Any]:
        """
        Agenda N tarefas para uma lista explícita de record IDs,
        SEM vincular a um processo. Aceita 1 ou N payloads por chamada.
        """
        if not record_ids:
            raise ValueError("Nenhum registro informado.")

        records = (
            self.db.query(PublicationRecord)
            .filter(PublicationRecord.id.in_(record_ids))
            .filter(PublicationRecord.status.in_([RECORD_STATUS_NEW, RECORD_STATUS_CLASSIFIED, RECORD_STATUS_IGNORED]))
            .all()
        )
        if not records:
            raise ValueError("Nenhuma publicação pendente para os IDs informados.")

        first = records[0]
        proposals = []
        if isinstance(first.raw_relationships, dict):
            pt = first.raw_relationships.get("_proposed_tasks")
            if isinstance(pt, list):
                proposals = pt
            else:
                p = first.raw_relationships.get("_proposed_task")
                if p:
                    proposals = [p]

        if payload_overrides:
            payloads = list(payload_overrides)
        elif payload_override:
            payloads = [payload_override]
        else:
            payloads = [p.get("payload") for p in proposals if p and p.get("payload")]

        if not payloads:
            raise ValueError("Proposta de tarefa inexistente. Configure um template global (sem escritório).")

        created_task_ids: list[int] = []
        for payload in payloads:
            self._enforce_description_limit(payload)
            created = self.client.create_task(payload)
            if not created or not created.get("id"):
                raise ValueError("Falha ao criar tarefa no Legal One.")
            created_task_ids.append(created["id"])

        from app.services.publication_treatment_service import PublicationTreatmentService
        treatment_service = PublicationTreatmentService(self.db)
        for r in records:
            r.status = RECORD_STATUS_SCHEDULED
            r.updated_at = datetime.now(timezone.utc)
            treatment_service.sync_item_from_record(r, commit=False)
        self.db.commit()

        return {
            "created_task_id": created_task_ids[0],
            "created_task_ids": created_task_ids,
            "scheduled_publication_ids": [r.id for r in records],
            "lawsuit_id": None,
        }

    # ──────────────────────────────────────────────
    # Contagens para o dashboard
    # ──────────────────────────────────────────────

    def get_statistics(self) -> dict[str, Any]:
        base = self.db.query(PublicationRecord).filter(PublicationRecord.is_duplicate == False)

        total = base.count()
        by_status = dict(
            self.db.query(PublicationRecord.status, sa_func.count(PublicationRecord.id))
            .filter(PublicationRecord.is_duplicate == False)
            .group_by(PublicationRecord.status)
            .all()
        )

        total_searches = self.db.query(PublicationSearch).count()
        last_search = (
            self.db.query(PublicationSearch)
            .order_by(PublicationSearch.created_at.desc())
            .first()
        )

        # Naturezas distintas para filtro dinâmico
        naturezas = [
            row[0] for row in
            self.db.query(PublicationRecord.natureza_processo)
            .filter(PublicationRecord.is_duplicate == False)
            .filter(PublicationRecord.natureza_processo.isnot(None))
            .filter(PublicationRecord.natureza_processo != "")
            .distinct()
            .order_by(PublicationRecord.natureza_processo)
            .all()
        ]

        return {
            "total_records": total,
            "by_status": {
                "novo": by_status.get(RECORD_STATUS_NEW, 0),
                "classificado": by_status.get(RECORD_STATUS_CLASSIFIED, 0),
                "agendado": by_status.get(RECORD_STATUS_SCHEDULED, 0),
                "ignorado": by_status.get(RECORD_STATUS_IGNORED, 0),
                "erro": by_status.get(RECORD_STATUS_ERROR, 0),
            },
            "total_searches": total_searches,
            "last_search": self._search_to_dict(last_search) if last_search else None,
            "available_naturezas": naturezas,
        }

    # ──────────────────────────────────────────────
    # Cancelamento
    # ──────────────────────────────────────────────

    def cancel_search(self, search_id: int) -> bool:
        search = self.db.query(PublicationSearch).filter_by(id=search_id).first()
        if not search or search.status not in (SEARCH_STATUS_RUNNING,):
            return False
        search.status = SEARCH_STATUS_CANCELLED
        search.finished_at = datetime.now(timezone.utc)
        self.db.commit()
        return True

    # ──────────────────────────────────────────────
    # Duplicatas com divergências de texto
    # ──────────────────────────────────────────────

    def list_duplicate_divergences(
        self,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """
        Encontra registros duplicados cujo texto difere do original.
        Retorna pares (original, duplicata) com preview das diferenças.
        """
        from sqlalchemy import func as sqlfunc

        # Encontra update_ids que aparecem mais de uma vez
        subq = (
            self.db.query(PublicationRecord.legal_one_update_id)
            .group_by(PublicationRecord.legal_one_update_id)
            .having(sqlfunc.count(PublicationRecord.id) > 1)
            .subquery()
        )

        # Busca todos os registros com esses update_ids
        records = (
            self.db.query(PublicationRecord)
            .filter(PublicationRecord.legal_one_update_id.in_(
                self.db.query(subq.c.legal_one_update_id)
            ))
            .order_by(
                PublicationRecord.legal_one_update_id,
                PublicationRecord.created_at,
            )
            .all()
        )

        # Agrupa por update_id
        by_update: dict = defaultdict(list)
        for r in records:
            by_update[r.legal_one_update_id].append(r)

        # Filtra apenas os que têm divergência de texto
        divergences = []
        for update_id, group in by_update.items():
            if len(group) < 2:
                continue
            original = group[0]
            original_text = (original.description or "").strip()
            for dup in group[1:]:
                dup_text = (dup.description or "").strip()
                if dup_text != original_text:
                    divergences.append({
                        "legal_one_update_id": update_id,
                        "original": {
                            "id": original.id,
                            "search_id": original.search_id,
                            "status": original.status,
                            "text_preview": original_text[:300],
                            "text_length": len(original_text),
                            "created_at": original.created_at.isoformat() if original.created_at else None,
                        },
                        "duplicate": {
                            "id": dup.id,
                            "search_id": dup.search_id,
                            "status": dup.status,
                            "text_preview": dup_text[:300],
                            "text_length": len(dup_text),
                            "is_duplicate": dup.is_duplicate,
                            "created_at": dup.created_at.isoformat() if dup.created_at else None,
                        },
                        "linked_lawsuit_cnj": original.linked_lawsuit_cnj or dup.linked_lawsuit_cnj,
                    })

        total = len(divergences)
        page = divergences[offset:offset + limit]
        return {"total": total, "offset": offset, "limit": limit, "divergences": page}

    # ──────────────────────────────────────────────
    # Serialização
    # ──────────────────────────────────────────────

    @staticmethod
    def _search_to_dict(search: PublicationSearch) -> dict[str, Any]:
        return {
            "id": search.id,
            "status": search.status,
            "date_from": search.date_from,
            "date_to": search.date_to,
            "origin_type": search.origin_type,
            "office_filter": search.office_filter,
            "total_found": search.total_found,
            "total_new": search.total_new,
            "total_duplicate": search.total_duplicate,
            "progress_step": search.progress_step,
            "progress_detail": search.progress_detail,
            "progress_pct": search.progress_pct,
            "requested_by_email": search.requested_by_email,
            "error_message": search.error_message,
            "created_at": search.created_at.isoformat() if search.created_at else None,
            "finished_at": search.finished_at.isoformat() if search.finished_at else None,
        }

    @staticmethod
    def _record_to_dict(record: PublicationRecord, include_full_text: bool = False) -> dict[str, Any]:
        proposal = None
        proposals = None
        if isinstance(record.raw_relationships, dict):
            proposal = record.raw_relationships.get("_proposed_task")
            proposals = record.raw_relationships.get("_proposed_tasks")

        result = {
            "id": record.id,
            "search_id": record.search_id,
            "legal_one_update_id": record.legal_one_update_id,
            "origin_type": record.origin_type,
            "update_type_id": record.update_type_id,
            "description_preview": (record.description or "")[:200],
            "publication_date": record.publication_date,
            "creation_date": record.creation_date,
            "linked_lawsuit_id": record.linked_lawsuit_id,
            "linked_lawsuit_cnj": record.linked_lawsuit_cnj,
            "linked_office_id": record.linked_office_id,
            "status": record.status,
            "category": record.category,
            "subcategory": record.subcategory,
            "polo": record.polo,
            "audiencia_data": record.audiencia_data,
            "audiencia_hora": record.audiencia_hora,
            "audiencia_link": record.audiencia_link,
            "classifications": record.classifications,
            "uf": record.uf,
            "natureza_processo": record.natureza_processo,
            "has_proposal": bool(proposal),
            "proposal": proposal if include_full_text else None,
            "proposals_count": len(proposals) if proposals else (1 if proposal else 0),
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "updated_at": record.updated_at.isoformat() if record.updated_at else None,
        }
        if include_full_text:
            result["description"] = record.description
            result["notes"] = record.notes
            result["raw_relationships"] = record.raw_relationships
        return result
