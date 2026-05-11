/**
 * UploadsTab — Chunk 2 do Base Processual.
 *
 * UX KEY DIFFERENTIATOR do modulo: drag-and-drop -> POST /dry-run -> dialog
 * com summary + lista compacta de eventos previstos -> botao confirmar
 * -> POST /commit -> toast + invalidate dashboard + refresh historico.
 *
 * Reupload identico -> IDEMPOTENTE (toast informa, nao mostra dialog).
 * Erro de header -> FALHOU + mensagem clara apontando coluna faltante.
 */

import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import {
  AlertTriangle,
  CheckCircle2,
  Download,
  FileSpreadsheet,
  Info,
  Loader2,
  RotateCw,
  Upload,
} from "lucide-react";

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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

import {
  type BaseProcessualUploadOut,
  type BaseProcessualUploadResult,
  commitDryRun,
  downloadXlsxUrl,
  dryRunUpload,
  listUploads,
} from "@/lib/api-base-processual";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 25;

function formatBR(dateStr: string | null): string {
  if (!dateStr) return "—";
  try {
    const d = new Date(dateStr);
    return d.toLocaleString("pt-BR", { timeZone: "America/Sao_Paulo" });
  } catch {
    return dateStr;
  }
}

function statusBadge(status: string): JSX.Element {
  const variants: Record<
    string,
    { label: string; className: string }
  > = {
    CONCLUIDO: {
      label: "Concluído",
      className: "bg-emerald-100 text-emerald-900 dark:bg-emerald-900/30 dark:text-emerald-300",
    },
    DRY_RUN: {
      label: "Dry-run",
      className: "bg-sky-100 text-sky-900 dark:bg-sky-900/30 dark:text-sky-300",
    },
    IDEMPOTENTE: {
      label: "Reupload",
      className: "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300",
    },
    FALHOU: {
      label: "Falhou",
      className: "bg-red-100 text-red-900 dark:bg-red-900/30 dark:text-red-300",
    },
    PROCESSANDO: {
      label: "Processando",
      className: "bg-amber-100 text-amber-900 dark:bg-amber-900/30 dark:text-amber-300",
    },
  };
  const v = variants[status] ?? {
    label: status,
    className: "bg-zinc-100 text-zinc-700",
  };
  return <Badge className={cn("font-medium", v.className)}>{v.label}</Badge>;
}

