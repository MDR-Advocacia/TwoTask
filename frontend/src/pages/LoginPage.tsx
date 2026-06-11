import { useState } from 'react';
import { useNavigate } from 'react-router-dom'; // Para redirecionar o usuário
import { useAuth } from '@/hooks/useAuth'
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { LogIn, AlertCircle } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { DunaFlowMark } from '@/components/DunaFlowMark';

// Base do oauth2-proxy (Microsoft Entra ID). Em produção fica em
// auth.dunatecnologia.com; sobrescrevível por env pra outros ambientes.
const SSO_AUTHORIZE_BASE =
  import.meta.env.VITE_SSO_AUTHORIZE_BASE || 'https://auth.dunatecnologia.com';

// Logo oficial da Microsoft (4 quadrados) — lucide não tem.
const MicrosoftIcon = ({ className }: { className?: string }) => (
  <svg className={className} viewBox="0 0 21 21" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
    <rect x="1" y="1" width="9" height="9" fill="#F25022" />
    <rect x="11" y="1" width="9" height="9" fill="#7FBA00" />
    <rect x="1" y="11" width="9" height="9" fill="#00A4EF" />
    <rect x="11" y="11" width="9" height="9" fill="#FFB900" />
  </svg>
);

const LoginPage = () => {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);

  const { login, isLoading } = useAuth(); // Pegamos a função login e o estado de loading do contexto
  const navigate = useNavigate(); // Hook para navegar programaticamente

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);

    try {
      await login(email, password);
      // Se o login for bem-sucedido, navega para o dashboard
      navigate('/');
    } catch (err) {
      if (err instanceof Error) {
        setError(err.message);
      } else {
        setError('Ocorreu um erro inesperado.');
      }
    }
  };

  // Inicia o fluxo SSO: redireciona pro oauth2-proxy/Entra e volta pra cá com
  // a sessão (cookie .dunatecnologia.com). No retorno, o AuthContext chama
  // /api/v1/auth/sso/session e loga automaticamente.
  const handleMicrosoftLogin = () => {
    const rd = `${window.location.origin}/`;
    window.location.href = `${SSO_AUTHORIZE_BASE}/oauth2/start?rd=${encodeURIComponent(rd)}`;
  };

  return (
    <div className="flex items-center justify-center min-h-screen bg-background px-4">
      <div className="w-full max-w-sm space-y-6">
        <div className="flex flex-col items-center gap-2">
          <DunaFlowMark size="lg" className="text-[hsl(var(--dunatech-navy))]" />
          <p className="text-xs font-medium uppercase tracking-[0.2em] text-muted-foreground">
            by DUNATECH
          </p>
        </div>
        <Card className="w-full">
          <CardHeader>
            <CardTitle className="text-2xl text-center">Entrar</CardTitle>
            <CardDescription className="text-center">
              Acesse com seu e-mail corporativo
            </CardDescription>
          </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit}>
            <div className="grid gap-4">
              <div className="grid gap-2">
                <Label htmlFor="email">E-mail</Label>
                <Input
                  id="email"
                  type="email"
                  placeholder="seu@email.com"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  disabled={isLoading}
                />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="password">Senha</Label>
                <Input
                  id="password"
                  type="password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  disabled={isLoading}
                />
              </div>
              {error && (
                <Alert variant="destructive">
                  <AlertCircle className="h-4 w-4" />
                  <AlertTitle>Falha no Login</AlertTitle>
                  <AlertDescription>
                    {error}
                  </AlertDescription>
                </Alert>
              )}
              <Button type="submit" className="w-full" disabled={isLoading}>
                {isLoading ? 'Entrando...' : <> <LogIn className="mr-2 h-4 w-4" /> Entrar </>}
              </Button>
            </div>
          </form>

          <div className="mt-4 grid gap-4">
            <div className="relative">
              <div className="absolute inset-0 flex items-center">
                <span className="w-full border-t" />
              </div>
              <div className="relative flex justify-center text-xs uppercase">
                <span className="bg-card px-2 text-muted-foreground">ou</span>
              </div>
            </div>
            <Button
              type="button"
              variant="outline"
              className="w-full"
              onClick={handleMicrosoftLogin}
              disabled={isLoading}
            >
              <MicrosoftIcon className="mr-2 h-4 w-4" />
              Entrar com Microsoft
            </Button>
          </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
};

export default LoginPage;