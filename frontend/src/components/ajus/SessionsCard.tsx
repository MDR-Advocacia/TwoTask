/**
 * Card "Sessões AJUS" da aba Classificação — multi-conta (Chunk 2a).
 *
 * Lista todas as contas configuradas, status individual e ações:
 *  - Cadastrar nova conta (modal com label/login/senha).
 *  - Editar (label/login/senha/ativo).
 *  - Login (dispara runner — Chunk 2b processa).
 *  - Submeter código de validação de IP (modal quando AJUS pede).
 *  - Encerrar sessão.
 *  - Deletar (só se não estiver executando).
 *
 * Refresh automático a cada 5s pra capturar mudanças de status feitas
 * pelo runner em background (offline → logando → aguardando_ip_code →
 * online → executando → online).
 */

import { useCallback, useEffect, useState } from "react";
import {
  AlertCircle,
  Ban,
  KeyRound,
  Loader2,
  LogIn,
  LogOut,
  Pencil,
  Plus,
  RefreshCw,
  ShieldAlert,
  Trash2,
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
import { useToast } from "@/hooks/use-toast";
import {
  createAjusSession,
  deleteAjusSession,
  fetchAjusSessionConfig,
  fetchAjusSessions,
  loginAjusSession,
  logoutAjusSession,
  submitAjusSessionIpCode,
  updateAjusSession,
} from "@/services/api";
import type {
  AjusAccountStatus,
  AjusSessionAccount,
  AjusSessionConfig,
} from "@/types/api";

const STATUS_BADGE: Record<AjusAccountStatus, { label: string; className: string }> = {
  offline: { label: "Offline", className: "bg-slate-50 text-slate-700 border-slate-300" },
  logando: { label: "Logando…", className: "bg-blue-50 text-blue-800 border-blue-300" },
  aguardando_ip_code: { label: "Aguardando IP", className: "bg-amber-50 text-amber-800 border-amber-300" },
  online: { label: "Online", className: "bg-emerald-50 text-emerald-800 border-emerald-300" },
  executando: { label: "Executando", className: "bg-violet-50 text-violet-800 border-violet-300" },
  erro: { label: "Erro", className: "bg-rose-50 text-rose-800 border-rose-300" },
};

interface FormState {
  id?: number;
  label: string;
  login: string;
  password: string;          // vazio = não troca em edit
  is_active: boolean;
}

const EMPTY_FORM: FormState = {
  label: "",
  login: "",
  password: "",
  is_active: true,
};

export function SessionsCard() {
  const { toast } = useToast();

  const [config, setConfig] = useState<AjusSessionConfig | null>(null);
  const [accounts, setAccounts] = useState<AjusSessionAccount[]>([]);
  const [loading, setLoading] = useState(false);
  const [actionId, setActionId] = useState<number | null>(null);
  // Mapa accountId -> lista de screenshots de debug. Carregado on-demand
  // quando a conta tem last_error_message (geralmente erro de login).
  const [debugByAcc, setDebugByAcc] = useState<Record<number, { name: string; size: number; mtime: number }[]>>({});

  // Modal de cadastro/edição
  const [formOpen, setFormOpen] = useState(false);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [formSaving, setFormSaving] = useState(false);

  // Modal de IP code
  const [ipCodeFor, setIpCodeFor] = useState<AjusSessionAccount | null>(null);
  const [ipCode, setIpCode] = useState("");
  const [ipCodeSaving, setIpCodeSaving] = useState(false);

  // ─── Loaders ──────────────────────────────────────────────────────
  const loadConfig = useCallback(async () => {
    try {
      const c = await fetchAjusSessionConfig();
      setConfig(c);
    } catch (e: unknown) {
      // não-fatal — UI mostra avisos genéricos
      // eslint-disable-next-line no-console
      console.warn("AJUS config load:", e);
    }
  }, []);

  const loadAccounts = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchAjusSessions();
      setAccounts(data);
    } catch (e: unknown) {
      toast({
        title: "Erro ao carregar sessões",
        description: e instanceof Error ? e.message : String(e),
        variant: "destructive",
      });
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => { loadConfig(); }, [loadConfig]);
  useEffect(() => { loadAccounts(); }, [loadAccounts]);

  // Refresh polling — captura mudanças do runner em background.
  useEffect(() => {
    const id = setInterval(() => {
      // Só polla se tem alguma conta em estado transitório
      const transitorios: AjusAccountStatus[] = [
        "logando", "aguardando_ip_code", "executando",
      ];
      if (accounts.some((a) => transitorios.includes(a.status))) {
        loadAccounts();
      }
    }, 5000);
    // Carrega lista de screenshots de debug pra contas com erro/offline.
  // Re-roda quando `accounts` muda — capta novos erros gerados pelo runner.
  useEffect(() => {
    const accountsWithError = accounts.filter(
      (a) => a.last_error_message && (a.status === "erro" || a.status === "offline"),
    );
    if (accountsWithError.length === 0) return;
    let cancelled = false;
    (async () => {
      const updates: Record<number, { name: string; size: number; mtime: number }[]> = {};
      for (const a of accountsWithError) {
        try {
          const files = await listAjusDebugScreenshots(a.id);
          updates[a.id] = files;
        } catch {
          // ignora — endpoint pode falhar se volume nao montado no api
        }
      }
      if (!cancelled && Object.keys(updates).length > 0) {
        setDebugByAcc((prev) => ({ ...prev, ...updates }));
      }
    })();
    return () => { cancelled = true; };
  }, [accounts]);

  return () => clearInterval(id);
  }, [accounts, loadAccounts]);

  // ─── Form handlers ────────────────────────────────────────────────
  const openCreate = () => { setForm(EMPTY_FORM); setFormOpen(true); };
  const openEdit = (a: AjusSessionAccount) => {
    setForm({
      id: a.id,
      label: a.label,
      login: a.login,
      password: "",
      is_active: a.is_active,
    });
    setFormOpen(true);
  };

  const handleSaveForm = async () => {
    if (!form.label.trim() || !form.login.trim()) {
      toast({ title: "Preencha label e login", variant: "destructive" });
      return;
    }
    if (!form.id && !form.password) {
      toast({ title: "Senha obrigatória pra nova conta", variant: "destructive" });
      return;
    }
    setFormSaving(true);
    try {
      if (form.id) {
        await updateAjusSession(form.id, {
          label: form.label,
          login: form.login,
          password: form.password || undefined,
          is_active: form.is_active,
        });
        toast({ title: "Conta atualizada" });
      } else {
        await createAjusSession({
          label: form.label,
          login: form.login,
          password: form.password,
        });
        toast({ title: "Conta cadastrada" });
      }
      setFormOpen(false);
      await loadAccounts();
    } catch (e: unknown) {
      toast({
        title: "Erro ao salvar",
        description: e instanceof Error ? e.message : String(e),
        variant: "destructive",
      });
    } finally {
      setFormSaving(false);
    }
  };

  // ─── Action handlers ──────────────────────────────────────────────
  const handleLogin = async (a: AjusSessionAccount) => {
    setActionId(a.id);
    try {
      await loginAjusSession(a.id);
      toast({
        title: "Login solicitado",
        description: "O runner vai processar nos próximos segundos. Acompanhe pelo status.",
      });
      await loadAccounts();
    } catch (e: unknown) {
      toast({
        title: "Erro ao solicitar login",
        description: e instanceof Error ? e.message : String(e),
        variant: "destructive",
      });
    } finally {
      setActionId(null);
    }
  };

  const handleLogout = async (a: AjusSessionAccount) => {
    if (!confirm(`Encerrar sessão de "${a.label}"?\n\nVai precisar logar de novo (e digitar IP code se AJUS pedir).`)) return;
    setActionId(a.id);
    try {
      await logoutAjusSession(a.id);
      toast({ title: "Sessão encerrada" });
      await loadAccounts();
    } catch (e: unknown) {
      toast({
        title: "Erro ao encerrar",
        description: e instanceof Error ? e.message : String(e),
        variant: "destructive",
      });
    } finally {
      setActionId(null);
    }
  };

  const handleDelete = async (a: AjusSessionAccount) => {
    if (!confirm(`Deletar conta "${a.label}"?\n\nNão pode estar executando. Histórico de classificações dessa conta fica como dispatched_by_account_id=NULL.`)) return;
    setActionId(a.id);
    try {
      await deleteAjusSession(a.id);
      toast({ title: "Conta deletada" });
      await loadAccounts();
    } catch (e: unknown) {
      toast({
        title: "Erro ao deletar",
        description: e instanceof Error ? e.message : String(e),
        variant: "destructive",
      });
    } finally {
      setActionId(null);
    }
  };

  const handleSubmitIpCode = async () => {
    if (!ipCodeFor) return;
    if (!ipCode.trim()) {
      toast({ title: "Digite o código", variant: "destructive" });
      return;
    }
    setIpCodeSaving(true);
    try {
      await submitAjusSessionIpCode(ipCodeFor.id, ipCode.trim());
      toast({ title: "Código enviado", description: "Runner vai consumir." });
      setIpCodeFor(null);
      setIpCode("");
      await loadAccounts();
    } catch (e: unknown) {
      toast({
        title: "Erro ao enviar código",
        description: e instanceof Error ? e.message : String(e),
        variant: "destructive",
      });
    } finally {
      setIpCodeSaving(false);
    }
  };

  // ─── Render ───────────────────────────────────────────────────────
  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <CardTitle className="text-base">Sessões AJUS</CardTitle>
            <CardDescription>
              Cadastre uma ou mais contas. O runner vai distribuir os
              processos da fila entre as contas online (round-robin).
              Mais contas = backlog drena mais rápido + resiliência se
              uma cair.
            </CardDescription>
          </div>
          <div className="flex items-end gap-2">
            <Button size="sm" variant="outline" onClick={loadAccounts} disabled={loading}>
              <RefreshCw className={`mr-2 h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
              Atualizar
            </Button>
            <Button size="sm" onClick={openCreate}>
              <Plus className="mr-1 h-3.5 w-3.5" />
              Nova conta
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* Avisos de config */}
        {config && !config.crypto_configured && (
          <Alert variant="destructive">
            <ShieldAlert className="h-4 w-4" />
            <AlertTitle>AJUS_FERNET_KEY não configurada</AlertTitle>
            <AlertDescription>
              Adicione a variável `AJUS_FERNET_KEY` no painel do Coolify
              (gere com `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`)
              antes de cadastrar contas. Sem isso, as senhas não conseguem
              ser criptografadas e o cadastro vai falhar.
            </AlertDescription>
          </Alert>
        )}
        {accounts.length === 0 && !loading && (
          <Alert>
            <AlertCircle className="h-4 w-4" />
            <AlertTitle>Nenhuma conta cadastrada</AlertTitle>
            <AlertDescription>
              Clique em "Nova conta" pra cadastrar. Você pode cadastrar
              quantas contas quiser — o dispatcher distribui os processos
              em round-robin entre as contas online.
            </AlertDescription>
          </Alert>
        )}

        {/* Grid de contas */}
        <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
          {accounts.map((a) => {
            const badge = STATUS_BADGE[a.status];
            const busy = actionId === a.id;
            return (
              <div
                key={a.id}
                className="rounded-lg border bg-card p-3 shadow-sm space-y-2"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="font-medium truncate">{a.label}</div>
                    <div className="text-xs text-muted-foreground truncate">
                      {a.login}
                    </div>
                  </div>
                  <Badge variant="outline" className={badge.className}>
                    {badge.label}
                  </Badge>
                </div>
                {!a.is_active && (
                  <Badge variant="outline" className="bg-slate-100 text-slate-700">
                    Desativada
                  </Badge>
                )}
                {a.last_error_message && (
                  <div className="text-xs text-destructive line-clamp-2" title={a.last_error_message}>
                    {a.last_error_message}
                  </div>
                )}
                {(debugByAcc[a.id] && debugByAcc[a.id].length > 0) && (
                  <a
                    href={ajusDebugScreenshotUrl(a.id, debugByAcc[a.id][0].name)}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-blue-600 hover:underline inline-flex items-center gap-1"
                    title={`${debugByAcc[a.id].length} screenshot(s) de debug. Mais recente: ${debugByAcc[a.id][0].name}`}
                  >
                    <ImageIcon className="h-3 w-3" />
                    Ver último screenshot ({debugByAcc[a.id].length})
                  </a>
                )}
                {a.last_used_at && (
                  <div className="text-[10px] text-muted-foreground">
                    Último uso: {new Date(a.last_used_at).toLocaleString("pt-BR")}
                  </div>
                )}
                <div className="flex flex-wrap gap-1 pt-1">
                  {(a.status === "offline" || a.status === "erro") && (
                    <Button size="sm" variant="outline" onClick={() => handleLogin(a)} disabled={busy || !a.is_active}>
                      <LogIn className="mr-1 h-3 w-3" />
                      Login
                    </Button>
                  )}
                  {a.status === "aguardando_ip_code" && (
                    <Button
                      size="sm"
                      onClick={() => { setIpCodeFor(a); setIpCode(""); }}
                      disabled={busy}
                    >
                      <KeyRound className="mr-1 h-3 w-3" />
                      Enviar código
                    </Button>
                  )}
                  {(a.status === "online" || a.status === "logando" || a.status === "aguardando_ip_code") && (
                    <Button size="sm" variant="outline" onClick={() => handleLogout(a)} disabled={busy}>
                      <LogOut className="mr-1 h-3 w-3" />
                      Encerrar
                    </Button>
                  )}
                  <Button size="sm" variant="outline" onClick={() => openEdit(a)} disabled={busy}>
                    <Pencil className="mr-1 h-3 w-3" />
                    Editar
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => handleDelete(a)} disabled={busy || a.status === "executando"}>
                    {busy ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : <Trash2 className="mr-1 h-3 w-3" />}
                  </Button>
                </div>
              </div>
            );
          })}
        </div>
      </CardContent>

      {/* Modal de cadastro/edição */}
      <Dialog open={formOpen} onOpenChange={setFormOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{form.id ? "Editar conta" : "Nova conta AJUS"}</DialogTitle>
            <DialogDescription>
              {form.id
                ? "Editar campos. Senha em branco mantém a atual; preenchida invalida o storage_state e força re-login."
                : "Cadastre uma conta humana do AJUS. Senha vai criptografada. Sessão é mantida por conta."}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1">
              <Label htmlFor="acc-label">Rótulo</Label>
              <Input
                id="acc-label"
                value={form.label}
                onChange={(e) => setForm({ ...form, label: e.target.value })}
                placeholder="Ex.: Conta MDR 1"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="acc-login">Login</Label>
              <Input
                id="acc-login"
                value={form.login}
                onChange={(e) => setForm({ ...form, login: e.target.value })}
                placeholder="usuario.ajus"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="acc-pwd">
                Senha {form.id && <span className="text-xs text-muted-foreground">(em branco mantém atual)</span>}
              </Label>
              <Input
                id="acc-pwd"
                type="password"
                value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
                placeholder={form.id ? "•••••••• (não trocar)" : "••••••••"}
                autoComplete="new-password"
              />
            </div>
            {form.id && (
              <div className="flex items-center gap-2">
                <input
                  id="acc-active"
                  type="checkbox"
                  className="h-4 w-4"
                  checked={form.is_active}
                  onChange={(e) => setForm({ ...form, is_active: e.target.checked })}
                />
                <Label htmlFor="acc-active">Conta ativa</Label>
              </div>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setFormOpen(false)}>
              Cancelar
            </Button>
            <Button onClick={handleSaveForm} disabled={formSaving}>
              {formSaving && <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />}
              {form.id ? "Salvar" : "Cadastrar"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Modal de IP code */}
      <Dialog open={!!ipCodeFor} onOpenChange={(open) => { if (!open) { setIpCodeFor(null); setIpCode(""); }}}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Código de validação de IP</DialogTitle>
            <DialogDescription>
              O AJUS pediu validação de IP pra "{ipCodeFor?.label}".
              Cole o código que chegou por e-mail.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-1">
            <Label htmlFor="ip-code">Código</Label>
            <Input
              id="ip-code"
              value={ipCode}
              onChange={(e) => setIpCode(e.target.value)}
              placeholder="Ex.: 123456"
              autoFocus
              onKeyDown={(e) => { if (e.key === "Enter") handleSubmitIpCode(); }}
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setIpCodeFor(null)}>
              Cancelar
            </Button>
            <Button onClick={handleSubmitIpCode} disabled={ipCodeSaving}>
              {ipCodeSaving && <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />}
              Enviar
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
