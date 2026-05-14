// frontend/src/pages/ClassificadorPage.tsx
//
// Pagina do modulo Classificador (diagnostico de carteira).
//
// Fase 2 (corrente):
// - Aba "Novo lote": 2 dialogs reais (upload xlsx + import de Prazos Iniciais).
// - Aba "Historico": tabela paginada de lotes criados, com badges de status.
// - Aba "Painel": placeholder (Fase 4 — graficos com recharts).

import { useCallback, useEffect, useMemo, useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Loader2, FileUp, Workflow, BarChart3, ScanSearch, Trash2, AlertCircle, FilePlus2, Sparkles, Eye, Inbox, Eraser, Users, RefreshCw, CalendarClock } from "lucide-react";
import { useToast } from "@/components/ui/use-toast";
import {
  ClassificadorLoteSummary,
  ClassificadorFromPiPreview,
  classifyClassificadorLote,
  cleanupClassificadorPedidosDuplicados,
  backfillClassificadorPartes,
  reExtractClassificadorPartes,
  reExtractClassificadorAudiencias,
  createClassificadorLoteFromPi,
  createClassificadorLoteUpload,
  deleteClassificadorLote,
  fetchClassificadorLotes,
  previewClassificadorFromPi,
} from "@/services/api";
import UploadPdfDialog from "@/components/classificador/UploadPdfDialog";
import LoteDetailDialog from "@/components/classificador/LoteDetailDialog";
import QuickPdfCard from "@/components/classificador/QuickPdfCard";
import PainelGlobalTab from "@/components/classificador/PainelGlobalTab";
import FilaTab from "@/components/classificador/FilaTab";


// ─── Helpers ──────────────────────────────────────────────────────────

const STATUS_BADGE: Record<string, { label: string; variant: "default" | "secondary" | "destructive" | "outline" }> = {
  RASCUNHO: { label: "Rascunho", variant: "secondary" },
  CAPTURANDO_L1: { label: "Capturando L1", variant: "default" },
  PRONTO_PARA_CLASSIFICAR: { label: "Pronto", variant: "default" },
  CLASSIFICANDO: { label: "Classificando", variant: "default" },
  CLASSIFICADO: { label: "Classificado", variant: "default" },
  ERRO: { label: "Erro", variant: "destructive" },
  CANCELADO: { label: "Cancelado", variant: "outline" },
};

function fmtBRL(value: number | null | undefined): string {
  if (value == null) return "—";
  return value.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
  } catch {
    return iso;
  }
}


// ─── Componente principal ────────────────────────────────────────────

export default function ClassificadorPage() {
  const [tab, setTab] = useState<string>("novo");
  const [reloadKey, setReloadKey] = useState(0);

  const refreshHistorico = useCallback(() => setReloadKey(k => k + 1), []);

  const handleLoteCriado = useCallback((lote: ClassificadorLoteSummary) => {
    refreshHistorico();
    setTab("historico");
  }, [refreshHistorico]);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
          <ScanSearch className="h-6 w-6 text-primary" />
          Classificador
        </h1>
        <p className="text-sm text-muted-foreground">
          Diagnostico de carteira processual — captura, classifica e gera
          relatorio executivo pra cliente. Reaproveita intakes ja tratados em
          Prazos Iniciais ou aceita carteiras avulsas via xlsx.
        </p>
      </div>

      <Tabs value={tab} onValueChange={setTab} className="w-full">
        <TabsList>
          <TabsTrigger value="novo" className="gap-2">
            <FileUp className="h-4 w-4" />
            Novo lote
          </TabsTrigger>
          <TabsTrigger value="historico" className="gap-2">
            <Workflow className="h-4 w-4" />
            Historico
          </TabsTrigger>
          <TabsTrigger value="fila" className="gap-2">
            <Inbox className="h-4 w-4" />
            Fila do robô
          </TabsTrigger>
          <TabsTrigger value="painel" className="gap-2">
            <BarChart3 className="h-4 w-4" />
            Painel
          </TabsTrigger>
        </TabsList>

        <TabsContent value="novo" className="mt-4">
          <div className="grid gap-4 md:grid-cols-3">
            <UploadXlsxCard onCreated={handleLoteCriado} />
            <ImportFromPiCard onCreated={handleLoteCriado} />
            <QuickPdfCard onCreated={(lote) => handleLoteCriado(lote)} />
            {/* (segundo arg `processoIds` ignorado — sera usado em Fase 4 pra abrir detalhe automatico) */}
          </div>

          <Card className="mt-4">
            <CardHeader>
              <CardTitle className="text-base">Fluxo do diagnostico</CardTitle>
            </CardHeader>
            <CardContent>
              <ol className="list-decimal pl-5 space-y-1 text-sm text-muted-foreground">
                <li>Capturar carteira (upload xlsx ou import de Prazos Iniciais).</li>
                <li>Refresh L1 — capa atualizada de cada processo (Fase 2c).</li>
                <li>Classificacao Anthropic — categoria/sub + PCOND + prob. exito (Fase 3).</li>
                <li>Relatorio — xlsx multi-aba + PDF executivo + painel (Fase 4).</li>
              </ol>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="historico" className="mt-4">
          <LotesHistoricoTable reloadKey={reloadKey} onChanged={refreshHistorico} />
        </TabsContent>

        <TabsContent value="fila" className="mt-4">
          <FilaTab />
        </TabsContent>

        <TabsContent value="painel" className="mt-4">
          <PainelGlobalTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}


