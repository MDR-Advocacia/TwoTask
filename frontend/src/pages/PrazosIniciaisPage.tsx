import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  AlertCircle,
  CalendarClock,
  CheckCircle2,
  ExternalLink,
  FileDown,
  FileText,
  Filter,
  Loader2,
  RefreshCw,
  Search,
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
import { Separator } from "@/components/ui/separator";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useToast } from "@/hooks/use-toast";
import {
  cancelarPrazoInicial,
  confirmarAgendamentoPrazoInicial,
  fetchPrazoInicialDetail,
  fetchPrazosIniciaisIntakes,
  reanalyzePrazoInicial,
  exportPrazosIniciaisXlsx,
  prazoInicialPdfUrl,
  reprocessarPrazoInicialCnj,
} from "@/services/api";
import type {
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
  { value: "EM_REVISAO", label: "Em revisao" },
  { value: "AGENDADO", label: "Agendado" },
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
  const [searchParams, setSearchParams] = useSearchParams();

  const [statusFilter, setStatusFilter] = useState("__all__");
  const [cnjFilter, setCnjFilter] = useState("");
  const [appliedStatus, setAppliedStatus] = useState("__all__");
  const [appliedCnj, setAppliedCnj] = useState("");
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

  const loadIntakes = useCallback(
    async (resetPage = false) => {
      setIsLoading(true);
      setLoadError(null);
      try {
        const nextOffset = resetPage ? 0 : offset;
        const payload = await fetchPrazosIniciaisIntakes({
          status: appliedStatus !== "__all__" ? appliedStatus : undefined,
          cnj_number: appliedCnj || undefined,
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
    [appliedCnj, appliedStatus, offset],
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
    setOffset(0);
  };

  const onLimparFiltros = () => {
    setStatusFilter("__all__");
    setCnjFilter("");
    setAppliedStatus("__all__");
    setAppliedCnj("");
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

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Filter className="h-4 w-4" />
            Filtros
          </CardTitle>
          <CardDescription>Filtre por status do intake ou por numero CNJ, com ou sem mascara.</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 md:grid-cols-[1fr_1fr_auto_auto_auto]">
            <div className="space-y-1">
              <Label htmlFor="pin-status">Status</Label>
              <Select value={statusFilter} onValueChange={setStatusFilter}>
                <SelectTrigger id="pin-status">
                  <SelectValue placeholder="Todos os status" />
                </SelectTrigger>
                <SelectContent>
                  {STATUS_OPTIONS.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1">
              <Label htmlFor="pin-cnj">CNJ</Label>
              <Input
                id="pin-cnj"
                placeholder="Ex.: 0072837-30.2026.8.05.0001"
                value={cnjFilter}
                onChange={(event) => setCnjFilter(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") onAplicarFiltros();
                }}
              />
            </div>

            <div className="flex items-end">
              <Button type="button" onClick={onAplicarFiltros} disabled={isLoading}>
                <Search className="mr-2 h-4 w-4" />
                Aplicar
              </Button>
            </div>

            <div className="flex items-end">
              <Button type="button" variant="outline" onClick={onLimparFiltros} disabled={isLoading}>
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
                title="Atualizar lista"
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
                  <TableHead className="w-[220px]">Status</TableHead>
                  <TableHead className="w-[120px] text-right">Sugestoes</TableHead>
                  <TableHead className="w-[120px] text-right">Acoes</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {isLoading && items.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={6} className="py-10 text-center">
                      <Loader2 className="mr-2 inline-block h-5 w-5 animate-spin" />
                      Carregando intakes...
                    </TableCell>
                  </TableRow>
                ) : null}

                {!isLoading && items.length === 0 && !loadError ? (
                  <TableRow>
                    <TableCell colSpan={6} className="py-10 text-center text-muted-foreground">
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
                          {item.natureza_processo || "Natureza pendente"}
                          {item.produto ? ` · ${item.produto}` : ""}
                        </div>
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge variant={statusBadgeVariant(item.status)}>{STATUS_LABEL[item.status] ?? item.status}</Badge>
                      {item.error_message ? (
                        <div className="mt-1 max-w-[220px] truncate text-xs text-muted-foreground" title={item.error_message}>
                          {item.error_message}
                        </div>
                      ) : null}
                    </TableCell>
                    <TableCell className="text-right">{item.sugestoes_count}</TableCell>
                    <TableCell className="text-right">
                      <Button size="sm" variant="outline" onClick={() => setSelectedId(item.id)}>
                        Detalhes
                      </Button>
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
        <DialogContent className="max-h-[88vh] max-w-5xl overflow-y-auto">
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
              <div className="grid gap-3 text-sm md:grid-cols-2 xl:grid-cols-3">
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
                <div>
                  <div className="text-xs text-muted-foreground">Escritorio</div>
                  <div>{detail.office_id ? `office_id = ${detail.office_id}` : "-"}</div>
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
                    <Button asChild size="sm" variant="outline" className="ml-auto">
                      <a href={prazoInicialPdfUrl(detail.id)} target="_blank" rel="noopener noreferrer">
                        <ExternalLink className="mr-1 h-4 w-4" />
                        Abrir em nova aba
                      </a>
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

          <DialogFooter className="gap-2">
            <Button
              variant="outline"
              onClick={onReprocessarCnj}
              disabled={
                !detail ||
                actionLoading ||
                !(detail.status === "RECEBIDO" || detail.status === "PROCESSO_NAO_ENCONTRADO")
              }
              title="Disponivel apenas em RECEBIDO / PROCESSO_NAO_ENCONTRADO"
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
              onClick={onReanalisar}
              disabled={
                !detail ||
                actionLoading ||
                detail.status === "RECEBIDO" ||
                detail.status === "EM_CLASSIFICACAO"
              }
              title="Apaga sugestões/pedidos atuais e reclassifica no próximo batch"
            >
              {actionLoading ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <RefreshCw className="mr-2 h-4 w-4" />
              )}
              Reanalisar
            </Button>

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
    </div>
  );
}
