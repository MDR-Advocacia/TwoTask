import { apiFetch } from "@/lib/api-client";
import {
  BatchExecution,
  LegalOnePositionFixControlResponse,
  LegalOnePositionFixStatus,
  PrazoInicialEnums,
  PrazoInicialIntakeDetail,
  PrazoInicialIntakeFilters,
  PrazoInicialIntakeListResponse,
  PrazoInicialIntakeSummary,
  PrazoInicialLegacyTaskCancelQueueListResponse,
  PrazoInicialLegacyTaskCircuitBreakerResetResponse,
  PrazoInicialLegacyTaskQueueFilters,
  PrazoInicialLegacyTaskQueueItemActionResponse,
  PrazoInicialLegacyTaskQueueMetrics,
  PrazoInicialLegacyTaskQueueProcessResponse,
  PrazoInicialSchedulingConfirmationPayload,
  PrazoInicialSchedulingConfirmationResponse,
  PrazoInicialTaskTemplate,
  PrazoInicialTaskTemplateCreatePayload,
  PrazoInicialTaskTemplateFilters,
  PrazoInicialTaskTemplateListResponse,
  PrazoInicialTaskTemplateUpdatePayload,
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
export async function confirmarAgendamentoPrazoInicial(
  intakeId: number,
  payload: PrazoInicialSchedulingConfirmationPayload,
): Promise<PrazoInicialSchedulingConfirmationResponse> {
  const response = await apiFetch(
    `/api/v1/prazos-iniciais/intakes/${intakeId}/confirmar-agendamento`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    },
  );
  return expectJson<PrazoInicialSchedulingConfirmationResponse>(response);
}


function _buildLegacyQueueParams(
  filters: PrazoInicialLegacyTaskQueueFilters,
): URLSearchParams {
  const params = new URLSearchParams();
  if (filters.queue_status) params.set("queue_status", filters.queue_status);
  if (typeof filters.limit === "number") params.set("limit", String(filters.limit));
  if (typeof filters.intake_id === "number") {
    params.set("intake_id", String(filters.intake_id));
  }
  if (filters.cnj_number) params.set("cnj_number", filters.cnj_number);
  if (filters.since) params.set("since", filters.since);
  if (filters.until) params.set("until", filters.until);
  return params;
}


export async function fetchPrazosIniciaisLegacyTaskCancelQueue(
  filters: PrazoInicialLegacyTaskQueueFilters = {},
): Promise<PrazoInicialLegacyTaskCancelQueueListResponse> {
  const qs = _buildLegacyQueueParams(filters).toString();
  const response = await apiFetch(
    `/api/v1/prazos-iniciais/legacy-task-cancel-queue${qs ? `?${qs}` : ""}`,
  );
  return expectJson<PrazoInicialLegacyTaskCancelQueueListResponse>(response);
}


export async function processPrazosIniciaisLegacyTaskCancelQueue(
  limit = 20,
): Promise<PrazoInicialLegacyTaskQueueProcessResponse> {
  const response = await apiFetch(
    `/api/v1/prazos-iniciais/legacy-task-cancel-queue/process-pending?limit=${limit}`,
    { method: "POST" },
  );
  return expectJson<PrazoInicialLegacyTaskQueueProcessResponse>(response);
}


export async function fetchPrazosIniciaisLegacyTaskCancelQueueMetrics(
  hours = 24,
): Promise<PrazoInicialLegacyTaskQueueMetrics> {
  const response = await apiFetch(
    `/api/v1/prazos-iniciais/legacy-task-cancel-queue/metrics?hours=${hours}`,
  );
  return expectJson<PrazoInicialLegacyTaskQueueMetrics>(response);
}


export async function reprocessPrazosIniciaisLegacyTaskCancelItem(
  itemId: number,
): Promise<PrazoInicialLegacyTaskQueueItemActionResponse> {
  const response = await apiFetch(
    `/api/v1/prazos-iniciais/legacy-task-cancel-queue/items/${itemId}/reprocessar`,
    { method: "POST" },
  );
  return expectJson<PrazoInicialLegacyTaskQueueItemActionResponse>(response);
}


export async function cancelPrazosIniciaisLegacyTaskCancelItem(
  itemId: number,
): Promise<PrazoInicialLegacyTaskQueueItemActionResponse> {
  const response = await apiFetch(
    `/api/v1/prazos-iniciais/legacy-task-cancel-queue/items/${itemId}/cancelar`,
    { method: "POST" },
  );
  return expectJson<PrazoInicialLegacyTaskQueueItemActionResponse>(response);
}


