// frontend/src/services/contatosApi.ts
//
// Cliente do modulo Atualizacao de Contatos LegalOne. Modulo proprio (nao
// mexe no services/api.ts grande) — endpoints em /api/v1/contatos-legalone.

import { apiFetch } from "@/lib/api-client";

export interface ContatoBatch {
  id: number;
  nome: string;
  description: string | null;
  dry_run: boolean;
  status: string;
  is_terminal: boolean;
  progress_pct: number;
  total_itens: number;
  total_sucesso: number;
  total_erro: number;
  total_pendente: number;
  source_filename: string | null;
  error_message: string | null;
  created_by_user_id: number | null;
  created_at: string | null;
  updated_at: string | null;
  finished_at: string | null;
}

export interface ContatoItemResult {
  dry_run: boolean;
  found: number | null;
  contact_id: number | null;
  city_id: number | null;
  created: { phones: number; emails: number; addresses: number; name: number };
  planned: { phones: any[]; emails: any[]; addresses: any[]; name: any[] };
  skipped: string[];
  errors: string[];
}

export interface ContatoItem {
  id: number;
  batch_id: number;
  row_number: number | null;
  doc_number: string;
  doc_kind: string;
  name: string | null;
  nome_abreviado: string | null;
  contact_id: number | null;
  status: string;
  phones: string[];
  email: string | null;
  address: Record<string, any> | null;
  result: ContatoItemResult | null;
  error_message: string | null;
  attempts: number;
  created_at: string | null;
  processed_at: string | null;
}

export interface ContatoIssue {
  row_number: number; // 0 = cabeçalho
  column: string;
  value: string;
  error: string;
  severity: "error" | "warning";
}

export interface ContatoPreview {
  filename: string;
  headers: string[];
  summary: Record<string, number>;
  sample: Array<{
    row_number: number;
    doc_number: string;
    doc_kind: string;
    name: string | null;
    nome_abreviado: string | null;
    phones: string[];
    email: string | null;
    address: Record<string, any> | null;
  }>;
  invalid: Array<{ row_number: number; reason: string; raw_doc: string }>;
  issues: ContatoIssue[];
  has_blocking: boolean;
}

export interface Paginated<T> {
  total: number;
  items: T[];
}

const BASE = "/api/v1/contatos-legalone";

async function asJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail: any = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      /* corpo nao-json */
    }
    // Detail estruturado (ex.: validação bloqueante): anexa issues no Error.
    if (detail && typeof detail === "object") {
      const e = new Error(detail.message || `HTTP ${res.status}`);
      (e as any).issues = detail.issues || [];
      (e as any).summary = detail.summary;
      throw e;
    }
    throw new Error(typeof detail === "string" ? detail : `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export async function previewContatosCsv(file: File): Promise<ContatoPreview> {
  const fd = new FormData();
  fd.append("file", file);
  return asJson(await apiFetch(`${BASE}/preview`, { method: "POST", body: fd }));
}

export async function createContatosBatch(params: {
  nome: string;
  description?: string;
  dryRun: boolean;
  file: File;
}): Promise<{ batch: ContatoBatch; summary: Record<string, any> }> {
  const fd = new FormData();
  fd.append("nome", params.nome);
  if (params.description) fd.append("description", params.description);
  fd.append("dry_run", params.dryRun ? "true" : "false");
  fd.append("file", params.file);
  return asJson(await apiFetch(`${BASE}/batches`, { method: "POST", body: fd }));
}

export async function listContatosBatches(opts: {
  limit?: number;
  offset?: number;
  status?: string;
}): Promise<Paginated<ContatoBatch>> {
  const q = new URLSearchParams();
  if (opts.limit != null) q.set("limit", String(opts.limit));
  if (opts.offset != null) q.set("offset", String(opts.offset));
  if (opts.status) q.set("status", opts.status);
  return asJson(await apiFetch(`${BASE}/batches?${q.toString()}`));
}

export async function getContatosBatch(id: number): Promise<ContatoBatch> {
  return asJson(await apiFetch(`${BASE}/batches/${id}`));
}

export async function getContatosBatchStatus(id: number): Promise<ContatoBatch> {
  return asJson(await apiFetch(`${BASE}/batches/${id}/status`));
}

export async function listContatosBatchItems(
  id: number,
  opts: { limit?: number; offset?: number; status?: string },
): Promise<Paginated<ContatoItem>> {
  const q = new URLSearchParams();
  if (opts.limit != null) q.set("limit", String(opts.limit));
  if (opts.offset != null) q.set("offset", String(opts.offset));
  if (opts.status) q.set("status", opts.status);
  return asJson(await apiFetch(`${BASE}/batches/${id}/items?${q.toString()}`));
}

export async function retryContatosBatch(
  id: number,
): Promise<{ batch: ContatoBatch; re_enqueued: number }> {
  return asJson(await apiFetch(`${BASE}/batches/${id}/retry-failed`, { method: "POST" }));
}

export async function cancelContatosBatch(id: number): Promise<ContatoBatch> {
  return asJson(await apiFetch(`${BASE}/batches/${id}/cancel`, { method: "POST" }));
}

export async function deleteContatosBatch(id: number): Promise<void> {
  const res = await apiFetch(`${BASE}/batches/${id}`, { method: "DELETE" });
  if (!res.ok && res.status !== 204) {
    throw new Error(`HTTP ${res.status}`);
  }
}

export async function downloadContatosTemplate(): Promise<Blob> {
  const res = await apiFetch(`${BASE}/template`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.blob();
}

// ─── Helpers de UI compartilhados ─────────────────────────────────────────

export const CONTATO_BATCH_BADGE: Record<
  string,
  { label: string; className: string }
> = {
  PROCESSING: { label: "Processando", className: "bg-blue-100 text-blue-700" },
  DONE: { label: "Concluído", className: "bg-green-100 text-green-700" },
  DONE_WITH_ERRORS: { label: "Concluído c/ erros", className: "bg-amber-100 text-amber-700" },
  CANCELLED: { label: "Cancelado", className: "bg-red-100 text-red-700" },
};

export const CONTATO_ITEM_BADGE: Record<
  string,
  { label: string; className: string }
> = {
  PENDENTE: { label: "Pendente", className: "bg-gray-100 text-gray-700" },
  PROCESSANDO: { label: "Processando", className: "bg-blue-100 text-blue-700" },
  SUCESSO: { label: "Sucesso", className: "bg-green-100 text-green-700" },
  ERRO: { label: "Erro", className: "bg-red-100 text-red-700" },
  NAO_ENCONTRADO: { label: "Não encontrado", className: "bg-amber-100 text-amber-700" },
  DUPLICADO: { label: "Duplicado", className: "bg-purple-100 text-purple-700" },
};

export function fmtContatoDate(iso: string | null): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat("pt-BR", {
    dateStyle: "short",
    timeStyle: "short",
    timeZone: "America/Sao_Paulo",
  }).format(new Date(iso));
}
