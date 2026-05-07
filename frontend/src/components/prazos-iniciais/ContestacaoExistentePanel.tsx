import {
  AlertTriangle,
  CheckCircle2,
  FileText,
  ShieldCheck,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import type { PrazoInicialContestacaoExistente } from "@/types/api";


function formatDate(d: string | null | undefined): string {
  if (!d) return "—";
  try {
    return new Date(`${d}T00:00:00`).toLocaleDateString("pt-BR");
  } catch {
    return d;
  }
}


interface Props {
  contestacao: PrazoInicialContestacaoExistente;
}


/**
 * Painel READ-ONLY que mostra a detecção de "contestação já apresentada"
 * pin021 — análise paralela da IA disparada quando a íntegra do intake
 * já contém uma petição de contestação. Não interfere em sugestões de
 * prazo nem em patrocínio — só metadado pro HITL decidir se complementa,
 * refaz, ou confirma sem providência.
 *
 * Estado vazio: quando `existe=false`, o componente NÃO renderiza nada
 * (a página pai checa antes de montar). UI fica limpa nos casos sem
 * contestação preexistente, que é a maioria.
 *
 * Sinais que o operador captura num olhar:
 * - Quem assinou (MDR Marcos Délli vs. outro escritório).
 * - Pra qual réu defendeu (em multi-réus, contestação do Banco Will
 *   não é contestação do Master).
 * - Se é genérica (boilerplate) ou customizada (tem trabalho aproveitável).
 *
 * Sem botões de ação — a decisão acontece nas sugestões/patrocínio. Aqui
 * é só consulta.
 */
export function ContestacaoExistentePanel({ contestacao }: Props) {
  if (!contestacao.existe) return null;

  // Cor de borda + chip da assinatura.
  // - MDR + custom        → verde (caso ideal, pode confirmar)
  // - MDR + genérica      → âmbar (precisa complementar)
  // - Outro + qualquer    → laranja (sinal forte de devolução)
  // - MDR null (truncado) → cinza (operador valida no PDF)
  const isMdr = contestacao.apresentada_por_mdr === true;
  const isOutro = contestacao.apresentada_por_mdr === false;
  const isGenerica = contestacao.generica === true;

  let borderClass = "border-muted";
  let chipClass = "bg-slate-50 text-slate-800 border-slate-300";
  let chipLabel = "Origem indeterminada";
  let chipIcon = <FileText className="h-3 w-3" />;
  if (isMdr && !isGenerica && contestacao.generica !== null) {
    borderClass = "border-emerald-300";
    chipClass = "bg-emerald-50 text-emerald-800 border-emerald-300";
    chipLabel = "MDR — customizada";
    chipIcon = <ShieldCheck className="h-3 w-3" />;
  } else if (isMdr && isGenerica) {
    borderClass = "border-amber-300";
    chipClass = "bg-amber-50 text-amber-900 border-amber-300";
    chipLabel = "MDR — genérica";
    chipIcon = <AlertTriangle className="h-3 w-3" />;
  } else if (isMdr) {
    borderClass = "border-emerald-200";
    chipClass = "bg-emerald-50 text-emerald-800 border-emerald-300";
    chipLabel = "MDR — qualidade indet.";
    chipIcon = <ShieldCheck className="h-3 w-3" />;
  } else if (isOutro) {
    borderClass = "border-orange-300";
    chipClass = "bg-orange-50 text-orange-900 border-orange-300";
    chipLabel = "Outro escritório";
    chipIcon = <AlertTriangle className="h-3 w-3" />;
  }

  return (
    <div className={`space-y-3 rounded-lg border-2 bg-card p-4 ${borderClass}`}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <FileText className="h-4 w-4 text-muted-foreground" />
            <h3 className="text-base font-semibold">Contestação já apresentada</h3>
            <Badge variant="outline" className={`text-xs ${chipClass}`}>
              <span className="mr-1 inline-flex items-center">{chipIcon}</span>
              {chipLabel}
            </Badge>
            {isGenerica ? (
              <Badge
                variant="outline"
                className="bg-amber-50 text-amber-900 border-amber-300 text-xs"
              >
                Genérica
              </Badge>
            ) : contestacao.generica === false ? (
              <Badge
                variant="outline"
                className="bg-emerald-50 text-emerald-800 border-emerald-300 text-xs"
              >
                <CheckCircle2 className="mr-1 h-3 w-3" />
                Customizada
              </Badge>
            ) : null}
          </div>
          <p className="text-xs text-muted-foreground">
            A IA detectou contestação na íntegra. Use pra decidir se
            complementa, refaz ou confirma sem providência.
          </p>
        </div>
      </div>

      <Separator />

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <div>
          <div className="text-xs uppercase tracking-wide text-muted-foreground">
            Assinada por
          </div>
          <div className="mt-1 text-sm">
            {contestacao.apresentada_por_nome || "—"}
            {contestacao.apresentada_por_oab
              ? ` · ${contestacao.apresentada_por_oab}`
              : ""}
          </div>
        </div>
        <div>
          <div className="text-xs uppercase tracking-wide text-muted-foreground">
            Data de apresentação
          </div>
          <div className="mt-1 text-sm">
            {formatDate(contestacao.data_apresentacao)}
          </div>
        </div>
        <div className="md:col-span-2">
          <div className="text-xs uppercase tracking-wide text-muted-foreground">
            Defendendo
          </div>
          <div className="mt-1 text-sm">
            {contestacao.parte_representada || "—"}
            {isOutro ? (
              <span className="ml-2 text-xs text-orange-700">
                (não é o Marcos Délli — verifique se essa contestação é
                de outro escritório / outro réu)
              </span>
            ) : null}
          </div>
        </div>
      </div>

      {contestacao.analise_qualidade ? (
        <div>
          <div className="text-xs uppercase tracking-wide text-muted-foreground">
            Análise de qualidade
          </div>
          <p className="mt-1 whitespace-pre-wrap text-sm text-muted-foreground">
            {contestacao.analise_qualidade}
          </p>
        </div>
      ) : null}
    </div>
  );
}

export default ContestacaoExistentePanel;
