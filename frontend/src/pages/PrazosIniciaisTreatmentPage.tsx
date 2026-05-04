import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  AlertCircle,
  AlertTriangle,
  Ban,
  Download,
  ExternalLink,
  Eraser,
  Loader2,
  Play,
  RefreshCw,
  RotateCcw,
  Rocket,
  ShieldAlert,
  ShieldCheck,
  Unlock,
  Workflow,
} from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useToast } from "@/hooks/use-toast";
import {
  cancelPrazosIniciaisLegacyTaskCancelItem,
  dispatchPrazoInicialTreatmentWeb,
  downloadPrazosIniciaisLegacyTaskCancelQueueCsv,
  fetchPrazosIniciaisIntakes,
  fetchPrazosIniciaisLegacyTaskCancelQueue,
  fetchPrazosIniciaisLegacyTaskCancelQueueMetrics,
  processPrazosIniciaisLegacyTaskCancelQueue,
  reprocessPrazosIniciaisLegacyTaskCancelItem,
  resetPrazosIniciaisLegacyTaskCancelCircuitBreaker,
} from "@/services/api";
import type {
  PrazoInicialIntakeSummary,
  PrazoInicialLegacyTaskCancelQueueItem,
  PrazoInicialLegacyTaskCancelQueueStatus,
  PrazoInicialLegacyTaskQueueFilters,
  PrazoInicialLegacyTaskQueueMetrics,
} from "@/types/api";

const STATUS_OPTIONS: { value: string; label: string }[] = [
  { value: "__all__", label: "Todos os status" },
  { value: "PENDENTE", label: "Pendentes" },
  { value: "PROCESSANDO", label: "Processando" },
  { value: "CONCLUIDO", label: "Concluídos" },
  { value: "FALHA", label: "Falhas" },
  { value: "CANCELADO", label: "Cancelados" },
];

function formatDateTime(value: string | null | undefined) {
  if (!value) return "-";
  return new Intl.DateTimeFormat("pt-BR", {
    dateStyle: "short",
    timeStyle: "medium",
    timeZone: "America/Fortaleza",
  }).format(new Date(value));
}

function formatCnj(value: string | null | undefined) {
  if (!value) return "-";
  const digits = value.replace(/\D/g, "");
  if (digits.length === 20) {
    return `${digits.slice(0, 7)}-${digits.slice(7, 9)}.${digits.slice(9, 13)}.${digits.slice(13, 14)}.${digits.slice(14, 16)}.${digits.slice(16, 20)}`;
  }
  return value;
}

function queueStatusLabel(status: PrazoInicialLegacyTaskCancelQueueStatus) {
  const labels: Record<string, string> = {
    PENDENTE: "Pendente",
    PROCESSANDO: "Processando",
    CONCLUIDO: "Concluído",
    FALHA: "Falha",
    CANCELADO: "Cancelado",
  };
  return labels[status] || status;
}

function queueStatusClass(status: PrazoInicialLegacyTaskCancelQueueStatus) {
  const styles: Record<string, string> = {
    PENDENTE: "bg-slate-100 text-slate-700",
    PROCESSANDO: "bg-blue-100 text-blue-800",
    CONCLUIDO: "bg-green-100 text-green-800",
    FALHA: "bg-red-100 text-red-800",
    CANCELADO: "bg-slate-200 text-slate-800",
  };
  return styles[status] || "bg-slate-100 text-slate-700";
}

function reasonLabel(reason: string | null | undefined) {
  if (!reason) return "-";
  const labels: Record<string, string> = {
    cancelled: "Cancelada",
    already_cancelled: "Já cancelada",
    already_in_target_status: "Já no status alvo",
    auth_failure: "Falha de autenticação",
    timeout: "Timeout",
    layout_drift: "Tela do L1 mudou",
    verification_failed: "Verificação pós-edição falhou",
    runner_error: "Erro do runner",
    task_not_found: "Task não encontrada",
    lawsuit_not_found: "Processo não encontrado",
    exception: "Exceção Python",
    intake_not_eligible: "Intake fora do estado AGENDADO",
    manually_cancelled: "Cancelado manualmente",
  };
  return labels[reason] || reason;
}

function resolveTaskLink(item: PrazoInicialLegacyTaskCancelQueueItem): string | null {
  const lastResult = item.last_result || {};
  return lastResult.details_url || lastResult.edit_url || null;
}

function isItemReprocessable(item: PrazoInicialLegacyTaskCancelQueueItem) {
  // Permite reprocessar tudo que NAO eh PENDENTE (ja na fila esperando o
  // worker pegar). Inclui CONCLUIDO (caso de sucesso falso onde a task
  // continua pendente no L1) e PROCESSANDO (preso por crash de worker).
  return item.queue_status !== "PENDENTE";
}

