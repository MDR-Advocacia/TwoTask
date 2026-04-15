// frontend/src/contexts/AuthContext.tsx

import { createContext, useState, ReactNode, useEffect } from 'react';

interface User {
  id: number;
  external_id?: number;
  name: string;
  email: string;
  role?: string;
  can_schedule_batch?: boolean;
  can_use_publications?: boolean;
  must_change_password?: boolean;
}

interface TokenData {
  sub: string;
  role: string;
  can_schedule_batch: boolean;
  can_use_publications: boolean;
  must_change_password: boolean;
  exp: number;
}

interface AuthContextType {
  isAuthenticated: boolean;
  user: User | null;
  token: string | null;
  tokenData: TokenData | null;
  mustChangePassword: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  isLoading: boolean;
  canScheduleBatch: boolean;
  canUsePublications: boolean;
  isAdmin: boolean;
  refreshMe: () => Promise<void>;
}

// Exporta o contexto para que o hook externo possa usá-lo
export const AuthContext = createContext<AuthContextType | undefined>(undefined);

// Helper to decode JWT
function decodeToken(token: string): TokenData | null {
  try {
    const parts = token.split('.');
    if (parts.length !== 3) return null;
    const decoded = JSON.parse(atob(parts[1]));
    return decoded;
  } catch (e) {
    return null;
  }
}

export const AuthProvider = ({ children }: { children: ReactNode }) => {
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [tokenData, setTokenData] = useState<TokenData | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const refreshMe = async () => {
    const storedToken = localStorage.getItem('authToken');
    if (storedToken) {
      try {
        const userResponse = await fetch('/api/v1/me', {
          headers: {
            Authorization: `Bearer ${storedToken}`,
          },
        });
        if (!userResponse.ok) {
          throw new Error('Falha ao atualizar dados do usuário');
        }
        const userData: User = await userResponse.json();
        setUser(userData);
      } catch (error) {
        console.error("Erro ao atualizar usuário:", error);
      }
    }
  };

  useEffect(() => {
    const loadUserFromToken = async () => {
      const storedToken = localStorage.getItem('authToken');
      if (storedToken) {
        try {
          const decoded = decodeToken(storedToken);
          setTokenData(decoded);
          const userResponse = await fetch('/api/v1/me', {
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
          setTokenData(null);
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
      const decoded = decodeToken(receivedToken);
      setToken(receivedToken);
      setTokenData(decoded);
      localStorage.setItem('authToken', receivedToken);
      const userResponse = await fetch('/api/v1/me', {
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
    setTokenData(null);
    localStorage.removeItem('authToken');
  };

  const value = {
    isAuthenticated: !!token,
    user,
    token,
    tokenData,
    mustChangePassword: tokenData?.must_change_password ?? false,
    login,
    logout,
    isLoading,
    canScheduleBatch: tokenData?.can_schedule_batch ?? false,
    canUsePublications: tokenData?.can_use_publications ?? true,
    isAdmin: tokenData?.role === 'admin',
    refreshMe,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

// A função useAuth foi MOVIDA para /hooks/useAuth.ts