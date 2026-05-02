/**
 * Mapas de display name pra valores em UPPER_SNAKE_CASE usados no
 * dominio de prazos iniciais (tipo_prazo, natureza_processo, produto).
 *
 * Espelha (ou amplia) os mapas equivalentes no backend
 * (`app/services/classifier/prazos_iniciais_schema.py:TIPO_PRAZO_LABELS`).
 * Mantenha em sincronia quando adicionar novos valores.
 *
 * Use as funcoes `tipoPrazoLabel`, `naturezaLabel`, `produtoLabel` em
 * vez de acessar os Records direto — elas tem fallback `humanize()`
 * generico, garantindo que valor desconhecido nao quebre a UI (vai
 * aparecer "feio" mas legivel).
 */

export const TIPO_PRAZO_LABEL: Record<string, string> = {
  CONTESTAR: "Contestação",
  LIMINAR: "Cumprimento de liminar",
  MANIFESTACAO_AVULSA: "Manifestação avulsa",
  AUDIENCIA: "Audiência",
  JULGAMENTO: "Julgamento",
  // Legado pre-pin011: split em SEM_PRAZO_EM_ABERTO + INDETERMINADO.
  // Mantido pra exibir intakes antigos sem ficar feio.
  SEM_DETERMINACAO: "Sem determinação (legado)",
  SEM_PRAZO_EM_ABERTO: "Sem prazo em aberto",
  INDETERMINADO: "Indeterminado",
  CONTRARRAZOES: "Contrarrazões",
};

export const NATUREZA_LABEL: Record<string, string> = {
  COMUM: "Comum",
  JUIZADO: "Juizado",
  AGRAVO_INSTRUMENTO: "Agravo de instrumento",
  OUTRO: "Outro",
};

export const PRODUTO_LABEL: Record<string, string> = {
  SUPERENDIVIDAMENTO: "Superendividamento",
  CREDCESTA: "CredCesta",
  CARTAO_CREDITO_CONSIGNADO: "Cartão crédito consignado",
  EXIBICAO_DOCUMENTOS: "Exibição de documentos",
  EMPRESTIMO_CONSIGNADO: "Empréstimo consignado",
  CARTAO_CREDITO: "Cartão de crédito",
  CONTA_CORRENTE: "Conta corrente",
  EMPRESTIMO_PESSOAL: "Empréstimo pessoal",
  FINANCIAMENTO: "Financiamento",
  SEGURO: "Seguro",
  OUTRO: "Outro",
};

/**
 * Fallback generico pra qualquer valor UPPER_SNAKE_CASE sem mapeamento
 * explicito. Converte "CARTAO_CREDITO_CONSIGNADO" → "Cartao credito
 * consignado" — sem acentos, mas legivel. Casos importantes ja estao
 * mapeados acima com acentuacao correta.
 */
export function humanize(snakeCase: string | null | undefined): string {
  if (!snakeCase) return "";
  return snakeCase
    .toLowerCase()
    .split("_")
    .map((w, i) => (i === 0 ? w.charAt(0).toUpperCase() + w.slice(1) : w))
    .join(" ");
}

export function tipoPrazoLabel(value: string | null | undefined): string {
  if (!value) return "";
  return TIPO_PRAZO_LABEL[value] ?? humanize(value);
}

export function naturezaLabel(value: string | null | undefined): string {
  if (!value) return "";
  return NATUREZA_LABEL[value] ?? humanize(value);
}

export function produtoLabel(value: string | null | undefined): string {
  if (!value) return "";
  return PRODUTO_LABEL[value] ?? humanize(value);
}
