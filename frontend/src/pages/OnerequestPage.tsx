// frontend/src/pages/OnerequestPage.tsx
//
// OneRequest — tratamento das DMIs (demandas diversas de assessoria) do Banco
// do Brasil. As solicitações são capturadas por um motor RPA externo e
// empurradas pro Flow via intake; aqui o operador direciona (responsável,
// setor, prazo) e agenda a tarefa no Legal One. Acesso pela permissão
// dedicada `can_use_onerequest` (admin libera por usuário).

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import UserSelector, { SelectableUser } from "@/components/ui/UserSelector";
import { useToast } from "@/hooks/use-toast";
import {
  AlertTriangle,
  CalendarCheck,
  Inbox,
  Loader2,
  RefreshCw,
  Search,
} from "lucide-react";
import {
  agendarSolicitacao,
  Farol,
  FormUser,
  getFormUsers,
  getOptions,
  listSolicitacoes,
  OnerequestSolicitacao,
  updateTratamento,
} from "@/services/onerequest";

const PAGE_SIZES = [25, 50, 100];

const FAROL_DOT: Record<Farol, string> = {
  cinza: "bg-slate-400",
  vermelho: "bg-red-500",
  amarelo: "bg-amber-400",
  roxo: "bg-purple-500",
  verde: "bg-emerald-500",
};

const KPI_DEFS: { key: string; label: string; dot: string }[] = [
  { key: "vencidas", label: "Vencidas", dot: "bg-slate-400" },
  { key: "hoje", label: "Hoje", dot: "bg-red-500" },
  { key: "amanha", label: "Amanhã", dot: "bg-amber-400" },
  { key: "fds", label: "Fim de semana", dot: "bg-purple-500" },
  { key: "futuras", label: "Futuras", dot: "bg-emerald-500" },
];

const STATUS_TRATAMENTO_FILTROS = [
  { value: "TODOS", label: "Todos os tratamentos" },
  { value: "NOVO", label: "Novo" },
  { value: "AGENDADO", label: "Agendado" },
  { value: "AGUARDANDO_PROCESSO", label: "Aguardando processo" },
  { value: "IGNORADO", label: "Sem providência" },
  { value: "ERRO", label: "Erro" },
];

function StatusTratamentoBadge({ status }: { status: string }) {
  switch (status) {
    case "AGENDADO":
      return <Badge className="bg-emerald-600 hover:bg-emerald-600">Agendado</Badge>;
    case "AGUARDANDO_PROCESSO":
      return <Badge className="bg-amber-500 hover:bg-amber-500">Aguardando processo</Badge>;
    case "IGNORADO":
      return <Badge variant="outline">Sem providência</Badge>;
    case "ERRO":
      return <Badge variant="destructive">Erro</Badge>;
    default:
      return <Badge variant="secondary">Novo</Badge>;
  }
}

