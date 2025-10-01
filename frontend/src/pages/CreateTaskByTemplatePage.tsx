// frontend/src/pages/CreateTaskByTemplatePage.tsx

import { useState, useEffect, useMemo } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { Plus, Target, User, Calendar, FileText, Send, Trash2, Eye, AlertCircle, RefreshCw, Building } from "lucide-react";
import { toast } from "@/hooks/use-toast";
import { Skeleton } from "@/components/ui/skeleton";
import UserSelector, { SelectableUser } from "@/components/ui/UserSelector";
import { MultiSelect } from "@/components/ui/MultiSelect";

// --- INTERFACES ALINHADAS COM O BACKEND ---
interface Office {
  id: number;
  name: string;
  path: string;
}

interface TaskTemplate {
  id: number;
  name: string;
  description: string;
  estimated_time: string;
  fields: string[];
}

interface Squad {
  id: number;
  name: string;
}

interface LegalOneUser {
  id: number;
  external_id: number;
  name: string;
  is_active: boolean;
  squads: { id: number; name: string }[];
}
// --- FIM DAS INTERFACES ---

interface TaskRequest {
  officeId: string;
  template: string;
  responsibleId: string | null;
  processes: string[];
  dueDate: string;
  priority: string;
  customFields: Record<string, string>;
}

