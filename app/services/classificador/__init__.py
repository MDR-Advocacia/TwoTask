"""Module Classificador (diagnostico de carteira).

Modulo paralelo a Prazos Iniciais — recebe carteira inteira (upload xlsx,
import dos intakes de prazos_iniciais ou API JSON), refresca capa via L1
e classifica com prompt proprio.

Servicos:
- xlsx_reader: parser do template do operador (CNJ + colunas opcionais)
- intake_service: criacao de lote + processos + idempotencia

Ver memory project_classificador.md.
"""
