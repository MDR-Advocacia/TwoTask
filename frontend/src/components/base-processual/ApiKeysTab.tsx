/**
 * ApiKeysTab — Chunk 6.
 *
 * CRUD de API keys que dao acesso aos endpoints publicos
 * (/api/v1/public/base-processual/*).
 *
 * Plaintext da chave so' aparece UMA VEZ: na resposta do POST (criacao)
 * e do POST /regenerate. Mostrado num dialog com "copiar" + alerta de
 * "guarde agora, nao tem recuperacao".
 *
 * Scopes:
 * - read_processos: lista/get processos SEM money fields
 * - read_valores: idem + money fields visiveis
 * - read_dashboard: dashboard endpoints
 * - read_all: tudo
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  AlertTriangle,
  Check,
  Copy,
  KeyRound,
  Loader2,
  Plus,
  RefreshCw,
  Shield,
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

import {
  type ApiKeyCreateResponse,
  type ApiKeyOut,
  type ApiKeyScope,
  createApiKey,
  listApiKeys,
  regenerateApiKey,
  revokeApiKey,
} from "@/lib/api-base-processual";

const SCOPES: Array<{ value: ApiKeyScope; label: string; help: string }> = [
  {
    value: "read_processos",
    label: "read_processos",
    help: "Lista/get processos sem valores financeiros.",
  },
  {
    value: "read_valores",
    label: "read_valores",
    help: "Idem + libera valor_causa/acordo/contingência/etc.",
  },
  {
    value: "read_dashboard",
    label: "read_dashboard",
    help: "Acesso ao /dashboard/resumo (KPIs).",
  },
  {
    value: "read_all",
    label: "read_all",
    help: "Super-scope. Libera tudo.",
  },
];

function fmtBR(s: string | null): string {
  if (!s) return "—";
  try {
    return new Date(s).toLocaleString("pt-BR", { timeZone: "America/Sao_Paulo" });
  } catch {
    return s;
  }
}

function StatusBadge({ k }: { k: ApiKeyOut }) {
  if (k.revoked_at) {
    return (
      <Badge className="bg-red-100 text-red-900 dark:bg-red-900/30 dark:text-red-300 font-normal">
        Revogada
      </Badge>
    );
  }
  return (
    <Badge className="bg-emerald-100 text-emerald-900 dark:bg-emerald-900/30 dark:text-emerald-300 font-normal">
      Ativa
    </Badge>
  );
}

export function ApiKeysTab() {
  const queryClient = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [plaintext, setPlaintext] = useState<ApiKeyCreateResponse | null>(null);

  const listQ = useQuery({
    queryKey: ["base-processual-api-keys"],
    queryFn: () => listApiKeys({ include_revoked: true, limit: 100 }),
  });

  const createMut = useMutation({
    mutationFn: createApiKey,
    onSuccess: (result) => {
      setPlaintext(result);
      setCreateOpen(false);
      queryClient.invalidateQueries({ queryKey: ["base-processual-api-keys"] });
    },
    onError: (err: Error) =>
      toast.error("Falha ao criar chave", { description: err.message }),
  });

  const regenMut = useMutation({
    mutationFn: regenerateApiKey,
    onSuccess: (result) => {
      setPlaintext(result);
      queryClient.invalidateQueries({ queryKey: ["base-processual-api-keys"] });
    },
    onError: (err: Error) =>
      toast.error("Falha ao regenerar", { description: err.message }),
  });

  const revokeMut = useMutation({
    mutationFn: revokeApiKey,
    onSuccess: () => {
      toast.success("Chave revogada");
      queryClient.invalidateQueries({ queryKey: ["base-processual-api-keys"] });
    },
    onError: (err: Error) =>
      toast.error("Falha ao revogar", { description: err.message }),
  });

  const handleRevoke = (k: ApiKeyOut) => {
    if (!window.confirm(`Revogar a chave "${k.nome}"? Não pode ser desfeito.`)) {
      return;
    }
    revokeMut.mutate(k.id);
  };

  const handleRegenerate = (k: ApiKeyOut) => {
    if (
      !window.confirm(
        `Regenerar a chave "${k.nome}"? Esta ação INVALIDA o plaintext atual — sistemas que usam essa chave param de funcionar imediatamente.`,
      )
    ) {
      return;
    }
    regenMut.mutate(k.id);
  };

  const items = listQ.data?.items ?? [];

  return (
    <div className="space-y-4">
      <Alert>
        <Shield className="h-4 w-4" />
        <AlertTitle>API pública</AlertTitle>
        <AlertDescription>
          Chaves dão acesso aos endpoints públicos em{" "}
          <code>/api/v1/public/base-processual/*</code>. Use o header{" "}
          <code>X-Base-Processual-Key: bpk_…</code>. Plaintext aparece uma única
          vez no momento da criação ou regeneração — guarde em local seguro.
        </AlertDescription>
      </Alert>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0">
          <div>
            <CardTitle>Chaves de API</CardTitle>
            <CardDescription>
              {items.length} chave(s) ·{" "}
              {items.filter((k) => !k.revoked_at).length} ativa(s)
            </CardDescription>
          </div>
          <Button onClick={() => setCreateOpen(true)} size="sm">
            <Plus className="h-3 w-3 mr-2" /> Nova chave
          </Button>
        </CardHeader>
        <CardContent>
          {listQ.isLoading ? (
            <div className="py-6 text-center text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin mx-auto" />
            </div>
          ) : items.length === 0 ? (
            <div className="py-6 text-center text-muted-foreground text-sm">
              Nenhuma chave criada ainda. Clique em "Nova chave" pra começar.
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Nome</TableHead>
                  <TableHead className="w-36">Prefixo</TableHead>
                  <TableHead className="w-32">Scope</TableHead>
                  <TableHead className="w-20 text-right">Rate</TableHead>
                  <TableHead className="w-40">Último uso</TableHead>
                  <TableHead className="w-24">Status</TableHead>
                  <TableHead className="w-32 text-right">Ações</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((k) => (
                  <TableRow key={k.id}>
                    <TableCell>
                      <div className="text-sm font-medium">{k.nome}</div>
                      <div className="text-xs text-muted-foreground">
                        criada {fmtBR(k.created_at)}
                      </div>
                    </TableCell>
                    <TableCell className="font-mono text-xs">
                      {k.key_prefix}…
                    </TableCell>
                    <TableCell className="text-xs">{k.scope}</TableCell>
                    <TableCell className="text-right tabular-nums text-xs">
                      {k.rate_limit_per_min}/min
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {fmtBR(k.last_used_at)}
                    </TableCell>
                    <TableCell>
                      <StatusBadge k={k} />
                    </TableCell>
                    <TableCell className="text-right">
                      {!k.revoked_at && (
                        <div className="flex justify-end gap-1">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => handleRegenerate(k)}
                            disabled={regenMut.isPending}
                            title="Regenerar plaintext (invalida o atual)"
                          >
                            <RefreshCw className="h-4 w-4" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => handleRevoke(k)}
                            disabled={revokeMut.isPending}
                            title="Revogar"
                          >
                            <Trash2 className="h-4 w-4 text-red-600" />
                          </Button>
                        </div>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <CreateDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onSubmit={(data) => createMut.mutate(data)}
        isPending={createMut.isPending}
      />

      <PlaintextDialog
        data={plaintext}
        onClose={() => setPlaintext(null)}
      />
    </div>
  );
}

function CreateDialog({
  open,
  onClose,
  onSubmit,
  isPending,
}: {
  open: boolean;
  onClose: () => void;
  onSubmit: (data: { nome: string; scope: ApiKeyScope; rate_limit_per_min: number }) => void;
  isPending: boolean;
}) {
  const [nome, setNome] = useState("");
  const [scope, setScope] = useState<ApiKeyScope>("read_processos");
  const [rate, setRate] = useState(60);

  const handleClose = () => {
    if (!isPending) {
      setNome("");
      setScope("read_processos");
      setRate(60);
      onClose();
    }
  };

  const handleSubmit = () => {
    if (!nome.trim()) {
      toast.error("Nome obrigatório.");
      return;
    }
    onSubmit({ nome: nome.trim(), scope, rate_limit_per_min: rate });
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && handleClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <KeyRound className="h-4 w-4" /> Nova chave de API
          </DialogTitle>
          <DialogDescription>
            Use um nome descritivo (sistema/consumidor + finalidade). O plaintext
            aparece <strong>uma única vez</strong> no próximo passo.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <div>
            <Label className="text-xs">Nome</Label>
            <Input
              value={nome}
              onChange={(e) => setNome(e.target.value)}
              placeholder="Ex.: Sistema X — Banco Master"
              autoFocus
            />
          </div>
          <div>
            <Label className="text-xs">Scope</Label>
            <Select value={scope} onValueChange={(v) => setScope(v as ApiKeyScope)}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {SCOPES.map((s) => (
                  <SelectItem key={s.value} value={s.value}>
                    <div>
                      <div className="font-mono text-xs">{s.label}</div>
                      <div className="text-[11px] text-muted-foreground">
                        {s.help}
                      </div>
                    </div>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label className="text-xs">Rate limit (req/min)</Label>
            <Input
              type="number"
              min={1}
              max={6000}
              value={rate}
              onChange={(e) => setRate(Math.max(1, Number(e.target.value) || 60))}
            />
            <div className="text-[11px] text-muted-foreground mt-1">
              Sliding window 60s. Default 60. Aumente pra consumidores que
              fazem polling frequente.
            </div>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={handleClose} disabled={isPending}>
            Cancelar
          </Button>
          <Button onClick={handleSubmit} disabled={isPending}>
            {isPending ? (
              <Loader2 className="h-4 w-4 animate-spin mr-2" />
            ) : (
              <KeyRound className="h-4 w-4 mr-2" />
            )}
            Criar chave
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function PlaintextDialog({
  data,
  onClose,
}: {
  data: ApiKeyCreateResponse | null;
  onClose: () => void;
}) {
  const [copied, setCopied] = useState(false);

  const copy = () => {
    if (!data) return;
    navigator.clipboard
      .writeText(data.plaintext)
      .then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
        toast.success("Plaintext copiado.");
      })
      .catch(() => toast.error("Não consegui acessar o clipboard."));
  };

  return (
    <Dialog open={!!data} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Check className="h-4 w-4 text-emerald-600" /> Chave criada
          </DialogTitle>
          <DialogDescription>
            <strong>Copie o plaintext agora</strong> — ele só aparece nesta tela.
          </DialogDescription>
        </DialogHeader>
        {data && (
          <div className="space-y-3">
            <Alert variant="destructive">
              <AlertTriangle className="h-4 w-4" />
              <AlertTitle>Salve agora</AlertTitle>
              <AlertDescription>
                Não tem como recuperar depois. Se perder, regere a chave
                (invalidando esta) e atualize quem consome.
              </AlertDescription>
            </Alert>
            <div>
              <Label className="text-xs">Plaintext</Label>
              <div className="flex gap-2">
                <Input
                  value={data.plaintext}
                  readOnly
                  className="font-mono text-xs"
                  onFocus={(e) => e.currentTarget.select()}
                />
                <Button onClick={copy} variant="outline" size="icon">
                  {copied ? (
                    <Check className="h-4 w-4 text-emerald-600" />
                  ) : (
                    <Copy className="h-4 w-4" />
                  )}
                </Button>
              </div>
            </div>
            <div className="text-xs text-muted-foreground space-y-1">
              <div>
                <span className="font-medium text-foreground">Chave #{data.api_key.id}</span>
                {" "}· nome: {data.api_key.nome}
              </div>
              <div>
                Scope: <code>{data.api_key.scope}</code> · Rate: {data.api_key.rate_limit_per_min}/min
              </div>
              <div>
                Como usar:{" "}
                <code className="text-foreground">
                  GET /api/v1/public/base-processual/processos
                </code>
                {" "}com header{" "}
                <code className="text-foreground">
                  X-Base-Processual-Key: {data.api_key.key_prefix}…
                </code>
              </div>
            </div>
          </div>
        )}
        <DialogFooter>
          <Button onClick={onClose}>Fechar</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
