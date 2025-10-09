// frontend/src/components/Layout.tsx

import { Link, NavLink, useNavigate } from "react-router-dom";
import {
  CircleUser,
  Menu,
  Home,
  Users,
  LogOut,
  FilePlus2,
  FileSearch2
} from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import { PropsWithChildren } from "react";
import { useAuth } from "@/hooks/useAuth";

// 1. Centralizamos os links de navegação em um array para facilitar a manutenção
const navLinks = [
  { to: "/", icon: Home, label: "Dashboard" },
  { to: "/tasks/template-batch", icon: FilePlus2, label: "Tarefas em Lote (IA)" },
  { to: "/tasks/by-process", icon: FileSearch2, label: "Tarefa por Processo" },
  { to: "/admin", icon: Users, label: "Administração" },
];

export default function Layout({ children }: PropsWithChildren) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  const NavContent = () => (
    <nav className="grid items-start px-2 text-sm font-medium lg:px-4">
      {navLinks.map(({ to, icon: Icon, label }) => (
        <NavLink
          key={to}
          to={to}
          className={({ isActive }) =>
            `flex items-center gap-3 rounded-lg px-3 py-2 text-muted-foreground transition-all hover:text-primary ${isActive ? 'bg-muted !text-primary' : ''}`
          }
        >
          <Icon className="h-4 w-4" />
          {label}
        </NavLink>
      ))}
    </nav>
  );

  return (
    // 2. A estrutura principal agora é um grid que divide a tela em sidebar e conteúdo
    <div className="grid min-h-screen w-full md:grid-cols-[220px_1fr] lg:grid-cols-[280px_1fr]">
      {/* --- SIDEBAR PARA DESKTOP --- */}
      <div className="hidden border-r bg-muted/40 md:block">
        <div className="flex h-full max-h-screen flex-col gap-2">
          <div className="flex h-14 items-center border-b px-4 lg:h-[60px] lg:px-6">
            <Link to="/" className="flex items-center gap-2 font-semibold">
              <img src="/logo-escritorio2.png" alt="Logo" className="w-20 h-15" />
              <span className="font-bold text-xl bg-gradient-to-r from-primary to-accent bg-clip-text text-transparent">
                TwoTask
              </span>
            </Link>
          </div>
          <div className="flex-1">
            <NavContent />
          </div>
        </div>
      </div>

      {/* --- CONTEÚDO PRINCIPAL E HEADER MOBILE --- */}
      <div className="flex flex-col">
        <header className="flex h-14 items-center gap-4 border-b bg-muted/40 px-4 lg:h-[60px] lg:px-6 sticky top-0 z-40 bg-background">
          {/* Menu Gaveta para Mobile */}
          <Sheet>
            <SheetTrigger asChild>
              <Button variant="outline" size="icon" className="shrink-0 md:hidden">
                <Menu className="h-5 w-5" />
                <span className="sr-only">Abrir menu de navegação</span>
              </Button>
            </SheetTrigger>
            <SheetContent side="left" className="flex flex-col">
              <div className="flex items-center gap-2 text-lg font-semibold mb-4">
                <img src="/logo-escritorio2.png" alt="Logo" className="w-10 h-10" />
                <span className="font-bold text-xl bg-gradient-to-r from-primary to-accent bg-clip-text text-transparent">
                  TwoTask
                </span>
              </div>
              <NavContent />
            </SheetContent>
          </Sheet>

          <div className="w-full flex-1">
            {/* Espaço para Breadcrumbs ou Título da Página no futuro */}
          </div>

          {/* Menu do Usuário (igual ao que fizemos no passo anterior) */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="secondary" size="icon" className="rounded-full">
                <CircleUser className="h-5 w-5" />
                <span className="sr-only">Abrir menu do usuário</span>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuLabel>{user?.name || 'Minha Conta'}</DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={handleLogout} className="text-red-600 focus:text-red-500 focus:bg-red-50 cursor-pointer">
                <LogOut className="mr-2 h-4 w-4" />
                <span>Sair</span>
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </header>

        {/* O conteúdo da página é renderizado aqui */}
        <main className="flex flex-1 flex-col gap-4 p-4 lg:gap-6 lg:p-6 overflow-auto">
          {children}
        </main>
      </div>
    </div>
  );
}