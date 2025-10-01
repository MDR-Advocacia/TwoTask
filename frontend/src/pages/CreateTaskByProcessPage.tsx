// frontend/src/pages/CreateTaskByProcessPage.tsx

import { useState, useEffect, useMemo } from 'react';
import { useToast } from "@/hooks/use-toast";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Loader2, Search } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from '@/components/ui/textarea';
import { Checkbox } from "@/components/ui/checkbox";
import UserSelector, { SelectableUser } from '@/components/ui/UserSelector';

// --- Tipos de Dados ---
interface Lawsuit {
  id: number;
  identifierNumber: string;
  responsibleOfficeId?: number;
}
interface Office {
  id: number;
  name: string;
  path: string;
  external_id: number;
}
interface TaskType {
  id: number;
  name: string;
}
interface TaskSubType {
  id: number;
  name: string;
  parentTypeId: number;
  squad_ids: number[];
}

const CreateTaskByProcessPage = () => {
  const { toast } = useToast();
  const [cnj, setCnj] = useState('');
  const [isSearching, setIsSearching] = useState(false);
  const [foundLawsuit, setFoundLawsuit] = useState<Lawsuit | null>(null);
  const [searchError, setSearchError] = useState<string | null>(null);

  const [taskTypes, setTaskTypes] = useState<TaskType[]>([]);
  const [subTypes, setSubTypes] = useState<TaskSubType[]>([]);
  const [users, setUsers] = useState<SelectableUser[]>([]);
  const [offices, setOffices] = useState<Office[]>([]);
  const [isFormLoading, setIsFormLoading] = useState(true);

  const [selectedTaskTypeId, setSelectedTaskTypeId] = useState<string>('');
  const [selectedSubTypeId, setSelectedSubTypeId] = useState<string>('');
  const [selectedResponsibleId, setSelectedResponsibleId] = useState<string | null>(null);
  const [description, setDescription] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  const [selectedStatusId, setSelectedStatusId] = useState<string>('1');
  const [selectedOriginOfficeId, setSelectedOriginOfficeId] = useState<string>('');
  const [isResponsible, setIsResponsible] = useState(true);
  const [isExecuter, setIsExecuter] = useState(true);
  const [isRequester, setIsRequester] = useState(true);

  const [startDateTime, setStartDateTime] = useState(new Date());
  const [endDateTime, setEndDateTime] = useState(() => {
    const date = new Date();
    date.setHours(date.getHours() + 24);
    return date;
  });

  useEffect(() => {
    const fetchFormData = async () => {
      setIsFormLoading(true);
      try {
        const [taskDataResponse, officesResponse] = await Promise.all([
          fetch('/api/v1/tasks/task-creation-data'),
          fetch('/api/v1/offices')
        ]);
        if (!taskDataResponse.ok || !officesResponse.ok) {
          throw new Error('Falha ao carregar os dados do formulário.');
        }
        const taskData = await taskDataResponse.json();
        const officesData = await officesResponse.json();
        setTaskTypes(taskData.task_types);
        setSubTypes(taskData.sub_types);
        setUsers(taskData.users);
        setOffices(officesData);
      } catch (error: any) {
        toast({ title: 'Erro ao Carregar Dados', description: error.message, variant: 'destructive' });
      } finally {
        setIsFormLoading(false);
      }
    };
    fetchFormData();
  }, [toast]);

  const selectedOffice = useMemo(() => 
    offices.find(o => o.id === parseInt(selectedOriginOfficeId, 10)),
    [offices, selectedOriginOfficeId]
  );

  const filteredSubTypes = useMemo(() => {
    if (!selectedTaskTypeId) return [];
    return subTypes.filter(st => st.parentTypeId === parseInt(selectedTaskTypeId, 10));
  }, [selectedTaskTypeId, subTypes]);

  const squadIdsForFilter = useMemo(() => {
    if (!selectedSubTypeId) return [];
    const selectedSubType = subTypes.find(st => st.id === parseInt(selectedSubTypeId, 10));
    return selectedSubType?.squad_ids || [];
  }, [selectedSubTypeId, subTypes]);

  useEffect(() => {
    setSelectedSubTypeId('');
    setSelectedResponsibleId(null);
  }, [selectedTaskTypeId]);

  useEffect(() => {
    setSelectedResponsibleId(null);
  }, [selectedSubTypeId]);

  useEffect(() => {
    if (startDateTime) {
      const newEndDateTime = new Date(startDateTime.getTime());
      newEndDateTime.setHours(newEndDateTime.getHours() + 24);
      setEndDateTime(newEndDateTime);
    }
  }, [startDateTime]);

  const handleSubmit = async () => {
    if (!foundLawsuit || !selectedSubTypeId || !selectedResponsibleId || !selectedOriginOfficeId) {
      toast({ title: 'Campos Obrigatórios', description: 'Tipo, subtipo, responsável e escritório de origem são obrigatórios.', variant: 'destructive' });
      return;
    }
    if (endDateTime <= startDateTime) {
      toast({ title: 'Data Inválida', description: 'A data de fim deve ser posterior à data de início.', variant: 'destructive' });
      return;
    }
    if (!foundLawsuit.responsibleOfficeId) {
      toast({ title: 'Erro de Dados', description: 'O ID do escritório responsável do processo não foi encontrado.', variant: 'destructive' });
      return;
    }
    setIsSubmitting(true);
    const selectedSubType = subTypes.find(st => st.id === parseInt(selectedSubTypeId, 10));
    if (!selectedSubType) {
      toast({ title: 'Erro Interno', description: 'Subtipo de tarefa não encontrado.', variant: 'destructive' });
      setIsSubmitting(false);
      return;
    }

    const task_payload = {
      subTypeId: parseInt(selectedSubTypeId, 10),
      description: description || 'Tarefa criada via sistema',
      priority: 'Normal',
      typeId: selectedSubType.parentTypeId,
      startDateTime: startDateTime.toISOString(),
      endDateTime: endDateTime.toISOString(),
      status: { id: parseInt(selectedStatusId, 10) },
      originOfficeId: parseInt(selectedOriginOfficeId, 10),
      responsibleOfficeId: foundLawsuit.responsibleOfficeId,
    };

    const requestBody = {
      cnj_number: foundLawsuit.identifierNumber,
      task_payload,
      participants: [{
          contact_id: parseInt(selectedResponsibleId, 10),
          is_responsible: isResponsible,
          is_executer: isExecuter,
          is_requester: isRequester,
      }],
    };

    try {
      const response = await fetch('/api/v1/tasks/create-full-process', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(requestBody),
      });
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Falha ao criar a tarefa.');
      }
      const result = await response.json();
      toast({
        title: 'Tarefa Criada com Sucesso!',
        description: `A tarefa ID ${result.created_task.id} foi criada e vinculada ao processo.`,
      });
      setFoundLawsuit(null);
      setCnj('');
      setSelectedTaskTypeId('');
      setSelectedSubTypeId('');
      setSelectedResponsibleId(null);
      setDescription('');
      setSelectedStatusId('1');
      setSelectedOriginOfficeId('');
      setIsResponsible(true);
      setIsExecuter(true);
      setIsRequester(true);
    } catch (error: any) {
      toast({ title: 'Erro ao Criar Tarefa', description: error.message, variant: 'destructive' });
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleSearch = async () => {
    if (!cnj.trim()) {
      toast({ title: 'CNJ Inválido', description: 'Por favor, insira um número de CNJ.', variant: 'destructive' });
      return;
    }
    setIsSearching(true);
    setSearchError(null);
    setFoundLawsuit(null);
    try {
      const response = await fetch(`/api/v1/tasks/search-lawsuit?cnj=${encodeURIComponent(cnj)}`);
      if (!response.ok) {
        if (response.status === 404) throw new Error('Nenhum processo encontrado com este CNJ.');
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Falha ao buscar o processo.');
      }
      const data: Lawsuit = await response.json();
      setFoundLawsuit(data);
      toast({ title: 'Processo Encontrado!', description: `ID do Processo: ${data.id}` });
    } catch (error: any) {
      setSearchError(error.message);
      toast({ title: 'Erro na Busca', description: error.message, variant: 'destructive' });
    } finally {
      setIsSearching(false);
    }
  };

  return (
    <div className="container mx-auto px-6 py-8">
       <div className="mb-8">
        <h1 className="text-3xl font-bold bg-gradient-to-r from-primary to-accent bg-clip-text text-transparent">
          Criação de Tarefa por Processo
        </h1>
        <p className="text-muted-foreground mt-1">
          Busque um processo por CNJ para criar uma nova tarefa vinculada.
        </p>
      </div>
      <div className="space-y-4 mt-4">
        <Card>
          <CardHeader><CardTitle>1. Buscar Processo por CNJ</CardTitle></CardHeader>
          <CardContent>
            <div className="flex items-center gap-2">
              <Input placeholder="0000000-00.0000.0.00.0000" value={cnj} onChange={(e) => setCnj(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && handleSearch()} disabled={isSearching} />
              <Button onClick={handleSearch} disabled={isSearching || !cnj.trim()}>
                {isSearching ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}<span className="ml-2">Buscar</span>
              </Button>
            </div>
            {searchError && <p className="text-red-500 text-sm mt-2">{searchError}</p>}
          </CardContent>
        </Card>
        {foundLawsuit && (
          <Card>
            <CardHeader>
              <CardTitle>2. Detalhes da Nova Tarefa</CardTitle>
              <CardDescription>Para o processo: <strong>{foundLawsuit.identifierNumber}</strong></CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="task-type">Tipo de Tarefa</Label>
                <Select value={selectedTaskTypeId} onValueChange={setSelectedTaskTypeId}><SelectTrigger id="task-type"><SelectValue placeholder="Selecione o tipo..." /></SelectTrigger><SelectContent>{taskTypes.map(type => (<SelectItem key={type.id} value={String(type.id)}>{type.name}</SelectItem>))}</SelectContent></Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="sub-type">Subtipo de Tarefa</Label>
                <Select value={selectedSubTypeId} onValueChange={setSelectedSubTypeId} disabled={!selectedTaskTypeId}><SelectTrigger id="sub-type"><SelectValue placeholder="Selecione o subtipo..." /></SelectTrigger><SelectContent>{filteredSubTypes.map(subType => (<SelectItem key={subType.id} value={String(subType.id)}>{subType.name}</SelectItem>))}</SelectContent></Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="responsible">Responsável</Label>
                <UserSelector users={users} value={selectedResponsibleId} onChange={setSelectedResponsibleId} filterBySquadIds={squadIdsForFilter} disabled={!selectedSubTypeId || users.length === 0} />
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="origin-office">Escritório de Origem</Label>
                  <Select value={selectedOriginOfficeId} onValueChange={setSelectedOriginOfficeId} disabled={offices.length === 0}>
                    <SelectTrigger id="origin-office">
                      {selectedOffice ? selectedOffice.path : "Selecione o escritório..."}
                    </SelectTrigger>
                    <SelectContent>
                      {offices.map(office => (
                        <SelectItem key={office.id} value={String(office.id)}>
                          {office.path}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="task-status">Status</Label>
                  <Select value={selectedStatusId} onValueChange={setSelectedStatusId}><SelectTrigger id="task-status"><SelectValue placeholder="Selecione o status..." /></SelectTrigger><SelectContent><SelectItem value="1">Aberta</SelectItem><SelectItem value="2">Em Andamento</SelectItem><SelectItem value="3">Pendente</SelectItem><SelectItem value="4">Concluída</SelectItem><SelectItem value="5">Cancelada</SelectItem></SelectContent></Select>
                </div>
              </div>
              <div className="space-y-2 pt-2">
                <Label>Papéis do Usuário na Tarefa</Label>
                <div className="flex items-center space-x-6 pt-2">
                  <div className="flex items-center space-x-2"><Checkbox id="isResponsible" checked={isResponsible} onCheckedChange={(checked) => setIsResponsible(Boolean(checked))} /><Label htmlFor="isResponsible" className="font-normal leading-none">Responsável</Label></div>
                  <div className="flex items-center space-x-2"><Checkbox id="isExecuter" checked={isExecuter} onCheckedChange={(checked) => setIsExecuter(Boolean(checked))} /><Label htmlFor="isExecuter" className="font-normal leading-none">Executor</Label></div>
                  <div className="flex items-center space-x-2"><Checkbox id="isRequester" checked={isRequester} onCheckedChange={(checked) => setIsRequester(Boolean(checked))} /><Label htmlFor="isRequester" className="font-normal leading-none">Solicitante</Label></div>
                </div>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="start-datetime">Data e Hora de Início</Label>
                  <Input id="start-datetime" type="datetime-local" value={startDateTime.toISOString().slice(0, 16)} onChange={(e) => setStartDateTime(new Date(e.target.value))} />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="end-datetime">Data e Hora de Fim</Label>
                  <Input id="end-datetime" type="datetime-local" value={endDateTime.toISOString().slice(0, 16)} onChange={(e) => setEndDateTime(new Date(e.target.value))} />
                </div>
              </div>
              <div className="space-y-2">
                <Label htmlFor="description">Descrição</Label>
                <Textarea id="description" placeholder="Insira a descrição da tarefa..." value={description} onChange={(e) => setDescription(e.target.value)} />
              </div>
              <div className="flex justify-end">
                <Button onClick={handleSubmit} disabled={isSubmitting || !selectedSubTypeId || !selectedResponsibleId}>
                  {isSubmitting ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : null}Criar Tarefa
                </Button>
              </div>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
};

export default CreateTaskByProcessPage;