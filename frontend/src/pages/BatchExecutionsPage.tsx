import { useMemo, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  Clock,
  Filter,
  ListChecks,
  Loader2,
  RefreshCw,
  RotateCw,
  XCircle,
} from 'lucide-react';

import { apiFetch } from '@/lib/api-client';
import { useAuth } from '@/hooks/useAuth';
import { useToast } from '@/hooks/use-toast';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';

interface BatchItem {
  id: number;
  process_number: string;
  status: string;
  created_task_id: number | null;
  error_message: string | null;
  fingerprint: string | null;
}

interface BatchExecution {
  id: number;
  source: string;
  source_filename: string | null;
  requested_by_email: string | null;
  status: string;
  start_time: string;
  end_time: string | null;
  total_items: number;
  success_count: number;
  failure_count: number;
  items: BatchItem[];
}

interface ErrorGroup {
  error_message: string;
  count: number;
  item_ids: number[];
  sample_processes: string[];
}

interface ErrorGroupsResponse {
  execution_id: number;
  total_failed: number;
  groups: ErrorGroup[];
}

const STATUS_META: Record<string, { color: string; label: string }> = {
  CONCLUIDO: { color: 'bg-green-100 text-green-700', label: 'Concluído' },
  CONCLUIDO_COM_FALHAS: { color: 'bg-amber-100 text-amber-700', label: 'Concluído c/ Falhas' },
  PROCESSANDO: { color: 'bg-blue-100 text-blue-700', label: 'Processando' },
  PENDENTE: { color: 'bg-gray-100 text-gray-700', label: 'Pendente' },
  PAUSADO: { color: 'bg-yellow-100 text-yellow-700', label: 'Pausado' },
  CANCELADO: { color: 'bg-red-100 text-red-700', label: 'Cancelado' },
};

const PAGE_SIZES = [10, 20, 50, 100];

const formatDate = (iso: string | null) => {
  if (!iso) return '—';
  return new Intl.DateTimeFormat('pt-BR', {
    dateStyle: 'short',
    timeStyle: 'medium',
    timeZone: 'America/Sao_Paulo',
  }).format(new Date(iso));
};

const duration = (start: string, end: string | null): string => {
  if (!end) return '—';
  const ms = new Date(end).getTime() - new Date(start).getTime();
  if (ms < 1000) return '<1s';
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const rs = s % 60;
  if (m < 60) return `${m}m ${rs}s`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
};

const StatusBadge = ({ status }: { status: string }) => {
  const meta = STATUS_META[status] ?? { color: 'bg-gray-100 text-gray-700', label: status };
  return <span className={`inline-block text-xs font-medium px-2 py-0.5 rounded-full ${meta.color}`}>{meta.label}</span>;
};

const ItemStatusIcon = ({ status }: { status: string }) => {
  const s = status.toUpperCase();
  if (s.includes('SUCESSO') || s.includes('SUCCESS') || s === 'CONCLUIDO') return <CheckCircle2 className="h-4 w-4 text-green-600" />;
  if (s.includes('FALHA') || s.includes('ERRO') || s.includes('FAIL') || s.includes('ERROR')) return <XCircle className="h-4 w-4 text-red-600" />;
  return <Clock className="h-4 w-4 text-gray-500" />;
};

