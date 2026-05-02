"""
Template de tarefa do fluxo "Agendar Prazos Iniciais".

Espelha `task_templates` em estrutura, mas separado em tabela própria pra
manter os dois fluxos (publicações vs prazos iniciais) independentes. Muda
a chave de casamento: em vez de (category, subcategory, office), casa por
(tipo_prazo, subtipo, natureza_aplicavel, office_external_id).

Regras de casamento (implementadas em `template_matching_service`):

- `tipo_prazo` casa exato com o valor emitido pela IA (CONTESTAR, LIMINAR,
  MANIFESTACAO_AVULSA, AUDIENCIA, JULGAMENTO, SEM_DETERMINACAO,
  CONTRARRAZOES).
- `subtipo` é opcional. Nos tipos AUDIENCIA e JULGAMENTO, usa os enums do
  schema (conciliacao/instrucao/una/outra | merito/extincao_sem_merito/outro).
  Para os demais, subtipo = NULL no template e no schema.
- `natureza_aplicavel`: NULL casa em qualquer natureza; valor casa só com
  intakes dessa natureza. Genérico e específico coexistem (NÃO há override).
- `office_external_id`: template específico (office != NULL) SOBREPÕE o
  template global (office = NULL) no MESMO (tipo_prazo, subtipo,
  natureza_aplicavel). Em outras palavras: se para (CONTESTAR, NULL, NULL,
  office=42) existe template ativo, o template (CONTESTAR, NULL, NULL,
  NULL) é ignorado para intakes desse escritório.
- **Múltiplos templates ativos dentro da MESMA combinação geram múltiplas
  sugestões** (ex: contestar → abrir prazo + pedir cópia ao correspondente).
  Por isso a tabela NÃO tem UniqueConstraint na chave de casamento — exato
  mesmo padrão de `task_templates` (publicações).

Fluxo completo de materialização:

  intake classificado
      └── para cada bloco com aplica=True:
              └── match_templates(tipo_prazo, subtipo, office)
                      ├── casou N templates → N sugestões com mapeamento L1 preenchido
                      └── casou zero → 1 sugestão com task_*_id NULL e
                                        intake vai para AGUARDANDO_CONFIG_TEMPLATE
"""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.session import Base


