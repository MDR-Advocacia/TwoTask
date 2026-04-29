"""
Serviço da fila de classificação AJUS — RPA Playwright (Chunk 1).

Operações:
  - Defaults singleton (admin edita matter+risco padrão).
  - Enqueue automático a partir do intake (intake_auto).
  - Enqueue em lote a partir de planilha XLSX (origem=planilha).
  - Listar / atualizar / cancelar / retry / get.
  - Geração da planilha modelo (template) com cabeçalhos esperados.

Derivações (origem=intake_auto):
  - `uf` → derivada do CNJ via `uf_from_cnj` (publication_search_service).
  - `comarca` → `integra_json.detalhes_extra.Jurisdição` (preferencial)
    → fallback parse do `capa_json.vara` (pega o trecho final após
    " DE ", ex.: "2ª V DOS FEITOS DE ... DE ITABUNA" → "ITABUNA").
  - `matter` → `defaults.default_matter` (admin configura na UI).
  - `risk_loss_probability` → `defaults.default_risk_loss_probability`.
  - `justice_fee` → NULL (Chunk 3 derivará da capa; por ora operador
    edita por linha antes do dispatch ou já preenche na planilha).

NÃO chama AJUS aqui — só prepara a fila. O runner Playwright vem no
Chunk 2.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from sqlalchemy.orm import Session

from app.models.ajus import (
    AJUS_CLASSIF_CANCELADO,
    AJUS_CLASSIF_ERRO,
    AJUS_CLASSIF_ORIGEM_INTAKE,
    AJUS_CLASSIF_ORIGEM_PLANILHA,
    AJUS_CLASSIF_PENDENTE,
    AJUS_CLASSIF_PROCESSANDO,
    AJUS_CLASSIF_STATUSES,
    AJUS_CLASSIF_SUCESSO,
    AjusClassificacaoDefaults,
    AjusClassificacaoQueue,
)
from app.models.prazo_inicial import PrazoInicialIntake
from app.services.publication_search_service import uf_from_cnj

logger = logging.getLogger(__name__)


# ─── Helpers de derivação ─────────────────────────────────────────────


# Regex pra capturar o último trecho após " DE " na string da vara.
# Ex.: "2ª V DOS FEITOS DE REL. DE CONS. ... DE ITABUNA" → "ITABUNA"
# Ex.: "VARA CIVEL DE SALVADOR" → "SALVADOR"
# Pega greedy até o fim, depois a última ocorrência de " DE ".
_VARA_CITY_RE = re.compile(r"\s+DE\s+([A-ZÁÉÍÓÚÂÊÔÃÕÇ' \-]+?)\s*$", re.IGNORECASE)


def _normalize_cnj_digits(cnj: Optional[str]) -> str:
    if not cnj:
        return ""
    return "".join(c for c in cnj if c.isdigit())


def _city_from_vara(vara: Optional[str]) -> Optional[str]:
    """
    Tenta extrair o nome da comarca a partir da string da vara
    (capa_json.vara). Heurística: pega o último trecho após " DE ".
    """
    if not vara:
        return None
    s = str(vara).strip()
    if not s:
        return None
    m = _VARA_CITY_RE.search(s)
    if not m:
        return None
    city = m.group(1).strip()
    if not city:
        return None
    # Limpa lixo comum no fim (pontos, espaços duplos)
    city = re.sub(r"\s{2,}", " ", city)
    city = city.rstrip(".")
    return city or None


def derive_uf_from_intake(intake: PrazoInicialIntake) -> Optional[str]:
    """UF derivada do CNJ (mesmo helper já usado em publications)."""
    return uf_from_cnj(intake.cnj_number)


def derive_comarca_from_intake(intake: PrazoInicialIntake) -> Optional[str]:
    """
    Comarca preferencial: `integra_json.detalhes_extra.Jurisdição`.
    Fallback: parse do `capa_json.vara`.
    Retorna None se nem um nem outro produziu valor.
    """
    integra = intake.integra_json or {}
    detalhes = (integra.get("detalhes_extra") or {}) if isinstance(integra, dict) else {}
    if isinstance(detalhes, dict):
        jurisdicao = detalhes.get("Jurisdição") or detalhes.get("Jurisdicao")
        if isinstance(jurisdicao, str) and jurisdicao.strip():
            return jurisdicao.strip()

    capa = intake.capa_json or {}
    vara = capa.get("vara") if isinstance(capa, dict) else None
    return _city_from_vara(vara)


# ─── Serviço ─────────────────────────────────────────────────────────


@dataclass
class XlsxRow:
    """Linha da planilha de classificação (validada pelo endpoint)."""

    cnj_number: str
    uf: Optional[str]
    comarca: Optional[str]
    matter: Optional[str]
    justice_fee: Optional[str]
    risk_loss_probability: Optional[str]


# Cabeçalhos esperados na planilha (template). Ordem é a ordem do
# arquivo gerado em /ajus/classificacao/template.xlsx.
XLSX_HEADERS: tuple[str, ...] = (
    "CNJ",
    "UF",
    "Comarca",
    "Matéria",
    "Justiça/Honorário",
    "Risco/Probabilidade Perda",
)


class AjusClassificacaoService:
    """Operações da fila de classificação."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # ── Defaults singleton ──────────────────────────────────────────

    def get_defaults(self) -> AjusClassificacaoDefaults:
        """Retorna o singleton id=1 (cria se não existir — defensivo)."""
        obj = self.db.get(AjusClassificacaoDefaults, 1)
        if obj is None:
            obj = AjusClassificacaoDefaults(id=1)
            self.db.add(obj)
            self.db.commit()
            self.db.refresh(obj)
        return obj

    def update_defaults(
        self,
        *,
        default_matter: Optional[str],
        default_risk_loss_probability: Optional[str],
    ) -> AjusClassificacaoDefaults:
        obj = self.get_defaults()
        obj.default_matter = (default_matter or "").strip() or None
        obj.default_risk_loss_probability = (
            (default_risk_loss_probability or "").strip() or None
        )
        self.db.commit()
        self.db.refresh(obj)
        return obj

    # ── Enqueue origem=intake_auto ──────────────────────────────────

    def enqueue_from_intake(
        self, intake: PrazoInicialIntake,
    ) -> Optional[AjusClassificacaoQueue]:
        """
        Cria item na fila com origem `intake_auto`. Idempotente —
        se o CNJ já existe na fila, retorna o registro existente
        sem sobrescrever (operador pode estar em meio a edição).
        """
        cnj = _normalize_cnj_digits(intake.cnj_number)
        if not cnj:
            logger.warning(
                "AJUS classif enqueue: intake %d sem CNJ válido — pulando",
                intake.id,
            )
            return None

        existing = (
            self.db.query(AjusClassificacaoQueue)
            .filter(AjusClassificacaoQueue.cnj_number == cnj)
            .one_or_none()
        )
        if existing is not None:
            logger.debug(
                "AJUS classif enqueue: CNJ %s já tem item id=%d (status=%s) — pulando",
                cnj, existing.id, existing.status,
            )
            return existing

        defaults = self.get_defaults()
        item = AjusClassificacaoQueue(
            cnj_number=cnj,
            intake_id=intake.id,
            origem=AJUS_CLASSIF_ORIGEM_INTAKE,
            uf=derive_uf_from_intake(intake),
            comarca=derive_comarca_from_intake(intake),
            matter=defaults.default_matter,
            justice_fee=None,  # Chunk 3 — derivar da capa.
            risk_loss_probability=defaults.default_risk_loss_probability,
            status=AJUS_CLASSIF_PENDENTE,
        )
        self.db.add(item)
        self.db.commit()
        self.db.refresh(item)
        logger.info(
            "AJUS classif enqueue: item id=%d criado (cnj=%s, origem=intake_auto)",
            item.id, cnj,
        )
        return item

    # ── Enqueue origem=planilha ─────────────────────────────────────

    def enqueue_from_xlsx_rows(
        self, rows: Iterable[XlsxRow],
    ) -> dict[str, Any]:
        """
        Processa N linhas da planilha. Cada linha:
          - CNJ obrigatório (normalizado em dígitos).
          - Demais campos: o que vier vai pro registro.

        Comportamento em colisão de CNJ:
          - Se já existe e está pendente: ATUALIZA campos com valores
            da planilha (operador pode reupar pra corrigir).
          - Se já existe em outro status (sucesso/processando/erro/cancelado):
            IGNORA pra preservar histórico (operador usa retry/cancel
            pra lidar caso a caso).
        """
        created = 0
        updated = 0
        skipped: list[dict[str, Any]] = []

        for row in rows:
            cnj = _normalize_cnj_digits(row.cnj_number)
            if not cnj:
                skipped.append(
                    {"cnj": row.cnj_number, "motivo": "CNJ inválido ou vazio"},
                )
                continue

            existing = (
                self.db.query(AjusClassificacaoQueue)
                .filter(AjusClassificacaoQueue.cnj_number == cnj)
                .one_or_none()
            )
            if existing is None:
                item = AjusClassificacaoQueue(
                    cnj_number=cnj,
                    intake_id=None,
                    origem=AJUS_CLASSIF_ORIGEM_PLANILHA,
                    uf=(row.uf or "").strip() or uf_from_cnj(cnj),
                    comarca=(row.comarca or "").strip() or None,
                    matter=(row.matter or "").strip() or None,
                    justice_fee=(row.justice_fee or "").strip() or None,
                    risk_loss_probability=(
                        (row.risk_loss_probability or "").strip() or None
                    ),
                    status=AJUS_CLASSIF_PENDENTE,
                )
                self.db.add(item)
                created += 1
                continue

            if existing.status != AJUS_CLASSIF_PENDENTE:
                skipped.append({
                    "cnj": cnj,
                    "motivo": (
                        f"Já existe em status '{existing.status}'. "
                        "Use cancel+novo upload ou retry."
                    ),
                })
                continue

            # Atualiza pendente com valores da planilha
            existing.uf = (row.uf or "").strip() or existing.uf or uf_from_cnj(cnj)
            existing.comarca = (row.comarca or "").strip() or existing.comarca
            existing.matter = (row.matter or "").strip() or existing.matter
            existing.justice_fee = (
                (row.justice_fee or "").strip() or existing.justice_fee
            )
            existing.risk_loss_probability = (
                (row.risk_loss_probability or "").strip()
                or existing.risk_loss_probability
            )
            # Origem migra pra planilha — operador subiu, dado é dele
            existing.origem = AJUS_CLASSIF_ORIGEM_PLANILHA
            updated += 1

        self.db.commit()
        return {
            "created": created,
            "updated": updated,
            "skipped": skipped,
        }

    # ── Queries ─────────────────────────────────────────────────────

    def list(
        self,
        *,
        statuses: Optional[list[str]] = None,
        origem: Optional[str] = None,
        cnj_search: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[int, list[AjusClassificacaoQueue]]:
        q = self.db.query(AjusClassificacaoQueue)
        if statuses:
            invalid = set(statuses) - AJUS_CLASSIF_STATUSES
            if invalid:
                raise ValueError(
                    f"Status inválido(s): {sorted(invalid)}",
                )
            if len(statuses) == 1:
                q = q.filter(AjusClassificacaoQueue.status == statuses[0])
            else:
                q = q.filter(AjusClassificacaoQueue.status.in_(statuses))
        if origem:
            if origem not in (
                AJUS_CLASSIF_ORIGEM_INTAKE, AJUS_CLASSIF_ORIGEM_PLANILHA,
            ):
                raise ValueError(f"Origem inválida: {origem}")
            q = q.filter(AjusClassificacaoQueue.origem == origem)
        if cnj_search:
            digits = _normalize_cnj_digits(cnj_search)
            if digits:
                q = q.filter(
                    AjusClassificacaoQueue.cnj_number.like(f"%{digits}%"),
                )

        total = q.count()
        items = (
            q.order_by(AjusClassificacaoQueue.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return total, items

    def get(self, item_id: int) -> AjusClassificacaoQueue:
        item = self.db.get(AjusClassificacaoQueue, item_id)
        if item is None:
            raise ValueError(f"Item de classificação {item_id} não encontrado.")
        return item

    # ── Mutações por item ───────────────────────────────────────────

    def update(
        self,
        item_id: int,
        *,
        uf: Optional[str] = None,
        comarca: Optional[str] = None,
        matter: Optional[str] = None,
        justice_fee: Optional[str] = None,
        risk_loss_probability: Optional[str] = None,
    ) -> AjusClassificacaoQueue:
        """
        Edita campos do item — só permitido em status pendente ou erro
        (após sucesso ou processando, edição é proibida pra preservar
        rastreabilidade).
        """
        item = self.get(item_id)
        if item.status not in (AJUS_CLASSIF_PENDENTE, AJUS_CLASSIF_ERRO):
            raise RuntimeError(
                f"Edição permitida apenas em pendente ou erro. "
                f"Status atual: {item.status}.",
            )
        if uf is not None:
            item.uf = uf.strip() or None
        if comarca is not None:
            item.comarca = comarca.strip() or None
        if matter is not None:
            item.matter = matter.strip() or None
        if justice_fee is not None:
            item.justice_fee = justice_fee.strip() or None
        if risk_loss_probability is not None:
            item.risk_loss_probability = risk_loss_probability.strip() or None
        self.db.commit()
        self.db.refresh(item)
        return item

    def cancel(self, item_id: int) -> AjusClassificacaoQueue:
        item = self.get(item_id)
        if item.status not in (AJUS_CLASSIF_PENDENTE, AJUS_CLASSIF_ERRO):
            raise RuntimeError(
                f"Cancelamento permitido apenas em pendente ou erro. "
                f"Status atual: {item.status}.",
            )
        item.status = AJUS_CLASSIF_CANCELADO
        self.db.commit()
        self.db.refresh(item)
        return item

    def retry(self, item_id: int) -> AjusClassificacaoQueue:
        item = self.get(item_id)
        if item.status != AJUS_CLASSIF_ERRO:
            raise RuntimeError(
                f"Retry permitido apenas em status 'erro'. "
                f"Atual: {item.status}.",
            )
        item.status = AJUS_CLASSIF_PENDENTE
        item.error_message = None
        self.db.commit()
        self.db.refresh(item)
        return item

    def retry_errors_bulk(
        self, *, item_ids: Optional[list[int]] = None,
    ) -> dict[str, Any]:
        """
        Reenfileira em massa todos os itens em status `erro`. Se
        `item_ids` for fornecido, restringe ao conjunto (intersect
        com status=erro). Sem `item_ids`, processa todos.

        Retorna dict com `retried` (count) e `ids` (lista dos ids
        reenfileirados). Itens em outros status sao ignorados.
        """
        q = (
            self.db.query(AjusClassificacaoQueue)
            .filter(AjusClassificacaoQueue.status == AJUS_CLASSIF_ERRO)
        )
        if item_ids:
            q = q.filter(AjusClassificacaoQueue.id.in_(item_ids))
        items = q.all()

        ids: list[int] = []
        for item in items:
            item.status = AJUS_CLASSIF_PENDENTE
            item.error_message = None
            ids.append(item.id)

        if ids:
            self.db.commit()
        return {"retried": len(ids), "ids": ids}

    # ── Hooks pro runner Playwright (Chunk 2) ───────────────────────
    # Esses métodos vão ser usados pelo runner; deixamos prontos pra
    # não ter que mexer no service depois.

    def mark_processing(self, item_id: int) -> AjusClassificacaoQueue:
        item = self.get(item_id)
        if item.status != AJUS_CLASSIF_PENDENTE:
            raise RuntimeError(
                f"Só itens pendentes podem ser marcados como processando. "
                f"Atual: {item.status}.",
            )
        item.status = AJUS_CLASSIF_PROCESSANDO
        item.executed_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(item)
        return item

    def mark_success(
        self, item_id: int, *, last_log: Optional[str] = None,
    ) -> AjusClassificacaoQueue:
        item = self.get(item_id)
        item.status = AJUS_CLASSIF_SUCESSO
        item.error_message = None
        if last_log is not None:
            item.last_log = last_log
        self.db.commit()
        self.db.refresh(item)
        return item

    def mark_error(
        self,
        item_id: int,
        *,
        error_message: str,
        last_log: Optional[str] = None,
    ) -> AjusClassificacaoQueue:
        item = self.get(item_id)
        item.status = AJUS_CLASSIF_ERRO
        item.error_message = error_message[:4000]
        if last_log is not None:
            item.last_log = last_log
        self.db.commit()
        self.db.refresh(item)
        return item
