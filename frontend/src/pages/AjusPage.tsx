import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  Ban,
  CheckCircle2,
  Clock,
  FileText,
  Loader2,
  Plus,
  RefreshCw,
  RotateCcw,
  Send,
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
  cancelAjusAndamento,
  createAjusCodAndamento,
  deleteAjusCodAndamento,
  dispatchAjusAndamentosPending,
  fetchAjusAndamentos,
  fetchAjusCodAndamento,
  retryAjusAndamento,
  updateAjusCodAndamento,
} from "@/services/api";
import type {
  AjusAndamentoQueueItem,
  AjusCodAndamento,
  AjusQueueStatus,
} from "@/types/api";
import { CodAndamentoFormDialog } from "@/components/ajus/CodAndamentoFormDialog";
import { ClassificacaoTab } from "@/components/ajus/ClassificacaoTab";

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

  // ─── Aba Códigos ───────────────────────────────────────────────────
  const [codigos, setCodigos] = useState<AjusCodAndamento[]>([]);
  const [codigosLoading, setCodigosLoading] = useState(false);
  const [codDialogOpen, setCodDialogOpen] = useState(false);
  const [editingCod, setEditingCod] = useState<AjusCodAndamento | null>(null);

  // ─── Loaders ───────────────────────────────────────────────────────
  const loadAndamentos = useCallback(async () => {
    setAndamentosLoading(true);
    try {
      const filters: Parameters<typeof fetchAjusAndamentos>[0] = { limit: 100 };
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
  }, [statusFilter, cnjFilter, toast]);

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
              <Table>
                <TableHeader>
                  <TableRow>
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
                      <TableCell colSpan={9} className="text-center text-sm text-muted-foreground py-8">
                        Nenhum andamento na fila com os filtros atuais.
                      </TableCell>
                    </TableRow>
                  )}
                  {andamentos.map((item) => {
                    const badge = STATUS_BADGE[item.status] || {
                      label: item.status,
                      className: "",
                    };
                    return (
                      <TableRow key={item.id}>
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
                            <FileText className="h-3.5 w-3.5 text-emerald-600" />
                          ) : (
                            <span className="text-xs text-muted-foreground">—</span>
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
    </div>
  );
}
