"""Serviço do módulo Citações BM.

Orquestra a ingestão de processos (lista manual de CNJ ou puxada
automática do Legal One por escritório+data), a varredura diária no
DataJud, a marcação de citação pelo operador e a listagem paginada.

Regra de ouro: o sistema só TRAZ movimentações. O status de citação é
alterado EXCLUSIVAMENTE pelo operador (nunca pelo scan).
"""

import hashlib
import logging
import time
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.utils import format_cnj
from app.models.citacoes_bm import (
    ORIGEM_L1_AUTO,
    ORIGEM_LISTA,
    SCAN_ERRO,
    SCAN_OK,
    SCAN_SEM_HITS,
    STATUS_CITADO,
    STATUS_NAO_CITADO,
    STATUS_PENDENTE,
    CitacaoBMMovimento,
    CitacaoBMProcesso,
)
from app.models.legal_one import LegalOneOffice
from app.services.citacoes_bm.datajud import buscar_movimentos, get_client
from app.services.citacoes_bm.heuristic import avaliar_candidato
from app.services.citacoes_bm.tribunal_alias import (
    cnj_digits,
    resolve_tribunal_alias,
    uf_do_cnj,
)

logger = logging.getLogger(__name__)

# Painel web do L1 (mesmo base usado no módulo de Publicações). O operador
# é mandado pra aba de Andamentos do processo, onde confirma a citação e
# faz a habilitação.
L1_WEB_BASE_URL = "https://mdradvocacia.novajus.com.br"

# Escritório do Banco Master (Réu) — confirmado external_id=61. Resolvido
# dinamicamente pelo path; a constante é só fallback se o catálogo de
# escritórios não estiver sincronizado.
BANCO_MASTER_REU_PATH = "MDR Advocacia / Área operacional / Banco Master / Réu"
BANCO_MASTER_REU_OFFICE_ID = 61

STATUS_VALIDOS = {STATUS_PENDENTE, STATUS_CITADO, STATUS_NAO_CITADO}


