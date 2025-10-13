// frontend/src/services/api.ts
import { BatchExecution } from "@/types/api"; // Importando nossa nova interface

// A variável VITE_API_BASE_URL deve ser configurada no seu ambiente, 
// mas usamos um fallback para o desenvolvimento local.
//const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

export async function fetchBatchExecutions(): Promise<BatchExecution[]> {
  try {
    const response = await fetch(`/api/v1/dashboard/batch-executions`);
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    const data: BatchExecution[] = await response.json();
    return data;
  } catch (error) {
    console.error("Falha ao buscar execuções de lote:", error);
    // Lançar o erro novamente permite que o componente que chama a função possa tratá-lo (ex: exibir uma mensagem de erro na UI)
    throw error;
  }
}

// --- NOVA FUNÇÃO PARA RETRY ---
export async function retryBatchExecution(executionId: number): Promise<{ message: string }> {
  try {
    const response = await fetch(`/api/v1/admin/batch-executions/${executionId}/retry`, {
      method: 'POST',
    });
    if (!response.ok) {
      const errorData = await response.json();
      throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
    }
    return response.json();
  } catch (error) {
    console.error(`Falha ao tentar reprocessar o lote ${executionId}:`, error);
    throw error;
  }
}