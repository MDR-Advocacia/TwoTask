import { BatchExecution } from "@/types/api"; 

// A variável VITE_API_BASE_URL deve ser configurada no seu ambiente, 
// mas usamos um fallback para o desenvolvimento local.
//const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

// --- ESSA FUNÇÃO FICA INTACTA (Para não quebrar a listagem) ---
export async function fetchBatchExecutions(): Promise<BatchExecution[]> {
  try {
    // Mantendo a rota original que você disse que funciona
    const response = await fetch(`/api/v1/dashboard/batch-executions`);
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    const data: BatchExecution[] = await response.json();
    return data;
  } catch (error) {
    console.error("Falha ao buscar execuções de lote:", error);
    throw error;
  }
}

// --- ESSA FUNÇÃO É ATUALIZADA (Para usar a lógica nova do Smart Retry) ---
export async function retryBatchExecution(
    executionId: number, 
    itemIds: number[] | null = null // <--- Aceita a lista de IDs opcional
): Promise<{ message: string }> {
  try {
    // ATENÇÃO: Apontamos para a rota '/tasks/' porque foi no arquivo 'tasks.py' 
    // que implementamos o suporte a JSON { item_ids: [...] }.
    // Se a rota antiga (/admin/...) não tiver sido atualizada no backend, ela vai ignorar os IDs.
    const url = `/api/v1/tasks/executions/${executionId}/retry`;
    
    // Prepara o corpo do request
    const options: RequestInit = {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
    };

    // Se tiver IDs para filtrar, enviamos no corpo. Se não, corpo vazio (null) reprocessa tudo.
    if (itemIds && itemIds.length > 0) {
      options.body = JSON.stringify({ item_ids: itemIds });
    }

    const response = await fetch(url, options);

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