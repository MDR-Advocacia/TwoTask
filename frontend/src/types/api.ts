export interface BatchExecutionItem {
  id: number;
  process_number: string;
  status: "SUCESSO" | "FALHA" | "PENDENTE" | "REPROCESSANDO";
  created_task_id: number | null;
  error_message: string | null;
  fingerprint?: string | null;
}

export interface BatchExecution {
  id: number;
  source: string;
  source_filename?: string | null;
  requested_by_email?: string | null;
  status: string;
  start_time: string;
  end_time: string | null;
  total_items: number;
  success_count: number;
  failure_count: number;
  items: BatchExecutionItem[];
}

export interface LegalOnePositionFixProgressItem {
  index: number;
  cnj: string;
  lawsuitId?: number | null;
  sequenceNumber?: string | null;
  status: string;
  startedAt?: string | null;
  finishedAt?: string | null;
  error?: string | null;
  positionSnippet?: string | null;
}

export interface LegalOnePositionFixWorkerStatus {
  id: string;
  label?: string | null;
  state?: string | null;
  total_items?: number | null;
  processed_items?: number | null;
  updated_count?: number | null;
  failed_count?: number | null;
  retry_pending_count?: number | null;
  remaining_items?: number | null;
  current_batch?: number | null;
  total_batches?: number | null;
  generated_at?: string | null;
}

export interface LegalOnePositionFixStatus {
  available: boolean;
  file_path: string;
  generated_at: string | null;
  state?: string | null;
  batch_size?: number | null;
  current_batch?: number | null;
  total_batches?: number | null;
  sleep_until?: string | null;
  control_file?: string | null;
  control_signal?: string | null;
  total_items: number;
  processed_items: number;
  updated_count: number;
  failed_count: number;
  retry_pending_count?: number | null;
  remaining_items: number;
  progress_percentage: number;
  average_update_seconds?: number | null;
  effective_average_seconds?: number | null;
  estimated_remaining_seconds?: number | null;
  estimated_completion_at?: string | null;
  active_queue_type?: string | null;
  retry_pass?: number | null;
  max_attempts?: number | null;
  workers?: LegalOnePositionFixWorkerStatus[];
  items: LegalOnePositionFixProgressItem[];
}

export interface LegalOnePositionFixControlResponse {
  message: string;
  action: "pause" | "resume";
  signal: string;
  control_file: string;
}

export interface PublicationTreatmentSummary {
  total_items: number;
  eligible_records: number;
  queue_count: number;
  pending_count: number;
  processing_count: number;
  completed_count: number;
  failed_count: number;
  cancelled_count: number;
  treated_target_count: number;
  without_providence_target_count: number;
}

export interface PublicationTreatmentItem {
  id: number;
  publication_record_id: number;
  legal_one_update_id: number;
  linked_lawsuit_id: number | null;
  linked_lawsuit_cnj: string | null;
  linked_office_id: number | null;
  publication_date: string | null;
  source_record_status: string;
  target_status: string;
  queue_status: string;
  attempt_count: number;
  last_run_id: number | null;
  last_attempt_at: string | null;
  treated_at: string | null;
  last_error: string | null;
  last_response: any;
  created_at: string | null;
  updated_at: string | null;
  record_status: string | null;
  publication_link: string | null;
}

export interface PublicationTreatmentRun {
  id: number;
  status: string;
  trigger_type: string;
  triggered_by_email: string | null;
  automation_id: number | null;
  total_items: number;
  processed_items: number;
  success_count: number;
  failed_count: number;
  retry_pending_count: number;
  batch_size: number | null;
  total_batches: number | null;
  current_batch: number | null;
  max_attempts: number | null;
  generated_at: string | null;
  sleep_until: string | null;
  started_at: string | null;
  finished_at: string | null;
  error_message: string | null;
  is_final: boolean;
  input_file_path?: string | null;
  status_file_path?: string | null;
  control_file_path?: string | null;
  log_file_path?: string | null;
  error_log_file_path?: string | null;
}

export interface PublicationTreatmentMonitor {
  summary: PublicationTreatmentSummary;
  active_run: PublicationTreatmentRun | null;
  available: boolean;
  progress_percentage: number;
  control_signal: string;
  recent_items: PublicationTreatmentItem[];
  recent_failures: PublicationTreatmentItem[];
}

export interface PublicationTreatmentStartResponse {
  started: boolean;
  reason: string;
  backfill: {
    created: number;
    updated: number;
    cancelled: number;
    scanned: number;
  };
  run: PublicationTreatmentRun | null;
}

export interface PublicationTreatmentControlResponse {
  message: string;
  action: string;
  signal: string;
  control_file: string;
  run: PublicationTreatmentRun;
}

