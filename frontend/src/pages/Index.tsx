import { useState } from "react";
import { Button } from "@/components/ui/button";
import Dashboard from "@/components/Dashboard";
import SquadManager from "@/components/SquadManager";
import TaskCreator from "@/components/TaskCreator";
import Layout from "@/components/Layout";

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

  const navButtons = (
    <>
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
    </>
  );

  return (
    <Layout navButtons={navButtons}>
      {renderActiveComponent()}
    </Layout>
  );
};

export default Index;