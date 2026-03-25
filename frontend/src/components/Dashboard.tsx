import { useEffect, useState } from "react";
import {
  Activity,
  AlertCircle,
  BrainCircuit,
  CheckCircle2,
  Download,
  FileUp,
  Filter,
  History,
  Loader2,
  Pause,
  RefreshCw,
  Square,
  Target,
  Webhook,
  XCircle,
  Play,
} from "lucide-react";

import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Pagination,
  PaginationContent,
  PaginationItem,
  PaginationNext,
  PaginationPrevious,
} from "@/components/ui/pagination";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useToast } from "@/hooks/use-toast";
import { BatchExecution, BatchExecutionItem } from "@/types/api";
import {
  cancelBatchExecution,
  downloadBatchErrorReport,
  fetchBatchExecutions,
  pauseBatchExecution,
  resumeBatchExecution,
  retryBatchExecution,
} from "@/services/api";


const sourceDisplayNames: { [key: string]: string } = {
  planilha: "Planilha",
  onesid: "Onesid",
  onerequest: "Onerequest",
};

const sourceIcons: { [key: string]: React.ElementType } = {
  planilha: FileUp,
  onesid: BrainCircuit,
  onerequest: Webhook,
  default: History,
};

const statusLabelMap: Record<string, string> = {
  PENDENTE: "Pendente",
  PROCESSANDO: "Processando",
  PAUSADO: "Pausado",
  CANCELADO: "Cancelado",
  CONCLUIDO: "Concluido",
  CONCLUIDO_COM_FALHAS: "Concluido c/ falhas",
};

const statusBadgeClassMap: Record<string, string> = {
  PENDENTE: "bg-slate-100 text-slate-700",
  PROCESSANDO: "bg-blue-100 text-blue-800",
  PAUSADO: "bg-amber-100 text-amber-800",
  CANCELADO: "bg-red-100 text-red-800",
  CONCLUIDO: "bg-green-100 text-green-800",
  CONCLUIDO_COM_FALHAS: "bg-orange-100 text-orange-800",
};

const SourceBadge = ({ source }: { source: string }) => {
  const lowerSource = source.toLowerCase();
  const displayName = sourceDisplayNames[lowerSource] || source;
  const Icon = sourceIcons[lowerSource] || sourceIcons.default;

  return (
    <Badge variant="outline" className="flex items-center gap-2">
      <Icon className="h-4 w-4" />
      <span>{displayName}</span>
    </Badge>
  );
};

const groupFailures = (items: BatchExecutionItem[]) => {
  const failures = items.filter((item) => item.status === "FALHA");
  return failures.reduce((acc, item) => {
    const errorMsg = item.error_message || "Erro desconhecido";
    if (!acc[errorMsg]) {
      acc[errorMsg] = [];
    }
    acc[errorMsg].push(item.id);
    return acc;
  }, {} as Record<string, number[]>);
};

