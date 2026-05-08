/**
 * Classifica error_message do AJUS em categorias acionáveis pro
 * operador, em vez de jogar a mensagem crua na tela.
 *
 * Cada categoria traz:
 *   - kind: identificador estável pra estatística/agrupamento
 *   - label: texto curto pro badge (max ~24 chars)
 *   - hint: ação humana clara ("Cadastrar Foro no processo do AJUS")
 *   - severity:
 *       - 'human_action'  → vermelho, operador precisa fazer algo manual no AJUS
 *       - 'data_input'    → âmbar, dado da planilha está inválido
 *       - 'infra'         → cinza, problema técnico (rede/sessão), retry resolve
 *       - 'unknown'       → cinza, mensagem não casou com nenhum padrão
 *
 * Padrões abaixo foram extraídos de logs reais do runner em 2026-05-07/08.
 * Adicionar novos padrões aqui quando aparecerem em produção.
 */

export type AjusErrorSeverity =
  | "human_action"
  | "data_input"
  | "infra"
  | "unknown";

export interface AjusErrorClassification {
  kind: string;
  label: string;
  hint: string;
  severity: AjusErrorSeverity;
}

/** Lista ordenada — primeira regex que casa vence. Mais específicas primeiro. */
const RULES: Array<{
  test: RegExp;
  out: Omit<AjusErrorClassification, never>;
}> = [
  // ─── Erros que precisam de intervenção humana no AJUS ────────────
  {
    test: /FK_acaojudicial_foro|FOREIGN KEY \(`?codForo`?\)/i,
    out: {
      kind: "foro_invalido_no_ajus",
      label: "Foro inválido",
      hint:
        "O processo no AJUS está com Foro inválido (FK quebrada). " +
        "Operador: abrir o processo no AJUS, selecionar um Foro válido " +
        "e salvar manualmente. Depois reenfileirar este item.",
      severity: "human_action",
    },
  },
  {
    test: /Foro:?\s*Este campo|Foro nao preenchido|Foro:.*preenchimento obrigat/i,
    out: {
      kind: "foro_vazio",
      label: "Foro vazio",
      hint:
        "Processo sem Foro preenchido no AJUS. " +
        "Operador: abrir o processo no AJUS, preencher o Foro e salvar. " +
        "Depois reenfileirar este item.",
      severity: "human_action",
    },
  },
  {
    test: /Nº? Vara|N°? Vara|Nº Vara.*preenchimento obrigat|Vara:.*obrigat/i,
    out: {
      kind: "vara_vazia",
      label: "Nº Vara vazio",
      hint:
        "Processo sem Nº Vara preenchido no AJUS. " +
        "Operador: abrir o processo no AJUS, preencher o número da Vara " +
        "e salvar. Depois reenfileirar este item.",
      severity: "human_action",
    },
  },
  {
    test: /sem Autor cadastrado|Preciso no Mínimo 1 Autor|preciso no minimo 1 autor/i,
    out: {
      kind: "autor_faltando",
      label: "Sem Autor",
      hint:
        "Processo no AJUS sem Autor cadastrado. " +
        "Operador: abrir o processo, ir na aba Partes e cadastrar pelo " +
        "menos 1 Autor. Depois reenfileirar este item.",
      severity: "human_action",
    },
  },
  {
    test: /sem Réu cadastrado|Preciso no Mínimo 1 Réu|preciso no minimo 1 reu/i,
    out: {
      kind: "reu_faltando",
      label: "Sem Réu",
      hint:
        "Processo no AJUS sem Réu cadastrado. " +
        "Operador: abrir o processo, ir na aba Partes e cadastrar pelo " +
        "menos 1 Réu. Depois reenfileirar este item.",
      severity: "human_action",
    },
  },
  {
    test: /campo obrigatorio nao preenchido no processo/i,
    out: {
      kind: "campo_obrigatorio_generico",
      label: "Campo obrigatório vazio",
      hint:
        "Algum campo obrigatório do processo está vazio no AJUS. " +
        "Operador: abrir o processo, identificar o campo com asterisco " +
        "vermelho, preencher e salvar. Depois reenfileirar.",
      severity: "human_action",
    },
  },
  {
    test: /processo nao encontrado|cnj nao encontrado|nao foi possivel localizar a busca rapida.*screenshot/i,
    out: {
      kind: "processo_nao_encontrado",
      label: "Não encontrado no AJUS",
      hint:
        "CNJ não foi encontrado na busca rápida do AJUS. " +
        "Operador: confirmar se o processo está cadastrado no AJUS. Se " +
        "não estiver, cadastrar antes de reenfileirar.",
      severity: "human_action",
    },
  },

  // ─── Erros de dados da planilha (operador corrige no item) ───────
  {
    test: /Matéria desconhecida|Display invalido.*Mat[ée]ria/i,
    out: {
      kind: "materia_invalida",
      label: "Matéria inválida",
      hint:
        "A Matéria informada na planilha não existe no AJUS. " +
        "Opções válidas: Administrativo, Cível, Consumidor, Criminal, " +
        "Não Classif., Trabalhista, Tributário. Edite o item.",
      severity: "data_input",
    },
  },
  {
    test: /Justiça\/Honorário desconhecido|Display invalido.*Justi/i,
    out: {
      kind: "justica_invalida",
      label: "Justiça inválida",
      hint:
        "Justiça/Honorário inválido. Opções válidas: " +
        "'Justiça Comum', 'Juizado Especial Cível', 'Não Definido'. " +
        "Edite o item.",
      severity: "data_input",
    },
  },
  {
    test: /Risco\/Prob\. Perda desconhecido|Display invalido.*Risco/i,
    out: {
      kind: "risco_invalido",
      label: "Risco inválido",
      hint:
        "Risco/Prob. Perda inválido. Opções válidas: " +
        "Possível, Praticamente Certo, Provável, Remoto. Edite o item.",
      severity: "data_input",
    },
  },
  {
    test: /Display invalido pra item|Natureza desconhecida/i,
    out: {
      kind: "display_invalido",
      label: "Valor inválido",
      hint:
        "Algum campo do item tem valor que não casa com o catálogo do " +
        "AJUS. Edite o item conferindo Matéria, Justiça e Risco.",
      severity: "data_input",
    },
  },

  // ─── Infra / sessão / runner (retry costuma resolver) ────────────
  {
    test: /sessão expirou|sessao expirou|Faça login novamente/i,
    out: {
      kind: "sessao_expirada",
      label: "Sessão expirada",
      hint:
        "A sessão da conta AJUS expirou. " +
        "Operador: relogar a conta no painel de Sessões e reenfileirar.",
      severity: "infra",
    },
  },
  {
    test: /workspace dentro do timeout|workspace nao liberou/i,
    out: {
      kind: "workspace_timeout",
      label: "Workspace travou",
      hint:
        "O workspace do AJUS não liberou a tempo (sessão lenta). " +
        "Geralmente resolve sozinho na próxima execução — basta reenfileirar.",
      severity: "infra",
    },
  },
  {
    test: /Save XHR nao saiu|form-cmp-nao-achado|form-target-nao-achado|form-values-vazio/i,
    out: {
      kind: "form_nao_montou",
      label: "Form não montou",
      hint:
        "O form do processo não montou a tempo (timing-issue de página " +
        "lenta). Reenfileirar costuma resolver.",
      severity: "infra",
    },
  },
  {
    test: /xhr-network-error|xhr-timeout|timeout 30000ms|timeout \d+ms/i,
    out: {
      kind: "rede_timeout",
      label: "Rede / timeout",
      hint:
        "Falha de rede ou timeout do AJUS. Reenfileirar — se persistir, " +
        "checar se o portal AJUS está fora do ar.",
      severity: "infra",
    },
  },
  {
    test: /Save XHR rejeitado.*status=200.*success=False/i,
    out: {
      kind: "save_rejeitado_pelo_server",
      label: "Save rejeitado",
      hint:
        "AJUS aceitou a requisição mas devolveu success=false sem " +
        "categoria conhecida. Olhar mensagem completa (tooltip) e abrir " +
        "ticket se persistir.",
      severity: "human_action",
    },
  },
];

