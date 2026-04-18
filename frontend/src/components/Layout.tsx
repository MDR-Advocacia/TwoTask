import { PropsWithChildren, useMemo } from "react";
import { Link, NavLink, useNavigate } from "react-router-dom";
import {
  CircleUser,
  Clock,
  FileUp,
  Home,
  ListChecks,
  LogOut,
  Menu,
  Newspaper,
  Settings,
  Users,
} from "lucide-react";

import { useAuth } from "@/hooks/useAuth";
import { Button } from "./ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "./ui/dropdown-menu";
import { Sheet, SheetContent, SheetTrigger } from "./ui/sheet";

type Permission = 'canScheduleBatch' | 'canUsePublications' | 'isAdmin';

interface NavItem {
  to: string;
  icon: React.ElementType;
  label: string;
  requirePermission?: Permission;
}

interface NavSection {
  title?: string;
  items: NavItem[];
}

export default function Layout({ children }: PropsWithChildren) {
  const { user, logout, canScheduleBatch, canUsePublications, isAdmin } = useAuth();
  const navigate = useNavigate();

  const hasPermission = (perm?: Permission) => {
    if (!perm) return true;
    if (perm === 'canScheduleBatch') return canScheduleBatch;
    if (perm === 'canUsePublications') return canUsePublications;
    if (perm === 'isAdmin') return isAdmin;
    return false;
  };

  const baseSections: NavSection[] = [
    {
      items: [
        { to: "/", icon: Home, label: "Dashboard" },
      ],
    },
    {
      title: "Criação de Tarefas",
      items: [
        { to: "/tasks/spreadsheet-batch", icon: FileUp, label: "Tarefas por Planilha", requirePermission: 'canScheduleBatch' },
        { to: "/batches", icon: ListChecks, label: "Acompanhamento de Lotes", requirePermission: 'canScheduleBatch' },
      ],
    },
    {
      title: "Tratamento de Publicações",
      items: [
        { to: "/automations", icon: Clock, label: "Agendamentos", requirePermission: 'canUsePublications' },
        { to: "/publications", icon: Newspaper, label: "Publicações Legal One", requirePermission: 'canUsePublications' },
        { to: "/publications/treatment", icon: ListChecks, label: "Tratamento Web", requirePermission: 'canUsePublications' },
        { to: "/publications/templates", icon: Settings, label: "Templates de Agendamento", requirePermission: 'canUsePublications' },
      ],
    },
    {
      items: [
        { to: "/admin", icon: Users, label: "Administração", requirePermission: 'isAdmin' },
      ],
    },
  ];

  const visibleSections = useMemo(() => {
    return baseSections
      .map(sec => ({ ...sec, items: sec.items.filter(it => hasPermission(it.requirePermission)) }))
      .filter(sec => sec.items.length > 0);
  }, [canScheduleBatch, canUsePublications, isAdmin]);

  const handleLogout = () => {
    logout();
    navigate("/login");
  };

  const NavContent = () => (
    <nav className="grid items-start px-2 text-sm font-medium lg:px-4">
      {visibleSections.map((section, idx) => (
        <div key={section.title ?? `sec-${idx}`} className={idx > 0 ? "mt-4" : ""}>
          {section.title && (
            <div className="px-3 pb-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/70">
              {section.title}
            </div>
          )}
          {section.items.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-lg px-3 py-2 text-muted-foreground transition-all hover:text-primary ${
                  isActive ? "bg-muted !text-primary" : ""
                }`
              }
            >
              <Icon className="h-4 w-4" />
              {label}
            </NavLink>
          ))}
        </div>
      ))}
    </nav>
  );

  return (
    <div className="grid min-h-screen w-full md:grid-cols-[220px_1fr] lg:grid-cols-[280px_1fr]">
      <div className="hidden border-r bg-muted/40 md:block">
        <div className="flex h-full max-h-screen flex-col gap-2">
          <div className="flex h-14 items-center border-b px-4 lg:h-[60px] lg:px-6">
            <Link to="/" className="flex items-center gap-2.5 w-full justify-center" title="DunaFlow by DUNATECH">
              <img
                src="/brand/dunaflow-logo.png"
                alt="DUNATECH"
                className="h-6 w-auto object-contain"
              />
              <span className="flow-neon text-2xl leading-none">Flow</span>
            </Link>
          </div>
          <div className="flex-1">
            <NavContent />
          </div>
        </div>
      </div>

      <div className="flex flex-col">
        <header className="sticky top-0 z-40 flex h-14 items-center gap-4 border-b bg-background px-4 lg:h-[60px] lg:px-6">
          <Sheet>
            <SheetTrigger asChild>
              <Button variant="outline" size="icon" className="shrink-0 md:hidden">
                <Menu className="h-5 w-5" />
                <span className="sr-only">Abrir menu de navegacao</span>
              </Button>
            </SheetTrigger>
            <SheetContent side="left" className="flex flex-col">
              <div className="mb-4 flex items-center justify-center gap-2.5">
                <img
                  src="/brand/dunaflow-logo.png"
                  alt="DUNATECH"
                  className="h-6 w-auto object-contain"
                />
                <span className="text-xl italic font-semibold leading-none text-[hsl(var(--dunatech-blue))]">
                  Flow
                </span>
              </div>
              <NavContent />
            </SheetContent>
          </Sheet>

          <div className="w-full flex-1" />

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="secondary" size="icon" className="rounded-full">
                <CircleUser className="h-5 w-5" />
                <span className="sr-only">Abrir menu do usuario</span>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuLabel>{user?.name || "Minha Conta"}</DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuItem asChild>
                <Link to="/me" className="cursor-pointer">
                  <CircleUser className="mr-2 h-4 w-4" />
                  <span>Meu Perfil</span>
                </Link>
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                onClick={handleLogout}
                className="cursor-pointer text-red-600 focus:bg-red-50 focus:text-red-500"
              >
                <LogOut className="mr-2 h-4 w-4" />
                <span>Sair</span>
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </header>

        <main className="flex flex-1 flex-col gap-4 overflow-auto p-4 lg:gap-6 lg:p-6">{children}</main>
      </div>
    </div>
  );
}