const CreateTaskByTemplatePage = () => {
  const [availableOffices, setAvailableOffices] = useState<Office[]>([]);
  const [taskTemplates, setTaskTemplates] = useState<TaskTemplate[]>([]);
  const [availableSquads, setAvailableSquads] = useState<Squad[]>([]);
  const [allUsers, setAllUsers] = useState<SelectableUser[]>([]);
  
  const [isInitialLoading, setIsInitialLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [taskData, setTaskData] = useState<TaskRequest>({
    officeId: "",
    template: "",
    responsibleId: null,
    processes: [],
    dueDate: "",
    priority: "medium",
    customFields: {},
  });

  const [selectedSquadIds, setSelectedSquadIds] = useState<string[]>([]);
  const [processInput, setProcessInput] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [showPreview, setShowPreview] = useState(true);

  const fetchInitialData = async () => {
    try {
      setIsInitialLoading(true);
      setError(null);

      const [officesResponse, templatesResponse, squadsResponse, usersResponse] = await Promise.all([
        fetch("/api/v1/offices/"),
        fetch("/api/v1/task_templates/"),
        fetch("/api/v1/squads/"),
        fetch("/api/v1/users/with-squads/"),
      ]);

      if (!officesResponse.ok || !templatesResponse.ok || !squadsResponse.ok || !usersResponse.ok) {
        throw new Error("Falha ao buscar dados iniciais do servidor.");
      }
      
      const offices = await officesResponse.json();
      const templates = await templatesResponse.json();
      const squads = await squadsResponse.json();
      const users: LegalOneUser[] = await usersResponse.json();

      setAvailableOffices(offices);
      setTaskTemplates(templates);
      setAvailableSquads(squads);
      
      const selectableUsers: SelectableUser[] = users.map(user => ({
        id: user.id,
        external_id: user.external_id,
        name: user.name,
        squads: user.squads,
      }));
      setAllUsers(selectableUsers);

    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : "Ocorreu um erro desconhecido.";
      setError(errorMessage);
      toast({
        title: "Erro ao Carregar Dados",
        description: "Não foi possível buscar os dados essenciais. Tente recarregar a página.",
        variant: "destructive",
      });
    } finally {
      setIsInitialLoading(false);
    }
  };

  useEffect(() => {
    fetchInitialData();
  }, []);
  
  const selectedOffice = availableOffices.find(o => o.id === Number(taskData.officeId));
  const selectedTemplate = taskTemplates.find(t => t.id === Number(taskData.template));
  const selectedUser = allUsers.find(u => String(u.external_id) === taskData.responsibleId);

  const addProcess = () => {
    if (processInput.trim() && !taskData.processes.includes(processInput.trim())) {
      setTaskData(prev => ({ ...prev, processes: [...prev.processes, processInput.trim()] }));
      setProcessInput("");
    }
  };

  const removeProcess = (process: string) => {
    setTaskData(prev => ({ ...prev, processes: prev.processes.filter(p => p !== process) }));
  };

  const handleCustomFieldChange = (field: string, value: string) => {
    setTaskData(prev => ({ ...prev, customFields: { ...prev.customFields, [field]: value } }));
  };

  const handleSubmit = async () => {
    if (!taskData.officeId || !selectedTemplate || !taskData.responsibleId || taskData.processes.length === 0) {
      toast({
        title: "Dados incompletos",
        description: "Preencha todos os campos obrigatórios: escritório, template, responsável e processos.",
        variant: "destructive",
      });
      return;
    }

    setIsSubmitting(true);
    
    await new Promise(resolve => setTimeout(resolve, 1500));
    
    const totalTasks = taskData.processes.length;
    
    setIsSubmitting(false);
    toast({
      title: "Tarefas criadas com sucesso!",
      description: `${totalTasks} tarefa(s) foram criadas para ${selectedUser?.name}.`,
    });

    setTaskData({
      officeId: "",
      template: "",
      responsibleId: null,
      processes: [],
      dueDate: "",
      priority: "medium",
      customFields: {},
    });
    setSelectedSquadIds([]);
    setShowPreview(true);
  };

  const getPriorityColor = (priority: string) => {
    switch (priority) {
      case 'high': return 'bg-red-100 text-red-800 border-red-200';
      case 'medium': return 'bg-yellow-100 text-yellow-800 border-yellow-200';
      case 'low': return 'bg-green-100 text-green-800 border-green-200';
      default: return 'bg-gray-100 text-gray-800 border-gray-200';
    }
  };

  const squadOptions = useMemo(() => {
    return availableSquads.map(s => ({ value: String(s.id), label: s.name }));
  }, [availableSquads]);
  
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
      <div className="container mx-auto px-6 py-8">
        <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 mb-8">
          <div>
            <h1 className="text-3xl font-bold bg-gradient-to-r from-primary to-accent bg-clip-text text-transparent">
              Criação de Tarefas em Lote
            </h1>
            <p className="text-muted-foreground mt-1">
              Crie uma ou mais tarefas para um único responsável a partir de um template.
            </p>
          </div>
          <div className="flex gap-3">
            <Button variant="outline" onClick={() => setShowPreview(!showPreview)}>
              <Eye className="w-4 h-4 mr-2" />
              {showPreview ? 'Ocultar' : 'Visualizar'} Resumo
            </Button>
          </div>
        </div>

        <div className="grid lg:grid-cols-3 gap-8">
          <div className="lg:col-span-2 space-y-6">
            
            <Card className="glass-card border-0 animate-fade-in">
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Building className="w-5 h-5 text-primary" />
                  1. Selecionar Escritório
                </CardTitle>
                <CardDescription>
                  Defina a qual unidade a tarefa pertence
                </CardDescription>
              </CardHeader>
              <CardContent>
                {isInitialLoading ? (
                  <Skeleton className="h-10 w-full" />
                ) : (
                  <Select value={taskData.officeId} onValueChange={(value) => setTaskData(prev => ({ ...prev, officeId: value }))}>
                    <SelectTrigger className="border-glass-border">
                      {selectedOffice ? selectedOffice.path : "Selecione um escritório..."}
                    </SelectTrigger>
                    <SelectContent>
                      {availableOffices.map(office => (
                        <SelectItem key={office.id} value={String(office.id)}>
                          <span className="font-medium">{office.path}</span>
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              </CardContent>
            </Card>

            <Card className="glass-card border-0 animate-fade-in">
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Target className="w-5 h-5 text-primary" />
                  2. Selecionar Template
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
                  <User className="w-5 h-5 text-primary" />
                  3. Selecionar Responsável
                </CardTitle>
                <CardDescription>
                  Filtre por squad e escolha o usuário que receberá a tarefa
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                 {isInitialLoading ? (
                  <div className="space-y-4">
                    <Skeleton className="h-10 w-full" />
                    <Skeleton className="h-10 w-full" />
                  </div>
                ) : (
                  <>
                    <div>
                      <label className="text-sm font-medium mb-2 block">Filtrar por Squad</label>
                      <MultiSelect
                        options={squadOptions}
                        onValueChange={setSelectedSquadIds}
                        defaultValue={selectedSquadIds}
                        placeholder="Selecione uma ou mais squads..."
                        className="bg-background"
                      />
                    </div>
                    <div>
                      <label className="text-sm font-medium mb-2 block">Responsável</label>
                      <UserSelector
                        users={allUsers}
                        value={taskData.responsibleId}
                        onChange={(value) => setTaskData(prev => ({...prev, responsibleId: value}))}
                        filterBySquadIds={selectedSquadIds.map(Number)}
                        placeholder="Selecione um responsável..."
                        disabled={isInitialLoading}
                      />
                    </div>
                  </>
                )}
              </CardContent>
            </Card>

            <Card className="glass-card border-0 animate-slide-up" style={{ animationDelay: '200ms' }}>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <FileText className="w-5 h-5 text-primary" />
                  4. Números de Processo
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
                  5. Configurações Adicionais
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
                {selectedOffice && (
                   <div>
                     <h4 className="font-medium mb-2">Escritório</h4>
                     <Badge variant="secondary" className="w-full justify-center py-2 text-center">
                       {selectedOffice.path}
                     </Badge>
                   </div>
                )}
                {selectedTemplate && (
                  <div>
                    <h4 className="font-medium mb-2">Template Selecionado</h4>
                    <Badge variant="secondary" className="w-full justify-center py-2">
                      {selectedTemplate.name}
                    </Badge>
                  </div>
                )}
                {selectedUser && (
                  <div>
                    <h4 className="font-medium mb-2">Responsável</h4>
                    <div className="text-sm p-2 bg-muted/30 rounded text-center">
                      <User className="inline-flex w-4 h-4 mr-2" />
                      {selectedUser.name}
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
                {selectedOffice && selectedTemplate && selectedUser && taskData.processes.length > 0 && (
                  <div className="pt-4 border-t border-glass-border">
                    <div className="text-center mb-4">
                      <div className="text-2xl font-bold text-primary">
                        {taskData.processes.length}
                      </div>
                      <div className="text-sm text-muted-foreground">
                        {taskData.processes.length === 1 ? "tarefa será criada" : "tarefas serão criadas"}
                      </div>
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

export default CreateTaskByTemplatePage;