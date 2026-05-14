// frontend/src/components/classificador/FilaTab.tsx
//
// Aba "Fila" do ClassificadorPage — mostra PDFs recebidos pelo motor
// dormente (robo de entrega) com 4 KPI cards de metricas + tabela
// paginada com filtros. Auto-refresh a cada 30s.

import { useCallback, useEffect, useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Loader2, RefreshCw, Inbox, AlertCircle, CheckCircle2, Clock } from "lucide-react";
import { useToast } from "@/components/ui/use-toast";
import {
  ClassificadorPendingItem,
  ClassificadorPendingMetrics,
  fetchClassificadorPending,
  fetchClassificadorPendingMetrics,
} from "@/services/api";


const STATUS_BADGE: Record<string, { label: string; variant: "default" | "secondary" | "destructive" | "outline" }> = {
  PENDENTE: { label: "Pendente", variant: "secondary" },
  ALOCADO: { label: "Alocado", variant: "default" },
  PROCESSADO: { label: "Processado", variant: "default" },
  ERRO: { label: "Erro", variant: "destructive" },
};

function fmtInt(v: number | null | undefined): string {
  if (v == null) return "—";
  return v.toLocaleString("pt-BR");
}

function fmtSec(s: number | null | undefined): string {
  if (s == null) return "—";
  if (s < 60) return `${s.toFixed(0)}s`;
  if (s < 3600) return `${(s / 60).toFixed(1)} min`;
  return `${(s / 3600).toFixed(1)} h`;
}

function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
  } catch {
    return iso;
  }
}

function fmtKB(b: number | null | undefined): string {
  if (b == null) return "—";
  return `${(b / 1024).toFixed(1)} KB`;
}


function KpiCard({
  icon: Icon, label, value, sub, accent = "#1A365D",
}: { icon: React.ElementType; label: string; value: string; sub?: string; accent?: string }) {
  return (
    <div className="rounded-md border bg-card p-3 flex items-start gap-3">
      <Icon className="h-5 w-5 mt-1 shrink-0" style={{ color: accent }} />
      <div className="min-w-0 flex-1">
        <div className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</div>
        <div className="text-xl font-semibold mt-0.5" style={{ color: accent }}>{value}</div>
        {sub && <div className="text-[11px] text-muted-foreground mt-0.5">{sub}</div>}
      </div>
    </div>
  );
}


