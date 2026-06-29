// Times (setores/supervisões) do Minha Equipe — espelha app/services/performance/teams.py.
// Cada time é um item de menu + uma permissão (árvore do admin) + o slug da rota.

export const TEAMS = [
  { key: "bb-reu", label: "BB Réu" },
  { key: "bb-execucao", label: "BB Execução & Encerramento" },
  { key: "bb-acordos", label: "BB Acordos" },
  { key: "bb-estrategico", label: "BB Estratégico" },
  { key: "master-reu", label: "Master Réu" },
  { key: "ativos-reu", label: "Ativos Réu" },
  { key: "bb-autor-processual", label: "BB Autor — Processual" },
  { key: "ativos-autor", label: "Ativos Autor" },
  { key: "autor-recursal", label: "Autor — Recursal" },
  { key: "ajuizamento", label: "Ajuizamento" },
  { key: "estrategico-autor", label: "Estratégico Autor" },
] as const;

export const TEAM_KEYS = TEAMS.map((t) => t.key);

export function teamLabel(key: string): string {
  return TEAMS.find((t) => t.key === key)?.label ?? key;
}

export function isValidTeam(key: string | undefined): boolean {
  return !!key && TEAM_KEYS.includes(key as (typeof TEAMS)[number]["key"]);
}
