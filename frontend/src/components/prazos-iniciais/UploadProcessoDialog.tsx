import { useCallback, useRef, useState } from "react";
import { FileUp, FilePlus, AlertCircle, CheckCircle2, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useToast } from "@/components/ui/use-toast";
import { uploadPrazoInicialPdf } from "@/services/api";
import type { PrazoInicialUploadResponse } from "@/types/api";

const MAX_PROCESSO_MB = 100;
const MAX_HABILITACAO_MB = 20;

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess?: (response: PrazoInicialUploadResponse) => void;
}

interface FileSlotProps {
  label: string;
  hint: string;
  file: File | null;
  onPick: (file: File | null) => void;
  required: boolean;
  maxMB: number;
  disabled: boolean;
  testId: string;
}

function FileSlot({ label, hint, file, onPick, required, maxMB, disabled, testId }: FileSlotProps) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const sizeMB = file ? file.size / 1024 / 1024 : 0;
  const overLimit = sizeMB > maxMB;

  return (
    <div className="space-y-2">
      <div className="flex items-baseline justify-between gap-2">
        <label className="text-sm font-medium">
          {label}
          {required ? <span className="text-red-600"> *</span> : (
            <span className="ml-1 text-xs font-normal text-muted-foreground">(opcional)</span>
          )}
        </label>
        <span className="text-xs text-muted-foreground">Máx. {maxMB} MB</span>
      </div>
      <div
        className={`flex items-center gap-3 rounded-md border border-dashed p-3 transition-colors ${
          overLimit
            ? "border-red-300 bg-red-50"
            : file
              ? "border-emerald-300 bg-emerald-50"
              : "border-muted bg-muted/30"
        }`}
      >
        {file ? (
          <CheckCircle2 className={`h-5 w-5 ${overLimit ? "text-red-500" : "text-emerald-600"}`} />
        ) : (
          <FilePlus className="h-5 w-5 text-muted-foreground" />
        )}
        <div className="min-w-0 flex-1">
          {file ? (
            <>
              <div className="truncate text-sm font-medium" title={file.name}>
                {file.name}
              </div>
              <div className={`text-xs ${overLimit ? "text-red-700" : "text-muted-foreground"}`}>
                {sizeMB.toFixed(1)} MB{overLimit ? " — excede o limite" : ""}
              </div>
            </>
          ) : (
            <div className="text-sm text-muted-foreground">{hint}</div>
          )}
        </div>
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf"
          className="hidden"
          data-testid={testId}
          onChange={(e) => {
            const f = e.target.files?.[0] ?? null;
            onPick(f);
            // permite selecionar o mesmo arquivo de novo no futuro
            e.target.value = "";
          }}
          disabled={disabled}
        />
        <div className="flex shrink-0 gap-2">
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => inputRef.current?.click()}
            disabled={disabled}
          >
            {file ? "Trocar" : "Escolher"}
          </Button>
          {file ? (
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() => onPick(null)}
              disabled={disabled}
            >
              Remover
            </Button>
          ) : null}
        </div>
      </div>
    </div>
  );
}


/**
 * Dialog de upload manual de processo (USER_UPLOAD).
 * - processo_pdf (obrigatório): PDF do processo na íntegra. O backend
 *   tenta extração mecânica via pdfplumber + extractor PJe TJBA. Em
 *   caso de PDF escaneado, cria intake com flag pdf_extraction_failed
 *   e o operador classifica manualmente no HITL.
 * - habilitacao_pdf (opcional): PDF de habilitação MDR — preservado pra
 *   GED L1 + AJUS. Pode ser anexado depois também (mas hoje a única
 *   rota de anexo é o upload).
 */
export function UploadProcessoDialog({ open, onOpenChange, onSuccess }: Props) {
  const { toast } = useToast();

  const [processoFile, setProcessoFile] = useState<File | null>(null);
  const [habilitacaoFile, setHabilitacaoFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const reset = useCallback(() => {
    setProcessoFile(null);
    setHabilitacaoFile(null);
    setErrorMessage(null);
    setSubmitting(false);
  }, []);

  const handleClose = useCallback(
    (next: boolean) => {
      if (!next) reset();
      onOpenChange(next);
    },
    [onOpenChange, reset],
  );

  const processoOver = processoFile ? processoFile.size / 1024 / 1024 > MAX_PROCESSO_MB : false;
  const habilitacaoOver = habilitacaoFile
    ? habilitacaoFile.size / 1024 / 1024 > MAX_HABILITACAO_MB
    : false;

  const canSubmit = !!processoFile && !processoOver && !habilitacaoOver && !submitting;

  const handleSubmit = useCallback(async () => {
    if (!processoFile) return;
    setSubmitting(true);
    setErrorMessage(null);
    try {
      const result = await uploadPrazoInicialPdf(processoFile, habilitacaoFile);

      if (result.already_existed) {
        toast({
          title: "PDF já cadastrado",
          description:
            result.user_message ||
            `Este processo já estava na fila como intake #${result.intake_id}.`,
        });
      } else if (result.pdf_extraction_failed) {
        toast({
          title: "Processo cadastrado — sem texto extraível",
          description:
            result.user_message ||
            "O PDF parece ser escaneado. Você pode classificar manualmente na tela de tratamento.",
        });
      } else {
        toast({
          title: "Processo cadastrado",
          description:
            result.user_message ||
            "Classificação em andamento. Aparecerá na listagem em segundos.",
        });
      }

      onSuccess?.(result);
      handleClose(false);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Falha ao subir o PDF.";
      setErrorMessage(message);
    } finally {
      setSubmitting(false);
    }
  }, [processoFile, habilitacaoFile, toast, onSuccess, handleClose]);

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FileUp className="h-5 w-5" />
            Subir processo (upload manual)
          </DialogTitle>
          <DialogDescription>
            O sistema tenta ler a capa e a íntegra automaticamente. Em caso de
            PDF escaneado, o processo é cadastrado mesmo assim e você
            classifica manualmente no tratamento.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          <FileSlot
            label="PDF do processo"
            hint="Arquivo do processo na íntegra (capa + integra)."
            file={processoFile}
            onPick={setProcessoFile}
            required
            maxMB={MAX_PROCESSO_MB}
            disabled={submitting}
            testId="upload-processo-input"
          />

          <FileSlot
            label="PDF da habilitação"
            hint="Habilitação MDR (procuração + carta de preposição). Vai pro GED + AJUS."
            file={habilitacaoFile}
            onPick={setHabilitacaoFile}
            required={false}
            maxMB={MAX_HABILITACAO_MB}
            disabled={submitting}
            testId="upload-habilitacao-input"
          />

          {errorMessage ? (
            <div className="flex gap-2 rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-800">
              <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
              <div>{errorMessage}</div>
            </div>
          ) : null}
        </div>

        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={() => handleClose(false)}
            disabled={submitting}
          >
            Cancelar
          </Button>
          <Button type="button" onClick={handleSubmit} disabled={!canSubmit}>
            {submitting ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Enviando…
              </>
            ) : (
              "Enviar"
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default UploadProcessoDialog;
