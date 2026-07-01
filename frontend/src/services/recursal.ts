// Serviço do módulo "Análise Recursal" (dentro de Prazos Processuais).
// Reusa o apiFetch (JWT automático). Self-contained — não depende do
// api.ts gigante.

import { apiFetch } from "@/lib/api-client";

const BASE = "/api/v1/recursal";

async function parse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const body = await response.json();
      if (body?.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

// ─── Tipos ────────────────────────────────────────────────────────────

export interface RecursalAnalise {
  id: number;
  processo_numero: string;
  cnj_number: string | null;
  uf: string | null;
  tribunal: string | null;
  status: string;
  extraction_confidence: string | null;
  extraction_failed: boolean;
  extractor_used: string | null;
  pdf_filename_original: string | null;
  error_message: string | null;
  // identificação
  nome_autor: string | null;
  cpf: string | null;
  objeto: string | null;
  produto: string | null;
  produto_categoria: string | null;
  // veredito
  resultado_decisao: string | null;
  tipo_decisao: string | null;
  resumo_topicos: string[];
  destaque: string | null;
  fundamentacao_juiz: string | null;
  contestacao_com_documentos: boolean | null;
  pontos_analise: string[];
  probabilidade_reversao: string | null;
  recorrer: string | null;
  tipo_recurso: string | null;
  fundamentacao: string | null;
  valor_causa: number | null;
  valor_condenacao: string | null;
  data_intimacao: string | null;
  prazo_fatal: string | null;
  custo_estimado: number | null;
  custo_detalhe: Record<string, unknown> | null;
  confianca: string | null;
  // parecer renderizado (pronto pra copiar)
  assunto: string | null;
  parecer_texto: string | null;
  analysis_batch_id: number | null;
  uploaded_by_email: string | null;
  uploaded_by_name: string | null;
  created_at: string | null;
  analyzed_at: string | null;
}

export interface RecursalListResponse {
  total: number;
  items: RecursalAnalise[];
}

export interface RecursalUploadResponse {
  id: number;
  processo_numero: string;
  cnj_number: string | null;
  uf: string | null;
  status: string;
  extraction_confidence: string | null;
  extraction_failed: boolean;
  already_existed: boolean;
  user_message: string | null;
}

export interface RecursalBatch {
  id: number;
  anthropic_batch_id: string | null;
  status: string;
  anthropic_status: string | null;
  total_records: number;
  succeeded_count: number;
  errored_count: number;
  model_used: string | null;
  requested_by_email: string | null;
  analise_ids: number[] | null;
  created_at: string | null;
  submitted_at: string | null;
  ended_at: string | null;
  applied_at: string | null;
}

export interface RecursalSubmitResponse {
  batch: RecursalBatch;
  submetidos: number;
}

export interface RecursalRefreshResponse {
  batch: RecursalBatch;
  summary: {
    succeeded: number;
    failed: number;
    skipped: number;
    total_results: number;
  } | null;
}

export interface RecursalCusta {
  id: number;
  uf: string;
  tribunal: string | null;
  tipo_recurso: string;
  percentual: number | null;
  valor_fixo: number | null;
  valor_minimo: number | null;
  valor_maximo: number | null;
  porte_remessa_retorno: number | null;
  vigencia: string | null;
  fundamentacao: string | null;
  ativo: boolean;
}

export interface RecursalCustaInput {
  uf: string;
  tribunal?: string | null;
  tipo_recurso: string;
  percentual?: number;
  valor_fixo?: number;
  valor_minimo?: number | null;
  valor_maximo?: number | null;
  porte_remessa_retorno?: number;
  vigencia?: string | null;
  fundamentacao?: string | null;
  ativo?: boolean;
}

// ─── Chamadas ─────────────────────────────────────────────────────────

export async function uploadRecursalProcesso(
  file: File,
  processoNumero?: string,
): Promise<RecursalUploadResponse> {
  const fd = new FormData();
  fd.append("processo_pdf", file);
  if (processoNumero) fd.append("processo_numero", processoNumero);
  const res = await apiFetch(`${BASE}/upload`, { method: "POST", body: fd });
  return parse<RecursalUploadResponse>(res);
}

export async function submitRecursal(): Promise<RecursalSubmitResponse> {
  const res = await apiFetch(`${BASE}/submit`, { method: "POST" });
  return parse<RecursalSubmitResponse>(res);
}

export interface RecursalProgresso {
  total: number;
  recebido: number;
  em_analise: number;
  analisado: number;
  erro: number;
  sem_texto: number;
  em_jogo: number;
  terminados: number;
  processando: number;
  pct: number;
}

export async function getRecursalProgresso(): Promise<RecursalProgresso> {
  return parse<RecursalProgresso>(await apiFetch(`${BASE}/progresso`));
}

export async function listRecursalAnalises(params: {
  status?: string;
  limit?: number;
  offset?: number;
}): Promise<RecursalListResponse> {
  const qs = new URLSearchParams();
  if (params.status) qs.set("status", params.status);
  if (params.limit != null) qs.set("limit", String(params.limit));
  if (params.offset != null) qs.set("offset", String(params.offset));
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  const res = await apiFetch(`${BASE}${suffix}`);
  return parse<RecursalListResponse>(res);
}

export async function getRecursalAnalise(id: number): Promise<RecursalAnalise> {
  const res = await apiFetch(`${BASE}/${id}`);
  return parse<RecursalAnalise>(res);
}

export async function deleteRecursalAnalise(id: number): Promise<{ ok: boolean }> {
  const res = await apiFetch(`${BASE}/${id}`, { method: "DELETE" });
  return parse<{ ok: boolean }>(res);
}

export async function listRecursalBatches(params: {
  limit?: number;
  offset?: number;
} = {}): Promise<{ total: number; items: RecursalBatch[] }> {
  const qs = new URLSearchParams();
  if (params.limit != null) qs.set("limit", String(params.limit));
  if (params.offset != null) qs.set("offset", String(params.offset));
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  const res = await apiFetch(`${BASE}/batches/list${suffix}`);
  return parse<{ total: number; items: RecursalBatch[] }>(res);
}

export async function refreshRecursalBatch(
  batchId: number,
): Promise<RecursalRefreshResponse> {
  const res = await apiFetch(`${BASE}/batches/${batchId}/refresh`, {
    method: "POST",
  });
  return parse<RecursalRefreshResponse>(res);
}

export async function listRecursalCustas(): Promise<{
  total: number;
  items: RecursalCusta[];
}> {
  const res = await apiFetch(`${BASE}/custas/list`);
  return parse<{ total: number; items: RecursalCusta[] }>(res);
}

export async function upsertRecursalCustas(
  rows: RecursalCustaInput[],
  replace = false,
): Promise<{ inserted: number; replaced: boolean }> {
  const res = await apiFetch(`${BASE}/custas`, {
    method: "POST",
    body: JSON.stringify({ rows, replace }),
  });
  return parse<{ inserted: number; replaced: boolean }>(res);
}
