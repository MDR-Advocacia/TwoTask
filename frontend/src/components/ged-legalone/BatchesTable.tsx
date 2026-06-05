import { useCallback, useEffect, useState } from "react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Loader2,
  Eye,
  Trash2,
  RefreshCw,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import { useToast } from "@/components/ui/use-toast";
import { listGedBatches, deleteGedBatch, GedUploadBatch } from "@/services/api";
import { BATCH_STATUS_BADGE, MODE_LABEL, fmtDate } from "./shared";
import BatchDetailDialog from "./BatchDetailDialog";

const PAGE_SIZE_DEFAULT = 25;

export default function BatchesTable({
  reloadKey,
  onChanged,
}: {
  reloadKey: number;
  onChanged: () => void;
}) {
  const { toast } = useToast();
  const [items, setItems] = useState<GedUploadBatch[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(PAGE_SIZE_DEFAULT);
  const [loading, setLoading] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [detailId, setDetailId] = useState<number | null>(null);

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listGedBatches({
        limit: pageSize,
        offset: (page - 1) * pageSize,
      });
      setItems(res.items);
      setTotal(res.total);
    } catch (err) {
      toast({
        title: "Falha ao carregar lotes",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, toast]);

  useEffect(() => {
    load();
  }, [load, reloadKey]);

  // Auto-refresh leve pra refletir o progresso dos lotes em andamento.
  useEffect(() => {
    const timer = setInterval(load, 8000);
    return () => clearInterval(timer);
  }, [load]);

  const handleDelete = async (id: number) => {
    if (
      !confirm(
        `Apagar lote #${id}? Remove os itens e os arquivos do servidor. Nao pode ser desfeito.`,
      )
    )
      return;
    setDeletingId(id);
    try {
      await deleteGedBatch(id);
      toast({ title: "Lote apagado", description: `#${id} removido.` });
      load();
      onChanged();
    } catch (err) {
      toast({
        title: "Falha ao apagar",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <div>
          <CardTitle className="text-base">Lotes de envio</CardTitle>
          <CardDescription>Cada linha e' um envio em lote. Total: {total}.</CardDescription>
        </div>
        <Button variant="ghost" size="sm" onClick={load} disabled={loading}>
          {loading ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <RefreshCw className="h-4 w-4" />
          )}
        </Button>
      </CardHeader>
      <CardContent>
        {loading && items.length === 0 ? (
          <div className="py-12 text-center text-sm text-muted-foreground">
            <Loader2 className="mr-2 inline h-4 w-4 animate-spin" />
            Carregando...
          </div>
        ) : items.length === 0 ? (
          <div className="py-12 text-center text-sm text-muted-foreground">
            Nenhum lote ainda. Use a aba "Enviar" pra comecar.
          </div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-xs text-muted-foreground">
                    <th className="py-2 pr-3">#</th>
                    <th className="py-2 pr-3">Nome</th>
                    <th className="py-2 pr-3">Modo</th>
                    <th className="py-2 pr-3">Status</th>
                    <th className="py-2 pr-3">Progresso</th>
                    <th className="py-2 pr-3">Criado em</th>
                    <th className="py-2 pr-3" />
                  </tr>
                </thead>
                <tbody>
                  {items.map((b) => {
                    const badge = BATCH_STATUS_BADGE[b.status] || {
                      label: b.status,
                      variant: "outline" as const,
                    };
                    return (
                      <tr key={b.id} className="border-b hover:bg-muted/30">
                        <td className="py-2 pr-3 font-mono text-xs">#{b.id}</td>
                        <td className="py-2 pr-3">{b.nome}</td>
                        <td className="py-2 pr-3 text-xs text-muted-foreground">
                          {MODE_LABEL[b.mode] || b.mode}
                        </td>
                        <td className="py-2 pr-3">
                          <Badge variant={badge.variant}>{badge.label}</Badge>
                        </td>
                        <td className="py-2 pr-3 tabular-nums">
                          {b.total_sucesso}/{b.total_itens}
                          {b.total_erro > 0 && (
                            <span className="text-rose-600"> ({b.total_erro} erro)</span>
                          )}
                        </td>
                        <td className="py-2 pr-3 text-xs text-muted-foreground">
                          {fmtDate(b.created_at)}
                        </td>
                        <td className="py-2 pr-3 text-right">
                          <div className="inline-flex items-center gap-0.5">
                            <Button
                              variant="ghost"
                              size="icon"
                              onClick={() => setDetailId(b.id)}
                              title="Acompanhar envio"
                            >
                              <Eye className="h-4 w-4" />
                            </Button>
                            <Button
                              variant="ghost"
                              size="icon"
                              onClick={() => handleDelete(b.id)}
                              disabled={deletingId === b.id}
                              title="Apagar lote"
                            >
                              {deletingId === b.id ? (
                                <Loader2 className="h-4 w-4 animate-spin" />
                              ) : (
                                <Trash2 className="h-4 w-4" />
                              )}
                            </Button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <div className="mt-3 flex items-center justify-between text-xs text-muted-foreground">
              <div>
                Pagina {page} de {totalPages} · Mostrando {items.length} de {total}
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
          </>
        )}
      </CardContent>

      <BatchDetailDialog
        batchId={detailId}
        open={detailId != null}
        onOpenChange={(v) => !v && setDetailId(null)}
        onChanged={load}
      />
    </Card>
  );
}
