// Serviço do módulo Citações BM (monitoramento de citação via DataJud).
// Self-contained (tipos + chamadas) pra não inflar o api.ts gigante.

import { apiFetch } from "@/lib/api-client";

const BASE = "/api/v1/publications/citacoes-bm";

export type StatusCitacao = "PENDENTE" | "CITADO" | "NAO_CITADO";
export type OrigemCitacao = "LISTA_MANUAL" | "L1_AUTO";

export interface CitacaoBMProcesso {
  id: number;
  cnj: string;
  cnj_mask: string | null;
  lawsuit_id: number | null;
  l1_url: string | null;
  office_external_id: number | null;
  office_path: string | null;
  l1_creation_date: string | null;
  tribunal_alias: string | null;
  uf: string | null;
  cidade: string | null;
  acao: string | null;
  cliente: string | null;
  contrario: string | null;
  origem: OrigemCitacao;
  status_citacao: StatusCitacao;
  citado_por_nome: string | null;
  citado_em: string | null;
  observacao: string | null;
  monitoramento_ativo: boolean;
  last_scan_at: string | null;
  last_scan_status: string | null;
  last_movement_at: string | null;
  total_movimentos: number;
  novos_movimentos: number;
  tem_candidato_citacao: boolean;
  created_at: string | null;
}

export interface CitacaoBMMovimento {
  id: number;
  codigo_tpu: number | null;
  nome: string;
  grau: string | null;
  data_hora: string | null;
  complementos: Array<Record<string, unknown>> | null;
  orgao_julgador: string | null;
  is_candidato_citacao: boolean;
  cit_match_termo: string | null;
  lido: boolean;
  captured_at: string | null;
}

export interface CitacaoBMDetail extends CitacaoBMProcesso {
  movimentos: CitacaoBMMovimento[];
  candidatos_count: number;
}

export interface CitacaoBMListResponse {
  total: number;
  items: CitacaoBMProcesso[];
}

export interface CitacaoBMSummary {
  total: number;
  monitorando: number;
  pendentes: number;
  com_novos: number;
  com_candidato: number;
  citados: number;
  nao_citados: number;
}

export interface ListParams {
  status?: StatusCitacao | "";
  origem?: OrigemCitacao | "";
  tribunal_alias?: string;
  uf?: string;
  apenas_com_novos?: boolean;
  arquivados?: "ativos" | "arquivados" | "todos";
  q?: string;
  limit?: number;
  offset?: number;
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      detail = body?.detail || detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export async function getCitacaoSummary(): Promise<CitacaoBMSummary> {
  return json(await apiFetch(`${BASE}/summary`));
}

export async function listCitacaoProcessos(
  params: ListParams,
): Promise<CitacaoBMListResponse> {
  const qs = new URLSearchParams();
  if (params.status) qs.set("status", params.status);
  if (params.origem) qs.set("origem", params.origem);
  if (params.tribunal_alias) qs.set("tribunal_alias", params.tribunal_alias);
  if (params.uf) qs.set("uf", params.uf);
  if (params.apenas_com_novos) qs.set("apenas_com_novos", "true");
  if (params.arquivados) qs.set("arquivados", params.arquivados);
  if (params.q) qs.set("q", params.q);
  qs.set("limit", String(params.limit ?? 50));
  qs.set("offset", String(params.offset ?? 0));
  return json(await apiFetch(`${BASE}?${qs.toString()}`));
}

export async function getCitacaoProcesso(id: number): Promise<CitacaoBMDetail> {
  return json(await apiFetch(`${BASE}/${id}`));
}

export async function ingestCitacaoList(
  text: string,
): Promise<Record<string, unknown>> {
  return json(
    await apiFetch(`${BASE}/ingest/list`, {
      method: "POST",
      body: JSON.stringify({ text }),
    }),
  );
}

export async function ingestCitacaoL1(
  data_corte?: string,
): Promise<Record<string, unknown>> {
  return json(
    await apiFetch(`${BASE}/ingest/l1`, {
      method: "POST",
      body: JSON.stringify({ data_corte: data_corte || null }),
    }),
  );
}

export async function scanCitacaoAll(
  limit?: number,
): Promise<{ started: boolean }> {
  return json(
    await apiFetch(`${BASE}/scan`, {
      method: "POST",
      body: JSON.stringify({ limit: limit ?? null }),
    }),
  );
}

export async function scanCitacaoProcesso(
  id: number,
): Promise<{ status: string; novos: number }> {
  return json(await apiFetch(`${BASE}/${id}/scan`, { method: "POST" }));
}

export async function setCitacaoStatus(
  id: number,
  status: StatusCitacao,
  observacao?: string,
): Promise<CitacaoBMProcesso> {
  return json(
    await apiFetch(`${BASE}/${id}/citacao`, {
      method: "PATCH",
      body: JSON.stringify({ status, observacao: observacao ?? null }),
    }),
  );
}

export async function markCitacaoRead(
  id: number,
): Promise<{ marcados: number }> {
  return json(await apiFetch(`${BASE}/${id}/mark-read`, { method: "POST" }));
}