export default function FilaTab() {
  const { toast } = useToast();
  const [items, setItems] = useState<ClassificadorPendingItem[]>([]);
  const [total, setTotal] = useState(0);
  const [metrics, setMetrics] = useState<ClassificadorPendingMetrics | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [clienteFilter, setClienteFilter] = useState<string>("");
  const [clienteDebounced, setClienteDebounced] = useState<string>("");
  const [loading, setLoading] = useState(false);

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  // Debounce do cliente
  useEffect(() => {
    const t = setTimeout(() => setClienteDebounced(clienteFilter.trim()), 300);
    return () => clearTimeout(t);
  }, [clienteFilter]);

  useEffect(() => {
    setPage(1);
  }, [statusFilter, clienteDebounced]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [list, m] = await Promise.all([
        fetchClassificadorPending({
          status: statusFilter || undefined,
          cliente_nome: clienteDebounced || undefined,
          limit: pageSize,
          offset: (page - 1) * pageSize,
        }),
        fetchClassificadorPendingMetrics(),
      ]);
      setItems(list.items);
      setTotal(list.total);
      setMetrics(m);
    } catch (err) {
      toast({
        title: "Falha ao carregar fila",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setLoading(false);
    }
  }, [statusFilter, clienteDebounced, page, pageSize, toast]);

  useEffect(() => {
    load();
  }, [load]);

  // Auto-refresh a cada 30s
  useEffect(() => {
    const timer = setInterval(() => load(), 30_000);
    return () => clearInterval(timer);
  }, [load]);

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h2 className="text-lg font-semibold tracking-tight flex items-center gap-2">
            <Inbox className="h-5 w-5" />
            Fila do robô
          </h2>
          <p className="text-xs text-muted-foreground">
            PDFs recebidos pelo motor dormente (intake API). O worker agrupa
            em batches de 50 por cliente e cria lotes automaticamente.
            Auto-refresh a cada 30s.
          </p>
        </div>
        <Button variant="ghost" size="sm" onClick={load} disabled={loading}>
          {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
        </Button>
      </div>

      {/* ─── 4 KPI cards ─── */}
      {metrics && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <KpiCard
            icon={Clock}
            label="Aguardando processamento"
            value={fmtInt(metrics.status_counts.pendente)}
            sub={metrics.latencia_segundos.pendente_mais_antigo != null
              ? `Mais antigo: ${fmtSec(metrics.latencia_segundos.pendente_mais_antigo)}`
              : "Nenhum pendente"}
            accent="#D97706"
          />
          <KpiCard
            icon={CheckCircle2}
            label="Processados (30d)"
            value={fmtInt(metrics.status_counts.processado)}
            sub={`Hoje: ${fmtInt(metrics.throughput.pdfs_hoje)} · 7d: ${fmtInt(metrics.throughput.pdfs_7d)}`}
            accent="#38A169"
          />
          <KpiCard
            icon={Inbox}
            label="Throughput médio"
            value={`${metrics.throughput.media_diaria_30d}/dia`}
            sub={`Total 30d: ${fmtInt(metrics.throughput.pdfs_30d)}`}
            accent="#2C5282"
          />
          <KpiCard
            icon={AlertCircle}
            label="Taxa de erro"
            value={metrics.taxa_erro != null ? `${(metrics.taxa_erro * 100).toFixed(1)}%` : "—"}
            sub={`${fmtInt(metrics.status_counts.erro)} com erro · ${fmtSec(metrics.latencia_segundos.media_fila_para_lote)} fila→lote`}
            accent={metrics.taxa_erro && metrics.taxa_erro > 0.05 ? "#C53030" : "#718096"}
          />
        </div>
      )}

      {/* ─── Filtros ─── */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Filtros</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <div>
              <Label htmlFor="fila-status" className="text-[10px]">Status</Label>
              <select
                id="fila-status"
                value={statusFilter}
                onChange={e => setStatusFilter(e.target.value)}
                className="h-8 w-full rounded border bg-background px-2 text-xs"
              >
                <option value="">Todos</option>
                <option value="PENDENTE">Pendente</option>
                <option value="ALOCADO">Alocado</option>
                <option value="PROCESSADO">Processado</option>
                <option value="ERRO">Erro</option>
              </select>
            </div>
            <div>
              <Label htmlFor="fila-cliente" className="text-[10px]">Cliente (busca parcial)</Label>
              <Input
                id="fila-cliente"
                value={clienteFilter}
                onChange={e => setClienteFilter(e.target.value)}
                placeholder="Banco Master, ..."
                className="h-8 text-xs"
              />
            </div>
            {(statusFilter || clienteDebounced) && (
              <div className="flex items-end">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => { setStatusFilter(""); setClienteFilter(""); }}
                >
                  Limpar filtros
                </Button>
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      {/* ─── Tabela ─── */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">
            PDFs na fila ({total})
          </CardTitle>
          <CardDescription className="text-xs">
            Cada linha é 1 PDF do robô. Click no lote_id (quando preenchido) pra ver o lote no Histórico.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {loading && items.length === 0 ? (
            <div className="py-12 text-center text-sm text-muted-foreground">
              <Loader2 className="inline h-4 w-4 animate-spin mr-2" />
              Carregando...
            </div>
          ) : items.length === 0 ? (
            <div className="py-12 text-center text-sm text-muted-foreground">
              Nenhum PDF na fila. Configure o robô pra enviar via POST /api/v1/classificador/intake/pdf.
            </div>
          ) : (
            <>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b text-left text-muted-foreground">
                      <th className="py-1.5 pr-2">#</th>
                      <th className="py-1.5 pr-2">Arquivo</th>
                      <th className="py-1.5 pr-2">Cliente</th>
                      <th className="py-1.5 pr-2">CNJ hint</th>
                      <th className="py-1.5 pr-2">Tamanho</th>
                      <th className="py-1.5 pr-2">Status</th>
                      <th className="py-1.5 pr-2">Lote</th>
                      <th className="py-1.5 pr-2">Recebido</th>
                      <th className="py-1.5 pr-2">Processado</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map(p => {
                      const badge = STATUS_BADGE[p.status] || { label: p.status, variant: "outline" as const };
                      return (
                        <tr key={p.id} className="border-b hover:bg-muted/30">
                          <td className="py-1 pr-2 font-mono">#{p.id}</td>
                          <td className="py-1 pr-2">
                            <div className="truncate max-w-[180px]" title={p.pdf_filename_original || ""}>
                              {p.pdf_filename_original || "—"}
                            </div>
                            <div className="text-[10px] font-mono text-muted-foreground">
                              {p.pdf_sha256.slice(0, 12)}...
                            </div>
                          </td>
                          <td className="py-1 pr-2">{p.cliente_nome || "—"}</td>
                          <td className="py-1 pr-2 font-mono text-[11px]">{p.cnj_hint || "—"}</td>
                          <td className="py-1 pr-2 tabular-nums text-muted-foreground">{fmtKB(p.pdf_bytes)}</td>
                          <td className="py-1 pr-2">
                            <Badge variant={badge.variant}>{badge.label}</Badge>
                            {p.error_message && (
                              <div className="text-[10px] text-red-700 mt-0.5 truncate max-w-[160px]" title={p.error_message}>
                                {p.error_message}
                              </div>
                            )}
                          </td>
                          <td className="py-1 pr-2 font-mono">
                            {p.lote_id ? `#${p.lote_id}` : "—"}
                          </td>
                          <td className="py-1 pr-2 text-muted-foreground">{fmtDateTime(p.received_at)}</td>
                          <td className="py-1 pr-2 text-muted-foreground">{fmtDateTime(p.processed_at)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              <div className="mt-3 flex items-center justify-between text-xs text-muted-foreground">
                <div>
                  Página {page} de {totalPages} · Mostrando {items.length} de {total}
                </div>
                <div className="flex items-center gap-2">
                  <select
                    className="rounded border bg-background px-2 py-1 text-xs"
                    value={pageSize}
                    onChange={e => { setPageSize(Number(e.target.value)); setPage(1); }}
                  >
                    <option value={25}>25</option>
                    <option value={50}>50</option>
                    <option value={100}>100</option>
                  </select>
                  <Button variant="outline" size="sm" disabled={page <= 1}
                    onClick={() => setPage(p => Math.max(1, p - 1))}>
                    Anterior
                  </Button>
                  <Button variant="outline" size="sm" disabled={page >= totalPages}
                    onClick={() => setPage(p => Math.min(totalPages, p + 1))}>
                    Próxima
                  </Button>
                </div>
              </div>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