// ─────────────────────────────────────────────────────────────
// Bloco de grupos de erro (lazy fetch + retry por grupo)
// ─────────────────────────────────────────────────────────────
function ErrorGroupsBlock({ executionId, canRetry }: { executionId: number; canRetry: boolean }) {
  const qc = useQueryClient();
  const { toast } = useToast();

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['batch-error-groups', executionId],
    queryFn: async () => {
      const res = await apiFetch(`/api/v1/admin/batch-executions/${executionId}/error-groups`);
      if (!res.ok) throw new Error('Falha ao carregar grupos de erro');
      return res.json() as Promise<ErrorGroupsResponse>;
    },
  });

  const retryMut = useMutation({
    mutationFn: async (itemIds: number[] | null) => {
      const res = await apiFetch(`/api/v1/admin/batch-executions/${executionId}/retry`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ item_ids: itemIds }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Falha ao enfileirar retry');
      }
      return res.json();
    },
    onSuccess: (_d, itemIds) => {
      toast({
        title: 'Reprocessamento enfileirado',
        description: itemIds ? `${itemIds.length} itens enviados para retry.` : 'Todas as falhas enviadas para retry.',
      });
      qc.invalidateQueries({ queryKey: ['batch-executions'] });
      qc.invalidateQueries({ queryKey: ['batch-error-groups', executionId] });
    },
    onError: (e: Error) => toast({ title: 'Erro', description: e.message, variant: 'destructive' }),
  });

  if (isLoading) return <div className="text-xs text-muted-foreground flex items-center gap-2"><Loader2 className="h-3 w-3 animate-spin" />Carregando grupos de erro...</div>;
  if (error) return <p className="text-xs text-red-700">{(error as Error).message}</p>;
  if (!data || data.total_failed === 0) return null;

  return (
    <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg">
      <div className="flex items-center justify-between mb-2">
        <div className="text-sm font-medium text-red-900">
          {data.total_failed} falhas agrupadas em {data.groups.length} tipos de erro
        </div>
        <div className="flex gap-2">
          <Button size="sm" variant="outline" onClick={() => refetch()}>
            <RefreshCw className="h-3 w-3 mr-1" />
            Recalcular
          </Button>
          {canRetry && (
            <Button
              size="sm"
              onClick={() => retryMut.mutate(null)}
              disabled={retryMut.isPending}
            >
              {retryMut.isPending ? <Loader2 className="h-3 w-3 mr-1 animate-spin" /> : <RotateCw className="h-3 w-3 mr-1" />}
              Reprocessar todas ({data.total_failed})
            </Button>
          )}
        </div>
      </div>
      <div className="space-y-2">
        {data.groups.map((g, i) => (
          <div key={i} className="flex items-start gap-3 p-2 bg-white border rounded">
            <XCircle className="h-4 w-4 text-red-600 shrink-0 mt-0.5" />
            <div className="flex-1 min-w-0">
              <div className="text-sm break-words">{g.error_message}</div>
              <div className="text-xs text-muted-foreground mt-1">
                {g.count} itens · Ex: {g.sample_processes.join(', ')}
                {g.count > g.sample_processes.length && '...'}
              </div>
            </div>
            {canRetry && (
              <Button
                size="sm"
                variant="outline"
                onClick={() => retryMut.mutate(g.item_ids)}
                disabled={retryMut.isPending}
                className="shrink-0"
              >
                <RotateCw className="h-3 w-3 mr-1" />
                Reprocessar {g.count}
              </Button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Página principal
// ─────────────────────────────────────────────────────────────
export default function BatchExecutionsPage() {
  const { isAdmin, canScheduleBatch } = useAuth();
  const canRetry = isAdmin || canScheduleBatch;

  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [sourceFilter, setSourceFilter] = useState<string>('all');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  const { data: executions = [], isLoading, isFetching, error, refetch } = useQuery({
    queryKey: ['batch-executions'],
    queryFn: async () => {
      const res = await apiFetch('/api/v1/dashboard/batch-executions?limit=500');
      if (!res.ok) throw new Error('Falha ao carregar histórico de lotes');
      return res.json() as Promise<BatchExecution[]>;
    },
    refetchInterval: 30000,
  });

  const sources = useMemo(() => {
    const s = new Set(executions.map((e) => e.source).filter(Boolean));
    return Array.from(s).sort();
  }, [executions]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return executions.filter((e) => {
      if (statusFilter !== 'all' && e.status !== statusFilter) return false;
      if (sourceFilter !== 'all' && e.source !== sourceFilter) return false;
      if (q) {
        const hay = [String(e.id), e.source, e.source_filename ?? '', e.requested_by_email ?? ''].join(' ').toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [executions, statusFilter, sourceFilter, search]);

  const stats = useMemo(() => {
    const totalItems = filtered.reduce((acc, e) => acc + e.total_items, 0);
    const totalSuccess = filtered.reduce((acc, e) => acc + e.success_count, 0);
    const totalFailure = filtered.reduce((acc, e) => acc + e.failure_count, 0);
    return { totalExec: filtered.length, totalItems, totalSuccess, totalFailure };
  }, [filtered]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const currentPage = Math.min(page, totalPages);
  const pageStart = (currentPage - 1) * pageSize;
  const pageEnd = pageStart + pageSize;
  const pageRows = filtered.slice(pageStart, pageEnd);

  // Reset página ao filtrar
  const resetPage = () => setPage(1);

  const toggle = (id: number) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
            <ListChecks className="h-6 w-6" />
            Acompanhamento de Lotes
          </h1>
          <p className="text-muted-foreground">
            Histórico das execuções dos motores de criação em lote (OneRequest, OneSid, Planilha).
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => refetch()} disabled={isFetching}>
            <RefreshCw className={`h-4 w-4 mr-2 ${isFetching ? 'animate-spin' : ''}`} />
            Atualizar
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card><CardHeader className="pb-2"><CardDescription>Execuções</CardDescription><CardTitle className="text-2xl">{stats.totalExec}</CardTitle></CardHeader></Card>
        <Card><CardHeader className="pb-2"><CardDescription>Itens processados</CardDescription><CardTitle className="text-2xl">{stats.totalItems.toLocaleString('pt-BR')}</CardTitle></CardHeader></Card>
        <Card><CardHeader className="pb-2"><CardDescription>Sucessos</CardDescription><CardTitle className="text-2xl text-green-700">{stats.totalSuccess.toLocaleString('pt-BR')}</CardTitle></CardHeader></Card>
        <Card><CardHeader className="pb-2"><CardDescription>Falhas</CardDescription><CardTitle className="text-2xl text-red-700">{stats.totalFailure.toLocaleString('pt-BR')}</CardTitle></CardHeader></Card>
      </div>

      <Card>
        <CardContent className="pt-6">
          <div className="flex flex-wrap items-center gap-2">
            <Filter className="h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Buscar por ID, arquivo, solicitante..."
              value={search}
              onChange={(e) => { setSearch(e.target.value); resetPage(); }}
              className="w-full sm:w-72"
            />
            <Select value={statusFilter} onValueChange={(v) => { setStatusFilter(v); resetPage(); }}>
              <SelectTrigger className="w-52"><SelectValue placeholder="Status" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Todos status</SelectItem>
                {Object.keys(STATUS_META).map((k) => <SelectItem key={k} value={k}>{STATUS_META[k].label}</SelectItem>)}
              </SelectContent>
            </Select>
            <Select value={sourceFilter} onValueChange={(v) => { setSourceFilter(v); resetPage(); }}>
              <SelectTrigger className="w-52"><SelectValue placeholder="Motor" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Todos motores</SelectItem>
                {sources.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
        </CardContent>
      </Card>

      {error ? (
        <Alert variant="destructive"><AlertCircle className="h-4 w-4" /><AlertTitle>Erro</AlertTitle><AlertDescription>{(error as Error).message}</AlertDescription></Alert>
      ) : isLoading ? (
        <div className="flex items-center justify-center h-40"><Loader2 className="h-6 w-6 animate-spin" /></div>
      ) : filtered.length === 0 ? (
        <Alert><AlertCircle className="h-4 w-4" /><AlertTitle>Nenhuma execução encontrada</AlertTitle><AlertDescription>Ajuste os filtros ou aguarde a próxima execução.</AlertDescription></Alert>
      ) : (
        <>
          <div className="space-y-2">
            {pageRows.map((e) => {
              const isOpen = expanded.has(e.id);
              const pct = e.total_items ? Math.round((e.success_count / e.total_items) * 100) : 0;
              return (
                <Card key={e.id} className="overflow-hidden">
                  <button type="button" onClick={() => toggle(e.id)} className="w-full text-left px-4 py-3 hover:bg-muted/40 transition flex items-center gap-3">
                    {isOpen ? <ChevronDown className="h-4 w-4 shrink-0" /> : <ChevronRight className="h-4 w-4 shrink-0" />}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-mono text-xs text-muted-foreground">#{e.id}</span>
                        <span className="font-medium">{e.source}</span>
                        {e.source_filename && <span className="text-xs text-muted-foreground truncate">· {e.source_filename}</span>}
                        <StatusBadge status={e.status} />
                      </div>
                      <div className="mt-1 text-xs text-muted-foreground flex flex-wrap gap-3">
                        <span>{formatDate(e.start_time)}</span>
                        <span>Duração: {duration(e.start_time, e.end_time)}</span>
                        {e.requested_by_email && <span>Por: {e.requested_by_email}</span>}
                      </div>
                    </div>
                    <div className="shrink-0 text-right">
                      <div className="text-sm font-medium">
                        <span className="text-green-700">{e.success_count}</span>
                        <span className="text-muted-foreground"> / </span>
                        <span className="text-red-700">{e.failure_count}</span>
                        <span className="text-muted-foreground"> de {e.total_items}</span>
                      </div>
                      <div className="w-32 h-1.5 bg-muted rounded-full mt-1 overflow-hidden">
                        <div className="h-full bg-green-500" style={{ width: `${pct}%` }} />
                      </div>
                    </div>
                  </button>

                  {isOpen && (
                    <CardContent className="border-t bg-muted/20 pt-4">
                      {e.failure_count > 0 && <ErrorGroupsBlock executionId={e.id} canRetry={canRetry} />}
                      {e.items.length === 0 ? (
                        <p className="text-sm text-muted-foreground">Sem detalhes de itens.</p>
                      ) : (
                        <div className="space-y-1 max-h-96 overflow-auto">
                          {e.items.map((it) => (
                            <div key={it.id} className="flex items-start gap-3 text-sm py-1.5 border-b last:border-0">
                              <ItemStatusIcon status={it.status} />
                              <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-2 flex-wrap">
                                  <span className="font-mono text-xs">{it.process_number}</span>
                                  <Badge variant="outline" className="text-xs">{it.status}</Badge>
                                  {it.created_task_id && <span className="text-xs text-muted-foreground">→ tarefa #{it.created_task_id}</span>}
                                </div>
                                {it.error_message && <p className="text-xs text-red-700 mt-0.5 break-words">{it.error_message}</p>}
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </CardContent>
                  )}
                </Card>
              );
            })}
          </div>

          {/* Paginação */}
          <div className="flex items-center justify-between flex-wrap gap-3 pt-2">
            <div className="text-xs text-muted-foreground">
              Mostrando {pageStart + 1}–{Math.min(pageEnd, filtered.length)} de {filtered.length}
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground">Por página:</span>
              <Select value={String(pageSize)} onValueChange={(v) => { setPageSize(Number(v)); setPage(1); }}>
                <SelectTrigger className="w-20 h-8"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {PAGE_SIZES.map((n) => <SelectItem key={n} value={String(n)}>{n}</SelectItem>)}
                </SelectContent>
              </Select>
              <div className="flex items-center gap-1 ml-2">
                <Button size="icon" variant="outline" className="h-8 w-8" onClick={() => setPage(1)} disabled={currentPage === 1}><ChevronsLeft className="h-4 w-4" /></Button>
                <Button size="icon" variant="outline" className="h-8 w-8" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={currentPage === 1}><ChevronLeft className="h-4 w-4" /></Button>
                <span className="text-sm px-2 min-w-[5rem] text-center">
                  Página {currentPage} / {totalPages}
                </span>
                <Button size="icon" variant="outline" className="h-8 w-8" onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={currentPage === totalPages}><ChevronRight className="h-4 w-4" /></Button>
                <Button size="icon" variant="outline" className="h-8 w-8" onClick={() => setPage(totalPages)} disabled={currentPage === totalPages}><ChevronsRight className="h-4 w-4" /></Button>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
