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

/**
 * Download autenticado: `apiFetch` injeta o Bearer JWT do localStorage,
 * baixa o arquivo como blob, e dispara o "Save As" do navegador via
 * `<a download>` programatico.
 *
 * Necessario porque <a href={url}> direto NAO envia Authorization
 * header — o backend exige JWT e respondia 401. Use sempre esta funcao
 * pra downloads de qualquer endpoint protegido (exports, uploads, etc).
 */
export async function downloadFileWithAuth(
  url: string,
  suggestedFilename: string,
): Promise<void> {
  const r = await apiFetch(url);
  if (!r.ok) throw await formatError(r);
  const blob = await r.blob();
  const objectUrl = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = objectUrl;
  a.download = suggestedFilename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  // Delay no revoke pra dar tempo do browser iniciar o download.
  setTimeout(() => URL.revokeObjectURL(objectUrl), 2000);
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

// --- Processos (Chunk 3) ---

export interface ProcessoOut {
  id: number;
  cod_ajus: string;
  numero_processo: string | null;
  numero_processo_mascarado: string | null;
  numero_interno: string | null;
  numero_pasta: string | null;
  acao_principal: string | null;
  materia: string | null;
  risco_prob_perda: string | null;
  tipo_acao: string | null;
  polo: string | null;
  natureza: string | null;
  numero_vara: string | null;
  foro: string | null;
  comarca: string | null;
  uf: string | null;
  empresa: string;
  grupo_responsavel: string | null;
  usuario_responsavel: string | null;
  escritorio_responsavel: string | null;
  situacao_processo: string;
  justica_honorario: string | null;
  valor_causa: number | null;
  valor_prev_acordo: number | null;
  valor_acordo: number | null;
  valor_discutido: number | null;
  valor_exito: number | null;
  valor_condenacao: number | null;
  valor_contingencia: number | null;
  ult_andamento: string | null;
  data_ult_andamento: string | null;
  dias_ult_atualizacao: number | null;
  distribuido_em: string | null;
  processo_virtual: boolean | null;
  numero_contrato: string | null;
  usuario_cadastro_acao: string | null;
  data_cadastro_acao: string | null;
  autores_json: Array<{ nome: string | null; documento: string | null }> | null;
  reus_json: Array<{ nome: string | null; documento: string | null }> | null;
  presenca_status: string;
  first_seen_upload_id: number | null;
  last_seen_upload_id: number | null;
  removed_at_upload_id: number | null;
  current_snapshot_id: number | null;
  created_at: string;
  updated_at: string;
}

export interface ProcessoListResponse {
  total: number;
  items: ProcessoOut[];
}

export interface ProcessosFilters {
  presenca_status?: string;
  cod_ajus?: string;
  numero_pasta?: string;
  empresa?: string;
  uf?: string;
  comarca?: string;
  situacao_processo?: string;
  polo?: string;
  materia?: string;
  natureza?: string;
  tipo_acao?: string;
  risco_prob_perda?: string;
  usuario_responsavel?: string;
  grupo_responsavel?: string;
  escritorio_responsavel?: string;
  valor_causa_min?: number;
  valor_causa_max?: number;
  distribuido_de?: string;
  distribuido_ate?: string;
  search?: string;
  sort_by?: string;
  limit?: number;
  offset?: number;
}

export interface SnapshotOut {
  id: number;
  upload_id: number;
  cod_ajus: string;
  diff_hash: string;
  captured_at: string;
  payload_normalized: Record<string, unknown>;
}

export interface SnapshotListResponse {
  total: number;
  items: SnapshotOut[];
}

export interface ProcessoPatch {
  situacao_processo?: string;
  usuario_responsavel?: string;
  grupo_responsavel?: string;
  escritorio_responsavel?: string;
  polo?: string;
  materia?: string;
  risco_prob_perda?: string;
  motivo?: string;
}

export async function listProcessos(
  filters: ProcessosFilters = {},
): Promise<ProcessoListResponse> {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(filters)) {
    if (v !== undefined && v !== null && v !== "") {
      qs.set(k, String(v));
    }
  }
  const url = `${BASE}/processos${qs.toString() ? `?${qs.toString()}` : ""}`;
  const r = await apiFetch(url);
  if (!r.ok) throw await formatError(r);
  return r.json();
}

export async function getProcesso(codAjus: string): Promise<ProcessoOut> {
  const r = await apiFetch(`${BASE}/processos/${encodeURIComponent(codAjus)}`);
  if (!r.ok) throw await formatError(r);
  return r.json();
}

