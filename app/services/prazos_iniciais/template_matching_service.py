"""
Matching de templates do fluxo "Agendar Prazos Iniciais".

Dada a tripla (tipo_prazo, subtipo, office_external_id) derivada da
classificação da IA, retorna os templates ativos que devem gerar
sugestões de tarefa.

Regras (fechadas com o usuário em 2026-04-20):

1. `is_active=True` sempre é exigido.
2. `tipo_prazo` casa por valor exato.
3. `subtipo`:
   - Se o intake tem subtipo (AUDIENCIA/JULGAMENTO): casa **exato** com
     o subtipo do template OU com `subtipo=NULL` (wildcard do template).
   - Se o intake não tem subtipo (demais tipos): casa apenas templates
     com `subtipo=NULL`.
4. `office_external_id` — regra de **sobreposição** (específico vence
   global no MESMO `(tipo_prazo, subtipo_resolvido)`):
   - Se existem templates específicos ativos (office = office_do_intake)
     para aquela combinação, os globais (office=NULL) daquela MESMA
     combinação são descartados.
   - Caso contrário, os globais valem.
   - Combinações `(tipo, subtipo)` diferentes coexistem livremente.

Não faz I/O além do SELECT. Não altera o banco. O `classifier` que
chama é responsável por materializar as sugestões.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Optional

from sqlalchemy.orm import Session

from app.models.prazo_inicial_task_template import PrazoInicialTaskTemplate


def match_templates(
    db: Session,
    *,
    tipo_prazo: str,
    subtipo: Optional[str],
    office_external_id: Optional[int],
) -> list[PrazoInicialTaskTemplate]:
    """
    Retorna os templates ativos que devem gerar sugestões para um bloco
    específico da classificação.

    Args:
        db: sessão do SQLAlchemy.
        tipo_prazo: valor exato do `tipo_prazo` do bloco
            (CONTESTAR / LIMINAR / MANIFESTACAO_AVULSA / AUDIENCIA /
             JULGAMENTO / SEM_DETERMINACAO).
        subtipo: valor do subtipo do bloco, ou None se o tipo não tem
            subtipo categorizado.
        office_external_id: external_id do escritório responsável pelo
            processo no L1. None se o intake não pôde ser associado a um
            escritório — nesse caso, só templates globais valem.

    Returns:
        Lista (possivelmente vazia) de PrazoInicialTaskTemplate. Os
        itens já estão filtrados pela regra de sobreposição
        específico>global.
    """
    q = db.query(PrazoInicialTaskTemplate).filter(
        PrazoInicialTaskTemplate.is_active.is_(True),
        PrazoInicialTaskTemplate.tipo_prazo == tipo_prazo,
    )

    # Casamento de subtipo.
    #   - intake com subtipo X: templates com subtipo=X ou subtipo=NULL.
    #   - intake sem subtipo:   templates com subtipo=NULL.
    if subtipo is not None:
        q = q.filter(
            (PrazoInicialTaskTemplate.subtipo == subtipo)
            | (PrazoInicialTaskTemplate.subtipo.is_(None))
        )
    else:
        q = q.filter(PrazoInicialTaskTemplate.subtipo.is_(None))

    # Casamento de office — específico OU global. O filtro na regra de
    # sobreposição acontece depois, em memória.
    if office_external_id is not None:
        q = q.filter(
            (PrazoInicialTaskTemplate.office_external_id == office_external_id)
            | (PrazoInicialTaskTemplate.office_external_id.is_(None))
        )
    else:
        q = q.filter(PrazoInicialTaskTemplate.office_external_id.is_(None))

    candidates = q.all()
    if not candidates:
        return []

    return _apply_specific_over_global(candidates)


def _apply_specific_over_global(
    templates: list[PrazoInicialTaskTemplate],
) -> list[PrazoInicialTaskTemplate]:
    """
    Implementa a sobreposição específico>global POR combinação
    (tipo_prazo, subtipo_normalizado).

    Dentro de cada combinação:
      - Se houver pelo menos um template com office != NULL, descarta os
        com office == NULL.
      - Senão mantém todos.

    Templates específicos e globais de COMBINAÇÕES diferentes coexistem
    sem interferir um no outro.
    """
    buckets: dict[tuple[str, Optional[str]], list[PrazoInicialTaskTemplate]] = (
        defaultdict(list)
    )
    for t in templates:
        buckets[(t.tipo_prazo, t.subtipo)].append(t)

    kept: list[PrazoInicialTaskTemplate] = []
    for bucket in buckets.values():
        has_specific = any(t.office_external_id is not None for t in bucket)
        if has_specific:
            kept.extend(t for t in bucket if t.office_external_id is not None)
        else:
            kept.extend(bucket)
    # Ordem estável: por id asc, pra testes previsíveis.
    kept.sort(key=lambda t: t.id if t.id is not None else 0)
    return kept
