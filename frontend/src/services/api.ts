import { apiFetch } from "@/lib/api-client";
import {
  BatchExecution,
  LegalOnePositionFixControlResponse,
  LegalOnePositionFixStatus,
  PublicationTreatmentControlResponse,
  PublicationTreatmentMonitor,
  PublicationTreatmentRun,
  PublicationTreatmentStartResponse,
} from "@/types/api";


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


export async function fetchLegalOnePositionFixStatus(): Promise<LegalOnePositionFixStatus> {
  const response = await apiFetch("/api/v1/monitor/legal-one-position-fix/status");
  return expectJson<LegalOnePositionFixStatus>(response);
}


export async function updateLegalOnePositionFixControl(
  action: "pause" | "resume",
): Promise<LegalOnePositionFixControlResponse> {
  const response = await apiFetch("/api/v1/monitor/legal-one-position-fix/control", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ action }),
  });
  return expectJson<LegalOnePositionFixControlResponse>(response);
}


export async function fetchPublicationTreatmentMonitor(
  signal?: AbortSignal,
): Promise<PublicationTreatmentMonitor> {
  const response = await apiFetch("/api/v1/publications/treatment/monitor", { signal });
  return expectJson<PublicationTreatmentMonitor>(response);
}


export async function fetchPublicationTreatmentRuns(
  signal?: AbortSignal,
): Promise<PublicationTreatmentRun[]> {
  const response = await apiFetch("/api/v1/publications/treatment/runs", { signal });
  return expectJson<PublicationTreatmentRun[]>(response);
}


export async function startPublicationTreatmentRun(): Promise<PublicationTreatmentStartResponse> {
  const response = await apiFetch("/api/v1/publications/treatment/runs/start", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({}),
  });
  return expectJson<PublicationTreatmentStartResponse>(response);
}


export async function retryPublicationTreatmentItem(
  itemId: number,
): Promise<PublicationTreatmentStartResponse> {
  const response = await apiFetch(`/api/v1/publications/treatment/items/${itemId}/retry`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({}),
  });
  return expectJson<PublicationTreatmentStartResponse>(response);
}


export async function updatePublicationTreatmentRunControl(
  runId: number,
  action: "pause" | "resume",
): Promise<PublicationTreatmentControlResponse> {
  const response = await apiFetch(`/api/v1/publications/treatment/runs/${runId}/control`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ action }),
  });
  return expectJson<PublicationTreatmentControlResponse>(response);
}
