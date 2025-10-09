import React, { createContext, useState, useContext, ReactNode } from 'react';

// Interface para os dados do usuário que queremos armazenar
interface User {
  id: number;
  external_id: number;
  name: string;
  email: string;
}

// Interface para o que o nosso contexto irá fornecer
interface AuthContextType {
  isAuthenticated: boolean;
  user: User | null;
  token: string | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  isLoading: boolean;
}

// Criando o contexto com um valor padrão
const AuthContext = createContext<AuthContextType | undefined>(undefined);

// O componente Provedor que irá envolver nossa aplicação
export const AuthProvider = ({ children }: { children: ReactNode }) => {
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const login = async (email: string, password: string) => {
    setIsLoading(true);

    // O FastAPI espera dados de formulário, não JSON, para o login OAuth2
    const formData = new URLSearchParams();
    formData.append('username', email);
    formData.append('password', password);

    try {
      const response = await fetch('/api/v1/auth/token', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded',
        },
        body: formData.toString(),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Falha na autenticação');
      }

      const data = await response.json();
      const receivedToken = data.access_token;

      setToken(receivedToken);
      localStorage.setItem('authToken', receivedToken);

      // Após obter o token, buscamos os dados do usuário
      const userResponse = await fetch('/api/v1/users/me', {
        headers: {
          Authorization: `Bearer ${receivedToken}`,
        },
      });

      if (!userResponse.ok) {
        throw new Error('Não foi possível buscar os dados do usuário.');
      }

      const userData: User = await userResponse.json();
      setUser(userData);

    } catch (error) {
      // Se ocorrer um erro, limpamos o estado e relançamos o erro
      // para que a página de login possa exibi-lo.
      logout();
      throw error;
    } finally {
      setIsLoading(false);
    }
  };

  const logout = () => {
    setUser(null);
    setToken(null);
    localStorage.removeItem('authToken');
  };

  const value = {
    isAuthenticated: !!token,
    user,
    token,
    login,
    logout,
    isLoading,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

// Hook customizado para facilitar o uso do contexto
export const useAuth = () => {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth deve ser usado dentro de um AuthProvider');
  }
  return context;
};