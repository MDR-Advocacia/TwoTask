import { useCallback, useRef, useState } from "react";
import type { ReactNode } from "react";
import { FileUp, FilePlus, Loader2, X, FileText } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { uploadPrazoInicialPdf } from "@/services/api";

const MAX_PROCESSO_MB = 100;
const CONCURRENCY = 3;

type ItemStatus =
  | "pending"
  | "uploading"
  | "done"
  | "duplicate"
  | "extraction_failed"
  | "error";

interface Item {
  file: File;
  status: ItemStatus;
  message?: string;
}

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Chamado ao terminar o lote — a página pai recarrega a listagem. */
  onSuccess?: () => void;
}

const STATUS_LABEL: Record<ItemStatus, string> = {
  pending: "Na fila",
  uploading: "Enviando…",
  done: "Criado",
  duplicate: "Já existia",
  extraction_failed: "Sem texto (manual)",
  error: "Erro",
};

const STATUS_CLASS: Record<ItemStatus, string> = {
  pending: "bg-slate-100 text-slate-700",
  uploading: "bg-blue-100 text-blue-800",
  done: "bg-emerald-100 text-emerald-800",
  duplicate: "bg-slate-100 text-slate-600",
  extraction_failed: "bg-amber-100 text-amber-800",
  error: "bg-red-100 text-red-800",
};

/**
 * Upload de petição inicial em LOTE (USER_UPLOAD em massa).
 *
 * Client-loop sobre o endpoint single `/intake/upload`: cada PDF vira um
 * intake independente (extração mecânica + idempotência por SHA no backend).
 * Roda com cap de concorrência (CONCURRENCY) e mostra status por arquivo +
 * resumo no final. A habilitação NÃO vai no lote — é por-processo e rara em
 * massa; operador usa o upload individual quando precisa anexá-la.
 */
