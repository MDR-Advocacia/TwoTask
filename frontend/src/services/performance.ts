// Serviço do módulo "Minha Equipe" (Performance de Equipes).
// Self-contained (tipos + chamadas) pra não inflar o api.ts.

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

export type Categoria = "operacional" | "profundo" | "ruido";

export interface PessoaMetrica {
  id: number;
  nome: string;
  cargo: string | null;
  squad: string | null;
  posicao: string | null;
  concluido: number;
  dias_ativos: number;
  throughput_dia: number;
  no_prazo_pct: number | null;
  cycle_dias: number | null;
  backlog: number;
  operacional_n: number;
  profundo_n: number;
  ruido_n: number;
}

export interface EquipeKpis {
  concluido: number;
  backlog: number;
  pessoas_ativas: number;
  pessoas_total: number;
  no_prazo_pct: number | null;
}

export interface EquipeResponse {
  periodo_dias: number;
  kpis: EquipeKpis;
  pessoas: PessoaMetrica[];
}

export interface MixItem {
  subtipo: string;
  categoria: Categoria;
  volume: number;
  cycle_dias: number | null;
  no_prazo_pct: number | null;
}

export interface RitmoOcio {
  volume: number;
  cadencia_seg: number | null;
  ocio_pct: number | null;
  dias: number;
  oper_share: number | null;
}

export interface PassadoKpis {
  concluido: number;
  dias_ativos: number;
  throughput_dia: number;
  no_prazo_pct: number | null;
  cycle_dias: number | null;
}

export interface PendenteTipo {
  subtipo: string;
  categoria: Categoria;
  total: number;
  atrasado: number;
}

export interface UrgenteItem {
  subtipo: string;
  prazo: string | null;
  dias: number | null;
  atrasado: boolean;
  cnj: string | null;
  pasta: string | null;
}

export interface PessoaDetalhe {
  pessoa: { id: number; nome: string; cargo: string | null; squad: string | null; posicao: string | null };
  periodo_dias: number;
  passado: { kpis: PassadoKpis; ritmo: RitmoOcio; mix: MixItem[] };
  futuro: {
    pendente: number;
    atrasado: number;
    sem_prazo: number;
    por_tipo: PendenteTipo[];
    urgentes: UrgenteItem[];
  };
}

export interface TipoItem {
  subtipo: string;
  categoria: Categoria;
  volume: number;
  pessoas: number;
  cycle_dias: number | null;
  densidade: number | null;
}

export async function getEquipe(days = 30, cargo?: string): Promise<EquipeResponse> {
  const qs = new URLSearchParams({ days: String(days) });
  if (cargo) qs.set("cargo", cargo);
  return json(await apiFetch(`${BASE}/equipe?${qs.toString()}`));
}

export async function getCargos(): Promise<string[]> {
  const r = await json<{ cargos: string[] }>(await apiFetch(`${BASE}/cargos`));
  return r.cargos;
}

export async function getPessoa(id: number, days = 30): Promise<PessoaDetalhe> {
  return json(await apiFetch(`${BASE}/pessoa/${id}?days=${days}`));
}

export async function getTipos(days = 30): Promise<TipoItem[]> {
  const r = await json<{ tipos: TipoItem[] }>(await apiFetch(`${BASE}/tipos?days=${days}`));
  return r.tipos;
}

export interface VazaoItem {
  id: number;
  nome: string;
  cargo: string | null;
  concluido: number;
  throughput_dia: number;
}

export interface BacklogItem {
  id: number;
  nome: string;
  cargo: string | null;
  backlog: number;
  atrasado: number;
}

export interface JornadaItem {
  id: number;
  nome: string;
  cargo: string | null;
  inicio_h: number;
  fim_h: number;
  hands_on_h: number;
  ocio_pct: number | null;
  dias: number;
  oper_share: number;
}

export interface TopTipoItem {
  subtipo: string;
  categoria: Categoria;
  volume: number;
  pendente: number;
  atrasado: number;
}

export interface DashboardData {
  periodo_dias: number;
  kpis: { atrasado_total: number; backlog_total: number };
  vazao: VazaoItem[];
  backlog: BacklogItem[];
  jornada: JornadaItem[];
  top_tipos: TopTipoItem[];
}

export async function getDashboard(days = 30): Promise<DashboardData> {
  return json(await apiFetch(`${BASE}/dashboard?days=${days}`));
}

export async function downloadExport(params: {
  escopo: "atrasado" | "pendente" | "concluido";
  days: number;
  pessoa_id?: number;
  subtipo?: string;
}): Promise<void> {
  const qs = new URLSearchParams({ escopo: params.escopo, days: String(params.days) });
  if (params.pessoa_id) qs.set("pessoa_id", String(params.pessoa_id));
  if (params.subtipo) qs.set("subtipo", params.subtipo);
  const res = await apiFetch(`${BASE}/export?${qs.toString()}`);
  if (!res.ok) throw new Error(`Erro ${res.status} ao exportar`);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `minha-equipe-${params.escopo}.xlsx`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// Baixa o PDF (download via <a>) em vez de window.open: o open roda DEPOIS dos
// ~20s de geração (Sonnet), fora do gesto do usuário, e o navegador bloqueia o
// popup silenciosamente. O download por <a download> funciona após o await.
async function fetchPdfAndDownload(path: string, filename: string): Promise<void> {
  const res = await apiFetch(path);
  if (!res.ok) throw new Error(`Erro ${res.status} ao gerar o relatório`);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}

export async function abrirRelatorioSetor(days: number): Promise<void> {
  return fetchPdfAndDownload(`${BASE}/relatorio-setor?days=${days}`, "relatorio-minha-equipe-setor.pdf");
}

export async function abrirRelatorioPessoa(id: number, days: number): Promise<void> {
  return fetchPdfAndDownload(`${BASE}/pessoa/${id}/relatorio?days=${days}`, `raio-x-pessoa-${id}.pdf`);
}

// ── Relatórios como job persistente ──
export interface RelatorioItem {
  id: number;
  tipo: string;
  label: string;
  days: number;
  status: "processando" | "pronto" | "erro";
  erro: string | null;
  criado_em: string | null;
  concluido_em: string | null;
}

export async function criarRelatorio(
  tipo: "setor" | "pessoa",
  days: number,
  pessoa_id?: number,
): Promise<{ id: number; label: string; status: string }> {
  return json(
    await apiFetch(`${BASE}/relatorios`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tipo, days, pessoa_id }),
    }),
  );
}

export async function listarRelatorios(): Promise<RelatorioItem[]> {
  const r = await json<{ items: RelatorioItem[] }>(await apiFetch(`${BASE}/relatorios`));
  return r.items;
}

export async function downloadRelatorioById(id: number): Promise<void> {
  return fetchPdfAndDownload(`${BASE}/relatorios/${id}/download`, `relatorio-minha-equipe-${id}.pdf`);
}

// ── Ingestão dos dados (download do relatório do L1) ──
export interface SyncStatus {
  last_sync: {
    ok: boolean;
    tarefas: number;
    data: string;
    relatorio: string;
    em: string;
    bytes: number;
  } | null;
  ja_sincronizou_hoje: boolean;
}

export async function getSyncStatus(): Promise<SyncStatus> {
  return json(await apiFetch(`${BASE}/sync`));
}

export async function triggerSync(): Promise<{ ok: boolean; mensagem: string }> {
  return json(await apiFetch(`${BASE}/sync`, { method: "POST" }));
}
