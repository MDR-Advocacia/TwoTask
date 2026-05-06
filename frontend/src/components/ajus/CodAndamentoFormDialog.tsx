import { useEffect, useState } from "react";
import { Info } from "lucide-react";

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
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/ui/use-toast";
import {
  AjusCodAndamento,
  AjusCodAndamentoCreatePayload,
} from "@/types/api";

interface FormState {
  codigo: string;
  label: string;
  descricao: string;
  situacao: "A" | "C";
  dias_agendamento_offset_uteis: string;
  dias_fatal_offset_uteis: string;
  informacao_template: string;
  is_default: boolean;
  is_devolucao: boolean;
  is_active: boolean;
}

const DEFAULT_FORM: FormState = {
  codigo: "",
  label: "",
  descricao: "",
  situacao: "A",
  dias_agendamento_offset_uteis: "3",
  dias_fatal_offset_uteis: "15",
  informacao_template: "Andamento — processo {cnj}.",
  is_default: false,
  is_devolucao: false,
  is_active: true,
};

function fromCodAndamento(t: AjusCodAndamento): FormState {
  return {
    codigo: t.codigo,
    label: t.label,
    descricao: t.descricao || "",
    situacao: t.situacao,
    dias_agendamento_offset_uteis: String(t.dias_agendamento_offset_uteis),
    dias_fatal_offset_uteis: String(t.dias_fatal_offset_uteis),
    informacao_template: t.informacao_template,
    is_default: t.is_default,
    is_devolucao: t.is_devolucao ?? false,
    is_active: t.is_active,
  };
}

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** null = criação; objeto = edição */
  cod: AjusCodAndamento | null;
  onCreate: (payload: AjusCodAndamentoCreatePayload) => Promise<void>;
  onUpdate: (id: number, payload: AjusCodAndamentoCreatePayload) => Promise<void>;
}

