/**
 * TemplateInlineModal — modal contextual de template (criar / editar).
 *
 * Diferenca do modal antigo: cat/sub vem do CONTEXTO (linha clicada
 * na arvore), nao do operador escolhendo num dropdown gigante. So
 * pergunta o que e essencial pra a tarefa: nome, subtipo, responsavel,
 * prazo, descricao, notas, target_role/squad.
 *
 * Usado pelo OfficeTemplateTree quando o operador clica:
 *  - "+ adicionar template" → mode="create" com cat/sub pre-preenchidos
 *  - "editar" → mode="edit" com template carregado
 */
import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  SubtypePicker,
  type SubtypePickerTaskType,
} from "@/components/ui/SubtypePicker";
import UserSelector from "@/components/ui/UserSelector";
import { useToast } from "@/hooks/use-toast";
import { apiFetch } from "@/lib/api-client";

export interface TemplateInlineModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Pra criar: passa office + cat + sub. Pra editar: passa templateId. */
  mode: "create" | "edit";
  officeExternalId: number | null;  // null = template global
  category: string;
  subcategory: string | null;
  templateId?: number;
  /** Chamado depois de salvar com sucesso (pai recarrega arvore). */
  onSaved: () => void;
}

interface User {
  external_id: number;
  name: string;
  email?: string;
}

const PRIORITIES = [
  { value: "Low", label: "Baixa" },
  { value: "Normal", label: "Normal" },
  { value: "High", label: "Alta" },
];

const DUE_REFERENCE_OPTIONS = [
  { value: "publication", label: "Data da publicação" },
  { value: "today", label: "Data atual (quando criar a tarefa)" },
];

