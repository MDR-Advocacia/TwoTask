"""Relatório Crítico de Performance do módulo de Publicações.

Compila — para um período escolhido pelo supervisor (mínimo 5 dias) — as
métricas de capacity da equipe de tratamento de publicações: funil de
auto-descarte, custo real por decisão (cronometrado via intervalo entre
tratamentos), produção por operador, pools por escritório e capacidade
ociosa. Gera um diagnóstico crítico (Sonnet, com fallback determinístico)
e renderiza um PDF executivo server-side reusando o Chromium do Playwright
que já vive na imagem da API.

Admin-only. Ver app/api/v1/endpoints/publications_performance.py.
"""

from app.services.publications_report.metrics import compute_metrics
from app.services.publications_report.narrative import build_narrative
from app.services.publications_report.html_report import render_html
from app.services.publications_report.pdf import html_to_pdf

__all__ = ["compute_metrics", "build_narrative", "render_html", "html_to_pdf"]
