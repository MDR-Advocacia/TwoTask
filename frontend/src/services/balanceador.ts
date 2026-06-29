// Serviço do módulo "Balanceador de Agenda".
// MOCK: leitura real (diagnóstico/matriz/detalhe do pool); escrita simulada.

import { apiFetch } from "@/lib/api-client";

const BASE = "/api/v1/balanceador";

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

export type Situacao = "atrasado" | "fatal_hoje" | "futuro" | "sem_prazo";

export interface Colaborador {
  id: number;
  nome: string;
  cargo: string | null;
  is_supervisor: boolean;
  atrasado: number;
  fatal_hoje: number;
  futuro: number;
  sem_prazo: number;
  total: number;
}

export interface MatrizItem {
  pessoa_id: number;
  subtipo: string;
  total: number;
  atrasado: number;
  fatal_hoje: number;
}

export interface TarefaDetalhe {
  l1_task_id: number | null;
  subtipo: string | null;
  descricao?: string | null; // assunto/anotações (vem no live; no snapshot é enriquecido à parte)
  cnj?: string | null;
  pasta?: string | null;
  uf?: string | null;
  prazo: string | null;
  situacao: Situacao;
}

// ── LIVE: pendentes de uma pessoa direto do L1 (matriz + detalhe) ──
export interface LivePessoaSub {
  subtipo: string;
  total: number;
  atrasado: number;
  fatal_hoje: number;
}
export interface LivePessoa {
  pessoa_id: number;
  nome: string | null;
  resolvido: boolean;
  total_real?: number | null; // total de pendentes COM prazo no L1 (pode ser > carregadas)
  carregadas?: number; // quantas vieram (teto das mais urgentes)
  capado?: boolean; // true = estourou o teto; há mais além das mais urgentes
  subtipos: LivePessoaSub[];
  tarefas: TarefaDetalhe[];
}
export async function getLivePessoa(team: string, pessoaId: number, dias: number): Promise<LivePessoa> {
  const qs = new URLSearchParams({ team, pessoa_id: String(pessoaId), dias: String(dias) });
  return json(await apiFetch(`${BASE}/live-pessoa?${qs.toString()}`));
}

export async function getDiagnostico(team: string): Promise<Colaborador[]> {
  const r = await json<{ colaboradores: Colaborador[] }>(await apiFetch(`${BASE}/diagnostico?team=${team}`));
  return r.colaboradores;
}

export async function getMatriz(team: string, pessoaIds: number[], dias: number): Promise<MatrizItem[]> {
  const qs = new URLSearchParams({ team, pessoas: pessoaIds.join(","), dias: String(dias) });
  const r = await json<{ matriz: MatrizItem[] }>(await apiFetch(`${BASE}/redistribuir?${qs.toString()}`));
  return r.matriz;
}

export async function getTarefas(
  team: string,
  pessoaId: number,
  subtipo: string,
  dias: number,
): Promise<TarefaDetalhe[]> {
  const qs = new URLSearchParams({ team, pessoa_id: String(pessoaId), subtipo, dias: String(dias) });
  const r = await json<{ tarefas: TarefaDetalhe[] }>(await apiFetch(`${BASE}/tarefas?${qs.toString()}`));
  return r.tarefas;
}

// Descrição (assunto/anotações) ao vivo do L1 — não vem no snapshot.
export async function getDescricoes(team: string, ids: number[]): Promise<Record<number, string | null>> {
  if (!ids.length) return {};
  const qs = new URLSearchParams({ team, ids: ids.join(",") });
  const r = await json<{ descricoes: Record<number, string | null> }>(
    await apiFetch(`${BASE}/descricoes?${qs.toString()}`),
  );
  return r.descricoes;
}

// ── Modelo local de "mudanças pendentes" (escrita simulada no mock) ──
export interface MovePendente {
  id: string; // chave local
  fromId: number;
  fromNome: string;
  toId: number;
  toNome: string;
  subtipo: string;
  qtd: number;
  individual: boolean; // true = tarefas escolhidas a dedo; false = em massa por número
  taskIds?: number[];
}

// ── Log de redistribuição (aba Relatórios) ──
export interface RedistribuicaoLog {
  id: number;
  criado_em: string | null;
  criado_por_nome: string | null;
  total_movimentos: number;
  total_tarefas: number;
  origem: string;
  detalhe: MovePendente[];
}

export async function registrarLog(team: string, movimentos: MovePendente[]): Promise<void> {
  const res = await apiFetch(`${BASE}/log?team=${team}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ movimentos }),
  });
  if (!res.ok) throw new Error(`Erro ${res.status} ao registrar o log`);
}

export async function listarLogs(team: string): Promise<RedistribuicaoLog[]> {
  const r = await json<{ logs: RedistribuicaoLog[] }>(await apiFetch(`${BASE}/logs?team=${team}`));
  return r.logs;
}
