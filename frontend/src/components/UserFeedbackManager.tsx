import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Archive,
  ArchiveRestore,
  Bot,
  CheckCircle2,
  Eye,
  Inbox,
  Loader2,
  MailOpen,
  RefreshCw,
} from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/hooks/use-toast";
import {
  fetchUserFeedbackStats,
  listUserFeedback,
  updateUserFeedback,
} from "@/services/api";
import type {
  UserFeedback,
  UserFeedbackCategory,
  UserFeedbackStats,
  UserFeedbackStatus,
} from "@/types/api";

const STATUS_LABEL: Record<UserFeedbackStatus, string> = {
  novo: "Novo",
  lido: "Lido",
  arquivado: "Arquivado",
};

const STATUS_BADGE: Record<UserFeedbackStatus, string> = {
  novo: "bg-blue-100 text-blue-800",
  lido: "bg-slate-100 text-slate-700",
  arquivado: "bg-slate-200 text-slate-500",
};

const CATEGORY_LABEL: Record<UserFeedbackCategory, string> = {
  bug: "Bug",
  sugestao: "Sugestão",
  duvida: "Dúvida",
  elogio: "Elogio",
  outro: "Outro",
};

const CATEGORY_BADGE: Record<UserFeedbackCategory, string> = {
  bug: "bg-red-100 text-red-800",
  sugestao: "bg-amber-100 text-amber-800",
  duvida: "bg-blue-100 text-blue-800",
  elogio: "bg-emerald-100 text-emerald-800",
  outro: "bg-slate-100 text-slate-700",
};

const PAGE_SIZE_OPTIONS = [25, 50, 100] as const;

function formatDateTime(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("pt-BR", {
    timeZone: "America/Fortaleza",
    dateStyle: "short",
    timeStyle: "short",
  });
}

/**
 * Painel admin de feedbacks recebidos pelo botao flutuante (bot).
 *
 * Layout:
 *  - Header com contadores (total, novos, lidos, arquivados) — clicaveis
 *    pra filtrar a lista pelo respectivo status. Default abre filtrado
 *    em "novo" (caixa de entrada).
 *  - Filtros: status + categoria + page size + refresh.
 *  - Tabela paginada (limit+offset no backend) com data, user, badge
 *    de categoria, snippet da mensagem, status, acao "Ver".
 *  - Modal de detalhes: mensagem completa + page_url + user_agent +
 *    nota interna + acoes (marcar lido / arquivar / restaurar).
 */
