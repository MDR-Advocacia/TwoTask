// frontend/src/types/api.ts

// Esta interface corresponde ao schema BatchExecutionItemResponse do backend
export interface BatchExecutionItem {
  id: number;
  process_number: string;
  status: "SUCESSO" | "FALHA";
  created_task_id: number | null;
  error_message: string | null;
}

// Esta interface corresponde ao schema BatchExecutionResponse do backend
export interface BatchExecution {
  id: number;
  source: string;
  start_time: string; // As datas virão como strings no formato ISO 8601
  end_time: string | null;
  total_items: number;
  success_count: number;
  failure_count: number;
  items: BatchExecutionItem[];
}