/** Classifica uma error_message. Sempre retorna algo (default: unknown). */
export function classifyAjusError(
  errorMessage: string | null | undefined,
): AjusErrorClassification {
  const msg = (errorMessage || "").trim();
  if (!msg) {
    return {
      kind: "vazio",
      label: "Sem detalhe",
      hint: "Item está em erro, mas sem mensagem registrada.",
      severity: "unknown",
    };
  }
  for (const rule of RULES) {
    if (rule.test.test(msg)) return rule.out;
  }
  return {
    kind: "desconhecido",
    label: "Erro desconhecido",
    hint:
      "Mensagem não casou com nenhum padrão conhecido. Veja a mensagem " +
      "completa no tooltip. Se for recorrente, adicionar regra em " +
      "ajusErrorClassifier.ts.",
    severity: "unknown",
  };
}

/** Cor Tailwind por severidade — pra Badge / texto. */
export function severityToBadgeClass(severity: AjusErrorSeverity): string {
  switch (severity) {
    case "human_action":
      return "border-red-300 bg-red-50 text-red-700 dark:bg-red-950 dark:text-red-300";
    case "data_input":
      return "border-amber-300 bg-amber-50 text-amber-700 dark:bg-amber-950 dark:text-amber-300";
    case "infra":
      return "border-slate-300 bg-slate-50 text-slate-700 dark:bg-slate-900 dark:text-slate-300";
    case "unknown":
    default:
      return "border-slate-300 bg-slate-50 text-slate-600 dark:bg-slate-900 dark:text-slate-400";
  }
}
