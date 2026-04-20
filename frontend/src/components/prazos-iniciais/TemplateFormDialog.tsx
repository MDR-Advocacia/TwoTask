import { useEffect, useMemo, useState } from "react";
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
  PrazoInicialEnums,
  PrazoInicialTaskTemplate,
  PrazoInicialTaskTemplateCreatePayload,
} from "@/types/api";

// Chave sentinela para "Genérico (NULL)" em selects — o shadcn/ui Select não
// aceita value="" e o backend aceita null nos campos opcionais.
const NULL_VALUE = "__null__";

// Tipos dos `tipo_prazo` que aceitam `subtipo` (espelha _validate_tipo_subtipo
// do backend, onde os demais tipos forçam subtipo=null).
const TIPOS_COM_SUBTIPO = new Set(["AUDIENCIA", "JULGAMENTO"]);

interface OfficeOption {
  id: number;
  external_id: number;
  name: string;
  path?: string;
}

interface SubTypeOption {
  id: number;
  external_id: number;
  name: string;
}

interface TaskTypeOption {
  id: number;
  name: string;
  sub_types: SubTypeOption[];
}

interface UserOption {
  id: number;
  external_id: number;
  name: string;
}

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  enums: PrazoInicialEnums;
  offices: OfficeOption[];
  taskTypes: TaskTypeOption[];
  users: UserOption[];
  /** null => criação; objeto => edição */
  template: PrazoInicialTaskTemplate | null;
  onCreate: (payload: PrazoInicialTaskTemplateCreatePayload) => Promise<void>;
  onUpdate: (
    id: number,
    payload: Partial<PrazoInicialTaskTemplateCreatePayload>,
  ) => Promise<void>;
}

// Estado interno do form — reflete exatamente os campos do payload, mas com
// strings onde o backend espera number/null (convertido no submit).
interface FormState {
  name: string;
  tipo_prazo: string;
  subtipo: string;          // "" ou valor
  natureza_aplicavel: string; // "" (= null) ou valor
  office_external_id: string; // "" (= null/global) ou "<id>"
  task_type_id: string;       // só pra UI (cascata task_type → subtype)
  task_subtype_external_id: string; // "<external_id>"
  responsible_user_external_id: string; // "<external_id>"
  priority: string;
  due_business_days: string;
  due_date_reference: string;
  description_template: string;
  notes_template: string;
  is_active: boolean;
}

function templateToForm(
  t: PrazoInicialTaskTemplate | null,
  taskTypes: TaskTypeOption[],
): FormState {
  // Pra edição, precisamos descobrir qual task_type contém o subtype escolhido.
  let taskTypeId = "";
  if (t) {
    for (const tt of taskTypes) {
      if (
        tt.sub_types.some((st) => st.external_id === t.task_subtype_external_id)
      ) {
        taskTypeId = String(tt.id);
        break;
      }
    }
  }
  return {
    name: t?.name || "",
    tipo_prazo: t?.tipo_prazo || "",
    subtipo: t?.subtipo || "",
    natureza_aplicavel: t?.natureza_aplicavel || "",
    office_external_id: t?.office_external_id ? String(t.office_external_id) : "",
    task_type_id: taskTypeId,
    task_subtype_external_id: t
      ? String(t.task_subtype_external_id)
      : "",
    responsible_user_external_id: t
      ? String(t.responsible_user_external_id)
      : "",
    priority: t?.priority || "Normal",
    due_business_days: t ? String(t.due_business_days) : "3",
    due_date_reference: t?.due_date_reference || "data_base",
    description_template: t?.description_template || "",
    notes_template: t?.notes_template || "",
    is_active: t?.is_active ?? true,
  };
}