export default function OnerequestPage() {
  const { toast } = useToast();
  const [items, setItems] = useState<OnerequestSolicitacao[]>([]);
  const [total, setTotal] = useState(0);
  const [kpis, setKpis] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(false);

  // Filtros
  const [buscaInput, setBuscaInput] = useState("");
  const [busca, setBusca] = useState("");
  const [statusTratamento, setStatusTratamento] = useState("TODOS");
  const [statusSistema, setStatusSistema] = useState("ABERTO");

  // Paginação
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);

  // Catálogos
  const [users, setUsers] = useState<FormUser[]>([]);
  const [setores, setSetores] = useState<string[]>([]);

  // Modal de tratamento
  const [selected, setSelected] = useState<OnerequestSolicitacao | null>(null);
  const [editResponsavelExt, setEditResponsavelExt] = useState<string | null>(null);
  const [editSetor, setEditSetor] = useState("");
  const [editData, setEditData] = useState("");
  const [editAnotacao, setEditAnotacao] = useState("");
  const [saving, setSaving] = useState(false);
  const [scheduling, setScheduling] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const resp = await listSolicitacoes({
        status_sistema: statusSistema,
        status_tratamento: statusTratamento === "TODOS" ? undefined : statusTratamento,
        busca: busca || undefined,
        limit: pageSize,
        offset: (page - 1) * pageSize,
      });
      setItems(resp.items);
      setTotal(resp.total);
      setKpis(resp.kpis);
    } catch (e) {
      toast({
        title: "Erro ao carregar",
        description: String((e as Error).message),
        variant: "destructive",
      });
    } finally {
      setLoading(false);
    }
  }, [statusSistema, statusTratamento, busca, page, pageSize, toast]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    getOptions()
      .then((o) => setSetores(o.setores))
      .catch(() => {});
    getFormUsers()
      .then(setUsers)
      .catch(() => {});
  }, []);

  const selectableUsers: SelectableUser[] = useMemo(
    () =>
      users.map((u) => ({
        id: u.id,
        external_id: u.external_id,
        name: u.name,
        squads: u.squads ?? [],
        email: u.email ?? null,
      })),
    [users],
  );

  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const firstRow = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const lastRow = Math.min(total, page * pageSize);

  const aplicarBusca = () => {
    setPage(1);
    setBusca(buscaInput.trim());
  };

  const openModal = (sol: OnerequestSolicitacao) => {
    setSelected(sol);
    const u = users.find((x) => x.id === sol.responsavel_user_id);
    setEditResponsavelExt(u ? String(u.external_id) : null);
    setEditSetor(sol.setor ?? "");
    setEditData(sol.data_agendamento ?? "");
    setEditAnotacao(sol.anotacao ?? "");
  };

  const closeModal = () => setSelected(null);

  const resolveResponsavelId = (): number | null => {
    if (!editResponsavelExt) return null;
    const u = users.find((x) => String(x.external_id) === editResponsavelExt);
    return u ? u.id : null;
  };

  const saveTratamento = async (): Promise<boolean> => {
    if (!selected) return false;
    setSaving(true);
    try {
      await updateTratamento(selected.id, {
        responsavel_user_id: resolveResponsavelId(),
        setor: editSetor || null,
        data_agendamento: editData || null,
        anotacao: editAnotacao || null,
      });
      toast({ title: "Tratamento salvo." });
      await load();
      return true;
    } catch (e) {
      toast({
        title: "Erro ao salvar",
        description: String((e as Error).message),
        variant: "destructive",
      });
      return false;
    } finally {
      setSaving(false);
    }
  };

  const handleAgendar = async () => {
    if (!selected) return;
    // Persiste o tratamento antes de agendar (garante responsável/setor/data).
    const ok = await saveTratamento();
    if (!ok) return;
    setScheduling(true);
    try {
      const res = await agendarSolicitacao(selected.id);
      if (res.ok) {
        toast({ title: "Agendado no Legal One", description: res.mensagem });
        closeModal();
      } else {
        toast({
          title: "Não agendado",
          description: res.mensagem,
          variant: "destructive",
        });
      }
      await load();
    } catch (e) {
      toast({
        title: "Erro ao agendar",
        description: String((e as Error).message),
        variant: "destructive",
      });
    } finally {
      setScheduling(false);
    }
  };

  const handleIgnorar = async () => {
    if (!selected) return;
    setSaving(true);
    try {
      await updateTratamento(selected.id, { status_tratamento: "IGNORADO" });
      toast({ title: "Marcada como sem providência." });
      closeModal();
      await load();
    } catch (e) {
      toast({
        title: "Erro",
        description: String((e as Error).message),
        variant: "destructive",
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-3">
        <Inbox className="h-6 w-6 text-primary" />
        <div>
          <h1 className="text-xl font-semibold">OneRequest — DMIs do Banco do Brasil</h1>
          <p className="text-sm text-muted-foreground">
            Demandas diversas de assessoria capturadas do Portal Jurídico do BB.
            Direcione e agende no Legal One.
          </p>
        </div>
      </div>

      {/* KPIs (farol por prazo do BB) */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {KPI_DEFS.map((kpi) => (
          <Card key={kpi.key}>
            <CardContent className="flex items-center gap-3 p-4">
              <span className={`h-3 w-3 rounded-full ${kpi.dot}`} />
              <div>
                <div className="text-2xl font-bold">{kpis[kpi.key] ?? 0}</div>
                <div className="text-xs text-muted-foreground">{kpi.label}</div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Filtros */}
      <Card>
        <CardContent className="flex flex-wrap items-end gap-3 p-4">
          <div className="flex-1 min-w-[220px]">
            <Label className="text-xs">Buscar</Label>
            <div className="flex gap-2">
              <Input
                placeholder="Nº solicitação, processo ou título"
                value={buscaInput}
                onChange={(e) => setBuscaInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") aplicarBusca();
                }}
              />
              <Button variant="secondary" onClick={aplicarBusca}>
                <Search className="h-4 w-4" />
              </Button>
            </div>
          </div>
          <div className="min-w-[200px]">
            <Label className="text-xs">Tratamento</Label>
            <Select
              value={statusTratamento}
              onValueChange={(v) => {
                setPage(1);
                setStatusTratamento(v);
              }}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {STATUS_TRATAMENTO_FILTROS.map((f) => (
                  <SelectItem key={f.value} value={f.value}>
                    {f.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="min-w-[160px]">
            <Label className="text-xs">Situação no BB</Label>
            <Select
              value={statusSistema}
              onValueChange={(v) => {
                setPage(1);
                setStatusSistema(v);
              }}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="ABERTO">Abertas</SelectItem>
                <SelectItem value="RESPONDIDO">Respondidas</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <Button variant="outline" onClick={() => load()} disabled={loading}>
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          </Button>
        </CardContent>
      </Card>

      {/* Tabela */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Solicitações</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-6"></TableHead>
                <TableHead>Nº Solicitação</TableHead>
                <TableHead>Título</TableHead>
                <TableHead>Processo</TableHead>
                <TableHead>Prazo BB</TableHead>
                <TableHead>Responsável</TableHead>
                <TableHead>Setor</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Ação</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading && items.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={9} className="py-10 text-center">
                    <Loader2 className="mx-auto h-6 w-6 animate-spin text-muted-foreground" />
                  </TableCell>
                </TableRow>
              ) : items.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={9} className="py-10 text-center text-muted-foreground">
                    Nenhuma solicitação encontrada.
                  </TableCell>
                </TableRow>
              ) : (
                items.map((sol) => (
                  <TableRow key={sol.id}>
                    <TableCell>
                      <span
                        className={`inline-block h-3 w-3 rounded-full ${FAROL_DOT[sol.farol]}`}
                        title={sol.prazo ? `Prazo BB: ${sol.prazo}` : "Sem prazo"}
                      />
                    </TableCell>
                    <TableCell className="font-mono text-xs">{sol.numero_solicitacao}</TableCell>
                    <TableCell className="max-w-[260px] truncate text-sm" title={sol.titulo ?? ""}>
                      {sol.titulo ?? <span className="text-muted-foreground">—</span>}
                    </TableCell>
                    <TableCell className="text-xs">
                      {sol.proc_utilizavel ? (
                        <span className="font-mono">{sol.numero_processo}</span>
                      ) : (
                        <Badge variant="outline" className="border-amber-300 text-amber-700">
                          sem processo
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell className="text-sm">{sol.prazo ?? "—"}</TableCell>
                    <TableCell className="text-sm">
                      {sol.responsavel_nome ?? <span className="text-muted-foreground">—</span>}
                    </TableCell>
                    <TableCell className="text-sm">{sol.setor ?? "—"}</TableCell>
                    <TableCell>
                      <StatusTratamentoBadge status={sol.status_tratamento} />
                    </TableCell>
                    <TableCell className="text-right">
                      <Button size="sm" variant="outline" onClick={() => openModal(sol)}>
                        Tratar
                      </Button>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>

          {/* Paginação */}
          <div className="mt-4 flex flex-wrap items-center justify-between gap-3 text-sm">
            <div className="flex items-center gap-2">
              <span className="text-muted-foreground">Por página:</span>
              <Select
                value={String(pageSize)}
                onValueChange={(v) => {
                  setPage(1);
                  setPageSize(Number(v));
                }}
              >
                <SelectTrigger className="w-20">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {PAGE_SIZES.map((s) => (
                    <SelectItem key={s} value={String(s)}>
                      {s}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="text-muted-foreground">
              {firstRow}–{lastRow} de {total} · Página {page} de {totalPages}
            </div>
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={page <= 1 || loading}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
              >
                Anterior
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={page >= totalPages || loading}
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              >
                Próxima
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Modal de tratamento */}
      <Dialog open={!!selected} onOpenChange={(o) => !o && closeModal()}>
        <DialogContent className="max-w-2xl">
          {selected && (
            <>
              <DialogHeader>
                <DialogTitle className="font-mono text-base">
                  DMI {selected.numero_solicitacao}
                </DialogTitle>
                <DialogDescription>{selected.titulo ?? "Sem título"}</DialogDescription>
              </DialogHeader>

              <div className="grid grid-cols-2 gap-3 text-sm">
                <div>
                  <span className="text-muted-foreground">NPJ direcionador:</span>{" "}
                  {selected.npj_direcionador ?? "—"}
                </div>
                <div>
                  <span className="text-muted-foreground">Polo:</span> {selected.polo ?? "—"}
                </div>
                <div>
                  <span className="text-muted-foreground">Prazo BB:</span> {selected.prazo ?? "—"}
                </div>
                <div>
                  <span className="text-muted-foreground">Processo:</span>{" "}
                  {selected.proc_utilizavel ? (
                    <span className="font-mono">{selected.numero_processo}</span>
                  ) : (
                    <span className="text-amber-700">sem processo utilizável</span>
                  )}
                </div>
              </div>

              {selected.texto_dmi && (
                <div className="max-h-32 overflow-auto whitespace-pre-wrap rounded-md bg-muted p-3 text-xs">
                  {selected.texto_dmi}
                </div>
              )}

              {selected.last_error && (
                <div className="flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 p-2 text-xs text-amber-800">
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                  <span>{selected.last_error}</span>
                </div>
              )}

              {selected.created_task_id && (
                <div className="text-xs text-emerald-700">
                  Tarefa criada no Legal One (ID {selected.created_task_id}).
                </div>
              )}

              <div className="grid gap-3">
                <div>
                  <Label className="text-xs">Responsável</Label>
                  <UserSelector
                    users={selectableUsers}
                    value={editResponsavelExt}
                    onChange={setEditResponsavelExt}
                    showEmail
                  />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <Label className="text-xs">Setor</Label>
                    <Select value={editSetor} onValueChange={setEditSetor}>
                      <SelectTrigger>
                        <SelectValue placeholder="Selecione o setor" />
                      </SelectTrigger>
                      <SelectContent>
                        {setores.map((s) => (
                          <SelectItem key={s} value={s}>
                            {s}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div>
                    <Label className="text-xs">Data de agendamento</Label>
                    <Input
                      placeholder="DD/MM/AAAA"
                      value={editData}
                      onChange={(e) => setEditData(e.target.value)}
                    />
                  </div>
                </div>
                <div>
                  <Label className="text-xs">Anotação</Label>
                  <Textarea
                    rows={3}
                    value={editAnotacao}
                    onChange={(e) => setEditAnotacao(e.target.value)}
                  />
                </div>
              </div>

              <DialogFooter className="gap-2 sm:justify-between">
                <Button
                  variant="ghost"
                  onClick={handleIgnorar}
                  disabled={saving || scheduling}
                >
                  Sem providência
                </Button>
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    onClick={saveTratamento}
                    disabled={saving || scheduling}
                  >
                    {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                    Salvar
                  </Button>
                  <Button onClick={handleAgendar} disabled={saving || scheduling}>
                    {scheduling ? (
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    ) : (
                      <CalendarCheck className="mr-2 h-4 w-4" />
                    )}
                    Agendar no Legal One
                  </Button>
                </div>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
