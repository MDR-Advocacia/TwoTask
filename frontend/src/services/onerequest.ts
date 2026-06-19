// Serviço do módulo OneRequest (DMIs do Banco do Brasil).
// Self-contained (tipos + chamadas) pra não inflar o api.ts gigante.

import { apiFetch } from "@/lib/api-client";

const BASE = "/api/v1/onerequest";

export type Farol = "cinza" | "vermelho" | "amarelo" | "roxo" | "verde";

export interface OnerequestSolicitacao {
  id: number;
  numero_solicitacao: string;
  titulo: string | null;
  npj_direcionador: string | null;
  prazo: string | null;
  texto_dmi: string | null;
  numero_processo: string | null;
  proc_utilizavel: boolean;
  polo: string | null;
  recebido_em: string | null;
  status_sistema: string;
  status_tratamento: string;
  responsavel_user_id: number | null;
  responsavel_nome: string | null;
  setor: string | null;
  data_agendamento: string | null;
  anotacao: string | null;
  created_task_id: number | null;
  linked_lawsuit_id: number | null;
  last_error: string | null;
  farol: Farol;
}

export interface ListResponse {
  total: number;
  kpis: Record<string, number>;
  items: OnerequestSolicitacao[];
}

export interface ListParams {
  status_sistema?: string;
  status_tratamento?: string;
  responsavel_user_id?: number;
  busca?: string;
  farol?: string;
  sem_responsavel?: boolean;
  limit?: number;
  offset?: number;
}

export interface Sugestao {
  setor: string | null;
  setor_confianca: string | null;
  responsavel_user_id: number | null;
  responsavel_nome: string | null;
  responsavel_confianca: number | null;
  data_agendamento: string | null;
}

export interface L1Task {
  task_id: number | null;
  description: string | null;
  status_id: number | null;
  status_label: string | null;
  end_date_time: string | null;
  l1_url: string | null;
}

export interface L1Tarefas {
  lawsuit_id: number | null;
  l1_url: string | null;
  pendentes: L1Task[];
  concluidas: L1Task[];
  resolvido: boolean;
  check_failed: boolean;
}

export interface Anotacao {
  id: number;
  texto: string;
  autor_nome: string | null;
  created_at: string | null;
}

export interface Estado {
  last_ingest_at: string | null;
  abertas: number;
}

export interface UpdateTratamentoBody {
  responsavel_user_id?: number | null;
  setor?: string | null;
  data_agendamento?: string | null;
  anotacao?: string | null;
  status_tratamento?: string | null;
}

export interface AgendarResult {
  ok: boolean;
  status_tratamento: string;
  created_task_id: number | null;
  mensagem: string;
}

export interface FormUser {
  id: number;
  external_id: number;
  name: string;
  squads: { id: number; name: string }[];
  email?: string | null;
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

export async function listSolicitacoes(params: ListParams): Promise<ListResponse> {
  const qs = new URLSearchParams();
  if (params.status_sistema) qs.set("status_sistema", params.status_sistema);
  if (params.status_tratamento) qs.set("status_tratamento", params.status_tratamento);
  if (params.responsavel_user_id)
    qs.set("responsavel_user_id", String(params.responsavel_user_id));
  if (params.busca) qs.set("busca", params.busca);
  if (params.farol) qs.set("farol", params.farol);
  if (params.sem_responsavel) qs.set("sem_responsavel", "true");
  qs.set("limit", String(params.limit ?? 50));
  qs.set("offset", String(params.offset ?? 0));
  return json(await apiFetch(`${BASE}/solicitacoes?${qs.toString()}`));
}

export async function getOptions(): Promise<{ setores: string[] }> {
  return json(await apiFetch(`${BASE}/options`));
}

export async function updateTratamento(
  id: number,
  body: UpdateTratamentoBody,
): Promise<{ ok: boolean; id: number; status_tratamento: string }> {
  return json(
    await apiFetch(`${BASE}/solicitacoes/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  );
}

export async function agendarSolicitacao(id: number): Promise<AgendarResult> {
  return json(
    await apiFetch(`${BASE}/solicitacoes/${id}/agendar`, { method: "POST" }),
  );
}

// Reusa o endpoint de dados do formulário de tarefas pra popular o
// UserSelector (mesma forma {id, external_id, name, squads}).
export async function getFormUsers(): Promise<FormUser[]> {
  const data = await json<{ users: FormUser[] }>(
    await apiFetch(`/api/v1/tasks/task-creation-data`),
  );
  return data.users ?? [];
}

export async function getEstado(): Promise<Estado> {
  return json(await apiFetch(`${BASE}/estado`));
}

export async function getSugestao(id: number): Promise<Sugestao> {
  return json(await apiFetch(`${BASE}/solicitacoes/${id}/sugestao`));
}

export async function getL1Tarefas(id: number): Promise<L1Tarefas> {
  return json(await apiFetch(`${BASE}/solicitacoes/${id}/l1-tarefas`));
}

export async function listAnotacoes(id: number): Promise<Anotacao[]> {
  return json(await apiFetch(`${BASE}/solicitacoes/${id}/anotacoes`));
}

export async function addAnotacao(id: number, texto: string): Promise<Anotacao> {
  return json(
    await apiFetch(`${BASE}/solicitacoes/${id}/anotacoes`, {
      method: "POST",
      body: JSON.stringify({ texto }),
    }),
  );
}
