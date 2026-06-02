import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  Ban,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Download,
  Loader2,
  PlayCircle,
  RefreshCw,
  Search,
  ShieldAlert,
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
import { useToast } from "@/hooks/use-toast";
import {
  cancelVarreduraRun,
  createVarreduraRun,
  createVarreduraRunFromList,
  downloadVarreduraRunXlsx,
  fetchVarreduraAchados,
  fetchVarreduraOffices,
  fetchVarreduraPatterns,
  fetchVarreduraRun,
  fetchVarreduraRuns,
  recoverVarreduraZombies,
  updateVarreduraAchado,
  type VarreduraAchado,
  type VarreduraOfficeOption,
  type VarreduraPattern,
  type VarreduraRun,
} from "@/services/api";

// ── Constantes ────────────────────────────────────────────────────────

const TIPOS_EVENTO_LABELS: Record<string, string> = {
  audiencia_designada: "Audiência designada",
  audiencia_cancelada: "Audiência cancelada",
  sentenca: "Sentença",
  revelia: "Revelia",
  transito_julgado: "Trânsito em julgado",
  arquivamento: "Arquivamento",
};

const TIPOS_EVENTO_COLORS: Record<string, string> = {
  audiencia_designada: "bg-blue-100 text-blue-900 border-blue-300",
  audiencia_cancelada: "bg-orange-100 text-orange-900 border-orange-300",
  sentenca: "bg-purple-100 text-purple-900 border-purple-300",
  revelia: "bg-red-100 text-red-900 border-red-300",
  transito_julgado: "bg-emerald-100 text-emerald-900 border-emerald-300",
  arquivamento: "bg-zinc-100 text-zinc-900 border-zinc-300",
};

const RUN_STATUS_LABELS: Record<string, string> = {
  RUNNING: "Em execução",
  DONE: "Concluída",
  FAILED: "Falhou",
  CANCELLED: "Cancelada",
};

const QUEUE_STATUS_LABELS: Record<string, string> = {
  PENDENTE: "Pendente",
  PROCESSANDO: "Processando",
  CONCLUIDO: "Concluído",
  FALHA: "Falha",
};

function formatDateTime(value: string | null | undefined) {
  if (!value) return "—";
  try {
    return new Intl.DateTimeFormat("pt-BR", {
      dateStyle: "short",
      timeStyle: "medium",
    }).format(new Date(value));
  } catch {
    return value;
  }
}

function formatDate(value: string | null | undefined) {
  if (!value) return "—";
  // Backend manda andamento_data ISO YYYY-MM-DD; queremos pt-BR.
  const m = value.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (m) {
    return `${m[3]}/${m[2]}/${m[1]}`;
  }
  return value;
}

function runStatusBadge(status: string) {
  const label = RUN_STATUS_LABELS[status] || status;
  if (status === "RUNNING") {
    return (
      <Badge className="bg-blue-100 text-blue-900 border-blue-300">
        <Loader2 className="h-3 w-3 mr-1 animate-spin" />
        {label}
      </Badge>
    );
  }
  if (status === "DONE") {
    return (
      <Badge className="bg-emerald-100 text-emerald-900 border-emerald-300">
        <CheckCircle2 className="h-3 w-3 mr-1" />
        {label}
      </Badge>
    );
  }
  if (status === "FAILED") {
    return (
      <Badge className="bg-red-100 text-red-900 border-red-300">
        <AlertCircle className="h-3 w-3 mr-1" />
        {label}
      </Badge>
    );
  }
  if (status === "CANCELLED") {
    return (
      <Badge className="bg-zinc-200 text-zinc-800 border-zinc-300">
        <Ban className="h-3 w-3 mr-1" />
        {label}
      </Badge>
    );
  }
  return <Badge variant="outline">{label}</Badge>;
}

// ── Pagina principal ──────────────────────────────────────────────────

