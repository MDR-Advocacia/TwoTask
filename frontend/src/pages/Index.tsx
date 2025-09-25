// frontend/src/pages/Index.tsx

import { useState } from "react";
import { Link } from "react-router-dom"; // 1. Importar o componente Link
import { Button } from "@/components/ui/button";
import Dashboard from "@/components/Dashboard";
import SquadManager from "@/components/SquadManager";
import TaskCreator from "@/components/TaskCreator";
import { Settings } from "lucide-react"; // 2. Importar o ícone

// 3. Importar os componentes do DropdownMenu
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";


const Index = () => {
  const [activeTab, setActiveTab] = useState<'dashboard' | 'squads' | 'tasks'>('dashboard');

  const renderActiveComponent = () => {
    switch (activeTab) {
      case 'dashboard':
        return <Dashboard />;
      case 'squads':
        return <SquadManager />;
      case 'tasks':
        return <TaskCreator />;
      default:
        return <Dashboard />;
    }
  };

  return (
    <div className="min-h-screen">
      {/* Navigation */}
      <nav className="glass-card rounded-none border-x-0 border-t-0 sticky top-0 z-50">
        <div className="container mx-auto px-6 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <img
                src="/logo-escritorio2.png"
                alt="Logo do Escritório"
                className="w-15 h-12 square object-cover"
              />
              <span className="font-bold text-xl bg-gradient-to-r from-primary to-accent bg-clip-text text-transparent">
                OneTask
              </span>
            </div>
            
            <div className="flex items-center gap-2"> {/* Agrupar todos os botões */}
              {/* Botões de Navegação Principal */}
              <Button
                variant={activeTab === 'dashboard' ? 'default' : 'ghost'}
                onClick={() => setActiveTab('dashboard')}
                className={activeTab === 'dashboard' ? 'glass-button border-0 text-white' : ''}
              >
                Dashboard
              </Button>
              <Button
                variant={activeTab === 'squads' ? 'default' : 'ghost'}
                onClick={() => setActiveTab('squads')}
                className={activeTab === 'squads' ? 'glass-button border-0 text-white' : ''}
              >
                Squads
              </Button>
              <Button
                variant={activeTab === 'tasks' ? 'default' : 'ghost'}
                onClick={() => setActiveTab('tasks')}
                className={activeTab === 'tasks' ? 'glass-button border-0 text-white' : ''}
              >
                Criar Tarefas
              </Button>

              {/* --- NOVO MENU DE ADMINISTRAÇÃO --- */}
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="outline" size="icon">
                    <Settings className="h-4 w-4" />
                    <span className="sr-only">Abrir configurações</span>
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem asChild>
                    <Link to="/admin">Administração</Link>
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          </div>
        </div>
      </nav>

      {/* Main Content */}
      <main>
        {renderActiveComponent()}
      </main>
    </div>
  );
};

export default Index;