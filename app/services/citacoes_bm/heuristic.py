"""Heurística de detecção de candidatos a CITAÇÃO em movimentos do DataJud.

IMPORTANTE: isto só DESTACA candidatos pra agilizar a triagem. Quem decide
se houve citação é o operador (o status_citacao nunca é setado por aqui).

Empiricamente (carteira Banco Master), o sinal de citação raramente está
no `nome` do movimento — costuma estar no `complementosTabelados`, no
campo `tipo_de_documento` (ex.: código 12265 "Expedida/certificada" cujo
complemento diz "Citação" / "Mandado"). Por isso varremos nome + nome e
descrição de cada complemento.

Os termos são propositalmente abrangentes (operador filtra os falsos):
- "cita"     -> citação, citado, citatório, citar
- "mandado"  -> mandado de citação (e afins)
- "edital"   -> edital de citação
"""

import unicodedata
from typing import Any

# Termos que disparam o destaque (já sem acento, minúsculos).
TERMOS_CITACAO = ("cita", "mandado", "edital")


def _normalizar(texto: Any) -> str:
    if texto is None:
        return ""
    s = str(texto)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower()


def _textos_do_movimento(nome: str | None, complementos: Any) -> list[str]:
    textos: list[str] = []
    if nome:
        textos.append(nome)
    if isinstance(complementos, list):
        for comp in complementos:
            if isinstance(comp, dict):
                for campo in ("nome", "descricao", "valor"):
                    valor = comp.get(campo)
                    if valor not in (None, ""):
                        textos.append(str(valor))
    elif isinstance(complementos, dict):
        for campo in ("nome", "descricao", "valor"):
            valor = complementos.get(campo)
            if valor not in (None, ""):
                textos.append(str(valor))
    return textos


def avaliar_candidato(
    nome: str | None, complementos: Any
) -> tuple[bool, str | None]:
    """Retorna (eh_candidato, termo_que_bateu).

    Procura os termos de citação no nome do movimento e em todos os
    complementos tabelados. Devolve o primeiro termo encontrado pra dar
    transparência ao operador (cit_match_termo).
    """
    for texto in _textos_do_movimento(nome, complementos):
        normalizado = _normalizar(texto)
        for termo in TERMOS_CITACAO:
            if termo in normalizado:
                return True, termo
    return False, None
