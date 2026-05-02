import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  AlertCircle,
  CalendarClock,
  CheckCircle2,
  Cpu,
  ExternalLink,
  FileDown,
  FileText,
  Filter,
  Loader2,
  Play,
  RefreshCw,
  RotateCcw,
  Search,
  Sparkles,
  Undo2,
  Workflow,
  XCircle,
} from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
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
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { MultiSelect } from "@/components/ui/MultiSelect";
import { Separator } from "@/components/ui/separator";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useToast } from "@/hooks/use-toast";
import { apiFetch } from "@/lib/api-client";
import {
  naturezaLabel,
  produtoLabel,
  tipoPrazoLabel,
} from "@/lib/prazos-iniciais-labels";
import {
  applyPrazosIniciaisBatch,
  cancelarPrazoInicial,
  reclassifyPrazoInicial,
  confirmarAgendamentoPrazoInicial,
  dispatchPrazoInicialPendingBatch,
  dispatchPrazoInicialTreatmentWeb,
  fetchPrazoInicialDetail,
  deletePrazoInicialIntake,
  fetchPrazosIniciaisBatches,
  fetchPrazosIniciaisEnums,
  fetchPrazosIniciaisIntakes,
  finalizarPrazoInicialSemProvidencia,
  reanalyzePrazoInicial,
  exportPrazosIniciaisXlsx,
  fetchPrazoInicialPdfBlob,
  reapplyPrazosIniciaisTemplates,
  recomputePrazoInicialGlobals,
  refreshPrazosIniciaisBatch,
  reprocessarPrazoInicialCnj,
  submitPrazosIniciaisClassifyPending,
  type ReapplyTemplatesResult,
} from "@/services/api";
import { useAuth } from "@/hooks/useAuth";
import type {
  PrazoInicialBatchSummary,
  PrazoInicialEnums,
  PrazoInicialIntakeDetail,
  PrazoInicialIntakeStatus,
  PrazoInicialIntakeSummary,
  PrazoInicialSugestao,
} from "@/types/api";

const PAGE_SIZE = 25;

const STATUS_OPTIONS: { value: string; label: string }[] = [
  { value: "__all__", label: "Todos os status" },
  { value: "RECEBIDO", label: "Recebido" },
  { value: "PROCESSO_NAO_ENCONTRADO", label: "Processo nao encontrado" },
  { value: "PRONTO_PARA_CLASSIFICAR", label: "Pronto para classificar" },
  { value: "EM_CLASSIFICACAO", label: "Em classificacao" },
  { value: "CLASSIFICADO", label: "Classificado" },
  { value: "AGUARDANDO_CONFIG_TEMPLATE", label: "Aguardando config de template" },
  { value: "EM_REVISAO", label: "Em revisao" },
  { value: "AGENDADO", label: "Agendado" },
  { value: "CONCLUIDO_SEM_PROVIDENCIA", label: "Concluido sem providencia" },
  { value: "GED_ENVIADO", label: "GED enviado" },
  { value: "CONCLUIDO", label: "Concluido" },
  { value: "ERRO_CLASSIFICACAO", label: "Erro na classificacao" },
  { value: "ERRO_AGENDAMENTO", label: "Erro no agendamento" },
  { value: "ERRO_GED", label: "Erro no GED" },
  { value: "CANCELADO", label: "Cancelado" },
];

const STATUS_LABEL: Record<string, string> = Object.fromEntries(
  STATUS_OPTIONS.filter((option) => option.value !== "__all__").map((option) => [option.value, option.label]),
);

const CONFIRMABLE_STATUSES = new Set(["EM_REVISAO", "CLASSIFICADO", "AGENDADO", "ERRO_AGENDAMENTO"]);

const REVIEW_LABEL: Record<string, string> = {
  pendente: "Pendente",
  aprovado: "Aprovado",
  rejeitado: "Rejeitado",
  editado: "Editado",
};

function statusBadgeVariant(status: PrazoInicialIntakeStatus): "default" | "secondary" | "destructive" | "outline" {
  if (status.startsWith("ERRO_")) return "destructive";
  if (status === "CANCELADO") return "outline";
  if (status === "CONCLUIDO" || status === "AGENDADO" || status === "GED_ENVIADO") {
    return "default";
  }
  return "secondary";
}

function reviewBadgeClass(reviewStatus: string) {
  const styles: Record<string, string> = {
    pendente: "bg-amber-100 text-amber-800",
    aprovado: "bg-green-100 text-green-800",
    rejeitado: "bg-red-100 text-red-800",
    editado: "bg-blue-100 text-blue-800",
  };
  return styles[reviewStatus] || "bg-slate-100 text-slate-700";
}

function formatCnj(cnj: string | null | undefined): string {
  if (!cnj) return "-";
  const digits = cnj.replace(/\D/g, "");
  if (digits.length === 20) {
    return `${digits.slice(0, 7)}-${digits.slice(7, 9)}.${digits.slice(9, 13)}.${digits.slice(13, 14)}.${digits.slice(14, 16)}.${digits.slice(16, 20)}`;
  }
  return cnj;
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "-";
  try {
    return new Intl.DateTimeFormat("pt-BR", {
      dateStyle: "short",
      timeStyle: "short",
      timeZone: "America/Fortaleza",
    }).format(new Date(value));
  } catch {
    return value;
  }
}

function formatDate(value: string | null | undefined): string {
  if (!value) return "-";
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    const [year, month, day] = value.split("-").map(Number);
    return new Intl.DateTimeFormat("pt-BR", {
      dateStyle: "short",
      timeZone: "America/Fortaleza",
    }).format(new Date(year, month - 1, day, 12, 0, 0));
  }
  return formatDateTime(value);
}

