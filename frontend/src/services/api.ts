import { apiFetch } from "@/lib/api-client";
import { BatchExecution } from "@/types/api";


async function expectJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
  }
  return response.json();
}


export async function fetchBatchExecutions(): Promise<BatchExecution[]> {
  const response = await apiFetch("/api/v1/dashboard/batch-executions");
  return expectJson<BatchExecution[]>(response);
}


export async function retryBatchExecution(
  executionId: number,
  itemIds: number[] | null = null,
): Promise<{ message: string }> {
  const options: RequestInit = {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
  };

  if (itemIds && itemIds.length > 0) {
    options.body = JSON.stringify({ item_ids: itemIds });
  }

  const response = await apiFetch(`/api/v1/tasks/executions/${executionId}/retry`, options);
  return expectJson<{ message: string }>(response);
}


export async function pauseBatchExecution(executionId: number): Promise<{ message: string; status: string }> {
  const response = await apiFetch(`/api/v1/tasks/executions/${executionId}/pause`, { method: "POST" });
  return expectJson<{ message: string; status: string }>(response);
}


export async function resumeBatchExecution(executionId: number): Promise<{ message: string; status: string }> {
  const response = await apiFetch(`/api/v1/tasks/executions/${executionId}/resume`, { method: "POST" });
  return expectJson<{ message: string; status: string }>(response);
}


export async function cancelBatchExecution(executionId: number): Promise<{ message: string; status: string }> {
  const response = await apiFetch(`/api/v1/tasks/executions/${executionId}/cancel`, { method: "POST" });
  return expectJson<{ message: string; status: string }>(response);
}


export async function downloadBatchErrorReport(executionId: number): Promise<Blob> {
  const response = await apiFetch(`/api/v1/tasks/executions/${executionId}/error-report`);
  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
  }
  return response.blob();
}
