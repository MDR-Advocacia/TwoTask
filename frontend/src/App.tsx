// frontend/src/App.tsx (versão final, refatorada)

import { BrowserRouter as Router, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useState, useEffect, useContext } from 'react';

// Componentes de Rota e Layout
import ProtectedRoute from './components/ProtectedRoute';
import { ChangePasswordDialog } from './components/ChangePasswordDialog';

// Páginas
import AdminPage from './pages/AdminPage';
import NotFound from './pages/NotFound';
import DashboardHome from './pages/DashboardHome';
import CreateTaskByTemplatePage from './pages/CreateTaskByTemplatePage';
import LoginPage from './pages/LoginPage';
import CreateTaskFromSpreadsheetPage from './pages/CreateTaskFromSpreadsheetPage';
import PublicationsPage from './pages/PublicationsPage';
import TaskTemplatesPage from './pages/TaskTemplatesPage';
import AutomationsPage from './pages/AutomationsPage';
import ProfilePage from './pages/ProfilePage';
import BatchExecutionsPage from './pages/BatchExecutionsPage';
import PublicationTreatmentPage from './pages/PublicationTreatmentPage';
import LookupByCnjPage from './pages/LookupByCnjPage';
import PrazosIniciaisPage from './pages/PrazosIniciaisPage';
import PrazosIniciaisTreatmentPage from './pages/PrazosIniciaisTreatmentPage';
import PrazosIniciaisTemplatesAdminPage from './pages/PrazosIniciaisTemplatesAdminPage';
import PatrocinioRelatorioPage from './pages/PatrocinioRelatorioPage';
import AjusPage from './pages/AjusPage';

// Contexto de Autenticação
import { AuthProvider, AuthContext } from './contexts/AuthContext';
import { Toaster } from '@/components/ui/toaster';

const queryClient = new QueryClient();

function AppContent() {
  const authContext = useContext(AuthContext);
  const [showChangePasswordDialog, setShowChangePasswordDialog] = useState(false);

  useEffect(() => {
    if (authContext?.mustChangePassword && authContext.isAuthenticated) {
      setShowChangePasswordDialog(true);
    }
  }, [authContext?.mustChangePassword, authContext?.isAuthenticated]);

  return (
    <>
      <Router>
        <Routes>
          {/* Rota Pública: Login */}
          <Route path="/login" element={<LoginPage />} />

          {/* Rotas Protegidas */}
          <Route element={<ProtectedRoute />}>
            <Route path="/" element={<DashboardHome />} />
            <Route path="/admin" element={<AdminPage />} />
            <Route path="/me" element={<ProfilePage />} />
            <Route path="/tasks/template-batch" element={<CreateTaskByTemplatePage />} />
            <Route path="/tasks/spreadsheet-batch" element={<CreateTaskFromSpreadsheetPage />} />
            <Route path="/publications" element={<PublicationsPage />} />
            <Route path="/publications/lookup" element={<LookupByCnjPage />} />
            <Route path="/publications/treatment" element={<PublicationTreatmentPage />} />
            <Route path="/publications/templates" element={<TaskTemplatesPage />} />
            <Route path="/automations" element={<AutomationsPage />} />
            <Route path="/batches" element={<BatchExecutionsPage />} />
            <Route path="/prazos-iniciais" element={<PrazosIniciaisPage />} />
            <Route path="/prazos-iniciais/treatment" element={<PrazosIniciaisTreatmentPage />} />
            <Route
              path="/prazos-iniciais/templates"
              element={<PrazosIniciaisTemplatesAdminPage />}
            />
            <Route
              path="/prazos-iniciais/patrocinio/relatorio"
              element={<PatrocinioRelatorioPage />}
            />
            <Route path="/ajus" element={<AjusPage />} />
          </Route>

          {/* Rota para página não encontrada */}
          <Route path="*" element={<NotFound />} />
        </Routes>
      </Router>

      <Toaster />

      <ChangePasswordDialog
        isOpen={showChangePasswordDialog}
        isMandatory={authContext?.mustChangePassword ?? false}
        onPasswordChanged={() => {
          setShowChangePasswordDialog(false);
          // O JWT atual ainda carrega must_change_password=true.
          // Força logout para que o próximo login emita um token com a claim atualizada.
          if (authContext?.mustChangePassword) {
            authContext?.logout();
          } else {
            authContext?.refreshMe();
          }
        }}
      />
    </>
  );
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <AppContent />
      </AuthProvider>
    </QueryClientProvider>
  );
}

export default App;
