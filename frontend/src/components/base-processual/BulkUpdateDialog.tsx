/**
 * BulkUpdateDialog — Chunk 4.
 *
 * Trigger: botao "Atualizar em lote" no header da ProcessosTab. Recebe os
 * filtros atuais + total preview. Operador escolhe quais campos setar e
 * confirma. Backend valida confirm_count (race-safe) e aplica em transacao.
 *
 * Cap = 1000 processos por bulk. Acima disso o backend devolve 409 e o
 * operador precisa refinar filtros (UI mostra alerta amarelo).
 */

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { AlertTriangle, CheckCircle2, Loader2, Pencil } from "lucide-react";

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
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";

import {
  type BulkUpdateFilters,
  type BulkUpdateSet,
  bulkUpdateProcessos,
} from "@/lib/api-base-processual";

const BULK_MAX = 1000;

type Props = {
  open: boolean;
  filters: BulkUpdateFilters;
  previewTotal: number;
  onClose: () => void;
};

const SITUACOES = ["Ativo", "Suspenso", "Baixado", "Arquivado", "Encerrado"];
const POLOS = ["Ativo", "Passivo"];
const RISCOS = ["Remoto", "Possível", "Provável", "Praticamente certo"];

export function BulkUpdateDialog({ open, filters, previewTotal, onClose }: Props) {
  const queryClient = useQueryClient();
  const [set, setSet] = useState<BulkUpdateSet>({});
  const [motivo, setMotivo] = useState("");

  const mut = useMutation({
    mutationFn: bulkUpdateProcessos,
    onSuccess: (result) => {
      if (result.total_afetados === 0) {
        toast.info("Nenhum processo casava o filtro.", {
          description: "Bulk nao alterou nada.",
        });
        return;
      }
      if (result.eventos_criados === 0) {
        toast.info("Todos os processos já tinham esses valores.", {
          description: `${result.total_afetados} processo(s) batem o filtro mas nenhum precisou mudar.`,
        });
      } else {
        toast.success(
          `${result.eventos_criados} processo(s) atualizado(s) em lote`,
          {
            description: `Upload virtual #${result.upload_id} criado. Veja em Eventos.`,
            duration: 10_000,
          },
        );
      }
      queryClient.invalidateQueries({ queryKey: ["base-processual-processos"] });
      queryClient.invalidateQueries({ queryKey: ["base-processual-eventos"] });
      queryClient.invalidateQueries({ queryKey: ["base-processual-dashboard"] });
      handleClose();
    },
    onError: (err: Error) => {
      toast.error("Falha no bulk update", { description: err.message });
    },
  });

  const handleClose = () => {
    setSet({});
    setMotivo("");
    onClose();
  };

  const handleConfirm = () => {
    const cleanSet: BulkUpdateSet = {};
    for (const [k, v] of Object.entries(set)) {
      if (v !== undefined && v !== "" && v !== null) {
        (cleanSet as Record<string, string>)[k] = v as string;
      }
    }
    if (Object.keys(cleanSet).length === 0) {
      toast.error("Escolha ao menos 1 campo pra atualizar.");
      return;
    }
    mut.mutate({
      filter: filters,
      set: cleanSet,
      motivo: motivo.trim() || undefined,
      confirm_count: previewTotal,
    });
  };

  const tooMany = previewTotal > BULK_MAX;
  const noResults = previewTotal === 0;
  const fieldsSet = Object.entries(set).filter(
    ([, v]) => v !== undefined && v !== "" && v !== null,
  ).length;

  return (
    <Dialog open={open} onOpenChange={(o) => !o && !mut.isPending && handleClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Pencil className="h-4 w-4" /> Atualização em lote
          </DialogTitle>
          <DialogDescription>
            Aplica os campos abaixo em todos os processos que casam com o filtro
            atual da tabela. Gera 1 evento <code>ATUALIZADO_MANUAL</code> por
            processo (auditável em Eventos).
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="rounded-md border bg-muted/30 p-3 text-sm">
            <div className="text-muted-foreground mb-1">Filtro atual</div>
            <div className="font-mono text-xs">
              <FilterSummary filters={filters} />
            </div>
            <div className="mt-2 flex items-center gap-2">
              <span className="text-muted-foreground">Processos afetados:</span>
              <span className="font-semibold tabular-nums">
                {previewTotal.toLocaleString("pt-BR")}
              </span>
            </div>
          </div>

          {tooMany && (
            <Alert variant="destructive">
              <AlertTriangle className="h-4 w-4" />
              <AlertTitle>Acima do limite de {BULK_MAX}</AlertTitle>
              <AlertDescription>
                Refine o filtro pra reduzir a {BULK_MAX} processos no máximo.
                Bulk maior precisa ser feito em lotes.
              </AlertDescription>
            </Alert>
          )}

          {noResults && (
            <Alert>
              <AlertTriangle className="h-4 w-4" />
              <AlertTitle>Filtro vazio</AlertTitle>
              <AlertDescription>
                Nenhum processo bate o filtro atual. Ajuste antes de prosseguir.
              </AlertDescription>
            </Alert>
          )}

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <Label className="text-xs">Situação</Label>
              <Select
                value={set.situacao_processo ?? ""}
                onValueChange={(v) =>
                  setSet((s) => ({ ...s, situacao_processo: v || undefined }))
                }
              >
                <SelectTrigger className="h-9">
                  <SelectValue placeholder="(não mexer)" />
                </SelectTrigger>
                <SelectContent>
                  {SITUACOES.map((s) => (
                    <SelectItem key={s} value={s}>{s}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="text-xs">Polo</Label>
              <Select
                value={set.polo ?? ""}
                onValueChange={(v) => setSet((s) => ({ ...s, polo: v || undefined }))}
              >
                <SelectTrigger className="h-9">
                  <SelectValue placeholder="(não mexer)" />
                </SelectTrigger>
                <SelectContent>
                  {POLOS.map((p) => (
                    <SelectItem key={p} value={p}>{p}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="text-xs">Risco/Prob. perda</Label>
              <Select
                value={set.risco_prob_perda ?? ""}
                onValueChange={(v) =>
                  setSet((s) => ({ ...s, risco_prob_perda: v || undefined }))
                }
              >
                <SelectTrigger className="h-9">
                  <SelectValue placeholder="(não mexer)" />
                </SelectTrigger>
                <SelectContent>
                  {RISCOS.map((r) => (
                    <SelectItem key={r} value={r}>{r}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="text-xs">Matéria</Label>
              <Input
                value={set.materia ?? ""}
                onChange={(e) =>
                  setSet((s) => ({ ...s, materia: e.target.value || undefined }))
                }
                placeholder="(não mexer)"
              />
            </div>
            <div className="col-span-2">
              <Label className="text-xs">Usuário responsável</Label>
              <Input
                value={set.usuario_responsavel ?? ""}
                onChange={(e) =>
                  setSet((s) => ({
                    ...s,
                    usuario_responsavel: e.target.value || undefined,
                  }))
                }
                placeholder="(não mexer)"
              />
            </div>
            <div className="col-span-2">
              <Label className="text-xs">Motivo (audit)</Label>
              <Textarea
                value={motivo}
                onChange={(e) => setMotivo(e.target.value)}
                placeholder="Ex.: realocacao de carteira por saida de advogado"
                rows={2}
              />
            </div>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={handleClose} disabled={mut.isPending}>
            Cancelar
          </Button>
          <Button
            onClick={handleConfirm}
            disabled={
              mut.isPending || tooMany || noResults || fieldsSet === 0
            }
          >
            {mut.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin mr-2" />
            ) : (
              <CheckCircle2 className="h-4 w-4 mr-2" />
            )}
            Aplicar em {previewTotal.toLocaleString("pt-BR")} processo(s)
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function FilterSummary({ filters }: { filters: BulkUpdateFilters }) {
  const entries = Object.entries(filters).filter(
    ([, v]) => v !== undefined && v !== null && v !== "" && !(Array.isArray(v) && v.length === 0),
  );
  if (entries.length === 0) {
    return <span className="text-amber-700 dark:text-amber-400">(sem filtro — TODA a base)</span>;
  }
  return (
    <span>
      {entries.map(([k, v], i) => (
        <span key={k}>
          {i > 0 && " · "}
          <span className="text-muted-foreground">{k}=</span>
          <span>{Array.isArray(v) ? `${v.length} cods` : String(v)}</span>
        </span>
      ))}
    </span>
  );
}