function formatBytes(bytes: number | null | undefined): string {
  if (!bytes || bytes <= 0) return "-";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function formatSuggestionDeadline(suggestion: PrazoInicialSugestao): string {
  if (suggestion.data_final_calculada) {
    const prazoLabel = suggestion.prazo_dias ? `${suggestion.prazo_dias} ${suggestion.prazo_tipo || ""}`.trim() : "-";
    return `${prazoLabel} ate ${formatDate(suggestion.data_final_calculada)}`;
  }
  if (suggestion.audiencia_data) {
    const hour = suggestion.audiencia_hora ? ` as ${String(suggestion.audiencia_hora).slice(0, 5)}` : "";
    return `Audiencia em ${formatDate(suggestion.audiencia_data)}${hour}`;
  }
  if (suggestion.prazo_dias) {
    return `${suggestion.prazo_dias} ${suggestion.prazo_tipo || ""}`.trim();
  }
  return "-";
}

function getPrimeiroPoloPassivo(detail: Pick<PrazoInicialIntakeDetail, "capa_json">): string {
  const polos = detail.capa_json?.polo_passivo || [];
  return polos[0]?.nome || "-";
}

function isConfirmableStatus(status: string): boolean {
  return CONFIRMABLE_STATUSES.has(status);
}

export default function PrazosIniciaisPage() {
  const { toast } = useToast();
  const { isAdmin } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();

  // Filtros - os "appliedXxx" são os que efetivamente vão pro GET, os
  // "xxxFilter" são os que o operador está editando antes de clicar "Aplicar".
  // Multi-select filtros guardam CSV (ex "CLASSIFICADO,AGENDADO").
  const [statusFilter, setStatusFilter] = useState("");           // CSV
  const [cnjFilter, setCnjFilter] = useState("");
  const [officeFilter, setOfficeFilter] = useState("");           // CSV de ids
  const [naturezaFilter, setNaturezaFilter] = useState("");       // CSV
  const [produtoFilter, setProdutoFilter] = useState("");         // CSV
  const [probExitoFilter, setProbExitoFilter] = useState("");     // CSV
  const [dateFromFilter, setDateFromFilter] = useState("");
  const [dateToFilter, setDateToFilter] = useState("");
  const [hasErrorFilter, setHasErrorFilter] = useState<"__all__" | "com" | "sem">("__all__");

  const [appliedStatus, setAppliedStatus] = useState("");
  const [appliedCnj, setAppliedCnj] = useState("");
  const [appliedOffice, setAppliedOffice] = useState("");
  const [appliedNatureza, setAppliedNatureza] = useState("");
  const [appliedProduto, setAppliedProduto] = useState("");
  const [appliedProbExito, setAppliedProbExito] = useState("");
  const [appliedDateFrom, setAppliedDateFrom] = useState("");
  const [appliedDateTo, setAppliedDateTo] = useState("");
  const [appliedHasError, setAppliedHasError] = useState<"__all__" | "com" | "sem">("__all__");
  const [offset, setOffset] = useState(0);

  const [items, setItems] = useState<PrazoInicialIntakeSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<PrazoInicialIntakeDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState(false);

  const [selectedSuggestions, setSelectedSuggestions] = useState<Record<number, boolean>>({});
  const [createdTaskIds, setCreatedTaskIds] = useState<Record<number, string>>({});

  // Enums (naturezas, produtos, etc.) pra popular os MultiSelects dos filtros.
  // Carregado 1x no mount — valores vêm do /api/v1/prazos-iniciais/enums.
  const [enums, setEnums] = useState<PrazoInicialEnums | null>(null);

  // Cadastro de escritórios (LegalOneOffice). Usado pra traduzir office_id
  // do intake/detail pro path hierárquico humano (ex: "MDR Advocacia /
  // Área operacional / Banco Master / Réu"). Carregado 1x no mount.
  const [offices, setOffices] = useState<
    Array<{ id: number; external_id: number; name: string; path: string | null }>
  >([]);

  // Resolve office_id → rótulo humano. Prefere o path completo; cai pro
  // name quando o path está vazio; cai pro id quando o escritório não
  // foi carregado ainda.
  const officeLabel = useCallback(
    (id: number | null | undefined): string => {
      if (!id) return "—";
      const office = offices.find((o) => o.external_id === id);
      if (!office) return `#${id}`;
      return office.path || office.name || `#${id}`;
    },
    [offices],
  );

  // Classificação em batch (Sonnet) — Onda 1 manual.
  const [batches, setBatches] = useState<PrazoInicialBatchSummary[]>([]);
  const [batchesLoading, setBatchesLoading] = useState(false);
  const [classifyingPending, setClassifyingPending] = useState(false);
  const [batchActionId, setBatchActionId] = useState<number | null>(null);

  // Reaplicar templates em lote — re-roda match_templates nas sugestoes
  // existentes sem chamar IA. Usado quando operador cadastra/edita
  // template novo e quer aplicar no backlog.
  const [reapplyDialogOpen, setReapplyDialogOpen] = useState(false);
  const [reapplyStatuses, setReapplyStatuses] = useState<string[]>([
    "AGUARDANDO_CONFIG_TEMPLATE",
  ]);
  const [reapplyDryRunResult, setReapplyDryRunResult] =
    useState<ReapplyTemplatesResult | null>(null);
  const [reapplyDryRunLoading, setReapplyDryRunLoading] = useState(false);
  const [reapplyConfirmLoading, setReapplyConfirmLoading] = useState(false);

  const loadIntakes = useCallback(
    async (resetPage = false) => {
      setIsLoading(true);
      setLoadError(null);
      try {
        const nextOffset = resetPage ? 0 : offset;
        const has_error =
          appliedHasError === "com" ? true
          : appliedHasError === "sem" ? false
          : undefined;
        const payload = await fetchPrazosIniciaisIntakes({
          status: appliedStatus || undefined,
          cnj_number: appliedCnj || undefined,
          office_id: appliedOffice || undefined,
          natureza_processo: appliedNatureza || undefined,
          produto: appliedProduto || undefined,
          probabilidade_exito_global: appliedProbExito || undefined,
          date_from: appliedDateFrom || undefined,
          date_to: appliedDateTo || undefined,
          has_error,
          limit: PAGE_SIZE,
          offset: nextOffset,
        });
        setItems(payload.items);
        setTotal(payload.total);
        if (resetPage) setOffset(0);
      } catch (error) {
        setLoadError(error instanceof Error ? error.message : "Erro ao carregar intakes.");
      } finally {
        setIsLoading(false);
      }
    },
    [
      appliedCnj, appliedStatus, appliedOffice, appliedNatureza,
      appliedProduto, appliedProbExito, appliedDateFrom, appliedDateTo,
      appliedHasError, offset,
    ],
  );

  const loadDetail = useCallback(async (intakeId: number) => {
    setDetailLoading(true);
    setDetailError(null);
    setDetail(null);
    try {
      const payload = await fetchPrazoInicialDetail(intakeId);
      setDetail(payload);
    } catch (error) {
      setDetailError(error instanceof Error ? error.message : "Erro ao carregar o detalhe do intake.");
    } finally {
      setDetailLoading(false);
    }
  }, []);

  useEffect(() => {
    loadIntakes();
  }, [loadIntakes]);

  useEffect(() => {
    if (selectedId === null) {
      setDetail(null);
      setDetailError(null);
      return;
    }
    loadDetail(selectedId);
  }, [loadDetail, selectedId]);

  // Deep-link: ?intake=<id> abre o dialog do intake direto. Útil pros links
  // vindos da Treatment Page ou de logs/Slack — não precisa o usuário caçar
  // o item na lista paginada.
  useEffect(() => {
    const raw = searchParams.get("intake");
    if (!raw) return;
    const parsed = Number(raw);
    if (!Number.isFinite(parsed) || parsed <= 0) return;
    setSelectedId(parsed);
    // Limpa o param da URL pra não reabrir ao fechar o dialog ou em re-renders.
    const next = new URLSearchParams(searchParams);
    next.delete("intake");
    setSearchParams(next, { replace: true });
  }, [searchParams, setSearchParams]);

  useEffect(() => {
    if (!detail) {
      setSelectedSuggestions({});
      setCreatedTaskIds({});
      return;
    }

    const nextSelection: Record<number, boolean> = {};
    const nextCreatedTaskIds: Record<number, string> = {};

    detail.sugestoes.forEach((suggestion) => {
      nextSelection[suggestion.id] = suggestion.review_status !== "rejeitado";
      nextCreatedTaskIds[suggestion.id] = suggestion.created_task_id ? String(suggestion.created_task_id) : "";
    });

    setSelectedSuggestions(nextSelection);
    setCreatedTaskIds(nextCreatedTaskIds);
  }, [detail]);

  const pageInfo = useMemo(() => {
    const start = total === 0 ? 0 : offset + 1;
    const end = Math.min(offset + PAGE_SIZE, total);
    return {
      start,
      end,
      hasPrev: offset > 0,
      hasNext: offset + PAGE_SIZE < total,
    };
  }, [offset, total]);

  const selectedSuggestionCount = useMemo(() => {
    if (!detail) return 0;
    return detail.sugestoes.filter((suggestion) => selectedSuggestions[suggestion.id]).length;
  }, [detail, selectedSuggestions]);

  const canConfirmScheduling = Boolean(
    detail &&
      isConfirmableStatus(detail.status) &&
      detail.sugestoes.length > 0 &&
      selectedSuggestionCount > 0 &&
      !actionLoading,
  );

  const onAplicarFiltros = () => {
    setAppliedStatus(statusFilter);
    setAppliedCnj(cnjFilter.trim());
    setAppliedOffice(officeFilter);
    setAppliedNatureza(naturezaFilter);
    setAppliedProduto(produtoFilter);
    setAppliedProbExito(probExitoFilter);
    setAppliedDateFrom(dateFromFilter);
    setAppliedDateTo(dateToFilter);
    setAppliedHasError(hasErrorFilter);
    setOffset(0);
  };

  const onLimparFiltros = () => {
    setStatusFilter("");
    setCnjFilter("");
    setOfficeFilter("");
    setNaturezaFilter("");
    setProdutoFilter("");
    setProbExitoFilter("");
    setDateFromFilter("");
    setDateToFilter("");
    setHasErrorFilter("__all__");
    setAppliedStatus("");
    setAppliedCnj("");
    setAppliedOffice("");
    setAppliedNatureza("");
    setAppliedProduto("");
    setAppliedProbExito("");
    setAppliedDateFrom("");
    setAppliedDateTo("");
    setAppliedHasError("__all__");
    setOffset(0);
  };

  const onReanalisar = async () => {
    if (!detail) return;
    if (
      !confirm(
        `Reanalisar intake #${detail.id}?\n\n` +
          "Isso apaga sugestões e pedidos atuais e reenvia o processo para\n" +
          "classificação na próxima janela de batch. Útil para popular os\n" +
          "campos novos (pedidos + aprovisionamento + análise estratégica)\n" +
          "em intakes classificados antes da última atualização.",
      )
    ) {
      return;
    }
    setActionLoading(true);
    try {
      await reanalyzePrazoInicial(detail.id);
      toast({
        title: "Reanalise iniciada",
        description: `Intake #${detail.id} será reclassificado no próximo batch.`,
      });
      await loadDetail(detail.id);
      await loadIntakes();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Erro desconhecido";
      toast({ title: "Erro", description: msg, variant: "destructive" });
    } finally {
      setActionLoading(false);
    }
  };

  // Onda 3 #5 — Disparo do tratamento web (GED + cancel da legada) de
  // um intake AGENDADO/CONCLUIDO_SEM_PROVIDENCIA com dispatch_pending=true.
  // Idempotente: backend retorna skipped:true se já foi disparado.
  const [dispatchingIntakeId, setDispatchingIntakeId] = useState<number | null>(
    null,
  );
  const [isBatchDispatching, setIsBatchDispatching] = useState(false);

  const onDispatchIntake = async (intakeId: number) => {
    setDispatchingIntakeId(intakeId);
    try {
      const result = await dispatchPrazoInicialTreatmentWeb(intakeId);
      if (result.skipped) {
        toast({
          title: "Já disparado",
          description: result.reason || "Intake não estava pendente.",
        });
      } else {
        toast({
          title: "Disparo concluído",
          description: `Intake #${intakeId}: GED enviado e cancel da legada enfileirado.`,
        });
      }
      await loadIntakes();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Erro desconhecido";
      toast({
        title: "Falha no disparo",
        description: msg,
        variant: "destructive",
      });
    } finally {
      setDispatchingIntakeId(null);
    }
  };

  const onDispatchPendingBatch = async () => {
    setIsBatchDispatching(true);
    try {
      const result = await dispatchPrazoInicialPendingBatch(10);
      const lines = [
        `${result.success_count} disparado(s)`,
        result.skipped_count ? `${result.skipped_count} já disparado(s)` : null,
        result.failure_count ? `${result.failure_count} falha(s)` : null,
      ].filter(Boolean);
      toast({
        title: "Disparo em lote",
        description:
          `${result.candidates} candidato(s). ${lines.join(" · ")}` +
          (result.failure_count
            ? `\n\nFalhas: ${result.failed
                .map((f) => `#${f.intake_id}: ${f.error}`)
                .join(" | ")}`
            : ""),
        variant: result.failure_count ? "destructive" : "default",
      });
      await loadIntakes();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Erro desconhecido";
      toast({
        title: "Falha ao disparar lote",
        description: msg,
        variant: "destructive",
      });
    } finally {
      setIsBatchDispatching(false);
    }
  };

  // HARD DELETE — admin only. Apaga intake + cascata + PDF fisico. Usado
  // pra reinjetar o mesmo processo do zero durante testes. Vai virar
  // arquivamento (soft delete) depois.
  const onDeleteIntake = async () => {
    if (!detail) return;
    if (
      !confirm(
        `DELETAR intake #${detail.id} (${detail.cnj_number || "sem CNJ"})?\n\n` +
          "Esta ação é IRREVERSÍVEL e remove o registro, sugestões, pedidos\n" +
          "e PDF do disco. Use apenas em ambiente de teste.",
      )
    ) {
      return;
    }
    setActionLoading(true);
    try {
      await deletePrazoInicialIntake(detail.id);
      toast({
        title: "Intake deletado",
        description: `Intake #${detail.id} removido permanentemente.`,
      });
      setSelectedId(null);
      await loadIntakes();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Erro desconhecido";
      toast({ title: "Erro ao deletar", description: msg, variant: "destructive" });
    } finally {
      setActionLoading(false);
    }
  };

  // Finaliza o intake sem criar tarefa no L1 (Caminho A). Sobe habilitação
  // pro GED, cancela task legada, marca CONCLUIDO_SEM_PROVIDENCIA. Usado
  // quando operador determina que o processo não exige providência do
  // banco (sentença improcedente transitada, arquivamento, etc.).
  const onFinalizeWithoutProvidence = async () => {
    if (!detail) return;
    const isRetry = detail.status === "CONCLUIDO_SEM_PROVIDENCIA";
    const promptTitle = isRetry
      ? `Retentar finalização do intake #${detail.id}?`
      : `Finalizar intake #${detail.id} SEM criar tarefa no Legal One?`;
    const promptBody = isRetry
      ? "O intake já está CONCLUIDO_SEM_PROVIDENCIA. Reexecutar os passos pode\n" +
        "ajudar se algum falhou na primeira vez (ex.: GED upload, cancelamento\n" +
        "da legada). Idempotente — passos já concluídos são pulados.\n\n" +
        "Opcional: digite um motivo da retentativa abaixo."
      : "Isso vai:\n" +
        "  • Subir a habilitação pro GED do processo no L1\n" +
        "  • Cancelar a task legada 'Agendar Prazos'\n" +
        "  • Marcar o intake como CONCLUIDO_SEM_PROVIDENCIA\n\n" +
        "Opcional: digite um motivo abaixo (aparece na trilha de auditoria) " +
        "ou deixe vazio e clique OK pra confirmar. Cancelar interrompe a ação.";
    const notes = window.prompt(`${promptTitle}\n\n${promptBody}`, "");
    if (notes === null) return;  // usuário apertou Cancel

    setActionLoading(true);
    try {
      await finalizarPrazoInicialSemProvidencia(detail.id, {
        notes: notes.trim() || null,
      });
      toast({
        title: "Intake finalizado sem providência",
        description:
          "Habilitação enviada ao GED, task legada entrou na fila de cancelamento.",
      });
      await Promise.all([loadDetail(detail.id), loadIntakes()]);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Erro desconhecido";
      toast({
        title: "Falha ao finalizar",
        description: msg,
        variant: "destructive",
        duration: 15000,
      });
    } finally {
      setActionLoading(false);
    }
  };

  // Baixa o PDF da habilitação autenticado (via apiFetch) e abre numa nova
  // aba usando Object URL. Anchor <a href target="_blank"> direto nao
  // funciona porque o browser nao envia o header Authorization do JWT em
  // navegacoes — resultado seria 401 'Not authenticated'.
  const onOpenPdfInNewTab = async () => {
    if (!detail) return;
    try {
      const blob = await fetchPrazoInicialPdfBlob(detail.id);
      const objectUrl = URL.createObjectURL(blob);
      // Abre e agenda revoke depois de um tempinho (browser ainda precisa
      // carregar o conteúdo antes de revogarmos).
      window.open(objectUrl, "_blank", "noopener,noreferrer");
      setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Erro desconhecido";
      toast({
        title: "Falha ao abrir PDF",
        description: msg,
        variant: "destructive",
      });
    }
  };

  // Recalcula agregados globais (valor total, aprovisionamento, prob. êxito)
  // a partir dos pedidos atuais. Não reprocessa no Sonnet — é barato e
  // idempotente. Útil pra corrigir intakes órfãos de apply antigo.
  const onRecomputeGlobals = async () => {
    if (!detail) return;
    setActionLoading(true);
    try {
      const result = await recomputePrazoInicialGlobals(detail.id);
      toast({
        title: "Totais recalculados",
        description:
          result.pedidos_count > 0
            ? `${result.pedidos_count} pedido(s) somados. Prob. êxito: ${result.probabilidade_exito_global ?? "—"}.`
            : "Sem pedidos pra agregar — valores ficaram em branco.",
      });
      await loadDetail(detail.id);
      await loadIntakes();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Erro desconhecido";
      toast({ title: "Erro ao recalcular", description: msg, variant: "destructive" });
    } finally {
      setActionLoading(false);
    }
  };

  const onExportXlsx = async () => {
    try {
      const blob = await exportPrazosIniciaisXlsx({
        status: appliedStatus !== "__all__" ? appliedStatus : undefined,
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const ts = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 16);
      a.download = `prazos_iniciais_${ts}.xlsx`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      toast({ title: "Erro ao exportar", description: msg, variant: "destructive" });
    }
  };

  const onReprocessarCnj = useCallback(async () => {
    if (!selectedId) return;
    setActionLoading(true);
    try {
      await reprocessarPrazoInicialCnj(selectedId);
      toast({
        title: "Reprocessamento solicitado",
        description: "A resolucao do CNJ no Legal One foi reiniciada em background.",
      });
      await Promise.all([loadDetail(selectedId), loadIntakes()]);
    } catch (error) {
      toast({
        title: "Erro ao reprocessar",
        description: error instanceof Error ? error.message : "Nao foi possivel reprocessar o intake.",
        variant: "destructive",
      });
    } finally {
      setActionLoading(false);
    }
  }, [loadDetail, loadIntakes, selectedId, toast]);

  const onReclassify = useCallback(async () => {
    if (!selectedId) return;
    const confirmed = window.confirm(
      "Reclassificar este intake? Todas as sugestoes e pedidos atuais serao APAGADOS, " +
      "e o intake voltara pra fila de classificacao no proximo batch. Util pra casos antigos " +
      "com SEM_DETERMINACAO ou pra reclassificar depois de ajustar templates/integra.",
    );
    if (!confirmed) return;

    setActionLoading(true);
    try {
      await reclassifyPrazoInicial(selectedId);
      toast({
        title: "Reclassificacao solicitada",
        description: "Sugestoes e pedidos antigos foram apagados. O intake entra no proximo batch de classificacao.",
      });
      await Promise.all([loadDetail(selectedId), loadIntakes()]);
    } catch (error) {
      toast({
        title: "Erro ao reclassificar",
        description: error instanceof Error ? error.message : "Nao foi possivel reclassificar o intake.",
        variant: "destructive",
      });
    } finally {
      setActionLoading(false);
    }
  }, [loadDetail, loadIntakes, selectedId, toast]);

  const onCancelar = useCallback(async () => {
    if (!selectedId) return;
    const confirmed = window.confirm(
      "Cancelar este intake? A automacao nao podera mais seguir com o fluxo de agendamentos iniciais para esse registro.",
    );
    if (!confirmed) return;

    setActionLoading(true);
    try {
      await cancelarPrazoInicial(selectedId);
      toast({
        title: "Intake cancelado",
        description: "O registro foi marcado como CANCELADO.",
      });
      await Promise.all([loadDetail(selectedId), loadIntakes()]);
    } catch (error) {
      toast({
        title: "Erro ao cancelar",
        description: error instanceof Error ? error.message : "Nao foi possivel cancelar o intake.",
        variant: "destructive",
      });
    } finally {
      setActionLoading(false);
    }
  }, [loadDetail, loadIntakes, selectedId, toast]);

  const setAllSuggestions = useCallback(
    (checked: boolean) => {
      if (!detail) return;
      const next: Record<number, boolean> = {};
      detail.sugestoes.forEach((suggestion) => {
        next[suggestion.id] = checked;
      });
      setSelectedSuggestions(next);
    },
    [detail],
  );

  const onConfirmarAgendamentos = useCallback(async () => {
    if (!selectedId || !detail) return;

    const selectedPayload: Array<{
      suggestion_id: number;
      created_task_id: number | null;
      review_status: string;
    }> = [];

    for (const suggestion of detail.sugestoes) {
      if (!selectedSuggestions[suggestion.id]) continue;

      const rawCreatedTaskId = createdTaskIds[suggestion.id]?.trim();
      let parsedCreatedTaskId: number | null = null;

      if (rawCreatedTaskId) {
        if (!/^\d+$/.test(rawCreatedTaskId)) {
          toast({
            title: "Task criada invalida",
            description: `A sugestao ${suggestion.id} precisa de um numero inteiro valido em task criada.`,
            variant: "destructive",
          });
          return;
        }
        parsedCreatedTaskId = Number.parseInt(rawCreatedTaskId, 10);
      }

      const reviewStatus =
        parsedCreatedTaskId !== null && parsedCreatedTaskId !== suggestion.created_task_id
          ? "editado"
          : suggestion.review_status === "editado"
            ? "editado"
            : "aprovado";

      selectedPayload.push({
        suggestion_id: suggestion.id,
        created_task_id: parsedCreatedTaskId,
        review_status: reviewStatus,
      });
    }

    if (selectedPayload.length === 0) {
      toast({
        title: "Nenhuma sugestao selecionada",
        description: "Selecione pelo menos uma sugestao para confirmar os agendamentos do intake.",
        variant: "destructive",
      });
      return;
    }

    setActionLoading(true);
    try {
      const response = await confirmarAgendamentoPrazoInicial(selectedId, {
        suggestions: selectedPayload,
        enqueue_legacy_task_cancellation: true,
      });

      const queueItem = response.legacy_task_cancellation_item;
      toast({
        title: "Agendamentos confirmados",
        description: queueItem
          ? `Intake em AGENDADO e item #${queueItem.id} entrou na fila tecnica para cancelar a task legada.`
          : "Intake atualizado para AGENDADO com sucesso.",
      });

      await Promise.all([loadDetail(selectedId), loadIntakes()]);
    } catch (error) {
      toast({
        title: "Falha ao confirmar agendamentos",
        description: error instanceof Error ? error.message : "Nao foi possivel confirmar os agendamentos.",
        variant: "destructive",
      });
    } finally {
      setActionLoading(false);
    }
  }, [createdTaskIds, detail, loadDetail, loadIntakes, selectedId, selectedSuggestions, toast]);

  // ─── Classificação em batch (Sonnet) — controlada manualmente ─────────

  const loadBatches = useCallback(async () => {
    setBatchesLoading(true);
    try {
      const response = await fetchPrazosIniciaisBatches(20);
      setBatches(response.items);
    } catch (error) {
      // Falhar silenciosamente — a tela principal continua funcionando
      // sem a listagem de batches. O erro já aparece no console.
      console.warn("Falha ao carregar batches de prazos iniciais", error);
    } finally {
      setBatchesLoading(false);
    }
  }, []);

  useEffect(() => {
    loadBatches();
  }, [loadBatches]);

  // Carrega enums 1x no mount. Usado pra popular os MultiSelects de
  // Natureza/Produto/Probabilidade nos filtros.
  useEffect(() => {
    let cancelled = false;
    fetchPrazosIniciaisEnums()
      .then((e) => { if (!cancelled) setEnums(e); })
      .catch((err) => {
        console.warn("Falha ao carregar enums de prazos iniciais:", err);
      });
    return () => { cancelled = true; };
  }, []);

  // Carrega cadastro de escritórios 1x no mount. Usado pra traduzir
  // office_id em path no modal de detalhes do intake. Silencioso em
  // falha — sem crashar a tela (cai no fallback "#id").
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await apiFetch("/api/v1/offices");
        if (!res.ok) return;
        const data = await res.json();
        if (!cancelled && Array.isArray(data)) setOffices(data);
      } catch (err) {
        console.warn("Falha ao carregar escritórios:", err);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const handleClassifyPending = useCallback(async () => {
    setClassifyingPending(true);
    try {
      const response = await submitPrazosIniciaisClassifyPending();
      if (!response.submitted) {
        toast({
          title: "Nenhum intake pendente",
          description: response.message,
        });
        return;
      }
      toast({
        title: "Batch criado",
        description: `${response.intakes_count} intake(s) enviados pro Sonnet. Batch #${response.batch_id}.`,
      });
      await Promise.all([loadBatches(), loadIntakes()]);
    } catch (error) {
      toast({
        title: "Falha ao classificar pendentes",
        description: error instanceof Error ? error.message : "Nao foi possivel criar o batch.",
        variant: "destructive",
      });
    } finally {
      setClassifyingPending(false);
    }
  }, [loadBatches, loadIntakes, toast]);

  // Reaplicar templates em lote — abre modal limpo, calcula dry_run sob
  // demanda quando o operador clica "Visualizar impacto".
  const openReapplyDialog = useCallback(() => {
    setReapplyDryRunResult(null);
    setReapplyDialogOpen(true);
  }, []);

  const toggleReapplyStatus = useCallback((status: string) => {
    setReapplyStatuses((prev) =>
      prev.includes(status)
        ? prev.filter((s) => s !== status)
        : [...prev, status],
    );
    // Mudou filtro → dry-run anterior fica stale. Limpa pra forçar
    // novo "Visualizar impacto" antes de confirmar.
    setReapplyDryRunResult(null);
  }, []);

  const handleReapplyDryRun = useCallback(async () => {
    if (reapplyStatuses.length === 0) {
      toast({
        title: "Selecione pelo menos um status",
        variant: "destructive",
      });
      return;
    }
    setReapplyDryRunLoading(true);
    try {
      const result = await reapplyPrazosIniciaisTemplates({
        status_in: reapplyStatuses,
        dry_run: true,
      });
      setReapplyDryRunResult(result);
    } catch (error) {
      toast({
        title: "Falha ao calcular impacto",
        description:
          error instanceof Error ? error.message : "Erro desconhecido.",
        variant: "destructive",
      });
    } finally {
      setReapplyDryRunLoading(false);
    }
  }, [reapplyStatuses, toast]);

  const handleReapplyConfirm = useCallback(async () => {
    if (reapplyStatuses.length === 0) return;
    setReapplyConfirmLoading(true);
    try {
      const result = await reapplyPrazosIniciaisTemplates({
        status_in: reapplyStatuses,
        dry_run: false,
      });
      toast({
        title: "Templates reaplicados",
        description:
          `${result.sugestoes_updated} sugestão(ões) atualizada(s) em ` +
          `${result.intakes_processed} intake(s). ` +
          `${result.intakes_promoted} intake(s) promovido(s) pra CLASSIFICADO.`,
      });
      setReapplyDialogOpen(false);
      setReapplyDryRunResult(null);
      await loadIntakes();
    } catch (error) {
      toast({
        title: "Falha ao reaplicar",
        description:
          error instanceof Error ? error.message : "Erro desconhecido.",
        variant: "destructive",
      });
    } finally {
      setReapplyConfirmLoading(false);
    }
  }, [reapplyStatuses, toast, loadIntakes]);

  const handleRefreshBatch = useCallback(
    async (batchId: number) => {
      setBatchActionId(batchId);
      try {
        await refreshPrazosIniciaisBatch(batchId);
        await loadBatches();
      } catch (error) {
        toast({
          title: "Falha ao atualizar status",
          description: error instanceof Error ? error.message : "Erro desconhecido.",
          variant: "destructive",
        });
      } finally {
        setBatchActionId(null);
      }
    },
    [loadBatches, toast],
  );

  const handleApplyBatch = useCallback(
    async (batchId: number) => {
      setBatchActionId(batchId);
      try {
        const result = await applyPrazosIniciaisBatch(batchId);
        toast({
          title: "Resultados aplicados",
          description: `${result.succeeded} intake(s) classificados, ${result.total_sugestoes} sugestao(oes) geradas. ${result.failed} falha(s), ${result.skipped} puladas.`,
        });
        await Promise.all([loadBatches(), loadIntakes()]);
      } catch (error) {
        toast({
          title: "Falha ao aplicar resultados",
          description: error instanceof Error ? error.message : "Erro desconhecido.",
          variant: "destructive",
        });
      } finally {
        setBatchActionId(null);
      }
    },
    [loadBatches, loadIntakes, toast],
  );

  // ─── Polling automático dos batches em processamento ──────────────────
  // Quando há batches ENVIADO/EM_PROCESSAMENTO, refresca status a cada 15s.
  // Quando algum vira PRONTO/READY, aplica resultados automaticamente.
  // Botões manuais (Atualizar status / Aplicar resultados) seguem como
  // fallback pra falhas pontuais ou re-aplicação.
  useEffect(() => {
    const inFlight = batches.filter(
      (b) => b.status === "ENVIADO" || b.status === "EM_PROCESSAMENTO",
    );
    const ready = batches.filter(
      (b) => b.status === "PRONTO" || b.status === "READY",
    );

    // Auto-aplicar batches prontos (1 por vez pra evitar duplicidade).
    if (ready.length > 0) {
      const next = ready[0];
      // Sentinela: só dispara se ninguém estiver aplicando outro batch.
      if (batchActionId === null) {
        // setBatchActionId protege contra re-entrada.
        setBatchActionId(next.id);
        applyPrazosIniciaisBatch(next.id)
          .then((result) => {
            toast({
              title: "Resultados aplicados (auto)",
              description: `Batch #${next.id}: ${result.succeeded} OK, ${result.total_sugestoes} sugestões.`,
            });
            return Promise.all([loadBatches(), loadIntakes()]);
          })
          .catch((err) => {
            toast({
              title: "Falha ao aplicar (auto)",
              description: err instanceof Error ? err.message : "Erro desconhecido.",
              variant: "destructive",
            });
          })
          .finally(() => setBatchActionId(null));
      }
      return;
    }

    // Sem batches em vôo → não precisa polling.
    if (inFlight.length === 0) return;

    const intervalId = window.setInterval(() => {
      // Refresca todos os batches em vôo. Falhas individuais são
      // silenciosas — o tick seguinte tenta de novo.
      Promise.all(
        inFlight.map((b) => refreshPrazosIniciaisBatch(b.id).catch(() => null)),
      ).then(() => {
        loadBatches();
      });
    }, 15000);

    return () => window.clearInterval(intervalId);
  }, [batches, batchActionId, loadBatches, loadIntakes, toast]);

  // Contagem de pendentes na grade visível (usado como badge no botão).
  const pendingCount = useMemo(
    () => items.filter((i) => i.status === "PRONTO_PARA_CLASSIFICAR").length,
    [items],
  );

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
            <CalendarClock className="h-6 w-6" />
            Agendar Prazos Iniciais
          </h1>
          <p className="text-muted-foreground">
            Recebe os processos do intake externo, mostra as sugestoes de agendamento e agora permite confirmar o
            fechamento operacional antes de enfileirar o cancelamento da task legada no Legal One.
          </p>
        </div>

        <div className="flex flex-col gap-2 sm:flex-row">
          <Button
            className="w-full sm:w-auto"
            onClick={handleClassifyPending}
            disabled={classifyingPending}
            title="Coleta intakes em PRONTO_PARA_CLASSIFICAR e envia em lote ao Sonnet."
          >
            {classifyingPending ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Sparkles className="mr-2 h-4 w-4" />
            )}
            Classificar pendentes
            {pendingCount > 0 && (
              <Badge variant="secondary" className="ml-2">
                {pendingCount}
              </Badge>
            )}
          </Button>
          <Button
            variant="outline"
            className="w-full sm:w-auto"
            onClick={onDispatchPendingBatch}
            disabled={isBatchDispatching}
            title="Dispara em lote os próximos 10 intakes pendentes (GED + cancel da legada)"
          >
            {isBatchDispatching ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : null}
            Disparar próximos 10
          </Button>
          <Button
            variant="outline"
            className="w-full sm:w-auto"
            onClick={openReapplyDialog}
            title="Re-roda match_templates nas sugestoes existentes (sem chamar IA). Util pra aplicar templates novos no backlog."
          >
            <RotateCcw className="mr-2 h-4 w-4" />
            Reaplicar templates
          </Button>
          <Button
            variant="outline"
            className="w-full sm:w-auto"
            onClick={onExportXlsx}
            title="Baixa XLSX com resumo, sugestões e pedidos (respeita filtro de status)"
          >
            <FileDown className="mr-2 h-4 w-4" />
            Exportar XLSX
          </Button>
          <Button asChild variant="outline" className="w-full sm:w-auto">
            <Link to="/prazos-iniciais/treatment">
              <Workflow className="mr-2 h-4 w-4" />
              Tratamento Web Agendamentos Iniciais
            </Link>
          </Button>
        </div>
      </div>

      {loadError ? (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Erro ao carregar</AlertTitle>
          <AlertDescription>{loadError}</AlertDescription>
        </Alert>
      ) : null}

      {/* ── Batches de classificação (Onda 1 manual) ───────────────────── */}
      {batches.length > 0 && (
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <div>
                <CardTitle className="flex items-center gap-2 text-base">
                  <Cpu className="h-4 w-4" />
                  Batches de classificação
                </CardTitle>
                <CardDescription>
                  Acompanhe o status dos envios ao Sonnet. Ao ficar PRONTO, clique em "Aplicar" para materializar pedidos e sugestões.
                </CardDescription>
              </div>
              <Button
                variant="ghost"
                size="sm"
                onClick={loadBatches}
                disabled={batchesLoading}
                title="Recarregar lista"
              >
                <RefreshCw className={`h-4 w-4 ${batchesLoading ? "animate-spin" : ""}`} />
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-[70px]">Batch</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead className="text-right">Intakes</TableHead>
                    <TableHead className="text-right">Sucesso</TableHead>
                    <TableHead className="text-right">Erros</TableHead>
                    <TableHead>Enviado em</TableHead>
                    <TableHead>Concluído em</TableHead>
                    <TableHead className="text-right">Ações</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {batches.map((batch) => {
                    const isActing = batchActionId === batch.id;
                    const isPronto = batch.status === "PRONTO" || batch.status === "READY";
                    const isAplicado = batch.status === "APLICADO";
                    const isEmAndamento =
                      batch.status === "ENVIADO" || batch.status === "EM_PROCESSAMENTO";
                    const statusColor =
                      isAplicado
                        ? "bg-emerald-100 text-emerald-700 border-emerald-300"
                        : isPronto
                          ? "bg-blue-100 text-blue-700 border-blue-300"
                          : isEmAndamento
                            ? "bg-amber-100 text-amber-700 border-amber-300"
                            : "bg-slate-100 text-slate-700 border-slate-300";
                    const fmtDate = (iso: string | null) =>
                      iso
                        ? new Date(iso).toLocaleString("pt-BR", {
                            day: "2-digit",
                            month: "2-digit",
                            hour: "2-digit",
                            minute: "2-digit",
                          })
                        : "—";
                    return (
                      <TableRow key={batch.id}>
                        <TableCell className="font-mono text-xs">#{batch.id}</TableCell>
                        <TableCell>
                          <Badge variant="outline" className={`text-[10px] ${statusColor}`}>
                            {batch.status}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-right tabular-nums">{batch.total_records}</TableCell>
                        <TableCell className="text-right tabular-nums text-emerald-700">
                          {batch.succeeded_count}
                        </TableCell>
                        <TableCell className="text-right tabular-nums text-red-700">
                          {batch.errored_count}
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {fmtDate(batch.submitted_at)}
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {fmtDate(batch.ended_at)}
                        </TableCell>
                        <TableCell className="text-right">
                          <div className="flex justify-end gap-1">
                            {isEmAndamento && (
                              <Button
                                size="sm"
                                variant="ghost"
                                className="h-7 text-xs"
                                onClick={() => handleRefreshBatch(batch.id)}
                                disabled={isActing}
                                title="Consultar Anthropic e atualizar status"
                              >
                                {isActing ? (
                                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                ) : (
                                  <>
                                    <RefreshCw className="mr-1 h-3.5 w-3.5" />
                                    Atualizar
                                  </>
                                )}
                              </Button>
                            )}
                            {isPronto && (
                              <Button
                                size="sm"
                                className="h-7 bg-blue-600 text-xs hover:bg-blue-700"
                                onClick={() => handleApplyBatch(batch.id)}
                                disabled={isActing}
                                title="Materializar pedidos e sugestões no banco"
                              >
                                {isActing ? (
                                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                ) : (
                                  <>
                                    <Play className="mr-1 h-3.5 w-3.5" />
                                    Aplicar
                                  </>
                                )}
                              </Button>
                            )}
                            {isAplicado && (
                              <span className="inline-flex items-center gap-1 text-xs text-emerald-700">
                                <CheckCircle2 className="h-3.5 w-3.5" />
                                Concluído
                              </span>
                            )}
                          </div>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Filter className="h-4 w-4" />
            Filtros
          </CardTitle>
          <CardDescription>
            Multi-seleção na maioria dos campos. Use Ctrl/Cmd pra marcar várias opções.
            Clique em <span className="font-semibold">Aplicar</span> (ou Enter no CNJ) pra executar a busca.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* ── Linha 1: Status, Natureza, Produto ──────────────────── */}
          <div className="grid gap-3 md:grid-cols-3">
            <div className="space-y-1">
              <Label className="text-xs uppercase tracking-wide text-muted-foreground">
                Status
              </Label>
              <MultiSelect
                options={STATUS_OPTIONS
                  .filter((o) => o.value !== "__all__")
                  .map((o) => ({ value: o.value, label: o.label }))}
                defaultValue={statusFilter ? statusFilter.split(",").filter(Boolean) : []}
                onValueChange={(vals) => setStatusFilter(vals.join(","))}
                placeholder="Todos"
                className="h-9 text-sm"
                maxCount={2}
              />
            </div>

            <div className="space-y-1">
              <Label className="text-xs uppercase tracking-wide text-muted-foreground">
                Natureza do processo
              </Label>
              <MultiSelect
                options={(enums?.naturezas ?? []).map((n) => ({ value: n, label: n }))}
                defaultValue={naturezaFilter ? naturezaFilter.split(",").filter(Boolean) : []}
                onValueChange={(vals) => setNaturezaFilter(vals.join(","))}
                placeholder={enums ? "Todas" : "Carregando..."}
                className="h-9 text-sm"
                maxCount={2}
              />
            </div>

            <div className="space-y-1">
              <Label className="text-xs uppercase tracking-wide text-muted-foreground">
                Produto
              </Label>
              <MultiSelect
                options={(enums?.produtos ?? []).map((p) => ({ value: p, label: p }))}
                defaultValue={produtoFilter ? produtoFilter.split(",").filter(Boolean) : []}
                onValueChange={(vals) => setProdutoFilter(vals.join(","))}
                placeholder={enums ? "Todos" : "Carregando..."}
                className="h-9 text-sm"
                maxCount={2}
              />
            </div>
          </div>

          {/* ── Linha 2: Prob. êxito, Erro, Escritório ──────────────── */}
          <div className="grid gap-3 md:grid-cols-3">
            <div className="space-y-1">
              <Label className="text-xs uppercase tracking-wide text-muted-foreground">
                Probabilidade de êxito global
              </Label>
              <MultiSelect
                options={[
                  { value: "remota", label: "Remota" },
                  { value: "possivel", label: "Possível" },
                  { value: "provavel", label: "Provável" },
                ]}
                defaultValue={probExitoFilter ? probExitoFilter.split(",").filter(Boolean) : []}
                onValueChange={(vals) => setProbExitoFilter(vals.join(","))}
                placeholder="Todas"
                className="h-9 text-sm"
                maxCount={3}
              />
            </div>

            <div className="space-y-1">
              <Label className="text-xs uppercase tracking-wide text-muted-foreground">
                Mensagem de erro
              </Label>
              <Select value={hasErrorFilter} onValueChange={(v) => setHasErrorFilter(v as "__all__" | "com" | "sem")}>
                <SelectTrigger className="h-9 text-sm">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__all__">Qualquer</SelectItem>
                  <SelectItem value="com">Só com erro</SelectItem>
                  <SelectItem value="sem">Só sem erro</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1">
              <Label className="text-xs uppercase tracking-wide text-muted-foreground">
                Escritório (IDs)
              </Label>
              <Input
                placeholder="CSV de IDs. Ex.: 61,62"
                value={officeFilter}
                onChange={(e) => setOfficeFilter(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") onAplicarFiltros(); }}
                className="h-9 text-sm"
              />
            </div>
          </div>

          {/* ── Linha 3: CNJ, Período, Botões ───────────────────────── */}
          <div className="grid gap-3 md:grid-cols-[2fr_1fr_1fr_auto_auto_auto]">
            <div className="space-y-1">
              <Label htmlFor="pin-cnj" className="text-xs uppercase tracking-wide text-muted-foreground">
                CNJ
              </Label>
              <Input
                id="pin-cnj"
                placeholder="Com ou sem máscara — match por dígitos"
                value={cnjFilter}
                onChange={(event) => setCnjFilter(event.target.value)}
                onKeyDown={(event) => { if (event.key === "Enter") onAplicarFiltros(); }}
                className="h-9 text-sm"
              />
            </div>

            <div className="space-y-1">
              <Label className="text-xs uppercase tracking-wide text-muted-foreground">
                Recebido de
              </Label>
              <Input
                type="date"
                value={dateFromFilter}
                onChange={(e) => setDateFromFilter(e.target.value)}
                className="h-9 text-sm"
              />
            </div>

            <div className="space-y-1">
              <Label className="text-xs uppercase tracking-wide text-muted-foreground">
                Recebido até
              </Label>
              <Input
                type="date"
                value={dateToFilter}
                onChange={(e) => setDateToFilter(e.target.value)}
                className="h-9 text-sm"
              />
            </div>

            <div className="flex items-end">
              <Button type="button" onClick={onAplicarFiltros} disabled={isLoading} className="h-9">
                <Search className="mr-2 h-4 w-4" />
                Aplicar
              </Button>
            </div>

            <div className="flex items-end">
              <Button type="button" variant="outline" onClick={onLimparFiltros} disabled={isLoading} className="h-9">
                <Undo2 className="mr-2 h-4 w-4" />
                Limpar
              </Button>
            </div>

            <div className="flex items-end">
              <Button
                type="button"
                variant="ghost"
                onClick={() => loadIntakes()}
                disabled={isLoading}
                title="Atualizar lista sem mudar filtros"
                className="h-9"
              >
                <RefreshCw className={`h-4 w-4 ${isLoading ? "animate-spin" : ""}`} />
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <CardTitle className="text-base">Intakes</CardTitle>
              <CardDescription>
                {isLoading
                  ? "Carregando..."
                  : total === 0
                    ? "Nenhum intake encontrado com os filtros atuais."
                    : `Exibindo ${pageInfo.start}-${pageInfo.end} de ${total} registro(s).`}
              </CardDescription>
            </div>
            <div className="text-sm text-muted-foreground">
              Abra um intake para confirmar as tasks criadas e mandar o cancelamento da task legada para a fila tecnica.
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <ScrollArea className="w-full">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[160px]">Recebido</TableHead>
                  <TableHead>CNJ</TableHead>
                  <TableHead>Arquivo / origem</TableHead>
                  <TableHead className="w-[200px]">Classificação</TableHead>
                  <TableHead className="w-[220px]">Status</TableHead>
                  <TableHead className="w-[120px] text-right">Sugestoes</TableHead>
                  <TableHead className="w-[120px] text-right">Acoes</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {isLoading && items.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={7} className="py-10 text-center">
                      <Loader2 className="mr-2 inline-block h-5 w-5 animate-spin" />
                      Carregando intakes...
                    </TableCell>
                  </TableRow>
                ) : null}

                {!isLoading && items.length === 0 && !loadError ? (
                  <TableRow>
                    <TableCell colSpan={7} className="py-10 text-center text-muted-foreground">
                      Nenhum intake encontrado.
                    </TableCell>
                  </TableRow>
                ) : null}

                {items.map((item) => (
                  <TableRow key={item.id}>
                    <TableCell className="whitespace-nowrap">{formatDateTime(item.received_at)}</TableCell>
                    <TableCell className="font-mono text-xs">{formatCnj(item.cnj_number)}</TableCell>
                    <TableCell>
                      <div className="space-y-1">
                        <div className="text-sm">{item.pdf_filename_original || item.external_id}</div>
                        <div className="text-xs text-muted-foreground">
                          {naturezaLabel(item.natureza_processo) || "Natureza pendente"}
                          {item.produto ? ` · ${produtoLabel(item.produto)}` : ""}
                        </div>
                        {item.treated_by_name ? (
                          <div className="text-xs text-muted-foreground">
                            Tratado por <span className="font-medium text-foreground/80">{item.treated_by_name}</span>
                            {item.treated_at ? ` em ${formatDateTime(item.treated_at)}` : ""}
                          </div>
                        ) : null}
                      </div>
                    </TableCell>
                    <TableCell>
                      {/* Classificacao = tipos_prazo distintos das sugestoes,
                          normalizados via tipoPrazoLabel. Lista vertical de
                          badges (sem cap) — o mais comum eh 1-2 sugestoes. */}
                      {item.tipos_prazo && item.tipos_prazo.length > 0 ? (
                        <div className="flex flex-col items-start gap-1">
                          {item.tipos_prazo.map((tp) => (
                            <Badge key={tp} variant="outline" className="font-normal">
                              {tipoPrazoLabel(tp)}
                            </Badge>
                          ))}
                        </div>
                      ) : (
                        <span className="text-xs text-muted-foreground">—</span>
                      )}
                    </TableCell>
                    <TableCell>
                      <Badge variant={statusBadgeVariant(item.status)}>{STATUS_LABEL[item.status] ?? item.status}</Badge>
                      {item.dispatch_pending ? (
                        <div className="mt-1">
                          <Badge variant="outline" className="bg-amber-50 text-amber-800 border-amber-300">
                            Pendente disparo
                          </Badge>
                        </div>
                      ) : null}
                      {item.error_message ? (
                        <div className="mt-1 max-w-[220px] truncate text-xs text-muted-foreground" title={item.error_message}>
                          {item.error_message}
                        </div>
                      ) : null}
                      {item.dispatch_error_message ? (
                        <div
                          className="mt-1 max-w-[220px] truncate text-xs text-destructive"
                          title={item.dispatch_error_message}
                        >
                          Disparo: {item.dispatch_error_message}
                        </div>
                      ) : null}
                    </TableCell>
                    <TableCell className="text-right">{item.sugestoes_count}</TableCell>
                    <TableCell className="text-right">
                      <div className="flex flex-col gap-1 items-end">
                        <Button size="sm" variant="outline" onClick={() => setSelectedId(item.id)}>
                          Detalhes
                        </Button>
                        {item.dispatch_pending ? (
                          <Button
                            size="sm"
                            variant="default"
                            disabled={dispatchingIntakeId === item.id}
                            onClick={() => onDispatchIntake(item.id)}
                            title="Sobe habilitação no GED + cancela task legada"
                          >
                            {dispatchingIntakeId === item.id ? (
                              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                            ) : null}
                            Disparar
                          </Button>
                        ) : null}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </ScrollArea>

          <div className="flex items-center justify-end gap-2 pt-4">
            <Button
              variant="outline"
              size="sm"
              disabled={!pageInfo.hasPrev || isLoading}
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            >
              Anterior
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={!pageInfo.hasNext || isLoading}
              onClick={() => setOffset(offset + PAGE_SIZE)}
            >
              Proxima
            </Button>
          </div>
        </CardContent>
      </Card>

      <Dialog
        open={selectedId !== null}
        onOpenChange={(open) => {
          if (!open) setSelectedId(null);
        }}
      >
        <DialogContent className="!max-w-[min(95vw,72rem)] max-h-[92vh] w-[95vw] overflow-y-auto overflow-x-hidden p-5 sm:p-6">
          <DialogHeader>
            <DialogTitle>Intake #{selectedId}</DialogTitle>
            <DialogDescription>
              Revise os dados do processo, marque as sugestoes efetivamente agendadas e confirme para disparar a fila
              de cancelamento da task legada.
            </DialogDescription>
          </DialogHeader>

          {detailLoading ? (
            <div className="py-10 text-center">
              <Loader2 className="mr-2 inline-block h-5 w-5 animate-spin" />
              Carregando...
            </div>
          ) : null}

          {detailError ? (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertTitle>Erro ao carregar detalhe</AlertTitle>
              <AlertDescription>{detailError}</AlertDescription>
            </Alert>
          ) : null}

          {detail && !detailLoading ? (
            <div className="space-y-5">
              <div className="grid gap-3 text-sm sm:grid-cols-2 2xl:grid-cols-3 [&>div]:min-w-0 [&>div>div]:break-words">
                <div>
                  <div className="text-xs text-muted-foreground">External ID</div>
                  <div className="break-all font-mono">{detail.external_id}</div>
                </div>
                <div>
                  <div className="text-xs text-muted-foreground">Status</div>
                  <Badge variant={statusBadgeVariant(detail.status)}>
                    {STATUS_LABEL[detail.status] ?? detail.status}
                  </Badge>
                </div>
                <div>
                  <div className="text-xs text-muted-foreground">Recebido em</div>
                  <div>{formatDateTime(detail.received_at)}</div>
                </div>
                <div>
                  <div className="text-xs text-muted-foreground">CNJ</div>
                  <div className="font-mono">{formatCnj(detail.cnj_number)}</div>
                </div>
                <div>
                  <div className="text-xs text-muted-foreground">Processo no Legal One</div>
                  <div>{detail.lawsuit_id ? `lawsuit_id = ${detail.lawsuit_id}` : "Nao resolvido"}</div>
                </div>
                <div className="min-w-0">
                  <div className="text-xs text-muted-foreground">Escritorio</div>
                  <div
                    className="break-words text-sm"
                    title={detail.office_id ? `office_id: ${detail.office_id}` : undefined}
                  >
                    {officeLabel(detail.office_id)}
                  </div>
                </div>
                <div>
                  <div className="text-xs text-muted-foreground">Natureza</div>
                  <div>{detail.natureza_processo || "-"}</div>
                </div>
                <div>
                  <div className="text-xs text-muted-foreground">Produto</div>
                  <div>{detail.produto || "-"}</div>
                </div>
                <div>
                  <div className="text-xs text-muted-foreground">Sugestoes</div>
                  <div>{detail.sugestoes.length}</div>
                </div>
                <div>
                  <div className="text-xs text-muted-foreground">Prob. êxito global</div>
                  <div className="capitalize">
                    {detail.probabilidade_exito_global ? (
                      <Badge
                        className={
                          detail.probabilidade_exito_global === "provavel"
                            ? "bg-emerald-100 text-emerald-800"
                            : detail.probabilidade_exito_global === "possivel"
                            ? "bg-amber-100 text-amber-800"
                            : "bg-rose-100 text-rose-800"
                        }
                      >
                        {detail.probabilidade_exito_global}
                      </Badge>
                    ) : (
                      <span className="text-muted-foreground">-</span>
                    )}
                  </div>
                </div>
                <div>
                  <div className="text-xs text-muted-foreground">
                    Valor estimado / pedido
                  </div>
                  <div>
                    {detail.valor_total_estimado != null
                      ? `R$ ${detail.valor_total_estimado.toLocaleString("pt-BR", { minimumFractionDigits: 2 })}`
                      : "-"}
                    {detail.valor_total_pedido != null && (
                      <span className="ml-1 text-xs text-muted-foreground">
                        (pedido R$ {detail.valor_total_pedido.toLocaleString("pt-BR", { minimumFractionDigits: 2 })})
                      </span>
                    )}
                  </div>
                </div>
                <div>
                  <div className="text-xs text-muted-foreground">Aprovisionamento (CPC 25)</div>
                  <div className="font-medium">
                    {detail.aprovisionamento_sugerido != null
                      ? `R$ ${detail.aprovisionamento_sugerido.toLocaleString("pt-BR", { minimumFractionDigits: 2 })}`
                      : "-"}
                  </div>
                </div>
              </div>

              {detail.error_message ? (
                <Alert variant="destructive">
                  <AlertCircle className="h-4 w-4" />
                  <AlertTitle>Mensagem de erro</AlertTitle>
                  <AlertDescription className="whitespace-pre-wrap">{detail.error_message}</AlertDescription>
                </Alert>
              ) : null}

              {detail.analise_estrategica ? (
                <div className="rounded-lg border bg-blue-50 p-3 text-sm">
                  <div className="mb-1 text-xs font-semibold text-blue-800">
                    Análise estratégica da IA
                  </div>
                  <div className="whitespace-pre-wrap text-blue-900">
                    {detail.analise_estrategica}
                  </div>
                </div>
              ) : null}

              {detail.natureza_processo === "AGRAVO_INSTRUMENTO" &&
              (detail.agravo_processo_origem_cnj || detail.agravo_decisao_agravada_resumo) ? (
                <div className="rounded-lg border bg-amber-50 p-3 text-sm">
                  <div className="mb-1 text-xs font-semibold text-amber-800">
                    Agravo de Instrumento
                  </div>
                  {detail.agravo_processo_origem_cnj ? (
                    <div className="mb-1">
                      <span className="text-xs text-muted-foreground">Processo de origem (1º grau): </span>
                      <span className="font-mono">
                        {detail.agravo_processo_origem_cnj}
                      </span>
                    </div>
                  ) : null}
                  {detail.agravo_decisao_agravada_resumo ? (
                    <div className="mt-1">
                      <span className="text-xs text-muted-foreground">Decisão agravada: </span>
                      <span className="whitespace-pre-wrap">{detail.agravo_decisao_agravada_resumo}</span>
                    </div>
                  ) : null}
                </div>
              ) : null}

              <Separator />

              <div>
                <div className="mb-2 text-sm font-semibold">Capa do processo</div>
                <div className="grid gap-2 text-sm md:grid-cols-2 xl:grid-cols-3">
                  <div>
                    <div className="text-xs text-muted-foreground">Tribunal / Vara</div>
                    <div>{`${detail.capa_json.tribunal || "-"} · ${detail.capa_json.vara || "-"}`}</div>
                  </div>
                  <div>
                    <div className="text-xs text-muted-foreground">Classe</div>
                    <div>{detail.capa_json.classe || "-"}</div>
                  </div>
                  <div>
                    <div className="text-xs text-muted-foreground">Assunto</div>
                    <div>{detail.capa_json.assunto || "-"}</div>
                  </div>
                  <div>
                    <div className="text-xs text-muted-foreground">Polo ativo</div>
                    <div>{(detail.capa_json.polo_ativo || []).map((parte) => parte.nome).join(", ") || "-"}</div>
                  </div>
                  <div>
                    <div className="text-xs text-muted-foreground">Polo passivo</div>
                    <div>{getPrimeiroPoloPassivo(detail)}</div>
                  </div>
                  <div>
                    <div className="text-xs text-muted-foreground">Distribuicao</div>
                    <div>{formatDate(detail.capa_json.data_distribuicao as string | null | undefined)}</div>
                  </div>
                </div>
              </div>

              <Separator />

              <div>
                <div className="mb-2 text-sm font-semibold">Habilitacao (PDF)</div>
                <div className="flex flex-wrap items-center gap-3 text-sm">
                  <FileText className="h-4 w-4" />
                  <span>
                    {detail.pdf_filename_original || "habilitacao.pdf"}
                    <span className="ml-2 text-muted-foreground">({formatBytes(detail.pdf_bytes)})</span>
                  </span>
                  {detail.pdf_bytes ? (
                    <Button
                      size="sm"
                      variant="outline"
                      className="ml-auto"
                      onClick={onOpenPdfInNewTab}
                      title="Baixa o PDF autenticado e abre numa nova aba"
                    >
                      <ExternalLink className="mr-1 h-4 w-4" />
                      Abrir em nova aba
                    </Button>
                  ) : (
                    <span className="ml-auto text-xs text-muted-foreground">Retencao expirada</span>
                  )}
                </div>
              </div>

              <Separator />

              {detail.sugestoes.length > 0 ? (
                <div className="space-y-3">
                  <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                    <div>
                      <div className="text-sm font-semibold">Sugestoes de agendamento ({detail.sugestoes.length})</div>
                      <div className="text-xs text-muted-foreground">
                        Marque apenas as tasks realmente criadas no Legal One. Ao confirmar, o intake vai para AGENDADO
                        e entra na fila tecnica de cancelamento da task "Agendar Prazos".
                      </div>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <Button type="button" size="sm" variant="outline" onClick={() => setAllSuggestions(true)}>
                        Selecionar todas
                      </Button>
                      <Button type="button" size="sm" variant="outline" onClick={() => setAllSuggestions(false)}>
                        Limpar selecao
                      </Button>
                      <Badge variant="secondary">{selectedSuggestionCount} selecionada(s)</Badge>
                    </div>
                  </div>

                  {!isConfirmableStatus(detail.status) ? (
                    <Alert>
                      <AlertCircle className="h-4 w-4" />
                      <AlertTitle>Confirmacao indisponivel neste status</AlertTitle>
                      <AlertDescription>
                        O backend permite confirmar apenas intakes em EM_REVISAO, CLASSIFICADO, AGENDADO ou
                        ERRO_AGENDAMENTO.
                      </AlertDescription>
                    </Alert>
                  ) : null}

                  <div className="overflow-x-auto rounded-md border">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead className="w-[64px]">Ok</TableHead>
                          <TableHead>Tipo / subtipo</TableHead>
                          <TableHead>Data base</TableHead>
                          <TableHead>Prazo / audiencia</TableHead>
                          <TableHead>Confianca</TableHead>
                          <TableHead>Revisao</TableHead>
                          <TableHead className="w-[180px]">Task criada</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {detail.sugestoes.map((suggestion) => (
                          <TableRow key={suggestion.id}>
                            <TableCell>
                              <Checkbox
                                checked={Boolean(selectedSuggestions[suggestion.id])}
                                onCheckedChange={(checked) =>
                                  setSelectedSuggestions((current) => ({
                                    ...current,
                                    [suggestion.id]: checked === true,
                                  }))
                                }
                                aria-label={`Selecionar sugestao ${suggestion.id}`}
                              />
                            </TableCell>
                            <TableCell>
                              <div className="font-medium">{suggestion.tipo_prazo}</div>
                              <div className="text-xs text-muted-foreground">
                                {suggestion.subtipo || "Sem subtipo"} · sugestao #{suggestion.id}
                              </div>
                              {suggestion.justificativa ? (
                                <div className="mt-1 max-w-[360px] text-xs text-muted-foreground">
                                  {suggestion.justificativa}
                                </div>
                              ) : null}
                              {suggestion.prazo_fatal_data ? (
                                <div
                                  className="mt-1 rounded-sm bg-rose-50 px-1.5 py-0.5 text-[11px] text-rose-700 inline-block"
                                  title={suggestion.prazo_fatal_fundamentacao || undefined}
                                >
                                  Prazo fatal: {formatDate(suggestion.prazo_fatal_data)}
                                </div>
                              ) : null}
                            </TableCell>
                            <TableCell>{formatDate(suggestion.data_base)}</TableCell>
                            <TableCell>{formatSuggestionDeadline(suggestion)}</TableCell>
                            <TableCell>{suggestion.confianca || "-"}</TableCell>
                            <TableCell>
                              <Badge className={reviewBadgeClass(suggestion.review_status)}>
                                {REVIEW_LABEL[suggestion.review_status] || suggestion.review_status}
                              </Badge>
                            </TableCell>
                            <TableCell>
                              <Input
                                inputMode="numeric"
                                placeholder="Ex.: 191842"
                                value={createdTaskIds[suggestion.id] || ""}
                                onChange={(event) =>
                                  setCreatedTaskIds((current) => ({
                                    ...current,
                                    [suggestion.id]: event.target.value,
                                  }))
                                }
                              />
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                </div>
              ) : (
                <Alert>
                  <AlertCircle className="h-4 w-4" />
                  <AlertTitle>Sem sugestoes disponiveis</AlertTitle>
                  <AlertDescription>
                    Este intake ainda nao gerou sugestoes elegiveis para confirmacao operacional.
                  </AlertDescription>
                </Alert>
              )}

              {detail.pedidos && detail.pedidos.length > 0 ? (
                <div>
                  <div className="mb-2 text-sm font-semibold">
                    Pedidos extraídos da petição inicial ({detail.pedidos.length})
                  </div>
                  <div className="overflow-x-auto rounded-md border">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Tipo</TableHead>
                          <TableHead>Prob. perda</TableHead>
                          <TableHead className="text-right">Indicado</TableHead>
                          <TableHead className="text-right">Estimado</TableHead>
                          <TableHead className="text-right">Aprovisionamento</TableHead>
                          <TableHead>Fundamentação</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {detail.pedidos.map((pedido) => (
                          <TableRow key={pedido.id}>
                            <TableCell className="font-medium">
                              {pedido.tipo_pedido}
                            </TableCell>
                            <TableCell>
                              {pedido.probabilidade_perda ? (
                                <Badge
                                  className={
                                    pedido.probabilidade_perda === "provavel"
                                      ? "bg-rose-100 text-rose-800"
                                      : pedido.probabilidade_perda === "possivel"
                                      ? "bg-amber-100 text-amber-800"
                                      : "bg-emerald-100 text-emerald-800"
                                  }
                                >
                                  {pedido.probabilidade_perda}
                                </Badge>
                              ) : (
                                <span className="text-muted-foreground">-</span>
                              )}
                            </TableCell>
                            <TableCell className="text-right text-sm">
                              {pedido.valor_indicado != null
                                ? `R$ ${pedido.valor_indicado.toLocaleString("pt-BR", { minimumFractionDigits: 2 })}`
                                : "-"}
                            </TableCell>
                            <TableCell className="text-right text-sm">
                              {pedido.valor_estimado != null
                                ? `R$ ${pedido.valor_estimado.toLocaleString("pt-BR", { minimumFractionDigits: 2 })}`
                                : "-"}
                            </TableCell>
                            <TableCell className="text-right text-sm font-medium">
                              {pedido.aprovisionamento != null
                                ? `R$ ${pedido.aprovisionamento.toLocaleString("pt-BR", { minimumFractionDigits: 2 })}`
                                : "-"}
                            </TableCell>
                            <TableCell className="max-w-[320px] text-xs text-muted-foreground">
                              {pedido.fundamentacao_risco || pedido.fundamentacao_valor || "-"}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                </div>
              ) : null}

              <Alert>
                <CheckCircle2 className="h-4 w-4" />
                <AlertTitle>Proximo passo apos a confirmacao</AlertTitle>
                <AlertDescription className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                  <span>
                    Assim que os agendamentos forem confirmados, o processo entra na fila que cancela a task legada
                    "Agendar Prazos - Banco Master".
                  </span>
                  <Button asChild size="sm" variant="outline">
                    <Link to="/prazos-iniciais/treatment">
                      <Workflow className="mr-2 h-4 w-4" />
                      Abrir tratamento web
                    </Link>
                  </Button>
                </AlertDescription>
              </Alert>
            </div>
          ) : null}

          <DialogFooter className="flex-wrap justify-end gap-2 sm:space-x-0">
            {/* Reclassificar - habilitado quando ja houve uma classificacao
                (CLASSIFICADO/AGUARDANDO_TEMPLATE/EM_REVISAO/ERRO) e voce quer
                jogar fora as sugestoes/pedidos atuais e re-classificar do
                zero. Util pros antigos com SEM_DETERMINACAO legado. */}
            <Button
              variant="outline"
              onClick={onReclassify}
              disabled={
                !detail ||
                actionLoading ||
                (detail.status !== "CLASSIFICADO" &&
                  detail.status !== "AGUARDANDO_CONFIG_TEMPLATE" &&
                  detail.status !== "EM_REVISAO" &&
                  detail.status !== "ERRO_CLASSIFICACAO")
              }
              title={
                detail
                  ? (
                      detail.status === "CLASSIFICADO" ||
                      detail.status === "AGUARDANDO_CONFIG_TEMPLATE" ||
                      detail.status === "EM_REVISAO" ||
                      detail.status === "ERRO_CLASSIFICACAO"
                    )
                    ? "Apaga sugestoes e pedidos atuais e reenvia o intake pra proxima rodada de classificacao"
                    : "Disponivel apenas em estados pos-classificacao"
                  : ""
              }
              className="border-purple-300 text-purple-700 hover:bg-purple-50 hover:text-purple-900"
            >
              {actionLoading ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <RotateCcw className="mr-2 h-4 w-4" />
              )}
              Reclassificar
            </Button>

            {/* Reprocessar CNJ — habilitado quando o L1 ainda nao tinha o
                processo na primeira tentativa de resolucao. Cobre o caso
                comum de intake chegar antes do cadastro no L1. */}
            <Button
              variant="outline"
              onClick={onReprocessarCnj}
              disabled={
                !detail ||
                actionLoading ||
                (detail.status !== "PROCESSO_NAO_ENCONTRADO" &&
                  detail.status !== "RECEBIDO")
              }
              title={
                detail?.status === "PROCESSO_NAO_ENCONTRADO"
                  ? "Tenta resolver o processo no Legal One de novo (caso tenha sido cadastrado depois)"
                  : detail?.status === "RECEBIDO"
                    ? "Forca nova tentativa de resolucao do CNJ"
                    : "Disponivel apenas em PROCESSO_NAO_ENCONTRADO ou RECEBIDO"
              }
              className="border-blue-300 text-blue-700 hover:bg-blue-50 hover:text-blue-900"
            >
              {actionLoading ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <RefreshCw className="mr-2 h-4 w-4" />
              )}
              Reprocessar CNJ
            </Button>

            <Button
              variant="destructive"
              onClick={onCancelar}
              disabled={!detail || actionLoading || detail.status === "CANCELADO" || detail.status === "CONCLUIDO"}
            >
              <XCircle className="mr-2 h-4 w-4" />
              Cancelar intake
            </Button>

            <Button
              variant="outline"
              onClick={onFinalizeWithoutProvidence}
              disabled={
                !detail ||
                actionLoading ||
                !detail.lawsuit_id ||
                detail.status === "CANCELADO" ||
                detail.status === "AGENDADO" ||
                detail.status === "RECEBIDO" ||
                detail.status === "EM_CLASSIFICACAO"
              }
              className="border-amber-400 text-amber-700 hover:bg-amber-50 hover:text-amber-900"
              title={
                !detail?.lawsuit_id
                  ? "Intake sem processo vinculado — reprocesse o CNJ primeiro"
                  : detail?.status === "CONCLUIDO_SEM_PROVIDENCIA"
                    ? "Retentar os passos que faltaram (idempotente): refaz GED se não subiu, cleanup PDF se não apagou, reenfileira cancelamento da legada"
                    : "Sobe habilitação pro GED, cancela task legada, marca intake como concluído SEM criar tarefa nova no L1"
              }
            >
              {actionLoading ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <CheckCircle2 className="mr-2 h-4 w-4" />
              )}
              {detail?.status === "CONCLUIDO_SEM_PROVIDENCIA"
                ? "Retentar finalização"
                : "Finalizar sem providência"}
            </Button>

            {isAdmin && (
              <Button
                variant="destructive"
                onClick={onDeleteIntake}
                disabled={!detail || actionLoading}
                title="HARD DELETE — admin only. Apaga intake + cascata + PDF. Use só em testes."
                className="bg-red-700 hover:bg-red-800"
              >
                <XCircle className="mr-2 h-4 w-4" />
                Deletar
              </Button>
            )}

            <Button variant="secondary" onClick={() => setSelectedId(null)}>
              Fechar
            </Button>

            <Button onClick={onConfirmarAgendamentos} disabled={!canConfirmScheduling}>
              {actionLoading ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <CheckCircle2 className="mr-2 h-4 w-4" />
              )}
              Confirmar agendamentos
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── Modal: Reaplicar templates em lote ─────────────────────── */}
      <Dialog open={reapplyDialogOpen} onOpenChange={setReapplyDialogOpen}>
        <DialogContent className="max-w-xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <RotateCcw className="h-4 w-4" />
              Reaplicar templates em lote
            </DialogTitle>
            <DialogDescription>
              Re-roda o casamento de templates nas sugestões já existentes
              dos intakes filtrados. <strong>Não chama a IA</strong> —
              apenas atualiza o mapeamento Legal One das sugestões com a
              configuração atual de templates. Use depois de cadastrar ou
              editar templates pra aplicar no backlog.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-2">
            <div className="space-y-2">
              <Label className="text-sm font-medium">
                Aplicar em intakes nos status:
              </Label>
              <div className="space-y-2">
                {[
                  {
                    value: "AGUARDANDO_CONFIG_TEMPLATE",
                    label: "Aguardando config de template",
                    hint: "Caso típico — intakes que ficaram sem template casado.",
                  },
                  {
                    value: "CLASSIFICADO",
                    label: "Classificado",
                    hint: "Re-aplica em intakes já com template (sobrescreve mapeamento atual).",
                  },
                  {
                    value: "EM_REVISAO",
                    label: "Em revisão",
                    hint: "Idem — apenas sugestões não-editadas e sem task no L1.",
                  },
                ].map((opt) => (
                  <div
                    key={opt.value}
                    className="flex items-start gap-2 rounded-md border p-3"
                  >
                    <Checkbox
                      id={`reapply-status-${opt.value}`}
                      checked={reapplyStatuses.includes(opt.value)}
                      onCheckedChange={() => toggleReapplyStatus(opt.value)}
                      className="mt-0.5"
                    />
                    <div className="space-y-0.5">
                      <Label
                        htmlFor={`reapply-status-${opt.value}`}
                        className="cursor-pointer"
                      >
                        {opt.label}
                      </Label>
                      <p className="text-xs text-muted-foreground">{opt.hint}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <Alert>
              <AlertCircle className="h-4 w-4" />
              <AlertDescription className="text-xs">
                Sugestões com tarefa já criada no Legal One ou editadas
                manualmente pelo operador são <strong>preservadas</strong>{" "}
                (não são tocadas pelo reapply).
              </AlertDescription>
            </Alert>

            {reapplyDryRunResult ? (
              <div className="rounded-md border bg-muted/30 p-3 space-y-1 text-sm">
                <p className="text-xs font-semibold uppercase text-muted-foreground tracking-wide">
                  Impacto previsto
                </p>
                <p>
                  <strong>{reapplyDryRunResult.intakes_processed}</strong>{" "}
                  intake(s) afetado(s)
                </p>
                <p>
                  <strong>{reapplyDryRunResult.sugestoes_updated}</strong>{" "}
                  sugestão(ões) com mapeamento atualizado
                </p>
                <p>
                  <strong>{reapplyDryRunResult.intakes_promoted}</strong>{" "}
                  intake(s) saem de AGUARDANDO_CONFIG_TEMPLATE para
                  CLASSIFICADO
                </p>
                {reapplyDryRunResult.sugestoes_no_match > 0 && (
                  <p className="text-muted-foreground">
                    {reapplyDryRunResult.sugestoes_no_match} sugestão(ões)
                    sem template casado (mantidas como estão)
                  </p>
                )}
                {reapplyDryRunResult.sugestoes_skipped_already_in_l1 > 0 && (
                  <p className="text-muted-foreground">
                    {reapplyDryRunResult.sugestoes_skipped_already_in_l1}{" "}
                    sugestão(ões) puladas (task já no L1)
                  </p>
                )}
                {reapplyDryRunResult.sugestoes_skipped_edited > 0 && (
                  <p className="text-muted-foreground">
                    {reapplyDryRunResult.sugestoes_skipped_edited}{" "}
                    sugestão(ões) puladas (editadas manualmente)
                  </p>
                )}
              </div>
            ) : null}
          </div>

          <DialogFooter className="gap-2 sm:gap-0">
            <Button
              variant="outline"
              onClick={() => setReapplyDialogOpen(false)}
              disabled={reapplyDryRunLoading || reapplyConfirmLoading}
            >
              Cancelar
            </Button>
            <Button
              variant="outline"
              onClick={handleReapplyDryRun}
              disabled={
                reapplyDryRunLoading ||
                reapplyConfirmLoading ||
                reapplyStatuses.length === 0
              }
            >
              {reapplyDryRunLoading ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : null}
              Visualizar impacto
            </Button>
            <Button
              onClick={handleReapplyConfirm}
              disabled={
                reapplyDryRunLoading ||
                reapplyConfirmLoading ||
                reapplyStatuses.length === 0 ||
                !reapplyDryRunResult
              }
              title={
                !reapplyDryRunResult
                  ? "Visualize o impacto antes de confirmar"
                  : undefined
              }
            >
              {reapplyConfirmLoading ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <CheckCircle2 className="mr-2 h-4 w-4" />
              )}
              Confirmar reaplicação
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