export async function getProcessoHistorico(
  codAjus: string,
  params: { limit?: number; offset?: number } = {},
): Promise<SnapshotListResponse> {
  const qs = new URLSearchParams();
  if (params.limit !== undefined) qs.set("limit", String(params.limit));
  if (params.offset !== undefined) qs.set("offset", String(params.offset));
  const url = `${BASE}/processos/${encodeURIComponent(codAjus)}/historico${
    qs.toString() ? `?${qs.toString()}` : ""
  }`;
  const r = await apiFetch(url);
  if (!r.ok) throw await formatError(r);
  return r.json();
}

export async function getProcessoEventos(
  codAjus: string,
  params: { limit?: number; offset?: number; tipo_evento?: string } = {},
): Promise<ListEventosResponse> {
  const qs = new URLSearchParams();
  if (params.limit !== undefined) qs.set("limit", String(params.limit));
  if (params.offset !== undefined) qs.set("offset", String(params.offset));
  if (params.tipo_evento) qs.set("tipo_evento", params.tipo_evento);
  const url = `${BASE}/processos/${encodeURIComponent(codAjus)}/eventos${
    qs.toString() ? `?${qs.toString()}` : ""
  }`;
  const r = await apiFetch(url);
  if (!r.ok) throw await formatError(r);
  return r.json();
}

