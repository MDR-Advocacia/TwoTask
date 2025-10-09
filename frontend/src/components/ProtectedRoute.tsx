// frontend/src/components/ProtectedRoute.tsx

import { Navigate, Outlet } from 'react-router-dom';
import { useAuth } from '@/hooks/useAuth'
import Layout from './Layout';
import { Loader2 } from 'lucide-react';

const ProtectedRoute = () => {
  const { isAuthenticated, isLoading } = useAuth();

  // Se ainda estivermos verificando a autenticação (ex: ao recarregar a página),
  // mostramos um indicador de carregamento.
  if (isLoading) {
    return (
      <div className="flex h-screen w-full items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  // Se o usuário estiver autenticado, renderizamos o Layout principal
  // e o conteúdo da rota filha através do <Outlet />.
  if (isAuthenticated) {
    return (
      <Layout>
        <Outlet />
      </Layout>
    );
  }

  // Se não estiver autenticado, redirecionamos para a página de login.
  return <Navigate to="/login" replace />;
};

export default ProtectedRoute;