export function UploadsTab() {
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);
  const [page, setPage] = useState(0);
  const [pendingDryRun, setPendingDryRun] =
    useState<BaseProcessualUploadResult | null>(null);

  const uploadsQuery = useQuery({
    queryKey: ["base-processual-uploads", page],
    queryFn: () => listUploads({ limit: PAGE_SIZE, offset: page * PAGE_SIZE }),
  });

  const dryRunMutation = useMutation({
    mutationFn: dryRunUpload,
    onSuccess: (result) => {
      if (result.status === "FALHOU") {
        toast.error("Upload falhou", {
          description: result.error_message ?? "Erro desconhecido.",
        });
        queryClient.invalidateQueries({ queryKey: ["base-processual-uploads"] });
        return;
      }
      if (result.is_idempotente) {
        toast.info("Reupload idêntico", {
          description:
            "Este XLSX já foi processado antes — nada novo a aplicar.",
        });
        queryClient.invalidateQueries({ queryKey: ["base-processual-uploads"] });
        return;
      }
      setPendingDryRun(result);
    },
    onError: (err: Error) =>
      toast.error("Erro no dry-run", { description: err.message }),
  });

  const commitMutation = useMutation({
    mutationFn: (id: number) => commitDryRun(id),
    onSuccess: (result) => {
      toast.success("Aplicado com sucesso", {
        description: `${result.summary_novos} novos · ${result.summary_atualizados} atualizados · ${result.summary_removidos} saídos · ${result.summary_inalterados} inalterados`,
      });
      setPendingDryRun(null);
      queryClient.invalidateQueries({ queryKey: ["base-processual-uploads"] });
      queryClient.invalidateQueries({
        queryKey: ["base-processual-dashboard"],
      });
    },
    onError: (err: Error) =>
      toast.error("Erro no commit", { description: err.message }),
  });

  const handleFile = (file: File) => {
    const name = file.name.toLowerCase();
    if (!name.endsWith(".xlsx")) {
      toast.error("Tipo inválido", { description: "Envie um arquivo .xlsx" });
      return;
    }
    dryRunMutation.mutate(file);
  };

  const data = uploadsQuery.data;
  const total = data?.total ?? 0;
  const items = data?.items ?? [];
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const from = total === 0 ? 0 : page * PAGE_SIZE + 1;
  const to = Math.min(total, (page + 1) * PAGE_SIZE);

  const isUploading = dryRunMutation.isPending;
  const isCommitting = commitMutation.isPending;

  return (
    <div className="space-y-6">
      {/* Upload zone */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Upload className="h-5 w-5" /> Subir nova planilha
          </CardTitle>
          <CardDescription>
            Arraste o XLSX (Listagem de Ações Judiciais do Legal One). Vamos
            simular o impacto antes de aplicar — você confirma se a planilha
            está correta.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div
            role="button"
            tabIndex={0}
            aria-label="Área de upload de arquivo XLSX"
            className={cn(
              "border-2 border-dashed rounded-lg p-12 text-center transition outline-none",
              "focus-visible:ring-2 focus-visible:ring-primary",
              isUploading
                ? "opacity-60 cursor-wait"
                : "cursor-pointer hover:border-primary/60",
              dragOver
                ? "border-primary bg-primary/5"
                : "border-muted-foreground/30",
            )}
            onDragOver={(e) => {
              e.preventDefault();
              if (!isUploading) setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragOver(false);
              if (isUploading) return;
              const f = e.dataTransfer.files?.[0];
              if (f) handleFile(f);
            }}
            onClick={() => !isUploading && fileInputRef.current?.click()}
            onKeyDown={(e) => {
              if ((e.key === "Enter" || e.key === " ") && !isUploading) {
                e.preventDefault();
                fileInputRef.current?.click();
              }
            }}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) handleFile(f);
                e.currentTarget.value = "";
              }}
            />
            {isUploading ? (
              <div className="flex flex-col items-center gap-2 text-muted-foreground">
                <Loader2 className="h-8 w-8 animate-spin" />
                <span className="text-sm">
                  Simulando o impacto da planilha... isso pode levar 30s pra
                  uma carteira de ~6 mil processos.
                </span>
              </div>
            ) : (
              <div className="flex flex-col items-center gap-2 text-muted-foreground">
                <FileSpreadsheet className="h-10 w-10" />
                <span className="text-sm">
                  Arraste o <strong>.xlsx</strong> ou clique para escolher
                </span>
                <span className="text-xs">Tamanho máximo: 30 MB</span>
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Historico */}
      <Card>
        <CardHeader>
          <CardTitle>Histórico de uploads</CardTitle>
          <CardDescription>
            Cada linha é uma submissão. Reuploads idênticos aparecem como{" "}
            <em>Reupload</em>. Dry-runs expiram em 30min.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {uploadsQuery.isLoading ? (
            <div className="flex items-center gap-2 text-muted-foreground py-8 justify-center">
              <Loader2 className="h-4 w-4 animate-spin" /> Carregando...
            </div>
          ) : uploadsQuery.isError ? (
            <div className="text-red-600 text-sm py-8 text-center">
              Erro ao carregar histórico.
            </div>
          ) : items.length === 0 ? (
            <div className="text-muted-foreground text-sm py-8 text-center">
              Nenhum upload ainda. Suba a primeira planilha acima.
            </div>
          ) : (
            <>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Data</TableHead>
                    <TableHead>Arquivo</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead className="text-right">Novos</TableHead>
                    <TableHead className="text-right">Saídos</TableHead>
                    <TableHead className="text-right">Atualizados</TableHead>
                    <TableHead className="text-right">Inalterados</TableHead>
                    <TableHead className="w-24"></TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {items.map((u) => (
                    <UploadRow key={u.id} u={u} />
                  ))}
                </TableBody>
              </Table>
              <div className="flex items-center justify-between mt-4 text-sm">
                <span className="text-muted-foreground">
                  {from}–{to} de {total}
                </span>
                <div className="flex items-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setPage((p) => Math.max(0, p - 1))}
                    disabled={page === 0}
                  >
                    Anterior
                  </Button>
                  <span className="text-muted-foreground">
                    Pág. {page + 1} de {totalPages}
                  </span>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() =>
                      setPage((p) => (p + 1 < totalPages ? p + 1 : p))
                    }
                    disabled={page + 1 >= totalPages}
                  >
                    Próxima
                  </Button>
                </div>
              </div>
            </>
          )}
        </CardContent>
      </Card>

      {/* Dry-run preview dialog */}
      <Dialog
        open={!!pendingDryRun}
        onOpenChange={(open) => {
          if (!open && !isCommitting) setPendingDryRun(null);
        }}
      >
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Info className="h-5 w-5" /> Confirmar aplicação
            </DialogTitle>
            <DialogDescription>
              Esta planilha vai alterar a base. Confira o impacto antes de
              aplicar — depois disso só dá pra desfazer caso a caso.
            </DialogDescription>
          </DialogHeader>
          {pendingDryRun && (
            <div className="space-y-4">
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <SummaryStat
                  label="Novos"
                  value={pendingDryRun.summary_novos}
                  tone="success"
                />
                <SummaryStat
                  label="Saídos"
                  value={pendingDryRun.summary_removidos}
                  tone="danger"
                />
                <SummaryStat
                  label="Atualizados"
                  value={pendingDryRun.summary_atualizados}
                  tone="warning"
                />
                <SummaryStat
                  label="Inalterados"
                  value={pendingDryRun.summary_inalterados}
                  tone="muted"
                />
              </div>
              {pendingDryRun.eventos_preview &&
                pendingDryRun.eventos_preview.length > 0 && (
                  <details className="border rounded-md p-3 text-sm bg-muted/40">
                    <summary className="cursor-pointer font-medium">
                      Ver primeiras{" "}
                      {Math.min(pendingDryRun.eventos_preview.length, 50)}{" "}
                      mudanças
                    </summary>
                    <ul className="mt-2 space-y-1 max-h-60 overflow-y-auto font-mono text-xs">
                      {pendingDryRun.eventos_preview
                        .slice(0, 50)
                        .map((e, i) => (
                          <li key={i} className="flex items-center gap-2">
                            <Badge
                              variant={
                                e.tipo === "ENTROU"
                                  ? "default"
                                  : e.tipo === "SAIU"
                                  ? "destructive"
                                  : "secondary"
                              }
                              className="text-[10px] uppercase tracking-wide"
                            >
                              {e.tipo}
                            </Badge>
                            <span className="text-foreground">
                              {e.cod_ajus}
                            </span>
                            {e.changed_fields && (
                              <span className="text-muted-foreground truncate">
                                · {Object.keys(e.changed_fields).join(", ")}
                              </span>
                            )}
                          </li>
                        ))}
                    </ul>
                  </details>
                )}
            </div>
          )}
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setPendingDryRun(null)}
              disabled={isCommitting}
            >
              Cancelar
            </Button>
            <Button
              onClick={() =>
                pendingDryRun &&
                commitMutation.mutate(pendingDryRun.upload_id)
              }
              disabled={isCommitting}
            >
              {isCommitting ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin mr-2" /> Aplicando...
                </>
              ) : (
                <>
                  <CheckCircle2 className="h-4 w-4 mr-2" /> Confirmar e aplicar
                </>
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function SummaryStat({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "success" | "danger" | "warning" | "muted";
}) {
  const toneClass: Record<typeof tone, string> = {
    success: "text-emerald-600 dark:text-emerald-400",
    danger: "text-red-600 dark:text-red-400",
    warning: "text-amber-600 dark:text-amber-400",
    muted: "text-muted-foreground",
  };
  return (
    <div className="rounded-md border p-3 text-center">
      <div className={cn("text-2xl font-semibold tabular-nums", toneClass[tone])}>
        {value.toLocaleString("pt-BR")}
      </div>
      <div className="text-xs text-muted-foreground uppercase tracking-wide mt-1">
        {label}
      </div>
    </div>
  );
}

function UploadRow({ u }: { u: BaseProcessualUploadOut }) {
  const isFailed = u.status === "FALHOU";
  return (
    <TableRow>
      <TableCell className="font-medium">{formatBR(u.uploaded_at)}</TableCell>
      <TableCell className="max-w-[16rem] truncate">
        <span title={u.filename}>{u.filename}</span>
        {isFailed && u.error_message && (
          <div className="text-xs text-red-600 dark:text-red-400 mt-1 flex items-start gap-1">
            <AlertTriangle className="h-3 w-3 mt-[2px] shrink-0" />
            <span className="line-clamp-2">{u.error_message}</span>
          </div>
        )}
      </TableCell>
      <TableCell>{statusBadge(u.status)}</TableCell>
      <TableCell className="text-right tabular-nums">
        {u.summary_novos.toLocaleString("pt-BR")}
      </TableCell>
      <TableCell className="text-right tabular-nums">
        {u.summary_removidos.toLocaleString("pt-BR")}
      </TableCell>
      <TableCell className="text-right tabular-nums">
        {u.summary_atualizados.toLocaleString("pt-BR")}
      </TableCell>
      <TableCell className="text-right tabular-nums">
        {u.summary_inalterados.toLocaleString("pt-BR")}
      </TableCell>
      <TableCell>
        {u.storage_path && (
          <a
            href={downloadXlsxUrl(u.id)}
            target="_blank"
            rel="noreferrer"
            title="Baixar XLSX original"
          >
            <Button variant="ghost" size="sm">
              <Download className="h-4 w-4" />
            </Button>
          </a>
        )}
      </TableCell>
    </TableRow>
  );
}