const Dashboard = () => {
  const [allExecutions, setAllExecutions] = useState<BatchExecution[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isRetrying, setIsRetrying] = useState<Record<number, boolean>>({});
  const [isControlling, setIsControlling] = useState<Record<number, string | null>>({});
  const [currentPage, setCurrentPage] = useState(1);

  const itemsPerPage = 10;
  const { toast } = useToast();

  const loadData = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await fetchBatchExecutions();
      setAllExecutions(data);
      setCurrentPage(1);
    } catch {
      setError("Nao foi possivel carregar o historico de execucoes. A API pode estar offline.");
      setAllExecutions([]);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const totalPages = Math.ceil(allExecutions.length / itemsPerPage);
  const paginatedExecutions = allExecutions.slice(
    (currentPage - 1) * itemsPerPage,
    currentPage * itemsPerPage,
  );

  const handlePageChange = (page: number) => {
    if (page >= 1 && page <= totalPages) {
      setCurrentPage(page);
    }
  };

  const handleRetry = async (executionId: number, itemIds: number[] | null = null) => {
    setIsRetrying((prev) => ({ ...prev, [executionId]: true }));
    try {
      await retryBatchExecution(executionId, itemIds);
      toast({
        title: "Reprocessamento iniciado",
        description: itemIds ? `Grupo com ${itemIds.length} item(ns) enviado.` : "Reprocessamento total iniciado.",
      });
      setTimeout(loadData, 1500);
    } catch (err) {
      toast({
        title: "Erro ao reprocessar",
        description: err instanceof Error ? err.message : "Tente novamente.",
        variant: "destructive",
      });
    } finally {
      setIsRetrying((prev) => ({ ...prev, [executionId]: false }));
    }
  };

  const handleControl = async (execution: BatchExecution, action: "pause" | "resume" | "cancel" | "report") => {
    setIsControlling((prev) => ({ ...prev, [execution.id]: action }));
    try {
      if (action === "pause") {
        await pauseBatchExecution(execution.id);
      } else if (action === "resume") {
        await resumeBatchExecution(execution.id);
      } else if (action === "cancel") {
        await cancelBatchExecution(execution.id);
      } else {
        const blob = await downloadBatchErrorReport(execution.id);
        const url = window.URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = `lote_${execution.id}_erros.csv`;
        document.body.appendChild(link);
        link.click();
        link.remove();
        window.URL.revokeObjectURL(url);
      }

      if (action !== "report") {
        toast({
          title: "Lote atualizado",
          description: `Acao "${action}" executada com sucesso.`,
        });
        setTimeout(loadData, 1200);
      }
    } catch (err) {
      toast({
        title: "Erro na acao do lote",
        description: err instanceof Error ? err.message : "Tente novamente.",
        variant: "destructive",
      });
    } finally {
      setIsControlling((prev) => ({ ...prev, [execution.id]: null }));
    }
  };

  const formatDateTime = (isoString: string | null) => {
    if (!isoString) return "N/A";
    let parsableString = isoString;
    const hasTimezone =
      isoString.endsWith("Z") || isoString.includes("+") || isoString.substring(10).includes("-");
    if (!hasTimezone) parsableString = `${isoString}Z`;

    return new Intl.DateTimeFormat("pt-BR", {
      dateStyle: "short",
      timeStyle: "medium",
      timeZone: "America/Sao_Paulo",
    }).format(new Date(parsableString));
  };

  const stats = [
    { title: "Execucoes", value: allExecutions.length, icon: Activity },
    { title: "Total Itens", value: allExecutions.reduce((acc, curr) => acc + (curr.total_items || 0), 0), icon: Target },
  ];

  return (
    <div className="container mx-auto px-6 py-8 space-y-8">
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 mb-8">
        <div>
          <h1 className="text-3xl font-bold bg-gradient-to-r from-primary to-accent bg-clip-text text-transparent">
            Dashboard de Acompanhamento
          </h1>
        </div>
        <Button onClick={loadData} variant="outline" size="sm" disabled={isLoading}>
          <RefreshCw className={`w-4 h-4 mr-2 ${isLoading ? "animate-spin" : ""}`} />
          Atualizar Dados
        </Button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        {stats.map((stat, index) => (
          <Card key={index} className="glass-card border-0">
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">{stat.title}</CardTitle>
              <stat.icon className="w-5 h-5 text-primary" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{stat.value}</div>
            </CardContent>
          </Card>
        ))}
      </div>

      <Card className="glass-card border-0 animate-fade-in">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Activity className="w-5 h-5 text-primary" />
            Historico de Execucoes em Lote
          </CardTitle>
          <CardDescription>Acompanhe os lotes e controle o que ainda estiver em processamento.</CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-4">
              <Skeleton className="h-12 w-full" />
              <Skeleton className="h-12 w-full" />
              <Skeleton className="h-12 w-full" />
            </div>
          ) : error ? (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertTitle>Erro ao carregar</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          ) : allExecutions.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              <p>Nenhuma execucao em lote encontrada.</p>
            </div>
          ) : (
            <>
              <Accordion type="single" collapsible className="w-full">
                {paginatedExecutions.map((execution) => {
                  const groupedErrors = groupFailures(execution.items || []);
                  const hasErrors = Object.keys(groupedErrors).length > 0;
                  const controlState = isControlling[execution.id];

                  return (
                    <AccordionItem value={`item-${execution.id}`} key={execution.id}>
                      <AccordionTrigger>
                        <div className="flex flex-1 items-center justify-between pr-4 text-sm gap-4">
                          <SourceBadge source={execution.source} />
                          <Badge className={statusBadgeClassMap[execution.status] || "bg-slate-100 text-slate-700"}>
                            {statusLabelMap[execution.status] || execution.status}
                          </Badge>
                          <span>{formatDateTime(execution.start_time)}</span>
                          <div className="hidden md:flex gap-4">
                            <Badge variant="secondary">Total: {execution.total_items}</Badge>
                            <Badge className="bg-green-100 text-green-800">Sucessos: {execution.success_count}</Badge>
                            <Badge variant={execution.failure_count > 0 ? "destructive" : "outline"}>
                              Falhas: {execution.failure_count}
                            </Badge>
                          </div>
                        </div>
                      </AccordionTrigger>
                      <AccordionContent>
                        <div className="flex flex-wrap gap-3 mb-4">
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => handleControl(execution, "pause")}
                            disabled={!["PENDENTE", "PROCESSANDO"].includes(execution.status) || !!controlState}
                          >
                            {controlState === "pause" ? <Loader2 className="w-3 h-3 animate-spin mr-2" /> : <Pause className="w-3 h-3 mr-2" />}
                            Pausar
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => handleControl(execution, "resume")}
                            disabled={execution.status !== "PAUSADO" || !!controlState}
                          >
                            {controlState === "resume" ? <Loader2 className="w-3 h-3 animate-spin mr-2" /> : <Play className="w-3 h-3 mr-2" />}
                            Retomar
                          </Button>
                          <Button
                            size="sm"
                            variant="destructive"
                            onClick={() => handleControl(execution, "cancel")}
                            disabled={!["PENDENTE", "PROCESSANDO", "PAUSADO"].includes(execution.status) || !!controlState}
                          >
                            {controlState === "cancel" ? <Loader2 className="w-3 h-3 animate-spin mr-2" /> : <Square className="w-3 h-3 mr-2" />}
                            Cancelar
                          </Button>
                          <Button
                            size="sm"
                            variant="secondary"
                            onClick={() => handleControl(execution, "report")}
                            disabled={execution.failure_count === 0 || !!controlState}
                          >
                            {controlState === "report" ? <Loader2 className="w-3 h-3 animate-spin mr-2" /> : <Download className="w-3 h-3 mr-2" />}
                            Baixar Erros
                          </Button>
                        </div>

                        {hasErrors && (
                          <div className="mx-1 my-4 p-4 border border-red-200 bg-red-50/50 rounded-md">
                            <div className="flex items-center gap-2 mb-3 text-red-800">
                              <Filter className="w-4 h-4" />
                              <h4 className="font-semibold text-sm">Analise de Falhas</h4>
                            </div>

                            <div className="space-y-2">
                              {Object.entries(groupedErrors).map(([errorMsg, ids]) => (
                                <div
                                  key={errorMsg}
                                  className="flex flex-col sm:flex-row sm:items-center justify-between bg-white p-3 rounded border border-red-100 shadow-sm gap-3"
                                >
                                  <div className="flex items-start gap-3">
                                    <Badge variant="destructive" className="mt-0.5">{ids.length}</Badge>
                                    <span className="text-sm text-gray-700 font-medium break-all">{errorMsg}</span>
                                  </div>

                                  <Button
                                    size="sm"
                                    variant="outline"
                                    className="shrink-0 border-red-200 hover:bg-red-50 text-red-700 h-8"
                                    onClick={() => handleRetry(execution.id, ids)}
                                    disabled={isRetrying[execution.id]}
                                  >
                                    {isRetrying[execution.id] ? <Loader2 className="w-3 h-3 animate-spin mr-2" /> : <RefreshCw className="w-3 h-3 mr-2" />}
                                    Reprocessar Grupo
                                  </Button>
                                </div>
                              ))}
                            </div>

                            <div className="mt-4 pt-3 border-t border-red-200 flex justify-end">
                              <Button
                                variant="ghost"
                                size="sm"
                                className="text-muted-foreground hover:text-foreground text-xs"
                                onClick={() => handleRetry(execution.id, null)}
                                disabled={isRetrying[execution.id]}
                              >
                                Ou reprocessar todos os {execution.failure_count} itens com falha
                              </Button>
                            </div>
                          </div>
                        )}

                        <div className="p-2 bg-muted/30 rounded-md mt-4">
                          <Table>
                            <TableHeader>
                              <TableRow>
                                <TableHead className="w-[100px]">Status</TableHead>
                                <TableHead>CNJ</TableHead>
                                <TableHead>Task ID</TableHead>
                                <TableHead>Detalhe do Erro</TableHead>
                              </TableRow>
                            </TableHeader>
                            <TableBody>
                              {execution.items.map((item) => (
                                <TableRow key={item.id}>
                                  <TableCell>
                                    {item.status === "SUCESSO" ? (
                                      <CheckCircle2 className="h-5 w-5 text-green-500" />
                                    ) : item.status === "REPROCESSANDO" ? (
                                      <Loader2 className="h-5 w-5 text-blue-500 animate-spin" />
                                    ) : item.status === "PENDENTE" ? (
                                      <History className="h-5 w-5 text-slate-500" />
                                    ) : (
                                      <XCircle className="h-5 w-5 text-destructive" />
                                    )}
                                  </TableCell>
                                  <TableCell className="font-mono text-xs">{item.process_number}</TableCell>
                                  <TableCell>{item.created_task_id || "---"}</TableCell>
                                  <TableCell className="text-xs text-destructive max-w-[300px] truncate" title={item.error_message || ""}>
                                    {item.error_message || "---"}
                                  </TableCell>
                                </TableRow>
                              ))}
                            </TableBody>
                          </Table>
                        </div>
                      </AccordionContent>
                    </AccordionItem>
                  );
                })}
              </Accordion>

              {totalPages > 1 && (
                <Pagination className="mt-8">
                  <PaginationContent>
                    <PaginationItem>
                      <PaginationPrevious
                        href="#"
                        onClick={(e) => {
                          e.preventDefault();
                          handlePageChange(currentPage - 1);
                        }}
                        className={currentPage === 1 ? "pointer-events-none opacity-50" : ""}
                      />
                    </PaginationItem>
                    <PaginationItem>
                      <span className="px-4 py-2 text-sm font-medium">
                        Pagina {currentPage} de {totalPages}
                      </span>
                    </PaginationItem>
                    <PaginationItem>
                      <PaginationNext
                        href="#"
                        onClick={(e) => {
                          e.preventDefault();
                          handlePageChange(currentPage + 1);
                        }}
                        className={currentPage === totalPages ? "pointer-events-none opacity-50" : ""}
                      />
                    </PaginationItem>
                  </PaginationContent>
                </Pagination>
              )}
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
};

export default Dashboard;
