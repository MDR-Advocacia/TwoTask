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
