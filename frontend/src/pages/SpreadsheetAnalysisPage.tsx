// frontend/src/pages/SpreadsheetAnalysisPage.tsx

import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useToast } from "@/hooks/use-toast";
import { Upload, File, AlertCircle, Loader2, Send, CheckCircle2, Archive, PlusCircle, XCircle, Briefcase, Undo2 } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from '@/components/ui/textarea';
import UserSelector, { SelectableUser } from '@/components/ui/UserSelector';
import { Separator } from '@/components/ui/separator';
import { cn } from '@/lib/utils';

// --- Interfaces ---
interface SpreadsheetRow {
    row_id: number;
    data: Record<string, any>;
}

interface AnalysisResponse {
    filename: string;
    headers: string[];
    rows: SpreadsheetRow[];
}

interface SubType { id: number; name: string; }
interface HierarchicalTaskType { id: number; name: string; sub_types: SubType[]; }

interface TaskFormData {
    taskId: string;
    rowId: number;
    selectedTaskTypeId: string;
    selectedSubTypeId: string;
    selectedResponsibleId: string | null;
    description: string;
    dueDate: string;
    dueTime: string;
    status: 'pending' | 'completed' | 'dismissed';
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
    const [tasksData, setTasksData] = useState<Record<number, TaskFormData[]>>({});

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
        const initialData: Record<number, TaskFormData[]> = {};
        rows.forEach(row => {
            initialData[row.row_id] = [{
                taskId: `task-${Date.now()}`,
                rowId: row.row_id,
                selectedTaskTypeId: '',
                selectedSubTypeId: '',
                selectedResponsibleId: null,
                description: '',
                dueDate: '',
                dueTime: '',
                status: 'pending',
            }];
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

    const handleTaskDataChange = (rowId: number, taskId: string, field: keyof Omit<TaskFormData, 'taskId' | 'rowId'>, value: any) => {
        setTasksData(prev => {
            const newTasks = prev[rowId].map(task => 
                task.taskId === taskId ? { ...task, [field]: value } : task
            );
            return { ...prev, [rowId]: newTasks };
        });
    };
    
    const handleConfirmPublication = async (rowId: number) => {
        const tasksToValidate = tasksData[rowId];
        const validationPayload = {
            tasks: tasksToValidate.map(task => ({
                selectedSubTypeId: task.selectedSubTypeId,
            })),
        };
    
        try {
            const response = await fetch('/api/v1/tasks/validate-publication-tasks', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(validationPayload),
            });
    
            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || "Ocorreu um erro de validação desconhecido.");
            }
    
            setTasksData(prev => ({
                ...prev,
                [rowId]: prev[rowId].map(task => ({ ...task, status: 'completed' }))
            }));
            toast({ 
                title: "Publicação Confirmada", 
                description: "As regras de negócio foram atendidas e as tarefas foram marcadas para agendamento.",
                className: "bg-green-100 border-green-300",
            });
    
        } catch (err) {
            const errorMessage = err instanceof Error ? err.message : "Erro inesperado.";
            toast({
                title: "Validação Falhou",
                description: errorMessage,
                variant: "destructive",
            });
        }
    };

    const markAsDismissed = (rowId: number) => {
        setTasksData(prev => ({
            ...prev,
            [rowId]: prev[rowId].map(task => ({ ...task, status: 'dismissed' }))
        }));
        toast({ title: "Publicação Dispensada", description: "Esta publicação não gerará tarefas." });
    }

    const handleUndoAction = (rowId: number) => {
        setTasksData(prev => ({
            ...prev,
            [rowId]: prev[rowId].map(task => ({ ...task, status: 'pending' }))
        }));
        toast({
            title: "Ação desfeita",
            description: "A publicação voltou ao estado pendente.",
        });
    };

    const handleAddTask = (rowId: number) => {
        setTasksData(prev => {
            const newTasks = [
                ...prev[rowId],
                {
                    taskId: `task-${Date.now()}-${prev[rowId].length}`,
                    rowId: rowId,
                    selectedTaskTypeId: '',
                    selectedSubTypeId: '',
                    selectedResponsibleId: null,
                    description: '',
                    dueDate: '',
                    dueTime: '',
                    status: 'pending',
                }
            ];
            return { ...prev, [rowId]: newTasks };
        });
    };

    const handleRemoveTask = (rowId: number, taskId: string) => {
        setTasksData(prev => ({
            ...prev,
            [rowId]: prev[rowId].filter(task => task.taskId !== taskId)
        }));
    };

    const handleSubmit = async () => {
        setIsSubmitting(true);
        const allTasks = Object.values(tasksData).flat();
        const completedTasks = allTasks
            .filter(task => task.status === 'completed')
            .map(task => {
                const originalRow = analysisResult?.rows.find(r => r.row_id === task.rowId);
                const user = users.find(u => u.id === Number(task.selectedResponsibleId));
                const publicationText = originalRow?.data['Andamentos / Descrição'] || '';
                const finalDescription = task.description 
                    ? `${publicationText}\n\n--- COMPLEMENTO ---\n${task.description}` 
                    : publicationText;
                return {
                    cnj_number: originalRow?.data['Nº do processo'] || '',
                    task_type_id: parseInt(task.selectedTaskTypeId, 10),
                    sub_type_id: parseInt(task.selectedSubTypeId, 10),
                    responsible_external_id: user?.external_id, 
                    description: finalDescription,
                    due_date: task.dueDate,
                    due_time: task.dueTime || null,
                };
            });
        
        if (completedTasks.some(t => !t.cnj_number || !t.responsible_external_id)) {
            toast({
                title: "Erro de Validação",
                description: "Uma ou mais tarefas concluídas não possuem um número de processo ou responsável válido.",
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
            const errorMessage = err instanceof Error ? err.message : "Erro inesperado.";
            toast({
                title: "Erro no Envio",
                description: errorMessage,
                variant: "destructive",
            });
        } finally {
            setIsSubmitting(false);
        }
    }

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
                    disabled={Object.values(tasksData).flat().filter(t => t.status === 'completed').length === 0 || isSubmitting}
                >
                    {isSubmitting ? ( <Loader2 className="w-4 h-4 mr-2 animate-spin" /> ) : ( <Send className="w-4 h-4 mr-2" /> )}
                    {isSubmitting ? 'Agendando...' : `Agendar Tarefas Concluídas (${Object.values(tasksData).flat().filter(t => t.status === 'completed').length})`}
                </Button>
            </div>
            <Accordion type="multiple" className="w-full space-y-4">
                {analysisResult.rows.map((row) => {
                    const tasks = tasksData[row.row_id] || [];
                    const firstTask = tasks[0];
                    if (!firstTask) return null;

                    const isDismissed = firstTask.status === 'dismissed';
                    const isCompleted = firstTask.status === 'completed';
                    const isAnyTaskFilled = tasks.some(t => t.selectedSubTypeId && t.selectedResponsibleId && t.dueDate);

                    return (
                        <AccordionItem 
                            value={`item-${row.row_id}`} 
                            key={row.row_id} 
                            className={`border rounded-lg transition-all ${isCompleted ? 'bg-green-50 border-green-200' : isDismissed ? 'bg-gray-100 border-gray-200 opacity-80' : 'bg-card'}`}
                        >
                            <AccordionTrigger className="px-6 text-left hover:no-underline">
                                <div className="flex items-center gap-4 w-full">
                                    <div className={cn("h-3 w-3 rounded-full flex-shrink-0", isCompleted ? "bg-green-500" : isDismissed ? "bg-gray-600" : "bg-blue-500")} />
                                    <span className="font-semibold text-sm">{row.data['Nº do processo'] || `Linha #${row.row_id}`}</span>
                                    <span className="truncate max-w-lg text-muted-foreground font-normal flex-1 text-left">
                                        {row.data['Andamentos / Descrição'] || 'Sem texto de publicação'}
                                    </span>
                                </div>
                            </AccordionTrigger>
                            <AccordionContent className="p-6 pt-0">
                                {isCompleted || isDismissed ? (
                                    // --- BLOCO PÓS-AÇÃO (NOVA LÓGICA) ---
                                    <div className="flex flex-col items-center justify-center text-center py-4">
                                        {isCompleted ? (
                                            <>
                                                <CheckCircle2 className="mx-auto h-8 w-8 mb-2 text-green-600" />
                                                <p className="font-semibold text-green-700">Publicação Confirmada</p>
                                                <p className='text-sm text-green-600'>As tarefas estão prontas para o agendamento final.</p>
                                            </>
                                        ) : (
                                            <>
                                                <Archive className="mx-auto h-8 w-8 mb-2 text-gray-600" />
                                                <p className="font-semibold text-gray-700">Publicação Dispensada</p>
                                                <p className='text-sm text-gray-600'>Esta publicação não irá gerar tarefas.</p>
                                            </>
                                        )}
                                        <Button 
                                            variant="outline" 
                                            size="sm" 
                                            className="mt-4" 
                                            onClick={() => handleUndoAction(row.row_id)}
                                        >
                                            <Undo2 className="w-4 h-4 mr-2" />
                                            Desfazer
                                        </Button>
                                    </div>
                                ) : (
                                    // --- BLOCO PRÉ-AÇÃO (LÓGICA EXISTENTE) ---
                                    <div className="space-y-6">
                                        <div className="space-y-4 pt-2">
                                            {row.data['Escritório responsável'] && (
                                                <div>
                                                    <Label className="text-xs text-muted-foreground">Escritório Responsável</Label>
                                                    <div className="flex items-center gap-2 text-sm font-semibold text-primary">
                                                        <Briefcase className="h-4 w-4" />
                                                        <span>{row.data['Escritório responsável']}</span>
                                                    </div>
                                                </div>
                                            )}
                                            <div>
                                                <Label className="text-xs text-muted-foreground">Texto da Publicação</Label>
                                                <p className="text-sm text-foreground p-3 bg-muted/50 rounded-md max-h-60 overflow-y-auto border">
                                                    {row.data['Andamentos / Descrição'] || 'N/A'}
                                                </p>
                                            </div>
                                        </div>

                                        {tasks.map((task, index) => {
                                            const parentType = taskTypes.find(t => t.id === parseInt(task.selectedTaskTypeId, 10));
                                            const subTypes = parentType ? parentType.sub_types : [];
                                            return (
                                                <div key={task.taskId} className={`p-4 border rounded-lg relative bg-background/20`}>
                                                    {tasks.length > 1 && (
                                                        <Button variant="ghost" size="icon" className="absolute top-2 right-2 h-6 w-6" onClick={() => handleRemoveTask(row.row_id, task.taskId)}>
                                                            <XCircle className="h-4 w-4 text-destructive" />
                                                        </Button>
                                                    )}
                                                    <h5 className="text-sm font-semibold mb-4 text-primary">Tarefa #{index + 1}</h5>
                                                    <div className="space-y-4">
                                                        <div className="grid md:grid-cols-2 gap-4">
                                                            <div className="space-y-2">
                                                                <Label>Tipo de Tarefa</Label>
                                                                <Select value={task.selectedTaskTypeId} onValueChange={(v) => handleTaskDataChange(row.row_id, task.taskId, 'selectedTaskTypeId', v)}><SelectTrigger><SelectValue placeholder="Selecione..." /></SelectTrigger><SelectContent>{taskTypes.map(t => <SelectItem key={t.id} value={String(t.id)}>{t.name}</SelectItem>)}</SelectContent></Select>
                                                            </div>
                                                            <div className="space-y-2">
                                                                <Label>Subtipo de Tarefa</Label>
                                                                <Select value={task.selectedSubTypeId} onValueChange={(v) => handleTaskDataChange(row.row_id, task.taskId, 'selectedSubTypeId', v)} disabled={!task.selectedTaskTypeId}><SelectTrigger><SelectValue placeholder="Selecione..." /></SelectTrigger><SelectContent>{subTypes.map(st => <SelectItem key={st.id} value={String(st.id)}>{st.name}</SelectItem>)}</SelectContent></Select>
                                                            </div>
                                                        </div>
                                                        <div className="space-y-2">
                                                            <Label>Responsável</Label>
                                                            <UserSelector users={users} value={task.selectedResponsibleId} onChange={(v) => handleTaskDataChange(row.row_id, task.taskId, 'selectedResponsibleId', v)} disabled={users.length === 0} />
                                                        </div>
                                                         <div className="space-y-2">
                                                            <Label>Descrição / Complemento</Label>
                                                            <Textarea placeholder="Adicione observações se necessário..." value={task.description} onChange={(e) => handleTaskDataChange(row.row_id, task.taskId, 'description', e.target.value)} />
                                                        </div>
                                                        <div className="grid grid-cols-2 gap-4">
                                                            <div className="space-y-2">
                                                                <Label>Data de Vencimento</Label>
                                                                <Input type="date" value={task.dueDate} onChange={(e) => handleTaskDataChange(row.row_id, task.taskId, 'dueDate', e.target.value)}/>
                                                            </div>
                                                            <div className="space-y-2">
                                                                <Label>Horário (Opcional)</Label>
                                                                <Input type="time" value={task.dueTime} onChange={(e) => handleTaskDataChange(row.row_id, task.taskId, 'dueTime', e.target.value)}/>
                                                            </div>
                                                        </div>
                                                    </div>
                                                </div>
                                            )
                                        })}
                                        <Separator />
                                        <div className="flex justify-between items-center pt-4">
                                            <Button variant="outline" onClick={() => handleAddTask(row.row_id)}>
                                                <PlusCircle className="w-4 h-4 mr-2" />
                                                Adicionar Tarefa
                                            </Button>
                                            <div className="flex items-center gap-2">
                                                <Button variant="ghost" size="sm" onClick={() => markAsDismissed(row.row_id)}>
                                                    <Archive className="w-4 h-4 mr-2"/>
                                                    Dispensar
                                                </Button>
                                                <Button 
                                                    onClick={() => handleConfirmPublication(row.row_id)} 
                                                    disabled={!isAnyTaskFilled}
                                                    className="bg-primary text-primary-foreground"
                                                >
                                                    <CheckCircle2 className="w-4 h-4 mr-2"/>
                                                    Confirmar e Marcar
                                                </Button>
                                            </div>
                                        </div>
                                    </div>
                                )}
                            </AccordionContent>
                        </AccordionItem>
                    )
                })}
            </Accordion>
        </div>
    );
};

export default SpreadsheetAnalysisPage;