export function TemplateInlineModal({
  open,
  onOpenChange,
  mode,
  officeExternalId,
  category,
  subcategory,
  templateId,
  onSaved,
}: TemplateInlineModalProps) {
  const { toast } = useToast();

  const [name, setName] = useState("");
  const [subtypeId, setSubtypeId] = useState<number | null>(null);
  const [responsibleId, setResponsibleId] = useState<number | null>(null);
  const [priority, setPriority] = useState("Normal");
  const [dueDays, setDueDays] = useState(3);
  const [dueRef, setDueRef] = useState("publication");
  const [description, setDescription] = useState("");
  const [notes, setNotes] = useState("");

  const [taskTypes, setTaskTypes] = useState<SubtypePickerTaskType[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [loadingMeta, setLoadingMeta] = useState(false);
  const [loadingTemplate, setLoadingTemplate] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  // Reset form ao abrir
  useEffect(() => {
    if (!open) return;
    if (mode === "create") {
      setName(`${category}${subcategory ? ` / ${subcategory}` : ""}`);
      setSubtypeId(null);
      setResponsibleId(null);
      setPriority("Normal");
      setDueDays(3);
      setDueRef("publication");
      setDescription("");
      setNotes("");
    }
  }, [open, mode, category, subcategory]);

  // Carrega meta (subtipos + usuarios) ao abrir
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoadingMeta(true);
    Promise.all([
      apiFetch("/api/v1/task-templates/meta/task-types"),
      apiFetch("/api/v1/task-templates/meta/users"),
    ])
      .then(async ([rTypes, rUsers]) => {
        if (!rTypes.ok || !rUsers.ok) throw new Error("Falha carregando catálogos");
        const [types, us] = await Promise.all([rTypes.json(), rUsers.json()]);
        if (cancelled) return;
        setTaskTypes(types ?? []);
        setUsers(us ?? []);
      })
      .catch((err) => {
        if (cancelled) return;
        toast({
          title: "Erro carregando catálogos",
          description: String(err?.message ?? err),
          variant: "destructive",
        });
      })
      .finally(() => !cancelled && setLoadingMeta(false));
    return () => {
      cancelled = true;
    };
  }, [open, toast]);

  // Em modo edit: carrega o template
  useEffect(() => {
    if (!open || mode !== "edit" || !templateId) return;
    let cancelled = false;
    setLoadingTemplate(true);
    apiFetch(`/api/v1/task-templates/${templateId}`)
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const t = await res.json();
        if (cancelled) return;
        setName(t.name ?? "");
        setSubtypeId(t.task_subtype_external_id ?? null);
        setResponsibleId(t.responsible_user_external_id ?? null);
        setPriority(t.priority ?? "Normal");
        setDueDays(t.due_business_days ?? 3);
        setDueRef(t.due_date_reference ?? "publication");
        setDescription(t.description_template ?? "");
        setNotes(t.notes_template ?? "");
      })
      .catch((err) => {
        if (cancelled) return;
        toast({
          title: "Falha carregando template",
          description: String(err?.message ?? err),
          variant: "destructive",
        });
      })
      .finally(() => !cancelled && setLoadingTemplate(false));
    return () => {
      cancelled = true;
    };
  }, [open, mode, templateId, toast]);

  const handleSubmit = async () => {
    if (!subtypeId) {
      toast({ title: "Selecione o subtipo de tarefa" });
      return;
    }
    if (!name.trim()) {
      toast({ title: "Defina um nome para o template" });
      return;
    }
    setSubmitting(true);
    try {
      const payload: Record<string, unknown> = {
        name: name.trim(),
        category,
        subcategory: subcategory ?? null,
        office_external_id: officeExternalId,
        task_subtype_external_id: subtypeId,
        responsible_user_external_id: responsibleId,
        priority,
        due_business_days: dueDays,
        due_date_reference: dueRef,
        description_template: description || null,
        notes_template: notes || null,
        is_active: true,
        target_role: "principal",
      };

      const url =
        mode === "create"
          ? "/api/v1/task-templates/"
          : `/api/v1/task-templates/${templateId}`;
      const method = mode === "create" ? "POST" : "PUT";

      const res = await apiFetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(
          (typeof data?.detail === "string" && data.detail) ||
            "Falha ao salvar template.",
        );
      }
      toast({
        title: mode === "create" ? "Template criado" : "Template atualizado",
        description: `${category}${subcategory ? ` / ${subcategory}` : ""}`,
      });
      onSaved();
      onOpenChange(false);
    } catch (err: any) {
      toast({
        title: "Erro ao salvar",
        description: err?.message || String(err),
        variant: "destructive",
      });
    } finally {
      setSubmitting(false);
    }
  };

  const isLoading = loadingMeta || loadingTemplate;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {mode === "create" ? "Adicionar template" : "Editar template"}
          </DialogTitle>
          <DialogDescription>
            <span className="font-mono text-xs">
              {category}
              {subcategory ? ` / ${subcategory}` : ""}
            </span>
            {officeExternalId == null && (
              <span className="ml-2 text-amber-600 dark:text-amber-400">
                · Template global (todos os escritórios)
              </span>
            )}
          </DialogDescription>
        </DialogHeader>

        {isLoading ? (
          <div className="flex items-center gap-2 py-8 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            Carregando...
          </div>
        ) : (
          <div className="space-y-4 py-2">
            {/* Nome */}
            <div className="grid gap-1.5">
              <Label htmlFor="tmpl-name" className="text-xs font-medium">
                Nome do template *
              </Label>
              <Input
                id="tmpl-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Ex.: Verificar contestação"
              />
            </div>

            {/* Subtipo */}
            <SubtypePicker
              value={subtypeId}
              taskTypes={taskTypes}
              onChange={(id) => setSubtypeId(id)}
              required
            />

            {/* Responsável */}
            <div className="grid gap-1.5">
              <Label className="text-xs font-medium">
                Responsável <span className="text-muted-foreground">(opcional)</span>
              </Label>
              <UserSelector
                // UserSelector espera value como string (external_id em string)
                // — aqui convertemos number<->string nas bordas pra alinhar tipos.
                value={responsibleId !== null ? String(responsibleId) : null}
                users={users.map((u) => ({
                  id: u.external_id,
                  external_id: u.external_id,
                  name: u.name,
                  squads: [],
                }))}
                onChange={(strId) =>
                  setResponsibleId(strId !== null ? Number(strId) : null)
                }
                placeholder="Selecione o responsável (opcional)"
              />
              <p className="text-xs text-muted-foreground">
                Se vazio, usa o responsável principal da pasta no momento de criar a tarefa.
              </p>
            </div>

            {/* Prioridade + prazo */}
            <div className="grid grid-cols-3 gap-3">
              <div className="grid gap-1.5">
                <Label className="text-xs font-medium">Prioridade</Label>
                <Select value={priority} onValueChange={setPriority}>
                  <SelectTrigger className="h-9 text-sm">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {PRIORITIES.map((p) => (
                      <SelectItem
                        key={p.value}
                        value={p.value}
                        className="text-sm"
                      >
                        {p.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="tmpl-due-days" className="text-xs font-medium">
                  Prazo (dias úteis)
                </Label>
                <Input
                  id="tmpl-due-days"
                  type="number"
                  min={0}
                  max={365}
                  value={dueDays}
                  onChange={(e) =>
                    setDueDays(Math.max(0, Math.min(365, Number(e.target.value))))
                  }
                />
              </div>
              <div className="grid gap-1.5">
                <Label className="text-xs font-medium">A contar de</Label>
                <Select value={dueRef} onValueChange={setDueRef}>
                  <SelectTrigger className="h-9 text-sm">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {DUE_REFERENCE_OPTIONS.map((o) => (
                      <SelectItem
                        key={o.value}
                        value={o.value}
                        className="text-sm"
                      >
                        {o.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            {/* Descrição + notas */}
            <div className="grid gap-1.5">
              <Label htmlFor="tmpl-desc" className="text-xs font-medium">
                Descrição da tarefa{" "}
                <span className="text-muted-foreground">
                  (opcional, suporta {"{cnj}"} e {"{publication_date}"})
                </span>
              </Label>
              <Textarea
                id="tmpl-desc"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Ex.: Verificar prazo de contestação no CNJ {cnj}"
                rows={2}
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="tmpl-notes" className="text-xs font-medium">
                Notas internas{" "}
                <span className="text-muted-foreground">(opcional)</span>
              </Label>
              <Textarea
                id="tmpl-notes"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                rows={2}
              />
            </div>
          </div>
        )}

        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={submitting}
          >
            Cancelar
          </Button>
          <Button
            type="button"
            onClick={handleSubmit}
            disabled={submitting || isLoading}
          >
            {submitting ? "Salvando..." : mode === "create" ? "Criar template" : "Salvar"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default TemplateInlineModal;
