"""
Calculadora de prazos processuais — útil/corrido com feriados nacionais.

Esta calculadora cobre os feriados nacionais brasileiros (Lei 10.607/2002 e
Lei 14.759/2023, que estabeleceu o Dia da Consciência Negra). Feriados
estaduais e municipais NÃO entram aqui — se for necessário cobrir o
recesso forense por tribunal, o cálculo deve ser refinado depois.

Regras aplicadas (CPC):
  - Art. 219: prazos em dias contam apenas dias úteis (a menos que a lei
    estabeleça contagem corrida — ex.: prazo material/multa diária).
  - Art. 224 §3: a contagem inicia no PRIMEIRO DIA ÚTIL seguinte ao
    termo inicial (data-base/intimação). O dia da intimação não conta.
  - Art. 224 §1: se vencimento cair em dia sem expediente forense,
    prorroga pro próximo dia útil. Aplicado tanto para `util` quanto
    `corrido`.

Uso típico:
    >>> data_final = calcular_prazo_final(date(2026, 4, 22), 15, "util")
"""

from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache
from typing import Iterable, Literal, Optional

PrazoTipo = Literal["util", "corrido"]


# ─── Feriados nacionais fixos ────────────────────────────────────────


FIXED_HOLIDAYS: tuple[tuple[int, int, str], ...] = (
    (1, 1, "Confraternização Universal"),
    (4, 21, "Tiradentes"),
    (5, 1, "Dia do Trabalho"),
    (9, 7, "Independência do Brasil"),
    (10, 12, "Nossa Senhora Aparecida"),
    (11, 2, "Finados"),
    (11, 15, "Proclamação da República"),
    (11, 20, "Dia da Consciência Negra"),  # Federal a partir de 2024
    (12, 25, "Natal"),
)


# ─── Feriados móveis (em torno da Páscoa) ────────────────────────────


def _easter_sunday(year: int) -> date:
    """
    Calcula o domingo de Páscoa pelo algoritmo de Butcher/Meeus
    (Calendário Gregoriano). Funciona pra qualquer ano > 1582.
    """
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _movable_holidays(year: int) -> list[date]:
    """
    Retorna feriados/recessos móveis: Carnaval (segunda + terça),
    Sexta-feira da Paixão e Corpus Christi.

    A Lei Federal 9.093/95 e o CNJ tratam segunda e terça de Carnaval
    como recesso forense — alinhado com a prática dos tribunais.
    """
    easter = _easter_sunday(year)
    return [
        easter - timedelta(days=48),  # Segunda de Carnaval
        easter - timedelta(days=47),  # Terça de Carnaval
        easter - timedelta(days=2),   # Sexta-feira da Paixão
        easter + timedelta(days=60),  # Corpus Christi
    ]


@lru_cache(maxsize=64)
def feriados_nacionais(year: int) -> frozenset[date]:
    """
    Conjunto de feriados nacionais (fixos + móveis) de um ano.
    Cacheado pra evitar recalcular Páscoa em cada chamada.
    """
    holidays: set[date] = set()
    for month, day, _ in FIXED_HOLIDAYS:
        try:
            holidays.add(date(year, month, day))
        except ValueError:
            # Não acontece com nossos meses/dias fixos — guard defensivo.
            continue
    holidays.update(_movable_holidays(year))
    return frozenset(holidays)


# ─── Helpers de dia útil ─────────────────────────────────────────────


def is_business_day(d: date, extra_holidays: Optional[Iterable[date]] = None) -> bool:
    """
    True se a data for dia útil: não é sábado, domingo nem feriado nacional.
    `extra_holidays` permite passar feriados extras (ex.: pontos facultativos
    relevantes pra prazo, ou recessos do tribunal).
    """
    if d.weekday() >= 5:  # 5=sáb, 6=dom
        return False
    if d in feriados_nacionais(d.year):
        return False
    if extra_holidays and d in set(extra_holidays):
        return False
    return True


def proximo_dia_util(d: date, extra_holidays: Optional[Iterable[date]] = None) -> date:
    """
    Retorna `d` se for dia útil; senão, avança até o próximo dia útil.
    Iterativo (no pior caso, ~5 saltos: feriado prolongado).
    """
    cur = d
    while not is_business_day(cur, extra_holidays):
        cur += timedelta(days=1)
    return cur