export async function resetPrazosIniciaisLegacyTaskCancelCircuitBreaker(): Promise<PrazoInicialLegacyTaskCircuitBreakerResetResponse> {
  const response = await apiFetch(
    "/api/v1/prazos-iniciais/legacy-task-cancel-queue/circuit-breaker/reset",
    { method: "POST" },
  );
  return expectJson<PrazoInicialLegacyTaskCircuitBreakerResetResponse>(response);
}


/**
 * Faz download do CSV da fila respeitando os mesmos filtros do GET.
 * Retorna o Blob pra o caller transformar em download via URL.createObjectURL.
 */
export async function downloadPrazosIniciaisLegacyTaskCancelQueueCsv(
  filters: PrazoInicialLegacyTaskQueueFilters = {},
): Promise<Blob> {
  const qs = _buildLegacyQueueParams(filters).toString();
  const response = await apiFetch(
    `/api/v1/prazos-iniciais/legacy-task-cancel-queue/export.csv${
      qs ? `?${qs}` : ""
    }`,
  );
  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
  }
  return response.blob();
}


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


// ─── Templates de Prazos Iniciais ─────────────────────────────────────

/**
 * Retorna os enums que populam os selects do admin de templates (tipos de
 * prazo, naturezas, produtos, subtipos, prioridades, referências de data).
 */
export async function fetchPrazosIniciaisEnums(): Promise<PrazoInicialEnums> {
  const response = await apiFetch("/api/v1/prazos-iniciais/enums");
  return expectJson<PrazoInicialEnums>(response);
}


/**
 * Lista templates com filtros opcionais.
 *
 * Convenção pra "valor nulo":
 *   - `subtipo: ""`             → filtra templates com subtipo NULL (genéricos)
 *   - `natureza_aplicavel: ""`  → filtra templates com natureza NULL (genéricos)
 *   - `office_external_id: 0`   → filtra templates com office NULL (globais)
 *
 * Passar `undefined` omite o filtro (não é enviado no querystring).
 */
export async function listPrazosIniciaisTemplates(
  filters: PrazoInicialTaskTemplateFilters = {},
): Promise<PrazoInicialTaskTemplateListResponse> {
  const params = new URLSearchParams();
  if (filters.tipo_prazo !== undefined) params.set("tipo_prazo", filters.tipo_prazo);
  if (filters.subtipo !== undefined) params.set("subtipo", filters.subtipo);
  if (filters.natureza_aplicavel !== undefined) {
    params.set("natureza_aplicavel", filters.natureza_aplicavel);
  }
  if (typeof filters.office_external_id === "number") {
    params.set("office_external_id", String(filters.office_external_id));
  }
  if (typeof filters.is_active === "boolean") {
    params.set("is_active", String(filters.is_active));
  }
  if (typeof filters.limit === "number") params.set("limit", String(filters.limit));
  if (typeof filters.offset === "number") params.set("offset", String(filters.offset));

  const qs = params.toString();
  const response = await apiFetch(
    `/api/v1/prazos-iniciais/templates${qs ? `?${qs}` : ""}`,
  );
  return expectJson<PrazoInicialTaskTemplateListResponse>(response);
}


export async function getPrazosIniciaisTemplate(
  templateId: number,
): Promise<PrazoInicialTaskTemplate> {
  const response = await apiFetch(
    `/api/v1/prazos-iniciais/templates/${templateId}`,
  );
  return expectJson<PrazoInicialTaskTemplate>(response);
}


export async function createPrazosIniciaisTemplate(
  payload: PrazoInicialTaskTemplateCreatePayload,
): Promise<PrazoInicialTaskTemplate> {
  const response = await apiFetch("/api/v1/prazos-iniciais/templates", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return expectJson<PrazoInicialTaskTemplate>(response);
}


export async function updatePrazosIniciaisTemplate(
  templateId: number,
  payload: PrazoInicialTaskTemplateUpdatePayload,
): Promise<PrazoInicialTaskTemplate> {
  const response = await apiFetch(
    `/api/v1/prazos-iniciais/templates/${templateId}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  return expectJson<PrazoInicialTaskTemplate>(response);
}


/**
 * Soft-delete: marca is_active=False no backend. Retorna o template atualizado.
 */
export async function deletePrazosIniciaisTemplate(
  templateId: number,
): Promise<PrazoInicialTaskTemplate> {
  const response = await apiFetch(
    `/api/v1/prazos-iniciais/templates/${templateId}`,
    { method: "DELETE" },
  );
  return expectJson<PrazoInicialTaskTemplate>(response);
}
