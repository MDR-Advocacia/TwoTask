// Gestão do cancelamento automático de duplicadas (whitelist + auditoria).
// Backend admin-gated (/performance/cancel-*).

import { apiFetch } from "@/lib/api-client";

const BASE = "/api/v1/performance";

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `Erro ${res.status}`;
    try {
      detail = (await res.json())?.detail || detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export interface WhitelistItem {
  id: number;
  subtipo: string;
  ativo: boolean;
  criado_em: string | null;
  criado_por: string | null;
}

export interface SubtipoCatalogo {
  subtipo: string;
  volume: number;
}

export interface MassaLogDetalhe {
  candidatos?: number;
  cancelled?: number;
  preservadas?: number;
  falhas?: number;
  dry_run?: boolean;
}

export interface MassaLog {
  id: number;
  iniciado_em: string | null;
  terminado_em: string | null;
  status: string; // running | done | erro
  dry_run: boolean;
  origem: string | null; // scheduler | manual
  total_candidatos: number;
  cancelled: number;
  preservadas: number;
  falhas: number;
  detalhe: Record<string, MassaLogDetalhe>;
}

export async function getWhitelist(): Promise<WhitelistItem[]> {
  const r = await json<{ whitelist: WhitelistItem[] }>(await apiFetch(`${BASE}/cancel-whitelist`));
  return r.whitelist;
}

export async function getCatalogo(busca = ""): Promise<SubtipoCatalogo[]> {
  const qs = new URLSearchParams({ busca });
  const r = await json<{ subtipos: SubtipoCatalogo[] }>(
    await apiFetch(`${BASE}/cancel-whitelist/catalogo?${qs.toString()}`),
  );
  return r.subtipos;
}

export async function addWhitelist(subtipo: string): Promise<WhitelistItem[]> {
  const r = await json<{ whitelist: WhitelistItem[] }>(
    await apiFetch(`${BASE}/cancel-whitelist`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ subtipo }),
    }),
  );
  return r.whitelist;
}

export async function toggleWhitelist(subtipo: string, ativo: boolean): Promise<WhitelistItem[]> {
  const r = await json<{ whitelist: WhitelistItem[] }>(
    await apiFetch(`${BASE}/cancel-whitelist/toggle`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ subtipo, ativo }),
    }),
  );
  return r.whitelist;
}

export async function removeWhitelist(subtipo: string): Promise<WhitelistItem[]> {
  const qs = new URLSearchParams({ subtipo });
  const r = await json<{ whitelist: WhitelistItem[] }>(
    await apiFetch(`${BASE}/cancel-whitelist?${qs.toString()}`, { method: "DELETE" }),
  );
  return r.whitelist;
}

export async function getMassaLogs(): Promise<MassaLog[]> {
  const r = await json<{ logs: MassaLog[] }>(await apiFetch(`${BASE}/cancel-massa/logs`));
  return r.logs;
}

export async function runMassa(dryRun: boolean): Promise<{ started: boolean; dry_run: boolean }> {
  const qs = new URLSearchParams({ dry_run: String(dryRun) });
  return json(await apiFetch(`${BASE}/cancel-massa/run?${qs.toString()}`, { method: "POST" }));
}