export async function patchProcesso(
  codAjus: string,
  patch: ProcessoPatch,
): Promise<ProcessoOut> {
  const r = await apiFetch(`${BASE}/processos/${encodeURIComponent(codAjus)}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
  if (!r.ok) throw await formatError(r);
  return r.json();
}

// --- Eventos cross-upload + Bulk Update (Chunk 4) ---

export interface EventosCrossFilters {
  tipo_evento?: string; // CSV: "ENTROU,SAIU"
  upload_id?: number;
  cod_ajus?: string;
  from_date?: string;
  to_date?: string;
  search?: string;
  limit?: number;
  offset?: number;
}

export async function listEventosCrossUpload(
  filters: EventosCrossFilters = {},
): Promise<ListEventosResponse> {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(filters)) {
    if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
  }
  const url = `${BASE}/eventos${qs.toString() ? `?${qs.toString()}` : ""}`;
  const r = await apiFetch(url);
  if (!r.ok) throw await formatError(r);
  return r.json();
}

export interface BulkUpdateFilters {
  presenca_status?: string;
  cod_ajus_list?: string[];
  empresa?: string;
  uf?: string;
  comarca?: string;
  situacao_processo?: string;
  polo?: string;
  materia?: string;
  natureza?: string;
  tipo_acao?: string;
  risco_prob_perda?: string;
  usuario_responsavel?: string;
  grupo_responsavel?: string;
  escritorio_responsavel?: string;
  valor_causa_min?: number;
  valor_causa_max?: number;
  distribuido_de?: string;
  distribuido_ate?: string;
  search?: string;
}

export interface BulkUpdateSet {
  situacao_processo?: string;
  usuario_responsavel?: string;
  grupo_responsavel?: string;
  escritorio_responsavel?: string;
  polo?: string;
  materia?: string;
  risco_prob_perda?: string;
}

export interface BulkUpdatePayload {
  filter: BulkUpdateFilters;
  set: BulkUpdateSet;
  motivo?: string;
  confirm_count?: number;
}

export interface BulkUpdateResult {
  total_afetados: number;
  cods_afetados: string[];
  upload_id: number;
  eventos_criados: number;
}

export async function bulkUpdateProcessos(
  payload: BulkUpdatePayload,
): Promise<BulkUpdateResult> {
  const r = await apiFetch(`${BASE}/processos/bulk-update`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
  if (!r.ok) throw await formatError(r);
  return r.json();
}

// --- Exports (Chunk 5) ---

export type ExportTemplate =
  | "movimentacao_semanal"
  | "carteira_responsavel"
  | "sumicos_periodo"
  | "variacao_valores"
  | "carteira_uf_comarca"
  | "snapshot_completo";

export interface ExportOut {
  id: number;
  template_name: string;
  params_json: Record<string, unknown> | null;
  status: string;
  file_path: string | null;
  file_bytes: number | null;
  total_rows: number | null;
  error_message: string | null;
  requested_by_user_id: number | null;
  requested_at: string;
  started_at: string | null;
  finished_at: string | null;
  expires_at: string | null;
}

export interface ExportListResponse {
  total: number;
  items: ExportOut[];
}

export interface ExportCreatePayload {
  template: ExportTemplate;
  params?: Record<string, unknown>;
}

export async function listExports(
  params: { limit?: number; offset?: number; template?: string; status?: string } = {},
): Promise<ExportListResponse> {
  const qs = new URLSearchParams();
  if (params.limit !== undefined) qs.set("limit", String(params.limit));
  if (params.offset !== undefined) qs.set("offset", String(params.offset));
  if (params.template) qs.set("template", params.template);
  if (params.status) qs.set("status", params.status);
  const url = `${BASE}/exports${qs.toString() ? `?${qs.toString()}` : ""}`;
  const r = await apiFetch(url);
  if (!r.ok) throw await formatError(r);
  return r.json();
}

export async function createExport(
  payload: ExportCreatePayload,
): Promise<ExportOut> {
  const r = await apiFetch(`${BASE}/exports`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
  if (!r.ok) throw await formatError(r);
  return r.json();
}

export function downloadExportUrl(exportId: number): string {
  return `${BASE}/exports/${exportId}/download`;
}

// --- API Keys (Chunk 6) ---

export type ApiKeyScope =
  | "read_processos"
  | "read_valores"
  | "read_dashboard"
  | "read_all";

export interface ApiKeyOut {
  id: number;
  nome: string;
  key_prefix: string;
  scope: string;
  rate_limit_per_min: number;
  last_used_at: string | null;
  revoked_at: string | null;
  created_by_user_id: number | null;
  created_at: string;
}

export interface ApiKeyListResponse {
  total: number;
  items: ApiKeyOut[];
}

export interface ApiKeyCreatePayload {
  nome: string;
  scope: ApiKeyScope;
  rate_limit_per_min?: number;
}

export interface ApiKeyCreateResponse {
  api_key: ApiKeyOut;
  plaintext: string;
}

export async function listApiKeys(
  params: { include_revoked?: boolean; limit?: number; offset?: number } = {},
): Promise<ApiKeyListResponse> {
  const qs = new URLSearchParams();
  if (params.include_revoked !== undefined)
    qs.set("include_revoked", String(params.include_revoked));
  if (params.limit !== undefined) qs.set("limit", String(params.limit));
  if (params.offset !== undefined) qs.set("offset", String(params.offset));
  const url = `${BASE}/api-keys${qs.toString() ? `?${qs.toString()}` : ""}`;
  const r = await apiFetch(url);
  if (!r.ok) throw await formatError(r);
  return r.json();
}

export async function createApiKey(
  payload: ApiKeyCreatePayload,
): Promise<ApiKeyCreateResponse> {
  const r = await apiFetch(`${BASE}/api-keys`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
  if (!r.ok) throw await formatError(r);
  return r.json();
}

export async function regenerateApiKey(
  keyId: number,
): Promise<ApiKeyCreateResponse> {
  const r = await apiFetch(`${BASE}/api-keys/${keyId}/regenerate`, {
    method: "POST",
  });
  if (!r.ok) throw await formatError(r);
  return r.json();
}

export async function revokeApiKey(keyId: number): Promise<ApiKeyOut> {
  const r = await apiFetch(`${BASE}/api-keys/${keyId}`, { method: "DELETE" });
  if (!r.ok) throw await formatError(r);
  return r.json();
}

// --- Conversao Listagem AJUS -> Planilha de migracao L1 ---

/**
 * Envia o XLSX da Listagem de Acoes Judiciais (saida AJUS) e recebe de
 * volta o XLSX no formato MODELO LEGAL ONE. O nome sugerido vem do
 * header Content-Disposition; se vier ausente cai no fallback fixo.
 */
export async function converterListagemL1(
  file: File,
): Promise<{ blob: Blob; filename: string }> {
  const fd = new FormData();
  fd.append("file", file);
  const r = await apiFetch(`${BASE}/conversao-l1`, {
    method: "POST",
    body: fd,
  });
  if (!r.ok) throw await formatError(r);
  const blob = await r.blob();
  const cd = r.headers.get("content-disposition") || "";
  let filename = "PLANILHA_MIGRACAO_COMPLETA.xlsx";
  // tenta filename*=UTF-8''<encoded> primeiro (RFC 5987)
  const star = /filename\*=UTF-8''([^;]+)/i.exec(cd);
  if (star?.[1]) {
    try {
      filename = decodeURIComponent(star[1]);
    } catch {
      // ignora
    }
  } else {
    const plain = /filename="?([^"]+)"?/i.exec(cd);
    if (plain?.[1]) filename = plain[1];
  }
  return { blob, filename };
}
