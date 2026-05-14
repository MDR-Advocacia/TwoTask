// frontend/src/components/classificador/UploadPdfDialog.tsx
//
// Dialog pra subir 1 ou N PDFs pra um lote do Classificador.
// Processa em serie pra evitar sobrecarga do extractor mecanico.
// Mostra progresso item-a-item + lista de erros.

import { useCallback, useState } from "react";
import { Button } from "@/components/ui/button";
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
import { Loader2, FilePlus2, CheckCircle2, XCircle, FileWarning, UploadCloud, FileText, X } from "lucide-react";
import { useToast } from "@/components/ui/use-toast";
import { uploadClassificadorProcessoPdf } from "@/services/api";


// Limite por arquivo (deve casar com backend/nginx).
const MAX_BYTES_PER_FILE = 200 * 1024 * 1024;


interface UploadPdfDialogProps {
  loteId: number;
  loteNome: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onUploaded: () => void;
}

interface UploadResult {
  filename: string;
  status: "pending" | "uploading" | "ok" | "error";
  message?: string;
  processoId?: number;
  extractor?: string | null;
  confidence?: string | null;
}

export default function UploadPdfDialog({
  loteId,
  loteNome,
  open,
  onOpenChange,
  onUploaded,
}: UploadPdfDialogProps) {
  const { toast } = useToast();
  const [files, setFiles] = useState<File[]>([]);
  const [produto, setProduto] = useState("");
  const [observacao, setObservacao] = useState("");
  const [uploading, setUploading] = useState(false);
  const [results, setResults] = useState<UploadResult[]>([]);
  const [dragActive, setDragActive] = useState(false);

  const totalSize = files.reduce((s, f) => s + f.size, 0);
  const oversized = files.filter(f => f.size > MAX_BYTES_PER_FILE);

  const addFiles = useCallback((selected: FileList | File[] | null) => {
    if (!selected) return;
    const incoming = Array.from(selected).filter(f =>
      f.type === "application/pdf" || f.name.toLowerCase().endsWith(".pdf"),
    );
    const total = Array.from(selected).length;
    if (incoming.length !== total) {
      toast({
        title: `${total - incoming.length} arquivo${total - incoming.length > 1 ? "s" : ""} ignorado${total - incoming.length > 1 ? "s" : ""}`,
        description: "Apenas PDFs sao aceitos.",
        variant: "destructive",
      });
    }
    setFiles(prev => {
      const seen = new Set(prev.map(f => `${f.name}_${f.size}`));
      const merged = [...prev];
      for (const f of incoming) {
        const key = `${f.name}_${f.size}`;
        if (!seen.has(key)) {
          merged.push(f);
          seen.add(key);
        }
      }
      setResults(merged.map(f => ({ filename: f.name, status: "pending" })));
      return merged;
    });
  }, [toast]);

  const removeFile = (idx: number) => {
    setFiles(prev => {
      const next = prev.filter((_, i) => i !== idx);
      setResults(next.map(f => ({ filename: f.name, status: "pending" })));
      return next;
    });
  };

  const clearFiles = () => {
    setFiles([]);
    setResults([]);
  };

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragActive(false);
    if (uploading) return;
    addFiles(e.dataTransfer.files);
  };

  const handleDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    if (uploading) return;
    setDragActive(true);
  };

  const handleDragLeave = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragActive(false);
  };

  const handleUpload = async () => {
    if (files.length === 0 || uploading) return;
    setUploading(true);

    let okCount = 0;
    let errCount = 0;

    for (let i = 0; i < files.length; i++) {
      const file = files[i];
      setResults(prev => prev.map((r, idx) => idx === i ? { ...r, status: "uploading" } : r));

      try {
        const result = await uploadClassificadorProcessoPdf(loteId, file, {
          produto: produto.trim() || undefined,
          observacao: observacao.trim() || undefined,
        });
        const p = result.processo;
        const isWarning = p.pdf_extraction_failed || p.extraction_confidence === "low";
        setResults(prev => prev.map((r, idx) => idx === i ? {
          ...r,
          status: isWarning ? "error" : "ok",
          message: p.pdf_extraction_failed
            ? (p.error_message || "Extracao falhou")
            : (p.extraction_confidence === "low"
              ? "Extracao parcial — confidence low"
              : "OK"),
          processoId: p.id,
          extractor: p.extractor_used,
          confidence: p.extraction_confidence,
        } : r));
        if (isWarning) errCount++;
        else okCount++;
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        setResults(prev => prev.map((r, idx) => idx === i ? {
          ...r,
          status: "error",
          message: msg,
        } : r));
        errCount++;
      }
    }

    setUploading(false);
    toast({
      title: "Upload concluido",
      description: `${okCount} OK · ${errCount} com aviso/erro de ${files.length} arquivos.`,
      variant: errCount > 0 ? "destructive" : "default",
    });
    onUploaded();
  };

  const handleClose = () => {
    if (uploading) return; // bloqueia fechar durante upload
    setFiles([]);
    setResults([]);
    setProduto("");
    setObservacao("");
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={(v) => !uploading && onOpenChange(v)}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Subir PDFs — {loteNome}</DialogTitle>
          <DialogDescription>
            Selecione 1 ou mais PDFs de processo. Sao processados em serie
            pelo extractor mecanico (PJe/eproc/eSAJ/PROJUDI/TJSP). PDFs
            sem texto extraivel viram status ERRO_CAPTURA.
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-3 py-2">
          <div className="grid gap-1">
            <Label htmlFor="pdf-files">Arquivos PDF *</Label>

            {/* Area de drag-and-drop grande */}
            <div
              onDrop={handleDrop}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onClick={() => !uploading && document.getElementById("pdf-files")?.click()}
              className={`
                relative rounded-lg border-2 border-dashed p-6 text-center cursor-pointer
                transition-colors min-h-[140px] flex flex-col items-center justify-center gap-2
                ${dragActive
                  ? "border-primary bg-primary/5"
                  : files.length > 0
                    ? "border-muted-foreground/30 bg-muted/30"
                    : "border-muted-foreground/40 hover:border-primary hover:bg-muted/30"
                }
                ${uploading ? "opacity-50 cursor-not-allowed" : ""}
              `}
            >
              <UploadCloud className={`h-8 w-8 ${dragActive ? "text-primary" : "text-muted-foreground"}`} />
              <div className="text-sm font-medium">
                {dragActive
                  ? "Solte os PDFs aqui"
                  : files.length === 0
                    ? "Arraste PDFs aqui ou clique pra selecionar"
                    : `${files.length} PDF${files.length > 1 ? "s" : ""} — arraste mais ou clique pra adicionar`}
              </div>
              <div className="text-[11px] text-muted-foreground">
                Aceita múltiplos PDFs · {(MAX_BYTES_PER_FILE / 1024 / 1024).toFixed(0)}MB máx por arquivo · enviados 1 por vez
              </div>
              <Input
                id="pdf-files"
                type="file"
                accept=".pdf,application/pdf"
                multiple
                onChange={e => addFiles(e.target.files)}
                disabled={uploading}
                className="hidden"
              />
            </div>

            {/* Lista de arquivos selecionados */}
            {files.length > 0 && (
              <div className="mt-2 rounded-md border bg-muted/20 max-h-48 overflow-y-auto">
                <div className="sticky top-0 bg-muted/60 px-3 py-1.5 border-b flex items-center justify-between text-xs">
                  <span className="font-medium">
                    {files.length} arquivo{files.length > 1 ? "s" : ""} · {(totalSize / 1024 / 1024).toFixed(2)} MB total
                  </span>
                  <button
                    type="button"
                    onClick={(e) => { e.stopPropagation(); clearFiles(); }}
                    className="text-muted-foreground hover:text-foreground"
                    disabled={uploading}
                  >
                    Limpar tudo
                  </button>
                </div>
                <ul className="divide-y text-xs">
                  {files.map((f, i) => {
                    const tooBig = f.size > MAX_BYTES_PER_FILE;
                    return (
                      <li key={i} className={`flex items-center gap-2 px-3 py-1.5 ${tooBig ? "bg-red-50" : ""}`}>
                        <FileText className={`h-3.5 w-3.5 shrink-0 ${tooBig ? "text-red-600" : "text-muted-foreground"}`} />
                        <div className="flex-1 min-w-0">
                          <div className="truncate font-medium">{f.name}</div>
                          <div className={`text-[10px] ${tooBig ? "text-red-700 font-medium" : "text-muted-foreground"}`}>
                            {(f.size / 1024 / 1024).toFixed(2)} MB
                            {tooBig && ` · excede ${(MAX_BYTES_PER_FILE / 1024 / 1024).toFixed(0)}MB`}
                          </div>
                        </div>
                        <button
                          type="button"
                          onClick={(e) => { e.stopPropagation(); removeFile(i); }}
                          className="text-muted-foreground hover:text-red-600 shrink-0"
                          disabled={uploading}
                          title="Remover"
                        >
                          <X className="h-3.5 w-3.5" />
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </div>
            )}

            {oversized.length > 0 && (
              <div className="rounded-md border border-red-300 bg-red-50 p-2 text-[11px] text-red-900 mt-1">
                <strong>{oversized.length} arquivo{oversized.length > 1 ? "s" : ""}</strong> excede{oversized.length === 1 ? "" : "m"} o
                limite de {(MAX_BYTES_PER_FILE / 1024 / 1024).toFixed(0)}MB — remova antes de enviar.
              </div>
            )}
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="grid gap-1">
              <Label htmlFor="pdf-produto">Produto (opcional)</Label>
              <Input
                id="pdf-produto"
                value={produto}
                onChange={e => setProduto(e.target.value)}
                placeholder="Cartao Credito, Cheque Especial..."
                disabled={uploading}
              />
            </div>
            <div className="grid gap-1">
              <Label htmlFor="pdf-obs">Observacao (opcional)</Label>
              <Input
                id="pdf-obs"
                value={observacao}
                onChange={e => setObservacao(e.target.value)}
                placeholder="Aplicada a todos os PDFs"
                disabled={uploading}
              />
            </div>
          </div>

          {results.length > 0 && (
            <div className="rounded-md border max-h-64 overflow-auto">
              <ul className="divide-y text-xs">
                {results.map((r, i) => (
                  <li key={i} className="flex items-start gap-2 p-2">
                    {r.status === "pending" && (
                      <FilePlus2 className="h-4 w-4 text-muted-foreground shrink-0 mt-0.5" />
                    )}
                    {r.status === "uploading" && (
                      <Loader2 className="h-4 w-4 animate-spin text-primary shrink-0 mt-0.5" />
                    )}
                    {r.status === "ok" && (
                      <CheckCircle2 className="h-4 w-4 text-green-600 shrink-0 mt-0.5" />
                    )}
                    {r.status === "error" && (
                      <XCircle className="h-4 w-4 text-red-600 shrink-0 mt-0.5" />
                    )}
                    <div className="flex-1 min-w-0">
                      <div className="truncate font-medium">{r.filename}</div>
                      {r.message && (
                        <div className="text-muted-foreground">{r.message}</div>
                      )}
                      {r.processoId && (
                        <div className="text-muted-foreground">
                          processo #{r.processoId}
                          {r.extractor && ` · extractor=${r.extractor}`}
                          {r.confidence && ` · confidence=${r.confidence}`}
                        </div>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {uploading && (
            <div className="text-xs text-muted-foreground flex items-center gap-2">
              <FileWarning className="h-3.5 w-3.5" />
              Nao feche a aba — uploads em serie.
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={handleClose} disabled={uploading}>
            {results.some(r => r.status === "ok" || r.status === "error") ? "Fechar" : "Cancelar"}
          </Button>
          <Button
            onClick={handleUpload}
            disabled={files.length === 0 || oversized.length > 0 || uploading}
          >
            {uploading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            Subir {files.length > 0 ? `(${files.length})` : ""}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
