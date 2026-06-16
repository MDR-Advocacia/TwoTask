// frontend/src/pages/CitacoesBMPage.tsx
//
// Citações BM — seção dentro de "Tratamento de Publicações".
// Monitora processos do Banco Master (Réu) via DataJud (API pública do CNJ)
// pra detectar a CITAÇÃO efetiva, gatilho da habilitação. O sistema só TRAZ
// as movimentações; quem decide se houve citação é o operador.

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useToast } from "@/hooks/use-toast";
import {
  Gavel,
  RefreshCw,
  Plus,
  ExternalLink,
  Search,
  CheckCircle2,
  XCircle,
  Eye,
  AlertTriangle,
  Inbox,
} from "lucide-react";
import {
  CitacaoBMDetail,
  CitacaoBMMovimento,
  CitacaoBMProcesso,
  CitacaoBMSummary,
  getCitacaoProcesso,
  getCitacaoSummary,
  ingestCitacaoL1,
  ingestCitacaoList,
  listCitacaoProcessos,
  markCitacaoRead,
  scanCitacaoAll,
  scanCitacaoProcesso,
  setCitacaoStatus,
  StatusCitacao,
} from "@/services/citacoesBm";

function fmtDateTime(value: string | null): string {
  if (!value) return "—";
  const d = new Date(value);
  if (isNaN(d.getTime())) return "—";
  return d.toLocaleString("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function fmtDate(value: string | null): string {
  if (!value) return "—";
  const d = new Date(value);
  if (isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("pt-BR");
}

function StatusBadge({ status }: { status: StatusCitacao }) {
  if (status === "CITADO")
    return <Badge className="bg-emerald-600 hover:bg-emerald-600">Citado</Badge>;
  if (status === "NAO_CITADO")
    return <Badge variant="outline">Não citado</Badge>;
  return <Badge variant="secondary">Pendente</Badge>;
}

function complementoResumo(comp: Record<string, unknown> | null): string {
  if (!comp || typeof comp !== "object") return "";
  const nome = (comp["nome"] as string) || "";
  const valor = (comp["valor"] as string) ?? "";
  const desc = (comp["descricao"] as string) || "";
  if (nome && valor !== "") return `${nome}: ${valor}`;
  return nome || desc || String(valor);
}

const PAGE_SIZES = [25, 50, 100];

export default function CitacoesBMPage() {
  const { toast } = useToast();
  const [summary, setSummary] = useState<CitacaoBMSummary | null>(null);
  const [items, setItems] = useState<CitacaoBMProcesso[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);

  // Filtros
  const [status, setStatus] = useState<StatusCitacao | "ALL">("ALL");
  const [arquivados, setArquivados] = useState<"ativos" | "arquivados" | "todos">(
    "ativos",
  );
  const [apenasComNovos, setApenasComNovos] = useState(false);
  const [q, setQ] = useState("");

  // Paginação
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(25);

  // Ingestão
  const [addOpen, setAddOpen] = useState(false);
  const [listText, setListText] = useState("");
  const [dataCorte, setDataCorte] = useState("");
  const [ingesting, setIngesting] = useState(false);

  // Detalhe
  const [detailOpen, setDetailOpen] = useState(false);
  const [detail, setDetail] = useState<CitacaoBMDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [actionBusy, setActionBusy] = useState(false);

  const [scanningAll, setScanningAll] = useState(false);

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  const loadList = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listCitacaoProcessos({
        status: status === "ALL" ? "" : status,
        apenas_com_novos: apenasComNovos,
        arquivados,
        q: q.trim() || undefined,
        limit: pageSize,
        offset: page * pageSize,
      });
      setItems(res.items);
      setTotal(res.total);
    } catch (e) {
      toast({
        title: "Erro ao carregar",
        description: String(e),
        variant: "destructive",
      });
    } finally {
      setLoading(false);
    }
  }, [status, apenasComNovos, arquivados, q, page, pageSize, toast]);

  const loadSummary = useCallback(async () => {
    try {
      setSummary(await getCitacaoSummary());
    } catch {
      /* silencioso */
    }
  }, []);

  useEffect(() => {
    loadList();
  }, [loadList]);
  useEffect(() => {
    loadSummary();
  }, [loadSummary]);

  // Volta pra página 0 quando muda filtro.
  useEffect(() => {
    setPage(0);
  }, [status, arquivados, apenasComNovos]);

  const refresh = useCallback(() => {
    loadList();
    loadSummary();
  }, [loadList, loadSummary]);

  const handleIngestList = async () => {
    if (!listText.trim()) return;
    setIngesting(true);
    try {
      const res = (await ingestCitacaoList(listText)) as Record<string, number | unknown>;
      toast({
        title: "Lista processada",
        description: `${res.criados as number} criados · ${
          (res.duplicados as unknown[])?.length ?? 0
        } duplicados · ${(res.invalidos as unknown[])?.length ?? 0} inválidos · ${
          res.l1_encontrados as number
        } resolvidos no L1`,
      });
      setListText("");
      setAddOpen(false);
      refresh();
    } catch (e) {
      toast({ title: "Erro", description: String(e), variant: "destructive" });
    } finally {
      setIngesting(false);
    }
  };

  const handleIngestL1 = async () => {
    setIngesting(true);
    try {
      const res = (await ingestCitacaoL1(dataCorte || undefined)) as Record<
        string,
        unknown
      >;
      toast({
        title: "Importação do L1",
        description: `${res.criados as number} novos criados (de ${
          res.encontrados_l1 as number
        } no L1, corte ${res.data_corte as string})`,
      });
      setAddOpen(false);
      refresh();
    } catch (e) {
      toast({ title: "Erro", description: String(e), variant: "destructive" });
    } finally {
      setIngesting(false);
    }
  };

  const handleScanAll = async () => {
    setScanningAll(true);
    try {
      await scanCitacaoAll();
      toast({
        title: "Varredura iniciada",
        description:
          "A consulta ao DataJud roda em segundo plano. Atualize em alguns minutos.",
      });
    } catch (e) {
      toast({ title: "Erro", description: String(e), variant: "destructive" });
    } finally {
      setScanningAll(false);
    }
  };

  const openDetail = async (id: number) => {
    setDetailOpen(true);
    setDetailLoading(true);
    setDetail(null);
    try {
      const d = await getCitacaoProcesso(id);
      setDetail(d);
      // Ao abrir, marca os movimentos como lidos (operador está vendo).
      if (d.novos_movimentos > 0) {
        await markCitacaoRead(id);
        refresh();
      }
    } catch (e) {
      toast({ title: "Erro", description: String(e), variant: "destructive" });
    } finally {
      setDetailLoading(false);
    }
  };

  const handleScanOne = async (id: number) => {
    setActionBusy(true);
    try {
      const r = await scanCitacaoProcesso(id);
      toast({
        title: "Atualizado",
        description:
          r.status === "OK"
            ? `${r.novos} movimento(s) novo(s).`
            : r.status === "SEM_HITS"
              ? "DataJud ainda não tem este processo (lag do tribunal)."
              : "Falha na consulta.",
      });
      const d = await getCitacaoProcesso(id);
      setDetail(d);
      refresh();
    } catch (e) {
      toast({ title: "Erro", description: String(e), variant: "destructive" });
    } finally {
      setActionBusy(false);
    }
  };

  const handleSetStatus = async (id: number, novoStatus: StatusCitacao) => {
    setActionBusy(true);
    try {
      await setCitacaoStatus(id, novoStatus);
      toast({
        title:
          novoStatus === "CITADO"
            ? "Marcado como CITADO"
            : novoStatus === "NAO_CITADO"
              ? "Marcado como não citado"
              : "Reaberto",
        description:
          novoStatus === "CITADO"
            ? "Processo arquivado do monitoramento. Abra no LegalOne para habilitar."
            : "Segue em monitoramento.",
      });
      const d = await getCitacaoProcesso(id);
      setDetail(d);
      refresh();
    } catch (e) {
      toast({ title: "Erro", description: String(e), variant: "destructive" });
    } finally {
      setActionBusy(false);
    }
  };

  const candidatos = useMemo(
    () => (detail ? detail.movimentos.filter((m) => m.is_candidato_citacao) : []),
    [detail],
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
          <Gavel className="h-6 w-6 text-primary" />
          Citações BM
        </h1>
        <p className="text-sm text-muted-foreground">
          Monitoramento da citação efetiva (Banco Master / Réu) via DataJud. O
          sistema traz as movimentações; <strong>você</strong> confirma a
          citação e é direcionado ao LegalOne para habilitar.
        </p>
      </div>

      {/* Cards de resumo */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 lg:grid-cols-6">
        <SummaryCard label="Monitorando" value={summary?.monitorando} />
        <SummaryCard label="Pendentes" value={summary?.pendentes} />
        <SummaryCard
          label="Com novidade"
          value={summary?.com_novos}
          accent="text-blue-600"
        />
        <SummaryCard
          label="Possível citação"
          value={summary?.com_candidato}
          accent="text-amber-600"
        />
        <SummaryCard
          label="Citados"
          value={summary?.citados}
          accent="text-emerald-600"
        />
        <SummaryCard label="Não citados" value={summary?.nao_citados} />
      </div>

      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-2">
        <Button onClick={() => setAddOpen(true)} className="gap-2">
          <Plus className="h-4 w-4" /> Adicionar processos
        </Button>
        <Button
          variant="outline"
          onClick={handleScanAll}
          disabled={scanningAll}
          className="gap-2"
        >
          <RefreshCw
            className={`h-4 w-4 ${scanningAll ? "animate-spin" : ""}`}
          />
          Atualizar agora (todos)
        </Button>

        <div className="ml-auto flex flex-wrap items-center gap-2">
          <div className="relative">
            <Search className="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Buscar CNJ…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  setPage(0);
                  loadList();
                }
              }}
              className="w-48 pl-8"
            />
          </div>
          <Select value={status} onValueChange={(v) => setStatus(v as never)}>
            <SelectTrigger className="w-36">
              <SelectValue placeholder="Status" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="ALL">Todos status</SelectItem>
              <SelectItem value="PENDENTE">Pendente</SelectItem>
              <SelectItem value="CITADO">Citado</SelectItem>
              <SelectItem value="NAO_CITADO">Não citado</SelectItem>
            </SelectContent>
          </Select>
          <Select
            value={arquivados}
            onValueChange={(v) => setArquivados(v as never)}
          >
            <SelectTrigger className="w-36">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="ativos">Ativos</SelectItem>
              <SelectItem value="arquivados">Arquivados</SelectItem>
              <SelectItem value="todos">Todos</SelectItem>
            </SelectContent>
          </Select>
          <Button
            variant={apenasComNovos ? "default" : "outline"}
            onClick={() => setApenasComNovos((v) => !v)}
            size="sm"
          >
            Só com novidade
          </Button>
        </div>
      </div>

      {/* Tabela */}
      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>CNJ</TableHead>
                <TableHead>UF</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Movimentações</TableHead>
                <TableHead>Última movimentação</TableHead>
                <TableHead>Última varredura</TableHead>
                <TableHead className="text-right">Ações</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading ? (
                <TableRow>
                  <TableCell colSpan={7} className="py-10 text-center text-muted-foreground">
                    Carregando…
                  </TableCell>
                </TableRow>
              ) : items.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={7} className="py-10 text-center text-muted-foreground">
                    <Inbox className="mx-auto mb-2 h-8 w-8 opacity-50" />
                    Nenhum processo. Clique em “Adicionar processos”.
                  </TableCell>
                </TableRow>
              ) : (
                items.map((p) => (
                  <TableRow
                    key={p.id}
                    className="cursor-pointer"
                    onClick={() => openDetail(p.id)}
                  >
                    <TableCell className="font-mono text-xs">
                      {p.cnj_mask || p.cnj}
                    </TableCell>
                    <TableCell>{p.uf || "—"}</TableCell>
                    <TableCell>
                      <StatusBadge status={p.status_citacao} />
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-wrap items-center gap-1">
                        {p.tem_candidato_citacao && (
                          <Badge className="gap-1 bg-amber-500 hover:bg-amber-500">
                            <AlertTriangle className="h-3 w-3" /> citação?
                          </Badge>
                        )}
                        {p.novos_movimentos > 0 && (
                          <Badge className="bg-blue-600 hover:bg-blue-600">
                            {p.novos_movimentos} novo(s)
                          </Badge>
                        )}
                        <span className="text-xs text-muted-foreground">
                          {p.total_movimentos} total
                        </span>
                        {p.last_scan_status === "SEM_HITS" && (
                          <span className="text-xs text-muted-foreground italic">
                            (s/ dados no DataJud)
                          </span>
                        )}
                      </div>
                    </TableCell>
                    <TableCell className="text-xs">
                      {fmtDateTime(p.last_movement_at)}
                    </TableCell>
                    <TableCell className="text-xs">
                      {fmtDateTime(p.last_scan_at)}
                    </TableCell>
                    <TableCell
                      className="text-right"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <div className="flex items-center justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => openDetail(p.id)}
                          title="Ver movimentações"
                        >
                          <Eye className="h-4 w-4" />
                        </Button>
                        {p.l1_url && (
                          <a
                            href={p.l1_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            title="Abrir pasta no LegalOne"
                          >
                            <Button variant="ghost" size="icon">
                              <ExternalLink className="h-4 w-4" />
                            </Button>
                          </a>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* Paginação */}
      <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
        <div className="text-muted-foreground">
          {total === 0
            ? "0 resultados"
            : `${page * pageSize + 1}–${Math.min(
                (page + 1) * pageSize,
                total,
              )} de ${total}`}
        </div>
        <div className="flex items-center gap-2">
          <Select
            value={String(pageSize)}
            onValueChange={(v) => {
              setPageSize(Number(v));
              setPage(0);
            }}
          >
            <SelectTrigger className="w-24">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PAGE_SIZES.map((s) => (
                <SelectItem key={s} value={String(s)}>
                  {s}/pág
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            variant="outline"
            size="sm"
            disabled={page === 0}
            onClick={() => setPage((p) => Math.max(0, p - 1))}
          >
            Anterior
          </Button>
          <span className="text-muted-foreground">
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
      </div>

      {/* Dialog: Adicionar processos */}
      <Dialog open={addOpen} onOpenChange={setAddOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>Adicionar processos ao monitoramento</DialogTitle>
            <DialogDescription>
              Cole uma lista de CNJs ou puxe automaticamente do LegalOne.
            </DialogDescription>
          </DialogHeader>
          <Tabs defaultValue="lista">
            <TabsList className="w-full">
              <TabsTrigger value="lista" className="flex-1">
                Colar lista de CNJ
              </TabsTrigger>
              <TabsTrigger value="l1" className="flex-1">
                Importar do LegalOne
              </TabsTrigger>
            </TabsList>
            <TabsContent value="lista" className="mt-3 flex flex-col gap-3">
              <Textarea
                rows={8}
                placeholder={"Um CNJ por linha (aceita máscara ou só dígitos)…"}
                value={listText}
                onChange={(e) => setListText(e.target.value)}
              />
              <Button onClick={handleIngestList} disabled={ingesting}>
                {ingesting ? "Processando…" : "Adicionar lista"}
              </Button>
            </TabsContent>
            <TabsContent value="l1" className="mt-3 flex flex-col gap-3">
              <p className="text-sm text-muted-foreground">
                Puxa do escritório <strong>Banco Master / Réu</strong> os
                processos com pasta cadastrada a partir da data de corte.
                Em branco = hoje.
              </p>
              <div className="flex flex-col gap-1">
                <label className="text-xs text-muted-foreground">
                  Data de corte (creationDate ≥)
                </label>
                <Input
                  type="date"
                  value={dataCorte}
                  onChange={(e) => setDataCorte(e.target.value)}
                  className="w-48"
                />
              </div>
              <Button onClick={handleIngestL1} disabled={ingesting}>
                {ingesting ? "Importando…" : "Importar do LegalOne"}
              </Button>
            </TabsContent>
          </Tabs>
        </DialogContent>
      </Dialog>

      {/* Dialog: Detalhe / timeline */}
      <Dialog open={detailOpen} onOpenChange={setDetailOpen}>
        <DialogContent className="max-h-[90vh] max-w-3xl overflow-hidden">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 font-mono text-base">
              {detail?.cnj_mask || detail?.cnj}
              {detail && <StatusBadge status={detail.status_citacao} />}
            </DialogTitle>
            <DialogDescription>
              {detail?.uf ? `${detail.uf} · ` : ""}
              {detail?.tribunal_alias || ""}
              {detail?.l1_creation_date
                ? ` · pasta criada em ${fmtDate(detail.l1_creation_date)}`
                : ""}
            </DialogDescription>
          </DialogHeader>

          {detailLoading ? (
            <div className="py-10 text-center text-muted-foreground">
              Carregando…
            </div>
          ) : detail ? (
            <div className="flex flex-col gap-3 overflow-hidden">
              {/* Ações */}
              <div className="flex flex-wrap items-center gap-2">
                {detail.status_citacao !== "CITADO" && (
                  <Button
                    size="sm"
                    className="gap-1 bg-emerald-600 hover:bg-emerald-700"
                    disabled={actionBusy}
                    onClick={() => handleSetStatus(detail.id, "CITADO")}
                  >
                    <CheckCircle2 className="h-4 w-4" /> Marcar CITADO
                  </Button>
                )}
                {detail.status_citacao !== "NAO_CITADO" && (
                  <Button
                    size="sm"
                    variant="outline"
                    className="gap-1"
                    disabled={actionBusy}
                    onClick={() => handleSetStatus(detail.id, "NAO_CITADO")}
                  >
                    <XCircle className="h-4 w-4" /> Não é citação
                  </Button>
                )}
                {detail.status_citacao !== "PENDENTE" && (
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={actionBusy}
                    onClick={() => handleSetStatus(detail.id, "PENDENTE")}
                  >
                    Reabrir
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="outline"
                  className="gap-1"
                  disabled={actionBusy}
                  onClick={() => handleScanOne(detail.id)}
                >
                  <RefreshCw className="h-4 w-4" /> Atualizar agora
                </Button>
                {detail.l1_url && (
                  <a
                    href={detail.l1_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="ml-auto"
                  >
                    <Button size="sm" className="gap-1">
                      <ExternalLink className="h-4 w-4" /> Abrir no LegalOne
                    </Button>
                  </a>
                )}
              </div>

              {detail.status_citacao === "CITADO" && detail.citado_por_nome && (
                <p className="text-xs text-emerald-700">
                  Citado marcado por {detail.citado_por_nome} em{" "}
                  {fmtDateTime(detail.citado_em)} · arquivado do monitoramento.
                </p>
              )}

              {/* Candidatos destacados */}
              {candidatos.length > 0 && (
                <div className="rounded-md border border-amber-300 bg-amber-50 p-2">
                  <div className="mb-1 flex items-center gap-1 text-xs font-semibold text-amber-700">
                    <AlertTriangle className="h-3.5 w-3.5" />
                    {candidatos.length} movimento(s) candidato(s) a citação
                  </div>
                  <div className="flex flex-col gap-1">
                    {candidatos.map((m) => (
                      <MovimentoLine key={`c-${m.id}`} m={m} highlight />
                    ))}
                  </div>
                </div>
              )}

              {/* Timeline completa */}
              <div className="text-xs font-semibold text-muted-foreground">
                Linha do tempo ({detail.movimentos.length})
              </div>
              <ScrollArea className="h-[40vh] rounded-md border">
                <div className="flex flex-col divide-y">
                  {detail.movimentos.map((m) => (
                    <MovimentoLine key={m.id} m={m} />
                  ))}
                  {detail.movimentos.length === 0 && (
                    <div className="p-4 text-center text-sm text-muted-foreground">
                      Sem movimentações capturadas ainda.
                      {detail.last_scan_status === "SEM_HITS" &&
                        " O DataJud ainda não tem este processo."}
                    </div>
                  )}
                </div>
              </ScrollArea>
            </div>
          ) : (
            <div className="py-10 text-center text-muted-foreground">
              Não foi possível carregar.
            </div>
          )}

          <DialogFooter>
            <Button variant="outline" onClick={() => setDetailOpen(false)}>
              Fechar
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function SummaryCard({
  label,
  value,
  accent,
}: {
  label: string;
  value?: number;
  accent?: string;
}) {
  return (
    <Card>
      <CardHeader className="p-3 pb-1">
        <CardTitle className="text-xs font-medium text-muted-foreground">
          {label}
        </CardTitle>
      </CardHeader>
      <CardContent className="p-3 pt-0">
        <div className={`text-2xl font-semibold ${accent || ""}`}>
          {value ?? "—"}
        </div>
      </CardContent>
    </Card>
  );
}

function MovimentoLine({
  m,
  highlight,
}: {
  m: CitacaoBMMovimento;
  highlight?: boolean;
}) {
  const comps = Array.isArray(m.complementos)
    ? m.complementos.map(complementoResumo).filter(Boolean)
    : [];
  return (
    <div
      className={`flex flex-col gap-0.5 px-3 py-2 ${
        highlight ? "" : !m.lido ? "bg-blue-50/60" : ""
      }`}
    >
      <div className="flex items-center gap-2">
        <span className="text-xs text-muted-foreground">
          {fmtDateTime(m.data_hora)}
        </span>
        {m.grau && (
          <span className="rounded bg-muted px-1 text-[10px] uppercase text-muted-foreground">
            {m.grau}
          </span>
        )}
        {m.is_candidato_citacao && (
          <Badge className="gap-1 bg-amber-500 px-1 py-0 text-[10px] hover:bg-amber-500">
            <AlertTriangle className="h-2.5 w-2.5" />
            {m.cit_match_termo}
          </Badge>
        )}
        {!m.lido && !highlight && (
          <span className="h-1.5 w-1.5 rounded-full bg-blue-600" title="Novo" />
        )}
      </div>
      <div className="text-sm">
        {m.nome}
        {m.codigo_tpu ? (
          <span className="ml-1 text-[10px] text-muted-foreground">
            #{m.codigo_tpu}
          </span>
        ) : null}
      </div>
      {comps.length > 0 && (
        <div className="text-xs text-muted-foreground">{comps.join(" · ")}</div>
      )}
    </div>
  );
}
