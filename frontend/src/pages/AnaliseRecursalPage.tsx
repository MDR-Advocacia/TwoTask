// Página "Análise Recursal" (dentro de Prazos Processuais).
//
// Operador sobe N PDFs de processos (nomeados pelo nº do processo),
// dispara o lote (1 chamada Sonnet/processo, ~R$0,17 cada), e vê o
// veredito de viabilidade recursal + o custo determinístico do preparo.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Scale,
  Upload,
  Loader2,
  RefreshCw,
  Trash2,
  FileText,
  AlertTriangle,
  Copy,
  Check,
  ChevronDown,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useToast } from "@/hooks/use-toast";
import {
  RecursalAnalise,
  RecursalBatch,
  deleteRecursalAnalise,
  listRecursalAnalises,
  listRecursalBatches,
  refreshRecursalBatch,
  submitRecursal,
  uploadRecursalProcesso,
} from "@/services/recursal";

const PAGE_SIZE = 25;

const STATUS_META: Record<string, { label: string; cls: string }> = {
  RECEBIDO: { label: "Aguardando análise", cls: "bg-slate-100 text-slate-700" },
  EM_ANALISE: { label: "Em análise", cls: "bg-blue-100 text-blue-700" },
  ANALISADO: { label: "Analisado", cls: "bg-emerald-100 text-emerald-700" },
  ERRO_ANALISE: { label: "Erro", cls: "bg-red-100 text-red-700" },
  SEM_TEXTO: { label: "PDF sem texto", cls: "bg-amber-100 text-amber-800" },
};

const RECORRER_META: Record<string, { label: string; cls: string }> = {
  SIM: { label: "RECORRER", cls: "bg-emerald-600 text-white" },
  NAO: { label: "NÃO RECORRER", cls: "bg-slate-500 text-white" },
  LIMITROFE: { label: "LIMÍTROFE", cls: "bg-amber-500 text-white" },
};

const REVERSAO_META: Record<string, { label: string; cls: string }> = {
  PROVAVEL: { label: "Reversão provável", cls: "bg-emerald-100 text-emerald-700" },
  POSSIVEL: { label: "Reversão possível", cls: "bg-amber-100 text-amber-800" },
  REMOTA: { label: "Reversão remota", cls: "bg-red-100 text-red-700" },
};

const RESULTADO_LABEL: Record<string, string> = {
  PROCEDENTE: "Procedente (banco perdeu)",
  IMPROCEDENTE: "Improcedente (banco venceu)",
  PARCIAL: "Parcialmente procedente",
  EXTINTO: "Extinto sem mérito",
};

const TIPO_RECURSO_LABEL: Record<string, string> = {
  APELACAO: "Apelação",
  AGRAVO: "Agravo",
  EMB_DECLARACAO: "Emb. de Declaração",
  RESP: "Recurso Especial",
  RE: "Recurso Extraordinário",
};

