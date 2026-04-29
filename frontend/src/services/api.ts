import { apiFetch } from "@/lib/api-client";
import {
  AjusAndamentoQueueListResponse,
  AjusCodAndamento,
  AjusCodAndamentoCreatePayload,
  AjusDispatchBatchResponse,
  BatchExecution,
  LegalOnePositionFixControlResponse,
  LegalOnePositionFixStatus,
  PrazoInicialApplyBatchResponse,
  PrazoInicialBatchListResponse,
  PrazoInicialBatchSummary,
  PrazoInicialClassifyPendingResponse,
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


// ─── Prazos Iniciais ──────────────────────────────────────────────────

export async function fetchPrazosIniciaisIntakes(
  filters: PrazoInicialIntakeFilters = {},
): Promise<PrazoInicialIntakeListResponse> {
  const params = new URLSearchParams();
  if (filters.status) params.set("status", filters.status);
  if (filters.cnj_number) params.set("cnj_number", filters.cnj_number);
  // office_id agora aceita CSV no backend — serializamos como string.
  if (filters.office_id) params.set("office_id", filters.office_id);
  if (filters.natureza_processo) {
    params.set("natureza_processo", filters.natureza_processo);
  }
  if (filters.produto) params.set("produto", filters.produto);
  if (filters.probabilidade_exito_global) {
    params.set("probabilidade_exito_global", filters.probabilidade_exito_global);
  }
  if (filters.date_from) params.set("date_from", filters.date_from);
  if (filters.date_to) params.set("date_to", filters.date_to);
  if (typeof filters.has_error === "boolean") {
    params.set("has_error", String(filters.has_error));
  }
  if (typeof filters.batch_id === "number") {
    params.set("batch_id", String(filters.batch_id));
  }
  if (filters.treated_by_user_id) {
    params.set("treated_by_user_id", filters.treated_by_user_id);
  }
  if (typeof filters.dispatch_pending === "boolean") {
    params.set("dispatch_pending", String(filters.dispatch_pending));
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
 * HARD DELETE de um intake (admin only). Apaga registro + PDF + cascata.
 * Usado pra reinjetar o mesmo processo do zero durante testes. Vai virar
 * arquivamento depois.
 */
export async function deletePrazoInicialIntake(intakeId: number): Promise<void> {
  const response = await apiFetch(
    `/api/v1/prazos-iniciais/intakes/${intakeId}`,
    { method: "DELETE" },
  );
  if (!response.ok && response.status !== 204) {
    let detail = "Falha ao deletar intake.";
    try {
      const data = await response.json();
      detail = data?.detail || detail;
    } catch (_) {
      // sem body
    }
    throw new Error(detail);
  }
}


/**
 * Onda 3 #5 — dispara o tratamento web (GED + enqueue cancel da legacy)
 * de um intake AGENDADO/CONCLUIDO_SEM_PROVIDENCIA. Idempotente — se
 * `dispatch_pending` já estiver false, retorna `skipped:true`.
 */
export async function dispatchPrazoInicialTreatmentWeb(
  intakeId: number,
): Promise<{
  intake: PrazoInicialIntakeSummary;
  legacy_task_cancellation_item: unknown | null;
  skipped: boolean;
  reason?: string | null;
}> {
  const response = await apiFetch(
    `/api/v1/prazos-iniciais/intakes/${intakeId}/dispatch-treatment-web`,
    { method: "POST" },
  );
  return expectJson(response);
}


/**
 * Onda 3 #5/#6 — dispara em lote N intakes pendentes em ordem cronológica.
 * Usado pelo botão "Disparar todos" e pelo worker periódico configurável.
 */
export async function dispatchPrazoInicialPendingBatch(
  batchLimit: number = 10,
): Promise<{
  candidates: number;
  success_count: number;
  skipped_count: number;
  failure_count: number;
  success_ids: number[];
  skipped_ids: number[];
  failed: { intake_id: number; error: string }[];
}> {
  const response = await apiFetch(
    `/api/v1/prazos-iniciais/intakes/dispatch-pending/process-batch?batch_limit=${batchLimit}`,
    { method: "POST" },
  );
  return expectJson(response);
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


// ═══════════════════════════════════════════════════════════════════════
// Classificação em lote (Sonnet / Anthropic Batches) — Onda 1 manual
// ═══════════════════════════════════════════════════════════════════════

/**
 * Dispara um batch de classificação com todos os intakes em
 * PRONTO_PARA_CLASSIFICAR. Aceita `limit` opcional pra cortar o tamanho.
 * Retorna metadados do batch criado (ou flag `submitted=false` se não
 * houver intakes pendentes).
 */
export async function submitPrazosIniciaisClassifyPending(
  limit?: number,
): Promise<PrazoInicialClassifyPendingResponse> {
  const qs = typeof limit === "number" && limit > 0 ? `?limit=${limit}` : "";
  const response = await apiFetch(
    `/api/v1/prazos-iniciais/classificar-pendentes${qs}`,
    { method: "POST" },
  );
  return expectJson<PrazoInicialClassifyPendingResponse>(response);
}

export async function fetchPrazosIniciaisBatches(
  limit = 50,
): Promise<PrazoInicialBatchListResponse> {
  const response = await apiFetch(
    `/api/v1/prazos-iniciais/batches?limit=${limit}`,
  );
  return expectJson<PrazoInicialBatchListResponse>(response);
}

export async function refreshPrazosIniciaisBatch(
  batchId: number,
): Promise<PrazoInicialBatchSummary> {
  const response = await apiFetch(
    `/api/v1/prazos-iniciais/batches/${batchId}/refresh`,
    { method: "POST" },
  );
  return expectJson<PrazoInicialBatchSummary>(response);
}

export async function applyPrazosIniciaisBatch(
  batchId: number,
): Promise<PrazoInicialApplyBatchResponse> {
  const response = await apiFetch(
    `/api/v1/prazos-iniciais/batches/${batchId}/apply`,
    { method: "POST" },
  );
  return expectJson<PrazoInicialApplyBatchResponse>(response);
}

/**
 * Recalcula os agregados globais (valor_total_pedido/estimado/
 * aprovisionamento/probabilidade_exito_global) a partir dos pedidos
 * persistidos do intake. Não re-roda Sonnet, não gasta tokens.
 * Útil pra corrigir intakes órfãos de apply antigo.
 */
/**
 * Finaliza o intake SEM criar tarefa no Legal One (Caminho A).
 * Sobe habilitação pro GED, cancela a task legada, marca intake como
 * CONCLUIDO_SEM_PROVIDENCIA. Caso operacional pra processos sem
 * providência necessária (ex.: sentença de improcedência transitada,
 * arquivamento definitivo).
 */
export async function finalizarPrazoInicialSemProvidencia(
  intakeId: number,
  payload: { notes?: string | null; enqueue_legacy_task_cancellation?: boolean } = {},
): Promise<{ intake: Record<string, unknown>; legacy_task_cancellation_item: Record<string, unknown> | null }> {
  const body = {
    notes: payload.notes ?? null,
    enqueue_legacy_task_cancellation: payload.enqueue_legacy_task_cancellation ?? true,
  };
  const response = await apiFetch(
    `/api/v1/prazos-iniciais/intakes/${intakeId}/finalizar-sem-providencia`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
  return expectJson(response);
}


export async function recomputePrazoInicialGlobals(
  intakeId: number,
): Promise<{
  intake_id: number;
  valor_total_pedido: number | null;
  valor_total_estimado: number | null;
  aprovisionamento_sugerido: number | null;
  probabilidade_exito_global: string | null;
  pedidos_count: number;
}> {
  const response = await apiFetch(
    `/api/v1/prazos-iniciais/intakes/${intakeId}/recompute-globals`,
    { method: "POST" },
  );
  return expectJson(response);
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



// ─── Reanalisar (Bloco F) ────────────────────────────────────────────
export async function reanalyzePrazoInicial(intakeId: number): Promise<{
  intake_id: number;
  status: string;
  message: string;
}> {
  const res = await apiFetch(`/api/v1/prazos-iniciais/intakes/${intakeId}/reanalisar`, {
    method: "POST",
  });
  return expectJson(res);
}

// ─── Export XLSX (Bloco F) ───────────────────────────────────────────
export async function exportPrazosIniciaisXlsx(filters: {
  status?: string;
  office_id?: number;
  date_from?: string;
  date_to?: string;
} = {}): Promise<Blob> {
  const params = new URLSearchParams();
  if (filters.status) params.set("status", filters.status);
  if (filters.office_id) params.set("office_id", String(filters.office_id));
  if (filters.date_from) params.set("date_from", filters.date_from);
  if (filters.date_to) params.set("date_to", filters.date_to);
  const qs = params.toString() ? `?${params.toString()}` : "";
  const res = await apiFetch(
    `/api/v1/prazos-iniciais/intakes/export.xlsx${qs}`,
  );
  if (!res.ok) {
    throw new Error(`HTTP error! status: ${res.status}`);
  }
  return res.blob();
}


// ─── AJUS — códigos de andamento + fila ───────────────────────────────

export async function fetchAjusCodAndamento(
  onlyActive = false,
): Promise<AjusCodAndamento[]> {
  const qs = onlyActive ? "?only_active=true" : "";
  const res = await apiFetch(`/api/v1/ajus/cod-andamento${qs}`);
  return expectJson<AjusCodAndamento[]>(res);
}

export async function createAjusCodAndamento(
  payload: AjusCodAndamentoCreatePayload,
): Promise<AjusCodAndamento> {
  const res = await apiFetch(`/api/v1/ajus/cod-andamento`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return expectJson<AjusCodAndamento>(res);
}

export async function updateAjusCodAndamento(
  id: number,
  payload: AjusCodAndamentoCreatePayload,
): Promise<AjusCodAndamento> {
  const res = await apiFetch(`/api/v1/ajus/cod-andamento/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return expectJson<AjusCodAndamento>(res);
}

export async function deleteAjusCodAndamento(id: number): Promise<void> {
  const res = await apiFetch(`/api/v1/ajus/cod-andamento/${id}`, {
    method: "DELETE",
  });
  if (!res.ok && res.status !== 204) {
    let detail = "Falha ao deletar código.";
    try {
      const data = await res.json();
      detail = data?.detail || detail;
    } catch (_) { /* sem body */ }
    throw new Error(detail);
  }
}

export interface AjusAndamentoFilters {
  status?: string;       // CSV
  cnj_number?: string;
  limit?: number;
  offset?: number;
}

export async function fetchAjusAndamentos(
  filters: AjusAndamentoFilters = {},
): Promise<AjusAndamentoQueueListResponse> {
  const params = new URLSearchParams();
  if (filters.status) params.set("status", filters.status);
  if (filters.cnj_number) params.set("cnj_number", filters.cnj_number);
  if (typeof filters.limit === "number") params.set("limit", String(filters.limit));
  if (typeof filters.offset === "number") params.set("offset", String(filters.offset));
  const qs = params.toString();
  const res = await apiFetch(
    `/api/v1/ajus/andamentos${qs ? `?${qs}` : ""}`,
  );
  return expectJson<AjusAndamentoQueueListResponse>(res);
}

export async function dispatchAjusAndamentosPending(
  batchLimit = 20,
): Promise<AjusDispatchBatchResponse> {
  const res = await apiFetch(
    `/api/v1/ajus/andamentos/dispatch-pending?batch_limit=${batchLimit}`,
    { method: "POST" },
  );
  return expectJson<AjusDispatchBatchResponse>(res);
}

export async function cancelAjusAndamento(itemId: number) {
  const res = await apiFetch(
    `/api/v1/ajus/andamentos/${itemId}/cancel`,
    { method: "POST" },
  );
  return expectJson(res);
}

export async function retryAjusAndamento(itemId: number) {
  const res = await apiFetch(
    `/api/v1/ajus/andamentos/${itemId}/retry`,
    { method: "POST" },
  );
  return expectJson(res);
}
