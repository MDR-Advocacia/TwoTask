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
