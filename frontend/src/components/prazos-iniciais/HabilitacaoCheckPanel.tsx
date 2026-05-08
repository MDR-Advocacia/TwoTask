import { useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  HelpCircle,
  Loader2,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  ShieldQuestion,
  XCircle,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { useToast } from "@/hooks/use-toast";
import { recheckPrazoInicialHabilitacao } from "@/services/api";
import type {
  PrazoInicialHabilitacaoCheck,
  PrazoInicialHabilitacaoCheckResult,
} from "@/types/api";

type CheckStatus = "OK" | "ALERTA" | "FALHA" | "PULADO" | string;
type AggregateStatus =
  | "NAO_VERIFICADO"
  | "OK"
  | "ALERTA"
  | "FALHA"
  | "ERRO_EXTRACAO"
  | string;

interface Props {
  intakeId: number;
  // Status agregado (vem do summary OU do detail.habilitacao_check.status).
  // null/undefined sao tratados como NAO_VERIFICADO.
  aggregateStatus: AggregateStatus | null | undefined;
  // Bloco completo. null/undefined quando nunca rodou (intake antigo).
  check: PrazoInicialHabilitacaoCheckResult | null | undefined;
  onUpdated: (next: PrazoInicialHabilitacaoCheckResult) => void;
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleString("pt-BR");
  } catch {
    return value;
  }
}

function aggregateStyles(status: AggregateStatus): {
  Icon: typeof ShieldCheck;
  label: string;
  badgeClass: string;
  hint: string;
} {
  switch (status) {
    case "OK":
      return {
        Icon: ShieldCheck,
        label: "Habilitação OK",
        badgeClass: "bg-green-100 text-green-800 border-green-300",
        hint: "Todos os checks passaram.",
      };
    case "ALERTA":
      return {
        Icon: ShieldAlert,
        label: "Habilitação com avisos",
        badgeClass: "bg-amber-100 text-amber-900 border-amber-300",
        hint: "Pontos de atenção identificados (não críticos).",
      };
    case "FALHA":
      return {
        Icon: ShieldAlert,
        label: "Habilitação com falhas críticas",
        badgeClass: "bg-red-100 text-red-800 border-red-300",
        hint: "Risco operacional — confira os checks marcados em vermelho.",
      };
    case "ERRO_EXTRACAO":
      return {
        Icon: ShieldQuestion,
        label: "Erro ao ler PDF",
        badgeClass: "bg-slate-100 text-slate-700 border-slate-300",
        hint: "Não foi possível extrair texto do PDF (escaneado?).",
      };
    case "NAO_VERIFICADO":
    default:
      return {
        Icon: ShieldQuestion,
        label: "Não verificado",
        badgeClass: "bg-slate-100 text-slate-700 border-slate-300",
        hint: "A validação heurística ainda não rodou neste PDF.",
      };
  }
}

function checkRowIcon(status: CheckStatus): {
  Icon: typeof CheckCircle2;
  className: string;
} {
  switch (status) {
    case "OK":
      return { Icon: CheckCircle2, className: "text-green-600" };
    case "ALERTA":
      return { Icon: AlertTriangle, className: "text-amber-600" };
    case "FALHA":
      return { Icon: XCircle, className: "text-red-600" };
    case "PULADO":
    default:
      return { Icon: HelpCircle, className: "text-slate-400" };
  }
}

function statusLabel(status: CheckStatus): string {
  if (status === "OK") return "OK";
  if (status === "ALERTA") return "Atenção";
  if (status === "FALHA") return "Falha";
  if (status === "PULADO") return "Pulado";
  return status;
}


