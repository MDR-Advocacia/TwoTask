/**
 * Aba "Classificação" da AjusPage.
 *
 * Funções:
 *  - Editar defaults (matter + risco padrão usados em intakes auto).
 *  - Listar a fila de classificação com filtros (status, origem, CNJ).
 *  - Editar item antes do dispatch (operador ajusta UF/comarca/etc.).
 *  - Cancelar / retry.
 *  - Upload XLSX com classificações em massa.
 *  - Download da planilha modelo.
 *
 * O dispatch real (Playwright runner) entra no Chunk 2 — aqui só
 * preparamos a fila.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  Ban,
  Bug,
  ChevronDown,
  Download,
  Loader2,
  Pause,
  Pencil,
  Play,
  RefreshCw,
  RotateCcw,
  Save,
  StopCircle,
  Upload,
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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useToast } from "@/hooks/use-toast";
import {
  ajusClassifTemplateXlsxUrl,
  cancelAjusClassifItem,
  cancelAjusClassifPendentes,
  dispatchAjusClassif,
  fetchAjusClassif,
  fetchAjusClassifDefaults,
  fetchAjusDebugScreenshotBlobUrl,
  listAjusDebugScreenshots,
  pauseAjusClassif,
  resumeAjusClassif,
  retryAjusClassifErrorsBulk,
  retryAjusClassifItem,
  updateAjusClassifDefaults,
  updateAjusClassifItem,
  uploadAjusClassifXlsx,
  type AjusDebugScreenshot,
} from "@/services/api";
import type {
  AjusClassifDefaults,
  AjusClassifQueueItem,
  AjusClassifQueueUpdatePayload,
  AjusClassifStatus,
} from "@/types/api";
import { SessionsCard } from "@/components/ajus/SessionsCard";

const STATUS_OPTIONS: { value: string; label: string }[] = [
  { value: "__all__", label: "Todos os status" },
  { value: "pendente", label: "Pendentes" },
  { value: "processando", label: "Processando" },
  { value: "sucesso", label: "Sucessos" },
  { value: "erro", label: "Erros (técnicos)" },
  { value: "nao_encontrado", label: "Não encontrados no AJUS" },
  { value: "cancelado", label: "Cancelados" },
];

const ORIGEM_OPTIONS: { value: string; label: string }[] = [
  { value: "__all__", label: "Todas as origens" },
  { value: "intake_auto", label: "Intake automático" },
  { value: "planilha", label: "Planilha" },
];

const STATUS_BADGE: Record<AjusClassifStatus, { label: string; className: string }> = {
  pendente: { label: "Pendente", className: "bg-amber-50 text-amber-800 border-amber-300" },
  processando: { label: "Processando", className: "bg-blue-50 text-blue-800 border-blue-300" },
  sucesso: { label: "Sucesso", className: "bg-emerald-50 text-emerald-800 border-emerald-300" },
  erro: { label: "Erro", className: "bg-rose-50 text-rose-800 border-rose-300" },
  cancelado: { label: "Cancelado", className: "bg-slate-50 text-slate-700 border-slate-300" },
  nao_encontrado: { label: "Não encontrado", className: "bg-orange-50 text-orange-800 border-orange-300" },
};

const ORIGEM_BADGE: Record<string, { label: string; className: string }> = {
  intake_auto: { label: "Auto", className: "bg-violet-50 text-violet-800 border-violet-300" },
  planilha: { label: "Planilha", className: "bg-sky-50 text-sky-800 border-sky-300" },
};

function formatCnj(value: string | null | undefined): string {
  if (!value) return "-";
  const digits = value.replace(/\D/g, "");
  if (digits.length === 20) {
    return `${digits.slice(0, 7)}-${digits.slice(7, 9)}.${digits.slice(9, 13)}.${digits.slice(13, 14)}.${digits.slice(14, 16)}.${digits.slice(16, 20)}`;
  }
  return value;
}

export function ClassificacaoTab() {
  const { toast } = useToast();
  const fileInputRef = useRef<HTMLInputElement>(null);

  // ─── Defaults ─────────────────────────────────────────────────────
  const [defaults, setDefaults] = useState<AjusClassifDefaults | null>(null);
  const [defaultsLoading, setDefaultsLoading] = useState(false);
  const [defaultsSaving, setDefaultsSaving] = useState(false);
  const [draftMatter, setDraftMatter] = useState("");
  const [draftRisk, setDraftRisk] = useState("");

  // ─── Fila ─────────────────────────────────────────────────────────
  const [items, setItems] = useState<AjusClassifQueueItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [statusFilter, setStatusFilter] = useState<string[]>([]);
  const [origemFilter, setOrigemFilter] = useState("__all__");
  const [cnjFilter, setCnjFilter] = useState("");
  const [actionId, setActionId] = useState<number | null>(null);

  // ─── Edit modal ───────────────────────────────────────────────────
  const [editing, setEditing] = useState<AjusClassifQueueItem | null>(null);
  const [editForm, setEditForm] = useState<AjusClassifQueueUpdatePayload>({});
  const [editSaving, setEditSaving] = useState(false);

  // ─── Upload ───────────────────────────────────────────────────────
  const [uploading, setUploading] = useState(false);

  // ─── Dispatch (rodar fila agora) ──────────────────────────────────
  const [dispatching, setDispatching] = useState(false);

  // ─── Retry em massa dos erros ─────────────────────────────────────
  const [retryingBulk, setRetryingBulk] = useState(false);

  // ─── Debug screenshots por item ───────────────────────────────────
  // Mostra as PNGs que o runner salvou em volume quando o item falhou.
  // Aberto pelo botao "Ver debug" no row de item com erro.
  const [debugItem, setDebugItem] = useState<AjusClassifQueueItem | null>(null);
  const [debugFiles, setDebugFiles] = useState<AjusDebugScreenshot[]>([]);
  const [debugLoading, setDebugLoading] = useState(false);
  const [debugBlobs, setDebugBlobs] = useState<Record<string, string>>({});

  // Revoke blobs quando trocar/fechar pra evitar memory leak.
  useEffect(() => {
    return () => {
      for (const url of Object.values(debugBlobs)) {
        try { URL.revokeObjectURL(url); } catch { /* noop */ }
      }
    };
  }, [debugBlobs]);

  const openDebugDialog = useCallback(async (item: AjusClassifQueueItem) => {
    if (!item.dispatched_by_account_id) {
      toast({
        title: "Sem screenshots",
        description: "Esse item nao foi processado por nenhuma conta ainda.",
        variant: "destructive",
      });
      return;
    }
    setDebugItem(item);
    setDebugLoading(true);
    setDebugFiles([]);
    setDebugBlobs({});
    try {
      const all = await listAjusDebugScreenshots(item.dispatched_by_account_id);
      // Filtra screenshots gerados perto do executed_at do item
      // (janela de +/- 10min). Se nao tiver executed_at, mostra todos
      // os mais recentes (ate 10).
      const ts = item.executed_at ? Date.parse(item.executed_at) / 1000 : null;
      const window = 10 * 60; // 10 min
      const filtered = ts
        ? all.filter((f) => Math.abs(f.mtime - ts) <= window).slice(0, 20)
        : all.slice(0, 10);
      const finalFiles = filtered.length ? filtered : all.slice(0, 5);
      setDebugFiles(finalFiles);

      // Pre-carrega blobs (autenticados) — abre os mais recentes em
      // sequencia pra UI ja mostrar a primeira imagem.
      const blobs: Record<string, string> = {};
      for (const f of finalFiles.slice(0, 5)) {
        try {
          blobs[f.name] = await fetchAjusDebugScreenshotBlobUrl(
            item.dispatched_by_account_id, f.name,
          );
        } catch {
          // ignora — UI mostra placeholder
        }
      }
      setDebugBlobs(blobs);
    } catch (e: unknown) {
      toast({
        title: "Erro ao carregar screenshots",
        description: e instanceof Error ? e.message : String(e),
        variant: "destructive",
      });
    } finally {
      setDebugLoading(false);
    }
  }, [toast]);

  const closeDebugDialog = useCallback(() => {
    setDebugItem(null);
    setDebugFiles([]);
    // revoga blobs ao fechar
    for (const url of Object.values(debugBlobs)) {
      try { URL.revokeObjectURL(url); } catch { /* noop */ }
    }
    setDebugBlobs({});
  }, [debugBlobs]);

  // ─── Loaders ──────────────────────────────────────────────────────
  const loadDefaults = useCallback(async () => {
    setDefaultsLoading(true);
    try {
      const data = await fetchAjusClassifDefaults();
      setDefaults(data);
      setDraftMatter(data.default_matter || "");
      setDraftRisk(data.default_risk_loss_probability || "");
    } catch (e: unknown) {
      toast({
        title: "Erro ao carregar defaults",
        description: e instanceof Error ? e.message : String(e),
        variant: "destructive",
      });
    } finally {
      setDefaultsLoading(false);
    }
  }, [toast]);

  const loadItems = useCallback(async () => {
    setLoading(true);
    try {
      const filters: Parameters<typeof fetchAjusClassif>[0] = { limit: 200 };
      if (statusFilter.length > 0) filters.status = statusFilter.join(",");
      if (origemFilter !== "__all__") filters.origem = origemFilter as "intake_auto" | "planilha";
      if (cnjFilter.trim()) filters.cnj_search = cnjFilter.trim();
      const resp = await fetchAjusClassif(filters);
      setItems(resp.items);
      setTotal(resp.total);
    } catch (e: unknown) {
      toast({
        title: "Erro ao carregar fila",
        description: e instanceof Error ? e.message : String(e),
        variant: "destructive",
      });
    } finally {
      setLoading(false);
    }
  }, [statusFilter, origemFilter, cnjFilter, toast]);

  useEffect(() => { loadDefaults(); }, [loadDefaults]);
  useEffect(() => { loadItems(); }, [loadItems]);

  // Auto-refresh — quando ha items em transicao (pendente claimed,
  // processando), polla a cada 3s pra refletir progresso do runner
  // sem o operador precisar apertar "Atualizar". Para sozinho quando
  // nao ha mais nada em curso.
  useEffect(() => {
    const inFlight = items.some(
      (i) => i.status === "processando" || (i.status === "pendente" && i.dispatched_by_account_id),
    );
    if (!inFlight) return;
    const id = setInterval(() => { void loadItems(); }, 3000);
    return () => clearInterval(id);
  }, [items, loadItems]);

  // ─── Defaults ─────────────────────────────────────────────────────
  const dirtyDefaults = useMemo(() => {
    if (!defaults) return false;
    return (
      (defaults.default_matter || "") !== draftMatter.trim() ||
      (defaults.default_risk_loss_probability || "") !== draftRisk.trim()
    );
  }, [defaults, draftMatter, draftRisk]);

  const handleSaveDefaults = async () => {
    setDefaultsSaving(true);
    try {
      const updated = await updateAjusClassifDefaults({
        default_matter: draftMatter.trim() || null,
        default_risk_loss_probability: draftRisk.trim() || null,
      });
      setDefaults(updated);
      toast({ title: "Defaults atualizados" });
    } catch (e: unknown) {
      toast({
        title: "Erro ao salvar defaults",
        description: e instanceof Error ? e.message : String(e),
        variant: "destructive",
      });
    } finally {
      setDefaultsSaving(false);
    }
  };

  // ─── Item handlers ────────────────────────────────────────────────
  const startEdit = (item: AjusClassifQueueItem) => {
    setEditing(item);
    setEditForm({
      uf: item.uf,
      comarca: item.comarca,
      matter: item.matter,
      justice_fee: item.justice_fee,
      risk_loss_probability: item.risk_loss_probability,
    });
  };

  const handleSaveEdit = async () => {
    if (!editing) return;
    setEditSaving(true);
    try {
      await updateAjusClassifItem(editing.id, editForm);
      toast({ title: "Item atualizado" });
      setEditing(null);
      await loadItems();
    } catch (e: unknown) {
      toast({
        title: "Erro ao salvar item",
        description: e instanceof Error ? e.message : String(e),
        variant: "destructive",
      });
    } finally {
      setEditSaving(false);
    }
  };

  const handleCancel = async (id: number) => {
    setActionId(id);
    try {
      await cancelAjusClassifItem(id);
      toast({ title: "Item cancelado" });
      await loadItems();
    } catch (e: unknown) {
      toast({
        title: "Erro ao cancelar",
        description: e instanceof Error ? e.message : String(e),
        variant: "destructive",
      });
    } finally {
      setActionId(null);
    }
  };

  const handleRetry = async (id: number) => {
    setActionId(id);
    try {
      await retryAjusClassifItem(id);
      toast({ title: "Item reenfileirado" });
      await loadItems();
    } catch (e: unknown) {
      toast({
        title: "Erro ao reenfileirar",
        description: e instanceof Error ? e.message : String(e),
        variant: "destructive",
      });
    } finally {
      setActionId(null);
    }
  };

  // ─── Dispatch ─────────────────────────────────────────────────────
  // O endpoint /dispatch agora APENAS sinaliza — o ajus-runner roda em
  // outro container, faz fast-poll de 2s e processa. Aqui mostramos
  // a mensagem do backend e damos refresh diferido pra capturar progresso.
  const handleDispatch = async () => {
    setDispatching(true);
    try {
      const res = await dispatchAjusClassif();
      toast({
        title: res.accepted ? "Disparo sinalizado" : "Nada a disparar",
        description: res.message ?? `${res.candidates} candidato(s).`,
        variant: res.accepted ? "default" : "destructive",
      });
      // Reload imediato pra refletir status, e outro depois de 5s pra
      // pegar o progresso do ajus-runner (fast-poll de 2s + processamento).
      await loadItems();
      if (res.accepted) {
        setTimeout(() => { void loadItems(); }, 5000);
        setTimeout(() => { void loadItems(); }, 15000);
      }
    } catch (e: unknown) {
      toast({
        title: "Erro ao disparar",
        description: e instanceof Error ? e.message : String(e),
        variant: "destructive",
      });
    } finally {
      setDispatching(false);
    }
  };

  // ─── Pause / Resume / Cancel pendentes ────────────────────────────
  const [pauseLoading, setPauseLoading] = useState(false);
  const [cancelPendentesLoading, setCancelPendentesLoading] = useState(false);
  const isPaused = !!defaults?.is_paused;

  const handlePauseToggle = async () => {
    setPauseLoading(true);
    try {
      const updated = isPaused ? await resumeAjusClassif() : await pauseAjusClassif();
      setDefaults(updated);
      toast({
        title: updated.is_paused ? "Dispatcher pausado" : "Dispatcher retomado",
        description: updated.is_paused
          ? "Itens em curso vao terminar; novos batches nao serao claimados ate retomar."
          : "Dispatcher voltou ao normal.",
      });
    } catch (e: unknown) {
      toast({
        title: "Erro ao alternar pausa",
        description: e instanceof Error ? e.message : String(e),
        variant: "destructive",
      });
    } finally {
      setPauseLoading(false);
    }
  };

  const handleCancelPendentes = async () => {
    const pendCount = items.filter((i) => i.status === "pendente").length;
    const msg =
      `Cancelar TODOS os itens em status 'pendente' que ainda nao foram ` +
      `processados? (Itens em curso continuarao normalmente.)\n\n` +
      `${pendCount} item(ns) pendente(s) na visao atual.`;
    if (!window.confirm(msg)) return;
    setCancelPendentesLoading(true);
    try {
      const res = await cancelAjusClassifPendentes();
      toast({
        title: "Pendentes cancelados",
        description: `${res.cancelled} item(ns) marcado(s) como cancelado.`,
      });
      await loadItems();
    } catch (e: unknown) {
      toast({
        title: "Erro ao cancelar pendentes",
        description: e instanceof Error ? e.message : String(e),
        variant: "destructive",
      });
    } finally {
      setCancelPendentesLoading(false);
    }
  };

  // ─── Retry em massa dos itens em erro ─────────────────────────────
  const handleRetryAllErrors = async () => {
    const errorCount = items.filter((i) => i.status === "erro").length;
    if (errorCount === 0) return;
    if (!window.confirm(
      `Reenfileirar ${errorCount} item(ns) em status 'erro' visíveis na lista? ` +
      `(Os filtros atuais ainda se aplicam — só os mostrados serão afetados.)`,
    )) {
      return;
    }
    setRetryingBulk(true);
    try {
      // Restringe ao conjunto VISÍVEL (filtrado). Sem item_ids o
      // endpoint pegaria TODOS os erros do banco — mais arriscado.
      const ids = items.filter((i) => i.status === "erro").map((i) => i.id);
      const res = await retryAjusClassifErrorsBulk(ids);
      toast({
        title: "Retry em massa concluído",
        description: `${res.retried} item(ns) reenfileirado(s).`,
      });
      await loadItems();
    } catch (e: unknown) {
      toast({
        title: "Erro no retry em massa",
        description: e instanceof Error ? e.message : String(e),
        variant: "destructive",
      });
    } finally {
      setRetryingBulk(false);
    }
  };

  // ─── Upload ───────────────────────────────────────────────────────
  const handleUpload = async (file: File) => {
    setUploading(true);
    try {
      const res = await uploadAjusClassifXlsx(file);
      const lines: string[] = [];
      lines.push(`${res.created} novo(s)`);
      if (res.updated) lines.push(`${res.updated} atualizado(s)`);
      if (res.skipped.length) lines.push(`${res.skipped.length} ignorado(s)`);
      toast({
        title: "Planilha processada",
        description: lines.join(" · "),
      });
      if (res.skipped.length) {
        // eslint-disable-next-line no-console
        console.warn("AJUS classif: linhas ignoradas:", res.skipped);
      }
      await loadItems();
    } catch (e: unknown) {
      toast({
        title: "Erro ao processar planilha",
        description: e instanceof Error ? e.message : String(e),
        variant: "destructive",
      });
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  // ─── Render ───────────────────────────────────────────────────────
  return (
    <div className="space-y-4">
      {/* Card de sessões AJUS (multi-conta) */}
      <SessionsCard />

      {/* Aviso defaults vazios */}
      {defaults && (!defaults.default_matter || !defaults.default_risk_loss_probability) && (
        <Alert>
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Defaults incompletos</AlertTitle>
          <AlertDescription>
            Configure abaixo a Matéria e o Risco/Probabilidade Perda padrão.
            Sem isso, intakes automáticos ficam com esses campos em branco e
            o operador precisa preencher um a um antes do dispatch.
          </AlertDescription>
        </Alert>
      )}

      {/* Card Defaults */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Defaults globais</CardTitle>
          <CardDescription>
            Aplicados a TODO intake automático. Operador pode editar por linha
            antes do dispatch. Linhas que vêm via planilha ignoram esses
            defaults (planilha traz tudo preenchido).
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid gap-3 md:grid-cols-2">
            <div className="space-y-1">
              <Label htmlFor="default-matter">Matéria padrão</Label>
              <Input
                id="default-matter"
                value={draftMatter}
                onChange={(e) => setDraftMatter(e.target.value)}
                placeholder="Ex.: Cumprimento de Sentença"
                disabled={defaultsLoading}
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="default-risk">Risco / Prob. Perda padrão</Label>
              <Input
                id="default-risk"
                value={draftRisk}
                onChange={(e) => setDraftRisk(e.target.value)}
                placeholder="Ex.: Remoto"
                disabled={defaultsLoading}
              />
            </div>
          </div>
          <div className="flex justify-end">
            <Button
              size="sm"
              onClick={handleSaveDefaults}
              disabled={!dirtyDefaults || defaultsSaving}
            >
              {defaultsSaving ? (
                <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
              ) : (
                <Save className="mr-2 h-3.5 w-3.5" />
              )}
              Salvar defaults
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Card Fila */}
      <Card>
        <CardHeader className="pb-3">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <CardTitle className="text-base">
                Fila de classificação
                {isPaused && (
                  <Badge
                    variant="outline"
                    className="ml-2 bg-amber-100 text-amber-900 border-amber-400 align-middle"
                    title={
                      defaults?.paused_at
                        ? `Pausado em ${new Date(defaults.paused_at).toLocaleString("pt-BR")}`
                            + (defaults?.paused_by ? ` por ${defaults.paused_by}` : "")
                        : "Dispatcher pausado"
                    }
                  >
                    <Pause className="mr-1 h-3 w-3" />
                    PAUSADO
                  </Badge>
                )}
              </CardTitle>
              <CardDescription>
                {total} item(ns). Origem "Auto" vem dos intakes de Prazos
                Iniciais; "Planilha" vem do upload manual.
                {isPaused && (
                  <span className="block mt-1 text-amber-800">
                    Dispatcher pausado — itens em curso terminam, novos
                    batches NAO serao claimados ate retomar.
                  </span>
                )}
              </CardDescription>
            </div>
            <div className="flex flex-wrap items-end gap-2">
              <div className="space-y-1">
                <label className="text-[10px] uppercase tracking-wide text-muted-foreground">
                  Status
                </label>
                <Popover>
                  <PopoverTrigger asChild>
                    <Button
                      variant="outline"
                      size="sm"
                      className="h-8 w-[200px] justify-between text-xs font-normal"
                    >
                      <span className="truncate">
                        {statusFilter.length === 0
                          ? "Todos os status"
                          : statusFilter.length === 1
                          ? STATUS_OPTIONS.find((o) => o.value === statusFilter[0])?.label || statusFilter[0]
                          : `${statusFilter.length} status selecionados`}
                      </span>
                      <ChevronDown className="ml-2 h-3 w-3 shrink-0 opacity-60" />
                    </Button>
                  </PopoverTrigger>
                  <PopoverContent className="w-[240px] p-2" align="start">
                    <div className="space-y-1">
                      <button
                        type="button"
                        className="w-full rounded px-2 py-1.5 text-left text-xs hover:bg-accent"
                        onClick={() => setStatusFilter([])}
                      >
                        {statusFilter.length === 0 ? "✓ " : ""}Todos os status
                      </button>
                      <div className="my-1 h-px bg-border" />
                      {STATUS_OPTIONS.filter((o) => o.value !== "__all__").map((o) => {
                        const checked = statusFilter.includes(o.value);
                        return (
                          <label
                            key={o.value}
                            className="flex items-center gap-2 rounded px-2 py-1.5 text-xs hover:bg-accent cursor-pointer"
                          >
                            <Checkbox
                              checked={checked}
                              onCheckedChange={(c) => {
                                if (c) {
                                  setStatusFilter((prev) => [...prev, o.value]);
                                } else {
                                  setStatusFilter((prev) => prev.filter((s) => s !== o.value));
                                }
                              }}
                            />
                            <span>{o.label}</span>
                          </label>
                        );
                      })}
                    </div>
                  </PopoverContent>
                </Popover>
              </div>
              <div className="space-y-1">
                <label className="text-[10px] uppercase tracking-wide text-muted-foreground">
                  Origem
                </label>
                <Select value={origemFilter} onValueChange={setOrigemFilter}>
                  <SelectTrigger className="h-8 w-[160px] text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {ORIGEM_OPTIONS.map((o) => (
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
                  onBlur={loadItems}
                  onKeyDown={(e) => { if (e.key === "Enter") loadItems(); }}
                  placeholder="CNJ"
                  className="h-8 w-[180px] text-xs"
                />
              </div>
              <Button
                size="sm"
                variant="outline"
                onClick={loadItems}
                disabled={loading}
              >
                <RefreshCw className={`mr-2 h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
                Atualizar
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={handleRetryAllErrors}
                disabled={retryingBulk || items.filter((i) => i.status === "erro").length === 0}
                title="Reenfileira (status 'erro' -> 'pendente') todos os itens em erro visíveis na lista. Respeita os filtros aplicados."
              >
                {retryingBulk ? (
                  <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
                ) : (
                  <RotateCcw className="mr-2 h-3.5 w-3.5" />
                )}
                Retry erros
                {items.filter((i) => i.status === "erro").length > 0 && (
                  <span className="ml-1 text-[10px] opacity-80">
                    ({items.filter((i) => i.status === "erro").length})
                  </span>
                )}
              </Button>
              <Button
                size="sm"
                onClick={handleDispatch}
                disabled={
                  dispatching
                  || isPaused
                  || items.filter((i) => i.status === "pendente").length === 0
                }
                title={
                  isPaused
                    ? "Dispatcher esta pausado. Retome antes de disparar."
                    : "Distribui itens pendentes entre as contas online (round-robin) e processa em batches de 5 por conta."
                }
              >
                {dispatching ? (
                  <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Play className="mr-2 h-3.5 w-3.5" />
                )}
                Disparar pendentes
              </Button>
              <Button
                size="sm"
                variant={isPaused ? "default" : "outline"}
                onClick={handlePauseToggle}
                disabled={pauseLoading}
                title={
                  isPaused
                    ? "Dispatcher esta pausado. Clique pra retomar."
                    : "Pausar dispatcher (itens em curso terminam; novos batches nao sao claimados)."
                }
              >
                {pauseLoading ? (
                  <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
                ) : isPaused ? (
                  <Play className="mr-2 h-3.5 w-3.5" />
                ) : (
                  <Pause className="mr-2 h-3.5 w-3.5" />
                )}
                {isPaused ? "Retomar" : "Pausar"}
              </Button>
              <Button
                size="sm"
                variant="destructive"
                onClick={handleCancelPendentes}
                disabled={
                  cancelPendentesLoading
                  || items.filter((i) => i.status === "pendente").length === 0
                }
                title="Cancela TODOS os itens em status 'pendente' que ainda nao foram processados. Itens em curso continuam."
              >
                {cancelPendentesLoading ? (
                  <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
                ) : (
                  <StopCircle className="mr-2 h-3.5 w-3.5" />
                )}
                Cancelar pendentes
              </Button>
              <Button
                size="sm"
                variant="outline"
                asChild
              >
                <a
                  href={ajusClassifTemplateXlsxUrl()}
                  download
                  rel="noopener noreferrer"
                >
                  <Download className="mr-2 h-3.5 w-3.5" />
                  Modelo XLSX
                </a>
              </Button>
              <Button
                size="sm"
                onClick={() => fileInputRef.current?.click()}
                disabled={uploading}
              >
                {uploading ? (
                  <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Upload className="mr-2 h-3.5 w-3.5" />
                )}
                Subir planilha
              </Button>
              <input
                ref={fileInputRef}
                type="file"
                accept=".xlsx"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) handleUpload(f);
                }}
              />
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>CNJ</TableHead>
                <TableHead>Origem</TableHead>
                <TableHead>UF</TableHead>
                <TableHead>Comarca</TableHead>
                <TableHead>Matéria</TableHead>
                <TableHead>Justiça/Honor.</TableHead>
                <TableHead>Risco</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Ações</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.length === 0 && !loading && (
                <TableRow>
                  <TableCell colSpan={9} className="text-center text-sm text-muted-foreground py-8">
                    Nenhum item na fila com os filtros atuais.
                  </TableCell>
                </TableRow>
              )}
              {items.map((item) => {
                const stBadge = STATUS_BADGE[item.status] || { label: item.status, className: "" };
                const orBadge = ORIGEM_BADGE[item.origem] || { label: item.origem, className: "" };
                const editable = item.status === "pendente" || item.status === "erro";
                const isProcessing = item.status === "processando";
                const isClaimed = item.status === "pendente" && !!item.dispatched_by_account_id;
                return (
                  <TableRow
                    key={item.id}
                    className={
                      isProcessing
                        ? "bg-blue-50 animate-pulse border-l-4 border-blue-500"
                        : isClaimed
                        ? "bg-blue-50/40 border-l-4 border-blue-300"
                        : undefined
                    }
                  >
                    <TableCell className="font-mono text-xs">
                      {formatCnj(item.cnj_number)}
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline" className={orBadge.className}>{orBadge.label}</Badge>
                    </TableCell>
                    <TableCell className="text-xs">{item.uf || "—"}</TableCell>
                    <TableCell className="text-xs max-w-[180px] truncate" title={item.comarca || ""}>
                      {item.comarca || "—"}
                    </TableCell>
                    <TableCell className="text-xs max-w-[180px] truncate" title={item.matter || ""}>
                      {item.matter || <span className="text-amber-700">—</span>}
                    </TableCell>
                    <TableCell className="text-xs max-w-[180px] truncate" title={item.justice_fee || ""}>
                      {item.justice_fee || <span className="text-amber-700">—</span>}
                    </TableCell>
                    <TableCell className="text-xs max-w-[140px] truncate" title={item.risk_loss_probability || ""}>
                      {item.risk_loss_probability || <span className="text-amber-700">—</span>}
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline" className={stBadge.className}>
                        {isProcessing && <Loader2 className="mr-1 h-3 w-3 animate-spin inline" />}
                        {isClaimed && !isProcessing && (
                          <span className="mr-1 inline-block h-2 w-2 rounded-full bg-blue-500 animate-pulse" />
                        )}
                        {isProcessing ? "Em execução" : isClaimed ? "Na fila do runner" : stBadge.label}
                      </Badge>
                      {item.error_message && (
                        <div
                          className="mt-1 max-w-[260px] truncate text-xs text-destructive"
                          title={item.error_message}
                        >
                          {item.error_message}
                        </div>
                      )}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-1">
                        {editable && (
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => startEdit(item)}
                            disabled={actionId === item.id}
                          >
                            <Pencil className="mr-1 h-3 w-3" />
                            Editar
                          </Button>
                        )}
                        {(item.status === "erro" || item.status === "nao_encontrado") && (
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => handleRetry(item.id)}
                            disabled={actionId === item.id}
                            title={
                              item.status === "nao_encontrado"
                                ? "Reenfileira esse item — use depois que o time cadastrar o processo no AJUS."
                                : "Reenfileira esse item pra nova tentativa do runner."
                            }
                          >
                            <RotateCcw className="mr-1 h-3 w-3" />
                            Retry
                          </Button>
                        )}
                        {(item.status === "erro" || item.status === "nao_encontrado")
                          && item.dispatched_by_account_id && (
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => openDebugDialog(item)}
                            disabled={actionId === item.id}
                            title="Ver screenshots de debug que o runner salvou na falha"
                          >
                            <Bug className="mr-1 h-3 w-3" />
                            Debug
                          </Button>
                        )}
                        {(item.status === "pendente" || item.status === "erro" || item.status === "nao_encontrado") && (
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => handleCancel(item.id)}
                            disabled={actionId === item.id}
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
        </CardContent>
      </Card>

      {/* Modal de edição */}
      <Dialog open={!!editing} onOpenChange={(open) => { if (!open) setEditing(null); }}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Editar classificação</DialogTitle>
            <DialogDescription>
              Edite os campos da capa antes do dispatch. Os textos devem
              bater EXATAMENTE com as opções aceitas no AJUS.
              {editing && (
                <span className="block mt-1 text-xs font-mono">
                  CNJ: {formatCnj(editing.cnj_number)}
                </span>
              )}
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-3 md:grid-cols-2">
            <div className="space-y-1">
              <Label>UF</Label>
              <Input
                value={editForm.uf || ""}
                onChange={(e) => setEditForm({ ...editForm, uf: e.target.value })}
              />
            </div>
            <div className="space-y-1">
              <Label>Comarca</Label>
              <Input
                value={editForm.comarca || ""}
                onChange={(e) => setEditForm({ ...editForm, comarca: e.target.value })}
              />
            </div>
            <div className="space-y-1 md:col-span-2">
              <Label>Matéria</Label>
              <Input
                value={editForm.matter || ""}
                onChange={(e) => setEditForm({ ...editForm, matter: e.target.value })}
                placeholder="Ex.: Cumprimento de Sentença"
              />
            </div>
            <div className="space-y-1 md:col-span-2">
              <Label>Justiça / Honorário</Label>
              <Input
                value={editForm.justice_fee || ""}
                onChange={(e) => setEditForm({ ...editForm, justice_fee: e.target.value })}
                placeholder="Ex.: Justiça Estadual"
              />
            </div>
            <div className="space-y-1 md:col-span-2">
              <Label>Risco / Prob. Perda</Label>
              <Input
                value={editForm.risk_loss_probability || ""}
                onChange={(e) => setEditForm({ ...editForm, risk_loss_probability: e.target.value })}
                placeholder="Ex.: Remoto"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditing(null)}>
              Cancelar
            </Button>
            <Button onClick={handleSaveEdit} disabled={editSaving}>
              {editSaving ? (
                <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
              ) : (
                <Save className="mr-2 h-3.5 w-3.5" />
              )}
              Salvar
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Modal de debug — screenshots que o runner salvou na falha do item */}
      <Dialog
        open={!!debugItem}
        onOpenChange={(open) => { if (!open) closeDebugDialog(); }}
      >
        <DialogContent className="max-w-4xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>
              Debug do item — CNJ {debugItem?.cnj_number || ""}
            </DialogTitle>
            <DialogDescription>
              Screenshots que o ajus-runner salvou no volume da conta{" "}
              <code>{debugItem?.dispatched_by_account_id ?? "?"}</code>
              {debugItem?.executed_at && (
                <>
                  {" "}— filtrados perto de{" "}
                  <code>{new Date(debugItem.executed_at).toLocaleString("pt-BR")}</code>
                </>
              )}
              .
            </DialogDescription>
          </DialogHeader>

          {debugItem?.error_message && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertTitle>Mensagem de erro</AlertTitle>
              <AlertDescription className="break-all text-xs">
                {debugItem.error_message}
              </AlertDescription>
            </Alert>
          )}

          {debugLoading ? (
            <div className="flex items-center justify-center gap-2 py-12 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Carregando screenshots...
            </div>
          ) : debugFiles.length === 0 ? (
            <div className="py-8 text-center text-sm text-muted-foreground">
              Nenhum screenshot encontrado pra esse item. O volume{" "}
              <code>/app/data/ajus-session/{debugItem?.dispatched_by_account_id}</code>{" "}
              pode estar vazio ou nao montado neste container.
            </div>
          ) : (
            <div className="space-y-4">
              {debugFiles.map((f) => (
                <div key={f.name} className="rounded-md border bg-muted/30 p-2">
                  <div className="mb-2 flex items-center justify-between gap-2 text-xs">
                    <code className="truncate" title={f.name}>{f.name}</code>
                    <span className="shrink-0 text-muted-foreground">
                      {new Date(f.mtime * 1000).toLocaleString("pt-BR")} ·{" "}
                      {(f.size / 1024).toFixed(1)} KB
                    </span>
                  </div>
                  {debugBlobs[f.name] ? (
                    <a
                      href={debugBlobs[f.name]}
                      target="_blank"
                      rel="noopener noreferrer"
                      title="Abrir em tamanho real em nova aba"
                    >
                      <img
                        src={debugBlobs[f.name]}
                        alt={f.name}
                        className="w-full rounded border"
                        loading="lazy"
                      />
                    </a>
                  ) : (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={async () => {
                        if (!debugItem?.dispatched_by_account_id) return;
                        try {
                          const url = await fetchAjusDebugScreenshotBlobUrl(
                            debugItem.dispatched_by_account_id, f.name,
                          );
                          setDebugBlobs((prev) => ({ ...prev, [f.name]: url }));
                        } catch (e) {
                          toast({
                            title: "Falha ao carregar imagem",
                            description: e instanceof Error ? e.message : String(e),
                            variant: "destructive",
                          });
                        }
                      }}
                    >
                      Carregar imagem
                    </Button>
                  )}
                </div>
              ))}
            </div>
          )}

          <DialogFooter>
            <Button variant="outline" onClick={closeDebugDialog}>
              Fechar
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
