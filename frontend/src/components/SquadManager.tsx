import { useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { Users, UserCheck, RefreshCw, Search, Crown, CheckCircle2, AlertCircle } from "lucide-react";
import { toast } from "@/hooks/use-toast";

interface SquadMember {
  id: string;
  name: string;
  role: string;
  isLeader: boolean;
  associatedUser?: string;
  status: 'active' | 'inactive' | 'pending';
}

interface Squad {
  id: string;
  name: string;
  department: string;
  members: SquadMember[];
  lastSync: string;
}

const SquadManager = () => {
  const [searchTerm, setSearchTerm] = useState("");
  const [selectedDepartment, setSelectedDepartment] = useState("all");
  const [isLoading, setIsLoading] = useState(false);

  // Mock data - replace with real API calls
  const [squads, setSquads] = useState<Squad[]>([
    {
      id: "1",
      name: "Squad Comercial",
      department: "Direito Empresarial",
      lastSync: "2 minutos atrás",
      members: [
        { id: "1", name: "Ana Silva", role: "Advogada Sênior", isLeader: true, associatedUser: "ana.silva@lo", status: "active" },
        { id: "2", name: "João Santos", role: "Advogado Júnior", isLeader: false, associatedUser: "joao.santos@lo", status: "active" },
        { id: "3", name: "Maria Costa", role: "Paralegal", isLeader: false, status: "pending" },
      ]
    },
    {
      id: "2",
      name: "Squad Tributário",
      department: "Direito Tributário",
      lastSync: "5 minutos atrás",
      members: [
        { id: "4", name: "Carlos Lima", role: "Advogado Especialista", isLeader: true, associatedUser: "carlos.lima@lo", status: "active" },
        { id: "5", name: "Fernanda Oliveira", role: "Advogada Pleno", isLeader: false, status: "pending" },
      ]
    },
    {
      id: "3",
      name: "Squad Trabalhista",
      department: "Direito Trabalhista",
      lastSync: "1 hora atrás",
      members: [
        { id: "6", name: "Roberto Silva", role: "Advogado Sênior", isLeader: true, associatedUser: "roberto.silva@lo", status: "active" },
        { id: "7", name: "Juliana Pereira", role: "Advogada Júnior", isLeader: false, associatedUser: "juliana.pereira@lo", status: "active" },
        { id: "8", name: "Pedro Alves", role: "Estagiário", isLeader: false, status: "inactive" },
      ]
    }
  ]);

  const legalOneUsers = [
    "ana.silva@lo", "joao.santos@lo", "carlos.lima@lo", "roberto.silva@lo", 
    "juliana.pereira@lo", "fernanda.oliveira@lo", "maria.costa@lo", "pedro.alves@lo"
  ];

  const departments = ["all", "Direito Empresarial", "Direito Tributário", "Direito Trabalhista"];

  const filteredSquads = squads.filter(squad => {
    const matchesSearch = squad.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
                         squad.members.some(member => member.name.toLowerCase().includes(searchTerm.toLowerCase()));
    const matchesDepartment = selectedDepartment === "all" || squad.department === selectedDepartment;
    return matchesSearch && matchesDepartment;
  });

  const handleAssociation = (squadId: string, memberId: string, userId: string) => {
    setSquads(prevSquads => 
      prevSquads.map(squad => 
        squad.id === squadId 
          ? {
              ...squad,
              members: squad.members.map(member =>
                member.id === memberId 
                  ? { ...member, associatedUser: userId, status: 'active' as const }
                  : member
              )
            }
          : squad
      )
    );
    
    toast({
      title: "Associação realizada",
      description: "Membro associado com sucesso ao usuário do Legal One.",
    });
  };

  const handleSyncAll = async () => {
    setIsLoading(true);
    // Simulate API call
    await new Promise(resolve => setTimeout(resolve, 2000));
    
    setSquads(prevSquads => 
      prevSquads.map(squad => ({
        ...squad,
        lastSync: "agora mesmo"
      }))
    );
    
    setIsLoading(false);
    toast({
      title: "Sincronização concluída",
      description: "Todos os squads foram sincronizados com sucesso.",
    });
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'active': return <CheckCircle2 className="w-4 h-4 text-green-600" />;
      case 'pending': return <AlertCircle className="w-4 h-4 text-yellow-600" />;
      case 'inactive': return <AlertCircle className="w-4 h-4 text-gray-400" />;
      default: return null;
    }
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'active': return 'bg-green-100 text-green-800 border-green-200';
      case 'pending': return 'bg-yellow-100 text-yellow-800 border-yellow-200';
      case 'inactive': return 'bg-gray-100 text-gray-800 border-gray-200';
      default: return 'bg-gray-100 text-gray-800 border-gray-200';
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-background via-muted/20 to-background">
      {/* Header */}
      <div className="glass-card rounded-none border-x-0 border-t-0 mb-8 p-6">
        <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
          <div>
            <h1 className="text-3xl font-bold bg-gradient-to-r from-primary to-accent bg-clip-text text-transparent">
              Gerenciamento de Squads
            </h1>
            <p className="text-muted-foreground mt-1">
              Configure e associe membros das equipes aos usuários do Legal One
            </p>
          </div>
          <Button 
            onClick={handleSyncAll}
            disabled={isLoading}
            className="glass-button border-0 text-white"
          >
            <RefreshCw className={`w-4 h-4 mr-2 ${isLoading ? 'animate-spin' : ''}`} />
            {isLoading ? 'Sincronizando...' : 'Sincronizar Todos'}
          </Button>
        </div>
      </div>

      <div className="container mx-auto px-6 space-y-8">
        {/* Filters */}
        <Card className="glass-card border-0 animate-fade-in">
          <CardContent className="pt-6">
            <div className="flex flex-col md:flex-row gap-4">
              <div className="flex-1">
                <div className="relative">
                  <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-muted-foreground w-4 h-4" />
                  <Input
                    placeholder="Buscar squads ou membros..."
                    value={searchTerm}
                    onChange={(e) => setSearchTerm(e.target.value)}
                    className="pl-10 border-glass-border"
                  />
                </div>
              </div>
              <Select value={selectedDepartment} onValueChange={setSelectedDepartment}>
                <SelectTrigger className="w-full md:w-[200px] border-glass-border">
                  <SelectValue placeholder="Departamento" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">Todos os Departamentos</SelectItem>
                  {departments.slice(1).map(dept => (
                    <SelectItem key={dept} value={dept}>{dept}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </CardContent>
        </Card>

        {/* Squads Grid */}
        <div className="grid gap-6">
          {filteredSquads.map((squad, index) => (
            <Card key={squad.id} className="glass-card border-0 animate-slide-up" 
                  style={{ animationDelay: `${index * 100}ms` }}>
              <CardHeader>
                <div className="flex justify-between items-start">
                  <div>
                    <CardTitle className="flex items-center gap-2">
                      <Users className="w-5 h-5 text-primary" />
                      {squad.name}
                    </CardTitle>
                    <CardDescription className="mt-1">
                      {squad.department} • Última sincronização: {squad.lastSync}
                    </CardDescription>
                  </div>
                  <Badge variant="secondary" className="bg-primary/10 text-primary border-primary/20">
                    {squad.members.length} membros
                  </Badge>
                </div>
              </CardHeader>
              <CardContent>
                <div className="space-y-4">
                  {squad.members.map((member) => (
                    <div key={member.id} className="flex items-center justify-between p-4 rounded-lg bg-muted/30 hover:bg-muted/50 transition-all duration-200">
                      <div className="flex items-center gap-3">
                        <div className="flex items-center gap-2">
                          {getStatusIcon(member.status)}
                          <div>
                            <div className="flex items-center gap-2">
                              <span className="font-medium">{member.name}</span>
                              {member.isLeader && (
                                <Crown className="w-4 h-4 text-yellow-500" />
                              )}
                            </div>
                            <p className="text-sm text-muted-foreground">{member.role}</p>
                          </div>
                        </div>
                      </div>
                      
                      <div className="flex items-center gap-3">
                        <Badge className={`border text-xs ${getStatusBadge(member.status)}`}>
                          {member.status === 'active' ? 'Ativo' : 
                           member.status === 'pending' ? 'Pendente' : 'Inativo'}
                        </Badge>
                        
                        <div className="min-w-[200px]">
                          <Select 
                            value={member.associatedUser || "none"} 
                            onValueChange={(value) => {
                              if (value !== "none") {
                                handleAssociation(squad.id, member.id, value);
                              }
                            }}
                          >
                            <SelectTrigger className="border-glass-border">
                              <SelectValue placeholder="Associar usuário..." />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="none">Sem associação</SelectItem>
                              {legalOneUsers.map(user => (
                                <SelectItem key={user} value={user}>
                                  <div className="flex items-center gap-2">
                                    <UserCheck className="w-4 h-4" />
                                    {user}
                                  </div>
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>

        {filteredSquads.length === 0 && (
          <Card className="glass-card border-0 animate-fade-in">
            <CardContent className="pt-6">
              <div className="text-center py-12">
                <Users className="w-12 h-12 text-muted-foreground mx-auto mb-4" />
                <h3 className="text-lg font-medium mb-2">Nenhum squad encontrado</h3>
                <p className="text-muted-foreground">
                  Tente ajustar os filtros de busca ou sincronize os dados novamente.
                </p>
              </div>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
};

export default SquadManager;