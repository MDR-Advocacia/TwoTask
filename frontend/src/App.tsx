// frontend/src/App.tsx (versão final, refatorada)

import { BrowserRouter as Router, Route, Routes } from 'react-router-dom';

// Componentes de Rota e Layout
import ProtectedRoute from './components/ProtectedRoute'; // Importamos nossa rota protegida

// Páginas
import AdminPage from './pages/AdminPage';
import NotFound from './pages/NotFound';
import Dashboard from './components/Dashboard';
import CreateTaskByTemplatePage from './pages/CreateTaskByTemplatePage';
import CreateTaskByProcessPage from './pages/CreateTaskByProcessPage';
import LoginPage from './pages/LoginPage';

// Contexto de Autenticação
import { AuthProvider } from './contexts/AuthContext';

function App() {
  return (
    <AuthProvider>
      <Router>
        <Routes>
          {/* Rota Pública: Login */}
          <Route path="/login" element={<LoginPage />} />

          {/* Rotas Protegidas */}
          <Route element={<ProtectedRoute />}>
            <Route path="/" element={<Dashboard />} />
            <Route path="/admin" element={<AdminPage />} />
            <Route path="/tasks/template-batch" element={<CreateTaskByTemplatePage />} />
            <Route path="/tasks/by-process" element={<CreateTaskByProcessPage />} />
          </Route>

          {/* Rota para página não encontrada */}
          <Route path="*" element={<NotFound />} />
        </Routes>
      </Router>
    </AuthProvider>
  );
}

export default App;