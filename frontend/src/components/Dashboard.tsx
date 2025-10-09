// frontend/src/components/Dashboard.tsx

import { useState, useEffect } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
// --- 1. ADICIONAR NOVOS ÍCONES ---
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
    BrainCircuit 
} from "lucide-react";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

// Tipos corretos, que correspondem à sua API
import { BatchExecution } from "@/types/api";
import { fetchBatchExecutions } from "@/services/api";

// --- 2. NOVO COMPONENTE VISUAL PARA A FONTE ---
const SourceBadge = ({ source }: { source: string }) => {
    // Determina o ícone com base no nome da fonte, ignorando maiúsculas/minúsculas
    const isSpreadsheet = source.toLowerCase() === 'planilha';
    const Icon = isSpreadsheet ? FileUp : BrainCircuit;
    
    return (
      <div className="flex items-center gap-2 font-medium text-sm px-2.5 py-0.5 rounded-full border bg-background">
        <Icon className="h-4 w-4 text-muted-foreground" />
        <span>{source}</span>
      </div>
    );
};

const Dashboard = () => {
  const [executions, setExecutions] = useState<BatchExecution[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadData = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await fetchBatchExecutions();
      setExecutions(data);
    } catch (err) {
      setError("Não foi possível carregar o histórico de execuções. A API pode estar offline.");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const formatDateTime = (isoString: string | null) => {
    if (!isoString) return "N/A";
    const date = new Date(isoString);
    return new Intl.DateTimeFormat('pt-BR', {
        dateStyle: 'short',
        timeStyle: 'medium',
        timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone,
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
          ) : executions.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              <p>Nenhuma execução em lote encontrada.</p>
              <p className="text-sm">Envie uma requisição para a API ou uma planilha para começar.</p>
            </div>
          ) : (
            <Accordion type="single" collapsible className="w-full">
              {executions.map((exec) => (
                <AccordionItem value={`item-${exec.id}`} key={exec.id}>
                  <AccordionTrigger>
                    <div className="flex flex-1 items-center justify-between pr-4 text-sm">
                      {/* --- 3. SUBSTITUIÇÃO DO BADGE ANTIGO PELO NOVO COMPONENTE --- */}
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
          )}
        </CardContent>
      </Card>
    </div>
  );
};

export default Dashboard;