import { useState, useEffect } from 'react';
import { useToast } from "@/hooks/use-toast";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Loader2, AlertTriangle, Save, Search } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from '@/components/ui/textarea';

// --- Tipos de Dados ---

// Associação
interface Squad { id: number; name: string; }
interface SubType { id: number; name: string; squad_id: number | null; }
interface TaskTypeGroup { parent_id: number; parent_name: string; sub_types: SubType[]; }

// Criação
interface Lawsuit { id: number; identifierNumber: string; }
interface TaskType { id: number; name: string; }
interface TaskSubType { id: number; name: string; parentTypeId: number; }
interface LegalOneUser { id: number; external_id: number; name: string; email: string; }


// --- Componente para Associar Tarefas ---
const AssociateTasks = () => {
    const { toast } = useToast();
    const [taskGroups, setTaskGroups] = useState<TaskTypeGroup[]>([]);
    const [squads, setSquads] = useState<Squad[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [saving, setSaving] = useState(false);
    const [selectedSquads, setSelectedSquads] = useState<Record<number, string>>({});

    const fetchData = async () => {
        setLoading(true);
        try {
            const [tasksResponse, squadsResponse] = await Promise.all([
                fetch('/api/v1/admin/task-types'),
                fetch('/api/v1/squads'),
            ]);
            if (!tasksResponse.ok || !squadsResponse.ok) throw new Error('Falha ao carregar dados.');
            const tasksData = await tasksResponse.json();
            const squadsData = await squadsResponse.json();
            setTaskGroups(tasksData);
            setSquads(squadsData);
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => { fetchData(); }, []);

    const handleSaveChanges = async (groupId: number) => {
        const squadId = selectedSquads[groupId];
        const group = taskGroups.find(g => g.parent_id === groupId);
        if (!squadId || !group) return;
        setSaving(true);
        try {
            await fetch('/api/v1/admin/task-types/associate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ squad_id: parseInt(squadId), task_type_ids: group.sub_types.map(st => st.id) }),
            });
            toast({ title: "Sucesso!", description: "Associação salva." });
            fetchData();
        } catch (err) {
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
                <CardTitle>Associação em Lote</CardTitle>
                <CardDescription>Associe grupos de subtipos de tarefa a um squad específico.</CardDescription>
            </CardHeader>
            <CardContent>
                <Accordion type="single" collapsible className="w-full">
                    {taskGroups.map(group => (
                        <AccordionItem value={`item-${group.parent_id}`} key={group.parent_id}>
                            <AccordionTrigger>{group.parent_name}</AccordionTrigger>
                            <AccordionContent>
                                <div className="space-y-4">
                                    <div className="flex items-center gap-4 p-4 border rounded-lg">
                                        <div className="flex-grow">
                                            <Label htmlFor={`squad-select-${group.parent_id}`}>Associar grupo ao Squad:</Label>
                                            <Select value={selectedSquads[group.parent_id] || ""} onValueChange={(value) => setSelectedSquads(prev => ({ ...prev, [group.parent_id]: value }))}>
                                                <SelectTrigger id={`squad-select-${group.parent_id}`}><SelectValue placeholder="Selecione..." /></SelectTrigger>
                                                <SelectContent>{squads.map(squad => <SelectItem key={squad.id} value={String(squad.id)}>{squad.name}</SelectItem>)}</SelectContent>
                                            </Select>
                                        </div>
                                        <Button onClick={() => handleSaveChanges(group.parent_id)} disabled={saving || !selectedSquads[group.parent_id]}>
                                            <Save className="mr-2 h-4 w-4" />{saving ? "Salvando..." : "Salvar"}
                                        </Button>
                                    </div>
                                </div>
                            </AccordionContent>
                        </AccordionItem>
                    ))}
                </Accordion>
            </CardContent>
        </Card>
    );
};


// --- Componente para Criar Tarefas ---
const CreateTask = () => {
    const { toast } = useToast();
    const [cnj, setCnj] = useState('');
    const [isSearching, setIsSearching] = useState(false);
    const [foundLawsuit, setFoundLawsuit] = useState<Lawsuit | null>(null);
    const [searchError, setSearchError] = useState<string | null>(null);
    const [taskTypes, setTaskTypes] = useState<TaskType[]>([]);
    const [subTypes, setSubTypes] = useState<TaskSubType[]>([]);
    const [users, setUsers] = useState<LegalOneUser[]>([]);
    const [filteredSubTypes, setFilteredSubTypes] = useState<TaskSubType[]>([]);
    const [selectedTaskTypeId, setSelectedTaskTypeId] = useState<string>('');
    const [selectedSubTypeId, setSelectedSubTypeId] = useState<string>('');
    const [selectedResponsibleId, setSelectedResponsibleId] = useState<string>('');
    const [description, setDescription] = useState('');
    const [isSubmitting, setIsSubmitting] = useState(false);

    useEffect(() => {
        const fetchFormData = async () => {
            try {
                const [taskTypesResponse, usersResponse] = await Promise.all([
                    fetch('/api/v1/admin/task-types'),
                    fetch('/api/v1/squads/legal-one-users')
                ]);
                if (!taskTypesResponse.ok || !usersResponse.ok) throw new Error('Falha ao carregar dados para o formulário.');

                const taskTypeGroups = await taskTypesResponse.json();
                const usersData = await usersResponse.json();
                const allTypes = taskTypeGroups.map((g: any) => ({ id: g.parent_id, name: g.parent_name }));
                const allSubTypes = taskTypeGroups.flatMap((g: any) => g.sub_types.map((st: any) => ({ ...st, parentTypeId: g.parent_id })));

                setTaskTypes(allTypes);
                setSubTypes(allSubTypes);
                setUsers(usersData);
            } catch (error) {
                toast({ title: 'Erro ao carregar dados', description: error.message, variant: 'destructive' });
            }
        };
        fetchFormData();
    }, [toast]);

    useEffect(() => {
        if (selectedTaskTypeId) {
            setFilteredSubTypes(subTypes.filter(st => st.parentTypeId === parseInt(selectedTaskTypeId)));
            setSelectedSubTypeId('');
        } else {
            setFilteredSubTypes([]);
        }
    }, [selectedTaskTypeId, subTypes]);

    const handleSearch = async () => {
        if (!cnj.trim()) return;
        setIsSearching(true);
        setSearchError(null);
        setFoundLawsuit(null);
        try {
            const response = await fetch(`/api/v1/tasks/search-lawsuit?cnj=${encodeURIComponent(cnj)}`);
            if (!response.ok) throw new Error(response.status === 404 ? 'Nenhum processo encontrado com este CNJ.' : 'Falha ao buscar o processo.');
            const data: Lawsuit = await response.json();
            setFoundLawsuit(data);
            toast({ title: 'Processo Encontrado!', description: `ID: ${data.id}` });
        } catch (error) {
            setSearchError(error.message);
        } finally {
            setIsSearching(false);
        }
    };

    const handleSubmit = async () => {
        if (!foundLawsuit || !selectedSubTypeId || !selectedResponsibleId) return;
        setIsSubmitting(true);
        try {
            const response = await fetch('/api/v1/tasks/create-full-process', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    cnj_number: foundLawsuit.identifierNumber,
                    task_payload: {
                        subTypeId: parseInt(selectedSubTypeId),
                        description: description || 'Tarefa criada via sistema',
                        startDateTime: new Date().toISOString(),
                        priority: 'Normal',
                    },
                    participants: [{ contact_id: parseInt(selectedResponsibleId), is_responsible: true, is_executer: true }],
                }),
            });
            if (!response.ok) throw new Error((await response.json()).detail || 'Falha ao criar a tarefa.');
            const result = await response.json();
            toast({ title: 'Tarefa Criada com Sucesso!', description: `ID da Tarefa: ${result.created_task.id}` });
            setFoundLawsuit(null);
            setCnj('');
            setSelectedTaskTypeId('');
            setSelectedSubTypeId('');
            setSelectedResponsibleId('');
            setDescription('');
        } catch (error) {
            toast({ title: 'Erro ao Criar Tarefa', description: error.message, variant: 'destructive' });
        } finally {
            setIsSubmitting(false);
        }
    };

    return (
        <div className="space-y-4 mt-4">
            <Card>
                <CardHeader>
                    <CardTitle>1. Buscar Processo por CNJ</CardTitle>
                </CardHeader>
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
                            <Select value={selectedTaskTypeId} onValueChange={setSelectedTaskTypeId}><SelectTrigger><SelectValue placeholder="Selecione..." /></SelectTrigger><SelectContent>{taskTypes.map(t => <SelectItem key={t.id} value={String(t.id)}>{t.name}</SelectItem>)}</SelectContent></Select>
                        </div>
                        <div className="space-y-2">
                            <Label htmlFor="sub-type">Subtipo de Tarefa</Label>
                            <Select value={selectedSubTypeId} onValueChange={setSelectedSubTypeId} disabled={!selectedTaskTypeId}><SelectTrigger><SelectValue placeholder="Selecione..." /></SelectTrigger><SelectContent>{filteredSubTypes.map(st => <SelectItem key={st.id} value={String(st.id)}>{st.name}</SelectItem>)}</SelectContent></Select>
                        </div>
                        <div className="space-y-2">
                            <Label htmlFor="responsible">Responsável</Label>
                            <Select value={selectedResponsibleId} onValueChange={setSelectedResponsibleId}><SelectTrigger><SelectValue placeholder="Selecione..." /></SelectTrigger><SelectContent>{users.map(u => <SelectItem key={u.id} value={String(u.external_id)}>{u.name}</SelectItem>)}</SelectContent></Select>
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