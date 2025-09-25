// frontend/src/components/SquadManager.tsx

import { useState, useEffect } from "react";
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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { useToast } from "@/hooks/use-toast";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { AlertCircle, Star } from "lucide-react"; // Importar o ícone de estrela

// ... (Interfaces permanecem as mesmas) ...
interface SquadMember {
  id: number;
  name: string;
  role: string | null;
  is_active: boolean;
  is_leader: boolean;
  legal_one_user_id: number | null;
}

interface Squad {
  id: number;
  name: string;
  sector: string;
  members: SquadMember[];
}

interface LegalOneUser {
  id: number;
  name: string;
}


const SquadManager = () => {
  const { toast } = useToast();
  const [squads, setSquads] = useState<Squad[]>([]);
  const [legalOneUsers, setLegalOneUsers] = useState<LegalOneUser[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // ... (lógica de fetch de dados permanece a mesma) ...
    const fetchAllData = async () => {
      setIsLoading(true);
      setError(null);
      try {
        const [squadsResponse, usersResponse] = await Promise.all([
          fetch("/api/v1/squads"),
          fetch("/api/v1/squads/legal-one-users"),
        ]);

        if (!squadsResponse.ok || !usersResponse.ok) {
          throw new Error("Falha ao buscar os dados do servidor.");
        }

        const squadsData: Squad[] = await squadsResponse.json();
        const usersData: LegalOneUser[] = await usersResponse.json();

        setSquads(squadsData);
        setLegalOneUsers(usersData);
      } catch (err) {
        const errorMessage = err instanceof Error ? err.message : "Ocorreu um erro desconhecido.";
        setError(errorMessage);
      } finally {
        setIsLoading(false);
      }
    };

    fetchAllData();
  }, []);

  const handleLinkChange = async (memberId: number, legalOneUserId: string | null) => {
    // ... (lógica de handleLinkChange permanece a mesma) ...
    try {
      const response = await fetch(`/api/v1/squads/members/link`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          squad_member_id: memberId,
          legal_one_user_id: legalOneUserId ? parseInt(legalOneUserId, 10) : null,
        }),
      });

      if (!response.ok) throw new Error("Falha ao atualizar o vínculo.");
      
      const updatedMember: SquadMember = await response.json();

      setSquads(currentSquads => 
        currentSquads.map(squad => ({
          ...squad,
          members: squad.members.map(member => 
            member.id === updatedMember.id ? updatedMember : member
          )
        }))
      );

      toast({
        title: "Vínculo Atualizado!",
        description: "A associação foi salva com sucesso.",
      });
    } catch (err) {
      toast({
        title: "Erro",
        description: "Não foi possível salvar a associação. Tente novamente.",
        variant: "destructive",
      });
    }
  };


  if (isLoading) {
    // ... (Skeleton UI) ...
    return <div>Carregando...</div>
  }

  if (error) {
    // ... (Error UI) ...
    return <div>Erro: {error}</div>
  }

  return (
    <div className="container mx-auto py-10 space-y-8">
      <div>
        <h1 className="text-3xl font-bold">Gerenciamento de Squads</h1>
        <p className="text-muted-foreground">
          Associe os membros de cada squad ao seu usuário correspondente no Legal One.
        </p>
      </div>

      {squads.map((squad) => (
        <Card key={squad.id}>
          <CardHeader>
            <CardTitle>{squad.name}</CardTitle>
            <CardDescription>{squad.sector}</CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Nome</TableHead>
                  <TableHead>Cargo</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="w-[350px]">Usuário Legal One</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {squad.members && squad.members.map((member) => (
                  <TableRow key={member.id}>
                    {/* --- A CORREÇÃO ESTÁ AQUI --- */}
                    <TableCell className="font-medium">
                      <div className="flex items-center gap-2">
                        <span>{member.name}</span>
                        {member.is_leader && (
                          <Badge variant="secondary" className="border-primary text-primary">
                            <Star className="mr-1 h-3 w-3" />
                            Líder
                          </Badge>
                        )}
                      </div>
                    </TableCell>
                    <TableCell>{member.role || "N/A"}</TableCell>
                    <TableCell>
                      <Badge variant={member.is_active ? "default" : "outline"}>
                        {member.is_active ? "Ativo" : "Inativo"}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Select
                        value={member.legal_one_user_id?.toString() || ""}
                        onValueChange={(value) => handleLinkChange(member.id, value === "unlink" ? null : value)}
                      >
                        <SelectTrigger>
                          <SelectValue placeholder="Selecione um usuário" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="unlink">Desvincular</SelectItem>
                          {legalOneUsers.map((user) => (
                            <SelectItem key={user.id} value={user.id.toString()}>
                              {user.name}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      ))}
    </div>
  );
};

export default SquadManager;