def add_business_days(
    base: date,
    n: int,
    extra_holidays: Optional[Iterable[date]] = None,
) -> date:
    """
    Soma `n` dias úteis a `base`, pulando fim de semana e feriados.

    Ao contrário de `calcular_prazo_final` (que segue o CPC: começa no
    dia útil seguinte ao termo inicial), esta é uma soma genérica de
    "N dias úteis a partir da data X" — útil para vencimentos
    operacionais (ex.: tarefa interna 5 dias úteis após uma publicação).

    Convenção:
      - n > 0: avança N dias úteis a partir de `base`.
      - n < 0: retrocede |N| dias úteis.
      - n == 0: retorna `base` sem ajuste.

    Diferença vs `proximo_dia_util` + soma corrida: aqui contamos
    APENAS dias úteis. Sábado, domingo e feriados nacionais não
    incrementam o contador.

    Args:
        base: data de referência (ex.: data da publicação).
        n: quantidade de dias úteis (positivo ou negativo).
        extra_holidays: feriados extras (recessos de tribunal, etc.).

    Returns:
        date resultante. Se `n == 0`, devolve `base` mesmo se cair em
        fim de semana/feriado (caller decide se quer prorrogar).
    """
    if n == 0:
        return base
    step = 1 if n > 0 else -1
    remaining = abs(n)
    cur = base
    while remaining > 0:
        cur += timedelta(days=step)
        if is_business_day(cur, extra_holidays):
            remaining -= 1
    return cur


# ─── Cálculo principal ───────────────────────────────────────────────


def calcular_prazo_final(
    data_base: date,
    prazo_dias: int,
    prazo_tipo: PrazoTipo,
    *,
    extra_holidays: Optional[Iterable[date]] = None,
) -> date:
    """
    Calcula a data final de um prazo processual.

    Args:
        data_base: termo inicial (data da intimação, ciência, juntada do AR).
                   Não conta na contagem (CPC art. 224).
        prazo_dias: quantidade de dias do prazo (ex.: 15).
        prazo_tipo: "util" (dias úteis, regra CPC) ou "corrido" (dias
                    corridos — usado em juizados, multas diárias, prazos
                    materiais).
        extra_holidays: feriados extras a considerar (recessos por tribunal,
                        pontos facultativos relevantes).

    Returns:
        date final calculada. Se o vencimento cair em dia sem expediente
        forense, prorroga pra o próximo dia útil (CPC art. 224 §1).

    Raises:
        ValueError se prazo_dias < 1 ou prazo_tipo inválido.
    """
    if prazo_dias is None or prazo_dias < 1:
        raise ValueError(f"prazo_dias inválido: {prazo_dias}")
    if prazo_tipo not in ("util", "corrido"):
        raise ValueError(f"prazo_tipo inválido: {prazo_tipo}")

    if prazo_tipo == "corrido":
        vencimento = data_base + timedelta(days=prazo_dias)
        # Art. 224 §1: prorroga se cair em dia sem expediente.
        return proximo_dia_util(vencimento, extra_holidays)

    # Útil: começa no primeiro dia útil seguinte ao termo inicial.
    primeiro_dia_util = proximo_dia_util(data_base + timedelta(days=1), extra_holidays)
    # Já contamos esse primeiro dia útil; faltam (prazo_dias - 1) dias úteis.
    cur = primeiro_dia_util
    restantes = prazo_dias - 1
    while restantes > 0:
        cur += timedelta(days=1)
        if is_business_day(cur, extra_holidays):
            restantes -= 1
    return cur


def calcular_prazo_seguro(
    data_base: Optional[date],
    prazo_dias: Optional[int],
    prazo_tipo: Optional[str],
    *,
    extra_holidays: Optional[Iterable[date]] = None,
) -> Optional[date]:
    """
    Wrapper tolerante a entradas faltantes — útil pra rodar sobre
    sugestões da IA (que podem vir incompletas). Retorna None se
    qualquer parâmetro essencial faltar.
    """
    if not data_base or not prazo_dias or prazo_tipo not in ("util", "corrido"):
        return None
    try:
        return calcular_prazo_final(
            data_base, prazo_dias, prazo_tipo, extra_holidays=extra_holidays
        )
    except (ValueError, TypeError):
        return None
