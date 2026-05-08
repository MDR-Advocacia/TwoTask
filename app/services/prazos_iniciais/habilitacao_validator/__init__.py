"""
Validador heuristico do PDF de habilitacao MDR.

A habilitacao do escritorio segue sempre o mesmo modelo (peticao
+ procuracao + ato BC + substabelecimento + carta de preposicao
opcional, assinada por Marcos Delli OAB/RN 5.553), o que permite
checagem por matching de strings sem precisar de IA.

Uso tipico (apos salvar habilitacao_pdf_path):

    outcome = run_validation(intake)
    persist_outcome(intake, outcome)
    db.commit()

`run_validation` NUNCA levanta — falhas de IO/extracao viram status
`ERRO_EXTRACAO`. Status `FALHA` nao bloqueia o avanco do intake;
apenas sinaliza pro operador no painel da habilitacao.
"""

from app.services.prazos_iniciais.habilitacao_validator.validator import (
    HabilitacaoCheckOutcome,
    persist_outcome,
    run_validation,
)

__all__ = ["HabilitacaoCheckOutcome", "run_validation", "persist_outcome"]
