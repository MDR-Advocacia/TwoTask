import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Users, Target, BarChart3, Settings, Plus, Activity } from "lucide-react";

const Dashboard = () => {
  const stats = [
    { 
      title: "Squads Ativos", 
      value: "12", 
      description: "Equipes configuradas",
      icon: Users,
      trend: "+2 este mês"
    },
    { 
      title: "Tarefas Criadas", 
      value: "1,247", 
      description: "Total este mês",
      icon: Target,
      trend: "+18% vs mês anterior"
    },
    { 
      title: "Taxa de Sucesso", 
      value: "98.5%", 
      description: "Automações concluídas",
      icon: BarChart3,
      trend: "+0.3% esta semana"
    },
    { 
      title: "Tempo Médio", 
      value: "2.3s", 
      description: "Processamento por tarefa",
      icon: Activity,
      trend: "-15% mais rápido"
    },
  ];

  const recentActions = [
    { action: "Squad Comercial sincronizado", time: "2 min atrás", status: "success" },
    { action: "15 tarefas criadas - Processo 1234567", time: "5 min atrás", status: "success" },
    { action: "Sincronização Legal One iniciada", time: "12 min atrás", status: "processing" },
    { action: "Squad Tributário atualizado", time: "1h atrás", status: "success" },
  ];

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'success': return 'bg-green-100 text-green-800 border-green-200';
      case 'processing': return 'bg-blue-100 text-blue-800 border-blue-200';
      default: return 'bg-gray-100 text-gray-800 border-gray-200';
    }
  };
''
  return (
    <div className="min-h-screen bg-gradient-to-br from-background via-muted/20 to-background">
      {/* Header */}
      <div className="glass-card rounded-none border-x-0 border-t-0 mb-8 p-6">
        <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
          <div>
            <h1 className="text-3xl font-bold bg-gradient-to-r from-primary to-accent bg-clip-text text-transparent">
              OneTask Dashboard
            </h1>
          </div>
          <div className="flex gap-3">
            <Button variant="outline" size="sm">
              <Settings className="w-4 h-4 mr-2" />
              Configurações
            </Button>
            <Button className="glass-button border-0 text-white">
              <Plus className="w-4 h-4 mr-2" />
              Nova Tarefa
            </Button>
          </div>
        </div>
      </div>

      <div className="container mx-auto px-6 space-y-8">
        {/* Stats Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
          {stats.map((stat, index) => (
            <Card key={index} className="glass-card hover:shadow-lg transition-all duration-300 animate-slide-up border-0" 
                  style={{ animationDelay: `${index * 100}ms` }}>
              <CardHeader className="flex flex-row items-center justify-between pb-2">
                <div className="space-y-1">
                  <CardTitle className="text-sm font-medium text-muted-foreground">
                    {stat.title}
                  </CardTitle>
                  <div className="text-2xl font-bold text-primary">
                    {stat.value}
                  </div>
                </div>
                <div className="p-2 rounded-xl bg-gradient-to-br from-primary/10 to-accent/10">
                  <stat.icon className="w-5 h-5 text-primary" />
                </div>
              </CardHeader>
              <CardContent className="pt-0">
                <p className="text-xs text-muted-foreground mb-2">
                  {stat.description}
                </p>
                <Badge variant="secondary" className="text-xs bg-green-100 text-green-700 border-green-200">
                  {stat.trend}
                </Badge>
              </CardContent>
            </Card>
          ))}
        </div>

        {/* Main Content Grid */}
        <div className="grid lg:grid-cols-3 gap-8">
          {/* Quick Actions */}
          <Card className="glass-card border-0 animate-fade-in lg:col-span-1">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Target className="w-5 h-5 text-primary" />
                Ações Rápidas
              </CardTitle>
              <CardDescription>
                Execute operações comuns rapidamente
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <Button variant="outline" className="w-full justify-start h-12 hover:bg-primary/5 border-glass-border">
                <Users className="w-4 h-4 mr-3" />
                Gerenciar Squads
              </Button>
              <Button variant="outline" className="w-full justify-start h-12 hover:bg-primary/5 border-glass-border">
                <Plus className="w-4 h-4 mr-3" />
                Criar Tarefas em Lote
              </Button>
              <Button variant="outline" className="w-full justify-start h-12 hover:bg-primary/5 border-glass-border">
                <BarChart3 className="w-4 h-4 mr-3" />
                Relatórios e Logs
              </Button>
              <Button variant="outline" className="w-full justify-start h-12 hover:bg-primary/5 border-glass-border">
                <Activity className="w-4 h-4 mr-3" />
                Monitorar APIs
              </Button>
            </CardContent>
          </Card>

          {/* Recent Activity */}
          <Card className="glass-card border-0 animate-fade-in lg:col-span-2" style={{ animationDelay: '200ms' }}>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Activity className="w-5 h-5 text-primary" />
                Atividades Recentes
              </CardTitle>
              <CardDescription>
                Últimas operações realizadas no sistema
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="space-y-4">
                {recentActions.map((item, index) => (
                  <div key={index} className="flex items-center justify-between p-3 rounded-lg bg-muted/30 hover:bg-muted/50 transition-colors">
                    <div className="flex-1">
                      <p className="text-sm font-medium">{item.action}</p>
                      <p className="text-xs text-muted-foreground">{item.time}</p>
                    </div>
                    <Badge className={`${getStatusColor(item.status)} border text-xs`}>
                      {item.status === 'success' ? 'Concluído' : 'Processando'}
                    </Badge>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </div>

        {/* System Status */}
        <Card className="glass-card border-0 animate-fade-in" style={{ animationDelay: '400ms' }}>
          <CardHeader>
            <CardTitle className="text-lg">Status do Sistema</CardTitle>
            <CardDescription>
              Monitoramento em tempo real dos serviços
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid md:grid-cols-3 gap-6">
              <div className="flex items-center gap-3">
                <div className="w-3 h-3 rounded-full bg-green-500 animate-pulse-glow"></div>
                <div>
                  <p className="text-sm font-medium">API Legal One</p>
                  <p className="text-xs text-muted-foreground">Operacional</p>
                </div>
              </div>
              <div className="flex items-center gap-3">
                <div className="w-3 h-3 rounded-full bg-green-500 animate-pulse-glow"></div>
                <div>
                  <p className="text-sm font-medium">API Squads</p>
                  <p className="text-xs text-muted-foreground">Operacional</p>
                </div>
              </div>
              <div className="flex items-center gap-3">
                <div className="w-3 h-3 rounded-full bg-green-500 animate-pulse-glow"></div>
                <div>
                  <p className="text-sm font-medium">Banco de Dados</p>
                  <p className="text-xs text-muted-foreground">Operacional</p>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
};

export default Dashboard;