function formatBRL(v: number | null): string {
  if (v == null) return "—";
  return v.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

function VerdictCard({
  an,
  onDelete,
}: {
  an: RecursalAnalise;
  onDelete: (id: number) => void;
}) {
  const status = STATUS_META[an.status] ?? { label: an.status, cls: "bg-slate-100 text-slate-700" };
  const recorrer = an.recorrer ? RECORRER_META[an.recorrer] : null;
  const reversao = an.probabilidade_reversao ? REVERSAO_META[an.probabilidade_reversao] : null;
  const analisado = an.status === "ANALISADO";
  const [copied, setCopied] = useState<string | null>(null);

  const copy = (text: string | null, key: string) => {
    if (!text) return;
    navigator.clipboard.writeText(text).then(() => {
      setCopied(key);
      setTimeout(() => setCopied((c) => (c === key ? null : c)), 1500);
    });
  };

  return (
    <Card className="overflow-hidden">
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <CardTitle className="text-base font-semibold truncate">
              {an.processo_numero}
            </CardTitle>
            <CardDescription className="truncate">
              {an.cnj_number ? `CNJ ${an.cnj_number}` : an.pdf_filename_original || "—"}
              {an.uf ? ` · ${an.uf}` : ""}
            </CardDescription>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${status.cls}`}>
              {status.label}
            </span>
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7 text-slate-400 hover:text-red-600"
              onClick={() => onDelete(an.id)}
              title="Remover"
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </CardHeader>

      <CardContent className="space-y-3">
        {an.status === "SEM_TEXTO" && (
          <div className="flex items-start gap-2 rounded-md bg-amber-50 p-3 text-sm text-amber-800">
            <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
            <span>
              PDF escaneado/sem texto — não entra na análise automática. Suba uma
              versão com texto (OCR) ou trate manualmente.
            </span>
          </div>
        )}

        {an.status === "ERRO_ANALISE" && an.error_message && (
          <div className="flex items-start gap-2 rounded-md bg-red-50 p-3 text-sm text-red-700">
            <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
            <span>{an.error_message}</span>
          </div>
        )}

        {analisado && (
          <>
            <div className="flex flex-wrap items-center gap-2">
              {recorrer && (
                <span className={`rounded-md px-3 py-1 text-sm font-bold ${recorrer.cls}`}>
                  {recorrer.label}
                </span>
              )}
              {reversao && (
                <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${reversao.cls}`}>
                  {reversao.label}
                </span>
              )}
              {an.tipo_recurso && (
                <Badge variant="outline">{TIPO_RECURSO_LABEL[an.tipo_recurso] ?? an.tipo_recurso}</Badge>
              )}
              {an.confianca && (
                <span className="text-xs text-slate-400">confiança {an.confianca.toLowerCase()}</span>
              )}
            </div>

            <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
              <div>
                <span className="text-slate-500">Resultado: </span>
                <span className="font-medium">
                  {an.resultado_decisao
                    ? RESULTADO_LABEL[an.resultado_decisao] ?? an.resultado_decisao
                    : "—"}
                </span>
              </div>
              <div>
                <span className="text-slate-500">Produto: </span>
                <span className="font-medium">{an.produto || "—"}</span>
                {an.produto_categoria && an.produto_categoria !== an.produto && (
                  <span className="text-slate-400"> · {an.produto_categoria}</span>
                )}
              </div>
              <div>
                <span className="text-slate-500">Valor da causa: </span>
                <span className="font-medium">{formatBRL(an.valor_causa)}</span>
              </div>
              <div>
                <span className="text-slate-500">Custo do preparo: </span>
                {an.custo_estimado != null ? (
                  <span className="font-semibold text-slate-800">{formatBRL(an.custo_estimado)}</span>
                ) : (
                  <span
                    className="text-amber-600"
                    title="Cadastre a tabela de custas do estado para calcular"
                  >
                    custas não cadastradas
                  </span>
                )}
              </div>
            </div>

            {an.assunto && (
              <div className="rounded-md bg-slate-50 px-3 py-2 text-xs text-slate-600 break-words">
                <span className="font-medium text-slate-500">Assunto: </span>
                {an.assunto}
              </div>
            )}

            <div className="flex flex-wrap gap-2">
              <Button variant="outline" size="sm" onClick={() => copy(an.assunto, "assunto")}>
                {copied === "assunto" ? (
                  <Check className="mr-1.5 h-3.5 w-3.5" />
                ) : (
                  <Copy className="mr-1.5 h-3.5 w-3.5" />
                )}
                Copiar assunto
              </Button>
              <Button size="sm" onClick={() => copy(an.parecer_texto, "parecer")}>
                {copied === "parecer" ? (
                  <Check className="mr-1.5 h-3.5 w-3.5" />
                ) : (
                  <Copy className="mr-1.5 h-3.5 w-3.5" />
                )}
                Copiar parecer
              </Button>
            </div>

            {an.parecer_texto && (
              <details className="group">
                <summary className="flex cursor-pointer items-center gap-1 text-sm text-slate-500 hover:text-slate-700">
                  <ChevronDown className="h-4 w-4 transition-transform group-open:rotate-180" />
                  Ver parecer completo
                </summary>
                <pre className="mt-2 whitespace-pre-wrap rounded-md bg-slate-50 p-3 text-sm text-slate-700 font-sans leading-relaxed">
                  {an.parecer_texto}
                </pre>
              </details>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}

export default function AnaliseRecursalPage() {
  const { toast } = useToast();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<{ done: number; total: number } | null>(null);

  const [analises, setAnalises] = useState<RecursalAnalise[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [loading, setLoading] = useState(false);

  const [batch, setBatch] = useState<RecursalBatch | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const loadAnalises = useCallback(async () => {
    setLoading(true);
    try {
      const resp = await listRecursalAnalises({
        status: statusFilter || undefined,
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      });
      setAnalises(resp.items);
      setTotal(resp.total);
    } catch (e) {
      toast({
        variant: "destructive",
        title: "Erro ao carregar análises",
        description: e instanceof Error ? e.message : String(e),
      });
    } finally {
      setLoading(false);
    }
  }, [statusFilter, page, toast]);

  useEffect(() => {
    loadAnalises();
  }, [loadAnalises]);

  // Carrega o lote mais recente ainda não aplicado (sobrevive a reload).
  useEffect(() => {
    listRecursalBatches({ limit: 1 })
      .then((r) => {
        const b = r.items[0];
        if (b && b.applied_at == null) setBatch(b);
      })
      .catch(() => {
        /* silencioso */
      });
  }, []);

  const pendentesCount = useMemo(
    () => analises.filter((a) => a.status === "RECEBIDO").length,
    [analises],
  );

  const handleFilesPicked = (e: React.ChangeEvent<HTMLInputElement>) => {
    setSelectedFiles(Array.from(e.target.files ?? []));
  };

  const handleUpload = async () => {
    if (selectedFiles.length === 0) return;
    setUploading(true);
    setUploadProgress({ done: 0, total: selectedFiles.length });
    let ok = 0;
    let already = 0;
    let semTexto = 0;
    const erros: string[] = [];
    for (let i = 0; i < selectedFiles.length; i++) {
      const f = selectedFiles[i];
      try {
        const r = await uploadRecursalProcesso(f);
        if (r.already_existed) already++;
        else if (r.status === "SEM_TEXTO") semTexto++;
        else ok++;
      } catch (e) {
        erros.push(`${f.name}: ${e instanceof Error ? e.message : String(e)}`);
      }
      setUploadProgress({ done: i + 1, total: selectedFiles.length });
    }
    setUploading(false);
    setUploadProgress(null);
    setSelectedFiles([]);
    if (fileInputRef.current) fileInputRef.current.value = "";

    const partes = [
      ok ? `${ok} pronto(s)` : null,
      semTexto ? `${semTexto} sem texto` : null,
      already ? `${already} já existia(m)` : null,
      erros.length ? `${erros.length} com erro` : null,
    ].filter(Boolean);
    toast({
      title: "Upload concluído",
      description: partes.join(" · ") || "Nenhum arquivo.",
      variant: erros.length ? "destructive" : "default",
    });
    setPage(0);
    loadAnalises();
  };

  const handleSubmit = async () => {
    setSubmitting(true);
    try {
      const r = await submitRecursal();
      setBatch(r.batch);
      toast({
        title: "Lote enviado",
        description: `${r.submetidos} processo(s) em análise. O resultado fica pronto em alguns minutos a algumas horas — clique em "Atualizar resultado".`,
      });
      loadAnalises();
    } catch (e) {
      toast({
        variant: "destructive",
        title: "Não foi possível enviar o lote",
        description: e instanceof Error ? e.message : String(e),
      });
    } finally {
      setSubmitting(false);
    }
  };

  const handleRefresh = async () => {
    if (!batch) return;
    setRefreshing(true);
    try {
      const r = await refreshRecursalBatch(batch.id);
      setBatch(r.batch);
      if (r.summary) {
        toast({
          title: "Resultados aplicados",
          description: `${r.summary.succeeded} analisado(s), ${r.summary.failed} com erro.`,
        });
        if (r.batch.applied_at) setBatch(null);
        loadAnalises();
      } else {
        toast({
          title: "Ainda processando",
          description: `Status: ${r.batch.anthropic_status ?? r.batch.status}. Tente de novo em instantes.`,
        });
      }
    } catch (e) {
      toast({
        variant: "destructive",
        title: "Erro ao atualizar",
        description: e instanceof Error ? e.message : String(e),
      });
    } finally {
      setRefreshing(false);
    }
  };

  const handleDelete = async (id: number) => {
    try {
      await deleteRecursalAnalise(id);
      loadAnalises();
    } catch (e) {
      toast({
        variant: "destructive",
        title: "Erro ao remover",
        description: e instanceof Error ? e.message : String(e),
      });
    }
  };

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const STATUS_OPTIONS: Array<{ value: string; label: string }> = [
    { value: "", label: "Todos" },
    { value: "RECEBIDO", label: "Aguardando" },
    { value: "EM_ANALISE", label: "Em análise" },
    { value: "ANALISADO", label: "Analisados" },
    { value: "SEM_TEXTO", label: "Sem texto" },
    { value: "ERRO_ANALISE", label: "Erro" },
  ];

  return (
    <div className="container mx-auto p-6 space-y-6">
      <div className="flex items-center gap-3">
        <Scale className="h-7 w-7 text-slate-700" />
        <div>
          <h1 className="text-2xl font-bold">Análise Recursal</h1>
          <p className="text-sm text-slate-500">
            Suba os PDFs dos processos (nomeados pelo nº do processo). A IA avalia
            a viabilidade de recurso do Banco Master e estima o custo do preparo.
          </p>
        </div>
      </div>

      {/* Upload */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">1. Enviar processos</CardTitle>
          <CardDescription>
            Selecione um ou vários PDFs. O nome do arquivo é usado como número do
            processo.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap items-center gap-3">
            <input
              ref={fileInputRef}
              type="file"
              accept="application/pdf"
              multiple
              onChange={handleFilesPicked}
              className="text-sm file:mr-3 file:rounded-md file:border-0 file:bg-slate-100 file:px-3 file:py-2 file:text-sm file:font-medium hover:file:bg-slate-200"
            />
            <Button onClick={handleUpload} disabled={uploading || selectedFiles.length === 0}>
              {uploading ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Upload className="mr-2 h-4 w-4" />
              )}
              {uploading
                ? uploadProgress
                  ? `Enviando ${uploadProgress.done}/${uploadProgress.total}…`
                  : "Enviando…"
                : `Enviar ${selectedFiles.length || ""} PDF(s)`}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Disparo do lote */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">2. Analisar</CardTitle>
          <CardDescription>
            Dispara a análise dos processos aguardando (~R$0,17 por processo, em lote).
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center gap-3">
          <Button onClick={handleSubmit} disabled={submitting}>
            {submitting ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <FileText className="mr-2 h-4 w-4" />
            )}
            Analisar pendentes
          </Button>

          {batch && (
            <div className="flex items-center gap-3 rounded-md bg-slate-50 px-3 py-2 text-sm">
              <span className="text-slate-600">
                Lote #{batch.id} · {batch.total_records} processo(s) ·{" "}
                <span className="font-medium">{batch.anthropic_status ?? batch.status}</span>
              </span>
              <Button
                variant="outline"
                size="sm"
                onClick={handleRefresh}
                disabled={refreshing}
              >
                {refreshing ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <RefreshCw className="mr-2 h-4 w-4" />
                )}
                Atualizar resultado
              </Button>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Filtros + lista */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          {STATUS_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              onClick={() => {
                setStatusFilter(opt.value);
                setPage(0);
              }}
              className={`rounded-full px-3 py-1 text-sm ${
                statusFilter === opt.value
                  ? "bg-slate-800 text-white"
                  : "bg-slate-100 text-slate-600 hover:bg-slate-200"
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
        <span className="text-sm text-slate-500">
          {total} resultado(s){pendentesCount ? ` · ${pendentesCount} aguardando nesta página` : ""}
        </span>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-12 text-slate-400">
          <Loader2 className="h-6 w-6 animate-spin" />
        </div>
      ) : analises.length === 0 ? (
        <div className="rounded-lg border border-dashed py-12 text-center text-slate-400">
          Nenhum processo. Suba PDFs acima para começar.
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {analises.map((an) => (
            <VerdictCard key={an.id} an={an} onDelete={handleDelete} />
          ))}
        </div>
      )}

      {/* Paginação */}
      {total > PAGE_SIZE && (
        <div className="flex items-center justify-center gap-4 pt-2">
          <Button
            variant="outline"
            size="sm"
            disabled={page === 0}
            onClick={() => setPage((p) => Math.max(0, p - 1))}
          >
            Anterior
          </Button>
          <span className="text-sm text-slate-500">
            Página {page + 1} de {totalPages}
          </span>
          <Button
            variant="outline"
            size="sm"
            disabled={page + 1 >= totalPages}
            onClick={() => setPage((p) => p + 1)}
          >
            Próxima
          </Button>
        </div>
      )}
    </div>
  );
}
