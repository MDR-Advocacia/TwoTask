import { useState, useEffect } from 'react';
import { useToast } from "@/hooks/use-toast";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogClose } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Loader2, AlertTriangle, Save, Pencil } from "lucide-react";

// Definição de tipos para os dados da API
interface Sector {
  id: number;
  name: string;
}

interface Squad {
  id: number;
  name: string;
}

import { MultiSelect } from "@/components/ui/MultiSelect";

interface SubType {
  id: number;
  name: string;
  squad_ids: number[];
}

interface TaskTypeGroup {
  parent_id: number;
  parent_name: string;
  sub_types: SubType[];
}

interface TaskManagerProps {
  syncCounter: number;
}

const TaskManager: React.FC<TaskManagerProps> = ({ syncCounter }) => {
  const { toast } = useToast();
  const [taskGroups, setTaskGroups] = useState<TaskTypeGroup[]>([]);
  const [sectors, setSectors] = useState<Sector[]>([]);
  const [squads, setSquads] = useState<Squad[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // State for selected sector
  const [selectedSector, setSelectedSector] = useState<string | null>(null);

  // State for the rename dialog
  const [isEditDialogOpen, setIsEditDialogOpen] = useState(false);
  const [editingGroup, setEditingGroup] = useState<{ id: number; name: string } | null>(null);
  const [newGroupName, setNewGroupName] = useState("");

  // Mapeamento local para os squads selecionados por grupo
  const [selectedSquads, setSelectedSquads] = useState<Record<number, string[]>>({});

  const handleEditClick = (group: { parent_id: number; parent_name: string }) => {
    setEditingGroup({ id: group.parent_id, name: group.parent_name });
    setNewGroupName(group.parent_name);
    setIsEditDialogOpen(true);
  };

  const handleRenameSave = async () => {
    if (!editingGroup || !newGroupName.trim()) {
      toast({ title: "Nome inválido", description: "O nome do grupo não pode ser vazio.", variant: "destructive" });
      return;
    }

    try {
      const response = await fetch(`/api/v1/admin/task-parent-groups/${editingGroup.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: newGroupName.trim() }),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || "Falha ao renomear o grupo.");
      }

      toast({
        title: "Sucesso!",
        description: `Grupo renomeado para "${newGroupName.trim()}".`,
      });
      setIsEditDialogOpen(false);
      fetchInitialData(); // Refresh data to show the new name
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : "Erro desconhecido";
      toast({
        title: "Erro ao Renomear",
        description: errorMessage,
        variant: "destructive",
      });
    }
  };

  const fetchInitialData = async () => {
    setLoading(true);
    setError(null);
    try {
      const [tasksResponse, sectorsResponse] = await Promise.all([
        fetch('/api/v1/admin/task-types'),
        fetch('/api/v1/sectors'),
      ]);

      if (!tasksResponse.ok) throw new Error('Falha ao buscar os tipos de tarefa.');
      if (!sectorsResponse.ok) throw new Error('Falha ao buscar os setores.');

      const tasksData = await tasksResponse.json();
      const sectorsData = await sectorsResponse.json();

      setTaskGroups(tasksData);
      setSectors(sectorsData);
      setSquads([]); // Squads will be loaded based on sector selection

      // Inicializa o estado dos squads selecionados com base nos dados recebidos
      const initialSelectedSquads: Record<number, string[]> = {};
      tasksData.forEach((group: TaskTypeGroup) => {
        // Coleta todos os IDs de squad únicos de todos os subtipos do grupo
        const squadIdsInGroup = new Set<string>();
        group.sub_types.forEach(st => {
          // Adiciona a verificação de segurança aqui
          if (st.squad_ids) {
            st.squad_ids.forEach(id => squadIdsInGroup.add(String(id)));
          }
        });
        initialSelectedSquads[group.parent_id] = Array.from(squadIdsInGroup);
      });
      setSelectedSquads(initialSelectedSquads);

    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : "Erro desconhecido";
      setError(errorMessage);
      toast({
        title: "Erro ao Carregar Dados Iniciais",
        description: errorMessage,
        variant: "destructive",
      });
    } finally {
      setLoading(false);
    }
  };

  const fetchSquadsBySector = async (sectorId: string) => {
    try {
      const squadsResponse = await fetch(`/api/v1/squads?sector_id=${sectorId}`);
      if (!squadsResponse.ok) throw new Error('Falha ao buscar os squads para o setor.');
      const squadsData = await squadsResponse.json();
      setSquads(squadsData);
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : "Erro desconhecido";
      toast({
        title: "Erro ao Carregar Squads",
        description: errorMessage,
        variant: "destructive",
      });
    }
  };

  useEffect(() => {
    fetchInitialData();
  }, [syncCounter]); // Refetch when syncCounter changes

  useEffect(() => {
    if (selectedSector) {
      fetchSquadsBySector(selectedSector);
      setSelectedSquads({}); // Limpa a seleção de squad ao trocar de setor
    } else {
      setSquads([]); // Limpa a lista de squads se nenhum setor estiver selecionado
    }
  }, [selectedSector]);

  const handleSquadChange = (groupId: number, squadIds: string[]) => {
    setSelectedSquads(prev => ({ ...prev, [groupId]: squadIds }));
  };

  const handleSaveChanges = async (groupId: number) => {
    const squadIds = selectedSquads[groupId] || [];

    const group = taskGroups.find(g => g.parent_id === groupId);
    if (!group) return;

    // Adicionado para robustez: não salvar se não houver squads no setor
    if (squads.length === 0) {
      toast({ title: "Não há squads neste setor para associar", variant: "destructive" });
      return;
    }

    setSaving(true);
    try {
      const response = await fetch('/api/v1/admin/task-types/associate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          squad_ids: squadIds.map(id => parseInt(id, 10)),
          task_type_ids: group.sub_types.map(st => st.id),
        }),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || "Falha ao salvar associação.");
      }

      toast({
        title: "Sucesso!",
        description: `Tarefas do grupo "${group.parent_name}" associadas com sucesso.`,
      });
      fetchInitialData();
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : "Erro desconhecido";
      toast({
        title: "Erro ao Salvar",
        description: errorMessage,
        variant: "destructive",
      });
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
        <p className="ml-4 text-muted-foreground">Carregando dados...</p>
      </div>
    );
  }

  if (error) {
    return (
      <Alert variant="destructive">
        <AlertTriangle className="h-4 w-4" />
        <AlertTitle>Erro de Comunicação</AlertTitle>
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Gerenciador de Tarefas</CardTitle>
        <CardDescription>
          Filtre por setor para ver os grupos de tarefas e associá-los a um squad.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="space-y-6">
          <div className="w-full md:w-1/3">
            <label htmlFor="sector-select" className="text-sm font-medium mb-2 block">
              1. Selecione um Setor
            </label>
            <Select onValueChange={setSelectedSector} value={selectedSector || ""}>
              <SelectTrigger id="sector-select">
                <SelectValue placeholder="Escolha um setor..." />
              </SelectTrigger>
              <SelectContent>
                {sectors.map(sector => (
                  <SelectItem key={sector.id} value={String(sector.id)}>
                    {sector.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {selectedSector && taskGroups.length > 0 && (
            <div className="border-t pt-6">
              <h3 className="text-lg font-medium mb-4">2. Associe os Grupos de Tarefas</h3>
              <Accordion type="single" collapsible className="w-full">
                {taskGroups.map(group => (
                  <AccordionItem value={`item-${group.parent_id}`} key={group.parent_id}>
                    <AccordionTrigger>
                      <span className="flex-grow text-left">{group.parent_name}</span>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="ml-4 h-8 w-8"
                        onClick={(e) => {
                          e.stopPropagation(); // Impede que o acordeão abra/feche
                          handleEditClick(group);
                        }}
                      >
                        <Pencil className="h-4 w-4" />
                      </Button>
                    </AccordionTrigger>
                    <AccordionContent>
                      <div className="space-y-4 p-2">
                        <div className="flex flex-col md:flex-row items-start md:items-center gap-4 p-4 border rounded-lg bg-muted/40">
                          <div className="flex-grow w-full md:w-auto">
                            <label htmlFor={`squad-multiselect-${group.parent_id}`} className="text-sm font-medium">
                              Associar todo o grupo aos Squads:
                            </label>
                            <MultiSelect
                              options={squads.map(s => ({ label: s.name, value: String(s.id) }))}
                              defaultValue={selectedSquads[group.parent_id] || []}
                              onValueChange={(value) => handleSquadChange(group.parent_id, value)}
                              placeholder="Selecione os squads..."
                              className="mt-1"
                            />
                          </div>
                          <Button onClick={() => handleSaveChanges(group.parent_id)} disabled={saving}>
                            <Save className="mr-2 h-4 w-4" />
                            {saving ? "Salvando..." : "Salvar Associações"}
                          </Button>
                        </div>
                        <Table>
                          <TableHeader>
                            <TableRow>
                              <TableHead>Subtipo de Tarefa</TableHead>
                              <TableHead>Squads Associados Atualmente</TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {group.sub_types.map(subType => (
                              <TableRow key={subType.id}>
                                <TableCell>{subType.name}</TableCell>
                                <TableCell>
                                  {(subType.squad_ids && subType.squad_ids.length > 0) ? (
                                    <div className="flex flex-wrap gap-1">
                                      {subType.squad_ids.map(squadId => (
                                        <Badge key={squadId} variant="secondary">
                                          {squads.find(s => s.id === squadId)?.name || 'ID desconhecido'}
                                        </Badge>
                                      ))}
                                    </div>
                                  ) : (
                                    <span className="text-muted-foreground">Nenhum</span>
                                  )}
                                </TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                      </div>
                    </AccordionContent>
                  </AccordionItem>
                ))}
              </Accordion>
            </div>
          )}

          {selectedSector && taskGroups.length === 0 && !loading && (
            <div className="text-center py-10 border-t">
                <p className="text-muted-foreground">Nenhum tipo de tarefa encontrado para este setor.</p>
                <p className="text-sm text-muted-foreground mt-2">
                    Tente sincronizar os dados na aba "Sincronização" para carregar as tarefas do Legal One.
                </p>
            </div>
          )}
        </div>
      </CardContent>
      <Dialog open={isEditDialogOpen} onOpenChange={setIsEditDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Renomear Grupo de Tarefas</DialogTitle>
          </DialogHeader>
          <div className="py-4">
            <label htmlFor="group-name" className="text-sm font-medium">
              Novo nome para "{editingGroup?.name}"
            </label>
            <Input
              id="group-name"
              value={newGroupName}
              onChange={(e) => setNewGroupName(e.target.value)}
              className="mt-2"
              autoFocus
            />
          </div>
          <DialogFooter>
            <DialogClose asChild>
              <Button type="button" variant="secondary">
                Cancelar
              </Button>
            </DialogClose>
            <Button type="button" onClick={handleRenameSave}>
              Salvar
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
};

export default TaskManager;