// frontend/src/hooks/useAuth.ts

import { useContext } from 'react';
// Importaremos o AuthContext diretamente do seu arquivo de origem
import { AuthContext } from '@/contexts/AuthContext';

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth deve ser usado dentro de um AuthProvider');
  }
  return context;
};