// ─── Prazos Iniciais ──────────────────────────────────────────────────

// Mantido em sincronia com as constantes INTAKE_STATUS_* do backend
// (app/models/prazo_inicial.py). Deixamos como string pra não quebrar
// quando o backend adicionar novos estados durante a evolução do fluxo.
export type PrazoInicialIntakeStatus =
  | "RECEBIDO"
  | "PROCESSO_NAO_ENCONTRADO"
  | "PRONTO_PARA_CLASSIFICAR"
  | "EM_CLASSIFICACAO"
  | "CLASSIFICADO"
  | "EM_REVISAO"
  | "AGENDADO"
  | "GED_ENVIADO"
  | "CONCLUIDO"
  | "ERRO_CLASSIFICACAO"
  | "ERRO_AGENDAMENTO"
  | "ERRO_GED"
  | "CANCELADO"
  | string;

export interface PrazoInicialIntakeSummary {
  id: number;
  external_id: string;
  cnj_number: string;
  lawsuit_id: number | null;
  office_id: number | null;
  status: PrazoInicialIntakeStatus;
  natureza_processo?: string | null;
  produto?: string | null;
  error_message: string | null;
  pdf_filename_original: string | null;
  pdf_bytes: number | null;
  ged_document_id: number | null;
  ged_uploaded_at: string | null;
  received_at: string;
  updated_at: string;
  sugestoes_count: number;
}

export interface PrazoInicialParteProcessual {
  nome: string;
  documento?: string | null;
}

export interface PrazoInicialCapaProcesso {
  tribunal?: string | null;
  vara?: string | null;
  classe?: string | null;
  assunto?: string | null;
  valor_causa?: number | null;
  data_distribuicao?: string | null;
  polo_ativo?: PrazoInicialParteProcessual[];
  polo_passivo?: PrazoInicialParteProcessual[];
  segredo_justica?: boolean;
  [extra: string]: unknown;
}

export interface PrazoInicialSugestao {
  id: number;
  tipo_prazo: string;
  subtipo: string | null;
  data_base: string | null;
  prazo_dias: number | null;
  prazo_tipo: string | null;
  data_final_calculada: string | null;
  audiencia_data: string | null;
  audiencia_hora: string | null;
  audiencia_link: string | null;
  confianca: string | null;
  justificativa: string | null;
  responsavel_sugerido_id: number | null;
  task_type_id: number | null;
  task_subtype_id: number | null;
  payload_proposto: Record<string, unknown> | null;
  review_status: string;
  reviewed_by_email: string | null;
  reviewed_at: string | null;
  created_task_id: number | null;
  created_at: string;
}

export interface PrazoInicialIntakeDetail extends PrazoInicialIntakeSummary {
  capa_json: PrazoInicialCapaProcesso;
  metadata_json: Record<string, unknown> | null;
  sugestoes: PrazoInicialSugestao[];
}

export interface PrazoInicialIntakeListResponse {
  total: number;
  items: PrazoInicialIntakeSummary[];
}

export interface PrazoInicialIntakeFilters {
  status?: string;
  cnj_number?: string;
  office_id?: number;
  limit?: number;
  offset?: number;
}

export type PrazoInicialLegacyTaskCancelQueueStatus =
  | "PENDENTE"
  | "PROCESSANDO"
  | "CONCLUIDO"
  | "FALHA"
  | "CANCELADO"
  | string;

export interface PrazoInicialLegacyTaskCancelQueueItem {
  id: number;
  intake_id: number;
  lawsuit_id: number | null;
  cnj_number: string | null;
  office_id: number | null;
  legacy_task_type_external_id: number;
  legacy_task_subtype_external_id: number;
  queue_status: PrazoInicialLegacyTaskCancelQueueStatus;
  attempt_count: number;
  selected_task_id: number | null;
  cancelled_task_id: number | null;
  last_reason: string | null;
  last_attempt_at: string | null;
  completed_at: string | null;
  last_error: string | null;
  last_result: any;
  created_at: string | null;
  updated_at: string | null;
}

export interface PrazoInicialLegacyTaskCancelQueueListResponse {
  total: number;
  items: PrazoInicialLegacyTaskCancelQueueItem[];
}

export interface PrazoInicialConfirmSchedulingSuggestion {
  suggestion_id: number;
  created_task_id?: number | null;
  review_status?: string | null;
}

export interface PrazoInicialSchedulingConfirmationPayload {
  suggestions?: PrazoInicialConfirmSchedulingSuggestion[];
  enqueue_legacy_task_cancellation?: boolean;
  legacy_task_type_external_id?: number;
  legacy_task_subtype_external_id?: number;
}

