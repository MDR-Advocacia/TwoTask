// frontend/src/App.tsx

import { BrowserRouter as Router, Route, Routes } from 'react-router-dom';
import Layout from './components/Layout';
import AdminPage from './pages/AdminPage';
import NotFound from './pages/NotFound';
import Dashboard from './components/Dashboard'; // Importando o Dashboard diretamente
import CreateTaskByTemplatePage from './pages/CreateTaskByTemplatePage';
import CreateTaskByProcessPage from './pages/CreateTaskByProcessPage';
import LoginPage from './pages/LoginPage';

function App() {
  return (
    <Router>
      <Layout>
        <Routes>
          {/* Rotas antigas atualizadas */}
          <Route path="/" element={<Dashboard />} />
          <Route path="/admin" element={<AdminPage />} />
          
          {/* Novas rotas para as páginas de criação de tarefas */}
          <Route path="/tasks/template-batch" element={<CreateTaskByTemplatePage />} />
          <Route path="/tasks/by-process" element={<CreateTaskByProcessPage />} />

          {/* Rota para página não encontrada */}
          <Route path="*" element={<NotFound />} />

          {/* --- NOVA ROTA DE LOGIN --- */}
          <Route path="/login" element={<LoginPage />} />

        </Routes>
      </Layout>
    </Router>
  );
}

export default App;