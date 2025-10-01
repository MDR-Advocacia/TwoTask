import { useState, useEffect, useMemo } from 'react';
import { useToast } from "@/hooks/use-toast";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Loader2, AlertTriangle, Save, Search, Pencil } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from '@/components/ui/textarea';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogClose } from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { MultiSelect } from "@/components/ui/MultiSelect";
import { Checkbox } from "@/components/ui/checkbox";
import UserSelector, { SelectableUser } from '@/components/ui/UserSelector';

// --- Tipos de Dados para Associação ---
interface Sector { id: number; name: string; }
interface Squad { id: number; name: string; }
interface TaskTypeGroup { parent_id: number; parent_name: string; sub_types: { id: number; name: string; squad_ids: number[]; }[]; }

// --- Tipos de Dados para Criação ---
interface Lawsuit {
  id: number;
  identifierNumber: string;
  responsibleOfficeId?: number;
}
interface Office {
  id: number;
  name: string;
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

// --- Componente para Associar Tarefas (Inalterado) ---
const AssociateTasks = () => {
    const { toast } = useToast();
    const [taskGroups, setTaskGroups] = useState<TaskTypeGroup[]>([]);
    const [sectors, setSectors] = useState<Sector[]>([]);
    const [squads, setSquads] = useState<Squad[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [saving, setSaving] = useState(false);
    const [selectedSector, setSelectedSector] = useState<string | null>(null);
    const [isEditDialogOpen, setIsEditDialogOpen] = useState(false);
    const [editingGroup, setEditingGroup] = useState<{ id: number; name: string } | null>(null);
    const [newGroupName, setNewGroupName] = useState("");
    const [selectedSquads, setSelectedSquads] = useState<Record<number, string[]>>({});

    const fetchInitialData = async () => {
        setLoading(true);
        setError(null);
        try {
            const [tasksResponse, sectorsResponse] = await Promise.all([
                fetch('/api/v1/admin/task-types'),
                fetch('/api/v1/sectors'),
            ]);
            if (!tasksResponse.ok || !sectorsResponse.ok) throw new Error('Falha ao carregar dados iniciais.');
            
            const tasksData = await tasksResponse.json();
            const sectorsData = await sectorsResponse.json();
            setTaskGroups(tasksData);
            setSectors(sectorsData);
            setSquads([]);

            const initialSelectedSquads: Record<number, string[]> = {};
            tasksData.forEach((group: TaskTypeGroup) => {
                const squadIdsInGroup = new Set<string>();
                group.sub_types.forEach(st => {
                    if (st.squad_ids) st.squad_ids.forEach(id => squadIdsInGroup.add(String(id)));
                });
                initialSelectedSquads[group.parent_id] = Array.from(squadIdsInGroup);
            });
            setSelectedSquads(initialSelectedSquads);
        } catch (err: any) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    };

    const fetchSquadsBySector = async (sectorId: string) => {
        try {
            const res = await fetch(`/api/v1/squads?sector_id=${sectorId}`);
            if (!res.ok) throw new Error('Falha ao buscar squads.');
            setSquads(await res.json());
        } catch (err: any) {
            toast({ title: "Erro ao Carregar Squads", description: err.message, variant: "destructive" });
        }
    };

    useEffect(() => { fetchInitialData(); }, []);
    useEffect(() => {
        if (selectedSector) {
            fetchSquadsBySector(selectedSector);
        } else {
            setSquads([]);
        }
    }, [selectedSector]);

    const handleEditClick = (group: { parent_id: number; parent_name: string }) => {
        setEditingGroup({ id: group.parent_id, name: group.parent_name });
        setNewGroupName(group.parent_name);
        setIsEditDialogOpen(true);
    };

    const handleRenameSave = async () => {
        if (!editingGroup || !newGroupName.trim()) return;
        try {
            const res = await fetch(`/api/v1/admin/task-parent-groups/${editingGroup.id}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: newGroupName.trim() }),
            });
            if (!res.ok) throw new Error((await res.json()).detail || "Falha ao renomear.");
            toast({ title: "Sucesso!", description: "Grupo renomeado." });
            setIsEditDialogOpen(false);
            fetchInitialData();
        } catch (err: any) {
            toast({ title: "Erro ao Renomear", description: err.message, variant: "destructive" });
        }
    };

    const handleSaveChanges = async (groupId: number) => {
        const squadIds = selectedSquads[groupId] || [];
        const group = taskGroups.find(g => g.parent_id === groupId);
        if (!group) return;
        setSaving(true);
        try {
            const res = await fetch('/api/v1/admin/task-types/associate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    squad_ids: squadIds.map(id => parseInt(id, 10)),
                    task_type_ids: group.sub_types.map(st => st.id),
                }),
            });
            if (!res.ok) throw new Error((await res.json()).detail || "Falha ao salvar.");
            toast({ title: "Sucesso!", description: "Associações salvas." });
            fetchInitialData();
        } catch (err: any) {
            toast({ title: "Erro ao Salvar", description: err.message, variant: "destructive" });
        } finally {
            setSaving(false);
        }
    };

    if (loading) return <div className="flex items-center justify-center h-64"><Loader2 className="h-8 w-8 animate-spin" /></div>;
    if (error) return <Alert variant="destructive"><AlertTitle>Erro</AlertTitle><AlertDescription>{error}</AlertDescription></Alert>;

    return (
        <Card className="mt-4">
            <CardHeader>
                <CardTitle>Associação de Tarefas a Squads</CardTitle>
                <CardDescription>Filtre por setor, depois associe grupos de tarefas a um ou mais squads.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
                <div className="w-full md:w-1/3">
                    <Label htmlFor="sector-select">1. Selecione um Setor</Label>
                    <Select onValueChange={setSelectedSector} value={selectedSector || ""}><SelectTrigger><SelectValue placeholder="Escolha um setor..." /></SelectTrigger><SelectContent>{sectors.map(s => <SelectItem key={s.id} value={String(s.id)}>{s.name}</SelectItem>)}</SelectContent></Select>
                </div>
                <div className="border-t pt-6">
                    <h3 className="text-lg font-medium mb-4">2. Associe os Grupos de Tarefas</h3>
                    <p className="text-sm text-muted-foreground mb-4">
                        Cada grupo de tarefas abaixo pode ser associado a um ou mais squads do setor selecionado. As associações são salvas por grupo.
                    </p>
                    <Accordion type="single" collapsible className="w-full">
                        {taskGroups.map(group => (
                            <AccordionItem value={`item-${group.parent_id}`} key={group.parent_id}>
                                <AccordionTrigger>
                                    <span className="flex-grow text-left">{group.parent_name}</span>
                                    <Button variant="ghost" size="icon" className="ml-4 h-8 w-8" onClick={(e) => { e.stopPropagation(); handleEditClick(group); }}><Pencil className="h-4 w-4" /></Button>
                                </AccordionTrigger>
                                <AccordionContent>
                                    <div className="space-y-4 p-2">
                                        <div className="flex flex-col md:flex-row items-start md:items-center gap-4 p-4 border rounded-lg">
                                            <div className="flex-grow w-full">
                                                <Label className={!selectedSector ? "text-muted-foreground" : ""}>Associar grupo aos Squads:</Label>
                                                <MultiSelect
                                                    options={squads.map(s => ({ label: s.name, value: String(s.id) }))}
                                                    defaultValue={selectedSquads[group.parent_id] || []}
                                                    onValueChange={(v) => setSelectedSquads(p => ({ ...p, [group.parent_id]: v }))}
                                                    placeholder={!selectedSector ? "Selecione um setor para carregar squads" : "Selecione squads..."}
                                                    disabled={!selectedSector || squads.length === 0}
                                                />
                                            </div>
                                            <Button onClick={() => handleSaveChanges(group.parent_id)} disabled={saving || !selectedSector}>
                                                <Save className="mr-2 h-4 w-4" />
                                                {saving ? "Salvando..." : "Salvar"}
                                            </Button>
                                        </div>
                                    </div>
                                </AccordionContent>
                            </AccordionItem>
                        ))}
                    </Accordion>
                </div>
            </CardContent>
            <Dialog open={isEditDialogOpen} onOpenChange={setIsEditDialogOpen}><DialogContent><DialogHeader><DialogTitle>Renomear Grupo</DialogTitle></DialogHeader><div className="py-4"><Label htmlFor="group-name">Novo nome para "{editingGroup?.name}"</Label><Input id="group-name" value={newGroupName} onChange={(e) => setNewGroupName(e.target.value)} className="mt-2" autoFocus /></div><DialogFooter><DialogClose asChild><Button type="button" variant="secondary">Cancelar</Button></DialogClose><Button type="button" onClick={handleRenameSave}>Salvar</Button></DialogFooter></DialogContent></Dialog>
        </Card>
    );
};


// --- Componente para Criar Tarefas (Versão Refatorada e Completa) ---
const CreateTask = () => {
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
      setSelectedResponsibleId('');
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
                <Label htmlFor="origin-office">Escritório de Responsável</Label>
                <Select value={selectedOriginOfficeId} onValueChange={setSelectedOriginOfficeId} disabled={offices.length === 0}><SelectTrigger id="origin-office"><SelectValue placeholder="Selecione o escritório..." /></SelectTrigger><SelectContent>{offices.map(office => (<SelectItem key={office.id} value={String(office.external_id)}>{office.name}</SelectItem>))}</SelectContent></Select>
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
  );
};

// --- Componente Principal com Abas ---
const TaskManager = () => {
    return (
        <Tabs defaultValue="create" className="w-full">
            <TabsList className="grid w-full grid-cols-2">
                <TabsTrigger value="create">Criar Nova Tarefa</TabsTrigger>
                <TabsTrigger value="associate">Associar Tarefas a Squads</TabsTrigger>
            </TabsList>
            <TabsContent value="create">
                <CreateTask />
            </TabsContent>
            <TabsContent value="associate">
                <AssociateTasks />
            </TabsContent>
        </Tabs>
    );
};

export default TaskManager;