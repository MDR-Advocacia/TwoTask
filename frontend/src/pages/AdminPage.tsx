// frontend/src/pages/AdminPage.tsx

import { useState } from 'react';
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useToast } from "@/hooks/use-toast";
import { RefreshCw, Database } from 'lucide-react';

import SectorManager from '@/components/SectorManager';
import SquadManager from '@/components/SquadManager';
import TaskManager from '@/components/TaskManager';
import Layout from '@/components/Layout';

const AdminPage = () => {
  const { toast } = useToast();
  const [isMetadataLoading, setIsMetadataLoading] = useState(false);
  const [syncCounter, setSyncCounter] = useState(0); // State to trigger refresh

  const handleSyncMetadata = async () => {
    setIsMetadataLoading(true);
    try {
      const response = await fetch(`/api/v1/admin/sync-metadata`, {
        method: 'POST',
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || 'Ocorreu um erro na solicitação.');
      }
      toast({
        title: "Sincronização Iniciada",
        description: "Sincronização de metadados do Legal One iniciada. A página irá recarregar os dados em breve.",
      });
      setSyncCounter(prev => prev + 1); // Increment to trigger refresh
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : "Erro desconhecido";
      toast({
        title: "Erro ao Iniciar Sincronização",
        description: errorMessage,
        variant: "destructive",
      });
    } finally {
      setIsMetadataLoading(false);
    }
  };

  return (
    <Layout>
      <div className="container mx-auto py-10">
        <div className="mb-8">
          <h1 className="text-3xl font-bold">Painel de Administração</h1>
          <p className="text-muted-foreground">
            Gerencie os dados mestres e a estrutura das equipes da sua aplicação.
          </p>
        </div>

        <Tabs defaultValue="squads" className="space-y-4">
          <TabsList>
            <TabsTrigger value="squads">Gerenciar Squads</TabsTrigger>
            <TabsTrigger value="tasks">Gerenciar Tarefas</TabsTrigger>
            <TabsTrigger value="sectors">Gerenciar Setores</TabsTrigger>
            <TabsTrigger value="sync">Sincronização</TabsTrigger>
          </TabsList>

          <TabsContent value="squads">
            <SquadManager />
          </TabsContent>

          <TabsContent value="tasks">
            <TaskManager syncCounter={syncCounter} />
          </TabsContent>

          <TabsContent value="sectors">
            <SectorManager />
          </TabsContent>

          <TabsContent value="sync">
            <Card>
              <CardHeader>
                <CardTitle className="text-xl flex items-center gap-2">
                  <Database className="h-5 w-5" />
                  Sincronização de Dados Mestres
                </CardTitle>
                <CardDescription>
                  Busca e atualiza os dados essenciais do Legal One, como usuários e tipos de tarefa.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-muted-foreground mb-4">
                  Execute esta ação quando houver novas configurações no Legal One que precisam ser refletidas aqui.
                </p>
                <Button
                  onClick={handleSyncMetadata}
                  disabled={isMetadataLoading}
                >
                  <RefreshCw className={`mr-2 h-4 w-4 ${isMetadataLoading ? 'animate-spin' : ''}`} />
                  {isMetadataLoading ? 'Sincronizando...' : 'Sincronizar Metadados'}
                </Button>
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      </div>
    </Layout>
  );
};

export default AdminPage;