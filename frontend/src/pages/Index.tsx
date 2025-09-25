import { useState } from "react";
import { Button } from "@/components/ui/button";
import Dashboard from "@/components/Dashboard";
import SquadManager from "@/components/SquadManager";
import TaskCreator from "@/components/TaskCreator";

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
            
            <div className="flex gap-1">
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