// ─── Card: Upload xlsx ────────────────────────────────────────────────

function UploadXlsxCard({ onCreated }: { onCreated: (lote: ClassificadorLoteSummary) => void }) {
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [nome, setNome] = useState("");
  const [clienteNome, setClienteNome] = useState("");
  const [descricao, setDescricao] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [warnings, setWarnings] = useState<string[]>([]);

  const canSubmit = nome.trim().length > 0 && file != null && !submitting;

  const handleSubmit = async () => {
    if (!canSubmit || !file) return;
    setSubmitting(true);
    setWarnings([]);
    try {
      const result = await createClassificadorLoteUpload({
        nome: nome.trim(),
        cliente_nome: clienteNome.trim() || undefined,
        descricao: descricao.trim() || undefined,
        file,
      });
      toast({
        title: "Lote criado",
        description: `Lote #${result.lote.id} com ${result.lote.total_processos} processos.`,
      });
      if (result.warnings && result.warnings.length > 0) {
        setWarnings(result.warnings);
        // mantem dialog aberto pra operador ver os avisos
      } else {
        setOpen(false);
        setNome("");
        setClienteNome("");
        setDescricao("");
        setFile(null);
      }
      onCreated(result.lote);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      toast({ title: "Falha no upload", description: msg, variant: "destructive" });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg flex items-center gap-2">
          <FileUp className="h-5 w-5" />
          Upload de planilha
        </CardTitle>
        <CardDescription>
          Sobe uma planilha .xlsx com coluna <strong>CNJ</strong> (uma linha
          por processo). Os outros dados sao buscados na Legal One depois.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button className="w-full">Criar lote por upload xlsx</Button>
          </DialogTrigger>
          <DialogContent className="sm:max-w-lg">
            <DialogHeader>
              <DialogTitle>Novo lote — upload de planilha</DialogTitle>
              <DialogDescription>
                Sobe um arquivo .xlsx com coluna CNJ. Maximo 30MB. Linhas
                vazias e duplicatas sao ignoradas automaticamente.
              </DialogDescription>
            </DialogHeader>

            <div className="grid gap-3 py-2">
              <div className="grid gap-1">
                <Label htmlFor="up-nome">Nome do lote *</Label>
                <Input
                  id="up-nome"
                  value={nome}
                  onChange={e => setNome(e.target.value)}
                  placeholder="Ex.: Diagnostico Banco Master Q2/2026"
                  maxLength={255}
                />
              </div>
              <div className="grid gap-1">
                <Label htmlFor="up-cliente">Cliente final (opcional)</Label>
                <Input
                  id="up-cliente"
                  value={clienteNome}
                  onChange={e => setClienteNome(e.target.value)}
                  placeholder="Ex.: Banco Master"
                  maxLength={255}
                />
              </div>
              <div className="grid gap-1">
                <Label htmlFor="up-desc">Descricao (opcional)</Label>
                <Textarea
                  id="up-desc"
                  value={descricao}
                  onChange={e => setDescricao(e.target.value)}
                  rows={2}
                />
              </div>
              <div className="grid gap-1">
                <Label htmlFor="up-file">Arquivo .xlsx *</Label>
                <Input
                  id="up-file"
                  type="file"
                  accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                  onChange={e => setFile(e.target.files?.[0] || null)}
                />
                {file && (
                  <p className="text-xs text-muted-foreground">
                    {file.name} — {(file.size / 1024).toFixed(1)} KB
                  </p>
                )}
              </div>

              {warnings.length > 0 && (
                <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-xs space-y-1">
                  <div className="flex items-center gap-1 font-medium text-amber-900">
                    <AlertCircle className="h-3.5 w-3.5" />
                    Avisos do parser ({warnings.length})
                  </div>
                  <ul className="list-disc pl-4 max-h-32 overflow-auto text-amber-800">
                    {warnings.map((w, i) => (
                      <li key={i}>{w}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>

            <DialogFooter>
              <Button variant="ghost" onClick={() => setOpen(false)} disabled={submitting}>
                Cancelar
              </Button>
              <Button onClick={handleSubmit} disabled={!canSubmit}>
                {submitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Criar lote
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </CardContent>
    </Card>
  );
}


// ─── Card: Import de Prazos Iniciais ─────────────────────────────────

function ImportFromPiCard({ onCreated }: { onCreated: (lote: ClassificadorLoteSummary) => void }) {
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [nome, setNome] = useState("");
  const [clienteNome, setClienteNome] = useState("");
  const [descricao, setDescricao] = useState("");
  const [dataInicio, setDataInicio] = useState("");
  const [dataFim, setDataFim] = useState("");
  const [preview, setPreview] = useState<ClassificadorFromPiPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  // Modo UPSERT: se selecionou um candidato pra atualizar
  const [mergeLoteId, setMergeLoteId] = useState<number | null>(null);
  const [resetClassif, setResetClassif] = useState(false);

  const filtros = useMemo(() => ({
    data_inicio: dataInicio || null,
    data_fim: dataFim || null,
  }), [dataInicio, dataFim]);

  // Auto-preview quando filtros mudam (debounced)
  useEffect(() => {
    if (!open) return;
    const timer = setTimeout(async () => {
      setPreviewLoading(true);
      try {
        const p = await previewClassificadorFromPi(filtros);
        setPreview(p);
      } catch {
        setPreview(null);
      } finally {
        setPreviewLoading(false);
      }
    }, 400);
    return () => clearTimeout(timer);
  }, [filtros, open]);

  // Quando atualiza, nome do lote não é obrigatório (usa o do lote existente)
  const canSubmit =
    (mergeLoteId !== null || nome.trim().length > 0) &&
    preview != null && preview.count > 0 && !submitting;

  const handleSubmit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    try {
      const result = await createClassificadorLoteFromPi({
        nome: nome.trim() || "(merge)",
        cliente_nome: clienteNome.trim() || undefined,
        descricao: descricao.trim() || undefined,
        filtros,
        merge_into_lote_id: mergeLoteId ?? undefined,
        reset_classification: mergeLoteId !== null ? resetClassif : undefined,
      });
      if (result.merge_stats) {
        toast({
          title: `Lote #${result.lote.id} atualizado`,
          description: `${result.merge_stats.atualizados} atualizados · ${result.merge_stats.criados} novos${result.merge_stats.reclassificar ? " · reclassificando" : ""}.`,
        });
      } else {
        toast({
          title: "Lote criado",
          description: `Lote #${result.lote.id} com ${result.lote.total_processos} processos espelhados de Prazos Iniciais.`,
        });
      }
      setOpen(false);
      setNome("");
      setClienteNome("");
      setDescricao("");
      setDataInicio("");
      setDataFim("");
      setPreview(null);
      setMergeLoteId(null);
      setResetClassif(false);
      onCreated(result.lote);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      toast({ title: "Falha ao criar/atualizar lote", description: msg, variant: "destructive" });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg flex items-center gap-2">
          <Workflow className="h-5 w-5" />
          Import de Prazos Iniciais
        </CardTitle>
        <CardDescription>
          Cria um lote a partir dos intakes ja tratados em Prazos Iniciais.
          Os dados serao refrescados na Legal One antes do snapshot (Fase 2c).
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button variant="outline" className="w-full">
              Criar lote a partir de Prazos Iniciais
            </Button>
          </DialogTrigger>
          <DialogContent className="sm:max-w-lg">
            <DialogHeader>
              <DialogTitle>Novo lote — import de Prazos Iniciais</DialogTitle>
              <DialogDescription>
                Filtra os intakes ja tratados (status CLASSIFICADO/EM_REVISAO/
                AGENDADO/CONCLUIDO) e espelha como lote do Classificador.
              </DialogDescription>
            </DialogHeader>

            <div className="grid gap-3 py-2">
              <div className="grid gap-1">
                <Label htmlFor="pi-nome">Nome do lote *</Label>
                <Input
                  id="pi-nome"
                  value={nome}
                  onChange={e => setNome(e.target.value)}
                  placeholder="Ex.: Carteira Q2/2026"
                  maxLength={255}
                />
              </div>
              <div className="grid gap-1">
                <Label htmlFor="pi-cliente">Cliente final (opcional)</Label>
                <Input
                  id="pi-cliente"
                  value={clienteNome}
                  onChange={e => setClienteNome(e.target.value)}
                  placeholder="Ex.: Banco Master"
                  maxLength={255}
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="grid gap-1">
                  <Label htmlFor="pi-di">Data inicio</Label>
                  <Input
                    id="pi-di"
                    type="date"
                    value={dataInicio}
                    onChange={e => setDataInicio(e.target.value)}
                  />
                </div>
                <div className="grid gap-1">
                  <Label htmlFor="pi-df">Data fim</Label>
                  <Input
                    id="pi-df"
                    type="date"
                    value={dataFim}
                    onChange={e => setDataFim(e.target.value)}
                  />
                </div>
              </div>
              <div className="grid gap-1">
                <Label htmlFor="pi-desc">Descricao (opcional)</Label>
                <Textarea
                  id="pi-desc"
                  value={descricao}
                  onChange={e => setDescricao(e.target.value)}
                  rows={2}
                />
              </div>

              <div className="rounded-md border bg-muted/40 p-3 text-sm">
                {previewLoading ? (
                  <div className="flex items-center gap-2 text-muted-foreground">
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    Calculando preview...
                  </div>
                ) : preview ? (
                  <>
                    <div className="font-medium">
                      {preview.count > 0
                        ? `${preview.count} intake${preview.count > 1 ? "s" : ""} casam com os filtros.`
                        : "Nenhum intake casa com esses filtros."}
                    </div>
                    {preview.sample.length > 0 && (
                      <ul className="mt-1 text-xs text-muted-foreground space-y-0.5">
                        {preview.sample.slice(0, 3).map(s => (
                          <li key={s.id}>
                            #{s.id} · {s.cnj_number || "(sem CNJ)"} · {s.status}
                          </li>
                        ))}
                        {preview.count > 3 && <li>+ {preview.count - 3} mais</li>}
                      </ul>
                    )}
                  </>
                ) : (
                  <div className="text-muted-foreground">
                    Defina os filtros pra ver o preview.
                  </div>
                )}
              </div>

              {/* Lotes candidatos (dedup) */}
              {preview && preview.candidate_lotes && preview.candidate_lotes.length > 0 && (
                <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-xs space-y-2">
                  <div className="flex items-center gap-1.5 font-medium text-amber-900">
                    <AlertCircle className="h-3.5 w-3.5" />
                    Lote{preview.candidate_lotes.length > 1 ? "s" : ""} existente{preview.candidate_lotes.length > 1 ? "s" : ""} detectado{preview.candidate_lotes.length > 1 ? "s" : ""}
                  </div>
                  <div className="text-amber-800">
                    Já existe lote no Classificador com os mesmos intakes do PI. Pra evitar duplicidade,
                    selecione um pra atualizar — ou clique "Criar novo" se quiser snapshot separado.
                  </div>
                  <div className="space-y-1">
                    {preview.candidate_lotes.map(c => (
                      <label
                        key={c.id}
                        className={`flex items-start gap-2 rounded border p-2 cursor-pointer ${
                          mergeLoteId === c.id
                            ? "border-amber-600 bg-amber-100"
                            : "border-amber-200 bg-white hover:bg-amber-50"
                        }`}
                      >
                        <input
                          type="radio"
                          name="merge-target"
                          checked={mergeLoteId === c.id}
                          onChange={() => setMergeLoteId(c.id)}
                          className="mt-0.5"
                        />
                        <div className="flex-1 min-w-0">
                          <div className="font-medium text-amber-900">
                            #{c.id} · {c.nome}
                          </div>
                          <div className="text-amber-800">
                            {c.cliente_nome || "(sem cliente)"} · status {c.status} ·
                            {" "}<strong>{c.matching_intakes} de {preview.count}</strong> intakes em comum
                            {" "}({c.total_processos} total no lote)
                          </div>
                        </div>
                      </label>
                    ))}
                    <label className={`flex items-start gap-2 rounded border p-2 cursor-pointer ${
                      mergeLoteId === null
                        ? "border-gray-500 bg-gray-100"
                        : "border-gray-200 bg-white hover:bg-gray-50"
                    }`}>
                      <input
                        type="radio"
                        name="merge-target"
                        checked={mergeLoteId === null}
                        onChange={() => setMergeLoteId(null)}
                        className="mt-0.5"
                      />
                      <div className="flex-1">
                        <div className="font-medium text-gray-900">Criar novo lote</div>
                        <div className="text-gray-600">
                          Snapshot separado — preserva relatórios antigos (gera duplicidade).
                        </div>
                      </div>
                    </label>
                  </div>

                  {mergeLoteId !== null && (
                    <label className="flex items-center gap-2 text-amber-900 mt-2">
                      <input
                        type="checkbox"
                        checked={resetClassif}
                        onChange={e => setResetClassif(e.target.checked)}
                      />
                      <span>
                        Reclassificar via IA após atualizar
                        <span className="text-amber-700"> (limpa categoria/valor/pedidos atuais e marca pra rodar Sonnet de novo)</span>
                      </span>
                    </label>
                  )}
                </div>
              )}
            </div>

            <DialogFooter>
              <Button variant="ghost" onClick={() => setOpen(false)} disabled={submitting}>
                Cancelar
              </Button>
              <Button onClick={handleSubmit} disabled={!canSubmit}>
                {submitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                {mergeLoteId !== null
                  ? `Atualizar lote #${mergeLoteId} (${preview?.count || 0})`
                  : `Criar lote ${preview && preview.count > 0 ? `(${preview.count})` : ""}`}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </CardContent>
    </Card>
  );
}


// ─── Tabela: Historico ───────────────────────────────────────────────

const PAGE_SIZE_DEFAULT = 25;

function LotesHistoricoTable({
  reloadKey,
  onChanged,
}: {
  reloadKey: number;
  onChanged: () => void;
}) {
  const { toast } = useToast();
  const [items, setItems] = useState<ClassificadorLoteSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(PAGE_SIZE_DEFAULT);
  const [loading, setLoading] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [classifyingId, setClassifyingId] = useState<number | null>(null);
  const [cleaningId, setCleaningId] = useState<number | null>(null);
  const [backfillingId, setBackfillingId] = useState<number | null>(null);
  const [reextractingId, setReextractingId] = useState<number | null>(null);
  const [audienciasId, setAudienciasId] = useState<number | null>(null);
  const [uploadDialogLote, setUploadDialogLote] = useState<ClassificadorLoteSummary | null>(null);
  const [detailDialogLote, setDetailDialogLote] = useState<ClassificadorLoteSummary | null>(null);

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  const handleClassify = async (lote: ClassificadorLoteSummary) => {
    const temErros = (lote.total_processos_com_erro || 0) > 0;
    const includeErrors = temErros && confirm(
      `Lote #${lote.id} tem ${lote.total_processos_com_erro} processo${lote.total_processos_com_erro > 1 ? "s" : ""} com erro de classificacao.\n\n` +
      `OK = INCLUIR os processos com erro (resetar e reclassificar)\n` +
      `Cancelar = NAO incluir (so' classifica os PRONTO)`,
    );

    if (!confirm(
      `Classificar lote #${lote.id} (${lote.nome})?\n\n` +
      `Vai submeter ${lote.total_processos_capturados}${includeErrors ? ` + ${lote.total_processos_com_erro} em erro` : ""} processos pra Sonnet ` +
      `via Anthropic Batches API.\n\n` +
      `Operacao async — pode levar minutos a horas. Worker do servidor ` +
      `acompanha automaticamente.`,
    )) return;
    setClassifyingId(lote.id);
    try {
      const r = await classifyClassificadorLote(lote.id, { includeErrors });
      toast({
        title: "Batch submetido",
        description: `Batch #${r.batch_id} (${r.total_records} processos) - ${r.status}. ` +
          `Anthropic batch=${r.anthropic_batch_id?.slice(0, 16) || "—"}...`,
      });
      onChanged();
    } catch (err) {
      toast({
        title: "Falha ao classificar",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setClassifyingId(null);
    }
  };

  useEffect(() => {
    let alive = true;
    setLoading(true);
    fetchClassificadorLotes({
      limit: pageSize,
      offset: (page - 1) * pageSize,
    })
      .then(res => {
        if (!alive) return;
        setItems(res.items);
        setTotal(res.total);
      })
      .catch(err => {
        if (!alive) return;
        toast({
          title: "Falha ao carregar lotes",
          description: err instanceof Error ? err.message : String(err),
          variant: "destructive",
        });
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [page, pageSize, reloadKey, toast]);

  const handleReExtractAudiencias = async (lote: ClassificadorLoteSummary) => {
    if (!confirm(
      `Extrair audiências do lote #${lote.id} (${lote.nome}) via regex no texto cru?\n\n` +
      `Util pra processos classificados ANTES do deploy de audiências. ` +
      `Operação gratuita (sem IA). Cobertura ~70-80% dos casos óbvios.`
    )) return;
    setAudienciasId(lote.id);
    try {
      const r = await reExtractClassificadorAudiencias(lote.id);
      toast({
        title: "Audiências extraídas",
        description:
          `${r.total_audiencias_extraidas} audiência(s) detectada(s) em ${r.processos_com_audiencia} de ${r.total_processos_no_lote} processo(s).` +
          (r.sem_texto > 0 ? ` ${r.sem_texto} sem texto cru.` : ""),
      });
      onChanged();
    } catch (err) {
      toast({
        title: "Falha ao extrair audiências",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setAudienciasId(null);
    }
  };

  const handleReExtractPartes = async (lote: ClassificadorLoteSummary) => {
    if (!confirm(
      `Re-extrair partes (e classe/vara/valor) do lote #${lote.id} (${lote.nome})?\n\n` +
      `Util pra processos cujo PDF foi subido ANTES do deploy que adicionou ` +
      `capa rica (capa_json antigo so' tinha 'tribunal'). Re-extrai do texto ` +
      `cru armazenado em integra_json. Operacao segura: nao re-processa PDF.`
    )) return;
    setReextractingId(lote.id);
    try {
      const r = await reExtractClassificadorPartes(lote.id);
      toast({
        title: "Re-extracao concluida",
        description:
          `${r.atualizados}/${r.total_processos_no_lote} processo${r.atualizados === 1 ? "" : "s"} ` +
          `com partes extraidas. ${r.com_capa_enriquecida} capa${r.com_capa_enriquecida === 1 ? "" : "s"} ` +
          `enriquecida${r.com_capa_enriquecida === 1 ? "" : "s"}.` +
          (r.sem_texto > 0 ? ` ${r.sem_texto} sem texto cru.` : ""),
      });
      onChanged();
    } catch (err) {
      toast({
        title: "Falha na re-extracao",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setReextractingId(null);
    }
  };

  const handleBackfillPartes = async (lote: ClassificadorLoteSummary) => {
    if (!confirm(
      `Preencher partes (polo ativo/passivo) do lote #${lote.id} (${lote.nome})?\n\n` +
      `Util pra lotes criados antes do fix que copiava partes do capa_json ` +
      `pras colunas separadas. Operacao segura: nao reextrai nada, so' copia ` +
      `do JSON existente.`
    )) return;
    setBackfillingId(lote.id);
    try {
      const r = await backfillClassificadorPartes(lote.id);
      toast({
        title: "Backfill concluido",
        description:
          `${r.atualizados}/${r.total_processos_no_lote} processo${r.atualizados === 1 ? "" : "s"} atualizado${r.atualizados === 1 ? "" : "s"}. ` +
          `${r.com_partes_em_capa} tinham partes no capa_json. ` +
          (r.sem_capa_json > 0 ? `${r.sem_capa_json} sem capa.` : ""),
      });
      onChanged();
    } catch (err) {
      toast({
        title: "Falha no backfill",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setBackfillingId(null);
    }
  };

  const handleCleanupPedidos = async (lote: ClassificadorLoteSummary) => {
    if (!confirm(
      `Limpar pedidos duplicados do lote #${lote.id} (${lote.nome})?\n\n` +
      `Util pra lotes que foram classificados antes do fix de duplicacao ` +
      `(quando o botao Classificar era pressionado varias vezes seguidas).\n\n` +
      `Mantem 1 copia de cada pedido unico por processo. Operacao segura: ` +
      `nao apaga pedidos legitimos.`
    )) return;
    setCleaningId(lote.id);
    try {
      const r = await cleanupClassificadorPedidosDuplicados(lote.id);
      toast({
        title: "Limpeza concluida",
        description:
          `${r.pedidos_removidos} pedido${r.pedidos_removidos === 1 ? "" : "s"} duplicado${r.pedidos_removidos === 1 ? "" : "s"} ` +
          `removido${r.pedidos_removidos === 1 ? "" : "s"} em ${r.processos_afetados} processo${r.processos_afetados === 1 ? "" : "s"}.`,
      });
      onChanged();
    } catch (err) {
      toast({
        title: "Falha na limpeza",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setCleaningId(null);
    }
  };

  const handleDelete = async (loteId: number) => {
    if (!confirm(`Apagar lote #${loteId}? Essa operacao nao pode ser desfeita.`)) return;
    setDeletingId(loteId);
    try {
      await deleteClassificadorLote(loteId);
      toast({ title: "Lote apagado", description: `#${loteId} removido.` });
      onChanged();
    } catch (err) {
      toast({
        title: "Falha ao apagar lote",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Lotes ja criados</CardTitle>
        <CardDescription>
          Cada linha e' um diagnostico de carteira. Total: {total}.
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
            Nenhum lote criado ainda. Vai pra aba "Novo lote" pra comecar.
          </div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-xs text-muted-foreground">
                    <th className="py-2 pr-3">#</th>
                    <th className="py-2 pr-3">Nome</th>
                    <th className="py-2 pr-3">Cliente</th>
                    <th className="py-2 pr-3">Status</th>
                    <th className="py-2 pr-3 text-right">Processos</th>
                    <th className="py-2 pr-3 text-right">PCOND total</th>
                    <th className="py-2 pr-3">Criado em</th>
                    <th className="py-2 pr-3" />
                  </tr>
                </thead>
                <tbody>
                  {items.map(lote => {
                    const badge = STATUS_BADGE[lote.status] || { label: lote.status, variant: "outline" as const };
                    return (
                      <tr key={lote.id} className="border-b hover:bg-muted/30">
                        <td className="py-2 pr-3 font-mono text-xs">#{lote.id}</td>
                        <td className="py-2 pr-3">{lote.nome}</td>
                        <td className="py-2 pr-3 text-muted-foreground">
                          {lote.cliente_nome || "—"}
                        </td>
                        <td className="py-2 pr-3">
                          <Badge variant={badge.variant}>{badge.label}</Badge>
                        </td>
                        <td className="py-2 pr-3 text-right tabular-nums">
                          {lote.total_processos_classificados}/{lote.total_processos}
                        </td>
                        <td className="py-2 pr-3 text-right tabular-nums text-muted-foreground">
                          {fmtBRL(lote.pcond_total)}
                        </td>
                        <td className="py-2 pr-3 text-xs text-muted-foreground">
                          {fmtDate(lote.created_at)}
                        </td>
                        <td className="py-2 pr-3 text-right">
                          <div className="inline-flex items-center gap-0.5">
                            <Button
                              variant="ghost"
                              size="icon"
                              onClick={() => setUploadDialogLote(lote)}
                              disabled={lote.status === "CLASSIFICADO"}
                              title={lote.status === "CLASSIFICADO" ? "Lote ja classificado" : "Subir PDFs"}
                            >
                              <FilePlus2 className="h-4 w-4" />
                            </Button>
                            <Button
                              variant="ghost"
                              size="icon"
                              onClick={() => handleClassify(lote)}
                              disabled={
                                classifyingId === lote.id ||
                                (lote.total_processos_capturados === 0 && lote.total_processos_com_erro === 0) ||
                                lote.status === "CLASSIFICANDO"
                              }
                              title={
                                (lote.total_processos_capturados === 0 && lote.total_processos_com_erro === 0)
                                  ? "Suba PDFs antes de classificar"
                                  : lote.status === "CLASSIFICANDO"
                                    ? "Lote em classificacao em curso"
                                    : lote.total_processos_com_erro > 0
                                      ? `Classificar ${lote.total_processos_capturados} + ${lote.total_processos_com_erro} em erro (opcional)`
                                      : `Classificar ${lote.total_processos_capturados} processos via Sonnet`
                              }
                            >
                              {classifyingId === lote.id ? (
                                <Loader2 className="h-4 w-4 animate-spin" />
                              ) : (
                                <Sparkles className="h-4 w-4" />
                              )}
                            </Button>
                            <Button
                              variant="ghost"
                              size="icon"
                              onClick={() => setDetailDialogLote(lote)}
                              title="Detalhe (processos + batches)"
                            >
                              <Eye className="h-4 w-4" />
                            </Button>
                            <Button
                              variant="ghost"
                              size="icon"
                              onClick={() => handleBackfillPartes(lote)}
                              disabled={backfillingId === lote.id}
                              title="Preencher polo ativo/passivo a partir do capa_json (lotes antigos)"
                            >
                              {backfillingId === lote.id ? (
                                <Loader2 className="h-4 w-4 animate-spin" />
                              ) : (
                                <Users className="h-4 w-4" />
                              )}
                            </Button>
                            <Button
                              variant="ghost"
                              size="icon"
                              onClick={() => handleReExtractPartes(lote)}
                              disabled={reextractingId === lote.id}
                              title="Re-extrair partes do texto cru (PDFs subidos antes do deploy de capa rica)"
                            >
                              {reextractingId === lote.id ? (
                                <Loader2 className="h-4 w-4 animate-spin" />
                              ) : (
                                <RefreshCw className="h-4 w-4" />
                              )}
                            </Button>
                            <Button
                              variant="ghost"
                              size="icon"
                              onClick={() => handleReExtractAudiencias(lote)}
                              disabled={audienciasId === lote.id}
                              title="Extrair audiências do texto cru (regex mecânico — lotes antigos)"
                            >
                              {audienciasId === lote.id ? (
                                <Loader2 className="h-4 w-4 animate-spin" />
                              ) : (
                                <CalendarClock className="h-4 w-4" />
                              )}
                            </Button>
                            <Button
                              variant="ghost"
                              size="icon"
                              onClick={() => handleCleanupPedidos(lote)}
                              disabled={cleaningId === lote.id}
                              title="Limpar pedidos duplicados (lotes classificados antes do fix de duplicacao)"
                            >
                              {cleaningId === lote.id ? (
                                <Loader2 className="h-4 w-4 animate-spin" />
                              ) : (
                                <Eraser className="h-4 w-4" />
                              )}
                            </Button>
                            <Button
                              variant="ghost"
                              size="icon"
                              onClick={() => handleDelete(lote.id)}
                              disabled={
                                deletingId === lote.id ||
                                lote.status === "CLASSIFICADO"
                              }
                              title={
                                lote.status === "CLASSIFICADO"
                                  ? "Lotes classificados nao podem ser deletados"
                                  : "Apagar lote"
                              }
                            >
                              {deletingId === lote.id ? (
                                <Loader2 className="h-4 w-4 animate-spin" />
                              ) : (
                                <Trash2 className="h-4 w-4" />
                              )}
                            </Button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <div className="mt-3 flex items-center justify-between text-xs text-muted-foreground">
              <div>
                Pagina {page} de {totalPages} · Mostrando {items.length} de {total}
              </div>
              <div className="flex items-center gap-2">
                <select
                  className="rounded border bg-background px-2 py-1 text-xs"
                  value={pageSize}
                  onChange={e => {
                    setPageSize(Number(e.target.value));
                    setPage(1);
                  }}
                >
                  <option value={25}>25</option>
                  <option value={50}>50</option>
                  <option value={100}>100</option>
                </select>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page <= 1}
                  onClick={() => setPage(p => Math.max(1, p - 1))}
                >
                  Anterior
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page >= totalPages}
                  onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                >
                  Proxima
                </Button>
              </div>
            </div>
          </>
        )}
      </CardContent>

      {/* Dialogs */}
      {uploadDialogLote && (
        <UploadPdfDialog
          loteId={uploadDialogLote.id}
          loteNome={uploadDialogLote.nome}
          open={!!uploadDialogLote}
          onOpenChange={(v) => !v && setUploadDialogLote(null)}
          onUploaded={onChanged}
        />
      )}
      <LoteDetailDialog
        lote={detailDialogLote}
        open={!!detailDialogLote}
        onOpenChange={(v) => !v && setDetailDialogLote(null)}
      />
    </Card>
  );
}
