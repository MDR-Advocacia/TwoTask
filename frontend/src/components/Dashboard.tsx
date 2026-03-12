import { useState, useEffect } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { 
    Users, 
    Target, 
    BarChart3, 
    Activity, 
    AlertCircle, 
    CheckCircle2, 
    XCircle, 
    RefreshCw,
    FileUp, 
    BrainCircuit,
    History,
    Webhook,
    Loader2,
    Filter // Icone novo para o filtro
} from "lucide-react";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Pagination,
  PaginationContent,
  PaginationItem,
  PaginationNext,
  PaginationPrevious,
} from "@/components/ui/pagination";
import { useToast } from "@/hooks/use-toast";

// Tipos e API
import { BatchExecution, BatchExecutionItem } from "@/types/api"; 
import { fetchBatchExecutions, retryBatchExecution } from "@/services/api"; 

// --- Mapas de Configuração ---
const sourceDisplayNames: { [key: string]: string } = {
    'planilha': 'Planilha',
    'onesid': 'Onesid', 
    'onerequest': 'Onerequest'
};

const sourceIcons: { [key: string]: React.ElementType } = {
    'planilha': FileUp,
    'onesid': BrainCircuit,
    'onerequest': Webhook,
    'default': History
};

const SourceBadge = ({ source }: { source: string }) => {
    const lowerSource = source.toLowerCase();
    const displayName = sourceDisplayNames[lowerSource] || source;
    const Icon = sourceIcons[lowerSource] || sourceIcons['default'];
    
    return (
      <Badge variant="outline" className="flex items-center gap-2">
        <Icon className="h-4 w-4" />
        <span>{displayName}</span>
      </Badge>
    );
};