export interface PrazoInicialSchedulingConfirmationResponse {
  intake: PrazoInicialIntakeSummary;
  confirmed_suggestion_ids: number[];
  created_task_ids: number[];
  legacy_task_cancellation_item: PrazoInicialLegacyTaskCancelQueueItem | null;
}

export interface PrazoInicialLegacyTaskQueueProcessResult {
  item: PrazoInicialLegacyTaskCancelQueueItem;
  result: any;
}

export interface PrazoInicialLegacyTaskQueueProcessResponse {
  processed_count: number;
  eligible_count?: number;
  success_count?: number;
  failure_count?: number;
  circuit_breaker_tripped?: boolean;
  circuit_breaker_tripped_during_tick?: boolean;
  tick_id?: string | null;
  items: PrazoInicialLegacyTaskQueueProcessResult[];
}

export interface PrazoInicialLegacyTaskCircuitBreakerResetResponse {
  success: boolean;
  circuit_breaker: PrazoInicialLegacyTaskCircuitBreakerSnapshot;
}

export interface PrazoInicialLegacyTaskQueueFilters {
  queue_status?: string;
  intake_id?: number;
  cnj_number?: string;
  since?: string; // ISO 8601
  until?: string; // ISO 8601
  limit?: number;
}

export interface PrazoInicialLegacyTaskCircuitBreakerSnapshot {
  tripped: boolean;
  tripped_until: string | null;
  consecutive_failures: number;
  threshold: number;
  cooldown_minutes: number;
  last_trip_reason: string | null;
  last_trip_at: string | null;
  last_reset_at: string | null;
  counted_reasons: string[];
}

export interface PrazoInicialLegacyTaskLastTickState {
  tick_id: string | null;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  eligible_count: number;
  processed_count: number;
  success_count: number;
  failure_count: number;
  circuit_breaker_tripped: boolean;
  circuit_breaker_tripped_during_tick: boolean;
  error: string | null;
}

export interface PrazoInicialLegacyTaskQueueMetrics {
  window_hours: number;
  window_start: string;
  now: string;
  totals_by_status: Record<string, number>;
  completed_in_window: number;
  failures_in_window: number;
  failures_by_reason_in_window: Record<string, number>;
  avg_latency_ms_in_window: number | null;
  latency_samples_in_window: number;
  circuit_breaker: PrazoInicialLegacyTaskCircuitBreakerSnapshot;
  rate_limit_seconds: number;
  last_tick: PrazoInicialLegacyTaskLastTickState;
}

export interface PrazoInicialLegacyTaskQueueItemActionResponse {
  item: PrazoInicialLegacyTaskCancelQueueItem;
}


// ─── Templates de Prazos Iniciais ─────────────────────────────────────

export interface PrazoInicialTaskTemplate {
  id: number;
  name: string;
  tipo_prazo: string;
  subtipo: string | null;
  natureza_aplicavel: string | null;
  office_external_id: number | null;
  office_name: string | null;
  task_subtype_external_id: number;
  task_subtype_name: string | null;
  responsible_user_external_id: number;
  responsible_user_name: string | null;
  priority: string;
  due_business_days: number;
  due_date_reference: string;
  description_template: string | null;
  notes_template: string | null;
  is_active: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface PrazoInicialTaskTemplateListResponse {
  total: number;
  items: PrazoInicialTaskTemplate[];
}

export interface PrazoInicialTaskTemplateCreatePayload {
  name: string;
  tipo_prazo: string;
  subtipo?: string | null;
  natureza_aplicavel?: string | null;
  office_external_id?: number | null;
  task_subtype_external_id: number;
  responsible_user_external_id: number;
  priority?: string;
  due_business_days?: number;
  due_date_reference?: string;
  description_template?: string | null;
  notes_template?: string | null;
  is_active?: boolean;
}

// Update aceita qualquer subconjunto dos campos do Create.
export type PrazoInicialTaskTemplateUpdatePayload =
  Partial<PrazoInicialTaskTemplateCreatePayload>;

export interface PrazoInicialTaskTemplateFilters {
  tipo_prazo?: string;
  /** "" (string vazia) = filtra por NULL (genérico); undefined = sem filtro */
  subtipo?: string;
  /** "" (string vazia) = filtra por NULL (genérico); undefined = sem filtro */
  natureza_aplicavel?: string;
  /** 0 = filtra por NULL (global); undefined = sem filtro */
  office_external_id?: number;
  is_active?: boolean;
  limit?: number;
  offset?: number;
}

export interface PrazoInicialEnums {
  tipos_prazo: string[];
  naturezas: string[];
  produtos: string[];
  subtipos_audiencia: string[];
  subtipos_julgamento: string[];
  priorities: string[];
  due_date_references: string[];
}
