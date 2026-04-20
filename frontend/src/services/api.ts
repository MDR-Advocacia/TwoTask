import { apiFetch } from "@/lib/api-client";
import {
  BatchExecution,
  LegalOnePositionFixControlResponse,
  LegalOnePositionFixStatus,
  PrazoInicialIntakeDetail,
  PrazoInicialIntakeFilters,
  PrazoInicialIntakeListResponse,
  PrazoInicialIntakeSummary,
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


export async function fetchPublicationTreatmentMonitor(): Promise<PublicationTreatmentMonitor> {
  const response = await apiFetch("/api/v1/publications/treatment/monitor");
  return expectJson<PublicationTreatmentMonitor>(response);
}


export async function fetchPublicationTreatmentRuns(): Promise<PublicationTreatmentRun[]> {
  const response = await apiFetch("/api/v1/publications/treatment/runs");
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


// ─── Prazos Iniciais ──────────────────────────────────────────────────

export async function fetchPrazosIniciaisIntakes(
  filters: PrazoInicialIntakeFilters = {},
): Promise<PrazoInicialIntakeListResponse> {
  const params = new URLSearchParams();
  if (filters.status) params.set("status", filters.status);
  if (filters.cnj_number) params.set("cnj_number", filters.cnj_number);
  if (typeof filters.office_id === "number") {
    params.set("office_id", String(filters.office_id));
  }
  if (typeof filters.limit === "number") params.set("limit", String(filters.limit));
  if (typeof filters.offset === "number") params.set("offset", String(filters.offset));

  const qs = params.toString();
  const response = await apiFetch(
    `/api/v1/prazos-iniciais/intakes${qs ? `?${qs}` : ""}`,
  );
  return expectJson<PrazoInicialIntakeListResponse>(response);
}


export async function fetchPrazoInicialDetail(
  intakeId: number,
): Promise<PrazoInicialIntakeDetail> {
  const response = await apiFetch(`/api/v1/prazos-iniciais/intakes/${intakeId}`);
  return expectJson<PrazoInicialIntakeDetail>(response);
}


export async function reprocessarPrazoInicialCnj(
  intakeId: number,
): Promise<PrazoInicialIntakeSummary> {
  const response = await apiFetch(
    `/api/v1/prazos-iniciais/intakes/${intakeId}/reprocessar-cnj`,
    { method: "POST" },
  );
  return expectJson<PrazoInicialIntakeSummary>(response);
}


export async function cancelarPrazoInicial(
  intakeId: number,
): Promise<PrazoInicialIntakeSummary> {
  const response = await apiFetch(
    `/api/v1/prazos-iniciais/intakes/${intakeId}/cancelar`,
    { method: "POST" },
  );
  return expectJson<PrazoInicialIntakeSummary>(response);
}


/**
 * Constrói a URL absoluta do PDF do intake (usada como `href` do link "Ver PDF").
 * O browser inclui o cookie/sessão via padrão fetch — mas neste app a auth é por
 * Bearer em header, então o link abre numa nova aba *apenas* se o usuário estiver
 * autenticado; caso contrário baixa o JSON de erro. Para preview confiável, usar
 * `fetchPrazoInicialPdfBlob` + object URL.
 */
export function prazoInicialPdfUrl(intakeId: number): string {
  return `/api/v1/prazos-iniciais/intakes/${intakeId}/pdf`;
}


export async function fetchPrazoInicialPdfBlob(intakeId: number): Promise<Blob> {
  const response = await apiFetch(prazoInicialPdfUrl(intakeId));
  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
  }
  return response.blob();
}