export function UserFeedbackManager() {
  const { toast } = useToast();
  const [items, setItems] = useState<UserFeedback[]>([]);
  const [total, setTotal] = useState(0);
  const [limit, setLimit] = useState<number>(50);
  const [offset, setOffset] = useState(0);
  const [statusFilter, setStatusFilter] = useState<UserFeedbackStatus | "todos">("novo");
  const [categoryFilter, setCategoryFilter] = useState<UserFeedbackCategory | "todos">("todos");
  const [stats, setStats] = useState<UserFeedbackStats | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<UserFeedback | null>(null);
  const [adminNoteDraft, setAdminNoteDraft] = useState("");
  const [savingId, setSavingId] = useState<number | null>(null);

  const totalPages = Math.max(1, Math.ceil(total / limit));
  const currentPage = Math.floor(offset / limit) + 1;

  const loadList = async () => {
    setIsLoading(true);
    try {
      const data = await listUserFeedback({
        limit,
        offset,
        status: statusFilter === "todos" ? undefined : statusFilter,
        category: categoryFilter === "todos" ? undefined : categoryFilter,
      });
      setItems(data.items);
      setTotal(data.total);
      setError(null);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Falha ao carregar.";
      setError(msg);
    } finally {
      setIsLoading(false);
    }
  };

  const loadStats = async () => {
    try {
      const s = await fetchUserFeedbackStats();
      setStats(s);
    } catch {
      // Stats sao secundarios — falha silenciosa nao bloqueia a UI.
    }
  };

  // Carrega lista quando filtros/paginacao mudam.
  useEffect(() => {
    loadList();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [limit, offset, statusFilter, categoryFilter]);

  // Stats so carrega no mount + apos updates.
  useEffect(() => {
    loadStats();
  }, []);

  const refresh = () => {
    loadList();
    loadStats();
  };

  // Resetar offset quando filtro muda (evita "pagina vazia" se o
  // filtro novo tem menos itens que o offset atual).
  const setStatusAndReset = (s: UserFeedbackStatus | "todos") => {
    setStatusFilter(s);
    setOffset(0);
  };
  const setCategoryAndReset = (c: UserFeedbackCategory | "todos") => {
    setCategoryFilter(c);
    setOffset(0);
  };
  const setLimitAndReset = (l: number) => {
    setLimit(l);
    setOffset(0);
  };

  const openDetails = (fb: UserFeedback) => {
    setSelected(fb);
    setAdminNoteDraft(fb.admin_note ?? "");
  };
  const closeDetails = () => {
    setSelected(null);
    setAdminNoteDraft("");
  };

  const updateLocal = (updated: UserFeedback) => {
    setItems((prev) =>
      prev.map((it) => (it.id === updated.id ? updated : it)),
    );
    setSelected(updated);
    loadStats(); // contadores ficam fora de sincronia se nao recarrega
  };

  const handleChangeStatus = async (
    fb: UserFeedback,
    next: UserFeedbackStatus,
  ) => {
    setSavingId(fb.id);
    try {
      const updated = await updateUserFeedback(fb.id, { status: next });
      updateLocal(updated);
      toast({ title: `Feedback marcado como ${STATUS_LABEL[next].toLowerCase()}` });
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Falha ao atualizar.";
      toast({ title: "Falha ao atualizar", description: msg, variant: "destructive" });
    } finally {
      setSavingId(null);
    }
  };

  const handleSaveNote = async () => {
    if (!selected) return;
    setSavingId(selected.id);
    try {
      const updated = await updateUserFeedback(selected.id, {
        admin_note: adminNoteDraft,
      });
      updateLocal(updated);
      toast({ title: "Nota interna salva" });
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Falha ao salvar.";
      toast({ title: "Falha ao salvar", description: msg, variant: "destructive" });
    } finally {
      setSavingId(null);
    }
  };

  const counters = useMemo(() => {
    if (!stats) return null;
    return [
      {
        key: "todos" as const,
        label: "Total",
        value: stats.total,
        Icon: Inbox,
        color: "text-slate-600",
      },
      {
        key: "novo" as const,
        label: "Novos",
        value: stats.novo,
        Icon: AlertTriangle,
        color: "text-blue-600",
      },
      {
        key: "lido" as const,
        label: "Lidos",
        value: stats.lido,
        Icon: MailOpen,
        color: "text-slate-500",
      },
      {
        key: "arquivado" as const,
        label: "Arquivados",
        value: stats.arquivado,
        Icon: Archive,
        color: "text-slate-400",
      },
    ];
  }, [stats]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold flex items-center gap-2">
            <Bot className="h-5 w-5 text-blue-600" />
            Feedback dos usuários
          </h2>
          <p className="text-sm text-muted-foreground">
            Mensagens enviadas pelo botão flutuante presente em todas as
            páginas. Captura page_url e user_agent automaticamente pra
            ajudar a reproduzir bugs sem precisar perguntar contexto.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={refresh} disabled={isLoading}>
          <RefreshCw className={`mr-2 h-4 w-4 ${isLoading ? "animate-spin" : ""}`} />
          Atualizar
        </Button>
      </div>

      {/* Cards de contadores — clicaveis pra filtrar */}
      {counters ? (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          {counters.map((c) => {
            const { Icon } = c;
            const active = statusFilter === c.key;
            return (
              <button
                key={c.key}
                type="button"
                onClick={() => setStatusAndReset(c.key)}
                className={`
                  rounded-lg border p-3 text-left transition-colors
                  ${active
                    ? "border-blue-400 bg-blue-50"
                    : "border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50"}
                `}
              >
                <div className="flex items-center justify-between">
                  <span className="text-xs text-muted-foreground">{c.label}</span>
                  <Icon className={`h-4 w-4 ${c.color}`} />
                </div>
                <div className="mt-1 text-2xl font-semibold">{c.value}</div>
              </button>
            );
          })}
        </div>
      ) : null}

      {error ? (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>Falha ao carregar</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      {/* Filtros adicionais */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Filtros</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-3 md:grid-cols-3">
            <div>
              <Label className="text-xs">Status</Label>
              <Select
                value={statusFilter}
                onValueChange={(v) => setStatusAndReset(v as UserFeedbackStatus | "todos")}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="todos">Todos</SelectItem>
                  <SelectItem value="novo">Novos</SelectItem>
                  <SelectItem value="lido">Lidos</SelectItem>
                  <SelectItem value="arquivado">Arquivados</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="text-xs">Categoria</Label>
              <Select
                value={categoryFilter}
                onValueChange={(v) => setCategoryAndReset(v as UserFeedbackCategory | "todos")}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="todos">Todas</SelectItem>
                  <SelectItem value="bug">Bug</SelectItem>
                  <SelectItem value="sugestao">Sugestão</SelectItem>
                  <SelectItem value="duvida">Dúvida</SelectItem>
                  <SelectItem value="elogio">Elogio</SelectItem>
                  <SelectItem value="outro">Outro</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="text-xs">Itens por página</Label>
              <Select
                value={String(limit)}
                onValueChange={(v) => setLimitAndReset(Number(v))}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {PAGE_SIZE_OPTIONS.map((n) => (
                    <SelectItem key={n} value={String(n)}>
                      {n}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Tabela */}
      <Card>
        <CardHeader>
          <CardTitle>
            {total} {total === 1 ? "feedback" : "feedbacks"}
            {statusFilter !== "todos" ? ` · ${STATUS_LABEL[statusFilter]}` : ""}
            {categoryFilter !== "todos" ? ` · ${CATEGORY_LABEL[categoryFilter]}` : ""}
          </CardTitle>
          <CardDescription>
            Ordenados do mais recente pro mais antigo.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[140px]">Data</TableHead>
                  <TableHead>Usuário</TableHead>
                  <TableHead className="w-[110px]">Categoria</TableHead>
                  <TableHead>Mensagem</TableHead>
                  <TableHead className="w-[110px]">Status</TableHead>
                  <TableHead className="w-[100px] text-right">Ações</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={6} className="py-10 text-center text-muted-foreground">
                      {isLoading ? "Carregando..." : "Nenhum feedback nesse filtro."}
                    </TableCell>
                  </TableRow>
                ) : (
                  items.map((fb) => (
                    <TableRow key={fb.id} className={fb.status === "novo" ? "bg-blue-50/30" : ""}>
                      <TableCell className="text-xs">{formatDateTime(fb.created_at)}</TableCell>
                      <TableCell className="text-xs">
                        <div className="font-medium">{fb.user_name ?? "—"}</div>
                        <div className="text-muted-foreground">{fb.user_email ?? ""}</div>
                      </TableCell>
                      <TableCell>
                        <Badge className={CATEGORY_BADGE[fb.category]}>
                          {CATEGORY_LABEL[fb.category]}
                        </Badge>
                      </TableCell>
                      <TableCell className="max-w-[400px] truncate text-xs" title={fb.message}>
                        {fb.message}
                      </TableCell>
                      <TableCell>
                        <Badge className={STATUS_BADGE[fb.status]}>
                          {STATUS_LABEL[fb.status]}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right">
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-7 px-2"
                          onClick={() => openDetails(fb)}
                        >
                          <Eye className="mr-1 h-3.5 w-3.5" />
                          Ver
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>

          {/* Controles de paginacao */}
          {total > 0 ? (
            <div className="mt-3 flex items-center justify-between border-t pt-3 text-xs text-muted-foreground">
              <div>
                Mostrando {offset + 1}–{Math.min(offset + limit, total)} de {total}
              </div>
              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  className="h-7 px-2"
                  onClick={() => setOffset((o) => Math.max(0, o - limit))}
                  disabled={offset === 0 || isLoading}
                >
                  Anterior
                </Button>
                <span>
                  Página {currentPage} de {totalPages}
                </span>
                <Button
                  variant="outline"
                  size="sm"
                  className="h-7 px-2"
                  onClick={() => setOffset((o) => o + limit)}
                  disabled={offset + limit >= total || isLoading}
                >
                  Próxima
                </Button>
              </div>
            </div>
          ) : null}
        </CardContent>
      </Card>

      {/* Modal de detalhes */}
      <Dialog open={selected !== null} onOpenChange={(o) => !o && closeDetails()}>
        <DialogContent className="sm:max-w-2xl">
          {selected ? (
            <>
              <DialogHeader>
                <DialogTitle className="flex items-center gap-2">
                  <Badge className={CATEGORY_BADGE[selected.category]}>
                    {CATEGORY_LABEL[selected.category]}
                  </Badge>
                  Feedback #{selected.id}
                  <Badge className={STATUS_BADGE[selected.status]}>
                    {STATUS_LABEL[selected.status]}
                  </Badge>
                </DialogTitle>
                <DialogDescription>
                  Enviado por {selected.user_name ?? "—"} em {formatDateTime(selected.created_at)}.
                </DialogDescription>
              </DialogHeader>

              <div className="space-y-3 py-2 text-sm">
                <div>
                  <Label className="text-xs">Mensagem</Label>
                  <div className="mt-1 whitespace-pre-wrap rounded-md border bg-slate-50 p-3 text-sm">
                    {selected.message}
                  </div>
                </div>

                <div className="grid grid-cols-1 gap-2 text-xs sm:grid-cols-2">
                  <div>
                    <span className="text-muted-foreground">Email:</span>{" "}
                    {selected.user_email ?? "—"}
                  </div>
                  <div className="truncate">
                    <span className="text-muted-foreground">Página:</span>{" "}
                    {selected.page_url ? (
                      <span title={selected.page_url}>{selected.page_url}</span>
                    ) : (
                      "—"
                    )}
                  </div>
                  <div className="truncate sm:col-span-2">
                    <span className="text-muted-foreground">User-Agent:</span>{" "}
                    <span title={selected.user_agent ?? ""}>
                      {selected.user_agent ?? "—"}
                    </span>
                  </div>
                  {selected.reviewed_by_name ? (
                    <div className="sm:col-span-2">
                      <span className="text-muted-foreground">Revisado por:</span>{" "}
                      {selected.reviewed_by_name} em {formatDateTime(selected.reviewed_at)}
                    </div>
                  ) : null}
                </div>

                <div>
                  <Label className="text-xs">Nota interna (visível só pra equipe)</Label>
                  <Textarea
                    rows={3}
                    value={adminNoteDraft}
                    onChange={(e) => setAdminNoteDraft(e.target.value)}
                    placeholder="Anote contexto, decisão tomada, link pra issue, etc."
                    disabled={savingId === selected.id}
                  />
                </div>
              </div>

              <DialogFooter className="flex-wrap gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => handleSaveNote()}
                  disabled={savingId === selected.id || adminNoteDraft === (selected.admin_note ?? "")}
                >
                  {savingId === selected.id ? (
                    <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
                  ) : null}
                  Salvar nota
                </Button>
                {selected.status === "novo" ? (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => handleChangeStatus(selected, "lido")}
                    disabled={savingId === selected.id}
                  >
                    <CheckCircle2 className="mr-2 h-3.5 w-3.5" />
                    Marcar como lido
                  </Button>
                ) : null}
                {selected.status !== "arquivado" ? (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => handleChangeStatus(selected, "arquivado")}
                    disabled={savingId === selected.id}
                  >
                    <Archive className="mr-2 h-3.5 w-3.5" />
                    Arquivar
                  </Button>
                ) : (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => handleChangeStatus(selected, "lido")}
                    disabled={savingId === selected.id}
                  >
                    <ArchiveRestore className="mr-2 h-3.5 w-3.5" />
                    Desarquivar
                  </Button>
                )}
                <Button onClick={closeDetails}>Fechar</Button>
              </DialogFooter>
            </>
          ) : null}
        </DialogContent>
      </Dialog>
    </div>
  );
}

export default UserFeedbackManager;
