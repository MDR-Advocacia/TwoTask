import { useCallback, useMemo, useState } from "react";
import { Archive, Loader2, AlertCircle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
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
import { useToast } from "@/components/ui/use-toast";
import { bulkArchivePrazoInicialIntakes } from "@/services/api";

const STATUS_OPTIONS: { value: string; label: string }[] = [
  { value: "RECEBIDO", label: "Recebido" },
  { value: "PROCESSO_NAO_ENCONTRADO", label: "Processo não encontrado" },
  { value: "PRONTO_PARA_CLASSIFICAR", label: "Pronto pra classificar" },
  { value: "CLASSIFICADO", label: "Classificado" },
  { value: "AGUARDANDO_CONFIG_TEMPLATE", label: "Aguardando template" },
  { value: "EM_REVISAO", label: "Em revisão" },
  { value: "AGENDADO", label: "Agendado" },
  { value: "CONCLUIDO_SEM_PROVIDENCIA", label: "Concluído sem providência" },
  { value: "CONCLUIDO", label: "Concluído" },
  { value: "GED_ENVIADO", label: "GED enviado" },
  { value: "ERRO_CLASSIFICACAO", label: "Erro classificação" },
  { value: "ERRO_AGENDAMENTO", label: "Erro agendamento" },
  { value: "ERRO_GED", label: "Erro GED" },
  { value: "CANCELADO", label: "Cancelado" },
];

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess?: () => void;
}

/**
 * Arquivamento em lote por CRITÉRIO (soft-delete). Arquiva os intakes
 * recebidos antes de uma data e/ou em certos status. Saem da fila ativa
 * (status ARQUIVADO), dados preservados. Cap de 500 por chamada no backend.
 */
export function ArquivarAntigosDialog({ open, onOpenChange, onSuccess }: Props) {
  const { toast } = useToast();
  const [beforeDate, setBeforeDate] = useState("");
  const [statuses, setStatuses] = useState<Set<string>>(new Set());
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reset = useCallback(() => {
    setBeforeDate("");
    setStatuses(new Set());
    setError(null);
    setSubmitting(false);
  }, []);

  const handleClose = useCallback(
    (next: boolean) => {
      if (submitting) return;
      if (!next) reset();
      onOpenChange(next);
    },
    [onOpenChange, reset, submitting],
  );

  const toggleStatus = useCallback((v: string) => {
    setStatuses((prev) => {
      const n = new Set(prev);
      if (n.has(v)) n.delete(v);
      else n.add(v);
      return n;
    });
  }, []);

  const canSubmit = useMemo(
    () => (!!beforeDate || statuses.size > 0) && !submitting,
    [beforeDate, statuses, submitting],
  );

  const handleSubmit = useCallback(async () => {
    setSubmitting(true);
    setError(null);
    try {
      const r = await bulkArchivePrazoInicialIntakes({
        before_date: beforeDate || undefined,
        status_in: statuses.size > 0 ? Array.from(statuses) : undefined,
      });
      toast({
        title:
          r.archived_count > 0
            ? `${r.archived_count} arquivado(s)`
            : "Nada pra arquivar",
        description:
          r.archived_count > 0
            ? "Saíram da fila ativa. Você ainda os vê filtrando por status ARQUIVADO."
            : "Nenhum intake casou o critério (ou já estavam arquivados).",
      });
      onSuccess?.();
      handleClose(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Falha ao arquivar.");
    } finally {
      setSubmitting(false);
    }
  }, [beforeDate, statuses, toast, onSuccess, handleClose]);

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Archive className="h-5 w-5" />
            Arquivar entradas antigas
          </DialogTitle>
          <DialogDescription>
            Arquiva em lote (soft-delete) os intakes que casarem o critério — saem
            da fila ativa, mas os dados ficam preservados. Informe a data e/ou os
            status. Até 500 por vez.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          <div className="space-y-1">
            <Label htmlFor="arq-before">Recebidos antes de</Label>
            <Input
              id="arq-before"
              type="date"
              value={beforeDate}
              onChange={(e) => setBeforeDate(e.target.value)}
              disabled={submitting}
            />
          </div>

          <div className="space-y-2">
            <Label>Restringir a status (opcional)</Label>
            <div className="grid grid-cols-2 gap-1">
              {STATUS_OPTIONS.map((o) => (
                <label key={o.value} className="flex items-center gap-2 text-sm">
                  <Checkbox
                    checked={statuses.has(o.value)}
                    onCheckedChange={() => toggleStatus(o.value)}
                    disabled={submitting}
                  />
                  {o.label}
                </label>
              ))}
            </div>
          </div>

          {error ? (
            <div className="flex gap-2 rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-800">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
              <div>{error}</div>
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
          <Button
            type="button"
            variant="destructive"
            onClick={handleSubmit}
            disabled={!canSubmit}
          >
            {submitting ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Arquivando…
              </>
            ) : (
              "Arquivar"
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default ArquivarAntigosDialog;
