import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  Ban,
  CheckCircle2,
  Clock,
  Eye,
  FileText,
  FileWarning,
  History,
  Loader2,
  Paperclip,
  Plus,
  RefreshCw,
  RotateCcw,
  Send,
  Upload,
  Workflow,
  XCircle,
} from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useToast } from "@/hooks/use-toast";
import {
  backfillAjusFromIntakes,
  cancelAjusAndamento,
  createAjusCodAndamento,
  deleteAjusCodAndamento,
  dispatchAjusAndamento,
  dispatchAjusAndamentosPending,
  dispatchSelectedAjusAndamentos,
  fetchAjusAndamentoPdfBlobUrl,
  fetchAjusAndamentos,
  fetchAjusCodAndamento,
  retryAjusAndamento,
  updateAjusCodAndamento,
  uploadAjusAndamentoPdf,
} from "@/services/api";
import type {
  AjusAndamentoQueueItem,
  AjusCodAndamento,
  AjusQueueStatus,
} from "@/types/api";
import { CodAndamentoFormDialog } from "@/components/ajus/CodAndamentoFormDialog";
import { ClassificacaoTab } from "@/components/ajus/ClassificacaoTab";
import { BulkUploadAndamentosDialog } from "@/components/ajus/BulkUploadAndamentosDialog";

const STATUS_OPTIONS: { value: string; label: string }[] = [
  { value: "__all__", label: "Todos os status" },
  { value: "pendente", label: "Pendentes" },
  { value: "enviando", label: "Enviando" },
  { value: "sucesso", label: "Sucessos" },
  { value: "erro", label: "Erros" },
  { value: "cancelado", label: "Cancelados" },
];

const STATUS_BADGE: Record<AjusQueueStatus, { label: string; className: string }> = {
  pendente: { label: "Pendente", className: "bg-amber-50 text-amber-800 border-amber-300" },
  enviando: { label: "Enviando", className: "bg-blue-50 text-blue-800 border-blue-300" },
  sucesso: { label: "Sucesso", className: "bg-emerald-50 text-emerald-800 border-emerald-300" },
  erro: { label: "Erro", className: "bg-rose-50 text-rose-800 border-rose-300" },
  cancelado: { label: "Cancelado", className: "bg-slate-50 text-slate-700 border-slate-300" },
};

function formatCnj(value: string | null | undefined): string {
  if (!value) return "-";
  const digits = value.replace(/\D/g, "");
  if (digits.length === 20) {
    return `${digits.slice(0, 7)}-${digits.slice(7, 9)}.${digits.slice(9, 13)}.${digits.slice(13, 14)}.${digits.slice(14, 16)}.${digits.slice(16, 20)}`;
  }
  return value;
}

function formatDate(value: string | null | undefined): string {
  if (!value) return "-";
  // espera ISO ou YYYY-MM-DD
  const d = value.length === 10 ? new Date(`${value}T12:00:00`) : new Date(value);
  if (isNaN(d.getTime())) return value;
  return d.toLocaleDateString("pt-BR");
}

