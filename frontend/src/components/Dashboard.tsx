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
    Loader2 // <--- 1. ÍCONE ADICIONADO (estava faltando no seu original)
} from "lucide-react";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
// --- 2. IMPORTAR COMPONENTES DE PAGINAÇÃO ---
import {
  Pagination,
  PaginationContent,
  PaginationItem,
  PaginationLink,
  PaginationNext,
  PaginationPrevious,
} from "@/components/ui/pagination";
import { useToast } from "@/hooks/use-toast";

// Tipos e API
import { BatchExecution } from "@/types/api"; // Mantido o tipo original
import { fetchBatchExecutions, retryBatchExecution } from "@/services/api"; 

// --- Mapas de Configuração (Inalterado) ---
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

// --- Componente SourceBadge (Inalterado) ---
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

const Dashboard = () => {
  // --- 3. ESTADO PARA GUARDAR TODAS AS EXECUÇÕES ---
  const [allExecutions, setAllExecutions] = useState<BatchExecution[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isRetrying, setIsRetrying] = useState<Record<number, boolean>>({});
  
  // --- 4. ESTADOS DE PAGINAÇÃO (CLIENT-SIDE) ---
  const [currentPage, setCurrentPage] = useState(1);
  const itemsPerPage = 10; // Defina quantos itens por página

  const { toast } = useToast();

  // --- 5. loadData (BUSCA TUDO) ---
  const loadData = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await fetchBatchExecutions();
      setAllExecutions(data); // Armazena a lista completa
      setCurrentPage(1); // Reseta para a página 1
    } catch (err) {
      setError("Não foi possível carregar o histórico de execuções. A API pode estar offline.");
      setAllExecutions([]);
    } finally {
      setIsLoading(false);
    }
  };

  // --- 6. useEffect (CARREGA DADOS 1 VEZ) ---
  useEffect(() => {
    loadData();
  }, []); // Dependência vazia, carrega só no mount

  // --- 7. LÓGICA DE PAGINAÇÃO (CLIENT-SIDE) ---
  
  // Calcula o total de páginas com base na lista completa
  const totalPages = Math.ceil(allExecutions.length / itemsPerPage);

  // "Fatia" a lista completa para obter apenas os itens da página atual
  const paginatedExecutions = allExecutions.slice(
    (currentPage - 1) * itemsPerPage,
    currentPage * itemsPerPage
  );

  // Função para mudar de página (apenas altera o estado)
  const handlePageChange = (page: number) => {
    if (page >= 1 && page <= totalPages) {
      setCurrentPage(page);
    }
  };

  // --- Função handleRetry (Ajustada para recarregar tudo) ---
  const handleRetry = async (executionId: number) => {
    setIsRetrying(prev => ({ ...prev, [executionId]: true }));
    try {
      await retryBatchExecution(executionId);
      toast({
        title: "Reprocessamento Iniciado",
        description: `Um novo lote foi criado para processar as falhas do lote #${executionId}.`,
      });
      // Aguarda um pouco e atualiza a lista inteira (o novo lote deve aparecer)
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

    if (!hasTimezone) {
      parsableString = isoString + 'Z';
    }
    const date = new Date(parsableString);

    return new Intl.DateTimeFormat('pt-BR', {
        dateStyle: 'short',
        timeStyle: 'medium',
        timeZone: 'America/Sao_Paulo' // Força a exibição no fuso de Brasília
    }).format(date);
  };

  const stats = [
    { title: "Squads Ativos", value: "...", icon: Users },
    { title: "Tarefas Criadas (Mês)", value: "...", icon: Target },
    { title: "Taxa de Sucesso", value: "...", icon: BarChart3 },
    { title: "Tempo Médio", value: "...", icon: Activity },
  ];

  return (
    <div className="container mx-auto px-6 py-8 space-y-8">
      {/* --- Header e Stats Cards (Inalterados) --- */}
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
      {/* --- Fim do Header e Stats Cards --- */}

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
          // --- 8. USAR allExecutions PARA VERIFICAR SE ESTÁ VAZIO ---
          ) : allExecutions.length === 0 ? ( 
            <div className="text-center py-8 text-muted-foreground">
              <p>Nenhuma execução em lote encontrada.</p>
              <p className="text-sm">Envie uma requisição para a API ou uma planilha para começar.</p>
            </div>
          ) : (
            // --- 9. USAR FRAGMENT <> PARA AGRUPAR LISTA E PAGINAÇÃO ---
            <>
              {/* --- 10. MAPEAR SOBRE paginatedExecutions --- */}
              <Accordion type="single" collapsible className="w-full">
                {paginatedExecutions.map((exec) => ( 
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
                      {/* --- Bloco de Retry (Inalterado, mas agora com Loader2 funcionando) --- */}
                      {exec.failure_count > 0 && (
                        <div className="px-4 py-2 border-b">
                          <Button 
                              size="sm" 
                              variant="outline"
                              onClick={() => handleRetry(exec.id)}
                              disabled={isRetrying[exec.id]}
                          >
                            {isRetrying[exec.id] ? (
                                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                            ) : (
                                <History className="mr-2 h-4 w-4" />
                            )}
                            Reprocessar {exec.failure_count} Falha(s)
                          </Button>
                        </div>
                      )}
                      {/* --- Tabela de Itens (Inalterada) --- */}
                      <div className="p-2 bg-muted/30 rounded-md">
                        <Table>
                          <TableHeader>
                            <TableRow>
                              <TableHead className="w-[100px]">Status</TableHead>
                              <TableHead>Número do Processo</TableHead>
                              <TableHead>ID da Tarefa Criada</TableHead>
                              <TableHead>Detalhe do Erro</TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {exec.items.map((item) => (
                              <TableRow key={item.id}>
                                <TableCell>
                                  {item.status === "SUCESSO" ? (
                                    <CheckCircle2 className="h-5 w-5 text-green-500" />
                                  ) : (
                                    <XCircle className="h-5 w-5 text-destructive" />
                                  )}
                                </TableCell>
                                <TableCell className="font-mono">{item.process_number}</TableCell>
                                <TableCell>{item.created_task_id || "---"}</TableCell>
                                <TableCell className="text-xs text-destructive">{item.error_message || "---"}</TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                      </div>
                    </AccordionContent>
                  </AccordionItem>
                ))}
              </Accordion>

              {/* --- 11. ADICIONAR O COMPONENTE DE PAGINAÇÃO --- */}
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
                        // Desabilita o botão se estiver na primeira página
                        className={currentPage === 1 ? "pointer-events-none text-muted-foreground" : ""}
                      />
                    </PaginationItem>

                    {/* Mostra a contagem de páginas. É mais simples e robusto que gerar N links */}
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
                        // Desabilita o botão se estiver na última página
                        className={currentPage === totalPages ? "pointer-events-none text-muted-foreground" : ""}
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