// --- FUNÇÃO AUXILIAR PARA AGRUPAR ERROS ---
const groupFailures = (items: BatchExecutionItem[]) => {
    const failures = items.filter(item => item.status === "FALHA");
    
    return failures.reduce((acc, item) => {
        // Normaliza a mensagem para agrupar erros idênticos
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
  
  // Paginação
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
    } catch (err) {
      setError("Não foi possível carregar o histórico de execuções. A API pode estar offline.");
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
    currentPage * itemsPerPage
  );

  const handlePageChange = (page: number) => {
    if (page >= 1 && page <= totalPages) {
      setCurrentPage(page);
    }
  };

  // --- Lógica de Retry Atualizada (Suporta itemIds) ---
  const handleRetry = async (executionId: number, itemIds: number[] | null = null) => {
    setIsRetrying(prev => ({ ...prev, [executionId]: true }));
    try {
      // Chama o serviço passando a lista de IDs (se houver)
      // NOTA: Você precisará atualizar o arquivo services/api.ts para aceitar esse segundo argumento
      await retryBatchExecution(executionId, itemIds); 
      
      const msg = itemIds 
        ? `Reprocessamento iniciado para ${itemIds.length} itens.` 
        : `Reprocessamento total iniciado.`;

      toast({
        title: "Reprocessamento Iniciado",
        description: msg,
      });
      setTimeout(loadData, 2000); 
    } catch (err) {
      toast({
        title: "Erro ao Reprocessar",
        description: err instanceof Error ? err.message : "Tente novamente.",
        variant: "destructive",
      });
    } finally {
      setIsRetrying(prev => ({ ...prev, [executionId]: false }));
    }
  };

  const formatDateTime = (isoString: string | null) => {
    if (!isoString) return "N/A";
    let parsableString = isoString;
    const hasTimezone = isoString.endsWith('Z') || isoString.includes('+') || isoString.substring(10).includes('-');
    if (!hasTimezone) parsableString = isoString + 'Z';
    
    return new Intl.DateTimeFormat('pt-BR', {
        dateStyle: 'short',
        timeStyle: 'medium',
        timeZone: 'America/Sao_Paulo'
    }).format(new Date(parsableString));
  };

  const stats = [
    { title: "Execuções", value: allExecutions.length, icon: Activity },
    { title: "Total Itens", value: allExecutions.reduce((acc, curr) => acc + (curr.total_items || 0), 0), icon: Target },
    // Adicione mais stats reais conforme necessário
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
          <RefreshCw className={`w-4 h-4 mr-2 ${isLoading ? 'animate-spin' : ''}`} />
          Atualizar Dados
        </Button>
      </div>

      {/* Stats Cards simplificados para exemplo */}
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
            Histórico de Execuções em Lote
          </CardTitle>
          <CardDescription>
            Acompanhe as últimas criações de tarefas via API ou Planilha.
          </CardDescription>
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
              <AlertTitle>Erro ao Carregar</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          ) : allExecutions.length === 0 ? ( 
            <div className="text-center py-8 text-muted-foreground">
              <p>Nenhuma execução em lote encontrada.</p>
            </div>
          ) : (
            <>
              <Accordion type="single" collapsible className="w-full">
                {paginatedExecutions.map((exec) => {
                  // Agrupa erros para esta execução
                  const groupedErrors = groupFailures(exec.items || []);
                  const hasErrors = Object.keys(groupedErrors).length > 0;

                  return (
                  <AccordionItem value={`item-${exec.id}`} key={exec.id}>
                    <AccordionTrigger>
                      <div className="flex flex-1 items-center justify-between pr-4 text-sm">
                        <SourceBadge source={exec.source} />
                        <span>{formatDateTime(exec.start_time)}</span>
                        
                        <div className="hidden md:flex gap-4">
                          <Badge variant="secondary">Total: {exec.total_items}</Badge>
                          <Badge className="bg-green-100 text-green-800">Sucessos: {exec.success_count}</Badge>
                          <Badge variant={exec.failure_count > 0 ? "destructive" : "outline"}>
                            Falhas: {exec.failure_count}
                          </Badge>
                        </div>
                      </div>
                    </AccordionTrigger>
                    <AccordionContent>
                      
                      {/* --- PAINEL DE SMART RETRY --- */}
                      {hasErrors && (
                        <div className="mx-1 my-4 p-4 border border-red-200 bg-red-50/50 rounded-md">
                          <div className="flex items-center gap-2 mb-3 text-red-800">
                            <Filter className="w-4 h-4" />
                            <h4 className="font-semibold text-sm">Análise de Falhas (Smart Retry)</h4>
                          </div>
                          
                          <div className="space-y-2">
                            {Object.entries(groupedErrors).map(([errorMsg, ids]) => (
                              <div key={errorMsg} className="flex flex-col sm:flex-row sm:items-center justify-between bg-white p-3 rounded border border-red-100 shadow-sm gap-3">
                                <div className="flex items-start gap-3">
                                  <Badge variant="destructive" className="mt-0.5">{ids.length}</Badge>
                                  <span className="text-sm text-gray-700 font-medium break-all">{errorMsg}</span>
                                </div>
                                
                                <Button 
                                  size="sm" 
                                  variant="outline"
                                  className="shrink-0 border-red-200 hover:bg-red-50 text-red-700 h-8"
                                  onClick={() => handleRetry(exec.id, ids)}
                                  disabled={isRetrying[exec.id]}
                                >
                                  {isRetrying[exec.id] ? <Loader2 className="w-3 h-3 animate-spin mr-2" /> : <RefreshCw className="w-3 h-3 mr-2" />}
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
                                onClick={() => handleRetry(exec.id, null)} // Null = Tudo
                                disabled={isRetrying[exec.id]}
                             >
                               Ou reprocessar todos os {exec.failure_count} itens com falha
                             </Button>
                          </div>
                        </div>
                      )}

                      {/* --- Tabela de Itens --- */}
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
                            {exec.items.map((item) => (
                              <TableRow key={item.id}>
                                <TableCell>
                                  {item.status === "SUCESSO" ? (
                                    <CheckCircle2 className="h-5 w-5 text-green-500" />
                                  ) : item.status === "REPROCESSANDO" ? (
                                    <Loader2 className="h-5 w-5 text-blue-500 animate-spin" />
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
                )})}
              </Accordion>

              {/* Paginação */}
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
                          Página {currentPage} de {totalPages}
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