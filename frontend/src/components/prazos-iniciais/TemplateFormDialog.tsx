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
import { SubtypePicker } from "@/components/ui/SubtypePicker";
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
  /** Squads de suporte (kind='support') pra dropdown do bloco. Carregado
   *  pelo parent via /api/v1/squads?kind=support. */
  supportSquads?: SupportSquadOption[];
}

// ─── Estado ────────────────────────────────────────────────────────────
// Bloco de tarefa: cada um vira um registro próprio na tabela
// `prazo_inicial_task_templates`. Compartilham a mesma chave de
// classificação (tipo_prazo, subtipo, natureza, escritório). Espelha o
// padrão de Publications (TaskTemplatesPage).
interface TaskBlock {
  name: string;
  // Template "no-op" (pin014): casa normal, mas NAO cria tarefa no L1.
  // Quando true, esconde os campos de task (subtype/responsavel/prioridade/
  // offset/refdata) — eles vao zerados no payload.
  skip_task_creation: boolean;
  task_type_id: string; // helper UI (cascata task_type → subtype)
  task_subtype_external_id: string;
  responsible_user_external_id: string;
  priority: string;
  due_business_days: string;
  due_date_reference: string;
  description_template: string;
  notes_template: string;
  is_active: boolean;
  // Quando true, ao criar a tarefa no L1 o backend redireciona pro
  // assistente da squad do `responsible_user_external_id`. Persiste em
  // `prazo_inicial_task_templates.target_role` ('principal' | 'assistente').
  target_role_assistant: boolean;
  target_squad_id: string;  // "" = nenhum; "<id>" = aponta pra squad de suporte
}

interface SupportSquadOption {
  id: number;
  name: string;
  office_external_id: number | null;
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
  skip_task_creation: false,
  task_type_id: "",
  task_subtype_external_id: "",
  responsible_user_external_id: "",
  priority: "Normal",
  due_business_days: "-3",
  due_date_reference: "data_base",
  description_template: "",
  notes_template: "",
  is_active: true,
  target_role_assistant: false,
  target_squad_id: "",
};

