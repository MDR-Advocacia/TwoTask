import { useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  ExternalLink,
  Loader2,
  RefreshCw,
  Rocket,
  Workflow,
} from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
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
  fetchPrazosIniciaisLegacyTaskCancelQueue,
  processPrazosIniciaisLegacyTaskCancelQueue,
} from "@/services/api";
import type {
  PrazoInicialLegacyTaskCancelQueueItem,
  PrazoInicialLegacyTaskCancelQueueStatus,
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

function resolveTaskLink(item: PrazoInicialLegacyTaskCancelQueueItem): string | null {
  const lastResult = item.last_result || {};
  return lastResult.details_url || lastResult.edit_url || null;
}

export default function PrazosIniciaisTreatmentPage() {
  const { toast } = useToast();
  const [items, setItems] = useState<PrazoInicialLegacyTaskCancelQueueItem[]>([]);
  const [total, setTotal] = useState(0);
  const [statusFilter, setStatusFilter] = useState("__all__");
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = async (showToast = false) => {
    try {
      const payload = await fetchPrazosIniciaisLegacyTaskCancelQueue({ limit: 500 });
      setItems(payload.items);
      setTotal(payload.total);
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

  useEffect(() => {
    loadData();
    const intervalId = setInterval(() => loadData(), 5000);
    return () => clearInterval(intervalId);
  }, []);

  const visibleItems = useMemo(() => {
    if (statusFilter === "__all__") return items;
    return items.filter((item) => item.queue_status === statusFilter);
  }, [items, statusFilter]);

  const summary = useMemo(() => {
    const pending = items.filter((item) => item.queue_status === "PENDENTE").length;
    const processing = items.filter((item) => item.queue_status === "PROCESSANDO").length;
    const completed = items.filter((item) => item.queue_status === "CONCLUIDO").length;
    const failed = items.filter((item) => item.queue_status === "FALHA").length;
    const cancelled = items.filter((item) => item.queue_status === "CANCELADO").length;
    const actionable = pending + processing + failed;
    const progress = total > 0 ? Math.round((completed / total) * 100) : 0;
    return { pending, processing, completed, failed, cancelled, actionable, progress };
  }, [items, total]);

  const recentFailures = useMemo(
    () => items.filter((item) => item.queue_status === "FALHA").slice(0, 6),
    [items],
  );

  const handleProcessQueue = async () => {
    try {
      setIsSubmitting(true);
      const response = await processPrazosIniciaisLegacyTaskCancelQueue(20);
      await loadData();
      toast({
        title: response.processed_count > 0 ? "Fila processada" : "Nenhum item elegível",
        description:
          response.processed_count > 0
            ? `${response.processed_count} item(ns) processado(s) nesta execução manual.`
            : "Não havia itens pendentes ou falhos para processar agora.",
      });
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

  const summaryCards = [
    { title: "Itens na fila", value: total },
    { title: "Pendentes", value: summary.pending },
    { title: "Processando", value: summary.processing },
    { title: "Concluídos", value: summary.completed },
    { title: "Falhas", value: summary.failed },
    { title: "Cancelados", value: summary.cancelled },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
              <Workflow className="h-6 w-6" />
              Tratamento Web Agendamentos Iniciais
            </h1>
            <Badge className={summary.actionable > 0 ? "bg-amber-100 text-amber-800" : "bg-green-100 text-green-800"}>
              {summary.actionable > 0 ? `${summary.actionable} aguardando tratamento` : "Fila estabilizada"}
            </Badge>
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
          <Button variant="outline" size="sm" onClick={() => loadData(true)} disabled={isLoading || isSubmitting}>
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
                <span>Progresso concluído: {summary.progress}%</span>
                <span>Com pendência: {summary.actionable}</span>
                <span>Última carga: {formatDateTime(items[0]?.updated_at || items[0]?.created_at)}</span>
                <span>Execução manual disponível a qualquer momento</span>
              </div>
            </>
          )}
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
                        <TableCell>#{item.intake_id}</TableCell>
                        <TableCell>{item.last_reason || "-"}</TableCell>
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
            <div className="flex items-center justify-between gap-3">
              <div>
                <CardTitle>Fila técnica</CardTitle>
                <CardDescription>
                  Visualização operacional dos itens gerados a partir da confirmação do agendamento.
                </CardDescription>
              </div>
              <div className="w-full max-w-[220px]">
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
            </div>
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
                    <TableHead></TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {visibleItems.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={10} className="py-10 text-center text-muted-foreground">
                        {isLoading ? "Carregando..." : "Nenhum item encontrado para o filtro atual."}
                      </TableCell>
                    </TableRow>
                  ) : (
                    visibleItems.map((item) => {
                      const taskLink = resolveTaskLink(item);
                      return (
                        <TableRow key={item.id}>
                          <TableCell className="font-mono text-xs">{formatCnj(item.cnj_number)}</TableCell>
                          <TableCell>#{item.intake_id}</TableCell>
                          <TableCell>{item.lawsuit_id || "-"}</TableCell>
                          <TableCell>
                            <Badge className={queueStatusClass(item.queue_status)}>
                              {queueStatusLabel(item.queue_status)}
                            </Badge>
                          </TableCell>
                          <TableCell>{item.attempt_count}</TableCell>
                          <TableCell>{item.selected_task_id || "-"}</TableCell>
                          <TableCell>{item.cancelled_task_id || "-"}</TableCell>
                          <TableCell>{item.last_reason || "-"}</TableCell>
                          <TableCell>{formatDateTime(item.updated_at || item.created_at)}</TableCell>
                          <TableCell>
                            {taskLink ? (
                              <a
                                href={taskLink}
                                target="_blank"
                                rel="noreferrer"
                                className="inline-flex items-center gap-1 text-primary hover:underline"
                              >
                                Abrir
                                <ExternalLink className="h-3.5 w-3.5" />
                              </a>
                            ) : (
                              <span className="text-muted-foreground">-</span>
                            )}
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