export default function VarreduraAndamentosPage() {
  const { toast } = useToast();
  const [tab, setTab] = useState<"runs" | "achados" | "padroes">("runs");
  const [patterns, setPatterns] = useState<VarreduraPattern[]>([]);

  // Modal de nova varredura
  const [isCreateOpen, setIsCreateOpen] = useState(false);

  // Runs
  const [runs, setRuns] = useState<VarreduraRun[]>([]);
  const [runsTotal, setRunsTotal] = useState(0);
  const [runsLoading, setRunsLoading] = useState(false);
  const [runsOffset, setRunsOffset] = useState(0);
  const [runsLimit] = useState(25);
  const [runsStatusFilter, setRunsStatusFilter] = useState<string>("__all__");

  // Achados
  const [achados, setAchados] = useState<VarreduraAchado[]>([]);
  const [achadosTotal, setAchadosTotal] = useState(0);
  const [achadosLoading, setAchadosLoading] = useState(false);
  const [achadosOffset, setAchadosOffset] = useState(0);
  const [achadosLimit] = useState(50);
  const [filterTipoEvento, setFilterTipoEvento] = useState<string>("__all__");
  const [filterTratado, setFilterTratado] = useState<string>("__all__");
  const [filterRunId, setFilterRunId] = useState<string>("");
  const [filterCnj, setFilterCnj] = useState<string>("");

  // Achado expandido (mostra texto completo)
  const [expandedAchadoId, setExpandedAchadoId] = useState<number | null>(null);

  const loadRuns = useCallback(async () => {
    setRunsLoading(true);
    try {
      const data = await fetchVarreduraRuns({
        status:
          runsStatusFilter !== "__all__" ? runsStatusFilter : undefined,
        limit: runsLimit,
        offset: runsOffset,
      });
      setRuns(data.items);
      setRunsTotal(data.total);
    } catch (err) {
      toast({
        title: "Erro ao carregar varreduras",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setRunsLoading(false);
    }
  }, [runsStatusFilter, runsLimit, runsOffset, toast]);

  const loadAchados = useCallback(async () => {
    setAchadosLoading(true);
    try {
      const runIdNum = filterRunId.trim()
        ? parseInt(filterRunId, 10)
        : undefined;
      const tratadoBool =
        filterTratado === "__all__"
          ? undefined
          : filterTratado === "tratado";
      const data = await fetchVarreduraAchados({
        run_id: Number.isFinite(runIdNum as number) ? runIdNum : undefined,
        tipo_evento:
          filterTipoEvento !== "__all__" ? filterTipoEvento : undefined,
        tratado: tratadoBool,
        cnj_search: filterCnj.trim() || undefined,
        limit: achadosLimit,
        offset: achadosOffset,
      });
      setAchados(data.items);
      setAchadosTotal(data.total);
    } catch (err) {
      toast({
        title: "Erro ao carregar achados",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setAchadosLoading(false);
    }
  }, [
    filterRunId,
    filterTipoEvento,
    filterTratado,
    filterCnj,
    achadosLimit,
    achadosOffset,
    toast,
  ]);

  useEffect(() => {
    if (tab === "runs") loadRuns();
    if (tab === "achados") loadAchados();
  }, [tab, loadRuns, loadAchados]);

  // Patterns: 1 fetch no mount
  useEffect(() => {
    fetchVarreduraPatterns()
      .then((d) => setPatterns(d.patterns))
      .catch(() => {});
  }, []);

  // Auto-refresh runs em execução
  useEffect(() => {
    if (tab !== "runs") return;
    const hasRunning = runs.some((r) => r.status === "RUNNING");
    if (!hasRunning) return;
    const id = setInterval(() => {
      loadRuns();
    }, 8000);
    return () => clearInterval(id);
  }, [tab, runs, loadRuns]);

  const handleCancelRun = async (runId: number) => {
    if (!confirm(`Cancelar a varredura #${runId}?`)) return;
    try {
      await cancelVarreduraRun(runId);
      toast({ title: "Varredura cancelada", description: `Run #${runId}` });
      loadRuns();
    } catch (err) {
      toast({
        title: "Erro ao cancelar",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    }
  };

  const handleRecoverZombies = async (runId: number) => {
    try {
      const res = await recoverVarreduraZombies(runId, 10);
      toast({
        title: "Recover de zumbis",
        description: `${res.recovered_count} item(s) devolvidos pra PENDENTE.`,
      });
      loadRuns();
    } catch (err) {
      toast({
        title: "Erro no recover",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    }
  };

  const handleToggleTratado = async (
    achado: VarreduraAchado,
    novoTratado: boolean,
    observacao?: string,
  ) => {
    try {
      const updated = await updateVarreduraAchado(achado.id, {
        tratado: novoTratado,
        observacao,
      });
      setAchados((prev) =>
        prev.map((a) => (a.id === updated.id ? updated : a)),
      );
    } catch (err) {
      toast({
        title: "Erro ao atualizar achado",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    }
  };

  return (
    <div className="container mx-auto p-6 space-y-6">
      <div className="flex items-start justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-2xl font-bold">Varredura de Andamentos</h1>
          <p className="text-sm text-muted-foreground mt-1 max-w-3xl">
            Entra nos processos onde o MDR é responsável master + cliente
            no polo passivo, abre a aba <strong>Andamentos</strong> de cada
            processo no Legal One e procura, nos últimos N dias, sinais
            de: audiência designada/cancelada, sentença, revelia, trânsito
            em julgado, arquivamento.
          </p>
          <p className="text-xs text-muted-foreground mt-2">
            <strong>Módulo incidental:</strong> roda local no Docker. Sem
            deploy em main.
          </p>
        </div>
        <Button onClick={() => setIsCreateOpen(true)}>
          <PlayCircle className="h-4 w-4 mr-2" />
          Nova varredura
        </Button>
      </div>

      <div className="flex gap-2 border-b">
        <button
          className={`px-4 py-2 text-sm font-medium ${
            tab === "runs"
              ? "border-b-2 border-primary text-primary"
              : "text-muted-foreground"
          }`}
          onClick={() => setTab("runs")}
        >
          Varreduras
        </button>
        <button
          className={`px-4 py-2 text-sm font-medium ${
            tab === "achados"
              ? "border-b-2 border-primary text-primary"
              : "text-muted-foreground"
          }`}
          onClick={() => setTab("achados")}
        >
          Achados
        </button>
        <button
          className={`px-4 py-2 text-sm font-medium ${
            tab === "padroes"
              ? "border-b-2 border-primary text-primary"
              : "text-muted-foreground"
          }`}
          onClick={() => setTab("padroes")}
        >
          Padrões detectados
        </button>
      </div>

      {tab === "runs" && (
        <RunsTab
          runs={runs}
          total={runsTotal}
          loading={runsLoading}
          offset={runsOffset}
          limit={runsLimit}
          statusFilter={runsStatusFilter}
          onChangeStatusFilter={(v) => {
            setRunsOffset(0);
            setRunsStatusFilter(v);
          }}
          onChangeOffset={setRunsOffset}
          onReload={loadRuns}
          onCancel={handleCancelRun}
          onRecoverZombies={handleRecoverZombies}
        />
      )}

      {tab === "achados" && (
        <AchadosTab
          achados={achados}
          total={achadosTotal}
          loading={achadosLoading}
          offset={achadosOffset}
          limit={achadosLimit}
          filterTipoEvento={filterTipoEvento}
          filterTratado={filterTratado}
          filterRunId={filterRunId}
          filterCnj={filterCnj}
          onChangeOffset={setAchadosOffset}
          onChangeTipoEvento={(v) => {
            setAchadosOffset(0);
            setFilterTipoEvento(v);
          }}
          onChangeTratado={(v) => {
            setAchadosOffset(0);
            setFilterTratado(v);
          }}
          onChangeRunId={(v) => {
            setAchadosOffset(0);
            setFilterRunId(v);
          }}
          onChangeCnj={(v) => {
            setAchadosOffset(0);
            setFilterCnj(v);
          }}
          onReload={loadAchados}
          expandedId={expandedAchadoId}
          onExpand={setExpandedAchadoId}
          onToggleTratado={handleToggleTratado}
        />
      )}

      {tab === "padroes" && <PatternsTab patterns={patterns} />}

      <CreateRunDialog
        open={isCreateOpen}
        onOpenChange={setIsCreateOpen}
        onCreated={(_run) => {
          setIsCreateOpen(false);
          setTab("runs");
          setRunsOffset(0);
          loadRuns();
        }}
      />
    </div>
  );
}

// ── Tab Runs ──────────────────────────────────────────────────────────

interface RunsTabProps {
  runs: VarreduraRun[];
  total: number;
  loading: boolean;
  offset: number;
  limit: number;
  statusFilter: string;
  onChangeStatusFilter: (v: string) => void;
  onChangeOffset: (v: number) => void;
  onReload: () => void;
  onCancel: (id: number) => void;
  onRecoverZombies: (id: number) => void;
}

function RunsTab(props: RunsTabProps) {
  const {
    runs,
    total,
    loading,
    offset,
    limit,
    statusFilter,
    onChangeStatusFilter,
    onChangeOffset,
    onReload,
    onCancel,
    onRecoverZombies,
  } = props;

  const totalPages = Math.max(1, Math.ceil(total / limit));
  const currentPage = Math.floor(offset / limit) + 1;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div>
            <CardTitle>Varreduras</CardTitle>
            <CardDescription>
              {total} execuções · Auto-refresh quando há varredura em
              execução.
            </CardDescription>
          </div>
          <div className="flex items-center gap-2">
            <Select value={statusFilter} onValueChange={onChangeStatusFilter}>
              <SelectTrigger className="w-[180px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__all__">Todos status</SelectItem>
                <SelectItem value="RUNNING">Em execução</SelectItem>
                <SelectItem value="DONE">Concluídas</SelectItem>
                <SelectItem value="FAILED">Falhas</SelectItem>
                <SelectItem value="CANCELLED">Canceladas</SelectItem>
              </SelectContent>
            </Select>
            <Button variant="outline" size="sm" onClick={onReload}>
              <RefreshCw className="h-4 w-4 mr-1" />
              Atualizar
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-16">#</TableHead>
              <TableHead>Iniciada</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Offices</TableHead>
              <TableHead className="text-center">Janela</TableHead>
              <TableHead className="text-center">Progresso</TableHead>
              <TableHead className="text-center">Achados</TableHead>
              <TableHead className="text-center">Falhas</TableHead>
              <TableHead className="text-right">Ações</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading && runs.length === 0 && (
              <TableRow>
                <TableCell colSpan={9} className="text-center py-8">
                  <Loader2 className="h-5 w-5 animate-spin inline" />
                </TableCell>
              </TableRow>
            )}
            {!loading && runs.length === 0 && (
              <TableRow>
                <TableCell
                  colSpan={9}
                  className="text-center py-8 text-muted-foreground"
                >
                  Nenhuma varredura ainda. Clique em "Nova varredura" pra
                  iniciar.
                </TableCell>
              </TableRow>
            )}
            {runs.map((r) => (
              <TableRow key={r.id}>
                <TableCell className="font-mono">#{r.id}</TableCell>
                <TableCell className="text-sm">
                  {formatDateTime(r.started_at)}
                </TableCell>
                <TableCell>{runStatusBadge(r.status)}</TableCell>
                <TableCell className="text-xs">
                  {(r.responsible_office_ids || []).join(", ")}
                </TableCell>
                <TableCell className="text-center text-xs">
                  {r.window_days}d
                </TableCell>
                <TableCell className="text-center font-mono text-sm">
                  {r.total_processados}/{r.total_processos}
                </TableCell>
                <TableCell className="text-center">
                  {r.total_achados > 0 ? (
                    <Badge className="bg-amber-100 text-amber-900 border-amber-300">
                      {r.total_achados}
                    </Badge>
                  ) : (
                    <span className="text-muted-foreground">0</span>
                  )}
                </TableCell>
                <TableCell className="text-center">
                  {r.total_falhas > 0 ? (
                    <Badge className="bg-red-100 text-red-900 border-red-300">
                      {r.total_falhas}
                    </Badge>
                  ) : (
                    <span className="text-muted-foreground">0</span>
                  )}
                </TableCell>
                <TableCell className="text-right space-x-1">
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => downloadVarreduraRunXlsx(r.id)}
                    title="Baixar XLSX com os achados desta varredura"
                  >
                    <Download className="h-3 w-3" />
                  </Button>
                  {r.status === "RUNNING" && (
                    <>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => onRecoverZombies(r.id)}
                        title="Devolver items presos em PROCESSANDO pra PENDENTE"
                      >
                        <ShieldAlert className="h-3 w-3" />
                      </Button>
                      <Button
                        size="sm"
                        variant="destructive"
                        onClick={() => onCancel(r.id)}
                      >
                        <Ban className="h-3 w-3" />
                      </Button>
                    </>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        {totalPages > 1 && (
          <div className="flex items-center justify-end gap-2 mt-4">
            <Button
              size="sm"
              variant="outline"
              disabled={offset === 0}
              onClick={() => onChangeOffset(Math.max(0, offset - limit))}
            >
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <span className="text-sm text-muted-foreground">
              Pág {currentPage}/{totalPages}
            </span>
            <Button
              size="sm"
              variant="outline"
              disabled={offset + limit >= total}
              onClick={() => onChangeOffset(offset + limit)}
            >
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ── Tab Achados ───────────────────────────────────────────────────────

interface AchadosTabProps {
  achados: VarreduraAchado[];
  total: number;
  loading: boolean;
  offset: number;
  limit: number;
  filterTipoEvento: string;
  filterTratado: string;
  filterRunId: string;
  filterCnj: string;
  onChangeOffset: (v: number) => void;
  onChangeTipoEvento: (v: string) => void;
  onChangeTratado: (v: string) => void;
  onChangeRunId: (v: string) => void;
  onChangeCnj: (v: string) => void;
  onReload: () => void;
  expandedId: number | null;
  onExpand: (id: number | null) => void;
  onToggleTratado: (
    achado: VarreduraAchado,
    novo: boolean,
    obs?: string,
  ) => void;
}

function AchadosTab(props: AchadosTabProps) {
  const {
    achados,
    total,
    loading,
    offset,
    limit,
    filterTipoEvento,
    filterTratado,
    filterRunId,
    filterCnj,
    onChangeOffset,
    onChangeTipoEvento,
    onChangeTratado,
    onChangeRunId,
    onChangeCnj,
    onReload,
    expandedId,
    onExpand,
    onToggleTratado,
  } = props;

  const totalPages = Math.max(1, Math.ceil(total / limit));
  const currentPage = Math.floor(offset / limit) + 1;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div>
            <CardTitle>Achados</CardTitle>
            <CardDescription>
              {total} eventos detectados nos andamentos. Marque como
              tratado conforme age.
            </CardDescription>
          </div>
          <Button variant="outline" size="sm" onClick={onReload}>
            <RefreshCw className="h-4 w-4 mr-1" />
            Atualizar
          </Button>
        </div>
        <div className="flex items-end gap-3 flex-wrap mt-3">
          <div className="space-y-1">
            <Label className="text-xs">Tipo evento</Label>
            <Select
              value={filterTipoEvento}
              onValueChange={onChangeTipoEvento}
            >
              <SelectTrigger className="w-[200px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__all__">Todos</SelectItem>
                {Object.entries(TIPOS_EVENTO_LABELS).map(([v, l]) => (
                  <SelectItem key={v} value={v}>
                    {l}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1">
            <Label className="text-xs">Status</Label>
            <Select value={filterTratado} onValueChange={onChangeTratado}>
              <SelectTrigger className="w-[150px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__all__">Todos</SelectItem>
                <SelectItem value="nao_tratado">Pendentes</SelectItem>
                <SelectItem value="tratado">Tratados</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1">
            <Label className="text-xs">Run #</Label>
            <Input
              type="number"
              value={filterRunId}
              onChange={(e) => onChangeRunId(e.target.value)}
              className="w-[100px]"
              placeholder="—"
            />
          </div>
          <div className="space-y-1 flex-1 min-w-[200px]">
            <Label className="text-xs">Buscar CNJ</Label>
            <div className="relative">
              <Search className="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                value={filterCnj}
                onChange={(e) => onChangeCnj(e.target.value)}
                className="pl-8"
                placeholder="ex. 0001234-..."
              />
            </div>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-16">Tratado</TableHead>
              <TableHead className="w-20">Data</TableHead>
              <TableHead className="w-44">Tipo</TableHead>
              <TableHead>CNJ</TableHead>
              <TableHead>Trecho</TableHead>
              <TableHead className="w-16 text-center">Run</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading && achados.length === 0 && (
              <TableRow>
                <TableCell colSpan={6} className="text-center py-8">
                  <Loader2 className="h-5 w-5 animate-spin inline" />
                </TableCell>
              </TableRow>
            )}
            {!loading && achados.length === 0 && (
              <TableRow>
                <TableCell
                  colSpan={6}
                  className="text-center py-8 text-muted-foreground"
                >
                  Nenhum achado.
                </TableCell>
              </TableRow>
            )}
            {achados.map((a) => {
              const isExpanded = expandedId === a.id;
              const tipoColor =
                TIPOS_EVENTO_COLORS[a.tipo_evento] ||
                "bg-gray-100 text-gray-900";
              const tipoLabel =
                TIPOS_EVENTO_LABELS[a.tipo_evento] || a.tipo_evento;
              return (
                <TableRow key={a.id}>
                  <TableCell>
                    <Checkbox
                      checked={a.tratado}
                      onCheckedChange={(checked) =>
                        onToggleTratado(a, !!checked)
                      }
                    />
                  </TableCell>
                  <TableCell className="text-sm">
                    {formatDate(a.andamento_data)}
                    {a.andamento_hora && (
                      <span className="text-xs text-muted-foreground block">
                        {a.andamento_hora}
                      </span>
                    )}
                  </TableCell>
                  <TableCell>
                    <Badge className={tipoColor}>{tipoLabel}</Badge>
                  </TableCell>
                  <TableCell className="font-mono text-xs">
                    {a.cnj_number || `lawsuit#${a.lawsuit_id}`}
                  </TableCell>
                  <TableCell
                    className="text-xs cursor-pointer max-w-[600px]"
                    onClick={() => onExpand(isExpanded ? null : a.id)}
                  >
                    {isExpanded ? (
                      <div className="whitespace-pre-wrap">
                        <div className="font-medium mb-1">
                          {a.andamento_tipo || "Andamento"}
                          {a.andamento_movimentado_por && (
                            <span className="text-muted-foreground ml-2">
                              · {a.andamento_movimentado_por}
                            </span>
                          )}
                        </div>
                        <div>{a.andamento_texto}</div>
                        {a.regex_matched && (
                          <div className="mt-1 text-amber-700">
                            ↳ matched: <em>{a.regex_matched}</em>
                          </div>
                        )}
                      </div>
                    ) : (
                      <div className="truncate">
                        {a.andamento_texto.slice(0, 140)}
                        {a.andamento_texto.length > 140 ? "…" : ""}
                      </div>
                    )}
                  </TableCell>
                  <TableCell className="text-center text-xs font-mono">
                    #{a.run_id}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
        {totalPages > 1 && (
          <div className="flex items-center justify-end gap-2 mt-4">
            <Button
              size="sm"
              variant="outline"
              disabled={offset === 0}
              onClick={() => onChangeOffset(Math.max(0, offset - limit))}
            >
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <span className="text-sm text-muted-foreground">
              Pág {currentPage}/{totalPages}
            </span>
            <Button
              size="sm"
              variant="outline"
              disabled={offset + limit >= total}
              onClick={() => onChangeOffset(offset + limit)}
            >
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ── Tab Patterns ──────────────────────────────────────────────────────

function PatternsTab({ patterns }: { patterns: VarreduraPattern[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Padrões detectados</CardTitle>
        <CardDescription>
          Regex aplicadas em cada andamento. Um andamento pode disparar
          múltiplos achados.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {patterns.length === 0 ? (
          <p className="text-sm text-muted-foreground">Carregando…</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Tipo</TableHead>
                <TableHead>Descrição</TableHead>
                <TableHead>Regex</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {patterns.map((p) => (
                <TableRow key={p.tipo}>
                  <TableCell>
                    <Badge
                      className={
                        TIPOS_EVENTO_COLORS[p.tipo] || "bg-gray-100"
                      }
                    >
                      {TIPOS_EVENTO_LABELS[p.tipo] || p.tipo}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-sm">{p.label}</TableCell>
                  <TableCell>
                    <code className="text-xs bg-muted px-2 py-1 rounded">
                      {p.regex}
                    </code>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

// ── Modal "Nova varredura" ────────────────────────────────────────────

interface CreateRunDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (run: VarreduraRun) => void;
}

function CreateRunDialog(props: CreateRunDialogProps) {
  const { open, onOpenChange, onCreated } = props;
  const { toast } = useToast();
  const [mode, setMode] = useState<"office" | "list">("office");
  const [offices, setOffices] = useState<VarreduraOfficeOption[]>([]);
  const [loadingOffices, setLoadingOffices] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [windowDays, setWindowDays] = useState(30);
  const [maxProcessos, setMaxProcessos] = useState(30);
  const [submitting, setSubmitting] = useState(false);
  const [showAll, setShowAll] = useState(false);
  // Modo lista: textarea de CNJs/IDs
  const [listText, setListText] = useState("");

  useEffect(() => {
    if (!open) return;
    setLoadingOffices(true);
    fetchVarreduraOffices()
      .then((rows) => {
        setOffices(rows);
        // Pre-seleciona offices com polo_scope=passivo (premissa do negocio).
        const preset = new Set<number>(
          rows.filter((o) => o.polo_scope === "passivo").map((o) => o.external_id),
        );
        setSelectedIds(preset);
      })
      .catch((err) =>
        toast({
          title: "Erro ao carregar offices",
          description: err instanceof Error ? err.message : String(err),
          variant: "destructive",
        }),
      )
      .finally(() => setLoadingOffices(false));
  }, [open, toast]);

  const toggleId = (id: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const visibleOffices = useMemo(() => {
    if (showAll) return offices;
    return offices.filter((o) => o.polo_scope === "passivo");
  }, [offices, showAll]);

  const submit = async () => {
    if (mode === "office") {
      if (selectedIds.size === 0) {
        toast({
          title: "Nenhum office selecionado",
          description: "Marque pelo menos 1 office responsável.",
          variant: "destructive",
        });
        return;
      }
      setSubmitting(true);
      try {
        const run = await createVarreduraRun({
          responsible_office_ids: Array.from(selectedIds),
          window_days: windowDays,
          max_processos: maxProcessos,
        });
        toast({
          title: "Varredura iniciada",
          description: `Run #${run.id} · ${run.total_processos} processos`,
        });
        onCreated(run);
      } catch (err) {
        toast({
          title: "Erro ao criar varredura",
          description: err instanceof Error ? err.message : String(err),
          variant: "destructive",
        });
      } finally {
        setSubmitting(false);
      }
      return;
    }

    // mode === "list"
    const items = listText
      .split(/[\n,;]+/)
      .map((s) => s.trim())
      .filter(Boolean);
    if (items.length === 0) {
      toast({
        title: "Lista vazia",
        description: "Cole CNJs ou lawsuit_ids (1 por linha).",
        variant: "destructive",
      });
      return;
    }
    setSubmitting(true);
    try {
      const { run, unresolved } = await createVarreduraRunFromList({
        identifiers: items,
        window_days: windowDays,
      });
      const desc =
        unresolved.length > 0
          ? `Run #${run.id} · ${run.total_processos} processos. ${unresolved.length} CNJ(s) nao encontrado(s).`
          : `Run #${run.id} · ${run.total_processos} processos`;
      toast({ title: "Varredura iniciada", description: desc });
      onCreated(run);
    } catch (err) {
      toast({
        title: "Erro ao criar varredura por lista",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setSubmitting(false);
    }
  };

  const listItemCount = useMemo(() => {
    return listText
      .split(/[\n,;]+/)
      .map((s) => s.trim())
      .filter(Boolean).length;
  }, [listText]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Nova varredura</DialogTitle>
          <DialogDescription>
            Escolha entre varrer por escritório responsável ou por lista
            específica de CNJs/lawsuit_ids.
          </DialogDescription>
        </DialogHeader>

        <div className="flex gap-2 border-b">
          <button
            type="button"
            className={`px-3 py-1.5 text-sm font-medium ${
              mode === "office"
                ? "border-b-2 border-primary text-primary"
                : "text-muted-foreground"
            }`}
            onClick={() => setMode("office")}
          >
            Por escritório
          </button>
          <button
            type="button"
            className={`px-3 py-1.5 text-sm font-medium ${
              mode === "list"
                ? "border-b-2 border-primary text-primary"
                : "text-muted-foreground"
            }`}
            onClick={() => setMode("list")}
          >
            Por lista (CNJ ou lawsuit_id)
          </button>
        </div>

        {mode === "list" && (
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label htmlFor="window-days-list">Janela (dias)</Label>
                <Input
                  id="window-days-list"
                  type="number"
                  min={1}
                  max={365}
                  value={windowDays}
                  onChange={(e) =>
                    setWindowDays(
                      Math.max(1, parseInt(e.target.value, 10) || 1),
                    )
                  }
                />
              </div>
              <div className="space-y-1">
                <Label>Itens detectados</Label>
                <div className="text-sm font-mono pt-2">{listItemCount}</div>
              </div>
            </div>
            <div className="space-y-1">
              <Label htmlFor="list-textarea">
                Cole CNJs ou lawsuit_ids (1 por linha, ou separados por vírgula/;)
              </Label>
              <textarea
                id="list-textarea"
                className="w-full h-[280px] font-mono text-xs border rounded-md p-2"
                placeholder={`0001234-56.2023.4.05.0001\n0009876-54.2024.8.05.0001\n64257\n64258`}
                value={listText}
                onChange={(e) => setListText(e.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                CNJs e lawsuit_ids podem ser misturados. CNJs serão
                resolvidos via API L1 (pode demorar alguns segundos).
              </p>
            </div>
            <Alert>
              <AlertCircle className="h-4 w-4" />
              <AlertDescription className="text-xs">
                Use este modo pra varrer uma base prioritária. Para a
                carteira inteira por escritório, use a aba "Por escritório".
              </AlertDescription>
            </Alert>
          </div>
        )}

        {mode === "office" && <div className="space-y-4">
          <div className="grid grid-cols-3 gap-3">
            <div className="space-y-1">
              <Label htmlFor="window-days">Janela (dias)</Label>
              <Input
                id="window-days"
                type="number"
                min={1}
                max={365}
                value={windowDays}
                onChange={(e) =>
                  setWindowDays(Math.max(1, parseInt(e.target.value, 10) || 1))
                }
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="max-processos">Máx processos</Label>
              <Input
                id="max-processos"
                type="number"
                min={1}
                max={5000}
                value={maxProcessos}
                onChange={(e) =>
                  setMaxProcessos(
                    Math.max(1, parseInt(e.target.value, 10) || 1),
                  )
                }
              />
              <p className="text-[10px] text-muted-foreground">
                limite global (todos offices)
              </p>
            </div>
            <div className="space-y-1">
              <Label>Offices selecionados</Label>
              <div className="text-sm font-mono pt-2">{selectedIds.size}</div>
            </div>
          </div>

          <div>
            <div className="flex items-center justify-between mb-2">
              <Label>Escritórios responsáveis</Label>
              <button
                type="button"
                className="text-xs text-muted-foreground hover:underline"
                onClick={() => setShowAll((v) => !v)}
              >
                {showAll ? "Mostrar só passivo" : "Mostrar todos"}
              </button>
            </div>
            {loadingOffices && (
              <div className="text-sm text-muted-foreground py-4">
                <Loader2 className="h-4 w-4 animate-spin inline mr-2" />
                Carregando offices…
              </div>
            )}
            {!loadingOffices && (
              <div className="border rounded-md max-h-[300px] overflow-y-auto divide-y">
                {visibleOffices.length === 0 && (
                  <div className="p-3 text-sm text-muted-foreground">
                    Nenhum office disponível. Verifique se há cadastros em
                    LegalOneOffice com polo_scope=passivo.
                  </div>
                )}
                {visibleOffices.map((o) => (
                  <label
                    key={o.external_id}
                    className="flex items-start gap-3 p-2.5 hover:bg-muted/50 cursor-pointer"
                  >
                    <Checkbox
                      checked={selectedIds.has(o.external_id)}
                      onCheckedChange={() => toggleId(o.external_id)}
                      className="mt-0.5"
                    />
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium truncate">
                        {o.path || o.name}
                      </div>
                      <div className="text-xs text-muted-foreground flex items-center gap-2">
                        <span>#{o.external_id}</span>
                        <Badge
                          variant="outline"
                          className={
                            o.polo_scope === "passivo"
                              ? "bg-red-50 border-red-300 text-red-900"
                              : o.polo_scope === "ativo"
                              ? "bg-green-50 border-green-300 text-green-900"
                              : "bg-zinc-50 border-zinc-300"
                          }
                        >
                          polo: {o.polo_scope}
                        </Badge>
                      </div>
                    </div>
                  </label>
                ))}
              </div>
            )}
          </div>

          <Alert>
            <AlertCircle className="h-4 w-4" />
            <AlertTitle>Como funciona</AlertTitle>
            <AlertDescription className="text-xs">
              O sistema resolve os processos via índice local
              (OfficeLawsuitIndex) ou API L1 e dispara um runner Playwright
              em background. Você acompanha o progresso na aba "Varreduras"
              — pode levar minutos a horas dependendo do volume.
            </AlertDescription>
          </Alert>
        </div>}

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={submitting}
          >
            Cancelar
          </Button>
          <Button onClick={submit} disabled={submitting}>
            {submitting && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
            Iniciar varredura
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
