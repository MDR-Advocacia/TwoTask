import { useCallback, useEffect, useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import {
  ChevronLeft,
  ChevronRight,
  Loader2,
  RefreshCw,
  RotateCw,
  Square,
} from "lucide-react";
import { useToast } from "@/components/ui/use-toast";
import {
  CONTATO_ITEM_BADGE,
  ContatoBatch,
  ContatoItem,
  cancelContatosBatch,
  getContatosBatch,
  listContatosBatchItems,
  retryContatosBatch,
} from "@/services/contatosApi";

const PAGE_SIZE = 50;

function resultSummary(it: ContatoItem): string {
  const r = it.result;
  if (it.status === "NAO_ENCONTRADO") return "Documento não encontrado no Legal One";
  if (it.status === "DUPLICADO")
    return `${r?.found ?? "?"} contatos com o mesmo documento (tratar manual)`;
  if (!r) return "—";
  if (r.dry_run) {
    const p = r.planned;
    const nome = p.name?.length ? " · nome" : "";
    return `Plano: ${p.phones.length} tel · ${p.emails.length} email · ${p.addresses.length} endereço${nome}`;
  }
  const c = r.created;
  const nome = c.name ? " · nome" : "";
  return `Criados: ${c.phones} tel · ${c.emails} email · ${c.addresses} endereço${nome}`;
}

export default function ContatosBatchDetail({
  batchId,
  open,
  onOpenChange,
  onChanged,
}: {
  batchId: number | null;
  open: boolean;
  onOpenChange: (v: boolean) => void;
  onChanged: () => void;
}) {
  const { toast } = useToast();
  const [batch, setBatch] = useState<ContatoBatch | null>(null);
  const [items, setItems] = useState<ContatoItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [acting, setActing] = useState<"retry" | "cancel" | null>(null);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const load = useCallback(async () => {
    if (batchId == null) return;
    setLoading(true);
    try {
      const [b, its] = await Promise.all([
        getContatosBatch(batchId),
        listContatosBatchItems(batchId, {
          limit: PAGE_SIZE,
          offset: (page - 1) * PAGE_SIZE,
        }),
      ]);
      setBatch(b);
      setItems(its.items);
      setTotal(its.total);
    } catch (err) {
      toast({
        title: "Falha ao carregar lote",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setLoading(false);
    }
  }, [batchId, page, toast]);

  useEffect(() => {
    if (open) load();
  }, [open, load]);

  // Polling enquanto o lote nao terminou.
  useEffect(() => {
    if (!open || !batch || batch.is_terminal) return;
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
  }, [open, batch, load]);

  const handleRetry = async () => {
    if (batchId == null) return;
    setActing("retry");
    try {
      const r = await retryContatosBatch(batchId);
      toast({ title: "Reprocessamento enfileirado", description: `${r.re_enqueued} item(ns).` });
      load();
      onChanged();
    } catch (err) {
      toast({
        title: "Falha ao reprocessar",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setActing(null);
    }
  };

  const handleCancel = async () => {
    if (batchId == null) return;
    if (!confirm("Cancelar o lote? Os itens pendentes não serão processados.")) return;
    setActing("cancel");
    try {
      await cancelContatosBatch(batchId);
      toast({ title: "Lote cancelado" });
      load();
      onChanged();
    } catch (err) {
      toast({
        title: "Falha ao cancelar",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setActing(null);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-3xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            {batch ? `Lote #${batch.id} — ${batch.nome}` : "Lote"}
            {batch?.dry_run && (
              <Badge variant="outline" className="border-amber-300 text-amber-700">
                Simulação (dry-run)
              </Badge>
            )}
          </DialogTitle>
          <DialogDescription>
            {batch?.dry_run
              ? "Modo simulação: mostra o que SERIA enviado ao Legal One, sem escrever nada."
              : "Escrita real no Legal One (telefones/e-mail/endereço por contato)."}
          </DialogDescription>
        </DialogHeader>

        {batch && (
          <div className="space-y-4">
            <Progress value={batch.progress_pct} className="h-3" />
            <div className="grid grid-cols-2 gap-2 text-sm md:grid-cols-4">
              <div className="rounded-md bg-muted/40 p-2">
                <p className="text-muted-foreground">Total</p>
                <p className="font-semibold">{batch.total_itens}</p>
              </div>
              <div className="rounded-md bg-muted/40 p-2">
                <p className="text-muted-foreground">Sucesso</p>
                <p className="font-semibold text-green-700">{batch.total_sucesso}</p>
              </div>
              <div className="rounded-md bg-muted/40 p-2">
                <p className="text-muted-foreground">Erro/Não achado</p>
                <p className="font-semibold text-red-700">{batch.total_erro}</p>
              </div>
              <div className="rounded-md bg-muted/40 p-2">
                <p className="text-muted-foreground">Pendente</p>
                <p className="font-semibold">{batch.total_pendente}</p>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <Button variant="ghost" size="sm" onClick={load} disabled={loading}>
                {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
              </Button>
              {batch.total_erro > 0 && batch.status !== "CANCELLED" && (
                <Button variant="outline" size="sm" onClick={handleRetry} disabled={acting !== null}>
                  {acting === "retry" ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RotateCw className="mr-2 h-4 w-4" />}
                  Reprocessar falhas
                </Button>
              )}
              {!batch.is_terminal && (
                <Button variant="destructive" size="sm" onClick={handleCancel} disabled={acting !== null}>
                  {acting === "cancel" ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Square className="mr-2 h-4 w-4" />}
                  Cancelar
                </Button>
              )}
            </div>

            <div className="rounded-md border">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-xs text-muted-foreground">
                    <th className="p-2">Linha</th>
                    <th className="p-2">Documento</th>
                    <th className="p-2">Status</th>
                    <th className="p-2">Resultado</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((it) => {
                    const badge = CONTATO_ITEM_BADGE[it.status] || {
                      label: it.status,
                      className: "bg-gray-100 text-gray-700",
                    };
                    return (
                      <tr key={it.id} className="border-b align-top last:border-0">
                        <td className="p-2 text-xs text-muted-foreground">{it.row_number ?? "—"}</td>
                        <td className="p-2">
                          <div className="font-mono text-xs">{it.doc_number}</div>
                          <div className="text-[11px] text-muted-foreground">{it.doc_kind}</div>
                        </td>
                        <td className="p-2">
                          <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${badge.className}`}>
                            {badge.label}
                          </span>
                        </td>
                        <td className="p-2 text-xs">
                          <div>{resultSummary(it)}</div>
                          {it.result?.skipped?.length ? (
                            <div className="mt-0.5 text-muted-foreground">
                              Pulado: {it.result.skipped.join("; ")}
                            </div>
                          ) : null}
                          {it.error_message && (
                            <div className="mt-0.5 text-red-700">{it.error_message}</div>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                  {items.length === 0 && !loading && (
                    <tr>
                      <td colSpan={4} className="p-6 text-center text-sm text-muted-foreground">
                        Sem itens.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>

            <div className="flex items-center justify-between text-xs text-muted-foreground">
              <div>
                Página {page} de {totalPages} · {total} item(ns)
              </div>
              <div className="flex items-center gap-2">
                <Button variant="outline" size="sm" className="h-7 w-7 p-0" disabled={page <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))}>
                  <ChevronLeft className="h-4 w-4" />
                </Button>
                <Button variant="outline" size="sm" className="h-7 w-7 p-0" disabled={page >= totalPages} onClick={() => setPage((p) => Math.min(totalPages, p + 1))}>
                  <ChevronRight className="h-4 w-4" />
                </Button>
              </div>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
