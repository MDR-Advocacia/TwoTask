"""
Template de tarefa do fluxo "Agendar Prazos Iniciais".

Espelha `task_templates` em estrutura, mas separado em tabela própria pra
manter os dois fluxos (publicações vs prazos iniciais) independentes. Muda
a chave de casamento: em vez de (category, subcategory, office), casa por
(tipo_prazo, subtipo, office_external_id).

Regras de casamento (implementadas em `template_matching_service`):

- `tipo_prazo` casa exato com o valor emitido pela IA (CONTESTAR, LIMINAR,
  MANIFESTACAO_AVULSA, AUDIENCIA, JULGAMENTO, SEM_DETERMINACAO).
- `subtipo` é opcional. Nos tipos AUDIENCIA e JULGAMENTO, usa os enums do
  schema (conciliacao/instrucao/una/outra | merito/extincao_sem_merito/outro).
  Para os demais, subtipo = NULL no template e no schema.
- `office_external_id`: template específico (office != NULL) SOBREPÕE o
  template global (office = NULL) no MESMO (tipo_prazo, subtipo). Em outras
  palavras: se para (CONTESTAR, NULL, office=42) existe template ativo, o
  template (CONTESTAR, NULL, NULL) é ignorado para intakes desse escritório.
- Múltiplos templates ativos dentro da MESMA combinação geram múltiplas
  sugestões (ex: contestar → abrir prazo + pedir cópia ao correspondente).

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
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.session import Base


class PrazoInicialTaskTemplate(Base):
    __tablename__ = "prazo_inicial_task_templates"
    __table_args__ = (
        UniqueConstraint(
            "tipo_prazo",
            "subtipo",
            "office_external_id",
            name="uq_pin_task_templates_tipo_subtipo_office",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)

    # ── Chave de casamento ────────────────────────────────────────────
    tipo_prazo = Column(String(64), nullable=False, index=True)
    # NULL = template cobre todos os subtipos daquele tipo_prazo (regra
    # típica para CONTESTAR/LIMINAR/MANIFESTACAO_AVULSA/SEM_DETERMINACAO).
    subtipo = Column(String(128), nullable=True, index=True)
    # NULL = template global. NOT NULL = template específico de escritório.
    office_external_id = Column(
        Integer,
        ForeignKey("legal_one_offices.external_id"),
        nullable=True,
        index=True,
    )

    # ── Configuração da tarefa gerada no Legal One ────────────────────
    task_subtype_external_id = Column(
        Integer,
        ForeignKey("legal_one_task_subtypes.external_id"),
        nullable=False,
        index=True,
    )
    responsible_user_external_id = Column(
        Integer,
        ForeignKey("legal_one_users.external_id"),
        nullable=False,
        index=True,
    )

    priority = Column(String, nullable=False, default="Normal")  # Low|Normal|High
    # Dias úteis somados à data-base para o agendamento no L1.
    # Quando o prazo vem da IA (ex: 15 dias úteis para contestar), esse
    # número pode ser sobrescrito pelo classifier — ver description da
    # Fase 3b no template_matching_service.
    due_business_days = Column(Integer, nullable=False, default=3)
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
