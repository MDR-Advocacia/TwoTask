// frontend/src/pages/AdminPage.tsx

import { useState, useEffect } from 'react';
import { useToast } from "@/hooks/use-toast";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Loader2, Save, Pencil } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogClose } from "@/components/ui/dialog";
import { MultiSelect } from "@/components/ui/MultiSelect";

// --- Tipos de Dados ---
interface Sector { id: number; name: string; }
interface Squad { id: number; name: string; }
interface TaskTypeGroup { parent_id: number; parent_name: string; sub_types: { id: number; name: string; squad_ids: number[]; }[]; }

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
        <Card>
            <CardHeader>
                <CardTitle>Associação de Tipos de Tarefa a Squads</CardTitle>
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

const AdminPage = () => {
    return (
        <div className="container mx-auto px-6 py-8">
            <div className="mb-8">
                <h1 className="text-3xl font-bold">Painel Administrativo</h1>
                <p className="text-muted-foreground mt-1">
                    Gerencie as configurações e associações do sistema.
                </p>
            </div>
            {/* Outros componentes administrativos podem ser adicionados aqui no futuro, em abas ou seções. */}
            <AssociateTasks />
        </div>
    )
}

export default AdminPage;