export function CodAndamentoFormDialog({
  open,
  onOpenChange,
  cod,
  onCreate,
  onUpdate,
}: Props) {
  const { toast } = useToast();
  const [form, setForm] = useState<FormState>(() =>
    cod ? fromCodAndamento(cod) : DEFAULT_FORM,
  );
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    setForm(cod ? fromCodAndamento(cod) : DEFAULT_FORM);
  }, [cod]);

  const isEdit = cod !== null;

  const validate = (): string | null => {
    if (!form.codigo.trim()) return "Informe o código (recebido da equipe AJUS).";
    if (!form.label.trim()) return "Informe o rótulo legível do código.";
    const ag = Number(form.dias_agendamento_offset_uteis);
    const ft = Number(form.dias_fatal_offset_uteis);
    if (!Number.isFinite(ag) || !Number.isInteger(ag)) {
      return "Offset de agendamento precisa ser inteiro.";
    }
    if (!Number.isFinite(ft) || !Number.isInteger(ft)) {
      return "Offset fatal precisa ser inteiro.";
    }
    if (!form.informacao_template.trim()) {
      return "Informe o template de texto da informação.";
    }
    return null;
  };

  const handleSubmit = async () => {
    const err = validate();
    if (err) {
      toast({ title: "Campo inválido", description: err, variant: "destructive" });
      return;
    }
    const payload: AjusCodAndamentoCreatePayload = {
      codigo: form.codigo.trim(),
      label: form.label.trim(),
      descricao: form.descricao.trim() || null,
      situacao: form.situacao,
      dias_agendamento_offset_uteis: Number(form.dias_agendamento_offset_uteis),
      dias_fatal_offset_uteis: Number(form.dias_fatal_offset_uteis),
      informacao_template: form.informacao_template,
      is_default: form.is_default,
      is_devolucao: form.is_devolucao,
      is_active: form.is_active,
    };
    setSubmitting(true);
    try {
      if (isEdit && cod) {
        await onUpdate(cod.id, payload);
      } else {
        await onCreate(payload);
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      toast({
        title: "Erro ao salvar código",
        description: msg,
        variant: "destructive",
      });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="!max-w-[min(95vw,64rem)] max-h-[90vh] w-[95vw] overflow-hidden flex flex-col p-5 sm:p-6">
        <DialogHeader>
          <DialogTitle>
            {isEdit ? `Editar código: ${cod?.label}` : "Novo código de andamento"}
          </DialogTitle>
          <DialogDescription>
            Cada código define um TEMPLATE: o que vai pro payload da AJUS quando
            esse código for usado pra enfileirar um andamento. O código que
            tiver <strong>"Default"</strong> marcado será usado automaticamente
            pra cada intake recebido — só pode haver um default.
          </DialogDescription>
        </DialogHeader>

        <ScrollArea className="flex-1 -mr-4 pr-4">
          <div className="space-y-4 pb-2">
            {/* Linha: codigo + label */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div className="space-y-1 min-w-0">
                <Label>Código (AJUS) *</Label>
                <Input
                  value={form.codigo}
                  onChange={(e) => setForm({ ...form, codigo: e.target.value })}
                  placeholder="Ex: 1234"
                />
                <p className="text-xs text-muted-foreground">
                  Valor recebido da equipe AJUS — vai literal no payload.
                </p>
              </div>
              <div className="space-y-1 min-w-0">
                <Label>Rótulo (uso interno) *</Label>
                <Input
                  value={form.label}
                  onChange={(e) => setForm({ ...form, label: e.target.value })}
                  placeholder="Ex: Recebimento de habilitação"
                />
              </div>
            </div>

            <div className="space-y-1 min-w-0">
              <Label>Descrição</Label>
              <Textarea
                rows={2}
                value={form.descricao}
                onChange={(e) => setForm({ ...form, descricao: e.target.value })}
                placeholder="Notas internas — quando usar este código, observações."
              />
            </div>

            {/* Linha: situacao + offsets */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <div className="space-y-1 min-w-0">
                <Label>Situação *</Label>
                <Select
                  value={form.situacao}
                  onValueChange={(v) =>
                    setForm({ ...form, situacao: v as "A" | "C" })
                  }
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="A">A — Em aberto</SelectItem>
                    <SelectItem value="C">C — Concluído</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1 min-w-0">
                <Label>Offset agendamento (dias úteis)</Label>
                <Input
                  type="number"
                  min={-365}
                  max={365}
                  step={1}
                  value={form.dias_agendamento_offset_uteis}
                  onChange={(e) =>
                    setForm({
                      ...form,
                      dias_agendamento_offset_uteis: e.target.value,
                    })
                  }
                />
              </div>
              <div className="space-y-1 min-w-0">
                <Label>Offset fatal (dias úteis)</Label>
                <Input
                  type="number"
                  min={-365}
                  max={365}
                  step={1}
                  value={form.dias_fatal_offset_uteis}
                  onChange={(e) =>
                    setForm({ ...form, dias_fatal_offset_uteis: e.target.value })
                  }
                />
              </div>
            </div>
            <p className="text-xs text-muted-foreground">
              <strong>Como funciona:</strong> data de evento = dia em que o intake
              é recebido. Agendamento = +N dias úteis após o evento. Fatal = +M
              dias úteis. Calculado automaticamente quando o item é enfileirado.
            </p>

            <div className="space-y-1 min-w-0">
              <Label>Template da informação *</Label>
              <Textarea
                rows={3}
                value={form.informacao_template}
                onChange={(e) =>
                  setForm({ ...form, informacao_template: e.target.value })
                }
                placeholder="Ex: Recebimento de habilitação no processo {cnj}."
              />
              <p className="text-xs text-muted-foreground inline-flex items-start gap-1">
                <Info className="h-3 w-3 mt-0.5 shrink-0" />
                <span>
                  Placeholders: <code>{"{cnj}"}</code>,{" "}
                  <code>{"{data_recebimento}"}</code>.
                </span>
              </p>
            </div>

            <div className="flex flex-wrap gap-4">
              <div className="flex items-center gap-2">
                <Checkbox
                  id="cod-default"
                  checked={form.is_default}
                  onCheckedChange={(v) =>
                    setForm({ ...form, is_default: Boolean(v) })
                  }
                />
                <Label htmlFor="cod-default" className="cursor-pointer">
                  Default (usado automaticamente em intakes novos)
                </Label>
              </div>
              <div className="flex items-center gap-2">
                <Checkbox
                  id="cod-devolucao"
                  checked={form.is_devolucao}
                  onCheckedChange={(v) =>
                    setForm({ ...form, is_devolucao: Boolean(v) })
                  }
                />
                <Label htmlFor="cod-devolucao" className="cursor-pointer">
                  Devolução automática (usado pelo /intake/devolucao)
                </Label>
              </div>
              <div className="flex items-center gap-2">
                <Checkbox
                  id="cod-active"
                  checked={form.is_active}
                  onCheckedChange={(v) =>
                    setForm({ ...form, is_active: Boolean(v) })
                  }
                />
                <Label htmlFor="cod-active" className="cursor-pointer">
                  Ativo
                </Label>
              </div>
            </div>
            <p className="text-xs text-muted-foreground">
              <strong>Default</strong> e <strong>Devolução automática</strong>{" "}
              são exclusivos: cada flag pode estar marcada em apenas{" "}
              <em>um</em> código ativo por vez (a tela impede dois marcados
              simultaneamente — se você marcar essa flag em outro código, o
              anterior é automaticamente desmarcado).
            </p>
          </div>
        </ScrollArea>

        <DialogFooter className="gap-2 sm:gap-0">
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={submitting}
          >
            Cancelar
          </Button>
          <Button onClick={handleSubmit} disabled={submitting}>
            {submitting ? "Salvando..." : isEdit ? "Atualizar" : "Criar"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