function isItemCancellable(item: PrazoInicialLegacyTaskCancelQueueItem) {
  return item.queue_status === "PENDENTE" || item.queue_status === "FALHA";
}

/**
 * Debounce de valor em memória. Usado pros filtros de CNJ/intake que
 * disparam uma chamada ao servidor a cada keystroke — com 400ms de debounce
 * o painel para de refetchar o tempo inteiro enquanto o operador digita.
 */
function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const handle = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(handle);
  }, [value, delayMs]);
  return debounced;
}

/**
 * Formata latência de forma amigável:
 *   - valores <1s viram "850 ms"
 *   - valores ≥1s viram "1.3 s"
 * O backend reporta sempre em ms.
 */
function formatLatencyMs(ms: number | null | undefined): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

export default function PrazosIniciaisTreatmentPage() {
  const { toast } = useToast();
  const [items, setItems] = useState<PrazoInicialLegacyTaskCancelQueueItem[]>([]);
  const [total, setTotal] = useState(0);
  const [statusFilter, setStatusFilter] = useState("__all__");
  const [cnjFilter, setCnjFilter] = useState("");
  const [intakeFilter, setIntakeFilter] = useState("");
  const [sinceFilter, setSinceFilter] = useState(""); // datetime-local
  const [untilFilter, setUntilFilter] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [actionItemId, setActionItemId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [metrics, setMetrics] = useState<PrazoInicialLegacyTaskQueueMetrics | null>(null);
  const [isCsvDownloading, setIsCsvDownloading] = useState(false);
  const [isResettingCircuitBreaker, setIsResettingCircuitBreaker] = useState(false);

  // Intakes pendentes de disparo (dispatch_pending=True). Etapa
  // ANTERIOR a fila de cancel da legada — sao os intakes que ja foram
  // confirmados pelo operador (status AGENDADO ou CONCLUIDO_SEM_PROVIDENCIA)
  // mas ainda nao tiveram o GED upload + enqueue cancel disparado.
  // Permite tratamento 1 por 1 (botao "Disparar" individual em cada
  // linha — util pra fase de testes).
  const [pendingIntakes, setPendingIntakes] = useState<PrazoInicialIntakeSummary[]>([]);
  const [pendingIntakesTotal, setPendingIntakesTotal] = useState(0);
  const [pendingIntakesLoading, setPendingIntakesLoading] = useState(false);
  const [dispatchingIntakeId, setDispatchingIntakeId] = useState<number | null>(null);

  // Debounce dos filtros de texto pra evitar refetch a cada keystroke. Os
  // filtros de Select / datetime-local ficam síncronos porque são cliques
  // pontuais e não sequências de caracteres.
  const debouncedCnjFilter = useDebouncedValue(cnjFilter, 400);
  const debouncedIntakeFilter = useDebouncedValue(intakeFilter, 400);

  const buildFilters = (): PrazoInicialLegacyTaskQueueFilters => {
    const filters: PrazoInicialLegacyTaskQueueFilters = { limit: 500 };
    if (statusFilter !== "__all__") filters.queue_status = statusFilter;
    const trimmedCnj = debouncedCnjFilter.trim();
    if (trimmedCnj) filters.cnj_number = trimmedCnj;
    const trimmedIntake = debouncedIntakeFilter.trim();
    if (trimmedIntake && /^\d+$/.test(trimmedIntake)) {
      filters.intake_id = Number(trimmedIntake);
    }
    if (sinceFilter) filters.since = new Date(sinceFilter).toISOString();
    if (untilFilter) filters.until = new Date(untilFilter).toISOString();
    return filters;
  };

  const hasActiveFilters =
    statusFilter !== "__all__" ||
    cnjFilter.trim() !== "" ||
    intakeFilter.trim() !== "" ||
    sinceFilter !== "" ||
    untilFilter !== "";

  const handleClearFilters = () => {
    setStatusFilter("__all__");
    setCnjFilter("");
    setIntakeFilter("");
    setSinceFilter("");
    setUntilFilter("");
  };

  const loadPendingIntakes = async () => {
    setPendingIntakesLoading(true);
    try {
      // Lista intakes com dispatch_pending=true ordenados por
      // received_at desc (default do endpoint). Pega ate 100 — fase
      // de testes nao deve ter pilha enorme, e operador filtra na
      // PrazosIniciaisPage se quiser ver historico.
      const payload = await fetchPrazosIniciaisIntakes({
        dispatch_pending: true,
        limit: 100,
        offset: 0,
      });
      setPendingIntakes(payload.items);
      setPendingIntakesTotal(payload.total);
    } catch (err) {
      console.warn("Falha ao carregar intakes pendentes de disparo:", err);
    } finally {
      setPendingIntakesLoading(false);
    }
  };

  const handleDispatchIntake = async (intakeId: number) => {
    setDispatchingIntakeId(intakeId);
    try {
      const result = await dispatchPrazoInicialTreatmentWeb(intakeId);
      // Endpoint eh idempotente — `skipped:true` quando dispatch_pending
      // ja era false (ex.: outra aba/worker disparou antes).
      if (result.skipped) {
        toast({
          title: `Intake #${intakeId} ja foi disparado`,
          description: result.reason || "Sem mudanças.",
        });
      } else {
        const queueItem = result.legacy_task_cancellation_item as
          | { id?: number }
          | null;
        const queueId = queueItem?.id;
        toast({
          title: "Disparo concluído",
          description: queueId
            ? `Intake #${intakeId}: GED enviado e item #${queueId} entrou na fila de cancelamento.`
            : `Intake #${intakeId}: disparo OK.`,
        });
      }
      // Recarrega ambas as listas — o intake sai dos pendentes e
      // (em geral) aparece na fila de cancel.
      await Promise.all([loadPendingIntakes(), loadData()]);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Falha desconhecida.";
      toast({
        title: `Falha ao disparar intake #${intakeId}`,
        description: message,
        variant: "destructive",
      });
    } finally {
      setDispatchingIntakeId(null);
    }
  };

  const loadData = async (showToast = false) => {
    try {
      const filters = buildFilters();
      const [payload, metricsPayload] = await Promise.all([
        fetchPrazosIniciaisLegacyTaskCancelQueue(filters),
        fetchPrazosIniciaisLegacyTaskCancelQueueMetrics(24).catch(() => null),
      ]);
      setItems(payload.items);
      setTotal(payload.total);
      setMetrics(metricsPayload);
      setError(null);
      if (showToast) {
        const pendingCount = payload.items.filter((item) => item.queue_status === "PENDENTE").length;
        toast({
          title: "Painel atualizado",
          description: `${pendingCount} item(ns) pendente(s) na fila.`,
        });
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : "Erro ao carregar o tratamento web.";
      setError(message);
      if (showToast) {
        toast({
          title: "Falha ao atualizar",
          description: message,
          variant: "destructive",
        });
      }
    } finally {
      setIsLoading(false);
    }
  };

  // Reload sempre que mudar um filtro. Os textos passam por debounce — então
  // este effect só dispara depois que o usuário para de digitar por 400ms.
  useEffect(() => {
    loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter, debouncedCnjFilter, debouncedIntakeFilter, sinceFilter, untilFilter]);

  // Lista de intakes pendentes de disparo carrega 1x e auto-refresh
  // junto com o restante (5s). Nao depende dos filtros da fila de cancel.
  useEffect(() => {
    loadPendingIntakes();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const intervalId = setInterval(() => {
      loadData();
      loadPendingIntakes();
    }, 5000);
    return () => clearInterval(intervalId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter, debouncedCnjFilter, debouncedIntakeFilter, sinceFilter, untilFilter]);

  // Totais globais vêm do endpoint /metrics (totals_by_status), pra os cards
  // de resumo não dependerem do recorte do filtro — se o usuário filtra por
  // "Falhas" o card "Pendentes" ainda mostra o total real do sistema.
  // Fallback: se ainda não carregou métricas (primeira render), usa a lista
  // visível, mas mostra um aviso discreto.
  const summary = useMemo(() => {
    const totals = metrics?.totals_by_status ?? null;
    const fromTotals = (status: string) => Number(totals?.[status] ?? 0);
    if (totals) {
      const pending = fromTotals("PENDENTE");
      const processing = fromTotals("PROCESSANDO");
      const completed = fromTotals("CONCLUIDO");
      const failed = fromTotals("FALHA");
      const cancelled = fromTotals("CANCELADO");
      const actionable = pending + processing + failed;
      const denom = pending + processing + completed + failed + cancelled;
      const progress = denom > 0 ? Math.round((completed / denom) * 100) : 0;
      return { pending, processing, completed, failed, cancelled, actionable, progress, source: "global" as const };
    }
    const pending = items.filter((item) => item.queue_status === "PENDENTE").length;
    const processing = items.filter((item) => item.queue_status === "PROCESSANDO").length;
    const completed = items.filter((item) => item.queue_status === "CONCLUIDO").length;
    const failed = items.filter((item) => item.queue_status === "FALHA").length;
    const cancelled = items.filter((item) => item.queue_status === "CANCELADO").length;
    const actionable = pending + processing + failed;
    const denom = items.length;
    const progress = denom > 0 ? Math.round((completed / denom) * 100) : 0;
    return { pending, processing, completed, failed, cancelled, actionable, progress, source: "visible" as const };
  }, [items, metrics]);

  const recentFailures = useMemo(
    () => items.filter((item) => item.queue_status === "FALHA").slice(0, 6),
    [items],
  );

  const handleProcessQueue = async () => {
    try {
      setIsSubmitting(true);
      const response = await processPrazosIniciaisLegacyTaskCancelQueue(20);
      await loadData();
      if (response.circuit_breaker_tripped) {
        // Backend não processou nada porque o breaker está aberto. Isso é
        // diferente de "nenhum item elegível" — informa o operador que a
        // ação dele foi NO-OP e aponta pro botão de reset (se ele tiver
        // evidência de que o L1 voltou).
        toast({
          title: "Circuit breaker aberto — nada processado",
          description:
            "O worker está em cooldown por falhas consecutivas de infraestrutura. Confira se o Legal One respondeu e, se estiver estável, clique em \"Resetar breaker\" pra liberar a fila.",
          variant: "destructive",
        });
      } else {
        toast({
          title: response.processed_count > 0 ? "Fila processada" : "Nenhum item elegível",
          description:
            response.processed_count > 0
              ? `${response.processed_count} item(ns) processado(s) (${response.success_count ?? 0} sucesso / ${response.failure_count ?? 0} falha).`
              : "Não havia itens pendentes ou falhos para processar agora.",
        });
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : "Não foi possível processar a fila.";
      toast({
        title: "Falha ao processar fila",
        description: message,
        variant: "destructive",
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleResetCircuitBreaker = async () => {
    try {
      setIsResettingCircuitBreaker(true);
      await resetPrazosIniciaisLegacyTaskCancelCircuitBreaker();
      await loadData();
      toast({
        title: "Circuit breaker resetado",
        description:
          "O worker volta a processar no próximo tick. Se a causa-raiz persistir, o breaker vai abrir de novo.",
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : "Não foi possível resetar o circuit breaker.";
      toast({
        title: "Falha ao resetar breaker",
        description: message,
        variant: "destructive",
      });
    } finally {
      setIsResettingCircuitBreaker(false);
    }
  };

  const handleReprocessItem = async (itemId: number) => {
    try {
      setActionItemId(itemId);
      await reprocessPrazosIniciaisLegacyTaskCancelItem(itemId);
      await loadData();
      toast({
        title: "Reprocessamento iniciado",
        description: `Item #${itemId} voltou para PENDENTE e o RPA foi disparado em background. Atualize a lista em alguns segundos pra ver o resultado.`,
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : "Não foi possível reprocessar o item.";
      toast({
        title: "Falha ao reprocessar",
        description: message,
        variant: "destructive",
      });
    } finally {
      setActionItemId(null);
    }
  };

  const handleCancelItem = async (itemId: number) => {
    try {
      setActionItemId(itemId);
      await cancelPrazosIniciaisLegacyTaskCancelItem(itemId);
      await loadData();
      toast({
        title: "Item cancelado",
        description: `Item #${itemId} marcado como CANCELADO; não será mais reprocessado pelo worker.`,
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : "Não foi possível cancelar o item.";
      toast({
        title: "Falha ao cancelar",
        description: message,
        variant: "destructive",
      });
    } finally {
      setActionItemId(null);
    }
  };

  const handleDownloadCsv = async () => {
    try {
      setIsCsvDownloading(true);
      const filters = buildFilters();
      const blob = await downloadPrazosIniciaisLegacyTaskCancelQueueCsv({
        ...filters,
        limit: 5000,
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `legacy-task-cancel-queue-${new Date()
        .toISOString()
        .replace(/[:.]/g, "-")}.csv`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Falha ao baixar CSV.";
      toast({
        title: "Falha ao exportar",
        description: message,
        variant: "destructive",
      });
    } finally {
      setIsCsvDownloading(false);
    }
  };

  // Os cards de "status" mostram totais globais do sistema (via metrics).
  // "Itens no filtro" fica separado pra o operador diferenciar o recorte
  // atual do estado geral da fila.
  const totalsSuffix = summary.source === "global" ? " (global)" : " (visível)";
  const summaryCards = [
    { title: "Itens no filtro", value: total },
    { title: `Pendentes${totalsSuffix}`, value: summary.pending },
    { title: `Processando${totalsSuffix}`, value: summary.processing },
    { title: `Concluídos${totalsSuffix}`, value: summary.completed },
    { title: `Falhas${totalsSuffix}`, value: summary.failed },
    { title: `Cancelados${totalsSuffix}`, value: summary.cancelled },
  ];

  const cb = metrics?.circuit_breaker;
  const cbBadge = cb ? (
    cb.tripped ? (
      <Badge className="gap-1 bg-red-100 text-red-800">
        <ShieldAlert className="h-3.5 w-3.5" />
        Circuit breaker aberto
        {cb.tripped_until ? ` (até ${formatDateTime(cb.tripped_until)})` : ""}
      </Badge>
    ) : (
      <Badge className="gap-1 bg-green-100 text-green-800">
        <ShieldCheck className="h-3.5 w-3.5" />
        Circuit breaker fechado ({cb.consecutive_failures}/{cb.threshold})
      </Badge>
    )
  ) : null;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
              <Workflow className="h-6 w-6" />
              Tratamento Web Agendamentos Iniciais
            </h1>
            <Badge className={summary.actionable > 0 ? "bg-amber-100 text-amber-800" : "bg-green-100 text-green-800"}>
              {summary.actionable > 0 ? `${summary.actionable} aguardando tratamento` : "Fila estabilizada"}
            </Badge>
            {cbBadge}
          </div>
          <p className="text-muted-foreground">
            Monitora o cancelamento da task legada de Agendar Prazos depois que o operador confirma os agendamentos iniciais do processo.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" onClick={handleProcessQueue} disabled={isLoading || isSubmitting}>
            {isSubmitting ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Rocket className="mr-2 h-4 w-4" />
            )}
            Processar pendentes
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={handleDownloadCsv}
            disabled={isCsvDownloading}
            title="Exporta os itens com os filtros atuais (até 5.000 linhas)"
          >
            {isCsvDownloading ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Download className="mr-2 h-4 w-4" />
            )}
            Exportar CSV
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              loadData(true);
              loadPendingIntakes();
            }}
            disabled={isLoading || isSubmitting}
          >
            <RefreshCw className={`mr-2 h-4 w-4 ${isLoading ? "animate-spin" : ""}`} />
            Atualizar
          </Button>
        </div>
      </div>

      {error ? (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Falha ao carregar monitor</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      {cb?.tripped ? (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>Circuit breaker do worker aberto</AlertTitle>
          <AlertDescription>
            <p>
              O worker periódico vai pular ticks
              {cb.tripped_until ? ` até ${formatDateTime(cb.tripped_until)}` : ""}.
              Última causa: {reasonLabel(cb.last_trip_reason)}
              {" "}({cb.consecutive_failures} falha(s) consecutiva(s) de infraestrutura).
              Chamadas iniciadas por confirmação de agendamento também passam pelo
              bloqueio — confira primeiro se o Legal One está respondendo e só então
              libere o breaker.
            </p>
            <div className="mt-3">
              <Button
                size="sm"
                variant="outline"
                onClick={handleResetCircuitBreaker}
                disabled={isResettingCircuitBreaker}
                title="Zera o contador e reabilita o worker no próximo tick"
              >
                {isResettingCircuitBreaker ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Unlock className="mr-2 h-4 w-4" />
                )}
                Resetar breaker
              </Button>
            </div>
          </AlertDescription>
        </Alert>
      ) : null}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {summaryCards.map((card) => (
          <Card key={card.title} className="border-0 shadow-sm">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">{card.title}</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-3xl font-semibold">{card.value}</div>
            </CardContent>
          </Card>
        ))}
      </div>

      {metrics ? (
        <Card className="border-0 shadow-sm">
          <CardHeader>
            <CardTitle>Saúde do worker (últimas {metrics.window_hours}h)</CardTitle>
            <CardDescription>
              Snapshot agregado do circuit breaker, último tick do worker e contadores
              da janela.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4 text-sm">
              <div>
                <div className="text-muted-foreground">Concluídos na janela</div>
                <div className="text-xl font-semibold">{metrics.completed_in_window}</div>
              </div>
              <div>
                <div className="text-muted-foreground">Falhas na janela</div>
                <div className="text-xl font-semibold">{metrics.failures_in_window}</div>
              </div>
              <div>
                <div className="text-muted-foreground">Latência média</div>
                <div className="text-xl font-semibold">
                  {formatLatencyMs(metrics.avg_latency_ms_in_window)}
                </div>
                <div className="text-xs text-muted-foreground">
                  ({metrics.latency_samples_in_window} amostras)
                </div>
              </div>
              <div>
                <div className="text-muted-foreground">Rate limit configurado</div>
                <div className="text-xl font-semibold">
                  {metrics.rate_limit_seconds.toFixed(1)} s
                </div>
                <div className="text-xs text-muted-foreground">entre items</div>
              </div>
              <div className="md:col-span-2">
                <div className="text-muted-foreground">Falhas por motivo (janela)</div>
                {Object.keys(metrics.failures_by_reason_in_window).length === 0 ? (
                  <div className="text-sm text-muted-foreground">Sem falhas no período.</div>
                ) : (
                  <ul className="mt-1 space-y-1">
                    {Object.entries(metrics.failures_by_reason_in_window).map(
                      ([reason, count]) => (
                        <li key={reason} className="flex items-center justify-between gap-3">
                          <span>{reasonLabel(reason)}</span>
                          <Badge variant="outline">{count}</Badge>
                        </li>
                      ),
                    )}
                  </ul>
                )}
              </div>
              <div className="md:col-span-2">
                <div className="text-muted-foreground">Último tick do worker</div>
                <div className="text-sm">
                  {metrics.last_tick.tick_id ? (
                    <>
                      <div>
                        Início: {formatDateTime(metrics.last_tick.started_at)} · Fim:{" "}
                        {formatDateTime(metrics.last_tick.finished_at)}
                      </div>
                      <div>
                        Processados: {metrics.last_tick.processed_count} (
                        {metrics.last_tick.success_count} sucesso ·{" "}
                        {metrics.last_tick.failure_count} falha) · Duração:{" "}
                        {formatLatencyMs(metrics.last_tick.duration_ms)}
                      </div>
                      {metrics.last_tick.circuit_breaker_tripped ? (
                        <div className="text-amber-700">
                          Tick pulado pelo circuit breaker.
                        </div>
                      ) : null}
                      {metrics.last_tick.error ? (
                        <div className="text-red-700">
                          Erro: {metrics.last_tick.error}
                        </div>
                      ) : null}
                    </>
                  ) : (
                    <div className="text-muted-foreground">
                      Worker ainda não rodou nenhum tick neste processo.
                    </div>
                  )}
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      ) : null}

      {/* ─── Intakes pendentes de disparo (1 por 1) ──────────────────
          Etapa ANTERIOR a fila de cancel. Lista intakes que ja foram
          confirmados mas ainda nao tiveram GED upload + enqueue cancel
          disparado. Operador pode disparar 1 por 1 (botao "Disparar"
          em cada linha) — util pra fase de testes onde queremos
          observar cada caso isoladamente, em vez do batch de 10. */}
      <Card className="border-0 shadow-sm">
        <CardHeader className="flex flex-row items-start justify-between gap-4">
          <div>
            <CardTitle className="flex items-center gap-2">
              <Play className="h-5 w-5" />
              Intakes pendentes de disparo
              <Badge
                className={
                  pendingIntakesTotal > 0
                    ? "bg-amber-100 text-amber-800"
                    : "bg-green-100 text-green-800"
                }
              >
                {pendingIntakesTotal}
              </Badge>
            </CardTitle>
            <CardDescription>
              Intakes confirmados (status AGENDADO ou CONCLUÍDO_SEM_PROVIDÊNCIA)
              ainda não disparados — disparo executa GED upload + enfileira o
              cancelamento da task legada. Use "Disparar" individual pra
              testar 1 por 1.
            </CardDescription>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={loadPendingIntakes}
            disabled={pendingIntakesLoading}
            title="Recarregar a lista de pendentes"
          >
            <RefreshCw
              className={`mr-2 h-4 w-4 ${pendingIntakesLoading ? "animate-spin" : ""}`}
            />
            Atualizar
          </Button>
        </CardHeader>
        <CardContent>
          {pendingIntakesLoading && pendingIntakes.length === 0 ? (
            <div className="flex min-h-24 items-center justify-center text-muted-foreground">
              <Loader2 className="mr-2 h-5 w-5 animate-spin" />
              Carregando...
            </div>
          ) : pendingIntakes.length === 0 ? (
            <div className="text-sm text-muted-foreground py-4 text-center">
              Sem intakes aguardando disparo. Os próximos confirmados aparecem
              aqui automaticamente.
            </div>
          ) : (
            <div className="overflow-x-auto rounded-md border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-[80px]">Intake</TableHead>
                    <TableHead>CNJ</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Tratado em</TableHead>
                    <TableHead>Tratado por</TableHead>
                    <TableHead>Última falha de disparo</TableHead>
                    <TableHead className="w-[140px] text-right">Ações</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {pendingIntakes.map((intake) => {
                    const isDispatchingThis = dispatchingIntakeId === intake.id;
                    const anyDispatching = dispatchingIntakeId !== null;
                    return (
                      <TableRow key={intake.id}>
                        <TableCell className="font-mono text-xs">
                          #{intake.id}
                        </TableCell>
                        <TableCell className="font-mono text-xs">
                          {intake.cnj_number || "-"}
                        </TableCell>
                        <TableCell>
                          <Badge variant="outline" className="text-[10px]">
                            {intake.status}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {formatDateTime(intake.treated_at)}
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {intake.treated_by_name || intake.treated_by_email || "-"}
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground max-w-[280px] truncate">
                          {intake.dispatch_error_message ? (
                            <span
                              className="text-red-700"
                              title={intake.dispatch_error_message}
                            >
                              {intake.dispatch_error_message}
                            </span>
                          ) : (
                            "—"
                          )}
                        </TableCell>
                        <TableCell className="text-right">
                          <div className="flex items-center justify-end gap-2">
                            <Link
                              to={`/prazos-iniciais?intake=${intake.id}`}
                              className="text-xs text-blue-600 hover:underline"
                              title="Abrir intake na página principal"
                            >
                              Detalhes
                            </Link>
                            <Button
                              size="sm"
                              variant="default"
                              disabled={anyDispatching}
                              onClick={() => handleDispatchIntake(intake.id)}
                              title="Sobe habilitação no GED + enfileira cancelamento da task legada"
                            >
                              {isDispatchingThis ? (
                                <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
                              ) : (
                                <Play className="mr-1 h-3.5 w-3.5" />
                              )}
                              Disparar
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          )}
          {pendingIntakesTotal > pendingIntakes.length ? (
            <div className="mt-2 text-xs text-muted-foreground">
              Mostrando {pendingIntakes.length} de {pendingIntakesTotal} intakes
              pendentes. Use a página principal pra ver todos com filtros.
            </div>
          ) : null}
        </CardContent>
      </Card>

      <Card className="border-0 shadow-sm">
        <CardHeader>
          <CardTitle>Andamento da fila</CardTitle>
          <CardDescription>
            A API já tenta processar em background ao confirmar o agendamento, e esse painel ajuda a acompanhar os casos que sobraram na fila técnica.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {isLoading ? (
            <div className="flex min-h-24 items-center justify-center text-muted-foreground">
              <Loader2 className="mr-2 h-5 w-5 animate-spin" />
              Carregando...
            </div>
          ) : (
            <>
              <Progress value={summary.progress} className="h-3" />
              <div className="grid gap-2 text-sm text-muted-foreground md:grid-cols-2 xl:grid-cols-4">
                <span>
                  Progresso ({summary.source === "global" ? "global" : "visível"}): {summary.progress}%
                </span>
                <span>Com pendência: {summary.actionable}</span>
                <span>Última atualização: {formatDateTime(items[0]?.updated_at || items[0]?.created_at)}</span>
                <span>Execução manual disponível a qualquer momento</span>
              </div>
            </>
          )}
        </CardContent>
      </Card>

      <Card className="border-0 shadow-sm">
        <CardHeader className="flex flex-row items-start justify-between gap-4">
          <div>
            <CardTitle>Filtros</CardTitle>
            <CardDescription>
              Os filtros são aplicados no servidor — a exportação CSV usa exatamente o mesmo
              recorte exibido aqui. Textos têm debounce de 400ms pra evitar flicker enquanto
              você digita.
            </CardDescription>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={handleClearFilters}
            disabled={!hasActiveFilters}
            title="Restaura status=Todos, limpa CNJ/Intake e intervalo de datas"
          >
            <Eraser className="mr-2 h-4 w-4" />
            Limpar filtros
          </Button>
        </CardHeader>
        <CardContent>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">Status</label>
              <Select value={statusFilter} onValueChange={setStatusFilter}>
                <SelectTrigger>
                  <SelectValue placeholder="Filtrar status" />
                </SelectTrigger>
                <SelectContent>
                  {STATUS_OPTIONS.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">CNJ</label>
              <Input
                placeholder="Trecho do CNJ"
                value={cnjFilter}
                onChange={(event) => setCnjFilter(event.target.value)}
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">Intake ID</label>
              <Input
                placeholder="ex.: 1234"
                value={intakeFilter}
                onChange={(event) => setIntakeFilter(event.target.value)}
                inputMode="numeric"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">Atualizado desde</label>
              <Input
                type="datetime-local"
                value={sinceFilter}
                onChange={(event) => setSinceFilter(event.target.value)}
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">Atualizado até</label>
              <Input
                type="datetime-local"
                value={untilFilter}
                onChange={(event) => setUntilFilter(event.target.value)}
              />
            </div>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-6 xl:grid-cols-[1.1fr_1.4fr]">
        <Card className="border-0 shadow-sm">
          <CardHeader>
            <CardTitle>Falhas recentes</CardTitle>
            <CardDescription>
              Itens em falha continuam elegíveis para novo processamento manual ou automático.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {recentFailures.length > 0 ? (
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>CNJ</TableHead>
                      <TableHead>Intake</TableHead>
                      <TableHead>Motivo</TableHead>
                      <TableHead>Erro</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {recentFailures.map((item) => (
                      <TableRow key={`failure-${item.id}`}>
                        <TableCell className="font-mono text-xs">{formatCnj(item.cnj_number)}</TableCell>
                        <TableCell>
                          <Link
                            to={`/prazos-iniciais?intake=${item.intake_id}`}
                            className="text-primary hover:underline"
                            title="Abrir detalhes do intake"
                          >
                            #{item.intake_id}
                          </Link>
                        </TableCell>
                        <TableCell>{reasonLabel(item.last_reason)}</TableCell>
                        <TableCell className="max-w-[280px] truncate" title={item.last_error || ""}>
                          {item.last_error || "-"}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            ) : (
              <Alert>
                <AlertCircle className="h-4 w-4" />
                <AlertTitle>Sem falhas recentes</AlertTitle>
                <AlertDescription>
                  Os itens que chegam aqui com sucesso saem da fila assim que a task legada é cancelada no Legal One.
                </AlertDescription>
              </Alert>
            )}
          </CardContent>
        </Card>

        <Card className="border-0 shadow-sm">
          <CardHeader>
            <CardTitle>Fila técnica</CardTitle>
            <CardDescription>
              Visualização operacional dos itens gerados a partir da confirmação do agendamento.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>CNJ</TableHead>
                    <TableHead>Intake</TableHead>
                    <TableHead>Processo L1</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Tent.</TableHead>
                    <TableHead>Task alvo</TableHead>
                    <TableHead>Task cancelada</TableHead>
                    <TableHead>Último motivo</TableHead>
                    <TableHead>Atualizado</TableHead>
                    <TableHead>Ações</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {items.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={10} className="py-10 text-center text-muted-foreground">
                        {isLoading ? "Carregando..." : "Nenhum item encontrado para o filtro atual."}
                      </TableCell>
                    </TableRow>
                  ) : (
                    items.map((item) => {
                      const taskLink = resolveTaskLink(item);
                      const acting = actionItemId === item.id;
                      return (
                        <TableRow key={item.id}>
                          <TableCell className="font-mono text-xs">{formatCnj(item.cnj_number)}</TableCell>
                          <TableCell>
                            <Link
                              to={`/prazos-iniciais?intake=${item.intake_id}`}
                              className="text-primary hover:underline"
                              title="Abrir detalhes do intake"
                            >
                              #{item.intake_id}
                            </Link>
                          </TableCell>
                          <TableCell>{item.lawsuit_id || "-"}</TableCell>
                          <TableCell>
                            <Badge className={queueStatusClass(item.queue_status)}>
                              {queueStatusLabel(item.queue_status)}
                            </Badge>
                          </TableCell>
                          <TableCell>{item.attempt_count}</TableCell>
                          <TableCell>{item.selected_task_id || "-"}</TableCell>
                          <TableCell>{item.cancelled_task_id || "-"}</TableCell>
                          <TableCell>{reasonLabel(item.last_reason)}</TableCell>
                          <TableCell>{formatDateTime(item.updated_at || item.created_at)}</TableCell>
                          <TableCell>
                            <div className="flex flex-wrap items-center gap-2">
                              {taskLink ? (
                                <a
                                  href={taskLink}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="inline-flex items-center gap-1 text-primary hover:underline"
                                  title="Abrir a task no Legal One"
                                >
                                  <ExternalLink className="h-3.5 w-3.5" />
                                </a>
                              ) : null}
                              {isItemReprocessable(item) ? (
                                <Button
                                  size="sm"
                                  variant="outline"
                                  className="h-7 px-2"
                                  disabled={acting}
                                  onClick={() => handleReprocessItem(item.id)}
                                  title="Voltar item para PENDENTE para o worker reprocessar"
                                >
                                  {acting ? (
                                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                  ) : (
                                    <RotateCcw className="h-3.5 w-3.5" />
                                  )}
                                </Button>
                              ) : null}
                              {isItemCancellable(item) ? (
                                <Button
                                  size="sm"
                                  variant="ghost"
                                  className="h-7 px-2 text-red-700 hover:bg-red-50"
                                  disabled={acting}
                                  onClick={() => handleCancelItem(item.id)}
                                  title="Cancelar manualmente este item (não será mais reprocessado)"
                                >
                                  {acting ? (
                                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                  ) : (
                                    <Ban className="h-3.5 w-3.5" />
                                  )}
                                </Button>
                              ) : null}
                            </div>
                          </TableCell>
                        </TableRow>
                      );
                    })
                  )}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
