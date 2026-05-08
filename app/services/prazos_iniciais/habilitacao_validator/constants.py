"""
Constantes do validador de habilitacoes MDR.

Centralizadas pra facilitar atualizacao quando o modelo da habilitacao
mudar (troca de titular, OAB, lista de advogados do escritorio, etc.).
Tudo aqui ja eh comparado contra texto NORMALIZADO (lowercase, sem
acento, whitespace colapsado) — ver habilitacao_validator/text.py.
"""

# ─── Advogado titular (subscritor da peticao + destinatario das publicacoes) ─

# Sem o nome + OAB do titular no pedido (d) "EXCLUSIVAMENTE em nome de...",
# qualquer intimacao publicada em outro nome eh nula (CPC 272 §5º). Por
# isso o check correspondente eh CRITICO.
TITULAR_NOME = "MARCOS DELLI RIBEIRO RODRIGUES"
TITULAR_NOME_VARIANTS = (
    "MARCOS DELLI RIBEIRO RODRIGUES",
    "MARCOS DÉLLI RIBEIRO RODRIGUES",
)
TITULAR_OAB_UF = "RN"
# Variantes de formatacao do numero da OAB encontradas em peticoes
# protocoladas. Match parcial: qualquer uma dessas + "RN" no texto
# satisfaz o check.
TITULAR_OAB_NUM_VARIANTS = ("5.553", "5553")


# ─── Strings ancora pra detectar cada bloco da habilitacao ───────────

ANCHOR_PETICAO_HABILITACAO = (
    "respeitavel juizo",
    "respeitável juízo",
    "respeitavel juízo",
    "respeitável juizo",
)
ANCHOR_PROCURACAO = ("procuracao", "procuração")
ANCHOR_SUBSTABELECIMENTO = ("substabelecimento",)


# ─── Regex CNJ — formato CNJ-padrao (com ou sem mascara) ─────────────

CNJ_REGEX = r"\d{7}[-\s.]*\d{2}[\s.]*\d{4}[\s.]*\d[\s.]*\d{2}[\s.]*\d{4}"


# ─── OABs do escritorio MDR no substabelecimento padrao ──────────────

# Lista enxuta pra evitar falso negativo quando alguem entra/sai. Match
# parcial: qualquer uma dessas no texto satisfaz o check (que eh AVISO,
# nao CRITICO). Origem: substabelecimento de habilitacoes 2025-2026.
OABS_ESCRITORIO_MIN = (
    "RN 19.744",  # Bruna Paula da Costa Ribeiro
    "RN 16.016",  # Weuder Martins Camara
    "RN 21.965",  # Arlisson Pereira da Silva
    "RN 4.921",   # Rodrigo Cavalcanti
    "RN 21.469",  # Gabriel Carvalho Rodrigues de Oliveira
    "RN 22.232",  # Arthur Augusto Alves de Almeida
    "RN 22.512",  # Joao Vitor de Araujo Pereira
    "RN 14.114",  # Shirley Saionara Linhares de Oliveira
)


# ─── Definicao dos checks (id, label, criticidade) ───────────────────

# Apenas pra documentacao — o validator nao reusa esse dict. As funcoes
# em checks.py constroem o dict de cada resultado individualmente.
CHECK_DEFS = (
    ("C1", "Peticao de habilitacao encontrada", "CRITICO"),
    ("C2", "Pedido de publicacoes exclusivas em nome do titular", "CRITICO"),
    ("C3", "Assinatura do advogado titular", "CRITICO"),
    ("C4", "Procuracao anexa", "CRITICO"),
    ("C5", "Substabelecimento anexo", "CRITICO"),
    ("C6", "Numero do processo bate com o intake", "CRITICO"),
    ("C7", "Cliente do intake aparece na habilitacao", "CRITICO"),
    ("C8", "OAB do escritorio no substabelecimento", "AVISO"),
    ("C9", "Data de assinatura plausivel", "AVISO"),
)
