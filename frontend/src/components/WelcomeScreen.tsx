// frontend/src/components/WelcomeScreen.tsx
//
// Tela de boas-vindas / "conta pendente". Mostrada pelo ProtectedRoute quando
// o usuário está autenticado mas ainda NÃO tem nenhuma permissão (e não é
// admin) — o caso de todo primeiro acesso via Entra ID. O admin libera as
// permissões na aba Admin > Contas SSO / Usuários; no próximo refresh o
// usuário entra normalmente.

import { useAuth } from '@/hooks/useAuth';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Clock, LogOut, RefreshCw } from 'lucide-react';

const WelcomeScreen = () => {
  const { user, logout, refreshMe } = useAuth();

  return (
    <div className="flex min-h-screen w-full items-center justify-center bg-background px-4">
      <div className="w-full max-w-md space-y-6 text-center">
        <div className="flex flex-col items-center gap-2">
          <img
            src="/brand/flow-wordmark.png"
            alt="Flow by DUNATECH"
            className="h-24 w-auto"
          />
        </div>

        <Card>
          <CardContent className="space-y-4 pt-6">
            <div className="flex justify-center">
              <span className="inline-flex h-14 w-14 items-center justify-center rounded-full bg-blue-50 text-blue-600">
                <Clock className="h-7 w-7" />
              </span>
            </div>

            <h1 className="text-xl font-semibold text-fg-strong">
              Conta criada com sucesso!
            </h1>

            <p className="text-sm text-muted-foreground">
              {user?.name ? <>Olá, <strong>{user.name}</strong>. </> : null}
              Seu acesso pela Microsoft foi reconhecido e sua conta está{' '}
              <strong>aguardando liberação do administrador</strong>.
            </p>
            <p className="text-sm text-muted-foreground">
              Assim que suas permissões forem liberadas, você poderá usar o sistema.
            </p>

            {user?.email ? (
              <p className="rounded-md bg-muted px-3 py-2 font-mono text-xs text-muted-foreground">
                {user.email}
              </p>
            ) : null}

            <div className="flex gap-2 pt-2">
              <Button variant="outline" className="flex-1" onClick={() => refreshMe()}>
                <RefreshCw className="mr-2 h-4 w-4" /> Já fui liberado
              </Button>
              <Button variant="ghost" className="flex-1" onClick={logout}>
                <LogOut className="mr-2 h-4 w-4" /> Sair
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
};

export default WelcomeScreen;
