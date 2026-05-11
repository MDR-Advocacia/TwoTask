/**
 * Cliente da API de Base Processual.
 *
 * Endpoints internos sob /api/v1/admin/base-processual. Auth via JWT
 * herdado do apiFetch (Bearer do localStorage).
 *
 * Chunk 2 cobre: uploads (dry-run + commit + list) + dashboard.
 * Outras rotas (processos, eventos, exports, api-keys) entram nos
 * proximos chunks.
 */

import { apiFetch } from "@/lib/api-client";

const BASE = "/api/v1/admin/base-processual";

// --- Types (mirror dos schemas Pydantic V2) ---

export interface BaseProcessualUploadOut {
  id: number;
  filename: string;
  file_sha256: string | null;
  file_bytes: number | null;
  total_rows_in_file: number | null;
  summary_novos: number;
  summary_removidos: number;
  summary_atualizados: number;
  summary_inalterados: number;
  status: string;
  error_message: string | null;
  eventos_preview_json:
    | Array<{
        tipo: string;
        cod_ajus: string;
        changed_fields: Record<string, unknown> | null;
      }>
    | null;
  dry_run_of_upload_id: number | null;
  storage_path: string | null;
  uploaded_by_user_id: number | null;
  uploaded_at: string;
  processed_at: string | null;
  committed_at: string | null;
  expires_at: string | null;
}

export interface BaseProcessualUploadResult {
  upload_id: number;
  status: string;
  summary_novos: number;
  summary_removidos: number;
  summary_atualizados: number;
  summary_inalterados: number;
  error_message: string | null;
  is_idempotente: boolean;
  eventos_preview:
    | Array<{
        tipo: string;
        cod_ajus: string;
        changed_fields: Record<string, unknown> | null;
      }>
    | null;
}

export interface ListUploadsResponse {
  total: number;
  items: BaseProcessualUploadOut[];
}

export interface BaseProcessualEventoOut {
  id: number;
  upload_id: number;
  processo_id: number;
  cod_ajus: string;
  tipo_evento: string;
  changed_fields: Record<string, unknown> | null;
  snapshot_before_id: number | null;
  snapshot_after_id: number | null;
  created_at: string;
}

export interface ListEventosResponse {
  total: number;
  items: BaseProcessualEventoOut[];
}

export interface DashboardResumoOut {
  total_ativos_na_base: number;
  total_removidos_na_base: number;
  novos_hoje: number;
  saidos_hoje: number;
  atualizados_hoje: number;
  ultimo_upload_id: number | null;
  ultimo_upload_em: string | null;
  ultimo_upload_status: string | null;
  ultimo_upload_filename: string | null;
  top_responsaveis: Array<{ usuario_responsavel: string | null; total: number }>;
  distribuicao_uf: Array<{ uf: string | null; total: number }>;
}

export interface DashboardSerieDiariaItem {
  data: string;
  novos: number;
  removidos: number;
  atualizados: number;
}

export interface DashboardSerieDiariaResponse {
  from_date: string;
  to_date: string;
  items: DashboardSerieDiariaItem[];
}

export interface MovimentacaoItem {
  evento_id: number;
  cod_ajus: string;
  numero_processo_mascarado: string | null;
  empresa: string | null;
  uf: string | null;
  comarca: string | null;
  usuario_responsavel: string | null;
  distribuido_em: string | null;
  visto_em: string | null;
  changed_fields: Record<string, unknown> | null;
}

export interface MovimentacaoDoDiaResponse {
  data: string;
  entraram_total: number;
  sairam_total: number;
  atualizados_total: number;
  entraram: MovimentacaoItem[];
  sairam: MovimentacaoItem[];
  atualizados: MovimentacaoItem[];
}

export interface InatividadeOut {
  ultimo_upload_em: string | null;
  horas_desde_ultimo: number | null;
  alerta: boolean;
  threshold_horas: number;
}

// --- helpers ---

async function formatError(r: Response): Promise<Error> {
  try {
    const body = await r.json();
    return new Error(body.detail ?? JSON.stringify(body));
  } catch {
    return new Error(`${r.status} ${r.statusText}`);
  }
}

