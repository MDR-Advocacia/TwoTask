import { useEffect, useState } from "react";
import { AlertTriangle, Edit3, Loader2, Plus, RefreshCw, Trash2, X } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
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
  fetchAllAdminNotices,
  updateAdminNotice,
} from "@/services/api";
import type {
  AdminNotice,
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
  starts_at: string;  // datetime-local string
  ends_at: string;
}

function blankForm(): FormState {
  // Default: aviso comeca em 5 min e termina em 1h. Operador editara'.
  const now = new Date();
  const start = new Date(now.getTime() + 5 * 60 * 1000);
  const end = new Date(now.getTime() + 60 * 60 * 1000);
  return {
    title: "",
    message: "",
    severity: "info",
    starts_at: isoToInputValue(start.toISOString()),
    ends_at: isoToInputValue(end.toISOString()),
  };
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
            <div className="grid gap-3 md:grid-cols-2">
              <div>
                <Label className="text-xs">Início *</Label>
                <Input
                  type="datetime-local"
                  value={form.starts_at}
                  onChange={(e) => setForm({ ...form, starts_at: e.target.value })}
                />
                <p className="text-[10px] text-muted-foreground mt-0.5">
                  Aviso so' aparece a partir desse momento.
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
                  <TableHead>Dispensado por</TableHead>
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
                      <TableCell className="max-w-[280px] truncate" title={n.title}>
                        {n.title}
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
                      <TableCell className="text-xs text-muted-foreground">
                        {n.dismissed_count} usuário(s)
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
    </div>
  );
}

export default AdminNoticesManager;