class PrazoInicialTaskTemplate(Base):
    __tablename__ = "prazo_inicial_task_templates"
    # Sem UniqueConstraint na chave de casamento: múltiplos templates por
    # (tipo_prazo, subtipo, natureza_aplicavel, office) são permitidos
    # (ver docstring do módulo). A CheckConstraint abaixo limita o range do
    # offset em dias úteis pra cair cedo em erros de entrada (ex: typo
    # "300" quando o usuário quis "-3").
    __table_args__ = (
        CheckConstraint(
            "due_business_days >= -365 AND due_business_days <= 30",
            name="ck_pin_task_templates_due_business_days_range",
        ),
        # Template "no-op" (skip_task_creation=TRUE) finaliza o caso sem
        # criar tarefa no L1 — task_subtype_external_id e
        # responsible_user_external_id ficam NULL. Template normal exige
        # ambos preenchidos. Migration: pin014.
        CheckConstraint(
            "(skip_task_creation = TRUE) OR ("
            "task_subtype_external_id IS NOT NULL AND "
            "responsible_user_external_id IS NOT NULL)",
            name="ck_pin_task_templates_skip_or_task_fields",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)

    # ── Chave de casamento ────────────────────────────────────────────
    tipo_prazo = Column(String(64), nullable=False, index=True)
    # NULL = template cobre todos os subtipos daquele tipo_prazo (regra
    # típica para CONTESTAR/LIMINAR/MANIFESTACAO_AVULSA/SEM_DETERMINACAO/
    # CONTRARRAZOES).
    subtipo = Column(String(128), nullable=True, index=True)
    # NULL = template casa em qualquer natureza. NOT NULL = só casa em
    # intakes dessa natureza exata. Diferente de office, NÃO há regra de
    # override entre genérico e específico — ambos casam se compatíveis
    # (operador filtra na HITL ou desativa o genérico).
    natureza_aplicavel = Column(String(64), nullable=True, index=True)
    # NULL = template global. NOT NULL = template específico de escritório.
    office_external_id = Column(
        Integer,
        ForeignKey("legal_one_offices.external_id"),
        nullable=True,
        index=True,
    )

    # Template "no-op": casa normal mas NAO cria tarefa no L1. Usado
    # quando o operador quer que a IA classifique e finalize sem
    # providencia automaticamente (ex.: SEM_PRAZO_EM_ABERTO recorrente).
    # Quando TRUE, task_subtype_external_id e responsible_user_external_id
    # devem ser NULL (CheckConstraint acima). Migration: pin014.
    skip_task_creation = Column(
        Boolean, default=False, nullable=False, server_default="false",
    )

    # ── Configuração da tarefa gerada no Legal One ────────────────────
    # Nullable apenas pra suportar templates no-op (skip_task_creation=TRUE).
    # Normal: ambos preenchidos. Garantia via CheckConstraint.
    task_subtype_external_id = Column(
        Integer,
        ForeignKey("legal_one_task_subtypes.external_id"),
        nullable=True,
        index=True,
    )
    responsible_user_external_id = Column(
        Integer,
        ForeignKey("legal_one_users.external_id"),
        nullable=True,
        index=True,
    )

    priority = Column(String, nullable=False, default="Normal")  # Low|Normal|High
    # Offset em dias úteis somado à data de referência para o agendamento
    # no L1. Convenção de sinal (igual a `task_templates`/publicações, onde a
    # soma é `base + timedelta(days=due_business_days)`):
    #   - negativo = antes da referência (D-N). Caso TÍPICO em prazos
    #     iniciais: o alerta interno tem que cair antes do fatal
    #     (ex: fatal 12/05, offset=-2 → tarefa em 10/05).
    #   - 0        = no dia da referência.
    #   - positivo = depois (útil para reuniões pós-audiência/julgamento).
    # Range permitido: -365..+30 (ver CheckConstraint).
    # Pode ser sobrescrito pelo classifier quando o prazo da IA é preciso
    # (ex: 15 dias úteis pra contestar) — ver Fase 3b no
    # template_matching_service.
    due_business_days = Column(Integer, nullable=False, default=-3)
    due_date_reference = Column(
        String,
        nullable=False,
        default="data_base",
        doc=(
            'Referência para cálculo do prazo da tarefa no L1: '
            '"data_base" (usa data_base da sugestão), '
            '"data_final_calculada" (usa a data já calculada), '
            '"today" (data atual), '
            '"audiencia_data" (para templates de AUDIENCIA).'
        ),
    )

    # Placeholders suportados: {cnj}, {tipo_prazo}, {subtipo}, {data_base},
    # {data_final}, {prazo_dias}, {prazo_tipo}, {objeto}, {assunto},
    # {audiencia_data}, {audiencia_hora}, {audiencia_tipo}, {audiencia_link},
    # {audiencia_endereco}, {julgamento_tipo}, {julgamento_data}.
    description_template = Column(Text, nullable=True)
    notes_template = Column(Text, nullable=True)

    is_active = Column(Boolean, default=True, nullable=False, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    # ── Relationships ─────────────────────────────────────────────────
    office = relationship(
        "LegalOneOffice",
        primaryjoin="PrazoInicialTaskTemplate.office_external_id == LegalOneOffice.external_id",
        foreign_keys=[office_external_id],
    )
    task_subtype = relationship(
        "LegalOneTaskSubType",
        primaryjoin="PrazoInicialTaskTemplate.task_subtype_external_id == LegalOneTaskSubType.external_id",
        foreign_keys=[task_subtype_external_id],
    )
    responsible_user = relationship(
        "LegalOneUser",
        primaryjoin="PrazoInicialTaskTemplate.responsible_user_external_id == LegalOneUser.external_id",
        foreign_keys=[responsible_user_external_id],
    )
