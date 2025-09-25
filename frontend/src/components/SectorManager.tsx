// frontend/src/components/SectorManager.tsx

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
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { useToast } from "@/hooks/use-toast";
import { PlusCircle, Edit, Trash2 } from "lucide-react";

// --- Interfaces ---
interface Sector {
  id: number;
  name: string;
  is_active: boolean;
}

const SectorManager = () => {
  const { toast } = useToast();
  const [sectors, setSectors] = useState<Sector[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isDialogOpen, setIsDialogOpen] = useState(false);
  const [currentSector, setCurrentSector] = useState<Partial<Sector>>({});

  // --- Data Fetching ---
  const fetchSectors = async () => {
    setIsLoading(true);
    try {
      const response = await fetch("/api/v1/sectors");
      if (!response.ok) throw new Error("Falha ao buscar setores.");
      const data: Sector[] = await response.json();
      setSectors(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro desconhecido.");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchSectors();
  }, []);

  // --- Event Handlers ---
  const handleSaveSector = async (e: FormEvent) => {
    e.preventDefault();
    const isEditing = !!currentSector.id;
    const url = isEditing ? `/api/v1/sectors/${currentSector.id}` : "/api/v1/sectors";
    const method = isEditing ? "PUT" : "POST";

    try {
      const response = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: currentSector.name }),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || "Falha ao salvar o setor.");
      }

      toast({
        title: `Setor ${isEditing ? "Atualizado" : "Criado"}!`,
        description: `O setor "${currentSector.name}" foi salvo com sucesso.`,
      });

      fetchSectors(); // Refresh list
      setIsDialogOpen(false); // Close dialog
    } catch (err) {
      toast({
        title: "Erro",
        description: err instanceof Error ? err.message : "Tente novamente.",
        variant: "destructive",
      });
    }
  };

  const handleDeleteSector = async (sector: Sector) => {
    if (!confirm(`Tem certeza que deseja desativar o setor "${sector.name}"?`)) return;

    try {
      const response = await fetch(`/api/v1/sectors/${sector.id}`, { method: "DELETE" });
      if (!response.ok) throw new Error("Falha ao desativar o setor.");

      toast({
        title: "Setor Desativado!",
        description: `O setor "${sector.name}" foi desativado.`,
      });

      fetchSectors(); // Refresh list
    } catch (err) {
      toast({
        title: "Erro",
        description: "Não foi possível desativar o setor. Tente novamente.",
        variant: "destructive",
      });
    }
  };

  const openDialog = (sector?: Sector) => {
    setCurrentSector(sector || {});
    setIsDialogOpen(true);
  };

  // --- Render Logic ---
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <div>
          <CardTitle>Gerenciamento de Setores</CardTitle>
          <CardDescription>Crie e organize os setores do seu escritório.</CardDescription>
        </div>
        <Dialog open={isDialogOpen} onOpenChange={setIsDialogOpen}>
          <DialogTrigger asChild>
            <Button onClick={() => openDialog()}>
              <PlusCircle className="mr-2 h-4 w-4" />
              Novo Setor
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>{currentSector.id ? "Editar Setor" : "Novo Setor"}</DialogTitle>
              <DialogDescription>
                {currentSector.id ? "Altere o nome do setor." : "Crie um novo setor para organizar seus squads."}
              </DialogDescription>
            </DialogHeader>
            <form onSubmit={handleSaveSector}>
              <div className="grid gap-4 py-4">
                <div className="grid grid-cols-4 items-center gap-4">
                  <Label htmlFor="name" className="text-right">Nome</Label>
                  <Input
                    id="name"
                    value={currentSector.name || ""}
                    onChange={(e) => setCurrentSector({ ...currentSector, name: e.target.value })}
                    className="col-span-3"
                    required
                  />
                </div>
              </div>
              <DialogFooter>
                <DialogClose asChild>
                  <Button type="button" variant="outline">Cancelar</Button>
                </DialogClose>
                <Button type="submit">Salvar</Button>
              </DialogFooter>
            </form>
          </DialogContent>
        </Dialog>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Nome</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="text-right">Ações</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              <TableRow><TableCell colSpan={3}>Carregando...</TableCell></TableRow>
            ) : error ? (
              <TableRow><TableCell colSpan={3} className="text-destructive">{error}</TableCell></TableRow>
            ) : sectors.length > 0 ? (
              sectors.map((sector) => (
                <TableRow key={sector.id}>
                  <TableCell className="font-medium">{sector.name}</TableCell>
                  <TableCell>
                    <Badge variant={sector.is_active ? "default" : "outline"}>
                      {sector.is_active ? "Ativo" : "Inativo"}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right">
                    <Button variant="ghost" size="icon" onClick={() => openDialog(sector)}>
                      <Edit className="h-4 w-4" />
                    </Button>
                    <Button variant="ghost" size="icon" onClick={() => handleDeleteSector(sector)}>
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))
            ) : (
              <TableRow><TableCell colSpan={3} className="text-center">Nenhum setor encontrado.</TableCell></TableRow>
            )}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
};

export default SectorManager;