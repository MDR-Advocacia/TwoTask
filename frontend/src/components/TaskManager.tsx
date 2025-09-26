import { useState, useEffect } from 'react';
import { useToast } from "@/hooks/use-toast";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Loader2, AlertTriangle, Save } from "lucide-react";

// Definição de tipos para os dados da API
interface Sector {
  id: number;
  name: string;
}

interface Squad {
  id: number;
  name: string;
}

interface SubType {
  id: number;
  name: string;
  squad_id: number | null;
}

interface TaskTypeGroup {
  parent_id: number;
  parent_name: string;
  sub_types: SubType[];
}

const TaskManager = () => {
  const { toast } = useToast();
  const [taskGroups, setTaskGroups] = useState<TaskTypeGroup[]>([]);
  const [sectors, setSectors] = useState<Sector[]>([]);
  const [squads, setSquads] = useState<Squad[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // State for selected sector
  const [selectedSector, setSelectedSector] = useState<string | null>(null);

  // Mapeamento local para o squad selecionado por grupo
  const [selectedSquads, setSelectedSquads] = useState<Record<number, string>>({});

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
      const initialSelectedSquads: Record<number, string> = {};
      tasksData.forEach((group: TaskTypeGroup) => {
        const representativeSubType = group.sub_types.find(st => st.squad_id !== null);
        if (representativeSubType && representativeSubType.squad_id) {
          initialSelectedSquads[group.parent_id] = String(representativeSubType.squad_id);
        }
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
  }, []);

  useEffect(() => {
    if (selectedSector) {
      fetchSquadsBySector(selectedSector);
      setSelectedSquads({}); // Limpa a seleção de squad ao trocar de setor
    } else {
      setSquads([]); // Limpa a lista de squads se nenhum setor estiver selecionado
    }
  }, [selectedSector]);

  const handleSquadChange = (groupId: number, squadId: string) => {
    setSelectedSquads(prev => ({ ...prev, [groupId]: squadId }));
  };

  const handleSaveChanges = async (groupId: number) => {
    const squadId = selectedSquads[groupId];
    if (!squadId) {
      toast({ title: "Nenhum squad selecionado", variant: "destructive" });
      return;
    }

    const group = taskGroups.find(g => g.parent_id === groupId);
    if (!group) return;

    setSaving(true);
    try {
      const response = await fetch('/api/v1/admin/task-types/associate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          squad_id: parseInt(squadId, 10),
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
      // Opcional: recarregar os dados para refletir o estado do servidor
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
        <p className="ml-4 text-muted-foreground">Carregando tipos de tarefa...</p>
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
          Associe grupos de tipos de tarefa a um squad específico. As alterações são salvas por grupo.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="space-y-4">
          <div className="w-1/3">
            <label htmlFor="sector-select" className="text-sm font-medium mb-2 block">
              Filtrar por Setor:
            </label>
            <Select onValueChange={setSelectedSector} value={selectedSector || ""}>
              <SelectTrigger id="sector-select">
                <SelectValue placeholder="Selecione um setor..." />
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

          <Accordion type="single" collapsible className="w-full" disabled={!selectedSector}>
            {taskGroups.map(group => (
              <AccordionItem value={`item-${group.parent_id}`} key={group.parent_id}>
                <AccordionTrigger>{group.parent_name}</AccordionTrigger>
                <AccordionContent>
                  <div className="space-y-4">
                    <div className="flex items-center gap-4 p-4 border rounded-lg">
                      <div className="flex-grow">
                        <label htmlFor={`squad-select-${group.parent_id}`} className="text-sm font-medium">
                          Associar todo o grupo ao Squad:
                        </label>
                        <Select
                          value={selectedSquads[group.parent_id] || ""}
                          onValueChange={(value) => handleSquadChange(group.parent_id, value)}
                          disabled={!selectedSector || squads.length === 0}
                        >
                          <SelectTrigger id={`squad-select-${group.parent_id}`}>
                            <SelectValue placeholder={squads.length > 0 ? "Selecione um squad..." : "Nenhum squad neste setor"} />
                          </SelectTrigger>
                          <SelectContent>
                            {squads.map(squad => (
                              <SelectItem key={squad.id} value={String(squad.id)}>
                                {squad.name}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                      <Button onClick={() => handleSaveChanges(group.parent_id)} disabled={saving || !selectedSquads[group.parent_id]}>
                        <Save className="mr-2 h-4 w-4" />
                        {saving ? "Salvando..." : "Salvar Grupo"}
                      </Button>
                    </div>

                    <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Subtipo de Tarefa</TableHead>
                        <TableHead>Squad Associado Atualmente</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {group.sub_types.map(subType => (
                        <TableRow key={subType.id}>
                          <TableCell>{subType.name}</TableCell>
                          <TableCell>
                            {squads.find(s => s.id === subType.squad_id)?.name || <span className="text-muted-foreground">Nenhum</span>}
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
      </CardContent>
    </Card>
  );
};

export default TaskManager;