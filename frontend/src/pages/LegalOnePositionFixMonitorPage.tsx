import { useEffect, useState } from "react";
import { AlertCircle, CheckCircle2, Clock3, Loader2, Pause, Play, RefreshCw } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useToast } from "@/hooks/use-toast";
import { fetchLegalOnePositionFixStatus, updateLegalOnePositionFixControl } from "@/services/api";
import { LegalOnePositionFixProgressItem, LegalOnePositionFixStatus } from "@/types/api";

const statusLabelMap: Record<string, string> = {
  updated: "Atualizado",
  verify_failed: "Falha na verificacao",
  error: "Erro",
  scheduled_retry: "Agendado para reprocesso",
};

const statusBadgeClassMap: Record<string, string> = {
  updated: "bg-green-100 text-green-800",
  verify_failed: "bg-amber-100 text-amber-800",
  error: "bg-red-100 text-red-800",
  scheduled_retry: "bg-sky-100 text-sky-800",
};

function formatDateTime(value: string | null | undefined) {
  if (!value) return "N/A";
  return new Intl.DateTimeFormat("pt-BR", {
    dateStyle: "short",
    timeStyle: "medium",
    timeZone: "America/Sao_Paulo",
  }).format(new Date(value));
}

function formatDuration(seconds: number | null | undefined) {
  if (seconds == null || Number.isNaN(seconds)) return "N/A";

  const rounded = Math.max(0, Math.round(seconds));
  const hours = Math.floor(rounded / 3600);
  const minutes = Math.floor((rounded % 3600) / 60);
  const remainingSeconds = rounded % 60;

  if (hours > 0) return `${hours}h ${minutes}min`;
  if (minutes > 0) return `${minutes}min ${remainingSeconds}s`;
  return `${remainingSeconds}s`;
}

function ExecutionStatusBadge({ data }: { data: LegalOnePositionFixStatus | null }) {
  if (!data || !data.available) {
    return <Badge variant="outline">Aguardando arquivo</Badge>;
  }
  if (data.state === "paused") {
    return <Badge className="bg-amber-100 text-amber-800">Pausado</Badge>;
  }
  if (data.state === "sleeping") {
    return <Badge className="bg-sky-100 text-sky-800">Pausa entre lotes</Badge>;
  }
  if (data.state === "stopped") {
    return <Badge className="bg-slate-200 text-slate-800">Interrompido</Badge>;
  }
  if (data.processed_items >= data.total_items && data.failed_count > 0) {
    return <Badge className="bg-amber-100 text-amber-800">Concluido com falhas</Badge>;
  }
  if (data.processed_items >= data.total_items && data.total_items > 0) {
    return <Badge className="bg-green-100 text-green-800">Concluido</Badge>;
  }
  if (data.processed_items > 0) {
    return <Badge className="bg-blue-100 text-blue-800">Em andamento</Badge>;
  }
  return <Badge variant="outline">Pronto para iniciar</Badge>;
}

function ItemStatusBadge({ item }: { item: LegalOnePositionFixProgressItem }) {
  const label = statusLabelMap[item.status] || item.status;
  const className = statusBadgeClassMap[item.status] || "bg-slate-100 text-slate-700";
  return <Badge className={className}>{label}</Badge>;
}

