// frontend/src/components/classificador/LoteDetailDialog.tsx
//
// Modal de detalhe de 1 lote do Classificador.
// Tabs:
// - Processos: tabela paginada com cnj, extractor, confidence, status, classificacao
// - Batches: lista de batches Anthropic do lote com contadores em tempo real

import { useCallback, useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Input } from "@/components/ui/input";
import { Loader2, RefreshCw, FileText, Sparkles, FileSpreadsheet, Download, Search, X, LayoutDashboard } from "lucide-react";
import { useToast } from "@/components/ui/use-toast";
import {
  ClassificadorBatchSummary,
  ClassificadorLoteSummary,
  ClassificadorProcessoSummary,
  ClassificadorRelatorioSummary,
  downloadClassificadorRelatorio,
  fetchClassificadorBatches,
  fetchClassificadorProcessos,
  fetchClassificadorRelatorios,
  generateClassificadorRelatorio,
  refreshClassificadorBatch,
} from "@/services/api";
import ProcessoDetailDrawer from "@/components/classificador/ProcessoDetailDrawer";
import LoteVisaoTab from "@/components/classificador/LoteVisaoTab";
import {
  ClassificadorFilterOptions,
  fetchClassificadorFilterOptions,
} from "@/services/api";


interface LoteDetailDialogProps {
  lote: ClassificadorLoteSummary | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const PROC_STATUS_BADGE: Record<string, { label: string; variant: "default" | "secondary" | "destructive" | "outline" }> = {
  PENDENTE: { label: "Pendente", variant: "secondary" },
  CAPTURANDO_L1: { label: "Capturando", variant: "default" },
  PRONTO_PARA_CLASSIFICAR: { label: "Pronto", variant: "default" },
  CLASSIFICADO: { label: "Classificado", variant: "default" },
  ERRO_CAPTURA: { label: "Erro captura", variant: "destructive" },
  ERRO_CLASSIFICACAO: { label: "Erro IA", variant: "destructive" },
};

const BATCH_STATUS_BADGE: Record<string, { label: string; variant: "default" | "secondary" | "destructive" | "outline" }> = {
  ENVIADO: { label: "Enviado", variant: "default" },
  EM_PROCESSAMENTO: { label: "Processando", variant: "default" },
  PRONTO: { label: "Pronto pra aplicar", variant: "default" },
  APLICADO: { label: "Aplicado", variant: "secondary" },
  FALHA: { label: "Falhou", variant: "destructive" },
  CANCELADO: { label: "Cancelado", variant: "outline" },
};

function fmtBRL(v: number | null | undefined): string {
  if (v == null) return "—";
  return v.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
  } catch {
    return iso;
  }
}

