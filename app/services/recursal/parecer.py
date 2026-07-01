"""
Renderização DETERMINÍSTICA do parecer recursal.

A IA extrai os campos; aqui montamos o `assunto` e o `parecer_texto`
seguindo o template fixo da casa. O custo é injetado já calculado
(determinístico) — a IA não escreve o número.
"""

from __future__ import annotations

from datetime import date
from typing import Optional


_TIPO_DECISAO_TXT = {
    "SENTENCA": "sentença",
    "ACORDAO": "acórdão",
    "DECISAO_INTERLOCUTORIA": "decisão interlocutória",
}
_RESULTADO_TXT = {
    "PROCEDENTE": "procedente",
    "PARCIAL": "parcialmente procedente",
    "IMPROCEDENTE": "improcedente",
    "EXTINTO": "extinto sem resolução de mérito",
}
_CHANCES_TXT = {"PROVAVEL": "altas", "POSSIVEL": "médias", "REMOTA": "baixas"}
# recorrer → (frase da conclusão, objeto da autorização)
_RECOMENDACAO = {
    "NAO": ("não recomendamos a interposição de recurso", "dispensa recursal"),
    "SIM": ("recomendamos a interposição de recurso", "interposição do recurso"),
    "LIMITROFE": (
        "a interposição de recurso é medida limítrofe, ficando a decisão a "
        "critério da contratante",
        "dispensa ou interposição do recurso",
    ),
}


def _fmt_brl(v: Optional[float]) -> str:
    if v is None:
        return "a estimar (tabela de custas do estado ainda não cadastrada)"
    inteiro, dec = f"{float(v):.2f}".split(".")
    # separador de milhar com ponto
    inteiro = f"{int(inteiro):,}".replace(",", ".")
    return f"R$ {inteiro},{dec}"


def _fmt_data(d: Optional[date]) -> str:
    if d is None:
        return "[A CONFIRMAR]"
    return d.strftime("%d/%m/%Y")


def _dash(v: Optional[str]) -> str:
    return v if (v and str(v).strip()) else "—"


def render_assunto(an) -> str:
    """Linha de assunto do e-mail."""
    tribunal = an.tribunal or an.uf or "—"
    return (
        f"({_dash(an.produto)}) – {_dash(an.objeto)} – {_dash(an.nome_autor)} "
        f"({_dash(an.cpf)}) – Proc. {an.processo_numero} – {tribunal}"
    )


def render_parecer(an, custo_estimado: Optional[float]) -> str:
    """Monta o corpo do parecer no template fixo."""
    tipo_dec = _TIPO_DECISAO_TXT.get(an.tipo_decisao or "", "decisão")
    resultado = _RESULTADO_TXT.get(an.resultado_decisao or "", "—")
    chances = _CHANCES_TXT.get(an.probabilidade_reversao or "", "baixas")
    recomendacao, autorizacao = _RECOMENDACAO.get(
        an.recorrer or "NAO", _RECOMENDACAO["NAO"]
    )

    topicos = an.resumo_topicos or []
    analises = an.pontos_analise or []
    fund_juiz = (an.fundamentacao_juiz or "").strip()
    fund_concl = (an.fundamentacao or "").strip()
    valor_cond = (an.valor_condenacao or "").strip() or (
        "Ilíquido (a ser apurado em liquidação de sentença)"
    )

    linhas: list[str] = []
    linhas.append("Prezados, bom dia.")
    linhas.append("📌 Parecer recursal")
    linhas.append(f"Processo: {an.processo_numero}")
    linhas.append(f"Autor: {_dash(an.nome_autor)}")
    linhas.append(f"CPF: {_dash(an.cpf)}")
    linhas.append(f"Produto: {_dash(an.produto)}")
    linhas.append("")

    linhas.append("📄 Resumo da decisão")
    linhas.append(f"Trata-se de {tipo_dec} que julgou o pedido {resultado}, para:")
    for t in topicos:
        linhas.append(f"• {t}")
    if an.destaque and an.destaque.strip():
        linhas.append(f"Registra-se que {an.destaque.strip()}.")
    linhas.append("")

    linhas.append("⚖️ Análise de viabilidade recursal")
    if fund_juiz:
        if fund_juiz[-1] not in ".!?;":
            fund_juiz = fund_juiz + "."
        linhas.append(f"A decisão fundamenta-se, em síntese, {fund_juiz}")
    else:
        linhas.append("A decisão fundamenta-se na análise do conjunto probatório dos autos.")
    if analises:
        linhas.append("No caso concreto, observa-se que:")
        for p in analises:
            linhas.append(f"• {p}")
    linhas.append(
        f"Diante disso, avaliamos que as chances de êxito recursal são {chances}."
    )
    linhas.append("")

    linhas.append("💰 Custos envolvidos")
    linhas.append(f"• Custas recursais (estimadas): {_fmt_brl(custo_estimado)}")
    linhas.append(f"• Valor da condenação: {valor_cond}")
    linhas.append("")

    linhas.append("✅ Conclusão")
    considerando = f", considerando {fund_concl.rstrip('.')}" if fund_concl else ""
    linhas.append(f"Diante do exposto, {recomendacao}{considerando}.")
    linhas.append(
        f"Solicitamos, assim, a gentileza de confirmar a autorização para "
        f"{autorizacao}, tendo em vista o prazo fatal em {_fmt_data(an.prazo_fatal)}."
    )
    linhas.append("")
    linhas.append("Permanecemos à disposição para quaisquer esclarecimentos.")
    linhas.append("Atenciosamente,")

    return "\n".join(linhas)
