import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useToast } from "@/hooks/use-toast";
import { Upload, File, AlertCircle, Loader2, ListTodo, Send, CheckCircle2 } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from '@/components/ui/textarea';
import UserSelector, { SelectableUser } from '@/components/ui/UserSelector';

// --- Interfaces para os dados ---
interface SpreadsheetRow {
  row_id: number;
  data: Record<string, any>;
}

interface AnalysisResponse {
  filename: string;
  headers: string[];
  rows: SpreadsheetRow[];
}

// Interfaces para os dados do formulário
interface SubType { id: number; name: string; }
interface HierarchicalTaskType { id: number; name: string; sub_types: SubType[]; }

// --- Interface para o estado de cada tarefa ---
interface TaskFormData {
  rowId: number;
  selectedTaskTypeId: string;
  selectedSubTypeId: string;
  selectedResponsibleId: string | null;
  description: string;
  dueDate: string;
  status: 'pending' | 'completed';
}

const SpreadsheetAnalysisPage = () => {
    const { toast } = useToast();
    const navigate = useNavigate();
    const [selectedFile, setSelectedFile] = useState<File | null>(null);
    const [isAnalyzing, setIsAnalyzing] = useState(false);
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [analysisResult, setAnalysisResult] = useState<AnalysisResponse | null>(null);
    const [isFormLoading, setIsFormLoading] = useState(true);
    const [taskTypes, setTaskTypes] = useState<HierarchicalTaskType[]>([]);
    const [users, setUsers] = useState<SelectableUser[]>([]);
    const [tasksData, setTasksData] = useState<Record<number, TaskFormData>>({});

    useEffect(() => {
        const fetchFormData = async () => {
          try {
            const taskDataResponse = await fetch('/api/v1/tasks/task-creation-data');
            if (!taskDataResponse.ok) throw new Error('Falha ao carregar os dados do formulário.');
            const data = await taskDataResponse.json();
            setTaskTypes(data.task_types);
            setUsers(data.users);
          } catch (error: any) {
            toast({ title: 'Erro ao Carregar Dados', description: error.message, variant: 'destructive' });
          } finally {
            setIsFormLoading(false);
          }
        };
        fetchFormData();
    }, [toast]);

    const initializeTasksData = (rows: SpreadsheetRow[]) => {
        const initialData: Record<number, TaskFormData> = {};
        rows.forEach(row => {
            initialData[row.row_id] = {
                rowId: row.row_id,
                selectedTaskTypeId: '',
                selectedSubTypeId: '',
                selectedResponsibleId: null,
                description: row.data['TEXTO_PUBLICACAO'] || '',
                dueDate: '',
                status: 'pending',
            };
        });
        setTasksData(initialData);
    };

    const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
        const file = event.target.files?.[0];
        if (file) {
          if (file.type === "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet") {
            setSelectedFile(file);
            setError(null);
            setAnalysisResult(null);
          } else {
            setError("Formato de arquivo inválido. Por favor, selecione um arquivo .xlsx.");
            setSelectedFile(null);
          }
        }
    };
    
    const handleAnalyze = async () => {
        if (!selectedFile) {
          setError("Nenhum arquivo selecionado.");
          return;
        }
        setIsAnalyzing(true);
        setError(null);
    
        const formData = new FormData();
        formData.append('file', selectedFile);
    
        try {
          const response = await fetch('/api/v1/tasks/analyze-spreadsheet', {
            method: 'POST',
            body: formData,
          });
    
          if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.detail || 'Ocorreu uma falha ao analisar o arquivo.');
          }
    
          const data: AnalysisResponse = await response.json();
          setAnalysisResult(data);
          initializeTasksData(data.rows);
          toast({
            title: "Análise Concluída!",
            description: `${data.rows.length} publicações prontas para agendamento.`,
          });
        } catch (err) {
            const errorMessage = err instanceof Error ? err.message : "Erro desconhecido.";
            setError(errorMessage);
            toast({
                title: "Erro na Análise",
                description: errorMessage,
                variant: "destructive",
            });
        } finally {
          setIsAnalyzing(false);
        }
    };

    const handleTaskDataChange = (rowId: number, field: keyof TaskFormData, value: any) => {
        setTasksData(prev => ({
            ...prev,
            [rowId]: {
                ...prev[rowId],
                [field]: value,
            }
        }));
    };

    const markAsCompleted = (rowId: number) => {
        handleTaskDataChange(rowId, 'status', 'completed');
        toast({
            title: "Publicação Concluída",
            description: "A tarefa para esta publicação foi marcada e será enviada.",
        });
    }

    const handleSubmit = async () => {
        setIsSubmitting(true);

        const completedTasks = Object.values(tasksData)
            .filter(task => task.status === 'completed')
            .map(task => {
                const originalRow = analysisResult?.rows.find(r => r.row_id === task.rowId);
                const user = users.find(u => u.id === Number(task.selectedResponsibleId));

                return {
                    cnj_number: originalRow?.data['NUMERO_PROCESSO'] || '',
                    task_type_id: parseInt(task.selectedTaskTypeId, 10),
                    sub_type_id: parseInt(task.selectedSubTypeId, 10),
                    responsible_external_id: user?.external_id, 
                    description: task.description,
                    due_date: task.dueDate,
                };
            });
        
        if (completedTasks.some(t => !t.cnj_number || !t.responsible_external_id)) {
            toast({
                title: "Erro de Validação",
                description: "Uma ou mais tarefas concluídas não possuem um número de processo ou responsável válido. Verifique os dados da planilha.",
                variant: "destructive",
            });
            setIsSubmitting(false);
            return;
        }

        const payload = {
            tasks: completedTasks,
            source_filename: analysisResult?.filename || 'N/A'
        };

        try {
            const response = await fetch('/api/v1/tasks/batch-create-interactive', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || "Falha ao enviar o lote de tarefas.");
            }
            
            toast({
                title: "Lote Enviado com Sucesso!",
                description: `${completedTasks.length} tarefas foram enviadas para agendamento em segundo plano.`,
                className: "bg-green-100 border-green-300",
            });

            setTimeout(() => navigate('/'), 1500);

        } catch (err) {
            const errorMessage = err instanceof Error ? err.message : "Erro desconhecido.";
            toast({
                title: "Erro no Envio",
                description: errorMessage,
                variant: "destructive",
            });
        } finally {
            setIsSubmitting(false);
        }
    };

    if (!analysisResult) {
        return (
            <div className="container mx-auto px-6 py-8">
              <div className="mb-8">
                <h1 className="text-3xl font-bold bg-gradient-to-r from-primary to-accent bg-clip-text text-transparent">
                  Agendamento Interativo por Planilha
                </h1>
                <p className="text-muted-foreground mt-1">
                  Faça o upload de um arquivo .xlsx para iniciar a análise e o agendamento de tarefas.
                </p>
              </div>
              
              <Card className="max-w-2xl mx-auto glass-card border-0 animate-fade-in">
                <CardHeader>
                  <CardTitle>1. Upload da Planilha</CardTitle>
                  <CardDescription>
                    Selecione o arquivo .xlsx contendo as publicações a serem analisadas.
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-6">
                  <div className="grid w-full items-center gap-1.5">
                    <Label htmlFor="spreadsheet-file">Arquivo Excel</Label>
                    <div className="flex items-center gap-3">
                      <Input
                        id="spreadsheet-file"
                        type="file"
                        accept=".xlsx"
                        onChange={handleFileChange}
                        className="file:text-primary file:font-medium"
                      />
                    </div>
                  </div>
        
                  {selectedFile && (
                    <div className="flex items-center p-3 rounded-md bg-muted/50">
                      <File className="w-5 h-5 mr-3 text-primary" />
                      <span className="text-sm font-medium">{selectedFile.name}</span>
                    </div>
                  )}
        
                  {error && (
                    <Alert variant="destructive">
                      <AlertCircle className="h-4 w-4" />
                      <AlertTitle>Erro</AlertTitle>
                      <AlertDescription>{error}</AlertDescription>
                    </Alert>
                  )}
        
                  <Button 
                    onClick={handleAnalyze} 
                    disabled={!selectedFile || isAnalyzing}
                    className="w-full glass-button text-white"
                  >
                    {isAnalyzing ? (
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    ) : (
                      <Upload className="mr-2 h-4 w-4" />
                    )}
                    {isAnalyzing ? 'Analisando...' : 'Analisar Planilha'}
                  </Button>
                </CardContent>
              </Card>
            </div>
          );
    }

    return (
        <div className="container mx-auto px-6 py-8">
             <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 mb-8">
                <div>
                    <h1 className="text-3xl font-bold">Análise de Publicações</h1>
                    <p className="text-muted-foreground mt-1">
                        Arquivo: <strong>{analysisResult.filename}</strong>. Preencha e confirme os agendamentos.
                    </p>
                </div>
                <Button 
                    size="lg" 
                    onClick={handleSubmit}
                    disabled={Object.values(tasksData).filter(t => t.status === 'completed').length === 0 || isSubmitting}
                >
                    {isSubmitting ? (
                        <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                    ) : (
                        <Send className="w-4 h-4 mr-2" />
                    )}
                    {isSubmitting ? 'Agendando...' : `Agendar Tarefas Concluídas (${Object.values(tasksData).filter(t => t.status === 'completed').length})`}
                </Button>
            </div>

            <Accordion type="multiple" className="w-full space-y-4">
                {analysisResult.rows.map((row) => {
                    const task = tasksData[row.row_id];
                    if (!task) return null;

                    const isCompleted = task.status === 'completed';
                    const parentType = taskTypes.find(t => t.id === parseInt(task.selectedTaskTypeId, 10));
                    const subTypes = parentType ? parentType.sub_types : [];

                    return (
                        <AccordionItem value={`item-${row.row_id}`} key={row.row_id} className={`border rounded-lg ${isCompleted ? 'bg-green-50 border-green-200' : 'bg-card'}`}>
                            <AccordionTrigger className="px-6 text-left hover:no-underline">
                                <div className="flex items-center gap-4">
                                    {isCompleted ? <CheckCircle2 className="h-5 w-5 text-green-600" /> : <ListTodo className="h-5 w-5 text-primary" />}
                                    <span className="font-mono text-sm">Linha #{row.row_id}</span>
                                    <span className="truncate max-w-md text-muted-foreground font-normal">
                                        {row.data['TEXTO_PUBLICACAO'] || 'Sem texto de publicação'}
                                    </span>
                                </div>
                            </AccordionTrigger>
                            <AccordionContent className="p-6 pt-0">
                                <div className="space-y-6">
                                    <div>
                                        <h4 className="font-medium mb-2">Texto da Publicação</h4>
                                        <p className="text-sm text-muted-foreground p-3 bg-muted/50 rounded-md max-h-40 overflow-y-auto">
                                            {row.data['TEXTO_PUBLICACAO'] || 'N/A'}
                                        </p>
                                    </div>

                                    <div className="grid md:grid-cols-2 gap-4">
                                        <div className="space-y-2">
                                            <Label>Tipo de Tarefa</Label>
                                            <Select value={task.selectedTaskTypeId} onValueChange={(v) => handleTaskDataChange(row.row_id, 'selectedTaskTypeId', v)}><SelectTrigger><SelectValue placeholder="Selecione..." /></SelectTrigger><SelectContent>{taskTypes.map(t => <SelectItem key={t.id} value={String(t.id)}>{t.name}</SelectItem>)}</SelectContent></Select>
                                        </div>
                                        <div className="space-y-2">
                                            <Label>Subtipo de Tarefa</Label>
                                            <Select value={task.selectedSubTypeId} onValueChange={(v) => handleTaskDataChange(row.row_id, 'selectedSubTypeId', v)} disabled={!task.selectedTaskTypeId}><SelectTrigger><SelectValue placeholder="Selecione..." /></SelectTrigger><SelectContent>{subTypes.map(st => <SelectItem key={st.id} value={String(st.id)}>{st.name}</SelectItem>)}</SelectContent></Select>
                                        </div>
                                    </div>
                                    <div className="space-y-2">
                                        <Label>Responsável</Label>
                                        <UserSelector users={users} value={task.selectedResponsibleId} onChange={(v) => handleTaskDataChange(row.row_id, 'selectedResponsibleId', v)} disabled={users.length === 0} />
                                    </div>
                                     <div className="space-y-2">
                                        <Label>Descrição / Complemento</Label>
                                        <Textarea placeholder="Adicione observações se necessário..." value={task.description} onChange={(e) => handleTaskDataChange(row.row_id, 'description', e.target.value)} />
                                    </div>
                                    <div className="space-y-2">
                                         <Label>Data de Vencimento</Label>
                                         <Input type="date" value={task.dueDate} onChange={(e) => handleTaskDataChange(row.row_id, 'dueDate', e.target.value)}/>
                                    </div>
                                    <div className="flex justify-end">
                                        <Button onClick={() => markAsCompleted(row.row_id)} disabled={!task.selectedSubTypeId || !task.selectedResponsibleId || !task.dueDate}>
                                            <CheckCircle2 className="w-4 h-4 mr-2"/>
                                            Concluir e Marcar para Agendamento
                                        </Button>
                                    </div>
                                </div>
                            </AccordionContent>
                        </AccordionItem>
                    )
                })}
            </Accordion>
        </div>
    );
};

export default SpreadsheetAnalysisPage;