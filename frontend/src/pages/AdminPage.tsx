// frontend/src/components/AdminPage.tsx

import { useState } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useToast } from "@/hooks/use-toast";
import { RefreshCw, Database, Users } from 'lucide-react';

const AdminPage = () => {
  const { toast } = useToast();
  const [isMetadataLoading, setIsMetadataLoading] = useState(false);
  const [isSquadsLoading, setIsSquadsLoading] = useState(false);

  const handleSync = async (
    endpoint: string, 
    setLoading: (isLoading: boolean) => void,
    successMessage: string
  ) => {
    setLoading(true);
    try {
      const response = await fetch(`/api/v1/admin/${endpoint}`, {
        method: 'POST',
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || 'Ocorreu um erro na solicitação.');
      }

      toast({
        title: "Sincronização Iniciada",
        description: successMessage,
      });

    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : "Erro desconhecido";
      toast({
        title: "Erro ao Iniciar Sincronização",
        description: errorMessage,
        variant: "destructive",
      });
    } finally {
      setLoading(false);
    }
  };
  
  return (
    <div className="container mx-auto py-10">
      <Card className="max-w-2xl mx-auto glass-card">
        <CardHeader>
          <CardTitle className="text-2xl">Painel de Administração</CardTitle>
          <CardDescription>
            Use estas ações para sincronizar os dados da aplicação com as fontes externas.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="p-4 border rounded-lg bg-muted/30">
            <div className="flex items-start">
              <div className="flex-shrink-0">
                <Database className="h-6 w-6 text-primary" />
              </div>
              <div className="ml-4 flex-1">
                <h3 className="text-lg font-semibold">Sincronizar Metadados do Legal One</h3>
                <p className="text-sm text-muted-foreground mt-1">
                  Busca e atualiza os dados essenciais do Legal One, como usuários, tipos de tarefa e escritórios. Execute esta ação quando houver novas configurações no Legal One.
                </p>
                <Button
                  className="mt-4"
                  onClick={() => handleSync('sync-metadata', setIsMetadataLoading, 'Sincronização de metadados do Legal One iniciada.')}
                  disabled={isMetadataLoading}
                >
                  <RefreshCw className={`mr-2 h-4 w-4 ${isMetadataLoading ? 'animate-spin' : ''}`} />
                  {isMetadataLoading ? 'Sincronizando...' : 'Sincronizar Metadados'}
                </Button>
              </div>
            </div>
          </div>

          <div className="p-4 border rounded-lg bg-muted/30">
            <div className="flex items-start">
              <div className="flex-shrink-0">
                <Users className="h-6 w-6 text-primary" />
              </div>
              <div className="ml-4 flex-1">
                <h3 className="text-lg font-semibold">Sincronizar Squads</h3>
                <p className="text-sm text-muted-foreground mt-1">
                  Busca e atualiza a estrutura de squads e membros a partir da API interna. Execute após mudanças na organização das equipes.
                </p>
                <Button
                  className="mt-4"
                  onClick={() => handleSync('sync-squads', setIsSquadsLoading, 'Sincronização de squads iniciada.')}
                  disabled={isSquadsLoading}
                >
                  <RefreshCw className={`mr-2 h-4 w-4 ${isSquadsLoading ? 'animate-spin' : ''}`} />
                  {isSquadsLoading ? 'Sincronizando...' : 'Sincronizar Squads'}
                </Button>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
};

export default AdminPage;