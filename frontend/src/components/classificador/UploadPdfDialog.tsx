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
import { Loader2, FilePlus2, CheckCircle2, XCircle, FileWarning } from "lucide-react";
import { useToast } from "@/components/ui/use-toast";
import { uploadClassificadorProcessoPdf } from "@/services/api";


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

  const handleFilesChange = useCallback((selected: FileList | null) => {
    if (!selected) return;
    const arr = Array.from(selected).filter(f => f.type === "application/pdf" || f.name.toLowerCase().endsWith(".pdf"));
    if (arr.length !== selected.length) {
      toast({
        title: "Alguns arquivos foram ignorados",
        description: "Apenas PDFs sao aceitos.",
        variant: "destructive",
      });
    }
    setFiles(arr);
    setResults(arr.map(f => ({ filename: f.name, status: "pending" })));
  }, [toast]);

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
            <Input
              id="pdf-files"
              type="file"
              accept=".pdf,application/pdf"
              multiple
              onChange={e => handleFilesChange(e.target.files)}
              disabled={uploading}
            />
            {files.length > 0 && (
              <p className="text-xs text-muted-foreground">
                {files.length} arquivo{files.length > 1 ? "s" : ""} selecionado{files.length > 1 ? "s" : ""} ·
                Tamanho total: {(files.reduce((s, f) => s + f.size, 0) / 1024 / 1024).toFixed(1)} MB
              </p>
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
            disabled={files.length === 0 || uploading}
          >
            {uploading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            Subir {files.length > 0 ? `(${files.length})` : ""}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
