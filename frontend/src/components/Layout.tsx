import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Settings } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

interface LayoutProps {
  children: React.ReactNode;
  navButtons?: React.ReactNode;
}

const Layout = ({ children, navButtons }: LayoutProps) => {
  return (
    <div className="min-h-screen">
      {/* Navigation */}
      <nav className="glass-card rounded-none border-x-0 border-t-0 sticky top-0 z-50">
        <div className="container mx-auto px-6 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
            <Link to="/" className="flex items-center gap-2">
              <img
                src="/logo-escritorio2.png"
                alt="Logo do Escritório"
                className="w-15 h-12 square object-cover"
              />
              <span className="font-bold text-xl bg-gradient-to-r from-primary to-accent bg-clip-text text-transparent">
                OneTask
              </span>
              </Link>
            </div>

            <div className="flex items-center gap-2">
              {navButtons}
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
        {children}
      </main>
    </div>
  );
};

export default Layout;