export default function LegalOnePositionFixMonitorPage() {
  const { toast } = useToast();
  const [data, setData] = useState<LegalOnePositionFixStatus | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmittingControl, setIsSubmittingControl] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadStatus = async (showToast = false) => {
    try {
      const status = await fetchLegalOnePositionFixStatus();
      setData(status);
      setError(null);
      if (showToast) {
        toast({
          title: "Andamento atualizado",
          description: `${status.processed_items}/${status.total_items} processos acompanhados.`,
        });
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : "Erro inesperado ao carregar o andamento.";
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
    loadStatus();
    const intervalId = setInterval(() => {
      loadStatus();
    }, 5000);
    return () => clearInterval(intervalId);
  }, []);

  const handleControl = async (action: "pause" | "resume") => {
    try {
      setIsSubmittingControl(true);
      const response = await updateLegalOnePositionFixControl(action);
      await loadStatus();
      toast({
        title: action === "pause" ? "Pausa solicitada" : "Execucao retomada",
        description: `${response.message} Arquivo: ${response.control_file}`,
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : "Nao foi possivel alterar a execucao.";
      toast({
        title: "Falha ao alterar execucao",
        description: message,
        variant: "destructive",
      });
    } finally {
      setIsSubmittingControl(false);
    }
  };

  const summaryCards = [
    { title: "Total do lote", value: data?.total_items ?? 0 },
    { title: "Processados", value: data?.processed_items ?? 0 },
    { title: "Atualizados", value: data?.updated_count ?? 0 },
    { title: "Falhas", value: data?.failed_count ?? 0 },
    { title: "Agendados p/ reprocesso", value: data?.retry_pending_count ?? 0 },
    { title: "Media por atualizacao", value: formatDuration(data?.average_update_seconds) },
    { title: "Tempo restante estimado", value: formatDuration(data?.estimated_remaining_seconds) },
  ];

  return (
    <div className="container mx-auto px-6 py-8 space-y-8">
      <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div className="space-y-2">
          <div className="flex items-center gap-3">
            <h1 className="text-3xl font-bold bg-gradient-to-r from-primary to-accent bg-clip-text text-transparent">
              Monitor de Correcao Legal One
            </h1>
            <ExecutionStatusBadge data={data} />
          </div>
          <p className="text-sm text-muted-foreground">
            Acompanhe a troca da posicao do cliente principal em tempo quase real.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => handleControl("pause")}
            disabled={isLoading || isSubmittingControl || data?.control_signal === "pause" || data?.state === "paused"}
          >
            <Pause className="mr-2 h-4 w-4" />
            Pausar
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => handleControl("resume")}
            disabled={
              isLoading ||
              isSubmittingControl ||
              (data?.control_signal !== "pause" && data?.state !== "paused" && data?.state !== "stopped")
            }
          >
            <Play className="mr-2 h-4 w-4" />
            Continuar
          </Button>
          <Button variant="outline" size="sm" onClick={() => loadStatus(true)} disabled={isLoading || isSubmittingControl}>
            <RefreshCw className={`mr-2 h-4 w-4 ${isLoading ? "animate-spin" : ""}`} />
            Atualizar
          </Button>
        </div>
      </div>

      {error ? (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Falha ao carregar andamento</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      {!isLoading && data && !data.available ? (
        <Alert>
          <Clock3 className="h-4 w-4" />
          <AlertTitle>Execucao ainda nao iniciada</AlertTitle>
          <AlertDescription>
            O arquivo de progresso ainda nao foi encontrado. Assim que a automacao gravar o lote vivo, a tela comeca a
            atualizar sozinha.
            <div className="mt-2 text-xs text-muted-foreground">{data.file_path}</div>
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

      <Card className="border-0 shadow-sm">
        <CardHeader>
          <CardTitle>Progresso do lote</CardTitle>
          <CardDescription>
            Ultima leitura: {formatDateTime(data?.generated_at)}. Arquivo monitorado: {data?.file_path || "N/A"}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <Progress value={data?.progress_percentage ?? 0} className="h-3" />
          <div className="flex flex-col gap-2 text-sm text-muted-foreground md:flex-row md:items-center md:justify-between">
            <span>{data?.progress_percentage ?? 0}% concluido</span>
            <span>{data?.remaining_items ?? 0} restantes</span>
          </div>
          <div className="grid gap-2 text-sm text-muted-foreground md:grid-cols-2">
            <span>
              Lote atual: {data?.current_batch ?? "-"} de {data?.total_batches ?? "-"} com blocos de {data?.batch_size ?? "-"}
            </span>
            <span>
              Fila ativa: {data?.active_queue_type === "retry" ? `Reprocesso ${data?.retry_pass ?? 1}` : "Primeira passagem"}
            </span>
            <span>Pausa ate: {formatDateTime(data?.sleep_until)}</span>
            <span>Conclusao estimada: {formatDateTime(data?.estimated_completion_at)}</span>
            <span>Media efetiva com pausas: {formatDuration(data?.effective_average_seconds)}</span>
            <span>Sinal atual: {data?.control_signal === "pause" ? "Pausa solicitada" : "Execucao livre"}</span>
            <span>Maximo de tentativas: {data?.max_attempts ?? "-"}</span>
            <span className="md:col-span-2">Arquivo de controle: {data?.control_file || "N/A"}</span>
          </div>
        </CardContent>
      </Card>

      {data?.workers && data.workers.length > 0 ? (
        <Card className="border-0 shadow-sm">
          <CardHeader>
            <CardTitle>Workers</CardTitle>
            <CardDescription>Resumo por instancia em execucao paralela.</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid gap-4 md:grid-cols-2">
              {data.workers.map((worker) => (
                <div key={worker.id} className="rounded-xl border border-border/70 p-4 space-y-3">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <div className="font-semibold">{worker.label || worker.id}</div>
                      <div className="text-xs text-muted-foreground">Estado: {worker.state || "N/A"}</div>
                    </div>
                    <Badge variant="outline">{worker.id}</Badge>
                  </div>
                  <div className="grid grid-cols-2 gap-2 text-sm">
                    <div>Total: {worker.total_items ?? 0}</div>
                    <div>Processados: {worker.processed_items ?? 0}</div>
                    <div>Atualizados: {worker.updated_count ?? 0}</div>
                    <div>Falhas: {worker.failed_count ?? 0}</div>
                    <div>Retry: {worker.retry_pending_count ?? 0}</div>
                    <div>Restantes: {worker.remaining_items ?? 0}</div>
                  </div>
                  <div className="text-xs text-muted-foreground">
                    Lote {worker.current_batch ?? "-"} de {worker.total_batches ?? "-"} · Ultima leitura{" "}
                    {formatDateTime(worker.generated_at)}
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      ) : null}

      <Card className="border-0 shadow-sm">
        <CardHeader>
          <CardTitle>Ultimos processos</CardTitle>
          <CardDescription>Os itens mais recentes aparecem primeiro.</CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="flex min-h-40 items-center justify-center text-muted-foreground">
              <Loader2 className="mr-2 h-5 w-5 animate-spin" />
              Carregando andamento...
            </div>
          ) : data?.items.length ? (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>#</TableHead>
                    <TableHead>CNJ</TableHead>
                    <TableHead>Sequencial</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Inicio</TableHead>
                    <TableHead>Fim</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.items.map((item) => (
                    <TableRow key={`${item.index}-${item.cnj}`}>
                      <TableCell>{item.index}</TableCell>
                      <TableCell className="font-mono text-xs">{item.cnj}</TableCell>
                      <TableCell className="font-mono">{item.sequenceNumber || "-"}</TableCell>
                      <TableCell>
                        <div className="flex flex-col gap-2">
                          <ItemStatusBadge item={item} />
                          {item.error ? <span className="text-xs text-red-600">{item.error}</span> : null}
                        </div>
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">{formatDateTime(item.startedAt)}</TableCell>
                      <TableCell className="text-xs text-muted-foreground">{formatDateTime(item.finishedAt)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          ) : (
            <Alert>
              <CheckCircle2 className="h-4 w-4" />
              <AlertTitle>Nenhum item processado ainda</AlertTitle>
              <AlertDescription>
                A lista sera preenchida automaticamente assim que a execucao comecar a gravar resultados.
              </AlertDescription>
            </Alert>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
