/**
 * PrazosIniciaisPage — Agendar Prazos Iniciais
 *
 * Fase 1 / UI mínima: lista de intakes recebidos pela automação externa
 * + drawer de detalhe + ações básicas (reprocessar CNJ, cancelar, ver PDF).
 *
 * Classificação e revisão de sugestões ficam para a Fase 4, quando a
 * taxonomia do fluxo estiver definida. Esta tela é o "backbone visual"
 * pra operar enquanto o resto do pipeline está em construção.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  CalendarClock,
  ExternalLink,
  FileText,
  Filter,
  Loader2,
  RefreshCw,
  Search,
  Undo2,
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
  cancelarPrazoInicial,
  fetchPrazoInicialDetail,
  fetchPrazosIniciaisIntakes,
  prazoInicialPdfUrl,
  reprocessarPrazoInicialCnj,
} from "@/services/api";
import type {
  PrazoInicialIntakeDetail,
  PrazoInicialIntakeStatus,
  PrazoInicialIntakeSummary,
} from "@/types/api";

// ─── Constantes de UI ────────────────────────────────────────────────

const PAGE_SIZE = 25;

// Opções do filtro de status — alinhadas com INTAKE_STATUS_* do backend.
const STATUS_OPTIONS: { value: string; label: string }[] = [
  { value: "__all__", label: "Todos os status" },
  { value: "RECEBIDO", label: "Recebido" },
  { value: "PROCESSO_NAO_ENCONTRADO", label: "Processo não encontrado" },
  { value: "PRONTO_PARA_CLASSIFICAR", label: "Pronto para classificar" },
  { value: "EM_CLASSIFICACAO", label: "Em classificação" },
  { value: "CLASSIFICADO", label: "Classificado" },
  { value: "EM_REVISAO", label: "Em revisão" },
  { value: "AGENDADO", label: "Agendado" },
  { value: "GED_ENVIADO", label: "GED enviado" },
  { value: "CONCLUIDO", label: "Concluído" },
  { value: "ERRO_CLASSIFICACAO", label: "Erro na classificação" },
  { value: "ERRO_AGENDAMENTO", label: "Erro no agendamento" },
  { value: "ERRO_GED", label: "Erro no GED" },
  { value: "CANCELADO", label: "Cancelado" },
];

const STATUS_LABEL: Record<string, string> = Object.fromEntries(
  STATUS_OPTIONS.filter((o) => o.value !== "__all__").map((o) => [o.value, o.label]),
);

type BadgeVariant = "default" | "secondary" | "destructive" | "outline";

function statusBadgeVariant(status: PrazoInicialIntakeStatus): BadgeVariant {
  if (status.startsWith("ERRO_")) return "destructive";
  if (status === "CANCELADO") return "outline";
  if (status === "CONCLUIDO" || status === "AGENDADO" || status === "GED_ENVIADO") {
    return "default";
  }
  return "secondary";
}

// ─── Helpers de formatação ──────────────────────────────────────────

function formatCnj(cnj: string | null | undefined): string {
  if (!cnj) return "—";
  const digits = cnj.replace(/\D/g, "");
  // CNJ padrão: NNNNNNN-DD.AAAA.J.TR.OOOO (20 dígitos)
  if (digits.length === 20) {
    return `${digits.slice(0, 7)}-${digits.slice(7, 9)}.${digits.slice(9, 13)}.${digits.slice(13, 14)}.${digits.slice(14, 16)}.${digits.slice(16, 20)}`;
  }
  return cnj;
}

function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("pt-BR", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

function formatBytes(bytes: number | null | undefined): string {
  if (!bytes || bytes <= 0) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function primeiroPoloPassivo(
  detail: Pick<PrazoInicialIntakeSummary, "id"> & {
    capa_json?: { polo_passivo?: { nome: string }[] };
  },
): string {
  const polos = detail.capa_json?.polo_passivo;
  if (!polos || polos.length === 0) return "—";
  const first = polos[0]?.nome;
  return first || "—";
}

// ─── Página ──────────────────────────────────────────────────────────

export default function PrazosIniciaisPage() {
  const { toast } = useToast();

  // Filtros (inputs controlados)
  const [statusFilter, setStatusFilter] = useState<string>("__all__");
  const [cnjFilter, setCnjFilter] = useState<string>("");
  // Filtros efetivamente aplicados (só muda ao clicar em "Aplicar"/"Limpar")
  const [appliedStatus, setAppliedStatus] = useState<string>("__all__");
  const [appliedCnj, setAppliedCnj] = useState<string>("");
  const [offset, setOffset] = useState<number>(0);

  // Dados
  const [items, setItems] = useState<PrazoInicialIntakeSummary[]>([]);
  const [total, setTotal] = useState<number>(0);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Drawer de detalhe (Dialog)
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<PrazoInicialIntakeDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState<boolean>(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState<boolean>(false);

  // ── Carrega lista ───────────────────────────────────────────────────
  const loadIntakes = useCallback(
    async (resetPage = false) => {
      setIsLoading(true);
      setLoadError(null);
      try {
        const nextOffset = resetPage ? 0 : offset;
        const data = await fetchPrazosIniciaisIntakes({
          status: appliedStatus !== "__all__" ? appliedStatus : undefined,
          cnj_number: appliedCnj || undefined,
          limit: PAGE_SIZE,
          offset: nextOffset,
        });
        setItems(data.items);
        setTotal(data.total);
        if (resetPage) setOffset(0);
      } catch (err) {
        const msg = err instanceof Error ? err.message : "Erro ao carregar intakes.";
        setLoadError(msg);
      } finally {
        setIsLoading(false);
      }
    },
    [appliedStatus, appliedCnj, offset],
  );

  useEffect(() => {
    loadIntakes();
  }, [loadIntakes]);

  // ── Detalhe ─────────────────────────────────────────────────────────
  const loadDetail = useCallback(async (id: number) => {
    setDetailLoading(true);
    setDetailError(null);
    setDetail(null);
    try {
      const data = await fetchPrazoInicialDetail(id);
      setDetail(data);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erro ao carregar detalhe.";
      setDetailError(msg);
    } finally {
      setDetailLoading(false);
    }
  }, []);

  useEffect(() => {
    if (selectedId !== null) {
      loadDetail(selectedId);
    } else {
      setDetail(null);
      setDetailError(null);
    }
  }, [selectedId, loadDetail]);

  // ── Ações ───────────────────────────────────────────────────────────
  const onReprocessarCnj = useCallback(async () => {
    if (!selectedId) return;
    setActionLoading(true);
    try {
      await reprocessarPrazoInicialCnj(selectedId);
      toast({
        title: "Reprocessamento solicitado",
        description: "A resolução do CNJ no Legal One foi reiniciada em background.",
      });
      await Promise.all([loadDetail(selectedId), loadIntakes()]);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erro ao reprocessar.";
      toast({ title: "Erro", description: msg, variant: "destructive" });
    } finally {
      setActionLoading(false);
    }
  }, [selectedId, toast, loadDetail, loadIntakes]);

  const onCancelar = useCallback(async () => {
    if (!selectedId) return;
    const ok = window.confirm(
      "Cancelar este intake? A automação não conseguirá mais agendar prazos a partir deste registro.",
    );
    if (!ok) return;
    setActionLoading(true);
    try {
      await cancelarPrazoInicial(selectedId);
      toast({
        title: "Intake cancelado",
        description: "O registro foi marcado como CANCELADO.",
      });
      await Promise.all([loadDetail(selectedId), loadIntakes()]);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erro ao cancelar.";
      toast({ title: "Erro", description: msg, variant: "destructive" });
    } finally {
      setActionLoading(false);
    }
  }, [selectedId, toast, loadDetail, loadIntakes]);

  // ── Paginação ───────────────────────────────────────────────────────
  const pageInfo = useMemo(() => {
    const start = total === 0 ? 0 : offset + 1;
    const end = Math.min(offset + PAGE_SIZE, total);
    const hasPrev = offset > 0;
    const hasNext = offset + PAGE_SIZE < total;
    return { start, end, hasPrev, hasNext };
  }, [offset, total]);

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

  // ── Render ──────────────────────────────────────────────────────────
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <CalendarClock className="h-6 w-6" />
          Agendar Prazos Iniciais
        </h1>
        <p className="text-muted-foreground">
          Fila de processos novos recebidos da automação externa para triagem e agendamento no Legal One.
        </p>
      </div>

      {loadError && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Erro ao carregar</AlertTitle>
          <AlertDescription>{loadError}</AlertDescription>
        </Alert>
      )}

      {/* Filtros */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Filter className="h-4 w-4" />
            Filtros
          </CardTitle>
          <CardDescription>
            Refine por status do intake ou por número CNJ (com ou sem máscara).
          </CardDescription>
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
                  {STATUS_OPTIONS.map((opt) => (
                    <SelectItem key={opt.value} value={opt.value}>
                      {opt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1">
              <Label htmlFor="pin-cnj">CNJ</Label>
              <Input
                id="pin-cnj"
                placeholder="Ex.: 1000123-45.2026.8.26.0100 ou parte dos dígitos"
                value={cnjFilter}
                onChange={(e) => setCnjFilter(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") onAplicarFiltros();
                }}
              />
            </div>

            <div className="flex items-end">
              <Button type="button" onClick={onAplicarFiltros} disabled={isLoading}>
                <Search className="h-4 w-4 mr-2" />
                Aplicar
              </Button>
            </div>
            <div className="flex items-end">
              <Button
                type="button"
                variant="outline"
                onClick={onLimparFiltros}
                disabled={isLoading}
              >
                <Undo2 className="h-4 w-4 mr-2" />
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

      {/* Lista */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Intakes</CardTitle>
          <CardDescription>
            {isLoading
              ? "Carregando..."
              : total === 0
                ? "Nenhum intake encontrado com os filtros atuais."
                : `Exibindo ${pageInfo.start}–${pageInfo.end} de ${total} registro(s).`}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ScrollArea className="w-full">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[160px]">Recebido</TableHead>
                  <TableHead>CNJ</TableHead>
                  <TableHead>Polo passivo</TableHead>
                  <TableHead className="w-[200px]">Status</TableHead>
                  <TableHead className="w-[110px] text-right">Sugestões</TableHead>
                  <TableHead className="w-[120px] text-right">Ações</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {isLoading && items.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={6} className="text-center py-10">
                      <Loader2 className="h-5 w-5 animate-spin inline-block mr-2" />
                      Carregando intakes…
                    </TableCell>
                  </TableRow>
                )}
                {!isLoading && items.length === 0 && !loadError && (
                  <TableRow>
                    <TableCell colSpan={6} className="text-center py-10 text-muted-foreground">
                      Nenhum intake encontrado.
                    </TableCell>
                  </TableRow>
                )}
                {items.map((it) => (
                  <TableRow key={it.id}>
                    <TableCell className="whitespace-nowrap">
                      {formatDateTime(it.received_at)}
                    </TableCell>
                    <TableCell className="font-mono text-xs">
                      {formatCnj(it.cnj_number)}
                    </TableCell>
                    <TableCell>
                      {/* O summary não carrega capa_json; fallback para external_id */}
                      <span className="text-muted-foreground text-sm">
                        {it.pdf_filename_original || it.external_id}
                      </span>
                    </TableCell>
                    <TableCell>
                      <Badge variant={statusBadgeVariant(it.status)}>
                        {STATUS_LABEL[it.status] ?? it.status}
                      </Badge>
                      {it.error_message && (
                        <div className="text-xs text-muted-foreground mt-1 truncate max-w-[200px]" title={it.error_message}>
                          {it.error_message}
                        </div>
                      )}
                    </TableCell>
                    <TableCell className="text-right">{it.sugestoes_count}</TableCell>
                    <TableCell className="text-right">
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => setSelectedId(it.id)}
                      >
                        Detalhes
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </ScrollArea>

          {/* Paginação */}
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
              Próxima
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Dialog de detalhe */}
      <Dialog
        open={selectedId !== null}
        onOpenChange={(open) => {
          if (!open) setSelectedId(null);
        }}
      >
        <DialogContent className="max-w-3xl max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Intake #{selectedId}</DialogTitle>
            <DialogDescription>
              Detalhes do processo recebido e ações disponíveis.
            </DialogDescription>
          </DialogHeader>

          {detailLoading && (
            <div className="py-10 text-center">
              <Loader2 className="h-5 w-5 animate-spin inline-block mr-2" />
              Carregando…
            </div>
          )}

          {detailError && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertTitle>Erro</AlertTitle>
              <AlertDescription>{detailError}</AlertDescription>
            </Alert>
          )}

          {detail && !detailLoading && (
            <div className="space-y-4">
              <div className="grid gap-3 md:grid-cols-2 text-sm">
                <div>
                  <div className="text-muted-foreground text-xs">External ID</div>
                  <div className="font-mono break-all">{detail.external_id}</div>
                </div>
                <div>
                  <div className="text-muted-foreground text-xs">Status</div>
                  <Badge variant={statusBadgeVariant(detail.status)}>
                    {STATUS_LABEL[detail.status] ?? detail.status}
                  </Badge>
                </div>
                <div>
                  <div className="text-muted-foreground text-xs">CNJ</div>
                  <div className="font-mono">{formatCnj(detail.cnj_number)}</div>
                </div>
                <div>
                  <div className="text-muted-foreground text-xs">Processo no L1</div>
                  <div>
                    {detail.lawsuit_id ? (
                      <span>lawsuit_id = {detail.lawsuit_id}</span>
                    ) : (
                      <span className="text-muted-foreground italic">Não resolvido</span>
                    )}
                  </div>
                </div>
                <div>
                  <div className="text-muted-foreground text-xs">Escritório</div>
                  <div>
                    {detail.office_id ? `office_id = ${detail.office_id}` : (
                      <span className="text-muted-foreground italic">—</span>
                    )}
                  </div>
                </div>
                <div>
                  <div className="text-muted-foreground text-xs">Recebido em</div>
                  <div>{formatDateTime(detail.received_at)}</div>
                </div>
              </div>

              {detail.error_message && (
                <Alert variant="destructive">
                  <AlertCircle className="h-4 w-4" />
                  <AlertTitle>Mensagem de erro</AlertTitle>
                  <AlertDescription className="whitespace-pre-wrap">
                    {detail.error_message}
                  </AlertDescription>
                </Alert>
              )}

              <Separator />

              <div>
                <div className="text-sm font-semibold mb-2">Capa do processo</div>
                <div className="grid gap-2 md:grid-cols-2 text-sm">
                  <div>
                    <div className="text-muted-foreground text-xs">Tribunal / Vara</div>
                    <div>
                      {(detail.capa_json.tribunal || "—") + " · " + (detail.capa_json.vara || "—")}
                    </div>
                  </div>
                  <div>
                    <div className="text-muted-foreground text-xs">Classe</div>
                    <div>{detail.capa_json.classe || "—"}</div>
                  </div>
                  <div>
                    <div className="text-muted-foreground text-xs">Polo ativo</div>
                    <div>
                      {(detail.capa_json.polo_ativo || [])
                        .map((p) => p.nome)
                        .join(", ") || "—"}
                    </div>
                  </div>
                  <div>
                    <div className="text-muted-foreground text-xs">Polo passivo</div>
                    <div>{primeiroPoloPassivo(detail)}</div>
                  </div>
                </div>
              </div>

              <Separator />

              <div>
                <div className="text-sm font-semibold mb-2">Habilitação (PDF)</div>
                <div className="flex items-center gap-3 text-sm">
                  <FileText className="h-4 w-4" />
                  <span>
                    {detail.pdf_filename_original || "habilitacao.pdf"}
                    <span className="text-muted-foreground ml-2">
                      ({formatBytes(detail.pdf_bytes)})
                    </span>
                  </span>
                  {detail.pdf_bytes ? (
                    <Button
                      asChild
                      size="sm"
                      variant="outline"
                      className="ml-auto"
                    >
                      <a
                        href={prazoInicialPdfUrl(detail.id)}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        <ExternalLink className="h-4 w-4 mr-1" />
                        Abrir em nova aba
                      </a>
                    </Button>
                  ) : (
                    <span className="text-muted-foreground text-xs ml-auto">
                      Retenção expirada
                    </span>
                  )}
                </div>
              </div>

              {detail.sugestoes.length > 0 && (
                <>
                  <Separator />
                  <div>
                    <div className="text-sm font-semibold mb-2">
                      Sugestões ({detail.sugestoes.length})
                    </div>
                    <div className="text-xs text-muted-foreground mb-3">
                      A revisão das sugestões está no pipeline da Fase 4 — por enquanto,
                      listagem somente-leitura.
                    </div>
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Tipo</TableHead>
                          <TableHead>Data base</TableHead>
                          <TableHead>Prazo</TableHead>
                          <TableHead>Confiança</TableHead>
                          <TableHead>Revisão</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {detail.sugestoes.map((s) => (
                          <TableRow key={s.id}>
                            <TableCell>
                              {s.tipo_prazo}
                              {s.subtipo ? (
                                <span className="text-muted-foreground text-xs ml-1">
                                  / {s.subtipo}
                                </span>
                              ) : null}
                            </TableCell>
                            <TableCell>{s.data_base || "—"}</TableCell>
                            <TableCell>
                              {s.prazo_dias
                                ? `${s.prazo_dias} ${s.prazo_tipo || ""}`.trim()
                                : s.audiencia_data
                                  ? `Audiência ${s.audiencia_data}`
                                  : "—"}
                            </TableCell>
                            <TableCell>{s.confianca || "—"}</TableCell>
                            <TableCell>{s.review_status}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                </>
              )}
            </div>
          )}

          <DialogFooter className="gap-2">
            <Button
              variant="outline"
              onClick={onReprocessarCnj}
              disabled={
                !detail ||
                actionLoading ||
                !(
                  detail.status === "RECEBIDO" ||
                  detail.status === "PROCESSO_NAO_ENCONTRADO"
                )
              }
              title="Disponível em RECEBIDO / PROCESSO_NAO_ENCONTRADO"
            >
              {actionLoading ? (
                <Loader2 className="h-4 w-4 animate-spin mr-2" />
              ) : (
                <RefreshCw className="h-4 w-4 mr-2" />
              )}
              Reprocessar CNJ
            </Button>
            <Button
              variant="destructive"
              onClick={onCancelar}
              disabled={
                !detail ||
                actionLoading ||
                detail.status === "CANCELADO" ||
                detail.status === "CONCLUIDO"
              }
            >
              <XCircle className="h-4 w-4 mr-2" />
              Cancelar intake
            </Button>
            <Button variant="secondary" onClick={() => setSelectedId(null)}>
              Fechar
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
