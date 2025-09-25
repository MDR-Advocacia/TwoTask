// frontend/src/components/SquadManager.tsx

import { useState, useEffect, FormEvent } from "react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
    DialogTrigger,
    DialogFooter,
    DialogClose,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Checkbox } from "@/components/ui/checkbox";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { useToast } from "@/hooks/use-toast";
import { PlusCircle, Edit, Trash2, Star, Users } from "lucide-react";

// --- Interfaces Alinhadas com a Nova API ---
interface LegalOneUser {
  id: number;
  name: string;
  is_active: boolean;
}

interface Sector {
  id: number;
  name: string;
}

interface SquadMember {
  id: number;
  is_leader: boolean;
  user: LegalOneUser;
}

interface Squad {
  id: number;
  name: string;
  is_active: boolean;
  sector: Sector;
  members: SquadMember[];
}

// Interfaces para o formulário
interface SquadMemberFormState {
  user_id: number;
  is_leader: boolean;
}
interface SquadFormState {
  id?: number;
  name: string;
  sector_id: number | null;
  members: SquadMemberFormState[];
}

const SquadManager = () => {
  const { toast } = useToast();
  const [squads, setSquads] = useState<Squad[]>([]);
  const [sectors, setSectors] = useState<Sector[]>([]);
  const [legalOneUsers, setLegalOneUsers] = useState<LegalOneUser[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // State for the dialog/form
  const [isDialogOpen, setIsDialogOpen] = useState(false);
  const [currentSquad, setCurrentSquad] = useState<SquadFormState>({
    name: "",
    sector_id: null,
    members: [],
  });

  // --- Data Fetching ---
  const fetchData = async () => {
    setIsLoading(true);
    try {
      const [squadsRes, sectorsRes, usersRes] = await Promise.all([
        fetch("/api/v1/squads"),
        fetch("/api/v1/sectors"),
        fetch("/api/v1/squads/legal-one-users"),
      ]);
      if (!squadsRes.ok || !sectorsRes.ok || !usersRes.ok) {
        throw new Error("Falha ao carregar dados essenciais.");
      }
      const squadsData = await squadsRes.json();
      const sectorsData = await sectorsRes.json();
      const usersData = await usersRes.json();
      setSquads(squadsData);
      setSectors(sectorsData);
      setLegalOneUsers(usersData);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro desconhecido");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  // --- Form and CRUD Logic ---
  const openDialog = (squad?: Squad) => {
    if (squad) {
      setCurrentSquad({
        id: squad.id,
        name: squad.name,
        sector_id: squad.sector.id,
        members: squad.members.map(m => ({ user_id: m.user.id, is_leader: m.is_leader }))
      });
    } else {
      // Garante que o estado seja totalmente redefinido para um novo squad
      setCurrentSquad({
        id: undefined, // Limpa o ID
        name: "",
        sector_id: null,
        members: [],
      });
    }
    setIsDialogOpen(true);
  };

  const handleMemberChange = (user_id: number) => {
    setCurrentSquad(prev => {
      const isSelected = prev.members.some(m => m.user_id === user_id);
      if (isSelected) {
        return { ...prev, members: prev.members.filter(m => m.user_id !== user_id) };
      } else {
        return { ...prev, members: [...prev.members, { user_id, is_leader: false }] };
      }
    });
  };

  const handleLeaderChange = (user_id: number) => {
    setCurrentSquad(prev => ({
      ...prev,
      members: prev.members.map(m => m.user_id === user_id ? { ...m, is_leader: !m.is_leader } : m)
    }));
  };

  const handleSaveSquad = async (e: FormEvent) => {
    e.preventDefault();
    if (!currentSquad.sector_id) {
        toast({ title: "Erro de Validação", description: "Por favor, selecione um setor.", variant: "destructive" });
        return;
    }

    const isEditing = !!currentSquad.id;
    const url = isEditing ? `/api/v1/squads/${currentSquad.id}` : "/api/v1/squads";
    const method = isEditing ? "PUT" : "POST";

    try {
      const response = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(currentSquad),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || "Falha ao salvar o squad.");
      }

      toast({
        title: `Squad ${isEditing ? "Atualizado" : "Criado"}!`,
        description: `O squad "${currentSquad.name}" foi salvo com sucesso.`,
      });

      fetchData();
      setIsDialogOpen(false);
    } catch (err) {
      toast({
        title: "Erro",
        description: err instanceof Error ? err.message : "Tente novamente.",
        variant: "destructive",
      });
    }
  };

  const handleDeleteSquad = async (squadId: number) => {
    if (!confirm("Tem certeza que deseja desativar este squad?")) return;

    try {
        const response = await fetch(`/api/v1/squads/${squadId}`, { method: 'DELETE' });
        if (!response.ok) throw new Error("Falha ao desativar o squad.");
        toast({ title: "Squad Desativado!" });
        fetchData();
    } catch (err) {
        toast({ title: "Erro", description: "Não foi possível desativar. Tente novamente.", variant: "destructive" });
    }
  };

  // --- Render Logic ---
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <div>
          <CardTitle>Gerenciamento de Squads</CardTitle>
          <CardDescription>Crie, edite e organize seus squads.</CardDescription>
        </div>
        <Button onClick={() => openDialog()}>
          <PlusCircle className="mr-2 h-4 w-4" />
          Novo Squad
        </Button>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Nome do Squad</TableHead>
              <TableHead>Setor</TableHead>
              <TableHead>Membros</TableHead>
              <TableHead className="text-right">Ações</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
             {isLoading ? (
              <TableRow><TableCell colSpan={4}>Carregando...</TableCell></TableRow>
            ) : error ? (
              <TableRow><TableCell colSpan={4} className="text-destructive">{error}</TableCell></TableRow>
            ) : squads.length > 0 ? (
              squads.map((squad) => (
                <TableRow key={squad.id}>
                  <TableCell className="font-medium">{squad.name}</TableCell>
                  <TableCell>{squad.sector.name}</TableCell>
                  <TableCell>
                     {squad.members.map(member => (
                        <Badge key={member.id} variant="secondary" className="mr-1 mb-1">
                            {member.is_leader && <Star className="mr-1 h-3 w-3 text-primary" />}
                            {member.user.name}
                        </Badge>
                     ))}
                  </TableCell>
                  <TableCell className="text-right">
                    <Button variant="ghost" size="icon" onClick={() => openDialog(squad)}>
                      <Edit className="h-4 w-4" />
                    </Button>
                    <Button variant="ghost" size="icon" onClick={() => handleDeleteSquad(squad.id)}>
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))
            ) : (
              <TableRow><TableCell colSpan={4} className="text-center">Nenhum squad encontrado. Crie o primeiro!</TableCell></TableRow>
            )}
          </TableBody>
        </Table>
      </CardContent>

      {/* --- Dialog Form --- */}
      <Dialog open={isDialogOpen} onOpenChange={setIsDialogOpen}>
          <DialogContent className="sm:max-w-[625px]">
            <DialogHeader>
              <DialogTitle>{currentSquad.id ? "Editar Squad" : "Novo Squad"}</DialogTitle>
              <DialogDescription>Preencha os detalhes do squad abaixo.</DialogDescription>
            </DialogHeader>
            <form onSubmit={handleSaveSquad}>
              <div className="grid gap-4 py-4">
                <div className="grid grid-cols-4 items-center gap-4">
                  <Label htmlFor="squad-name" className="text-right">Nome</Label>
                  <Input id="squad-name" value={currentSquad.name} onChange={e => setCurrentSquad({...currentSquad, name: e.target.value})} className="col-span-3" required />
                </div>
                <div className="grid grid-cols-4 items-center gap-4">
                  <Label htmlFor="sector" className="text-right">Setor</Label>
                  <Select value={currentSquad.sector_id?.toString()} onValueChange={value => setCurrentSquad({...currentSquad, sector_id: Number(value)})}>
                      <SelectTrigger className="col-span-3">
                          <SelectValue placeholder="Selecione um setor" />
                      </SelectTrigger>
                      <SelectContent>
                          {sectors.map(sector => <SelectItem key={sector.id} value={sector.id.toString()}>{sector.name}</SelectItem>)}
                      </SelectContent>
                  </Select>
                </div>
                <div className="grid grid-cols-4 items-start gap-4">
                    <Label className="text-right pt-2">Membros</Label>
                    <div className="col-span-3 border rounded-md p-4 max-h-60 overflow-y-auto">
                        <div className="flex items-center justify-between mb-2">
                            <h4 className="font-medium">Usuários do Legal One</h4>
                            <Badge variant="outline">{currentSquad.members.length} selecionado(s)</Badge>
                        </div>
                        <div className="space-y-2">
                            {legalOneUsers.map(user => {
                                const selection = currentSquad.members.find(m => m.user_id === user.id);
                                return (
                                    <div key={user.id} className="flex items-center justify-between p-2 rounded-md hover:bg-muted">
                                        <div className="flex items-center gap-2">
                                            <Checkbox id={`user-${user.id}`} checked={!!selection} onCheckedChange={() => handleMemberChange(user.id)} />
                                            <Label htmlFor={`user-${user.id}`}>{user.name}</Label>
                                        </div>
                                        {selection && (
                                            <div className="flex items-center gap-2">
                                                <Checkbox id={`leader-${user.id}`} checked={selection.is_leader} onCheckedChange={() => handleLeaderChange(user.id)} />
                                                <Label htmlFor={`leader-${user.id}`} className="text-sm text-muted-foreground">Líder <Star className="inline h-3 w-3" /></Label>
                                            </div>
                                        )}
                                    </div>
                                )
                            })}
                        </div>
                    </div>
                </div>
              </div>
              <DialogFooter>
                <DialogClose asChild><Button type="button" variant="outline">Cancelar</Button></DialogClose>
                <Button type="submit">Salvar Squad</Button>
              </DialogFooter>
            </form>
          </DialogContent>
        </Dialog>
    </Card>
  );
};

export default SquadManager;