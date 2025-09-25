// frontend/src/components/TaskCreator.tsx

import { useState, useEffect } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { Plus, Target, Users, Calendar, FileText, Send, Trash2, Eye, AlertCircle, RefreshCw } from "lucide-react";
import { toast } from "@/hooks/use-toast";
import { Skeleton } from "@/components/ui/skeleton";

// --- INTERFACES ALINHADAS COM O BACKEND ---
interface TaskTemplate {
  id: number;
  name: string;
  description: string;
  estimated_time: string; // Snake case vindo da API
  fields: string[];
}

interface SquadMember {
    id: number;
    name: string;
    role: string;
}

interface SelectedSquad {
  id: number;
  name: string;
  members: SquadMember[];
}
// --- FIM DAS INTERFACES ---

interface TaskRequest {
  template: string;
  squads: string[];
  processes: string[];
  dueDate: string;
  priority: string;
  customFields: Record<string, string>;
}

const TaskCreator = () => {
  const [taskTemplates, setTaskTemplates] = useState<TaskTemplate[]>([]);
  const [availableSquads, setAvailableSquads] = useState<SelectedSquad[]>([]);
  
  const [isInitialLoading, setIsInitialLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [taskData, setTaskData] = useState<TaskRequest>({
    template: "",
    squads: [],
    processes: [],
    dueDate: "",
    priority: "medium",
    customFields: {}
  });

  const [processInput, setProcessInput] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [showPreview, setShowPreview] = useState(false);

  const fetchInitialData = async () => {
    try {
      setIsInitialLoading(true);
      setError(null);

      // Usamos Promise.all para buscar os dados em paralelo, melhorando a performance.
      const [templatesResponse, squadsResponse] = await Promise.all([
        fetch("/api/v1/task_templates"),
        fetch("/api/v1/squads")
      ]);

      if (!templatesResponse.ok || !squadsResponse.ok) {
        throw new Error("Falha ao buscar dados iniciais do servidor.");
      }

      const templates = await templatesResponse.json();
      const squads = await squadsResponse.json();

      setTaskTemplates(templates);
      setAvailableSquads(squads);

    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : "Ocorreu um erro desconhecido.";
      setError(errorMessage);
      toast({
        title: "Erro ao Carregar Dados",
        description: "Não foi possível buscar os templates e squads. Tente recarregar a página.",
        variant: "destructive"
      });
    } finally {
      setIsInitialLoading(false);
    }
  };

  useEffect(() => {
    fetchInitialData();
  }, []);

  const selectedTemplate = taskTemplates.find(t => t.id === Number(taskData.template));
  const selectedSquadObjects = availableSquads.filter(s => taskData.squads.includes(String(s.id)));

  const addProcess = () => {
    if (processInput.trim() && !taskData.processes.includes(processInput.trim())) {
      setTaskData(prev => ({ ...prev, processes: [...prev.processes, processInput.trim()] }));
      setProcessInput("");
    }
  };

  const removeProcess = (process: string) => {
    setTaskData(prev => ({ ...prev, processes: prev.processes.filter(p => p !== process) }));
  };

  const handleSquadToggle = (squadId: string) => {
    setTaskData(prev => ({
      ...prev,
      squads: prev.squads.includes(squadId)
        ? prev.squads.filter(id => id !== squadId)
        : [...prev.squads, squadId]
    }));
  };

  const handleCustomFieldChange = (field: string, value: string) => {
    setTaskData(prev => ({ ...prev, customFields: { ...prev.customFields, [field]: value } }));
  };

  const handleSubmit = async () => {
    if (!selectedTemplate || taskData.squads.length === 0 || taskData.processes.length === 0) {
      toast({
        title: "Dados incompletos",
        description: "Preencha todos os campos obrigatórios.",
        variant: "destructive"
      });
      return;
    }

    setIsSubmitting(true);
    
    // Simulação de chamada de API
    await new Promise(resolve => setTimeout(resolve, 3000));
    
    const totalTasks = taskData.processes.length * selectedSquadObjects.reduce((acc, squad) => acc + squad.members.length, 0);
    
    setIsSubmitting(false);
    toast({
      title: "Tarefas criadas com sucesso!",
      description: `${totalTasks} tarefas foram criadas no Legal One.`,
    });

    // Resetar o formulário
    setTaskData({
      template: "",
      squads: [],
      processes: [],
      dueDate: "",
      priority: "medium",
      customFields: {}
    });
    setShowPreview(false);
  };

  const getPriorityColor = (priority: string) => {
    switch (priority) {
      case 'high': return 'bg-red-100 text-red-800 border-red-200';
      case 'medium': return 'bg-yellow-100 text-yellow-800 border-yellow-200';
      case 'low': return 'bg-green-100 text-green-800 border-green-200';
      default: return 'bg-gray-100 text-gray-800 border-gray-200';
    }
  };
  
  if (error) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen bg-background text-center p-4">
        <AlertCircle className="w-16 h-16 text-destructive mb-4" />
        <h1 className="text-2xl font-bold mb-2">Ocorreu um Erro</h1>
        <p className="text-muted-foreground mb-6 max-w-md">{error}</p>
        <Button onClick={fetchInitialData}>
          <RefreshCw className="w-4 h-4 mr-2" />
          Tentar Novamente
        </Button>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-background via-muted/20 to-background">
      <div className="glass-card rounded-none border-x-0 border-t-0 mb-8 p-6">
        <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
          <div>
            <h1 className="text-3xl font-bold bg-gradient-to-r from-primary to-accent bg-clip-text text-transparent">
              Criação de Tarefas
            </h1>
            <p className="text-muted-foreground mt-1">
              Crie tarefas em lote para múltiplos processos e squads
            </p>
          </div>
          <div className="flex gap-3">
            <Button variant="outline" onClick={() => setShowPreview(!showPreview)}>
              <Eye className="w-4 h-4 mr-2" />
              {showPreview ? 'Ocultar' : 'Visualizar'} Resumo
            </Button>
          </div>
        </div>
      </div>

      <div className="container mx-auto px-6">
        <div className="grid lg:grid-cols-3 gap-8">
          <div className="lg:col-span-2 space-y-6">
            <Card className="glass-card border-0 animate-fade-in">
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Target className="w-5 h-5 text-primary" />
                  1. Selecionar Template
                </CardTitle>
                <CardDescription>
                  Escolha o tipo de tarefa que será criada
                </CardDescription>
              </CardHeader>
              <CardContent>
                {isInitialLoading ? (
                  <Skeleton className="h-10 w-full" />
                ) : (
                  <Select value={taskData.template} onValueChange={(value) => setTaskData(prev => ({ ...prev, template: value, customFields: {} }))}>
                    <SelectTrigger className="border-glass-border">
                      <SelectValue placeholder="Selecione um template de tarefa..." />
                    </SelectTrigger>
                    <SelectContent>
                      {taskTemplates.map(template => (
                        <SelectItem key={template.id} value={String(template.id)}>
                          <div className="flex flex-col">
                            <span className="font-medium">{template.name}</span>
                            <span className="text-xs text-muted-foreground">{template.description}</span>
                          </div>
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
                
                {selectedTemplate && (
                  <div className="mt-4 p-4 bg-muted/30 rounded-lg">
                    <div className="flex items-center justify-between mb-2">
                      <h4 className="font-medium">{selectedTemplate.name}</h4>
                      <Badge variant="secondary">{selectedTemplate.estimated_time}</Badge>
                    </div>
                    <p className="text-sm text-muted-foreground mb-3">{selectedTemplate.description}</p>
                    <div className="space-y-3">
                      {selectedTemplate.fields.map(field => (
                        <div key={field}>
                          <label className="text-sm font-medium mb-1 block">{field}</label>
                          <Input
                            placeholder={`Digite ${field.toLowerCase()}...`}
                            value={taskData.customFields[field] || ""}
                            onChange={(e) => handleCustomFieldChange(field, e.target.value)}
                            className="border-glass-border"
                          />
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>

            <Card className="glass-card border-0 animate-slide-up" style={{ animationDelay: '100ms' }}>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Users className="w-5 h-5 text-primary" />
                  2. Selecionar Squads
                </CardTitle>
                <CardDescription>
                  Escolha as equipes que receberão as tarefas
                </CardDescription>
              </CardHeader>
              <CardContent>
                {isInitialLoading ? (
                  <div className="space-y-3">
                    <Skeleton className="h-16 w-full" />
                    <Skeleton className="h-16 w-full" />
                  </div>
                ) : (
                  <div className="space-y-3">
                    {availableSquads.map(squad => (
                      <div key={squad.id} className="flex items-center space-x-3 p-3 rounded-lg bg-muted/30 hover:bg-muted/50 transition-colors">
                        <Checkbox
                          checked={taskData.squads.includes(String(squad.id))}
                          onCheckedChange={() => handleSquadToggle(String(squad.id))}
                        />
                        <div className="flex-1">
                          <div className="flex items-center justify-between">
                            <span className="font-medium">{squad.name}</span>
                            <Badge variant="secondary">{squad.members.length} membros</Badge>
                          </div>
                          <p className="text-xs text-muted-foreground mt-1">
                            {squad.members.map(m => m.name).join(', ')}
                          </p>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>

            <Card className="glass-card border-0 animate-slide-up" style={{ animationDelay: '200ms' }}>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <FileText className="w-5 h-5 text-primary" />
                  3. Números de Processo
                </CardTitle>
                <CardDescription>
                  Adicione os processos para os quais as tarefas serão criadas
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="flex gap-2 mb-4">
                  <Input
                    placeholder="Digite o número do processo..."
                    value={processInput}
                    onChange={(e) => setProcessInput(e.target.value)}
                    onKeyPress={(e) => e.key === 'Enter' && addProcess()}
                    className="border-glass-border"
                  />
                  <Button onClick={addProcess} variant="outline">
                    <Plus className="w-4 h-4" />
                  </Button>
                </div>
                {taskData.processes.length > 0 && (
                  <div className="space-y-2 max-h-40 overflow-y-auto">
                    {taskData.processes.map((process, index) => (
                      <div key={index} className="flex items-center justify-between p-2 bg-muted/30 rounded">
                        <span className="text-sm font-mono">{process}</span>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => removeProcess(process)}
                          className="h-6 w-6 p-0 hover:bg-destructive hover:text-destructive-foreground"
                        >
                          <Trash2 className="w-3 h-3" />
                        </Button>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>

            <Card className="glass-card border-0 animate-slide-up" style={{ animationDelay: '300ms' }}>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Calendar className="w-5 h-5 text-primary" />
                  4. Configurações Adicionais
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid md:grid-cols-2 gap-4">
                  <div>
                    <label className="text-sm font-medium mb-2 block">Data de Vencimento</label>
                    <Input
                      type="date"
                      value={taskData.dueDate}
                      onChange={(e) => setTaskData(prev => ({ ...prev, dueDate: e.target.value }))}
                      className="border-glass-border"
                    />
                  </div>
                  <div>
                    <label className="text-sm font-medium mb-2 block">Prioridade</label>
                    <Select value={taskData.priority} onValueChange={(value) => setTaskData(prev => ({ ...prev, priority: value }))}>
                      <SelectTrigger className="border-glass-border">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="low">Baixa</SelectItem>
                        <SelectItem value="medium">Média</SelectItem>
                        <SelectItem value="high">Alta</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>

          <div className="lg:col-span-1">
            <Card className={`glass-card border-0 sticky top-6 transition-all duration-300 ${showPreview ? 'animate-fade-in' : 'opacity-50'}`}>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Eye className="w-5 h-5 text-primary" />
                  Resumo da Criação
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                {selectedTemplate && (
                  <div>
                    <h4 className="font-medium mb-2">Template Selecionado</h4>
                    <Badge variant="secondary" className="w-full justify-center py-2">
                      {selectedTemplate.name}
                    </Badge>
                  </div>
                )}
                {taskData.squads.length > 0 && (
                  <div>
                    <h4 className="font-medium mb-2">Squads ({taskData.squads.length})</h4>
                    <div className="space-y-1">
                      {selectedSquadObjects.map(squad => (
                        <div key={squad.id} className="text-sm p-2 bg-muted/30 rounded">
                          {squad.name} <span className="text-muted-foreground">({squad.members.length} membros)</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                {taskData.processes.length > 0 && (
                  <div>
                    <h4 className="font-medium mb-2">Processos ({taskData.processes.length})</h4>
                    <div className="text-sm text-muted-foreground max-h-20 overflow-y-auto">
                      {taskData.processes.slice(0, 3).map((process, i) => (
                        <div key={i} className="font-mono">{process}</div>
                      ))}
                      {taskData.processes.length > 3 && (
                        <div className="text-xs">... e mais {taskData.processes.length - 3}</div>
                      )}
                    </div>
                  </div>
                )}
                <div className="space-y-2">
                  <div className="flex justify-between text-sm">
                    <span>Prioridade:</span>
                    <Badge className={`${getPriorityColor(taskData.priority)} border text-xs`}>
                      {taskData.priority === 'high' ? 'Alta' : taskData.priority === 'medium' ? 'Média' : 'Baixa'}
                    </Badge>
                  </div>
                  {taskData.dueDate && (
                    <div className="flex justify-between text-sm">
                      <span>Vencimento:</span>
                      <span className="text-muted-foreground">{new Date(taskData.dueDate).toLocaleDateString('pt-BR', { timeZone: 'UTC' })}</span>
                    </div>
                  )}
                </div>
                {selectedTemplate && taskData.squads.length > 0 && taskData.processes.length > 0 && (
                  <div className="pt-4 border-t border-glass-border">
                    <div className="text-center mb-4">
                      <div className="text-2xl font-bold text-primary">
                        {taskData.processes.length * selectedSquadObjects.reduce((acc, squad) => acc + squad.members.length, 0)}
                      </div>
                      <div className="text-sm text-muted-foreground">tarefas serão criadas</div>
                    </div>
                    <Button 
                      onClick={handleSubmit}
                      disabled={isSubmitting}
                      className="w-full glass-button border-0 text-white"
                    >
                      <Send className={`w-4 h-4 mr-2 ${isSubmitting ? 'animate-pulse' : ''}`} />
                      {isSubmitting ? 'Criando Tarefas...' : 'Criar Tarefas'}
                    </Button>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </div>
      </div>
    </div>
  );
};

export default TaskCreator;