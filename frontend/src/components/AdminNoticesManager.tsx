import { useEffect, useState } from "react";
import { AlertTriangle, Bell, Check, Edit3, Eye, Loader2, Plus, RefreshCw, Trash2, X } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
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
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/hooks/use-toast";
import {
  createAdminNotice,
  deleteAdminNotice,
  fetchAdminNoticeAudience,
  fetchAllAdminNotices,
  updateAdminNotice,
} from "@/services/api";
import type {
  AdminNotice,
  AdminNoticeAudience,
  AdminNoticeCreatePayload,
  AdminNoticeSeverity,
  AdminNoticeStatus,
} from "@/types/api";

const SEVERITY_LABEL: Record<AdminNoticeSeverity, string> = {
  info: "Informativo",
  warning: "Atenção",
  danger: "Crítico",
};

const SEVERITY_BADGE: Record<AdminNoticeSeverity, string> = {
  info: "bg-blue-100 text-blue-800",
  warning: "bg-amber-100 text-amber-800",
  danger: "bg-red-100 text-red-800",
};

const STATUS_BADGE: Record<AdminNoticeStatus, string> = {
  agendado: "bg-slate-100 text-slate-700",
  ativo: "bg-emerald-100 text-emerald-800",
  expirado: "bg-slate-200 text-slate-600",
};

/**
 * `<input type="datetime-local">` trabalha em timezone local do browser e
 * espera "YYYY-MM-DDTHH:mm". Isos do backend vem com sufixo Z (UTC). As
 * helpers abaixo convertem ida e volta sem perder precisao do dia.
 */
function isoToInputValue(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function inputValueToIso(local: string): string {
  if (!local) return "";
  // datetime-local nao tem TZ — interpretamos como local do browser e
  // convertemos pra ISO UTC. Backend persiste em UTC e o componente
  // AdminNoticeBar mostra de novo em local pt-BR.
  return new Date(local).toISOString();
}

function formatDateTime(iso: string): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("pt-BR", {
    timeZone: "America/Fortaleza",
    dateStyle: "short",
    timeStyle: "short",
  });
}


interface FormState {
  title: string;
  message: string;
  severity: AdminNoticeSeverity;
  require_ack: boolean;
  starts_at: string;  // datetime-local string
  ends_at: string;
}

function blankForm(): FormState {
  // Default: aviso ja' fica ativo imediatamente (starts_at = agora - 1min,
  // pra cobrir o gap ate' o proximo poll do front e evitar que o operador
  // pense que o sistema esta' lento). Termina em 1h. Pra agendar pro
  // futuro o operador edita o campo Inicio. (Antes era +5min, mas isso
  // dava sensacao de "demorou muito pra aparecer" pq todo aviso saia
  // agendado por padrao.)
  const now = new Date();
  const start = new Date(now.getTime() - 60 * 1000);
  const end = new Date(now.getTime() + 60 * 60 * 1000);
  return {
    title: "",
    message: "",
    severity: "info",
    require_ack: false,
    starts_at: isoToInputValue(start.toISOString()),
    ends_at: isoToInputValue(end.toISOString()),
  };
}