export function UploadProcessoLoteDialog({ open, onOpenChange, onSuccess }: Props) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [items, setItems] = useState<Item[]>([]);
  const [running, setRunning] = useState(false);
  const [finished, setFinished] = useState(false);

  const reset = useCallback(() => {
    setItems([]);
    setRunning(false);
    setFinished(false);
  }, []);

  const handleClose = useCallback(
    (next: boolean) => {
      if (running) return; // não fecha no meio do envio
      if (!next) reset();
      onOpenChange(next);
    },
    [onOpenChange, reset, running],
  );

  const addFiles = useCallback((fileList: FileList | null) => {
    if (!fileList) return;
    const picked = Array.from(fileList).filter(
      (f) => f.type === "application/pdf" || f.name.toLowerCase().endsWith(".pdf"),
    );
    setItems((prev) => {
      const existing = new Set(prev.map((it) => `${it.file.name}:${it.file.size}`));
      const novos = picked
        .filter((f) => !existing.has(`${f.name}:${f.size}`))
        .map((f) => ({ file: f, status: "pending" as ItemStatus }));
      return [...prev, ...novos];
    });
    setFinished(false);
  }, []);

  const removeAt = useCallback((idx: number) => {
    setItems((prev) => prev.filter((_, i) => i !== idx));
  }, []);

  const updateItem = useCallback((idx: number, patch: Partial<Item>) => {
    setItems((prev) => prev.map((it, i) => (i === idx ? { ...it, ...patch } : it)));
  }, []);

  const start = useCallback(async () => {
    const files = items.map((it) => it.file);
    if (!files.length) return;
    setRunning(true);
    setFinished(false);
    let next = 0;
    const worker = async () => {
      while (next < files.length) {
        const i = next++;
        if (files[i].size / 1024 / 1024 > MAX_PROCESSO_MB) {
          updateItem(i, { status: "error", message: `Excede ${MAX_PROCESSO_MB} MB` });
          continue;
        }
        updateItem(i, { status: "uploading", message: undefined });
        try {
          const r = await uploadPrazoInicialPdf(files[i], null);
          const st: ItemStatus = r.already_existed
            ? "duplicate"
            : r.pdf_extraction_failed
              ? "extraction_failed"
              : "done";
          updateItem(i, { status: st, message: r.user_message || undefined });
        } catch (e) {
          updateItem(i, {
            status: "error",
            message: e instanceof Error ? e.message : "Falha no upload",
          });
        }
      }
    };
    await Promise.all(
      Array.from({ length: Math.min(CONCURRENCY, files.length) }, () => worker()),
    );
    setRunning(false);
    setFinished(true);
    onSuccess?.();
  }, [items, updateItem, onSuccess]);

  const counts = items.reduce(
    (acc, it) => {
      acc[it.status] = (acc[it.status] || 0) + 1;
      return acc;
    },
    {} as Record<ItemStatus, number>,
  );

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FileUp className="h-5 w-5" />
            Subir processos em lote
          </DialogTitle>
          <DialogDescription>
            Selecione vários PDFs de processo de uma vez — cada um vira um intake
            (extração mecânica; PDFs escaneados entram pra classificação manual).
            A habilitação não vai no lote; use o upload individual quando precisar.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3 py-2">
          <input
            ref={inputRef}
            type="file"
            accept="application/pdf"
            multiple
            className="hidden"
            data-testid="upload-lote-input"
            onChange={(e) => {
              addFiles(e.target.files);
              e.target.value = "";
            }}
            disabled={running}
          />
          <Button
            type="button"
            variant="outline"
            onClick={() => inputRef.current?.click()}
            disabled={running}
          >
            <FilePlus className="mr-2 h-4 w-4" />
            Escolher PDFs
          </Button>

          {items.length > 0 ? (
            <div className="max-h-72 divide-y overflow-y-auto rounded-md border">
              {items.map((it, idx) => (
                <div key={`${it.file.name}-${idx}`} className="flex items-center gap-3 p-2 text-sm">
                  <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
                  <div className="min-w-0 flex-1">
                    <div className="truncate" title={it.file.name}>
                      {it.file.name}
                    </div>
                    {it.message ? (
                      <div className="truncate text-xs text-muted-foreground">{it.message}</div>
                    ) : null}
                  </div>
                  <span className={`shrink-0 rounded px-2 py-0.5 text-xs ${STATUS_CLASS[it.status]}`}>
                    {STATUS_LABEL[it.status]}
                  </span>
                  {!running ? (
                    <button
                      type="button"
                      onClick={() => removeAt(idx)}
                      className="text-muted-foreground hover:text-foreground"
                      title="Remover"
                    >
                      <X className="h-4 w-4" />
                    </button>
                  ) : null}
                </div>
              ))}
            </div>
          ) : (
            <div className="rounded-md border border-dashed p-6 text-center text-sm text-muted-foreground">
              Nenhum arquivo selecionado.
            </div>
          )}

          {finished ? (
            <div className="flex flex-wrap gap-2 text-xs">
              <SummaryBadge tone="emerald">{counts.done || 0} criados</SummaryBadge>
              <SummaryBadge tone="slate">{counts.duplicate || 0} já existiam</SummaryBadge>
              <SummaryBadge tone="amber">{counts.extraction_failed || 0} sem texto</SummaryBadge>
              <SummaryBadge tone="red">{counts.error || 0} com erro</SummaryBadge>
            </div>
          ) : null}
        </div>

        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={() => handleClose(false)}
            disabled={running}
          >
            {finished ? "Fechar" : "Cancelar"}
          </Button>
          <Button type="button" onClick={start} disabled={items.length === 0 || running}>
            {running ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Enviando…
              </>
            ) : (
              `Enviar ${items.length || ""}`.trim()
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function SummaryBadge({
  tone,
  children,
}: {
  tone: "emerald" | "slate" | "amber" | "red";
  children: ReactNode;
}) {
  const map = {
    emerald: "bg-emerald-100 text-emerald-800",
    slate: "bg-slate-100 text-slate-700",
    amber: "bg-amber-100 text-amber-800",
    red: "bg-red-100 text-red-800",
  };
  return <span className={`rounded px-2 py-0.5 ${map[tone]}`}>{children}</span>;
}

export default UploadProcessoLoteDialog;
