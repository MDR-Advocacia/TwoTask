// Conteúdo COMPLETO para: frontend/src/components/SquadManager.tsx

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
import { toast } from "@/components/ui/use-toast";

// --- NOVAS INTERFACES ---
// Estas interfaces definem o "formato" dos dados que esperamos da nossa API FastAPI.
// É crucial que elas correspondam aos seus Pydantic Schemas.

interface SquadMember {
  id: number;
  name: string;
  email: string;
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

// --- CONSTANTE DA API ---
const API_BASE_URL = "http://localhost:8000/api/v1";

export default function SquadManager() {
  // --- ESTADOS DO COMPONENTE ---
  const [squads, setSquads] = useState<Squad[]>([]);
  const [legalOneUsers, setLegalOneUsers] = useState<LegalOneUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // --- EFEITO PARA BUSCAR DADOS (useEffect) ---
  // Este hook do React executa o código dentro dele uma vez, quando o componente é montado.
  useEffect(() => {
    const fetchData = async () => {
      try {
        setLoading(true);
        // Busca os squads e os usuários da nossa API em paralelo
        const [squadsResponse, usersResponse] = await Promise.all([
          fetch(`${API_BASE_URL}/dashboard/squads`),
          fetch(`${API_BASE_URL}/dashboard/legal-one-users`),
        ]);

        if (!squadsResponse.ok || !usersResponse.ok) {
          throw new Error("Falha ao buscar dados da API");
        }

        const squadsData: Squad[] = await squadsResponse.json();
        const usersData: LegalOneUser[] = await usersResponse.json();

        // Armazena os dados no estado do componente
        setSquads(squadsData);
        setLegalOneUsers(usersData);
        setError(null);
      } catch (err) {
        if (err instanceof Error) {
            setError(err.message);
        } else {
            setError("Ocorreu um erro desconhecido");
        }
        // Exibe um toast de erro para o usuário
        toast({
          variant: "destructive",
          title: "Erro de Conexão",
          description: "Não foi possível carregar os dados da API. Verifique se o backend está rodando.",
        });
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, []); // O array vazio [] garante que isso rode apenas uma vez

  // --- FUNÇÃO PARA ATUALIZAR O VÍNCULO ---
  // Esta função é chamada quando o valor de um dropdown é alterado.
  const handleLinkChange = async (squadMemberId: number, legalOneUserId: string | null) => {
    try {
        const response = await fetch(`${API_BASE_URL}/admin/update-member-link`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            // O Pydantic no FastAPI entende este formato JSON automaticamente
            body: JSON.stringify({
                squad_member_id: squadMemberId,
                legal_one_user_id: legalOneUserId ? parseInt(legalOneUserId, 10) : null,
            }),
        });

        if (!response.ok) {
            throw new Error('Falha ao salvar o vínculo.');
        }

        // Atualiza o estado local para refletir a mudança imediatamente, sem precisar recarregar a página
        setSquads(prevSquads =>
            prevSquads.map(squad => ({
                ...squad,
                members: squad.members.map(member =>
                    member.id === squadMemberId
                        ? { ...member, legal_one_user_id: legalOneUserId ? parseInt(legalOneUserId, 10) : null }
                        : member
                ),
            }))
        );

        toast({
          title: "Sucesso!",
          description: "O vínculo foi atualizado.",
        });

    } catch (error) {
        toast({
          variant: "destructive",
          title: "Erro ao Salvar",
          description: "Não foi possível atualizar o vínculo. Tente novamente.",
        });
    }
  };

  // --- RENDERIZAÇÃO CONDICIONAL ---
  if (loading) {
    return <p>Carregando dados da API...</p>;
  }

  if (error) {
    return <p className="text-destructive">Erro: {error}</p>;
  }

  // --- O JSX (HTML) DO COMPONENTE ---
  return (
    <div>
      {squads.map((squad) => (
        <Card key={squad.id} className="mb-8">
          <CardHeader>
            <CardTitle>{squad.name}</CardTitle>
            <CardDescription>Setor: {squad.sector}</CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Membro</TableHead>
                  <TableHead>Cargo</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="w-[300px]">Usuário Legal One</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {squad.members.filter(m => m.is_active).map((member) => (
                  <TableRow key={member.id}>
                    <TableCell className="font-medium">
                        {member.name}
                        {member.is_leader && <Badge variant="outline" className="ml-2">Líder</Badge>}
                    </TableCell>
                    <TableCell>{member.role || "N/A"}</TableCell>
                    <TableCell>
                        <Badge variant={member.is_active ? "default" : "destructive"}>
                            {member.is_active ? "Ativo" : "Inativo"}
                        </Badge>
                    </TableCell>
                    <TableCell>
                      <Select
                        // O valor é o ID do usuário vinculado, convertido para string
                        value={member.legal_one_user_id?.toString() || ""}
                        // Ao mudar, chama nossa função de atualização
                        onValueChange={(value) => handleLinkChange(member.id, value === "" ? null : value)}
                      >
                        <SelectTrigger>
                          <SelectValue placeholder="Selecione um usuário" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="">Desvincular</SelectItem>
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
}