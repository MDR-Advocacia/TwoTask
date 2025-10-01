// frontend/src/components/ui/sidebar.tsx

import { Link, useLocation } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { 
    Home, 
    PanelLeft, 
    Settings, 
    ChevronRight,
    FilePlus2,
    CopyPlus,
    PlusSquare
} from 'lucide-react';
import { useMobile } from '@/hooks/use-mobile';
import { Sheet, SheetContent, SheetTrigger } from './sheet';

interface NavLinkProps {
  to: string;
  icon: React.ElementType;
  label: string;
  isSidebarCollapsed: boolean;
}

function NavLink({ to, icon: Icon, label, isSidebarCollapsed }: NavLinkProps) {
  const location = useLocation();
  const isActive = location.pathname === to;

  if (isSidebarCollapsed) {
    return (
      <TooltipProvider>
        <Tooltip delayDuration={0}>
          <TooltipTrigger asChild>
            <Link to={to}>
              <Button variant={isActive ? "secondary" : "ghost"} className="w-10 h-10 p-0">
                <Icon className="h-5 w-5" />
                <span className="sr-only">{label}</span>
              </Button>
            </Link>
          </TooltipTrigger>
          <TooltipContent side="right">{label}</TooltipContent>
        </Tooltip>
      </TooltipProvider>
    );
  }

  return (
    <Link to={to}>
      <Button variant={isActive ? "secondary" : "ghost"} className="w-full justify-start">
        <Icon className="mr-4 h-5 w-5" />
        {label}
      </Button>
    </Link>
  );
}

function MainNav({ isSidebarCollapsed }: { isSidebarCollapsed: boolean }) {
    const location = useLocation();
    const isTaskCreationActive = location.pathname.startsWith('/tasks');

    return (
        <nav className="grid gap-2">
            <NavLink to="/" icon={Home} label="Dashboard" isSidebarCollapsed={isSidebarCollapsed} />

            {/* --- NOVO MENU EXPANSÍVEL PARA CRIAÇÃO DE TAREFAS --- */}
            <Collapsible defaultOpen={isTaskCreationActive}>
                <CollapsibleTrigger asChild>
                    <Button variant={isTaskCreationActive ? "secondary" : "ghost"} className="w-full justify-start">
                        <FilePlus2 className="mr-4 h-5 w-5" />
                        {!isSidebarCollapsed && "Criar Tarefas"}
                        {!isSidebarCollapsed && <ChevronRight className="ml-auto h-4 w-4 transition-transform [&[data-state=open]]:rotate-90" />}
                    </Button>
                </CollapsibleTrigger>
                <CollapsibleContent className="pt-1 space-y-1">
                    <Link to="/tasks/template-batch" className="pl-4">
                        <Button variant={location.pathname === '/tasks/template-batch' ? "secondary" : "ghost"} className="w-full justify-start">
                            <CopyPlus className="mr-4 h-5 w-5" />
                            {!isSidebarCollapsed && "Por Template (Lote)"}
                        </Button>
                    </Link>
                    <Link to="/tasks/by-process" className="pl-4">
                        <Button variant={location.pathname === '/tasks/by-process' ? "secondary" : "ghost"} className="w-full justify-start">
                            <PlusSquare className="mr-4 h-5 w-5" />
                            {!isSidebarCollapsed && "Por Processo (Individual)"}
                        </Button>
                    </Link>
                </CollapsibleContent>
            </Collapsible>
            
            <NavLink to="/admin" icon={Settings} label="Admin" isSidebarCollapsed={isSidebarCollapsed} />
        </nav>
    );
}

export function Sidebar() {
    const isMobile = useMobile();
    const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);

    if (isMobile) {
        return (
            <Sheet>
                <SheetTrigger asChild>
                    <Button variant="ghost" size="icon" className="md:hidden">
                        <PanelLeft className="h-6 w-6" />
                        <span className="sr-only">Toggle Menu</span>
                    </Button>
                </SheetTrigger>
                <SheetContent side="left" className="w-64 p-4">
                    <div className="flex flex-col h-full">
                        <div className="flex items-center justify-center p-4">
                            <img src="/logo-escritorio.png" alt="Logo" className="h-10" />
                        </div>
                        <div className="flex-1 overflow-auto mt-4">
                            <MainNav isSidebarCollapsed={false} />
                        </div>
                    </div>
                </SheetContent>
            </Sheet>
        );
    }
    
    return (
        <div className={`hidden md:flex flex-col border-r bg-background transition-all duration-300 ${isSidebarCollapsed ? "w-16" : "w-64"}`}>
            <div className="flex h-16 items-center justify-between p-4">
                {!isSidebarCollapsed && <img src="/logo-escritorio.png" alt="Logo" className="h-10" />}
                <Button variant="ghost" size="icon" onClick={() => setIsSidebarCollapsed(!isSidebarCollapsed)}>
                    <PanelLeft className="h-6 w-6" />
                </Button>
            </div>
            <div className="flex-1 overflow-auto p-2">
                <MainNav isSidebarCollapsed={isSidebarCollapsed} />
            </div>
        </div>
    );
}