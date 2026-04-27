import { useEffect, useMemo, useState } from "react";
import { Info, Plus, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
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

// ─── Estado ────────────────────────────────────────────────────────────
// Bloco de tarefa: cada um vira um registro próprio na tabela
// `prazo_inicial_task_templates`. Compartilham a mesma chave de
// classificação (tipo_prazo, subtipo, natureza, escritório). Espelha o
// padrão de Publications (TaskTemplatesPage).
interface TaskBlock {
  name: string;
  task_type_id: string; // helper UI (cascata task_type → subtype)
  task_subtype_external_id: string;
  responsible_user_external_id: string;
  priority: string;
  due_business_days: string;
  due_date_reference: string;
  description_template: string;
  notes_template: string;
  is_active: boolean;
}

interface FormState {
  // ── Classificação compartilhada ──
  tipo_prazo: string;
  subtipo: string;          // "" ou valor
  natureza_aplicavel: string; // "" (= null) ou valor
  office_external_id: string; // "" (= null/global) ou "<id>"
  // ── Lista de tarefas ──
  taskBlocks: TaskBlock[];
}

const BLANK_TASK_BLOCK: TaskBlock = {
  name: "",
  task_type_id: "",
  task_subtype_external_id: "",
  responsible_user_external_id: "",
  priority: "Normal",
  due_business_days: "-3",
  due_date_reference: "data_base",
  description_template: "",
  notes_template: "",
  is_active: true,
};

function templateToTaskBlock(
  t: PrazoInicialTaskTemplate,
  taskTypes: TaskTypeOption[],
): TaskBlock {
  // Descobre qual task_type contém o subtype escolhido (cascata).
  let taskTypeId = "";
  for (const tt of taskTypes) {
    if (
      tt.sub_types.some((st) => st.external_id === t.task_subtype_external_id)
    ) {
      taskTypeId = String(tt.id);
      break;
    }
  }
  return {
    name: t.name || "",
    task_type_id: taskTypeId,
    task_subtype_external_id: String(t.task_subtype_external_id),
    responsible_user_external_id: String(t.responsible_user_external_id),
    priority: t.priority || "Normal",
    due_business_days: String(t.due_business_days),
    due_date_reference: t.due_date_reference || "data_base",
    description_template: t.description_template || "",
    notes_template: t.notes_template || "",
    is_active: t.is_active ?? true,
  };
}

function templateToForm(
  t: PrazoInicialTaskTemplate | null,
  taskTypes: TaskTypeOption[],
): FormState {
  return {
    tipo_prazo: t?.tipo_prazo || "",
    subtipo: t?.subtipo || "",
    natureza_aplicavel: t?.natureza_aplicavel || "",
    office_external_id: t?.office_external_id ? String(t.office_external_id) : "",
    taskBlocks: t
      ? [templateToTaskBlock(t, taskTypes)]
      : [{ ...BLANK_TASK_BLOCK }],
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

  // ─── Helpers de manipulação dos blocos ────────────────────────────

  const setBlockField = (idx: number, key: keyof TaskBlock, value: unknown) =>
    setForm((prev) => {
      const blocks = [...prev.taskBlocks];
      blocks[idx] = { ...blocks[idx], [key]: value } as TaskBlock;
      return { ...prev, taskBlocks: blocks };
    });

  const addTaskBlock = () =>
    setForm((prev) => ({
      ...prev,
      taskBlocks: [
        ...prev.taskBlocks,
        // Copia o último bloco (ergonomia: usuário tipicamente quer config
        // similar) mas zera o nome pra forçar revisão. Não copia is_active
        // pra novo bloco começar ativo por default.
        {
          ...prev.taskBlocks[prev.taskBlocks.length - 1],
          name: "",
        },
      ],
    }));

  const removeTaskBlock = (idx: number) =>
    setForm((prev) => ({
      ...prev,
      taskBlocks: prev.taskBlocks.filter((_, i) => i !== idx),
    }));

  // Sincroniza task_subtype quando muda o task_type — limpa se não for filho.
  useEffect(() => {
    setForm((prev) => {
      const blocks = prev.taskBlocks.map((b) => {
        if (!b.task_type_id) return b;
        const parent = taskTypes.find((tt) => String(tt.id) === b.task_type_id);
        if (!parent) return b;
        if (
          b.task_subtype_external_id &&
          !parent.sub_types.some(
            (st) => String(st.external_id) === b.task_subtype_external_id,
          )
        ) {
          return { ...b, task_subtype_external_id: "" };
        }
        return b;
      });
      return { ...prev, taskBlocks: blocks };
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.taskBlocks.map((b) => b.task_type_id).join(",")]);

  const subtypesForBlock = (block: TaskBlock): SubTypeOption[] => {
    const parent = taskTypes.find((tt) => String(tt.id) === block.task_type_id);
    return parent ? parent.sub_types : [];
  };

  // ─── Validação ────────────────────────────────────────────────────

  const validate = (): string | null => {
    if (!form.tipo_prazo) return "Selecione o tipo de prazo.";
    if (form.tipo_prazo === "CONTRARRAZOES") {
      if (
        form.natureza_aplicavel &&
        form.natureza_aplicavel !== "AGRAVO_INSTRUMENTO"
      ) {
        return "CONTRARRAZOES só é emitido em AGRAVO_INSTRUMENTO. Use essa natureza ou deixe genérico.";
      }
    }
    if (form.taskBlocks.length === 0) return "Adicione pelo menos uma tarefa.";

    for (let i = 0; i < form.taskBlocks.length; i++) {
      const b = form.taskBlocks[i];
      const tag = `Tarefa ${i + 1}`;
      if (!b.task_subtype_external_id) {
        return `${tag}: selecione a task do Legal One.`;
      }
      if (!b.responsible_user_external_id) {
        return `${tag}: selecione o responsável.`;
      }
      const days = Number(b.due_business_days);
      if (
        !Number.isFinite(days) ||
        !Number.isInteger(days) ||
        days < -365 ||
        days > 30
      ) {
        return `${tag}: offset em dias úteis precisa ser inteiro entre -365 e 30.`;
      }
    }
    return null;
  };

  // ─── Submit ───────────────────────────────────────────────────────

  // Helper pra encontrar o nome do subtype escolhido (auto-name fallback).
  const subtypeName = (subtypeId: string): string => {
    for (const tt of taskTypes) {
      const s = tt.sub_types.find(
        (x) => String(x.external_id) === subtypeId,
      );
      if (s) return s.name;
    }
    return "Tarefa";
  };

  const buildPayloadForBlock = (
    block: TaskBlock,
  ): PrazoInicialTaskTemplateCreatePayload => {
    // Auto-nome: tipo_prazo (+ subtipo) — task_subtype. Se usuário preencheu
    // name explicitamente, usa esse.
    const autoName =
      `${form.tipo_prazo}` +
      (form.subtipo ? ` / ${form.subtipo}` : "") +
      ` — ${subtypeName(block.task_subtype_external_id)}`;
    return {
      name: block.name.trim() || autoName,
      tipo_prazo: form.tipo_prazo,
      subtipo: tipoExigeSubtipo && form.subtipo ? form.subtipo : null,
      natureza_aplicavel: form.natureza_aplicavel || null,
      office_external_id: form.office_external_id
        ? Number(form.office_external_id)
        : null,
      task_subtype_external_id: Number(block.task_subtype_external_id),
      responsible_user_external_id: Number(block.responsible_user_external_id),
      priority: block.priority,
      due_business_days: Number(block.due_business_days),
      due_date_reference: block.due_date_reference,
      description_template: block.description_template.trim() || null,
      notes_template: block.notes_template.trim() || null,
      is_active: block.is_active,
    };
  };

  const handleSubmit = async () => {
    const err = validate();
    if (err) {
      toast({ title: "Campo inválido", description: err, variant: "destructive" });
      return;
    }
    setSubmitting(true);
    try {
      if (isEdit && template) {
        // Edição: bloco 0 vira PUT no template existente; blocos extras
        // viram POSTs novos compartilhando a mesma chave de classificação.
        const firstPayload = buildPayloadForBlock(form.taskBlocks[0]);
        await onUpdate(template.id, firstPayload);
        for (let i = 1; i < form.taskBlocks.length; i++) {
          await onCreate(buildPayloadForBlock(form.taskBlocks[i]));
        }
        if (form.taskBlocks.length > 1) {
          toast({
            title: "Template atualizado",
            description: `Atualizado + ${form.taskBlocks.length - 1} nova(s) tarefa(s) adicionada(s).`,
          });
        }
      } else {
        // Criação: cada bloco vira um POST. N blocos = N templates com
        // mesma chave de classificação.
        for (const block of form.taskBlocks) {
          await onCreate(buildPayloadForBlock(block));
        }
        if (form.taskBlocks.length > 1) {
          toast({
            title: `${form.taskBlocks.length} templates criados`,
            description: `Mesma classificação, ${form.taskBlocks.length} tarefas.`,
          });
        }
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
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
      <DialogContent className="!max-w-[min(95vw,64rem)] max-h-[90vh] w-[95vw] overflow-hidden flex flex-col p-5 sm:p-6">
        <DialogHeader>
          <DialogTitle>
            {isEdit ? `Editar template: ${template?.name}` : "Novo template"}
          </DialogTitle>
          <DialogDescription>
            Defina a classificação (em cima) e uma ou mais tarefas que serão
            sugeridas no Legal One quando o classifier casar essa
            combinação. Cada tarefa vira uma sugestão separada (ex: abrir
            prazo + pedir cópia ao correspondente).
          </DialogDescription>
        </DialogHeader>

        <ScrollArea className="flex-1 -mr-4 pr-4">
          <div className="space-y-6 pb-2">
            {/* ─── BLOCO 1 — Classificação compartilhada ─── */}
            <section className="space-y-4">
              <div className="flex items-center gap-2">
                <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                  Classificação (casamento)
                </p>
              </div>

              {/* Linha: tipo + subtipo */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div className="space-y-1 min-w-0">
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

                <div className="space-y-1 min-w-0">
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
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div className="space-y-1 min-w-0">
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

                <div className="space-y-1 min-w-0">
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
                    <SelectTrigger className="min-w-0">
                      <SelectValue className="truncate" />
                    </SelectTrigger>
                    <SelectContent className="max-w-[min(90vw,42rem)]">
                      <SelectItem value={NULL_VALUE}>
                        Global (todos os escritórios)
                      </SelectItem>
                      {offices.map((o) => (
                        <SelectItem
                          key={o.external_id}
                          value={String(o.external_id)}
                        >
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
            </section>

            {/* ─── BLOCO 2 — Lista de tarefas ─── */}
            <section className="space-y-3">
              <div className="flex items-center justify-between gap-2">
                <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                  Tarefas a criar{" "}
                  <span className="font-normal normal-case">
                    ({form.taskBlocks.length})
                  </span>
                </p>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={addTaskBlock}
                  className="h-7 px-2 text-xs"
                >
                  <Plus className="mr-1 h-3 w-3" />
                  Adicionar tarefa
                </Button>
              </div>

              {form.taskBlocks.map((block, idx) => {
                const blockSubtypes = subtypesForBlock(block);
                const selectedUser = users.find(
                  (u) =>
                    String(u.external_id) ===
                    block.responsible_user_external_id,
                );
                return (
                  <div
                    key={idx}
                    className="rounded-lg border bg-muted/20 p-4 space-y-4 min-w-0"
                  >
                    {/* Header do bloco */}
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                          Tarefa {idx + 1}
                        </p>
                        {isEdit && idx === 0 && (
                          <Badge
                            variant="outline"
                            className="text-[10px] h-4 px-1.5"
                          >
                            Editando existente
                          </Badge>
                        )}
                        {isEdit && idx > 0 && (
                          <Badge
                            variant="secondary"
                            className="text-[10px] h-4 px-1.5"
                          >
                            Nova
                          </Badge>
                        )}
                      </div>
                      {/* Em edição, não deixa remover o bloco original — usa o
                          delete da listagem principal pra isso. */}
                      {form.taskBlocks.length > 1 &&
                        !(isEdit && idx === 0) && (
                          <button
                            type="button"
                            onClick={() => removeTaskBlock(idx)}
                            className="rounded p-0.5 text-muted-foreground hover:bg-destructive/10 hover:text-destructive transition-colors"
                            title="Remover esta tarefa"
                          >
                            <X className="h-3.5 w-3.5" />
                          </button>
                        )}
                    </div>

                    {/* Nome do template (opcional) */}
                    <div className="space-y-1 min-w-0">
                      <Label htmlFor={`tpl-name-${idx}`}>
                        Nome do template
                        <span className="ml-1 text-muted-foreground font-normal">
                          (opcional — auto-derivado se vazio)
                        </span>
                      </Label>
                      <Input
                        id={`tpl-name-${idx}`}
                        value={block.name}
                        onChange={(e) =>
                          setBlockField(idx, "name", e.target.value)
                        }
                        placeholder={`Ex: Abrir prazo ${form.tipo_prazo || "TIPO"} — global`}
                      />
                    </div>

                    {/* Linha: task type → task subtype (cascade) */}
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      <div className="space-y-1 min-w-0">
                        <Label>Categoria da task *</Label>
                        <Select
                          value={block.task_type_id}
                          onValueChange={(v) =>
                            setBlockField(idx, "task_type_id", v)
                          }
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
                      <div className="space-y-1 min-w-0">
                        <Label>Task do Legal One *</Label>
                        <Select
                          value={block.task_subtype_external_id}
                          onValueChange={(v) =>
                            setBlockField(idx, "task_subtype_external_id", v)
                          }
                          disabled={!block.task_type_id}
                        >
                          <SelectTrigger>
                            <SelectValue placeholder="Selecione..." />
                          </SelectTrigger>
                          <SelectContent>
                            {blockSubtypes.map((st) => (
                              <SelectItem
                                key={st.external_id}
                                value={String(st.external_id)}
                              >
                                {st.name}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                    </div>

                    {/* Responsável */}
                    <div className="space-y-1 min-w-0">
                      <Label>Responsável padrão *</Label>
                      <Select
                        value={block.responsible_user_external_id}
                        onValueChange={(v) =>
                          setBlockField(idx, "responsible_user_external_id", v)
                        }
                      >
                        <SelectTrigger>
                          <SelectValue placeholder="Selecione..." />
                        </SelectTrigger>
                        <SelectContent>
                          {users.map((u) => (
                            <SelectItem
                              key={u.external_id}
                              value={String(u.external_id)}
                            >
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
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                      <div className="space-y-1 min-w-0">
                        <Label>Prioridade</Label>
                        <Select
                          value={block.priority}
                          onValueChange={(v) =>
                            setBlockField(idx, "priority", v)
                          }
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
                      <div className="space-y-1 min-w-0">
                        <Label>Offset (dias úteis)</Label>
                        <Input
                          type="number"
                          min={-365}
                          max={30}
                          step={1}
                          value={block.due_business_days}
                          onChange={(e) =>
                            setBlockField(
                              idx,
                              "due_business_days",
                              e.target.value,
                            )
                          }
                        />
                      </div>
                      <div className="space-y-1 min-w-0">
                        <Label>Referência da data</Label>
                        <Select
                          value={block.due_date_reference}
                          onValueChange={(v) =>
                            setBlockField(idx, "due_date_reference", v)
                          }
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

                    {/* Help text do offset (uma linha só, fora do grid pra
                        evitar quebrar o layout 3-col) */}
                    <p className="text-xs text-muted-foreground">
                      <strong>Offset:</strong> negativo = antes da referência
                      (D-N). Ex: fatal 12/05 com <code>-2</code> → tarefa em
                      10/05. <code>0</code> = no dia. Positivo = depois.
                    </p>

                    {/* Description template */}
                    <div className="space-y-1 min-w-0">
                      <Label>Descrição (template)</Label>
                      <Textarea
                        rows={3}
                        value={block.description_template}
                        onChange={(e) =>
                          setBlockField(
                            idx,
                            "description_template",
                            e.target.value,
                          )
                        }
                        placeholder="Ex: Abrir prazo {tipo_prazo} no processo {cnj}. Data base: {data_base}."
                      />
                    </div>

                    {/* Notes template */}
                    <div className="space-y-1 min-w-0">
                      <Label>Anotações (template)</Label>
                      <Textarea
                        rows={2}
                        value={block.notes_template}
                        onChange={(e) =>
                          setBlockField(idx, "notes_template", e.target.value)
                        }
                        placeholder="Texto livre — mesmos placeholders."
                      />
                    </div>

                    {/* Ativo */}
                    <div className="flex items-center gap-2">
                      <Checkbox
                        id={`tpl-active-${idx}`}
                        checked={block.is_active}
                        onCheckedChange={(v) =>
                          setBlockField(idx, "is_active", Boolean(v))
                        }
                      />
                      <Label
                        htmlFor={`tpl-active-${idx}`}
                        className="cursor-pointer"
                      >
                        Template ativo
                      </Label>
                    </div>
                  </div>
                );
              })}

              {/* Help geral sobre placeholders (renderiza uma vez fora dos
                  blocos pra não poluir cada card) */}
              <p className="text-xs text-muted-foreground inline-flex items-start gap-1 px-1">
                <Info className="h-3 w-3 mt-0.5 shrink-0" />
                <span>
                  Placeholders disponíveis nos templates:{" "}
                  <code>{"{cnj}"}</code>, <code>{"{tipo_prazo}"}</code>,{" "}
                  <code>{"{subtipo}"}</code>, <code>{"{data_base}"}</code>,{" "}
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
            </section>
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
            {submitting
              ? "Salvando..."
              : isEdit
                ? form.taskBlocks.length > 1
                  ? `Atualizar (+${form.taskBlocks.length - 1} nova(s))`
                  : "Atualizar"
                : form.taskBlocks.length > 1
                  ? `Criar ${form.taskBlocks.length} templates`
                  : "Criar"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