export function HabilitacaoCheckPanel({
  intakeId,
  aggregateStatus,
  check,
  onUpdated,
}: Props) {
  const { toast } = useToast();
  const [isRunning, setIsRunning] = useState(false);

  const status = (check?.status || aggregateStatus || "NAO_VERIFICADO") as AggregateStatus;
  const styles = aggregateStyles(status);
  const checks = check?.checks || [];

  async function handleRecheck() {
    setIsRunning(true);
    try {
      const result = await recheckPrazoInicialHabilitacao(intakeId);
      onUpdated(result);
      const variant =
        result.status === "FALHA" || result.status === "ERRO_EXTRACAO"
          ? "destructive"
          : "default";
      toast({
        title: `Habilitação revalidada — ${statusLabel(result.status)}`,
        description: aggregateStyles(result.status).hint,
        variant,
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : "Erro desconhecido";
      toast({
        title: "Falha ao revalidar habilitação",
        description: message,
        variant: "destructive",
      });
    } finally {
      setIsRunning(false);
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2">
          <styles.Icon className="h-5 w-5" />
          <div className="text-sm font-semibold">Conferência da habilitação</div>
        </div>
        <Badge variant="outline" className={styles.badgeClass}>
          {styles.label}
        </Badge>
        {check?.checked_at ? (
          <span className="text-xs text-muted-foreground">
            Verificado em {formatDateTime(check.checked_at)}
          </span>
        ) : null}
        <Button
          size="sm"
          variant="outline"
          className="ml-auto"
          onClick={handleRecheck}
          disabled={isRunning}
          title="Roda novamente os checks heurísticos sobre o PDF salvo"
        >
          {isRunning ? (
            <Loader2 className="mr-1 h-4 w-4 animate-spin" />
          ) : (
            <RefreshCw className="mr-1 h-4 w-4" />
          )}
          {check ? "Revalidar" : "Verificar"}
        </Button>
      </div>

      <div className="text-xs text-muted-foreground">{styles.hint}</div>

      {checks.length === 0 ? (
        <div className="rounded-md border border-dashed border-slate-200 bg-slate-50 p-3 text-xs text-muted-foreground">
          Nenhum check executado ainda. Clique em <strong>Verificar</strong> para
          rodar a validação heurística (CNJ, cliente, pedido de publicações
          exclusivas em nome do titular, procuração, substabelecimento, etc.).
        </div>
      ) : (
        <div className="space-y-1">
          <Separator />
          {checks.map((c: PrazoInicialHabilitacaoCheck) => {
            const { Icon, className } = checkRowIcon(c.status);
            const isCritical = c.criticidade === "CRITICO";
            return (
              <div
                key={c.id}
                className="flex items-start gap-3 rounded-md py-2 px-1 hover:bg-slate-50/60"
              >
                <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${className}`} />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-medium">{c.label}</span>
                    {isCritical ? (
                      <Badge
                        variant="outline"
                        className="bg-red-50 text-red-700 border-red-200 text-[10px] uppercase"
                      >
                        Crítico
                      </Badge>
                    ) : (
                      <Badge
                        variant="outline"
                        className="bg-slate-50 text-slate-600 border-slate-200 text-[10px] uppercase"
                      >
                        Aviso
                      </Badge>
                    )}
                    <Badge
                      variant="outline"
                      className={`text-[10px] uppercase ${
                        c.status === "OK"
                          ? "bg-green-50 text-green-700 border-green-200"
                          : c.status === "ALERTA"
                            ? "bg-amber-50 text-amber-800 border-amber-200"
                            : c.status === "FALHA"
                              ? "bg-red-50 text-red-700 border-red-200"
                              : "bg-slate-50 text-slate-600 border-slate-200"
                      }`}
                    >
                      {statusLabel(c.status)}
                    </Badge>
                  </div>
                  {c.detalhe ? (
                    <div className="mt-1 text-xs text-muted-foreground">
                      {c.detalhe}
                    </div>
                  ) : null}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}


/**
 * Badge compacto pra tabela/listagem. Mostra so' o ícone colorido +
 * tooltip com label do status, sem detalhes. Click é responsabilidade
 * do caller (geralmente abre o detalhe).
 */
export function HabilitacaoCheckBadge({
  status,
  hasHabilitacaoPdf,
}: {
  status: AggregateStatus | null | undefined;
  hasHabilitacaoPdf: boolean;
}) {
  if (!hasHabilitacaoPdf) {
    return null;
  }
  const s = (status || "NAO_VERIFICADO") as AggregateStatus;
  const styles = aggregateStyles(s);
  const StatusIcon = styles.Icon;
  return (
    <Badge
      variant="outline"
      className={`gap-1 text-xs ${styles.badgeClass}`}
      title={`${styles.label} — ${styles.hint}`}
    >
      <StatusIcon className="h-3 w-3" />
      {s === "NAO_VERIFICADO"
        ? "Hab.?"
        : s === "OK"
          ? "Hab. OK"
          : s === "ALERTA"
            ? "Hab. ⚠"
            : s === "FALHA"
              ? "Hab. ✗"
              : "Hab. erro"}
    </Badge>
  );
}