// --- Uploads ---

export async function dryRunUpload(file: File): Promise<BaseProcessualUploadResult> {
  const fd = new FormData();
  fd.append("file", file);
  const r = await apiFetch(`${BASE}/uploads/dry-run`, {
    method: "POST",
    body: fd,
  });
  if (!r.ok) throw await formatError(r);
  return r.json();
}

export async function commitDryRun(
  dryRunId: number,
): Promise<BaseProcessualUploadResult> {
  const r = await apiFetch(`${BASE}/uploads/${dryRunId}/commit`, {
    method: "POST",
  });
  if (!r.ok) throw await formatError(r);
  return r.json();
}

export async function uploadDirect(
  file: File,
): Promise<BaseProcessualUploadResult> {
  const fd = new FormData();
  fd.append("file", file);
  const r = await apiFetch(`${BASE}/uploads`, { method: "POST", body: fd });
  if (!r.ok) throw await formatError(r);
  return r.json();
}

export async function listUploads(
  params: { limit?: number; offset?: number; status?: string } = {},
): Promise<ListUploadsResponse> {
  const qs = new URLSearchParams();
  if (params.limit !== undefined) qs.set("limit", String(params.limit));
  if (params.offset !== undefined) qs.set("offset", String(params.offset));
  if (params.status) qs.set("status", params.status);
  const url = `${BASE}/uploads${qs.toString() ? `?${qs.toString()}` : ""}`;
  const r = await apiFetch(url);
  if (!r.ok) throw await formatError(r);
  return r.json();
}

export async function getUpload(id: number): Promise<BaseProcessualUploadOut> {
  const r = await apiFetch(`${BASE}/uploads/${id}`);
  if (!r.ok) throw await formatError(r);
  return r.json();
}

export async function listEventosDoUpload(
  uploadId: number,
  params: { limit?: number; offset?: number; tipo_evento?: string } = {},
): Promise<ListEventosResponse> {
  const qs = new URLSearchParams();
  if (params.limit !== undefined) qs.set("limit", String(params.limit));
  if (params.offset !== undefined) qs.set("offset", String(params.offset));
  if (params.tipo_evento) qs.set("tipo_evento", params.tipo_evento);
  const url = `${BASE}/uploads/${uploadId}/eventos${
    qs.toString() ? `?${qs.toString()}` : ""
  }`;
  const r = await apiFetch(url);
  if (!r.ok) throw await formatError(r);
  return r.json();
}

export function downloadXlsxUrl(uploadId: number): string {
  return `${BASE}/uploads/${uploadId}/download`;
}

// --- Dashboard ---

export async function getDashboardResumo(): Promise<DashboardResumoOut> {
  const r = await apiFetch(`${BASE}/dashboard/resumo`);
  if (!r.ok) throw await formatError(r);
  return r.json();
}

export async function getDashboardSerieDiaria(
  params: { from_date?: string; to_date?: string } = {},
): Promise<DashboardSerieDiariaResponse> {
  const qs = new URLSearchParams();
  if (params.from_date) qs.set("from_date", params.from_date);
  if (params.to_date) qs.set("to_date", params.to_date);
  const url = `${BASE}/dashboard/serie-diaria${
    qs.toString() ? `?${qs.toString()}` : ""
  }`;
  const r = await apiFetch(url);
  if (!r.ok) throw await formatError(r);
  return r.json();
}

export async function getDashboardMovimentacaoDoDia(
  params: { data?: string; limit?: number } = {},
): Promise<MovimentacaoDoDiaResponse> {
  const qs = new URLSearchParams();
  if (params.data) qs.set("data", params.data);
  if (params.limit !== undefined) qs.set("limit", String(params.limit));
  const url = `${BASE}/dashboard/movimentacao-do-dia${
    qs.toString() ? `?${qs.toString()}` : ""
  }`;
  const r = await apiFetch(url);
  if (!r.ok) throw await formatError(r);
  return r.json();
}

export async function getDashboardInatividade(): Promise<InatividadeOut> {
  const r = await apiFetch(`${BASE}/dashboard/inatividade`);
  if (!r.ok) throw await formatError(r);
  return r.json();
}