def build_l1_folder_url(lawsuit_id: int | None) -> str | None:
    """Deep-link pra aba de Andamentos do processo no painel web do L1."""
    if not lawsuit_id:
        return None
    return (
        f"{L1_WEB_BASE_URL}/processos/processos/DetailsAndamentos/{int(lawsuit_id)}"
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value: Any) -> datetime | None:
    """Parse de timestamp ISO do DataJud/L1 ('...Z' ou com offset)."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    s = str(value).strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        # DataJud às vezes manda só data (YYYY-MM-DD) ou compacto.
        for fmt in ("%Y-%m-%d", "%Y%m%d%H%M%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                dt = datetime.strptime(s[: len(fmt) + 4], fmt)
                break
            except ValueError:
                continue
        else:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _movement_fingerprint(
    grau: Any, codigo: Any, data_hora: Any, nome: Any, complementos: Any
) -> str:
    raw = "|".join(
        [
            str(grau or ""),
            str(codigo or ""),
            str(data_hora or ""),
            str(nome or ""),
            str(complementos or ""),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _to_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


class CitacoesBMService:
    def __init__(self, db: Session, l1_client: Any | None = None) -> None:
        self.db = db
        self._l1_client = l1_client  # lazy
        self._office_path_cache: dict[int, str | None] = {}

    # ── Legal One (lazy + tolerante a falta de credencial) ────────────
    def _l1(self):
        if self._l1_client is None:
            from app.services.legal_one_client import LegalOneApiClient

            self._l1_client = LegalOneApiClient()
        return self._l1_client

    def _office_path(self, external_id: int | None) -> str | None:
        if not external_id:
            return None
        if external_id in self._office_path_cache:
            return self._office_path_cache[external_id]
        office = (
            self.db.query(LegalOneOffice)
            .filter(LegalOneOffice.external_id == external_id)
            .first()
        )
        path = office.path if office else None
        self._office_path_cache[external_id] = path
        return path

    def resolve_banco_master_office(self) -> tuple[int, str]:
        """Devolve (external_id, path) do escritório Banco Master / Réu."""
        office = (
            self.db.query(LegalOneOffice)
            .filter(LegalOneOffice.path == BANCO_MASTER_REU_PATH)
            .first()
        )
        if office:
            return office.external_id, office.path
        # Fallback tolerante a acento/normalização do path.
        office = (
            self.db.query(LegalOneOffice)
            .filter(
                LegalOneOffice.path.ilike("%Banco Master%"),
                or_(
                    LegalOneOffice.path.ilike("%Réu%"),
                    LegalOneOffice.path.ilike("%Reu%"),
                ),
            )
            .first()
        )
        if office:
            return office.external_id, office.path
        logger.warning(
            "Escritório Banco Master/Réu não encontrado no catálogo; "
            "usando fallback id=%s.",
            BANCO_MASTER_REU_OFFICE_ID,
        )
        return BANCO_MASTER_REU_OFFICE_ID, BANCO_MASTER_REU_PATH

    # ── Ingestão ──────────────────────────────────────────────────────
    def ingest_lista(
        self, cnjs: Iterable[str], created_by_email: str | None = None
    ) -> dict[str, Any]:
        """Ingere uma lista de CNJs (colados pelo operador)."""
        validos: list[str] = []
        invalidos: list[str] = []
        seen: set[str] = set()
        for raw in cnjs:
            digits = cnj_digits(raw)
            if not digits or len(digits) != 20:
                if raw and str(raw).strip():
                    invalidos.append(str(raw).strip())
                continue
            if digits in seen:
                continue
            seen.add(digits)
            validos.append(digits)

        existentes = {
            row.cnj
            for row in self.db.query(CitacaoBMProcesso.cnj)
            .filter(CitacaoBMProcesso.cnj.in_(validos))
            .all()
        } if validos else set()
        duplicados = [c for c in validos if c in existentes]
        novos = [c for c in validos if c not in existentes]

        # Resolução L1 (best-effort): CNJ -> lawsuit_id / office / creationDate.
        l1_map: dict[str, dict[str, Any]] = {}
        if novos:
            try:
                l1_map = self._l1().search_lawsuits_by_cnj_numbers(novos) or {}
            except Exception as exc:
                logger.warning("Resolução L1 falhou na ingestão por lista: %s", exc)
                l1_map = {}

        l1_encontrados = 0
        for digits in novos:
            item = l1_map.get(digits) or l1_map.get(format_cnj(digits))
            office_id = None
            lawsuit_id = None
            l1_created = None
            if item:
                l1_encontrados += 1
                lawsuit_id = _to_int(item.get("id"))
                office_id = _to_int(item.get("responsibleOfficeId"))
                l1_created = _parse_dt(item.get("creationDate"))

            proc = CitacaoBMProcesso(
                cnj=digits,
                cnj_mask=format_cnj(digits),
                lawsuit_id=lawsuit_id,
                office_external_id=office_id,
                office_path=self._office_path(office_id),
                l1_creation_date=l1_created,
                tribunal_alias=resolve_tribunal_alias(digits),
                uf=uf_do_cnj(digits),
                origem=ORIGEM_LISTA,
                status_citacao=STATUS_PENDENTE,
                monitoramento_ativo=True,
                created_by_email=created_by_email,
            )
            self.db.add(proc)

        self.db.commit()
        return {
            "total_recebidos": len(validos) + len(invalidos),
            "validos": len(validos),
            "criados": len(novos),
            "duplicados": duplicados,
            "invalidos": invalidos,
            "l1_encontrados": l1_encontrados,
            "l1_nao_encontrados": [c for c in novos if c not in l1_map
                                   and format_cnj(c) not in l1_map],
        }

    def ingest_l1_auto(
        self, data_corte: str | None = None, created_by_email: str | None = None
    ) -> dict[str, Any]:
        """Puxa do L1 os processos novos do Banco Master/Réu (creationDate>=corte)."""
        office_id, office_path = self.resolve_banco_master_office()
        if not data_corte:
            data_corte = _now().date().isoformat()

        try:
            lawsuits = self._l1().fetch_lawsuits_by_office_since(
                office_id, data_corte
            )
        except Exception as exc:
            logger.warning("fetch_lawsuits_by_office_since falhou: %s", exc)
            return {
                "office_external_id": office_id,
                "data_corte": data_corte,
                "encontrados_l1": 0,
                "criados": 0,
                "duplicados": 0,
                "erro": str(exc),
            }

        criados = 0
        duplicados = 0
        existentes = {
            row.cnj for row in self.db.query(CitacaoBMProcesso.cnj).all()
        }
        for item in lawsuits:
            digits = cnj_digits(item.get("identifierNumber"))
            if not digits or len(digits) != 20:
                continue
            if digits in existentes:
                duplicados += 1
                continue
            existentes.add(digits)
            proc = CitacaoBMProcesso(
                cnj=digits,
                cnj_mask=format_cnj(digits),
                lawsuit_id=_to_int(item.get("id")),
                office_external_id=_to_int(item.get("responsibleOfficeId"))
                or office_id,
                office_path=office_path,
                l1_creation_date=_parse_dt(item.get("creationDate")),
                tribunal_alias=resolve_tribunal_alias(digits),
                uf=uf_do_cnj(digits),
                origem=ORIGEM_L1_AUTO,
                status_citacao=STATUS_PENDENTE,
                monitoramento_ativo=True,
                created_by_email=created_by_email,
            )
            self.db.add(proc)
            criados += 1

        self.db.commit()
        return {
            "office_external_id": office_id,
            "data_corte": data_corte,
            "encontrados_l1": len(lawsuits),
            "criados": criados,
            "duplicados": duplicados,
        }

    # ── Varredura DataJud ─────────────────────────────────────────────
    def _recompute_counters(self, proc: CitacaoBMProcesso) -> None:
        agg = (
            self.db.query(
                func.count(CitacaoBMMovimento.id),
                func.count(CitacaoBMMovimento.id).filter(
                    CitacaoBMMovimento.lido.is_(False)
                ),
                func.max(CitacaoBMMovimento.data_hora),
                func.count(CitacaoBMMovimento.id).filter(
                    CitacaoBMMovimento.is_candidato_citacao.is_(True)
                ),
            )
            .filter(CitacaoBMMovimento.processo_id == proc.id)
            .one()
        )
        total, novos, last_mov, candidatos = agg
        proc.total_movimentos = int(total or 0)
        proc.novos_movimentos = int(novos or 0)
        proc.last_movement_at = last_mov
        proc.tem_candidato_citacao = bool(candidatos)

    def scan_processo(
        self, proc: CitacaoBMProcesso, client: Any | None = None
    ) -> dict[str, Any]:
        """Varre 1 processo no DataJud e insere os movimentos novos."""
        alias = proc.tribunal_alias or resolve_tribunal_alias(proc.cnj)
        if not alias:
            proc.last_scan_at = _now()
            proc.last_scan_status = SCAN_ERRO
            proc.last_scan_error = "Tribunal não mapeado para o CNJ."
            self.db.commit()
            return {"status": SCAN_ERRO, "novos": 0, "erro": "tribunal_nao_mapeado"}
        if not proc.tribunal_alias:
            proc.tribunal_alias = alias

        try:
            resultado = buscar_movimentos(proc.cnj, alias, client=client)
        except Exception as exc:
            proc.last_scan_at = _now()
            proc.last_scan_status = SCAN_ERRO
            proc.last_scan_error = str(exc)[:500]
            self.db.commit()
            logger.warning("Scan DataJud falhou p/ %s [%s]: %s", proc.cnj, alias, exc)
            return {"status": SCAN_ERRO, "novos": 0, "erro": str(exc)[:200]}

        if resultado["status"] == SCAN_SEM_HITS:
            proc.last_scan_at = _now()
            proc.last_scan_status = SCAN_SEM_HITS
            proc.last_scan_error = None
            self.db.commit()
            return {"status": SCAN_SEM_HITS, "novos": 0}

        existing_fps = {
            row.fingerprint
            for row in self.db.query(CitacaoBMMovimento.fingerprint)
            .filter(CitacaoBMMovimento.processo_id == proc.id)
            .all()
        }
        novos = 0
        for mov in resultado["movimentos"]:
            fp = _movement_fingerprint(
                mov.get("grau"),
                mov.get("codigo"),
                mov.get("dataHora"),
                mov.get("nome"),
                mov.get("complementos"),
            )
            if fp in existing_fps:
                continue
            existing_fps.add(fp)
            cand, termo = avaliar_candidato(mov.get("nome"), mov.get("complementos"))
            self.db.add(
                CitacaoBMMovimento(
                    processo_id=proc.id,
                    codigo_tpu=_to_int(mov.get("codigo")),
                    nome=mov.get("nome") or "Movimento sem nome",
                    grau=mov.get("grau"),
                    data_hora=_parse_dt(mov.get("dataHora")),
                    complementos=mov.get("complementos") or None,
                    orgao_julgador=mov.get("orgao"),
                    fingerprint=fp,
                    is_candidato_citacao=cand,
                    cit_match_termo=termo,
                    lido=False,
                )
            )
            novos += 1

        self.db.flush()
        proc.last_scan_at = _now()
        proc.last_scan_status = SCAN_OK
        proc.last_scan_error = None
        self._recompute_counters(proc)
        self.db.commit()
        return {"status": SCAN_OK, "novos": novos}

    def scan_all(self, limit: int | None = None) -> dict[str, Any]:
        """Varre todos os processos ativos (job diário / botão geral)."""
        client = get_client()
        query = (
            self.db.query(CitacaoBMProcesso)
            .filter(CitacaoBMProcesso.monitoramento_ativo.is_(True))
            .order_by(
                CitacaoBMProcesso.last_scan_at.asc().nullsfirst(),
                CitacaoBMProcesso.id.asc(),
            )
        )
        if limit:
            query = query.limit(limit)
        processos = query.all()

        ok = sem_hits = erro = total_novos = 0
        for idx, proc in enumerate(processos):
            if idx:
                # Educado com a API pública do DataJud (evita throttle 429).
                time.sleep(0.25)
            res = self.scan_processo(proc, client=client)
            if res["status"] == SCAN_OK:
                ok += 1
                total_novos += res.get("novos", 0)
            elif res["status"] == SCAN_SEM_HITS:
                sem_hits += 1
            else:
                erro += 1
        return {
            "processos": len(processos),
            "ok": ok,
            "sem_hits": sem_hits,
            "erro": erro,
            "novos_movimentos": total_novos,
        }

    # ── Ações do operador ─────────────────────────────────────────────
    def marcar_citacao(
        self,
        processo_id: int,
        status: str,
        user_id: int | None = None,
        user_nome: str | None = None,
        observacao: str | None = None,
    ) -> CitacaoBMProcesso | None:
        if status not in STATUS_VALIDOS:
            raise ValueError(f"Status inválido: {status}")
        proc = (
            self.db.query(CitacaoBMProcesso)
            .filter(CitacaoBMProcesso.id == processo_id)
            .first()
        )
        if not proc:
            return None

        proc.status_citacao = status
        if observacao is not None:
            proc.observacao = observacao
        if status == STATUS_CITADO:
            proc.citado_por_user_id = user_id
            proc.citado_por_nome = user_nome
            proc.citado_em = _now()
            # Já cumpriu o objetivo: arquiva (sai da varredura diária).
            proc.monitoramento_ativo = False
        else:
            # Reabriu / não é citação: volta a monitorar e limpa o registro.
            proc.monitoramento_ativo = True
            proc.citado_por_user_id = None
            proc.citado_por_nome = None
            proc.citado_em = None
        self.db.commit()
        self.db.refresh(proc)
        return proc

    def marcar_lidos(self, processo_id: int) -> int:
        count = (
            self.db.query(CitacaoBMMovimento)
            .filter(
                CitacaoBMMovimento.processo_id == processo_id,
                CitacaoBMMovimento.lido.is_(False),
            )
            .update({CitacaoBMMovimento.lido: True}, synchronize_session=False)
        )
        proc = (
            self.db.query(CitacaoBMProcesso)
            .filter(CitacaoBMProcesso.id == processo_id)
            .first()
        )
        if proc:
            proc.novos_movimentos = 0
        self.db.commit()
        return count

    # ── Leitura / listagem ────────────────────────────────────────────
    @staticmethod
    def _processo_to_dict(proc: CitacaoBMProcesso) -> dict[str, Any]:
        return {
            "id": proc.id,
            "cnj": proc.cnj,
            "cnj_mask": proc.cnj_mask,
            "lawsuit_id": proc.lawsuit_id,
            "l1_url": build_l1_folder_url(proc.lawsuit_id),
            "office_external_id": proc.office_external_id,
            "office_path": proc.office_path,
            "l1_creation_date": proc.l1_creation_date,
            "tribunal_alias": proc.tribunal_alias,
            "uf": proc.uf,
            "cidade": proc.cidade,
            "acao": proc.acao,
            "cliente": proc.cliente,
            "contrario": proc.contrario,
            "origem": proc.origem,
            "status_citacao": proc.status_citacao,
            "citado_por_nome": proc.citado_por_nome,
            "citado_em": proc.citado_em,
            "observacao": proc.observacao,
            "monitoramento_ativo": proc.monitoramento_ativo,
            "last_scan_at": proc.last_scan_at,
            "last_scan_status": proc.last_scan_status,
            "last_movement_at": proc.last_movement_at,
            "total_movimentos": proc.total_movimentos,
            "novos_movimentos": proc.novos_movimentos,
            "tem_candidato_citacao": proc.tem_candidato_citacao,
            "created_at": proc.created_at,
        }

    @staticmethod
    def _movimento_to_dict(mov: CitacaoBMMovimento) -> dict[str, Any]:
        return {
            "id": mov.id,
            "codigo_tpu": mov.codigo_tpu,
            "nome": mov.nome,
            "grau": mov.grau,
            "data_hora": mov.data_hora,
            "complementos": mov.complementos,
            "orgao_julgador": mov.orgao_julgador,
            "is_candidato_citacao": mov.is_candidato_citacao,
            "cit_match_termo": mov.cit_match_termo,
            "lido": mov.lido,
            "captured_at": mov.captured_at,
        }

    def list_processos(
        self,
        status: str | None = None,
        origem: str | None = None,
        tribunal_alias: str | None = None,
        uf: str | None = None,
        apenas_com_novos: bool = False,
        arquivados: str = "ativos",
        q: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        query = self.db.query(CitacaoBMProcesso)
        if status:
            query = query.filter(CitacaoBMProcesso.status_citacao == status)
        if origem:
            query = query.filter(CitacaoBMProcesso.origem == origem)
        if tribunal_alias:
            query = query.filter(
                CitacaoBMProcesso.tribunal_alias == tribunal_alias
            )
        if uf:
            query = query.filter(CitacaoBMProcesso.uf == uf.upper())
        if apenas_com_novos:
            query = query.filter(CitacaoBMProcesso.novos_movimentos > 0)
        if arquivados == "ativos":
            query = query.filter(CitacaoBMProcesso.monitoramento_ativo.is_(True))
        elif arquivados == "arquivados":
            query = query.filter(CitacaoBMProcesso.monitoramento_ativo.is_(False))
        # "todos" => sem filtro
        if q:
            termo = f"%{cnj_digits(q) or q.strip()}%"
            query = query.filter(CitacaoBMProcesso.cnj.ilike(termo))

        total = query.count()
        rows = (
            query.order_by(
                CitacaoBMProcesso.tem_candidato_citacao.desc(),
                CitacaoBMProcesso.novos_movimentos.desc(),
                CitacaoBMProcesso.last_movement_at.desc().nullslast(),
                CitacaoBMProcesso.id.desc(),
            )
            .limit(max(1, min(limit, 500)))
            .offset(max(0, offset))
            .all()
        )
        return {
            "total": total,
            "items": [self._processo_to_dict(r) for r in rows],
        }

    def get_processo_detail(self, processo_id: int) -> dict[str, Any] | None:
        proc = (
            self.db.query(CitacaoBMProcesso)
            .filter(CitacaoBMProcesso.id == processo_id)
            .first()
        )
        if not proc:
            return None
        movimentos = (
            self.db.query(CitacaoBMMovimento)
            .filter(CitacaoBMMovimento.processo_id == processo_id)
            .order_by(
                CitacaoBMMovimento.data_hora.desc().nullslast(),
                CitacaoBMMovimento.id.desc(),
            )
            .all()
        )
        data = self._processo_to_dict(proc)
        data["movimentos"] = [self._movimento_to_dict(m) for m in movimentos]
        data["candidatos_count"] = sum(
            1 for m in movimentos if m.is_candidato_citacao
        )
        return data

    def get_summary(self) -> dict[str, Any]:
        """Contadores pros cards do topo da página."""
        base = self.db.query(func.count(CitacaoBMProcesso.id))

        def _count(*filters):
            q = self.db.query(func.count(CitacaoBMProcesso.id))
            for f in filters:
                q = q.filter(f)
            return int(q.scalar() or 0)

        return {
            "total": int(base.scalar() or 0),
            "monitorando": _count(
                CitacaoBMProcesso.monitoramento_ativo.is_(True)
            ),
            "pendentes": _count(
                CitacaoBMProcesso.status_citacao == STATUS_PENDENTE,
                CitacaoBMProcesso.monitoramento_ativo.is_(True),
            ),
            "com_novos": _count(CitacaoBMProcesso.novos_movimentos > 0),
            "com_candidato": _count(
                CitacaoBMProcesso.tem_candidato_citacao.is_(True),
                CitacaoBMProcesso.monitoramento_ativo.is_(True),
            ),
            "citados": _count(CitacaoBMProcesso.status_citacao == STATUS_CITADO),
            "nao_citados": _count(
                CitacaoBMProcesso.status_citacao == STATUS_NAO_CITADO
            ),
        }