export default function LoteDetailDialog({ lote, open, onOpenChange }: LoteDetailDialogProps) {
  const { toast } = useToast();
  const [tab, setTab] = useState<string>("visao");
  const [processos, setProcessos] = useState<ClassificadorProcessoSummary[]>([]);
  const [procTotal, setProcTotal] = useState(0);
  const [procPage, setProcPage] = useState(1);
  const [batches, setBatches] = useState<ClassificadorBatchSummary[]>([]);
  const [relatorios, setRelatorios] = useState<ClassificadorRelatorioSummary[]>([]);
  const [loadingProc, setLoadingProc] = useState(false);
  const [loadingBatch, setLoadingBatch] = useState(false);
  const [loadingRel, setLoadingRel] = useState(false);
  const [refreshingBatch, setRefreshingBatch] = useState<number | null>(null);
  const [generatingRel, setGeneratingRel] = useState<"XLSX" | "PDF" | null>(null);
  const [downloadingRel, setDownloadingRel] = useState<number | null>(null);

  // Filtros + busca por CNJ
  const [cnjQuery, setCnjQuery] = useState("");
  const [cnjQueryDebounced, setCnjQueryDebounced] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [sourceFilter, setSourceFilter] = useState<string>("");
  const [poloFilter, setPoloFilter] = useState<string>("");
  const [categoriaFilter, setCategoriaFilter] = useState<string>("");
  const [patrocinioFilter, setPatrocinioFilter] = useState<string>("");

  // Filter options carregadas via /filter-options
  const [filterOptions, setFilterOptions] = useState<ClassificadorFilterOptions | null>(null);

  // Drawer de detalhe do processo
  const [drawerProcessoId, setDrawerProcessoId] = useState<number | null>(null);

  // Carrega filter options quando o lote abre (1x)
  useEffect(() => {
    if (!open || !lote) {
      setFilterOptions(null);
      return;
    }
    let alive = true;
    fetchClassificadorFilterOptions(lote.id)
      .then(opts => { if (alive) setFilterOptions(opts); })
      .catch(() => { /* falha silenciosa — selects ficam sem opcoes */ });
    return () => { alive = false; };
  }, [open, lote]);

  // Debounce do CNJ search (300ms)
  useEffect(() => {
    const t = setTimeout(() => setCnjQueryDebounced(cnjQuery.trim()), 300);
    return () => clearTimeout(t);
  }, [cnjQuery]);

  // Reset page quando filtro muda
  useEffect(() => {
    setProcPage(1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cnjQueryDebounced, statusFilter, sourceFilter, poloFilter, categoriaFilter, patrocinioFilter]);

  const PAGE_SIZE = 50;
  const procTotalPages = Math.max(1, Math.ceil(procTotal / PAGE_SIZE));

  const loadProcessos = useCallback(async () => {
    if (!lote) return;
    setLoadingProc(true);
    try {
      const r = await fetchClassificadorProcessos(lote.id, {
        limit: PAGE_SIZE,
        offset: (procPage - 1) * PAGE_SIZE,
        cnj_match: cnjQueryDebounced || undefined,
        status: statusFilter || undefined,
        source: sourceFilter || undefined,
        polo: poloFilter || undefined,
        categoria_id: categoriaFilter ? Number(categoriaFilter) : undefined,
        patrocinio: patrocinioFilter || undefined,
      });
      setProcessos(r.items);
      setProcTotal(r.total);
    } catch (err) {
      toast({
        title: "Falha ao carregar processos",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setLoadingProc(false);
    }
  }, [lote, procPage, cnjQueryDebounced, statusFilter, sourceFilter, poloFilter, categoriaFilter, patrocinioFilter, toast]);

  const loadBatches = useCallback(async () => {
    if (!lote) return;
    setLoadingBatch(true);
    try {
      const r = await fetchClassificadorBatches(lote.id);
      setBatches(r.items);
    } catch (err) {
      toast({
        title: "Falha ao carregar batches",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setLoadingBatch(false);
    }
  }, [lote, toast]);

  const loadRelatorios = useCallback(async () => {
    if (!lote) return;
    setLoadingRel(true);
    try {
      const r = await fetchClassificadorRelatorios(lote.id);
      setRelatorios(r.items);
    } catch (err) {
      toast({
        title: "Falha ao carregar relatorios",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setLoadingRel(false);
    }
  }, [lote, toast]);

  const handleGenerate = async (formato: "XLSX" | "PDF") => {
    if (!lote) return;
    setGeneratingRel(formato);
    try {
      const r = await generateClassificadorRelatorio(lote.id, formato);
      toast({
        title: `Relatorio ${formato} gerado`,
        description: `Relatorio #${r.id} (${r.file_bytes ? (r.file_bytes / 1024).toFixed(1) + " KB" : "—"}). Status: ${r.status}.`,
      });
      await loadRelatorios();
    } catch (err) {
      toast({
        title: `Falha ao gerar ${formato}`,
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setGeneratingRel(null);
    }
  };

  const handleDownload = async (rel: ClassificadorRelatorioSummary) => {
    if (!lote) return;
    setDownloadingRel(rel.id);
    try {
      const ext = rel.formato.toLowerCase();
      const filename = `classificador-lote-${lote.id}-${rel.id}.${ext}`;
      await downloadClassificadorRelatorio(lote.id, rel.id, filename);
    } catch (err) {
      toast({
        title: "Falha ao baixar relatorio",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setDownloadingRel(null);
    }
  };

  useEffect(() => {
    if (open && lote) {
      if (tab === "processos") loadProcessos();
      if (tab === "batches") loadBatches();
      if (tab === "relatorios") loadRelatorios();
    }
  }, [open, lote, tab, loadProcessos, loadBatches, loadRelatorios]);

  // Auto-refresh quando ha batch in_progress
  const hasActiveBatch = useMemo(
    () => batches.some(b => ["ENVIADO", "EM_PROCESSAMENTO", "PRONTO"].includes(b.status)),
    [batches],
  );

  useEffect(() => {
    if (!open || !hasActiveBatch || tab !== "batches") return;
    const timer = setInterval(() => {
      loadBatches();
    }, 10000); // 10s
    return () => clearInterval(timer);
  }, [open, hasActiveBatch, tab, loadBatches]);

  const handleRefreshBatch = async (batchId: number) => {
    setRefreshingBatch(batchId);
    try {
      const updated = await refreshClassificadorBatch(batchId);
      setBatches(prev => prev.map(b => b.id === batchId ? updated : b));
    } catch (err) {
      toast({
        title: "Falha ao atualizar batch",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setRefreshingBatch(null);
    }
  };

  if (!lote) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-5xl max-h-[90vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle>
            Lote #{lote.id} · {lote.nome}
          </DialogTitle>
          <DialogDescription>
            {lote.cliente_nome || "(sem cliente)"} ·
            Status: <Badge>{lote.status}</Badge> ·
            {lote.total_processos_classificados}/{lote.total_processos} classificados
            {lote.total_processos_com_erro > 0 && ` · ${lote.total_processos_com_erro} com erro`}
          </DialogDescription>
        </DialogHeader>

        <Tabs value={tab} onValueChange={setTab} className="flex-1 overflow-hidden flex flex-col">
          <TabsList>
            <TabsTrigger value="visao" className="gap-2">
              <LayoutDashboard className="h-4 w-4" />
              Visão geral
            </TabsTrigger>
            <TabsTrigger value="processos" className="gap-2">
              <FileText className="h-4 w-4" />
              Processos ({procTotal || lote.total_processos})
            </TabsTrigger>
            <TabsTrigger value="batches" className="gap-2">
              <Sparkles className="h-4 w-4" />
              Batches IA ({batches.length})
            </TabsTrigger>
            <TabsTrigger value="relatorios" className="gap-2">
              <FileSpreadsheet className="h-4 w-4" />
              Relatorios ({relatorios.length})
            </TabsTrigger>
          </TabsList>

          {/* ─── Visão geral (dashboard) ─── */}
          <TabsContent value="visao" className="flex-1 overflow-auto mt-3">
            <LoteVisaoTab loteId={lote?.id ?? null} active={tab === "visao"} />
          </TabsContent>

          {/* ─── Processos ─── */}
          <TabsContent value="processos" className="flex-1 overflow-auto mt-3">
            {/* Barra de busca + filtros */}
            <div className="flex flex-wrap items-center gap-2 mb-3">
              <div className="relative flex-1 min-w-[200px]">
                <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
                <Input
                  value={cnjQuery}
                  onChange={e => setCnjQuery(e.target.value)}
                  placeholder="Buscar por CNJ..."
                  className="h-8 pl-7 pr-7 text-xs"
                />
                {cnjQuery && (
                  <button
                    onClick={() => setCnjQuery("")}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>
              <select
                value={statusFilter}
                onChange={e => setStatusFilter(e.target.value)}
                className="h-8 rounded border bg-background px-2 text-xs"
              >
                <option value="">Status (todos)</option>
                <option value="PENDENTE">Pendente</option>
                <option value="CAPTURANDO_L1">Capturando</option>
                <option value="PRONTO_PARA_CLASSIFICAR">Pronto</option>
                <option value="CLASSIFICADO">Classificado</option>
                <option value="ERRO_CAPTURA">Erro captura</option>
                <option value="ERRO_CLASSIFICACAO">Erro IA</option>
              </select>
              <select
                value={sourceFilter}
                onChange={e => setSourceFilter(e.target.value)}
                className="h-8 rounded border bg-background px-2 text-xs"
              >
                <option value="">Source (todos)</option>
                <option value="PDF_UPLOAD">PDF Upload</option>
                <option value="PDF_ROBOT_API">PDF Robot</option>
                <option value="UPLOAD_XLSX">XLSX</option>
                <option value="PRAZOS_INICIAIS">Prazos Iniciais</option>
                <option value="API_JSON">API JSON</option>
              </select>
              <select
                value={poloFilter}
                onChange={e => setPoloFilter(e.target.value)}
                className="h-8 rounded border bg-background px-2 text-xs"
              >
                <option value="">Polo (todos)</option>
                <option value="autor">Autor</option>
                <option value="reu">Réu</option>
                <option value="ambos">Ambos</option>
              </select>
              <select
                value={categoriaFilter}
                onChange={e => setCategoriaFilter(e.target.value)}
                className="h-8 rounded border bg-background px-2 text-xs max-w-[220px]"
              >
                <option value="">Categoria (todas)</option>
                {(filterOptions?.categorias || []).map(c => (
                  <option key={c.id} value={c.id}>{c.nome}</option>
                ))}
              </select>
              <select
                value={patrocinioFilter}
                onChange={e => setPatrocinioFilter(e.target.value)}
                className="h-8 rounded border bg-background px-2 text-xs"
              >
                <option value="">Patrocínio (todos)</option>
                {(filterOptions?.patrocinios || []).map(p => (
                  <option key={p} value={p}>{p}</option>
                ))}
              </select>
              {(cnjQueryDebounced || statusFilter || sourceFilter || poloFilter || categoriaFilter || patrocinioFilter) && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setCnjQuery("");
                    setStatusFilter("");
                    setSourceFilter("");
                    setPoloFilter("");
                    setCategoriaFilter("");
                    setPatrocinioFilter("");
                  }}
                >
                  Limpar
                </Button>
              )}
            </div>

            {loadingProc && processos.length === 0 ? (
              <div className="py-12 text-center text-sm text-muted-foreground">
                <Loader2 className="inline h-4 w-4 animate-spin mr-2" />
                Carregando...
              </div>
            ) : processos.length === 0 ? (
              <div className="py-12 text-center text-sm text-muted-foreground">
                Nenhum processo neste lote ainda. Use "Subir PDFs" pra comecar.
              </div>
            ) : (
              <>
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b text-left text-muted-foreground">
                        <th className="py-1.5 pr-2">#</th>
                        <th className="py-1.5 pr-2">CNJ</th>
                        <th className="py-1.5 pr-2">Source</th>
                        <th className="py-1.5 pr-2">Extractor</th>
                        <th className="py-1.5 pr-2">Conf</th>
                        <th className="py-1.5 pr-2">Status</th>
                        <th className="py-1.5 pr-2">Polo</th>
                        <th className="py-1.5 pr-2 text-right">PCOND</th>
                        <th className="py-1.5 pr-2 text-right">P.exito</th>
                      </tr>
                    </thead>
                    <tbody>
                      {processos.map(p => {
                        const badge = PROC_STATUS_BADGE[p.status] || {
                          label: p.status, variant: "outline" as const,
                        };
                        return (
                          <tr
                            key={p.id}
                            className="border-b hover:bg-muted/40 cursor-pointer"
                            onClick={() => setDrawerProcessoId(p.id)}
                            title="Click pra ver detalhe completo"
                          >
                            <td className="py-1.5 pr-2 font-mono">#{p.id}</td>
                            <td className="py-1.5 pr-2 font-mono">{p.cnj_number || "—"}</td>
                            <td className="py-1.5 pr-2 text-muted-foreground">{p.source}</td>
                            <td className="py-1.5 pr-2 text-muted-foreground">{p.extractor_used || "—"}</td>
                            <td className="py-1.5 pr-2 text-muted-foreground">
                              {p.extraction_confidence || "—"}
                            </td>
                            <td className="py-1.5 pr-2">
                              <Badge variant={badge.variant}>{badge.label}</Badge>
                            </td>
                            <td className="py-1.5 pr-2 text-muted-foreground">{p.polo || "—"}</td>
                            <td className="py-1.5 pr-2 text-right tabular-nums">
                              {fmtBRL(p.pcond_sugerido)}
                            </td>
                            <td className="py-1.5 pr-2 text-right tabular-nums">
                              {p.prob_exito != null
                                ? `${(Number(p.prob_exito) * 100).toFixed(0)}%`
                                : "—"}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>

                <div className="mt-3 flex items-center justify-between text-xs text-muted-foreground">
                  <div>
                    Pagina {procPage} de {procTotalPages} · Mostrando {processos.length} de {procTotal}
                  </div>
                  <div className="flex items-center gap-2">
                    <Button variant="outline" size="sm" disabled={procPage <= 1}
                      onClick={() => setProcPage(p => Math.max(1, p - 1))}>
                      Anterior
                    </Button>
                    <Button variant="outline" size="sm" disabled={procPage >= procTotalPages}
                      onClick={() => setProcPage(p => Math.min(procTotalPages, p + 1))}>
                      Proxima
                    </Button>
                    <Button variant="ghost" size="sm" onClick={loadProcessos}>
                      <RefreshCw className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                </div>
              </>
            )}
          </TabsContent>

          {/* ─── Batches ─── */}
          <TabsContent value="batches" className="flex-1 overflow-auto mt-3">
            {loadingBatch && batches.length === 0 ? (
              <div className="py-12 text-center text-sm text-muted-foreground">
                <Loader2 className="inline h-4 w-4 animate-spin mr-2" />
                Carregando...
              </div>
            ) : batches.length === 0 ? (
              <div className="py-12 text-center text-sm text-muted-foreground">
                Nenhum batch enviado pra IA ainda. Use "Classificar" no historico.
              </div>
            ) : (
              <div className="space-y-3">
                {hasActiveBatch && (
                  <div className="text-xs text-muted-foreground rounded-md border bg-muted/30 p-2">
                    <Loader2 className="inline h-3 w-3 animate-spin mr-1" />
                    Batch em curso — auto-refresh a cada 10s. Worker do servidor
                    polla Anthropic a cada 30s automaticamente.
                  </div>
                )}
                {batches.map(b => {
                  const badge = BATCH_STATUS_BADGE[b.status] || {
                    label: b.status, variant: "outline" as const,
                  };
                  return (
                    <div key={b.id} className="rounded-md border p-3 text-xs">
                      <div className="flex items-center justify-between mb-2">
                        <div className="flex items-center gap-2">
                          <span className="font-mono">#{b.id}</span>
                          <Badge variant={badge.variant}>{badge.label}</Badge>
                          {b.anthropic_status && (
                            <span className="text-muted-foreground">
                              Anthropic: {b.anthropic_status}
                            </span>
                          )}
                        </div>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleRefreshBatch(b.id)}
                          disabled={refreshingBatch === b.id}
                        >
                          {refreshingBatch === b.id ? (
                            <Loader2 className="h-3.5 w-3.5 animate-spin" />
                          ) : (
                            <RefreshCw className="h-3.5 w-3.5" />
                          )}
                        </Button>
                      </div>

                      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                        <div>
                          <div className="text-muted-foreground">Total</div>
                          <div className="tabular-nums">{b.total_records}</div>
                        </div>
                        <div>
                          <div className="text-muted-foreground">Sucesso</div>
                          <div className="tabular-nums text-green-700">{b.succeeded_count}</div>
                        </div>
                        <div>
                          <div className="text-muted-foreground">Erro</div>
                          <div className="tabular-nums text-red-700">{b.errored_count}</div>
                        </div>
                        <div>
                          <div className="text-muted-foreground">Expirado/Cancelado</div>
                          <div className="tabular-nums">{b.expired_count + b.canceled_count}</div>
                        </div>
                      </div>

                      <div className="mt-2 grid grid-cols-1 sm:grid-cols-3 gap-2 text-muted-foreground">
                        <div>Modelo: {b.model_used || "—"}</div>
                        <div>Submetido: {fmtDateTime(b.submitted_at)}</div>
                        <div>Aplicado: {fmtDateTime(b.applied_at)}</div>
                      </div>

                      {b.error_message && (
                        <div className="mt-2 rounded border border-red-200 bg-red-50 p-2 text-red-900">
                          {b.error_message}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </TabsContent>

          {/* ─── Relatorios ─── */}
          <TabsContent value="relatorios" className="flex-1 overflow-auto mt-3">
            <div className="flex items-center gap-2 mb-3">
              <Button
                onClick={() => handleGenerate("XLSX")}
                disabled={generatingRel === "XLSX"}
              >
                {generatingRel === "XLSX" ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <FileSpreadsheet className="mr-2 h-4 w-4" />
                )}
                Gerar XLSX
              </Button>
              <Button
                variant="outline"
                onClick={() => handleGenerate("PDF")}
                disabled={generatingRel === "PDF"}
                title="Gera PDF executivo (5 paginas) — capa + graficos + analise"
              >
                {generatingRel === "PDF" ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <FileText className="mr-2 h-4 w-4" />
                )}
                Gerar PDF
              </Button>
              <Button variant="ghost" size="sm" onClick={loadRelatorios}>
                <RefreshCw className="h-4 w-4" />
              </Button>
            </div>

            {loadingRel && relatorios.length === 0 ? (
              <div className="py-12 text-center text-sm text-muted-foreground">
                <Loader2 className="inline h-4 w-4 animate-spin mr-2" />
                Carregando...
              </div>
            ) : relatorios.length === 0 ? (
              <div className="py-12 text-center text-sm text-muted-foreground">
                Nenhum relatorio gerado ainda. Click "Gerar XLSX" pra criar o primeiro.
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b text-left text-muted-foreground">
                      <th className="py-1.5 pr-2">#</th>
                      <th className="py-1.5 pr-2">Formato</th>
                      <th className="py-1.5 pr-2">Status</th>
                      <th className="py-1.5 pr-2 text-right">Tamanho</th>
                      <th className="py-1.5 pr-2">Gerado em</th>
                      <th className="py-1.5 pr-2 text-right">Acoes</th>
                    </tr>
                  </thead>
                  <tbody>
                    {relatorios.map(r => {
                      const ready = r.status === "PRONTO";
                      const failed = r.status === "FALHOU";
                      return (
                        <tr key={r.id} className="border-b hover:bg-muted/30">
                          <td className="py-1.5 pr-2 font-mono">#{r.id}</td>
                          <td className="py-1.5 pr-2">
                            <Badge variant="outline">{r.formato}</Badge>
                          </td>
                          <td className="py-1.5 pr-2">
                            <Badge variant={ready ? "default" : failed ? "destructive" : "secondary"}>
                              {r.status}
                            </Badge>
                          </td>
                          <td className="py-1.5 pr-2 text-right tabular-nums text-muted-foreground">
                            {r.file_bytes ? `${(r.file_bytes / 1024).toFixed(1)} KB` : "—"}
                          </td>
                          <td className="py-1.5 pr-2 text-muted-foreground">
                            {fmtDateTime(r.finished_at || r.requested_at)}
                          </td>
                          <td className="py-1.5 pr-2 text-right">
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => handleDownload(r)}
                              disabled={!ready || downloadingRel === r.id}
                              title={
                                ready
                                  ? "Baixar relatorio"
                                  : `Indisponivel — status ${r.status}`
                              }
                            >
                              {downloadingRel === r.id ? (
                                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                              ) : (
                                <Download className="h-3.5 w-3.5" />
                              )}
                            </Button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}

            <p className="mt-3 text-[11px] text-muted-foreground">
              XLSX e' gerado de forma sincrona (geralmente {"<"} 5s). Inclui 12
              abas com KPIs, sumarios por categoria/patrocinio/produto/UF, top
              20 e detalhamento completo.
            </p>
          </TabsContent>
        </Tabs>
      </DialogContent>

      {/* Drawer de detalhe de processo (fora do DialogContent pra evitar
          conflito de overlay) */}
      <ProcessoDetailDrawer
        loteId={lote?.id ?? null}
        processoId={drawerProcessoId}
        open={drawerProcessoId !== null}
        onOpenChange={(v) => !v && setDrawerProcessoId(null)}
      />
    </Dialog>
  );
}
