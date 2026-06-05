import { useCallback, useEffect, useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Loader2, RefreshCw, ChevronLeft, ChevronRight } from "lucide-react";
import { useToast } from "@/components/ui/use-toast";
import {
  getGedBatchStatus,
  listGedBatchItems,
  retryGedBatchFailed,
  GedBatchStatus,
  GedUploadItem,
} from "@/services/api";
import { BATCH_STATUS_BADGE, ITEM_STATUS_BADGE } from "./shared";

interface Props {
  batchId: number | null;
  open: boolean;
  onOpenChange: (v: boolean) => void;
  onChanged?: () => void;
}

const PAGE_SIZE_DEFAULT = 50;

export default function BatchDetailDialog({ batchId, open, onOpenChange, onChanged }: Props) {
  const { toast } = useToast();
  const [status, setStatus] = useState<GedBatchStatus | null>(null);
  const [items, setItems] = useState<GedUploadItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(PAGE_SIZE_DEFAULT);
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [loadingItems, setLoadingItems] = useState(false);
  const [retrying, setRetrying] = useState(false);

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  const loadStatus = useCallback(async () => {
    if (batchId == null) return;
    try {
      setStatus(await getGedBatchStatus(batchId));
    } catch {
      /* silencioso durante o poll */
    }
  }, [batchId]);

  const loadItems = useCallback(async () => {
    if (batchId == null) return;
    setLoadingItems(true);
    try {
      const res = await listGedBatchItems(batchId, {
        status: statusFilter || undefined,
        limit: pageSize,
        offset: (page - 1) * pageSize,
      });
      setItems(res.items);
      setTotal(res.total);
    } catch (err) {
      toast({
        title: "Falha ao carregar itens",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setLoadingItems(false);
    }
  }, [batchId, statusFilter, pageSize, page, toast]);

  // Reset + carga inicial ao abrir.
  useEffect(() => {
    if (open && batchId != null) {
      setPage(1);
      setStatusFilter("");
      loadStatus();
    }
  }, [open, batchId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (open) loadItems();
  }, [open, loadItems]);

  // Polling de 4s enquanto o lote nao terminou.
  useEffect(() => {
    if (!open || !status || status.is_terminal) return;
    const timer = setInterval(() => {
      loadStatus();
      loadItems();
    }, 4000);
    return () => clearInterval(timer);
  }, [open, status, loadStatus, loadItems]);

  const handleRetry = async () => {
    if (batchId == null) return;
    setRetrying(true);
    try {
      const r = await retryGedBatchFailed(batchId);
      toast({ title: "Reprocessando", description: `${r.re_enqueued} item(ns) re-enfileirado(s).` });
      await loadStatus();
      await loadItems();
      onChanged?.();
    } catch (err) {
      toast({
        title: "Falha ao reprocessar",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setRetrying(false);
    }
  };

  const badge = status
    ? BATCH_STATUS_BADGE[status.status] || { label: status.status, variant: "outline" as const }
    : null;
  const canRetry = !!status && status.total_erro > 0 && !retrying;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            Lote #{batchId}
            {badge && <Badge variant={badge.variant}>{badge.label}</Badge>}
          </DialogTitle>
          <DialogDescription>
            Acompanhamento do envio ao GED — atualiza automaticamente.
          </DialogDescription>
        </DialogHeader>

        {status && (
          <div className="space-y-2">
            <Progress value={status.progress_pct} />
            <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
              <div className="flex gap-4">
                <span className="text-emerald-700">{status.total_sucesso} sucesso</span>
                <span className="text-rose-600">{status.total_erro} erro</span>
                <span className="text-muted-foreground">{status.total_pendente} pendente</span>
                <span className="font-medium">{status.progress_pct}%</span>
              </div>
              <Button size="sm" variant="outline" onClick={handleRetry} disabled={!canRetry}>
                {retrying ? (
                  <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
                ) : (
                  <RefreshCw className="mr-2 h-3.5 w-3.5" />
                )}
                Reprocessar falhas
              </Button>
            </div>
          </div>
        )}

        <div className="flex items-center gap-2">
          <select
            className="rounded border bg-background px-2 py-1 text-xs"
            value={statusFilter}
            onChange={(e) => {
              setStatusFilter(e.target.value);
              setPage(1);
            }}
          >
            <option value="">Todos os status</option>
            <option value="PENDENTE">Pendente</option>
            <option value="PROCESSANDO">Enviando</option>
            <option value="SUCESSO">Sucesso</option>
            <option value="ERRO">Erro</option>
            <option value="CNJ_NAO_ENCONTRADO">CNJ nao encontrado</option>
          </select>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              loadStatus();
              loadItems();
            }}
            disabled={loadingItems}
          >
            {loadingItems ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <RefreshCw className="h-3.5 w-3.5" />
            )}
          </Button>
        </div>

        <div className="max-h-72 overflow-y-auto rounded-md border">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-muted/60 text-left text-xs text-muted-foreground">
              <tr>
                <th className="px-2 py-1.5">CNJ</th>
                <th className="px-2 py-1.5">Arquivo</th>
                <th className="px-2 py-1.5">Status</th>
                <th className="px-2 py-1.5">Detalhe</th>
              </tr>
            </thead>
            <tbody>
              {items.length === 0 && !loadingItems ? (
                <tr>
                  <td colSpan={4} className="px-2 py-8 text-center text-muted-foreground">
                    Nenhum item.
                  </td>
                </tr>
              ) : (
                items.map((it) => {
                  const b =
                    ITEM_STATUS_BADGE[it.status] || {
                      label: it.status,
                      variant: "outline" as const,
                    };
                  return (
                    <tr key={it.id} className="border-t">
                      <td className="px-2 py-1.5 font-mono text-xs">
                        {it.cnj_masked || it.cnj_number || "—"}
                      </td>
                      <td className="px-2 py-1.5">
                        <div className="max-w-[200px] truncate" title={it.original_filename || ""}>
                          {it.original_filename || "—"}
                        </div>
                      </td>
                      <td className="px-2 py-1.5">
                        <Badge variant={b.variant}>{b.label}</Badge>
                      </td>
                      <td className="px-2 py-1.5 text-xs text-muted-foreground">
                        {it.status === "SUCESSO"
                          ? `GED #${it.ged_document_id}`
                          : it.error_message || "—"}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <div>
            Pagina {page} de {totalPages} · {items.length} de {total}
          </div>
          <div className="flex items-center gap-2">
            <select
              className="rounded border bg-background px-2 py-1 text-xs"
              value={pageSize}
              onChange={(e) => {
                setPageSize(Number(e.target.value));
                setPage(1);
              }}
            >
              <option value={25}>25</option>
              <option value={50}>50</option>
              <option value={100}>100</option>
            </select>
            <Button
              variant="outline"
              size="sm"
              className="h-7 w-7 p-0"
              disabled={page <= 1}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
            >
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="h-7 w-7 p-0"
              disabled={page >= totalPages}
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            >
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Fechar
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
