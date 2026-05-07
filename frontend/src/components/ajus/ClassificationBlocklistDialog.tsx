import { useEffect, useRef, useState } from "react";
import {
  AlertCircle,
  Ban,
  CheckCircle2,
  FileSpreadsheet,
  Loader2,
  Upload,
} from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
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
import { useToast } from "@/hooks/use-toast";
import {
  fetchAjusClassificationBlocklistStats,
  uploadAjusClassificationBlocklist,
} from "@/services/api";
import type { AjusBlocklistStatsResponse } from "@/types/api";


interface Props {
  open: boolean;
  onOpenChange: (next: boolean) => void;
  /** Chamado depois de upload bem-sucedido pra o pai recarregar a lista. */
  onUploaded?: () => void;
}


function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString("pt-BR");
  } catch {
    return iso;
  }
}


export function ClassificationBlocklistDialog({
  open,
  onOpenChange,
  onUploaded,
}: Props) {
  const { toast } = useToast();
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [stats, setStats] = useState<AjusBlocklistStatsResponse | null>(null);
  const [statsLoading, setStatsLoading] = useState(false);

  // Carrega stats sempre que abre
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setStatsLoading(true);
    fetchAjusClassificationBlocklistStats()
      .then((s) => {
        if (!cancelled) setStats(s);
      })
      .catch((err) => {
        if (!cancelled) {
          toast({
            variant: "destructive",
            title: "Erro ao carregar stats",
            description: String(err),
          });
        }
      })
      .finally(() => {
        if (!cancelled) setStatsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, toast]);

  // Reset ao fechar
  useEffect(() => {
    if (!open) {
      setFile(null);
      if (fileRef.current) fileRef.current.value = "";
    }
  }, [open]);

  async function handleUpload() {
    if (!file) {
      toast({
        variant: "destructive",
        title: "Arquivo obrigatorio",
        description: "Selecione a planilha .xlsx exportada do Legal One.",
      });
      return;
    }
    setUploading(true);
    try {
      const result = await uploadAjusClassificationBlocklist(file);
      const parts: string[] = [];
      if (result.added > 0) parts.push(`${result.added} novo(s)`);
      if (result.updated > 0) parts.push(`${result.updated} atualizado(s)`);
      if (result.removed > 0) parts.push(`${result.removed} liberado(s)`);
      const summary = parts.length > 0 ? parts.join(" · ") : "sem mudancas";
      toast({
        title: "Blocklist atualizado",
        description: `${summary}. Total no blocklist: ${result.total_after}.`,
      });
      // Recarrega stats e notifica o pai
      const s = await fetchAjusClassificationBlocklistStats();
      setStats(s);
      onUploaded?.();
      // Fecha
      onOpenChange(false);
    } catch (err) {
      toast({
        variant: "destructive",
        title: "Falha no upload",
        description: String(err),
      });
    } finally {
      setUploading(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Ban className="h-4 w-4" />
            Bloqueio por classificacao pendente
          </DialogTitle>
          <DialogDescription>
            Suba a planilha de processos com classificacao pendente
            exportada do Legal One. CNJs que aparecerem no arquivo ficam
            bloqueados pra envio AJUS. CNJs que sumirem do arquivo (que
            estavam no blocklist anterior) sao liberados automaticamente.
          </DialogDescription>
        </DialogHeader>

        {/* Stats atuais */}
        <Alert>
          <FileSpreadsheet className="h-4 w-4" />
          <AlertTitle>Estado atual</AlertTitle>
          <AlertDescription>
            {statsLoading ? (
              <span className="flex items-center gap-2 text-sm">
                <Loader2 className="h-3 w-3 animate-spin" />
                carregando...
              </span>
            ) : stats ? (
              <div className="text-sm space-y-0.5">
                <div>
                  <strong>{stats.total_no_blocklist}</strong> CNJs no
                  blocklist atual
                </div>
                <div>
                  <strong>{stats.items_fila_bloqueados}</strong> item(ns)
                  da fila atualmente bloqueados (status pendente/erro com
                  CNJ no blocklist)
                </div>
                <div className="text-xs text-muted-foreground">
                  Ultimo upload: {formatDate(stats.ultimo_upload_at)}
                </div>
              </div>
            ) : (
              <span className="text-sm text-muted-foreground">
                Sem dados.
              </span>
            )}
          </AlertDescription>
        </Alert>

        {/* Comportamento */}
        <Alert variant="default">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Como funciona</AlertTitle>
          <AlertDescription className="text-sm">
            Cada upload <strong>SUBSTITUI</strong> o blocklist atual. CNJ
            que estiver na planilha que voce subir agora = bloqueado. CNJ
            que estava bloqueado mas nao aparece mais = liberado.
            Detectamos automaticamente a coluna "Numeros Processo" / "CNJ"
            / "Processo" pelo header (case-insensitive); fallback pega
            qualquer coluna onde a primeira celula valida bata o regex de
            CNJ.
          </AlertDescription>
        </Alert>

        {/* Input de arquivo */}
        <div className="space-y-2">
          <label className="text-sm font-medium">
            Planilha (.xlsx) <span className="text-red-500">*</span>
          </label>
          <Input
            ref={fileRef}
            type="file"
            accept=".xlsx,.xlsm,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            disabled={uploading}
          />
          {file && (
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <CheckCircle2 className="h-3 w-3 text-green-600" />
              {file.name} ({(file.size / 1024).toFixed(1)} KB)
            </div>
          )}
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={uploading}
          >
            Cancelar
          </Button>
          <Button onClick={handleUpload} disabled={!file || uploading}>
            {uploading ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Upload className="mr-2 h-4 w-4" />
            )}
            Enviar e substituir blocklist
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
