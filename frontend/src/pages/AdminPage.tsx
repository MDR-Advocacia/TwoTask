// frontend/src/pages/AdminPage.tsx

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import SectorManager from '@/components/SectorManager';
import SquadManager from '@/components/SquadManager';

const AdminPage = () => {
  return (
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
          <TabsTrigger value="sectors">Gerenciar Setores</TabsTrigger>
        </TabsList>

        <TabsContent value="squads">
          {/* Componente de Gerenciamento de Squads */}
          <SquadManager />
        </TabsContent>

        <TabsContent value="sectors">
          {/* Componente de Gerenciamento de Setores */}
          <SectorManager />
        </TabsContent>
      </Tabs>
    </div>
  );
};

export default AdminPage;