export default function AjusPage() {
  const { toast } = useToast();

  // ─── Aba Andamentos ────────────────────────────────────────────────
  const [andamentos, setAndamentos] = useState<AjusAndamentoQueueItem[]>([]);
  const [andamentosTotal, setAndamentosTotal] = useState(0);
  const [andamentosLoading, setAndamentosLoading] = useState(false);
  const [statusFilter, setStatusFilter] = useState<string>("__all__");
  const [cnjFilter, setCnjFilter] = useState<string>("");
  const [actionItemId, setActionItemId] = useState<number | null>(null);
  const [isDispatching, setIsDispatching] = useState(false);
  const [isBackfilling, setIsBackfilling] = useState(false);
  const [isDispatchingSelected, setIsDispatchingSelected] = useState(false);
  // Paginacao
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(50);
  // Multi-selecao (apenas pendente/erro sao selecionaveis)
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  // Upload de PDF — track qual item esta em upload pra mostrar spinner
  const [uploadingItemId, setUploadingItemId] = useState<number | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const uploadTargetItemRef = useRef<number | null>(null);

  // ─── Aba Códigos ───────────────────────────────────────────────────
  const [codigos, setCodigos] = useState<AjusCodAndamento[]>([]);
  const [codigosLoading, setCodigosLoading] = useState(false);
  const [codDialogOpen, setCodDialogOpen] = useState(false);
  const [editingCod, setEditingCod] = useState<AjusCodAndamento | null>(null);

  // ─── Bulk upload ───────────────────────────────────────────────────
  const [bulkDialogOpen, setBulkDialogOpen] = useState(false);

  // ─── Loaders ───────────────────────────────────────────────────────
  const loadAndamentos = useCallback(async () => {
    setAndamentosLoading(true);
    try {
      const filters: Parameters<typeof fetchAjusAndamentos>[0] = {
        limit: pageSize,
        offset: page * pageSize,
      };
      if (statusFilter !== "__all__") filters.status = statusFilter;
      if (cnjFilter.trim()) filters.cnj_number = cnjFilter.trim();
      const resp = await fetchAjusAndamentos(filters);
      setAndamentos(resp.items);
      setAndamentosTotal(resp.total);
    } catch (e: unknown) {
      toast({
        title: "Erro ao carregar andamentos",
        description: e instanceof Error ? e.message : String(e),
        variant: "destructive",
      });
    } finally {
      setAndamentosLoading(false);
    }
  }, [statusFilter, cnjFilter, page, pageSize, toast]);

  // Reset de pagina quando filtros mudam, pra nao ficar olhando offset
  // que ja' nao existe (ex.: filtra por status e o total cai de 300 pra 5).
  useEffect(() => { setPage(0); }, [statusFilter, cnjFilter, pageSize]);

  // Limpa selecao ao trocar de pagina/filtros — selecionar tem escopo
  // local da pagina atual, evita confusao de "selecionei 18 mas so' 5
  // estao na tela".
  useEffect(() => { setSelectedIds(new Set()); }, [page, pageSize, statusFilter, cnjFilter]);

  const totalPages = Math.max(1, Math.ceil(andamentosTotal / pageSize));
  const safePage = Math.min(page, totalPages - 1);

  // Itens elegiveis pra dispatch (multi-select)
  const selectableIds = useMemo(
    () => andamentos
      .filter((i) => i.status === "pendente" || i.status === "erro")
      .map((i) => i.id),
    [andamentos],
  );
  const allOnPageSelected = (
    selectableIds.length > 0
    && selectableIds.every((id) => selectedIds.has(id))
  );
  const someOnPageSelected = (
    !allOnPageSelected
    && selectableIds.some((id) => selectedIds.has(id))
  );

  const loadCodigos = useCallback(async () => {
    setCodigosLoading(true);
    try {
      const data = await fetchAjusCodAndamento(false);
      setCodigos(data);
    } catch (e: unknown) {
      toast({
        title: "Erro ao carregar códigos",
        description: e instanceof Error ? e.message : String(e),
        variant: "destructive",
      });
    } finally {
      setCodigosLoading(false);
    }
  }, [toast]);

  useEffect(() => { loadAndamentos(); }, [loadAndamentos]);
  useEffect(() => { loadCodigos(); }, [loadCodigos]);

  // ─── Handlers — Andamentos ─────────────────────────────────────────
  const handleDispatchPending = async () => {
    setIsDispatching(true);
    try {
      const result = await dispatchAjusAndamentosPending(20);
      const lines = [
        `${result.success_count} enviado(s) com sucesso`,
        result.error_count ? `${result.error_count} erro(s)` : null,
      ].filter(Boolean);
      toast({
        title: "Disparo concluído",
        description: `${result.candidates} candidato(s) processado(s). ${lines.join(" · ")}`,
        variant: result.error_count > 0 ? "destructive" : "default",
      });
      await loadAndamentos();
    } catch (e: unknown) {
      toast({
        title: "Falha ao disparar",
        description: e instanceof Error ? e.message : String(e),
        variant: "destructive",
      });
    } finally {
      setIsDispatching(false);
    }
  };

  /**
   * Backfill: enfileira todos os intakes ja' classificados que ainda
   * nao tem item na fila do AJUS. Idempotente -- rodar 2x nao duplica.
   * Faz dry_run primeiro pra mostrar quantos vao ser enfileirados (e
   * quantos sem PDF), aguarda confirmacao, depois executa.
   */
  const handleBackfill = async () => {
    setIsBackfilling(true);
    try {
      // 1) Pre-visualiza
      const preview = await backfillAjusFromIntakes({ dry_run: true });
      if (preview.error) {
        toast({
          title: "Backfill bloqueado",
          description: preview.error,
          variant: "destructive",
        });
        return;
      }
      if (preview.enqueued === 0) {
        toast({
          title: "Nada a fazer",
          description: (
            preview.skipped_already > 0
              ? `Todos os ${preview.candidates} candidato(s) ja' estao na fila.`
              : "Nenhum intake elegivel encontrado."
          ),
        });
        return;
      }
      const semPdf = preview.enqueued_without_pdf.length;
      const linhas = [
        `Vai enfileirar ${preview.enqueued} processo(s) na fila do AJUS.`,
      ];
      if (preview.skipped_already > 0) {
        linhas.push(
          `(${preview.skipped_already} ja' estao na fila e serao pulados.)`,
        );
      }
      if (semPdf > 0) {
        linhas.push(
          `ATENCAO: ${semPdf} entrarao SEM PDF da habilitacao -- ` +
            `marcados pra anexo manual antes do envio.`,
        );
      }
      linhas.push("Confirmar?");
      // eslint-disable-next-line no-alert
      const ok = window.confirm(linhas.join("\n\n"));
      if (!ok) return;

      // 2) Executa
      const result = await backfillAjusFromIntakes({ dry_run: false });
      if (result.error) {
        toast({
          title: "Falha no backfill",
          description: result.error,
          variant: "destructive",
        });
        return;
      }
      const semPdfFinal = result.enqueued_without_pdf.length;
      const partes = [`${result.enqueued} item(ns) enfileirado(s).`];
      if (result.skipped_already > 0) {
        partes.push(`${result.skipped_already} ja' estavam na fila.`);
      }
      if (result.skipped_other > 0) {
        partes.push(`${result.skipped_other} com falha (ver logs).`);
      }
      if (semPdfFinal > 0) {
        partes.push(
          `${semPdfFinal} sem PDF -- anexar via "Upload em lote" antes de enviar.`,
        );
      }
      toast({
        title: "Backfill concluido",
        description: partes.join(" "),
        variant: semPdfFinal > 0 || result.skipped_other > 0
          ? "destructive"
          : "default",
      });
      if (semPdfFinal > 0) {
        console.warn("AJUS backfill sem PDF:", result.enqueued_without_pdf);
      }
      await loadAndamentos();
    } catch (e: unknown) {
      toast({
        title: "Falha no backfill",
        description: e instanceof Error ? e.message : String(e),
        variant: "destructive",
      });
    } finally {
      setIsBackfilling(false);
    }
  };

  // ─── Handlers — multi-select dispatch ─────────────────────────────
  const toggleSelect = (id: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };
  const toggleSelectAllOnPage = () => {
    setSelectedIds((prev) => {
      if (allOnPageSelected) {
        const next = new Set(prev);
        for (const id of selectableIds) next.delete(id);
        return next;
      }
      const next = new Set(prev);
      for (const id of selectableIds) next.add(id);
      return next;
    });
  };

  const handleDispatchSelected = async () => {
    if (selectedIds.size === 0) return;
    if (selectedIds.size > 20) {
      toast({
        title: "Limite excedido",
        description: "Maximo de 20 itens por disparo (limite AJUS). Reduza a selecao.",
        variant: "destructive",
      });
      return;
    }
    setIsDispatchingSelected(true);
    try {
      const result = await dispatchSelectedAjusAndamentos(
        Array.from(selectedIds),
      );
      const lines = [
        `${result.success_count} enviado(s) com sucesso`,
        result.error_count ? `${result.error_count} erro(s)` : null,
      ].filter(Boolean);
      toast({
        title: "Disparo selecionado concluido",
        description: `${result.candidates} item(ns) processado(s). ${lines.join(" · ")}`,
        variant: result.error_count > 0 ? "destructive" : "default",
      });
      setSelectedIds(new Set());
      await loadAndamentos();
    } catch (e: unknown) {
      toast({
        title: "Falha ao disparar selecionados",
        description: e instanceof Error ? e.message : String(e),
        variant: "destructive",
      });
    } finally {
      setIsDispatchingSelected(false);
    }
  };

  // ─── Handlers — PDF (visualizar / anexar) ─────────────────────────
  const handleViewPdf = async (id: number) => {
    try {
      const url = await fetchAjusAndamentoPdfBlobUrl(id);
      const w = window.open(url, "_blank", "noopener,noreferrer");
      // Revoga apos um tempo pra liberar memoria; se a aba nao abrir
      // (popup bloqueado) ja' setamos como fallback href via toast.
      if (!w) {
        toast({
          title: "Pop-up bloqueado",
          description: "Permita pop-ups pra abrir o PDF.",
          variant: "destructive",
        });
      }
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (e: unknown) {
      toast({
        title: "Erro ao abrir PDF",
        description: e instanceof Error ? e.message : String(e),
        variant: "destructive",
      });
    }
  };

  const triggerUpload = (id: number) => {
    uploadTargetItemRef.current = id;
    fileInputRef.current?.click();
  };

  const handleFileSelected = async (
    ev: React.ChangeEvent<HTMLInputElement>,
  ) => {
    const file = ev.target.files?.[0];
    // Reset do input agora pra permitir re-upload do mesmo arquivo.
    ev.target.value = "";
    const targetId = uploadTargetItemRef.current;
    uploadTargetItemRef.current = null;
    if (!file || !targetId) return;
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      toast({
        title: "Arquivo invalido",
        description: "Selecione um arquivo .pdf.",
        variant: "destructive",
      });
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      toast({
        title: "Arquivo grande",
        description: "PDF excede 10MB (limite AJUS).",
        variant: "destructive",
      });
      return;
    }
    setUploadingItemId(targetId);
    try {
      await uploadAjusAndamentoPdf(targetId, file);
      toast({
        title: `PDF anexado ao item #${targetId}`,
        description: "Item pronto pra disparo.",
      });
      await loadAndamentos();
    } catch (e: unknown) {
      toast({
        title: "Falha ao anexar PDF",
        description: e instanceof Error ? e.message : String(e),
        variant: "destructive",
      });
    } finally {
      setUploadingItemId(null);
    }
  };

  const handleCancel = async (id: number) => {
    setActionItemId(id);
    try {
      await cancelAjusAndamento(id);
      toast({ title: "Andamento cancelado" });
      await loadAndamentos();
    } catch (e: unknown) {
      toast({
        title: "Falha ao cancelar",
        description: e instanceof Error ? e.message : String(e),
        variant: "destructive",
      });
    } finally {
      setActionItemId(null);
    }
  };

  const handleRetry = async (id: number) => {
    setActionItemId(id);
    try {
      await retryAjusAndamento(id);
      toast({ title: "Andamento reenfileirado" });
      await loadAndamentos();
    } catch (e: unknown) {
      toast({
        title: "Falha ao reenfileirar",
        description: e instanceof Error ? e.message : String(e),
        variant: "destructive",
      });
    } finally {
      setActionItemId(null);
    }
  };

  /**
   * Dispatch pontual: envia 1 item agora numa request isolada (sem
   * agrupar com a fila). Util pra debug ("testar este 1 caso") e pra
   * reenviar pontual depois de operador corrigir dado num item em erro.
   * Backend aceita item em status pendente ou erro.
   */
  const handleDispatchOne = async (id: number) => {
    setActionItemId(id);
    try {
      const result = await dispatchAjusAndamento(id);
      if (result.success) {
        toast({
          title: `Item #${id} enviado com sucesso`,
          description: result.cod_informacao_judicial
            ? `AJUS retornou cod_informacao_judicial=${result.cod_informacao_judicial}.`
            : "AJUS confirmou inserção.",
        });
      } else {
        toast({
          title: `Item #${id}: AJUS rejeitou`,
          description: result.msg || "AJUS retornou inserido=false sem mensagem.",
          variant: "destructive",
        });
      }
      await loadAndamentos();
    } catch (e: unknown) {
      // 502 (config/AJUS API), 409 (status nao elegivel), 404 (id sumiu).
      toast({
        title: `Falha ao disparar item #${id}`,
        description: e instanceof Error ? e.message : String(e),
        variant: "destructive",
      });
    } finally {
      setActionItemId(null);
    }
  };

  // ─── Handlers — Códigos ────────────────────────────────────────────
  const handleCreateCod = async (payload: Parameters<typeof createAjusCodAndamento>[0]) => {
    await createAjusCodAndamento(payload);
    toast({ title: "Código criado" });
    setCodDialogOpen(false);
    setEditingCod(null);
    await loadCodigos();
  };

  const handleUpdateCod = async (id: number, payload: Parameters<typeof updateAjusCodAndamento>[1]) => {
    await updateAjusCodAndamento(id, payload);
    toast({ title: "Código atualizado" });
    setCodDialogOpen(false);
    setEditingCod(null);
    await loadCodigos();
  };

  const handleDeleteCod = async (cod: AjusCodAndamento) => {
    if (!confirm(`Deletar código "${cod.label}"?\n\nSó é permitido se não estiver em uso na fila.`)) return;
    try {
      await deleteAjusCodAndamento(cod.id);
      toast({ title: "Código deletado" });
      await loadCodigos();
    } catch (e: unknown) {
      toast({
        title: "Erro ao deletar",
        description: e instanceof Error ? e.message : String(e),
        variant: "destructive",
      });
    }
  };

  // ─── Resumo de status ──────────────────────────────────────────────
  const statusCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    andamentos.forEach((a) => { counts[a.status] = (counts[a.status] || 0) + 1; });
    return counts;
  }, [andamentos]);

  // ─── Render ────────────────────────────────────────────────────────
  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
          <Workflow className="h-6 w-6" />
          AJUS — Andamentos
        </h1>
        <p className="text-muted-foreground">
          Cada intake recebido em Prazos Iniciais é enfileirado automaticamente
          aqui, com base no código de andamento default. Acumule e clique em
          "Enviar próximos 20" pra disparar o lote pra AJUS.
        </p>
      </div>

      <Tabs defaultValue="andamentos" className="space-y-4">
        <TabsList>
          <TabsTrigger value="andamentos">Andamentos</TabsTrigger>
          <TabsTrigger value="classificacao">Classificação</TabsTrigger>
          <TabsTrigger value="codigos">Códigos de Andamento</TabsTrigger>
        </TabsList>

        {/* ═══ ABA: ANDAMENTOS ═══ */}
        <TabsContent value="andamentos" className="space-y-4">
          {/* Aviso se não há código default */}
          {codigos.length > 0 && !codigos.some((c) => c.is_default && c.is_active) && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertTitle>Sem código default ativo</AlertTitle>
              <AlertDescription>
                Nenhum código de andamento está marcado como "Default". Sem isso,
                novos intakes não serão enfileirados automaticamente. Vá na aba
                "Códigos de Andamento" e marque um.
              </AlertDescription>
            </Alert>
          )}
          {codigos.length > 0 && !codigos.some((c) => c.is_devolucao && c.is_active) && (
            <Alert>
              <AlertCircle className="h-4 w-4" />
              <AlertTitle>Sem código de devolução ativo</AlertTitle>
              <AlertDescription>
                Nenhum código de andamento está marcado como "Devolução
                automática". Os intakes recebidos via{" "}
                <code>/intake/devolucao</code> são criados, mas não vão pra
                fila AJUS automaticamente até você marcar um código.
              </AlertDescription>
            </Alert>
          )}
          {codigos.length === 0 && !codigosLoading && (
            <Alert>
              <AlertCircle className="h-4 w-4" />
              <AlertTitle>Nenhum código cadastrado</AlertTitle>
              <AlertDescription>
                Você precisa cadastrar pelo menos um código de andamento (vindo
                da equipe AJUS) na aba "Códigos de Andamento" antes do
                enfileiramento começar a funcionar.
              </AlertDescription>
            </Alert>
          )}

          <Card>
            <CardHeader className="pb-3">
              <div className="flex flex-wrap items-end justify-between gap-3">
                <div>
                  <CardTitle className="text-base">Fila</CardTitle>
                  <CardDescription>
                    {andamentosTotal} item(ns)
                    {Object.entries(statusCounts).length > 0 && (
                      <span className="ml-2 text-xs">
                        — {Object.entries(statusCounts)
                          .map(([s, n]) => `${STATUS_BADGE[s as AjusQueueStatus]?.label || s}: ${n}`)
                          .join(" · ")}
                      </span>
                    )}
                  </CardDescription>
                </div>
                <div className="flex flex-wrap items-end gap-2">
                  <div className="space-y-1">
                    <label className="text-[10px] uppercase tracking-wide text-muted-foreground">
                      Status
                    </label>
                    <Select value={statusFilter} onValueChange={setStatusFilter}>
                      <SelectTrigger className="h-8 w-[180px] text-xs">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {STATUS_OPTIONS.map((o) => (
                          <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-1">
                    <label className="text-[10px] uppercase tracking-wide text-muted-foreground">
                      Buscar processo
                    </label>
                    <Input
                      value={cnjFilter}
                      onChange={(e) => setCnjFilter(e.target.value)}
                      onBlur={loadAndamentos}
                      onKeyDown={(e) => { if (e.key === "Enter") loadAndamentos(); }}
                      placeholder="CNJ (só dígitos)"
                      className="h-8 w-[200px] text-xs"
                    />
                  </div>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={loadAndamentos}
                    disabled={andamentosLoading}
                  >
                    <RefreshCw className={`mr-2 h-3.5 w-3.5 ${andamentosLoading ? "animate-spin" : ""}`} />
                    Atualizar
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => setBulkDialogOpen(true)}
                    disabled={codigos.filter((c) => c.is_active).length === 0}
                    title="Upload em lote — N PDFs (CNJ no nome) ou lista de CNJs"
                  >
                    <Upload className="mr-2 h-3.5 w-3.5" />
                    Upload em lote
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={handleBackfill}
                    disabled={
                      isBackfilling ||
                      codigos.filter((c) => c.is_active && c.is_default).length === 0
                    }
                    title={
                      "Enfileira processos antigos ja' classificados que ainda " +
                      "nao tem item na fila. Idempotente. Mostra preview antes."
                    }
                  >
                    {isBackfilling ? (
                      <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <History className="mr-2 h-3.5 w-3.5" />
                    )}
                    Backfill antigos
                  </Button>
                  <Button
                    size="sm"
                    onClick={handleDispatchPending}
                    disabled={isDispatching || (statusCounts.pendente || 0) === 0}
                  >
                    {isDispatching ? (
                      <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Send className="mr-2 h-3.5 w-3.5" />
                    )}
                    Enviar próximos 20
                  </Button>
                </div>
              </div>
            </CardHeader>
            <CardContent>
              {/* Hidden file input — usado pelos botoes "Anexar PDF" das linhas. */}
              <input
                ref={fileInputRef}
                type="file"
                accept="application/pdf,.pdf"
                className="hidden"
                onChange={handleFileSelected}
              />
              {/* Toolbar de selecao multipla — aparece quando ha selecionados. */}
              {selectedIds.size > 0 && (
                <div className="mb-3 flex items-center justify-between rounded-md border bg-muted/40 px-3 py-2 text-sm">
                  <div>
                    <strong>{selectedIds.size}</strong> item(ns) selecionado(s)
                    {selectedIds.size > 20 && (
                      <span className="ml-2 text-destructive">
                        (excede 20 — limite AJUS por request)
                      </span>
                    )}
                  </div>
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => setSelectedIds(new Set())}
                    >
                      Limpar
                    </Button>
                    <Button
                      size="sm"
                      onClick={handleDispatchSelected}
                      disabled={
                        isDispatchingSelected
                        || selectedIds.size === 0
                        || selectedIds.size > 20
                      }
                    >
                      {isDispatchingSelected ? (
                        <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Send className="mr-2 h-3.5 w-3.5" />
                      )}
                      Disparar selecionados ({selectedIds.size})
                    </Button>
                  </div>
                </div>
              )}
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-[36px]">
                      <input
                        type="checkbox"
                        aria-label="Selecionar todos da pagina"
                        checked={allOnPageSelected}
                        ref={(el) => {
                          if (el) el.indeterminate = someOnPageSelected;
                        }}
                        onChange={toggleSelectAllOnPage}
                        disabled={selectableIds.length === 0}
                      />
                    </TableHead>
                    <TableHead>CNJ</TableHead>
                    <TableHead>Código</TableHead>
                    <TableHead>Sit.</TableHead>
                    <TableHead>Evento</TableHead>
                    <TableHead>Agendam.</TableHead>
                    <TableHead>Fatal</TableHead>
                    <TableHead>PDF</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead className="text-right">Ações</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {andamentos.length === 0 && !andamentosLoading && (
                    <TableRow>
                      <TableCell colSpan={10} className="text-center text-sm text-muted-foreground py-8">
                        Nenhum andamento na fila com os filtros atuais.
                      </TableCell>
                    </TableRow>
                  )}
                  {andamentos.map((item) => {
                    const badge = STATUS_BADGE[item.status] || {
                      label: item.status,
                      className: "",
                    };
                    const selectable = item.status === "pendente" || item.status === "erro";
                    const isUploadingThis = uploadingItemId === item.id;
                    return (
                      <TableRow key={item.id}>
                        <TableCell>
                          <input
                            type="checkbox"
                            aria-label={`Selecionar item ${item.id}`}
                            checked={selectedIds.has(item.id)}
                            onChange={() => toggleSelect(item.id)}
                            disabled={!selectable}
                            title={
                              selectable
                                ? undefined
                                : `Apenas pendente/erro podem ser selecionados (status: ${item.status})`
                            }
                          />
                        </TableCell>
                        <TableCell className="font-mono text-xs">
                          {formatCnj(item.cnj_number)}
                        </TableCell>
                        <TableCell className="text-xs">
                          <div className="font-medium">{item.cod_andamento_label || "-"}</div>
                          <div className="text-muted-foreground">
                            {item.cod_andamento_codigo || ""}
                          </div>
                        </TableCell>
                        <TableCell className="text-xs">{item.situacao}</TableCell>
                        <TableCell className="text-xs">{formatDate(item.data_evento)}</TableCell>
                        <TableCell className="text-xs">{formatDate(item.data_agendamento)}</TableCell>
                        <TableCell className="text-xs">{formatDate(item.data_fatal)}</TableCell>
                        <TableCell>
                          {item.has_pdf ? (
                            <button
                              type="button"
                              onClick={() => handleViewPdf(item.id)}
                              className="inline-flex items-center gap-1 text-xs text-emerald-700 hover:text-emerald-900 hover:underline"
                              title="Abrir PDF da habilitacao"
                            >
                              <FileText className="h-3.5 w-3.5" />
                              <Eye className="h-3 w-3" />
                            </button>
                          ) : selectable ? (
                            <button
                              type="button"
                              onClick={() => triggerUpload(item.id)}
                              disabled={isUploadingThis}
                              className="inline-flex items-center gap-1 text-xs text-rose-700 hover:text-rose-900 hover:underline disabled:opacity-50"
                              title="Sem PDF — clique pra anexar"
                            >
                              {isUploadingThis ? (
                                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                              ) : (
                                <FileWarning className="h-3.5 w-3.5" />
                              )}
                              <Paperclip className="h-3 w-3" />
                            </button>
                          ) : (
                            <FileWarning
                              className="h-3.5 w-3.5 text-rose-500"
                              aria-label="Sem PDF"
                            />
                          )}
                        </TableCell>
                        <TableCell>
                          <Badge variant="outline" className={badge.className}>
                            {item.status === "sucesso" && <CheckCircle2 className="mr-1 h-3 w-3" />}
                            {item.status === "erro" && <XCircle className="mr-1 h-3 w-3" />}
                            {item.status === "pendente" && <Clock className="mr-1 h-3 w-3" />}
                            {badge.label}
                          </Badge>
                          {item.error_message && (
                            <div
                              className="mt-1 max-w-[260px] truncate text-xs text-destructive"
                              title={item.error_message}
                            >
                              {item.error_message}
                            </div>
                          )}
                          {item.cod_informacao_judicial && (
                            <div className="mt-1 text-xs text-muted-foreground">
                              ID AJUS: {item.cod_informacao_judicial}
                            </div>
                          )}
                        </TableCell>
                        <TableCell className="text-right">
                          <div className="flex justify-end gap-1">
                            {(item.status === "pendente" || item.status === "erro") && (
                              <Button
                                size="sm"
                                variant="default"
                                onClick={() => handleDispatchOne(item.id)}
                                disabled={actionItemId === item.id}
                                title="Dispara so' este item agora — debug 1 a 1, isolando do batch."
                              >
                                <Send className="mr-1 h-3 w-3" />
                                Disparar
                              </Button>
                            )}
                            {item.status === "erro" && (
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={() => handleRetry(item.id)}
                                disabled={actionItemId === item.id}
                              >
                                <RotateCcw className="mr-1 h-3 w-3" />
                                Retry
                              </Button>
                            )}
                            {(item.status === "pendente" || item.status === "erro") && (
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={() => handleCancel(item.id)}
                                disabled={actionItemId === item.id}
                              >
                                <Ban className="mr-1 h-3 w-3" />
                                Cancelar
                              </Button>
                            )}
                          </div>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
              {/* Controles de paginacao */}
              <div className="mt-3 flex items-center justify-between border-t pt-3 text-xs text-muted-foreground">
                <div>
                  {andamentosTotal === 0 ? (
                    "Sem itens."
                  ) : (
                    <>
                      Mostrando {safePage * pageSize + 1}–
                      {Math.min((safePage + 1) * pageSize, andamentosTotal)} de{" "}
                      {andamentosTotal} item(ns)
                    </>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  <label className="text-[10px] uppercase tracking-wide">
                    Por pagina
                  </label>
                  <Select
                    value={String(pageSize)}
                    onValueChange={(v) => setPageSize(Number(v))}
                  >
                    <SelectTrigger className="h-7 w-[70px] text-xs">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="25">25</SelectItem>
                      <SelectItem value="50">50</SelectItem>
                      <SelectItem value="100">100</SelectItem>
                      <SelectItem value="200">200</SelectItem>
                    </SelectContent>
                  </Select>
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-7 px-2"
                    onClick={() => setPage((p) => Math.max(0, p - 1))}
                    disabled={safePage === 0 || andamentosLoading}
                  >
                    Anterior
                  </Button>
                  <span>
                    Página {safePage + 1} de {totalPages}
                  </span>
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-7 px-2"
                    onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
                    disabled={safePage >= totalPages - 1 || andamentosLoading}
                  >
                    Próxima
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* ═══ ABA: CLASSIFICAÇÃO ═══ */}
        <TabsContent value="classificacao" className="space-y-4">
          <ClassificacaoTab />
        </TabsContent>

        {/* ═══ ABA: CÓDIGOS ═══ */}
        <TabsContent value="codigos" className="space-y-4">
          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <CardTitle className="text-base">Códigos de Andamento</CardTitle>
                  <CardDescription>
                    Cadastre os códigos fornecidos pela equipe AJUS. Apenas um pode
                    ser "Default" — esse é o usado automaticamente quando um intake
                    é recebido.
                  </CardDescription>
                </div>
                <Button
                  size="sm"
                  onClick={() => { setEditingCod(null); setCodDialogOpen(true); }}
                >
                  <Plus className="mr-1 h-3.5 w-3.5" />
                  Novo código
                </Button>
              </div>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Código</TableHead>
                    <TableHead>Rótulo</TableHead>
                    <TableHead>Sit.</TableHead>
                    <TableHead>Offsets (úteis)</TableHead>
                    <TableHead>Default</TableHead>
                    <TableHead>Devolução</TableHead>
                    <TableHead>Ativo</TableHead>
                    <TableHead className="text-right">Ações</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {codigos.length === 0 && !codigosLoading && (
                    <TableRow>
                      <TableCell colSpan={8} className="text-center text-sm text-muted-foreground py-8">
                        Nenhum código cadastrado. Clique em "Novo código" pra começar.
                      </TableCell>
                    </TableRow>
                  )}
                  {codigos.map((c) => (
                    <TableRow key={c.id}>
                      <TableCell className="font-mono text-xs">{c.codigo}</TableCell>
                      <TableCell>
                        <div className="text-sm font-medium">{c.label}</div>
                        {c.descricao && (
                          <div className="text-xs text-muted-foreground">{c.descricao}</div>
                        )}
                      </TableCell>
                      <TableCell className="text-xs">{c.situacao}</TableCell>
                      <TableCell className="text-xs">
                        agend: {c.dias_agendamento_offset_uteis} ·
                        fatal: {c.dias_fatal_offset_uteis}
                      </TableCell>
                      <TableCell>
                        {c.is_default ? (
                          <Badge className="bg-emerald-100 text-emerald-800">Default</Badge>
                        ) : (
                          <span className="text-xs text-muted-foreground">—</span>
                        )}
                      </TableCell>
                      <TableCell>
                        {c.is_devolucao ? (
                          <Badge className="bg-orange-100 text-orange-800">Devolução</Badge>
                        ) : (
                          <span className="text-xs text-muted-foreground">—</span>
                        )}
                      </TableCell>
                      <TableCell>
                        {c.is_active ? (
                          <Badge variant="outline" className="bg-emerald-50 text-emerald-700">Ativo</Badge>
                        ) : (
                          <Badge variant="outline" className="bg-slate-50 text-slate-600">Inativo</Badge>
                        )}
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex justify-end gap-1">
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => { setEditingCod(c); setCodDialogOpen(true); }}
                          >
                            Editar
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => handleDeleteCod(c)}
                          >
                            Deletar
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      <CodAndamentoFormDialog
        open={codDialogOpen}
        onOpenChange={(open) => {
          setCodDialogOpen(open);
          if (!open) setEditingCod(null);
        }}
        cod={editingCod}
        onCreate={handleCreateCod}
        onUpdate={handleUpdateCod}
      />

      <BulkUploadAndamentosDialog
        open={bulkDialogOpen}
        onOpenChange={setBulkDialogOpen}
        codigos={codigos}
        onSuccess={() => loadAndamentos()}
      />
    </div>
  );
}