function AudienceColumn({
  title,
  Icon,
  iconClass,
  entries,
}: {
  title: string;
  Icon: React.ComponentType<{ className?: string }>;
  iconClass: string;
  entries: AdminNoticeAudience["seen"];
}) {
  return (
    <div className="rounded-md border">
      <div className="flex items-center gap-2 border-b bg-slate-50 px-3 py-2 text-sm font-medium">
        <Icon className={`h-4 w-4 ${iconClass}`} />
        {title}
        <span className="ml-auto text-xs text-muted-foreground">{entries.length}</span>
      </div>
      {entries.length === 0 ? (
        <p className="px-3 py-6 text-center text-xs text-muted-foreground">
          Ninguém ainda.
        </p>
      ) : (
        <ul className="divide-y">
          {entries.map((e) => (
            <li key={e.user_id} className="px-3 py-2">
              <div className="text-sm font-medium text-slate-800">
                {e.name || e.email || `Usuário ${e.user_id}`}
              </div>
              {e.email ? (
                <div className="text-xs text-muted-foreground">{e.email}</div>
              ) : null}
              <div className="mt-0.5 text-[11px] text-muted-foreground">
                {formatDateTime(e.at)}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}


export function AdminNoticesManager() {
  const { toast } = useToast();
  const [notices, setNotices] = useState<AdminNotice[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<AdminNotice | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<FormState>(blankForm());
  const [submitting, setSubmitting] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  // Painel de audiencia (quem viu / quem confirmou) — aberto pelo contador.
  const [audienceNotice, setAudienceNotice] = useState<AdminNotice | null>(null);
  const [audience, setAudience] = useState<AdminNoticeAudience | null>(null);
  const [audienceLoading, setAudienceLoading] = useState(false);

  const load = async () => {
    setIsLoading(true);
    try {
      const data = await fetchAllAdminNotices();
      setNotices(data);
      setError(null);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Falha ao carregar.";
      setError(msg);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const openCreate = () => {
    setEditing(null);
    setForm(blankForm());
    setShowForm(true);
  };

  const openEdit = (notice: AdminNotice) => {
    setEditing(notice);
    setForm({
      title: notice.title,
      message: notice.message,
      severity: notice.severity,
      require_ack: notice.require_ack,
      starts_at: isoToInputValue(notice.starts_at),
      ends_at: isoToInputValue(notice.ends_at),
    });
    setShowForm(true);
  };

  const closeForm = () => {
    setShowForm(false);
    setEditing(null);
    setForm(blankForm());
  };

  const validate = (): string | null => {
    if (!form.title.trim()) return "Titulo eh obrigatorio.";
    if (!form.message.trim()) return "Mensagem eh obrigatoria.";
    if (!form.starts_at) return "Inicio eh obrigatorio.";
    if (!form.ends_at) return "Fim eh obrigatorio.";
    if (new Date(form.ends_at) <= new Date(form.starts_at)) {
      return "Fim precisa ser depois do inicio.";
    }
    return null;
  };

  const handleSave = async () => {
    const err = validate();
    if (err) {
      toast({ title: "Campo invalido", description: err, variant: "destructive" });
      return;
    }
    setSubmitting(true);
    try {
      const payload: AdminNoticeCreatePayload = {
        title: form.title.trim(),
        message: form.message.trim(),
        severity: form.severity,
        require_ack: form.require_ack,
        starts_at: inputValueToIso(form.starts_at),
        ends_at: inputValueToIso(form.ends_at),
      };
      if (editing) {
        await updateAdminNotice(editing.id, payload);
        toast({ title: "Aviso atualizado" });
      } else {
        await createAdminNotice(payload);
        toast({ title: "Aviso criado" });
      }
      closeForm();
      await load();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Falha ao salvar.";
      toast({ title: "Falha ao salvar aviso", description: msg, variant: "destructive" });
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (notice: AdminNotice) => {
    if (
      !window.confirm(
        `Apagar o aviso "${notice.title}"? Os dismissals dos usuarios tambem serao removidos.`,
      )
    ) {
      return;
    }
    setDeletingId(notice.id);
    try {
      await deleteAdminNotice(notice.id);
      toast({ title: "Aviso apagado" });
      await load();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Falha ao apagar.";
      toast({ title: "Falha ao apagar", description: msg, variant: "destructive" });
    } finally {
      setDeletingId(null);
    }
  };

  const openAudience = async (notice: AdminNotice) => {
    setAudienceNotice(notice);
    setAudience(null);
    setAudienceLoading(true);
    try {
      const data = await fetchAdminNoticeAudience(notice.id);
      setAudience(data);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Falha ao carregar.";
      toast({
        title: "Falha ao carregar audiência",
        description: msg,
        variant: "destructive",
      });
      setAudienceNotice(null);
    } finally {
      setAudienceLoading(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">Avisos broadcast</h2>
          <p className="text-sm text-muted-foreground">
            Banners exibidos no topo da app pra todos os usuarios autenticados,
            dentro da janela de inicio/fim. Polling de 30s no front; cada user
            ve uma vez (clicar X marca dismiss persistente).
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={load} disabled={isLoading}>
            <RefreshCw className={`mr-2 h-4 w-4 ${isLoading ? "animate-spin" : ""}`} />
            Atualizar
          </Button>
          <Button size="sm" onClick={openCreate}>
            <Plus className="mr-2 h-4 w-4" />
            Novo aviso
          </Button>
        </div>
      </div>

      {error ? (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>Falha ao carregar</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      {showForm ? (
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <div>
              <CardTitle>{editing ? `Editar aviso #${editing.id}` : "Novo aviso"}</CardTitle>
              <CardDescription>
                Editar mantém os dismissals existentes (quem ja' fechou o
                anterior nao re-recebe). Pra forcar todos a verem de novo,
                apague e crie um novo.
              </CardDescription>
            </div>
            <Button variant="ghost" size="sm" onClick={closeForm}>
              <X className="h-4 w-4" />
            </Button>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="grid gap-3 md:grid-cols-2">
              <div>
                <Label className="text-xs">Título *</Label>
                <Input
                  value={form.title}
                  onChange={(e) => setForm({ ...form, title: e.target.value })}
                  placeholder="Ex.: Manutencao programada do Legal One"
                  maxLength={200}
                />
              </div>
              <div>
                <Label className="text-xs">Severidade</Label>
                <Select
                  value={form.severity}
                  onValueChange={(v) =>
                    setForm({ ...form, severity: v as AdminNoticeSeverity })
                  }
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="info">Informativo (azul)</SelectItem>
                    <SelectItem value="warning">Atenção (amarelo)</SelectItem>
                    <SelectItem value="danger">Crítico (vermelho)</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div>
              <Label className="text-xs">Mensagem *</Label>
              <Textarea
                rows={3}
                value={form.message}
                onChange={(e) => setForm({ ...form, message: e.target.value })}
                placeholder="Conteudo do aviso. Pode quebrar linha pra detalhes."
              />
            </div>
            <div className="rounded-md border bg-slate-50 p-3">
              <div className="flex items-start gap-2.5">
                <Checkbox
                  id="notice-require-ack"
                  checked={form.require_ack}
                  onCheckedChange={(v) =>
                    setForm({ ...form, require_ack: Boolean(v) })
                  }
                  className="mt-0.5"
                />
                <div>
                  <Label htmlFor="notice-require-ack" className="cursor-pointer font-medium">
                    Exibir como pop-up (exige clicar em "Ciente")
                  </Label>
                  <p className="text-[11px] text-muted-foreground mt-0.5">
                    Marcado: abre um modal bloqueante na tela do usuário, que só
                    some ao clicar "Ciente". Desmarcado: banner discreto no topo
                    da app, fechável no X.
                  </p>
                </div>
              </div>
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              <div>
                <Label className="text-xs">Início *</Label>
                <Input
                  type="datetime-local"
                  value={form.starts_at}
                  onChange={(e) => setForm({ ...form, starts_at: e.target.value })}
                />
                <p className="text-[10px] text-muted-foreground mt-0.5">
                  Por padrão começa agora. Edite pra agendar pro futuro
                  (aviso fica como "agendado" até o horário marcado).
                </p>
              </div>
              <div>
                <Label className="text-xs">Fim *</Label>
                <Input
                  type="datetime-local"
                  value={form.ends_at}
                  onChange={(e) => setForm({ ...form, ends_at: e.target.value })}
                />
                <p className="text-[10px] text-muted-foreground mt-0.5">
                  Apos esse momento, ninguem mais ve (mesmo quem nunca fechou).
                </p>
              </div>
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <Button variant="outline" onClick={closeForm} disabled={submitting}>
                Cancelar
              </Button>
              <Button onClick={handleSave} disabled={submitting}>
                {submitting ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : null}
                {editing ? "Salvar" : "Criar"}
              </Button>
            </div>
          </CardContent>
        </Card>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>Histórico ({notices.length})</CardTitle>
          <CardDescription>
            Lista todos os avisos (agendados, ativos e expirados).
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>ID</TableHead>
                  <TableHead>Título</TableHead>
                  <TableHead>Severidade</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Início</TableHead>
                  <TableHead>Fim</TableHead>
                  <TableHead>Audiência</TableHead>
                  <TableHead className="text-right">Ações</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {notices.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={8} className="py-10 text-center text-muted-foreground">
                      {isLoading ? "Carregando..." : "Nenhum aviso cadastrado."}
                    </TableCell>
                  </TableRow>
                ) : (
                  notices.map((n) => (
                    <TableRow key={n.id}>
                      <TableCell className="font-mono text-xs">#{n.id}</TableCell>
                      <TableCell className="max-w-[280px]">
                        <div className="flex items-center gap-2">
                          <span className="truncate" title={n.title}>{n.title}</span>
                          {n.require_ack ? (
                            <span
                              className="shrink-0 inline-flex items-center gap-1 rounded border border-violet-300 bg-violet-50 px-1.5 py-0.5 text-[10px] font-medium text-violet-700"
                              title="Aparece como pop-up bloqueante (exige Ciente)"
                            >
                              <Bell className="h-3 w-3" /> Pop-up
                            </span>
                          ) : null}
                        </div>
                      </TableCell>
                      <TableCell>
                        <Badge className={SEVERITY_BADGE[n.severity]}>
                          {SEVERITY_LABEL[n.severity]}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <Badge className={STATUS_BADGE[n.status]}>{n.status}</Badge>
                      </TableCell>
                      <TableCell className="text-xs">{formatDateTime(n.starts_at)}</TableCell>
                      <TableCell className="text-xs">{formatDateTime(n.ends_at)}</TableCell>
                      <TableCell className="text-xs">
                        <button
                          type="button"
                          onClick={() => openAudience(n)}
                          className="inline-flex items-center gap-3 rounded-md px-2 py-1 hover:bg-slate-100"
                          title="Ver quem viu e quem confirmou"
                        >
                          <span className="inline-flex items-center gap-1 text-slate-600">
                            <Eye className="h-3.5 w-3.5" />
                            {n.seen_count}
                          </span>
                          <span className="inline-flex items-center gap-1 text-emerald-700">
                            <Check className="h-3.5 w-3.5" />
                            {n.dismissed_count}
                          </span>
                        </button>
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex items-center justify-end gap-1">
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-7 w-7 p-0"
                            onClick={() => openEdit(n)}
                            title="Editar"
                          >
                            <Edit3 className="h-3.5 w-3.5" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-7 w-7 p-0 text-red-700 hover:bg-red-50"
                            onClick={() => handleDelete(n)}
                            disabled={deletingId === n.id}
                            title="Apagar"
                          >
                            {deletingId === n.id ? (
                              <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            ) : (
                              <Trash2 className="h-3.5 w-3.5" />
                            )}
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      <Dialog
        open={audienceNotice !== null}
        onOpenChange={(open) => {
          if (!open) {
            setAudienceNotice(null);
            setAudience(null);
          }
        }}
      >
        <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>
              Audiência{audienceNotice ? ` — #${audienceNotice.id} ${audienceNotice.title}` : ""}
            </DialogTitle>
            <DialogDescription>
              "Viu" = aviso renderizado na tela do usuário (impressão).
              "Confirmou" = clicou em Ciente/fechou o aviso.
            </DialogDescription>
          </DialogHeader>
          {audienceLoading ? (
            <div className="flex items-center justify-center py-10 text-muted-foreground">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Carregando...
            </div>
          ) : audience ? (
            <div className="grid gap-4 md:grid-cols-2">
              <AudienceColumn
                title="Confirmou (Ciente)"
                Icon={Check}
                iconClass="text-emerald-700"
                entries={audience.acknowledged}
              />
              <AudienceColumn
                title="Viu"
                Icon={Eye}
                iconClass="text-slate-600"
                entries={audience.seen}
              />
            </div>
          ) : null}
        </DialogContent>
      </Dialog>
    </div>
  );
}

export default AdminNoticesManager;