export function TemplateFormDialog({
  open,
  onOpenChange,
  enums,
  offices,
  taskTypes,
  users,
  template,
  onCreate,
  onUpdate,
}: Props) {
  const { toast } = useToast();
  const [form, setForm] = useState<FormState>(() =>
    templateToForm(template, taskTypes),
  );
  const [submitting, setSubmitting] = useState(false);

  // Quando o template muda (abertura do dialog), reseta o form.
  useEffect(() => {
    setForm(templateToForm(template, taskTypes));
  }, [template, taskTypes]);

  const isEdit = template !== null;
  const tipoExigeSubtipo = TIPOS_COM_SUBTIPO.has(form.tipo_prazo);

  // Subtipos permitidos pelo `tipo_prazo` atual (vem dos enums).
  const subtiposPermitidos = useMemo(() => {
    if (form.tipo_prazo === "AUDIENCIA") return enums.subtipos_audiencia;
    if (form.tipo_prazo === "JULGAMENTO") return enums.subtipos_julgamento;
    return [];
  }, [form.tipo_prazo, enums]);

  // Quando muda o tipo_prazo, limpa o subtipo se não for mais válido.
  useEffect(() => {
    if (!tipoExigeSubtipo && form.subtipo) {
      setForm((f) => ({ ...f, subtipo: "" }));
    } else if (
      tipoExigeSubtipo &&
      form.subtipo &&
      !subtiposPermitidos.includes(form.subtipo)
    ) {
      setForm((f) => ({ ...f, subtipo: "" }));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.tipo_prazo]);

  // Quando muda o task_type, limpa o subtype.
  useEffect(() => {
    // Se o subtype escolhido não pertence ao novo task_type, limpa.
    const parent = taskTypes.find((tt) => String(tt.id) === form.task_type_id);
    if (parent && form.task_subtype_external_id) {
      const stillValid = parent.sub_types.some(
        (st) => String(st.external_id) === form.task_subtype_external_id,
      );
      if (!stillValid) {
        setForm((f) => ({ ...f, task_subtype_external_id: "" }));
      }
    } else if (!parent && form.task_subtype_external_id) {
      setForm((f) => ({ ...f, task_subtype_external_id: "" }));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.task_type_id]);

  const filteredSubTypes = useMemo(() => {
    const parent = taskTypes.find((tt) => String(tt.id) === form.task_type_id);
    return parent ? parent.sub_types : [];
  }, [form.task_type_id, taskTypes]);

  const selectedUser = users.find(
    (u) => String(u.external_id) === form.responsible_user_external_id,
  );

  // ─── Validação client-side mínima ────────────────────────────────
  // O backend valida tudo de verdade; aqui a gente só bloqueia submit
  // quando falta campo obrigatório pra dar mensagem amigável.
  const validate = (): string | null => {
    if (!form.name.trim()) return "Informe o nome do template.";
    if (!form.tipo_prazo) return "Selecione o tipo de prazo.";
    if (!form.task_subtype_external_id) return "Selecione a task do Legal One.";
    if (!form.responsible_user_external_id) return "Selecione o responsável.";
    const days = Number(form.due_business_days);
    if (!Number.isFinite(days) || days < 0 || days > 365) {
      return "Prazo em dias úteis precisa estar entre 0 e 365.";
    }
    if (form.tipo_prazo === "CONTRARRAZOES") {
      // Guard-rail de negócio: CONTRARRAZOES só faz sentido com natureza
      // AGRAVO_INSTRUMENTO ou null. Avisa, não bloqueia.
      if (
        form.natureza_aplicavel &&
        form.natureza_aplicavel !== "AGRAVO_INSTRUMENTO"
      ) {
        return "CONTRARRAZOES só é emitido em AGRAVO_INSTRUMENTO. Use essa natureza ou deixe genérico.";
      }
    }
    return null;
  };

  // ─── Submit ───────────────────────────────────────────────────────

  const buildPayload = (): PrazoInicialTaskTemplateCreatePayload => {
    return {
      name: form.name.trim(),
      tipo_prazo: form.tipo_prazo,
      subtipo: tipoExigeSubtipo && form.subtipo ? form.subtipo : null,
      natureza_aplicavel: form.natureza_aplicavel || null,
      office_external_id: form.office_external_id
        ? Number(form.office_external_id)
        : null,
      task_subtype_external_id: Number(form.task_subtype_external_id),
      responsible_user_external_id: Number(form.responsible_user_external_id),
      priority: form.priority,
      due_business_days: Number(form.due_business_days),
      due_date_reference: form.due_date_reference,
      description_template: form.description_template.trim() || null,
      notes_template: form.notes_template.trim() || null,
      is_active: form.is_active,
    };
  };

  const handleSubmit = async () => {
    const err = validate();
    if (err) {
      toast({ title: "Campo inválido", description: err, variant: "destructive" });
      return;
    }
    const payload = buildPayload();
    setSubmitting(true);
    try {
      if (isEdit && template) {
        await onUpdate(template.id, payload);
      } else {
        await onCreate(payload);
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      // Detalhes do backend (409 / 422) já vêm no errorData.detail do api.ts
      toast({
        title: "Erro ao salvar template",
        description: msg,
        variant: "destructive",
      });
    } finally {
      setSubmitting(false);
    }
  };

  // ─── Render ───────────────────────────────────────────────────────

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl max-h-[90vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle>
            {isEdit ? `Editar template: ${template?.name}` : "Novo template"}
          </DialogTitle>
          <DialogDescription>
            Defina qual task do Legal One será sugerida quando o classifier
            encontrar este tipo de prazo, e pra qual escritório/natureza ela se
            aplica.
          </DialogDescription>
        </DialogHeader>

        <ScrollArea className="flex-1 pr-4 -mr-4">
          <div className="space-y-4">
            {/* Nome */}
            <div className="space-y-1">
              <Label htmlFor="tpl-name">Nome do template *</Label>
              <Input
                id="tpl-name"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="Ex: Abrir prazo CONTESTAR — global"
              />
              <p className="text-xs text-muted-foreground">
                Usado só pra identificar o template na listagem. Não aparece no Legal One.
              </p>
            </div>

            {/* Linha: tipo + subtipo */}
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label>Tipo de prazo *</Label>
                <Select
                  value={form.tipo_prazo}
                  onValueChange={(v) => setForm({ ...form, tipo_prazo: v })}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Selecione..." />
                  </SelectTrigger>
                  <SelectContent>
                    {enums.tipos_prazo.map((t) => (
                      <SelectItem key={t} value={t}>
                        {t}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-1">
                <Label>Subtipo {tipoExigeSubtipo ? "" : "(não aplicável)"}</Label>
                <Select
                  value={form.subtipo || NULL_VALUE}
                  onValueChange={(v) =>
                    setForm({ ...form, subtipo: v === NULL_VALUE ? "" : v })
                  }
                  disabled={!tipoExigeSubtipo}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="—" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={NULL_VALUE}>
                      Qualquer subtipo
                    </SelectItem>
                    {subtiposPermitidos.map((st) => (
                      <SelectItem key={st} value={st}>
                        {st}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {!tipoExigeSubtipo && form.tipo_prazo && (
                  <p className="text-xs text-muted-foreground">
                    Só <em>AUDIENCIA</em> e <em>JULGAMENTO</em> usam subtipo.
                  </p>
                )}
              </div>
            </div>

            {/* Linha: natureza + office */}
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label>Natureza aplicável</Label>
                <Select
                  value={form.natureza_aplicavel || NULL_VALUE}
                  onValueChange={(v) =>
                    setForm({
                      ...form,
                      natureza_aplicavel: v === NULL_VALUE ? "" : v,
                    })
                  }
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={NULL_VALUE}>
                      Genérica (qualquer natureza)
                    </SelectItem>
                    {enums.naturezas.map((n) => (
                      <SelectItem key={n} value={n}>
                        {n}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  Genérico + específico coexistem — ambos geram sugestões.
                </p>
              </div>

              <div className="space-y-1">
                <Label>Escritório</Label>
                <Select
                  value={form.office_external_id || NULL_VALUE}
                  onValueChange={(v) =>
                    setForm({
                      ...form,
                      office_external_id: v === NULL_VALUE ? "" : v,
                    })
                  }
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={NULL_VALUE}>
                      Global (todos os escritórios)
                    </SelectItem>
                    {offices.map((o) => (
                      <SelectItem key={o.external_id} value={String(o.external_id)}>
                        {o.path || o.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  Específico sobrepõe global na mesma combinação de tipo/natureza.
                </p>
              </div>
            </div>

            {/* Linha: task type → task subtype (cascade) */}
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label>Categoria da task *</Label>
                <Select
                  value={form.task_type_id}
                  onValueChange={(v) => setForm({ ...form, task_type_id: v })}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Selecione..." />
                  </SelectTrigger>
                  <SelectContent>
                    {taskTypes.map((tt) => (
                      <SelectItem key={tt.id} value={String(tt.id)}>
                        {tt.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1">
                <Label>Task do Legal One *</Label>
                <Select
                  value={form.task_subtype_external_id}
                  onValueChange={(v) =>
                    setForm({ ...form, task_subtype_external_id: v })
                  }
                  disabled={!form.task_type_id}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Selecione..." />
                  </SelectTrigger>
                  <SelectContent>
                    {filteredSubTypes.map((st) => (
                      <SelectItem key={st.external_id} value={String(st.external_id)}>
                        {st.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            {/* Responsável */}
            <div className="space-y-1">
              <Label>Responsável padrão *</Label>
              <Select
                value={form.responsible_user_external_id}
                onValueChange={(v) =>
                  setForm({ ...form, responsible_user_external_id: v })
                }
              >
                <SelectTrigger>
                  <SelectValue placeholder="Selecione..." />
                </SelectTrigger>
                <SelectContent>
                  {users.map((u) => (
                    <SelectItem key={u.external_id} value={String(u.external_id)}>
                      {u.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {selectedUser && (
                <p className="text-xs text-muted-foreground">
                  external_id: {selectedUser.external_id}
                </p>
              )}
            </div>

            {/* Linha: prioridade + due_days + due_ref */}
            <div className="grid grid-cols-3 gap-3">
              <div className="space-y-1">
                <Label>Prioridade</Label>
                <Select
                  value={form.priority}
                  onValueChange={(v) => setForm({ ...form, priority: v })}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {enums.priorities.map((p) => (
                      <SelectItem key={p} value={p}>
                        {p}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1">
                <Label>Dias úteis</Label>
                <Input
                  type="number"
                  min={0}
                  max={365}
                  value={form.due_business_days}
                  onChange={(e) =>
                    setForm({ ...form, due_business_days: e.target.value })
                  }
                />
              </div>
              <div className="space-y-1">
                <Label>Referência da data</Label>
                <Select
                  value={form.due_date_reference}
                  onValueChange={(v) => setForm({ ...form, due_date_reference: v })}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {enums.due_date_references.map((r) => (
                      <SelectItem key={r} value={r}>
                        {r}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            {/* Description template */}
            <div className="space-y-1">
              <Label>Descrição (template)</Label>
              <Textarea
                rows={3}
                value={form.description_template}
                onChange={(e) =>
                  setForm({ ...form, description_template: e.target.value })
                }
                placeholder="Ex: Abrir prazo {tipo_prazo} no processo {cnj}. Data base: {data_base}."
              />
              <p className="text-xs text-muted-foreground inline-flex items-start gap-1">
                <Info className="h-3 w-3 mt-0.5 shrink-0" />
                <span>
                  Placeholders: <code>{"{cnj}"}</code>, <code>{"{tipo_prazo}"}</code>
                  , <code>{"{subtipo}"}</code>, <code>{"{data_base}"}</code>,{" "}
                  <code>{"{data_final}"}</code>, <code>{"{prazo_dias}"}</code>,{" "}
                  <code>{"{prazo_tipo}"}</code>, <code>{"{objeto}"}</code>,{" "}
                  <code>{"{assunto}"}</code>, <code>{"{audiencia_data}"}</code>,{" "}
                  <code>{"{audiencia_hora}"}</code>,{" "}
                  <code>{"{audiencia_tipo}"}</code>,{" "}
                  <code>{"{audiencia_link}"}</code>,{" "}
                  <code>{"{audiencia_endereco}"}</code>,{" "}
                  <code>{"{julgamento_tipo}"}</code>,{" "}
                  <code>{"{julgamento_data}"}</code>.
                </span>
              </p>
            </div>

            {/* Notes template */}
            <div className="space-y-1">
              <Label>Anotações (template)</Label>
              <Textarea
                rows={2}
                value={form.notes_template}
                onChange={(e) =>
                  setForm({ ...form, notes_template: e.target.value })
                }
                placeholder="Texto livre — mesmos placeholders."
              />
            </div>

            {/* Ativo */}
            <div className="flex items-center gap-2">
              <Checkbox
                id="tpl-active"
                checked={form.is_active}
                onCheckedChange={(v) =>
                  setForm({ ...form, is_active: Boolean(v) })
                }
              />
              <Label htmlFor="tpl-active" className="cursor-pointer">
                Template ativo
              </Label>
            </div>
          </div>
        </ScrollArea>

        <DialogFooter>
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
