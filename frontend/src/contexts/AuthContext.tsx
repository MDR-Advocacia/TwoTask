// frontend/src/contexts/AuthContext.tsx

import { createContext, useState, ReactNode, useEffect } from 'react';

// ... (interfaces User e AuthContextType permanecem as mesmas) ...
interface User {
  id: number;
  external_id: number;
  name: string;
  email: string;
}

interface AuthContextType {
  isAuthenticated: boolean;
  user: User | null;
  token: string | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  isLoading: boolean;
}

// Exporta o contexto para que o hook externo possa usá-lo
export const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider = ({ children }: { children: ReactNode }) => {
  // ... (toda a lógica interna de useState, useEffect, login e logout permanece EXATAMENTE a mesma) ...
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const loadUserFromToken = async () => {
      const storedToken = localStorage.getItem('authToken');
      if (storedToken) {
        try {
          const userResponse = await fetch('/api/v1/users/me', {
            headers: {
              Authorization: `Bearer ${storedToken}`,
            },
          });
          if (!userResponse.ok) {
            throw new Error('Sessão inválida ou expirada');
          }
          const userData: User = await userResponse.json();
          setUser(userData);
          setToken(storedToken);
        } catch (error) {
          console.error("Erro ao validar token:", error);
          localStorage.removeItem('authToken');
          setUser(null);
          setToken(null);
        }
      }
      setIsLoading(false);
    };
    loadUserFromToken();
  }, []);

  const login = async (email: string, password: string) => {
    setIsLoading(true);
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

// A função useAuth foi MOVIDA para /hooks/useAuth.ts