function templateToTaskBlock(
  t: PrazoInicialTaskTemplate,
  taskTypes: TaskTypeOption[],
): TaskBlock {
  // Descobre qual task_type contém o subtype escolhido (cascata).
  // Templates no-op (skip_task_creation=true) tem subtype=null — fica
  // taskTypeId="" mesmo, sem cascata aplicavel.
  let taskTypeId = "";
  if (t.task_subtype_external_id != null) {
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
    name: t.name || "",
    skip_task_creation: !!t.skip_task_creation,
    task_type_id: taskTypeId,
    task_subtype_external_id:
      t.task_subtype_external_id != null
        ? String(t.task_subtype_external_id)
        : "",
    responsible_user_external_id:
      t.responsible_user_external_id != null
        ? String(t.responsible_user_external_id)
        : "",
    priority: t.priority || "Normal",
    due_business_days: String(t.due_business_days),
    due_date_reference: t.due_date_reference || "data_base",
    description_template: t.description_template || "",
    notes_template: t.notes_template || "",
    is_active: t.is_active ?? true,
    target_role_assistant: (t as any).target_role === "assistente",
    target_squad_id: (t as any).target_squad_id ? String((t as any).target_squad_id) : "",
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
  supportSquads = [],
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
        // Copia o último bloco como base de ergonomia (responsável,
        // prioridade, prazo etc. costumam ser parecidos), MAS limpa
        // task_type_id + task_subtype_external_id pra forçar escolha
        // consciente. Sem isso, o backend retornaria 409 de duplicata
        // exata (mesma chave classificação + mesmo subtype) ao salvar.
        {
          ...prev.taskBlocks[prev.taskBlocks.length - 1],
          name: "",
          task_type_id: "",
          task_subtype_external_id: "",
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

  /**
   * Adapter pro `SubtypePicker` compartilhado.
   *
   * O componente em `@/components/ui/SubtypePicker` foi escrito pro shape
   * usado em Publications (`external_id` + `subtypes`). Aqui usamos
   * `id` + `sub_types`. Mapeamos uma vez pra não converter a cada render
   * dos blocos. O `external_id` no adapter recebe o `tt.id` interno —
   * é só identificador opaco pro picker, não vai pra API. O picker chama
   * `onChange(subId, parentType)` e a gente usa `parentType.external_id`
   * (= tt.id original) pra alimentar `block.task_type_id`.
   */
  const taskTypesForPicker = useMemo(
    () =>
      taskTypes.map((tt) => ({
        external_id: tt.id,
        name: tt.name,
        subtypes: tt.sub_types.map((st) => ({
          external_id: st.external_id,
          name: st.name,
        })),
      })),
    [taskTypes],
  );

  /**
   * Subtypes em uso por OUTROS blocos do form atual. Se o operador tentar
   * selecionar um já em uso, o backend retornaria 409. Marcamos o item
   * como `(já em uso)` e disabled no Select pra evitar a tentativa.
   *
   * Cobre só duplicatas dentro do form. Duplicatas com templates "irmãos"
   * já existentes no banco (mesma chave classificação + office, subtype
   * diferente) ainda podem dar 409 — pra cobrir esse caso, a página
   * admin precisaria passar a lista de irmãos como prop. Fica como
   * follow-up se aparecer no uso real.
   */
  const subtypesInUseByOtherBlocks = (blockIdx: number): Set<string> => {
    const used = new Set<string>();
    form.taskBlocks.forEach((b, i) => {
      if (i === blockIdx) return;
      // Blocos no-op nao reservam subtype (nao criam tarefa).
      if (b.skip_task_creation) return;
      if (b.task_subtype_external_id) {
        used.add(b.task_subtype_external_id);
      }
    });
    return used;
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

    // Pre-flight: detecta subtypes duplicados ENTRE blocos do form. Cada
    // tarefa precisa de um subtype diferente — o backend rejeita
    // duplicata exata na chave (tipo_prazo, subtipo, natureza, office,
    // task_subtype) com 409, e a mensagem genérica não diz qual bloco
    // está colidindo. Blocos no-op (skip_task_creation) nao usam subtype.
    const seenSubtypes = new Map<string, number>();
    for (let i = 0; i < form.taskBlocks.length; i++) {
      const blk = form.taskBlocks[i];
      if (blk.skip_task_creation) continue;
      const sub = blk.task_subtype_external_id;
      if (!sub) continue;
      if (seenSubtypes.has(sub)) {
        const firstIdx = seenSubtypes.get(sub)!;
        return `Tarefa ${firstIdx + 1} e Tarefa ${i + 1} usam o mesmo subtipo de task. Cada tarefa precisa de um subtipo diferente.`;
      }
      seenSubtypes.set(sub, i);
    }

    for (let i = 0; i < form.taskBlocks.length; i++) {
      const b = form.taskBlocks[i];
      const tag = `Tarefa ${i + 1}`;
      // Bloco no-op: pula validacoes de campos de tarefa — eles vao
      // como null no payload.
      if (b.skip_task_creation) continue;
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
    // name explicitamente, usa esse. Bloco no-op: nao tem subtype, label
    // "— Sem providencia".
    const autoName =
      `${form.tipo_prazo}` +
      (form.subtipo ? ` / ${form.subtipo}` : "") +
      ` — ${block.skip_task_creation ? "Sem providência" : subtypeName(block.task_subtype_external_id)}`;
    return {
      name: block.name.trim() || autoName,
      tipo_prazo: form.tipo_prazo,
      subtipo: tipoExigeSubtipo && form.subtipo ? form.subtipo : null,
      natureza_aplicavel: form.natureza_aplicavel || null,
      office_external_id: form.office_external_id
        ? Number(form.office_external_id)
        : null,
      skip_task_creation: block.skip_task_creation,
      // Bloco no-op: zera os IDs de tarefa (backend rejeita se viessem
      // preenchidos com skip=true).
      task_subtype_external_id: block.skip_task_creation
        ? null
        : Number(block.task_subtype_external_id),
      responsible_user_external_id: block.skip_task_creation
        ? null
        : Number(block.responsible_user_external_id),
      priority: block.priority,
      due_business_days: Number(block.due_business_days),
      due_date_reference: block.due_date_reference,
      description_template: block.description_template.trim() || null,
      notes_template: block.notes_template.trim() || null,
      is_active: block.is_active,
      target_role: block.target_role_assistant ? "assistente" : "principal",
      target_squad_id: block.target_squad_id ? parseInt(block.target_squad_id) : null,
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

        {/* Scroll nativo em vez do Radix ScrollArea — ScrollArea precisa de
            altura explícita resolvida e às vezes falha quando o conteúdo
            cresce dinamicamente (ex.: 2+ blocos de tarefa empurrando além
            do max-h-90vh). overflow-y-auto + flex-1 dentro de DialogContent
            flex-col com max-h-[90vh] resolve sem mistério. */}
        <div className="flex-1 overflow-y-auto -mr-2 pr-2 min-h-0">
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
                const usedSubtypes = subtypesInUseByOtherBlocks(idx);
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

                    {/* Toggle no-op: nao agendar tarefa, finalizar caso */}
                    <div className="flex items-start gap-2 rounded-md border bg-background p-3">
                      <Checkbox
                        id={`tpl-skip-${idx}`}
                        checked={block.skip_task_creation}
                        onCheckedChange={(v) =>
                          setBlockField(
                            idx,
                            "skip_task_creation",
                            Boolean(v),
                          )
                        }
                        className="mt-0.5"
                      />
                      <div className="space-y-0.5">
                        <Label
                          htmlFor={`tpl-skip-${idx}`}
                          className="cursor-pointer"
                        >
                          Não agendar tarefa — apenas finalizar caso
                        </Label>
                        <p className="text-xs text-muted-foreground">
                          Quando essa classificação aparecer, o intake é
                          finalizado como{" "}
                          <em>concluído sem providência</em>: sobe a
                          habilitação no GED e cancela a task legada, sem
                          criar tarefa nova no Legal One.
                        </p>
                      </div>
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

                    {/* Bloco de configuracao da tarefa (oculto em template
                        no-op — skip_task_creation=true). Cobre subtype,
                        responsavel, prioridade/offset/refdata, e templates
                        de descricao/anotacoes. */}
                    {!block.skip_task_creation ? (
                    <>
                    {/* Combobox unificado tipo+subtipo com busca, igual ao
                        modal de Confirmar Agendamento e ao form de templates
                        de publicação. Catálogo do L1 tem ~900 subtipos —
                        Select tradicional vira inviável.

                        Adapter de schema: `taskTypes` aqui usa `id` e
                        `sub_types` (snake), enquanto o SubtypePicker
                        compartilhado espera `external_id` e `subtypes`.
                        Mapeamos no useMemo pra não recalcular a cada render.

                        `task_type_id` continua sendo derivado: setado
                        automaticamente quando o operador escolhe um subtipo. */}
                    <SubtypePicker
                      value={
                        block.task_subtype_external_id
                          ? Number(block.task_subtype_external_id)
                          : null
                      }
                      taskTypes={taskTypesForPicker}
                      onChange={(subId, parentType) => {
                        setBlockField(
                          idx,
                          "task_subtype_external_id",
                          String(subId),
                        );
                        setBlockField(
                          idx,
                          "task_type_id",
                          parentType ? String(parentType.external_id) : "",
                        );
                      }}
                      disabledSubtypeIds={
                        new Set(Array.from(usedSubtypes).map(Number))
                      }
                      label="Task do Legal One"
                      required
                      placeholder="Selecione a task"
                      searchPlaceholder="Buscar por categoria ou task..."
                    />

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
                      <div className="flex items-start gap-2 pt-1">
                        <Checkbox
                          id={`target-assistant-${idx}`}
                          checked={block.target_role_assistant}
                          onCheckedChange={(v) =>
                            setBlockField(idx, "target_role_assistant", !!v)
                          }
                        />
                        <Label
                          htmlFor={`target-assistant-${idx}`}
                          className="text-xs font-normal leading-tight cursor-pointer"
                        >
                          Atribuir ao <strong>assistente</strong>
                          {block.target_squad_id ? " da squad escolhida abaixo" : " da squad do responsável"}
                          <span className="block text-muted-foreground">
                            {block.target_squad_id
                              ? "Marcado = vai pro assistente da squad de suporte (round-robin). Desmarcado = vai pro líder dessa squad."
                              : "Marcado = responsável vira 'líder de referência' e a tarefa cai pro assistente da squad principal dele."}
                          </span>
                        </Label>
                      </div>
                      <div className="space-y-1 pt-1">
                        <Label className="text-xs">
                          Squad de suporte (opcional)
                          <span className="ml-1 text-muted-foreground font-normal">
                            — sobrepõe o responsável padrão
                          </span>
                        </Label>
                        <Select
                          value={block.target_squad_id || "_none"}
                          onValueChange={(v) =>
                            setBlockField(idx, "target_squad_id", v === "_none" ? "" : v)
                          }
                        >
                          <SelectTrigger><SelectValue placeholder="Sem squad de suporte" /></SelectTrigger>
                          <SelectContent>
                            <SelectItem value="_none">Sem squad de suporte (responsável padrão)</SelectItem>
                            {supportSquads
                              .filter((s) => {
                                const tmplOff = form.office_external_id;
                                if (!tmplOff) return true;  // template global
                                return s.office_external_id != null && s.office_external_id === parseInt(tmplOff);
                              })
                              .map((s) => (
                                <SelectItem key={s.id} value={String(s.id)}>{s.name}</SelectItem>
                              ))}
                          </SelectContent>
                        </Select>
                      </div>
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
                    </>
                    ) : null}

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
        </div>

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
