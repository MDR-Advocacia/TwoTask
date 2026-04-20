/**
 * TaskTemplatesPage — Configuração de Templates de Agendamento
 *
 * Permite criar/editar/excluir templates que mapeiam:
 *   classificação (categoria + subcategoria) × escritório responsável
 *   → tipo/subtipo de tarefa + usuário responsável + prazo + textos
 *
 * Estes templates são usados pelo motor de auto-classificação para
 * pré-montar tarefas que o operador confirma antes de enviar ao Legal One.
 */

import { useEffect, useState, useMemo } from "react";
import {
  AlertCircle,
  BookTemplate,
  Building2,
  Check,
  Edit2,
  LayoutGrid,
  List,
  Loader2,
  Plus,
  RefreshCw,
  Settings,
  ShieldAlert,
  Tag,
  Trash2,
  User,
  X,
} from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
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
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { useToast } from "@/hooks/use-toast";
import { apiFetch } from "@/lib/api-client";

const API = "/api/v1/task-templates";

// ─── Types ─────────────────────────────────────────────────────────────────

interface Office {
  id: number;
  external_id: number;
  name: string;
  path: string;
}

interface TaskSubtype {
  external_id: number;
  name: string;
}

interface TaskType {
  external_id: number;
  name: string;
  subtypes: TaskSubtype[];
}

interface AppUser {
  external_id: number;
  name: string;
  email: string | null;
}

interface CategoryEntry {
  category: string;
  subcategories: string[];
}

interface ClassificationOverride {
  id: number;
  office_external_id: number;
  category: string;
  subcategory: string | null;
  action: "exclude" | "include_custom";
  custom_description: string | null;
  is_active: boolean;
  created_at: string | null;
}

interface TaskTemplate {
  id: number;
  name: string;
  category: string;
  subcategory: string | null;
  office_external_id: number | null;
  office_name: string | null;
  task_subtype_external_id: number;
  task_subtype_name: string | null;
  task_type_name: string | null;
  responsible_user_external_id: number;
  responsible_user_name: string | null;
  priority: string;
  due_business_days: number;
  due_date_reference: string;
  description_template: string | null;
  notes_template: string | null;
  is_active: boolean;
}

// ─── Blank form ────────────────────────────────────────────────────────────

/** Um bloco de tarefa dentro do formulário (pode haver N por classificação) */
const BLANK_TASK_BLOCK = {
  name: "",
  task_type_external_id: "", // helper, not sent to API
  task_subtype_external_id: "",
  responsible_user_external_id: "",
  priority: "Normal",
  due_business_days: "3",
  due_date_reference: "publication",
  description_template:
    "Publicação judicial referente ao processo {cnj} em {publication_date}.",
  notes_template: "",
  is_active: true,
};

type TaskBlock = typeof BLANK_TASK_BLOCK;

/** Formulário compartilhado — classificação (topo) + N blocos de tarefa */
const BLANK_FORM = {
  category: "",
  subcategory: "",
  office_external_id: "_global",
  taskBlocks: [{ ...BLANK_TASK_BLOCK }] as TaskBlock[],
};

// ─── Component ─────────────────────────────────────────────────────────────

const TaskTemplatesPage = () => {
  const { toast } = useToast();

  const [templates, setTemplates] = useState<TaskTemplate[]>([]);
  const [offices, setOffices] = useState<Office[]>([]);
  const [taskTypes, setTaskTypes] = useState<TaskType[]>([]);
  const [users, setUsers] = useState<AppUser[]>([]);
  const [categories, setCategories] = useState<CategoryEntry[]>([]);

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Filter state
  const [filterOffice, setFilterOffice] = useState("all");
  const [filterCategory, setFilterCategory] = useState("all");
  const [viewMode, setViewMode] = useState<"flat" | "by-office">("flat");
  const [coverageOnlyMissing, setCoverageOnlyMissing] = useState(false);

  // Form dialog
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState({ ...BLANK_FORM });

  // Classification overrides
  const [overrides, setOverrides] = useState<ClassificationOverride[]>([]);
  const [loadingOverrides, setLoadingOverrides] = useState(false);
  const [overrideFilterOffice, setOverrideFilterOffice] = useState("");
  const [overrideDialogOpen, setOverrideDialogOpen] = useState(false);
  const [editingOverride, setEditingOverride] = useState<ClassificationOverride | null>(null);
  const [savingOverride, setSavingOverride] = useState(false);
  const [overrideForm, setOverrideForm] = useState({
    // "all" = aplicar em todos os escritórios (bulk);
    // string numérica = escritório específico.
    scope: "all" as string,
    office_external_id: "",
    category: "",
    subcategory: "",
    action: "exclude" as "exclude" | "include_custom",
    custom_description: "",
    is_active: true,
  });

  // Bulk override (aplicar/remover em todos os escritórios)
  const [bulkDialogOpen, setBulkDialogOpen] = useState(false);
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkForm, setBulkForm] = useState({
    mode: "apply" as "apply" | "remove",
    category: "",
    subcategory: "",
    action: "exclude" as "exclude" | "include_custom",
    custom_description: "",
  });
  const bulkSubcategories = useMemo(() => {
    if (!bulkForm.category) return [];
    const entry = categories.find((c) => c.category === bulkForm.category);
    return entry?.subcategories || [];
  }, [bulkForm.category, categories]);

  // ─── Data loading ──────────────────────────────────────────────────────

  const loadAll = async () => {
    setLoading(true);
    setError(null);
    try {
      const [tplRes, offRes, ttRes, usrRes, catRes] = await Promise.all([
        apiFetch(`${API}/`),
        apiFetch("/api/v1/offices"),
        apiFetch(`${API}/meta/task-types`),
        apiFetch(`${API}/meta/users`),
        apiFetch(`${API}/meta/categories`),
      ]);

      if (!tplRes.ok || !offRes.ok || !ttRes.ok || !usrRes.ok || !catRes.ok) {
        throw new Error("Falha ao carregar dados. Tente recarregar a página.");
      }

      setTemplates(await tplRes.json());
      setOffices(await offRes.json());
      setTaskTypes(await ttRes.json());
      setUsers(await usrRes.json());
      const catData = await catRes.json();
      setCategories(catData.categories || []);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadAll();
    loadOverrides();
  }, []);

  /**
   * Carrega SEMPRE todos os overrides. O filtro por escritório é aplicado
   * na exibição da tabela (client-side). Isso garante que o grid de cobertura
   * por escritório possa aplicar os overrides certos de cada escritório sem
   * depender do filtro da tabela.
   */
  const loadOverrides = async (_officeId?: string) => {
    setLoadingOverrides(true);
    try {
      const res = await apiFetch(`/api/v1/publications/classification-overrides`);
      if (!res.ok) throw new Error("Falha ao carregar overrides.");
      setOverrides(await res.json());
    } catch (err: any) {
      toast({ title: "Erro", description: err.message, variant: "destructive" });
    } finally {
      setLoadingOverrides(false);
    }
  };

  // ─── Computed ──────────────────────────────────────────────────────────

  const filteredTemplates = useMemo(() => {
    return templates.filter((t) => {
      if (filterOffice !== "all") {
        const tOffice = t.office_external_id === null ? "_global" : String(t.office_external_id);
        if (tOffice !== filterOffice) return false;
      }
      if (filterCategory !== "all" && t.category !== filterCategory) return false;
      return true;
    });
  }, [templates, filterOffice, filterCategory]);

  /** Retorna os subtipos disponíveis para o tipo escolhido num bloco específico */
  const getSubtypesForBlock = (blockIdx: number): TaskSubtype[] => {
    const typeId = form.taskBlocks[blockIdx]?.task_type_external_id;
    if (!typeId) return [];
    return taskTypes.find((t) => String(t.external_id) === typeId)?.subtypes ?? [];
  };

  const categorySubcategories = useMemo(() => {
    if (!form.category) return [];
    const entry = categories.find((c) => c.category === form.category);
    return entry?.subcategories ?? [];
  }, [form.category, categories]);

  const overrideCategorySubcategories = useMemo(() => {
    if (!overrideForm.category) return [];
    const entry = categories.find((c) => c.category === overrideForm.category);
    return entry?.subcategories ?? [];
  }, [overrideForm.category, categories]);

  /**
   * Aplica os overrides ATIVOS de um escritório específico sobre a taxonomia
   * base, devolvendo a "taxonomia efetiva" daquele escritório.
   *
   * - exclude com subcategory=null → remove a categoria inteira
   * - exclude com subcategory preenchida → remove só aquela subcategoria
   * - include_custom → adiciona categoria (se nova) e/ou subcategoria
   */
  const getEffectiveCategoriesForOffice = (officeId: number): CategoryEntry[] => {
    const tree: Record<string, string[]> = {};
    categories.forEach((c) => {
      tree[c.category] = [...c.subcategories];
    });

    const relevant = overrides.filter(
      (o) => o.office_external_id === officeId && o.is_active
    );

    // Exclusões
    relevant
      .filter((o) => o.action === "exclude")
      .forEach((o) => {
        if (o.subcategory == null || o.subcategory === "") {
          delete tree[o.category];
        } else if (tree[o.category]) {
          tree[o.category] = tree[o.category].filter((s) => s !== o.subcategory);
        }
      });

    // Adições customizadas
    relevant
      .filter((o) => o.action === "include_custom")
      .forEach((o) => {
        if (!tree[o.category]) tree[o.category] = [];
        if (o.subcategory && !tree[o.category].includes(o.subcategory)) {
          tree[o.category].push(o.subcategory);
        }
      });

    return Object.entries(tree).map(([cat, subs]) => ({
      category: cat,
      subcategories: subs,
    }));
  };

  /**
   * Cobertura por escritório: para cada escritório, quantas combinações
   * categoria/subcategoria já têm template ativo e quais estão faltando.
   *
   * Cada "slot" é uma combinação (categoria, subcategoria ou "-"). A taxonomia
   * esperada é a **efetiva daquele escritório** — já com os overrides
   * (excluir / adicionar customizada) aplicados.
   */
  const coverageByOffice = useMemo(() => {
    type Slot = { category: string; subcategory: string };

    // Agrupa templates por escritório (somente ativos contam como coberto)
    // Ignora templates globais (office_external_id === null) na cobertura por escritório
    const templatesByOffice = new Map<number, TaskTemplate[]>();
    templates.forEach((t) => {
      if (t.office_external_id === null) return;
      const arr = templatesByOffice.get(t.office_external_id) || [];
      arr.push(t);
      templatesByOffice.set(t.office_external_id, arr);
    });

    // Apenas escritórios que aparecem no filterOffice (ou todos)
    const relevantOffices = offices.filter((o) =>
      filterOffice === "all" ? true : String(o.external_id) === filterOffice
    );

    return relevantOffices.map((office) => {
      // Taxonomia efetiva DESTE escritório (base + overrides ativos).
      const effective = getEffectiveCategoriesForOffice(office.external_id);
      const expectedSlots: Slot[] = [];
      effective.forEach((entry) => {
        if (entry.subcategories.length > 0) {
          entry.subcategories.forEach((sub) => {
            expectedSlots.push({ category: entry.category, subcategory: sub });
          });
        } else {
          expectedSlots.push({ category: entry.category, subcategory: "-" });
        }
      });

      const officeTemplates = templatesByOffice.get(office.external_id) || [];
      // Normaliza subcategory "" / null para "-"
      const coveredKeys = new Set(
        officeTemplates
          .filter((t) => t.is_active)
          .map(
            (t) =>
              `${t.category}||${t.subcategory && t.subcategory !== "" ? t.subcategory : "-"}`
          )
      );

      const slots = expectedSlots
        .filter((s) =>
          filterCategory === "all" ? true : s.category === filterCategory
        )
        .map((s) => {
          const key = `${s.category}||${s.subcategory}`;
          const covered = coveredKeys.has(key);
          const templateMatch = covered
            ? officeTemplates.find(
                (t) =>
                  t.is_active &&
                  t.category === s.category &&
                  (t.subcategory ?? "-") === s.subcategory
              )
            : null;
          return { ...s, covered, template: templateMatch };
        });

      const coveredCount = slots.filter((s) => s.covered).length;
      const missingCount = slots.length - coveredCount;

      return {
        office,
        slots,
        coveredCount,
        missingCount,
        total: slots.length,
      };
    });
  }, [templates, offices, categories, overrides, filterOffice, filterCategory]);

  // ─── Form helpers ──────────────────────────────────────────────────────

  /** Atualiza campo de topo do formulário (category, subcategory, office_external_id) */
  const setField = (key: string, value: any) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  /** Atualiza um campo dentro de um bloco de tarefa específico */
  const setBlockField = (blockIdx: number, key: string, value: any) =>
    setForm((prev) => {
      const blocks = [...prev.taskBlocks];
      blocks[blockIdx] = { ...blocks[blockIdx], [key]: value };
      return { ...prev, taskBlocks: blocks };
    });

  /** Adiciona um novo bloco de tarefa (copia o último como base) */
  const addTaskBlock = () =>
    setForm((prev) => ({
      ...prev,
      taskBlocks: [
        ...prev.taskBlocks,
        { ...prev.taskBlocks[prev.taskBlocks.length - 1], name: "" },
      ],
    }));

  /** Remove o bloco de tarefa no índice dado */
  const removeTaskBlock = (idx: number) =>
    setForm((prev) => ({
      ...prev,
      taskBlocks: prev.taskBlocks.filter((_, i) => i !== idx),
    }));

  const openCreate = () => {
    setEditingId(null);
    setForm({
      ...BLANK_FORM,
      taskBlocks: [{ ...BLANK_TASK_BLOCK }],
    });
    setDialogOpen(true);
  };

  const openEdit = (tmpl: TaskTemplate) => {
    const parentType = taskTypes.find((tt) =>
      tt.subtypes.some((s) => s.external_id === tmpl.task_subtype_external_id)
    );
    setEditingId(tmpl.id);
    setForm({
      category: tmpl.category,
      subcategory: tmpl.subcategory ?? "",
      office_external_id: tmpl.office_external_id === null ? "_global" : String(tmpl.office_external_id),
      taskBlocks: [{
        name: tmpl.name,
        task_type_external_id: parentType ? String(parentType.external_id) : "",
        task_subtype_external_id: String(tmpl.task_subtype_external_id),
        responsible_user_external_id: String(tmpl.responsible_user_external_id),
        priority: tmpl.priority,
        due_business_days: String(tmpl.due_business_days),
        due_date_reference: tmpl.due_date_reference || "publication",
        description_template: tmpl.description_template ?? "",
        notes_template: tmpl.notes_template ?? "",
        is_active: tmpl.is_active,
      }],
    });
    setDialogOpen(true);
  };

  const handleSave = async () => {
    if (!form.category || form.taskBlocks.length === 0) {
      toast({
        title: "Campos obrigatórios",
        description: "Preencha ao menos a categoria.",
        variant: "destructive",
      });
      return;
    }

    // Valida todos os blocos
    for (let i = 0; i < form.taskBlocks.length; i++) {
      const b = form.taskBlocks[i];
      if (!b.task_subtype_external_id || !b.responsible_user_external_id) {
        toast({
          title: `Tarefa ${i + 1} incompleta`,
          description: "Preencha: subtipo de tarefa e usuário responsável.",
          variant: "destructive",
        });
        return;
      }
    }

    setSaving(true);
    const officeValue =
      form.office_external_id === "_global" || form.office_external_id === ""
        ? null
        : parseInt(form.office_external_id);

    // Helper pra obter nome do subtipo (pra auto-nome)
    const subtypeName = (subtypeId: string): string => {
      for (const t of taskTypes) {
        const s = t.subtypes.find((x) => String(x.external_id) === subtypeId);
        if (s) return s.name;
      }
      return "Tarefa";
    };

    const buildPayload = (block: TaskBlock, idx: number) => ({
      // Nome auto-gerado: usa o subtipo como rótulo. Backend exige name,
      // mas a UI não expõe mais esse campo ao usuário.
      name: (block.name?.trim() ||
        `${form.category}${form.subcategory ? " / " + form.subcategory : ""} — ${subtypeName(block.task_subtype_external_id)}`),
      category: form.category,
      subcategory: form.subcategory || null,
      office_external_id: officeValue,
      task_subtype_external_id: parseInt(block.task_subtype_external_id),
      responsible_user_external_id: parseInt(block.responsible_user_external_id),
      priority: block.priority,
      due_business_days: parseInt(block.due_business_days) || 3,
      due_date_reference: block.due_date_reference || "publication",
      description_template: block.description_template || null,
      notes_template: block.notes_template || null,
      is_active: block.is_active,
    });

    try {
      if (editingId) {
        // Edição:
        //  - bloco 0 → PUT no registro existente (editingId)
        //  - blocos 1..N (adicionados via "Adicionar tarefa") → POST como
        //    novos registros compartilhando categoria + subcategoria + escritório.
        const firstPayload = buildPayload(form.taskBlocks[0], 0);
        const putRes = await apiFetch(`${API}/${editingId}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(firstPayload),
        });
        if (!putRes.ok) {
          const data = await putRes.json().catch(() => ({}));
          throw new Error(data.detail || "Erro ao atualizar template.");
        }

        const addedNames: string[] = [];
        for (let idx = 1; idx < form.taskBlocks.length; idx++) {
          const payload = buildPayload(form.taskBlocks[idx], idx);
          const res = await apiFetch(`${API}/`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          });
          if (!res.ok) {
            const data = await res.json().catch(() => ({}));
            throw new Error(data.detail || `Erro ao criar tarefa ${idx + 1}.`);
          }
          const created_item = await res.json();
          addedNames.push(created_item.name ?? payload.name);
        }

        if (addedNames.length > 0) {
          toast({
            title: `Template atualizado e ${addedNames.length} tarefa${addedNames.length > 1 ? "s" : ""} adicionada${addedNames.length > 1 ? "s" : ""}`,
            description: `Atualizada: "${firstPayload.name}" • Novas: ${addedNames.join(" • ")}`,
          });
        } else {
          toast({ title: "Template atualizado", description: `"${firstPayload.name}" salvo com sucesso.` });
        }
      } else {
        // Criação: cria um registro por bloco (cada bloco gera uma tarefa
        // distinta no agendamento, mas o usuário enxerga como "1 template
        // com N tarefas").
        const created: string[] = [];
        for (let idx = 0; idx < form.taskBlocks.length; idx++) {
          const payload = buildPayload(form.taskBlocks[idx], idx);
          const res = await apiFetch(`${API}/`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          });
          if (!res.ok) {
            const data = await res.json().catch(() => ({}));
            throw new Error(data.detail || `Erro ao criar tarefa ${idx + 1}.`);
          }
          const created_item = await res.json();
          created.push(created_item.name ?? payload.name);
        }
        toast({
          title: `Template criado com ${created.length} tarefa${created.length > 1 ? "s" : ""}`,
          description: created.join(" • "),
        });
      }

      setDialogOpen(false);
      await loadAll();
    } catch (err: any) {
      toast({ title: "Erro", description: err.message, variant: "destructive" });
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: number, name: string) => {
    if (!confirm(`Remover o template "${name}"?`)) return;
    try {
      const res = await apiFetch(`${API}/${id}`, { method: "DELETE" });
      if (!res.ok && res.status !== 204) {
        throw new Error("Erro ao remover template.");
      }
      toast({ title: "Template removido" });
      setTemplates((prev) => prev.filter((t) => t.id !== id));
    } catch (err: any) {
      toast({ title: "Erro", description: err.message, variant: "destructive" });
    }
  };

  const handleToggleActive = async (tmpl: TaskTemplate) => {
    try {
      const res = await apiFetch(`${API}/${tmpl.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_active: !tmpl.is_active }),
      });
      if (!res.ok) throw new Error("Erro ao atualizar template.");
      toast({
        title: tmpl.is_active ? "Template desativado" : "Template ativado",
      });
      await loadAll();
    } catch (err: any) {
      toast({ title: "Erro", description: err.message, variant: "destructive" });
    }
  };

  // ─── Classification Overrides CRUD ─────────────────────────────────────

  /** Abre o dialog pra adicionar uma classificação personalizada (include_custom). */
  const openAddClassification = () => {
    setEditingOverride(null);
    setOverrideForm({
      scope: "all",
      office_external_id: "",
      category: "",
      subcategory: "",
      action: "include_custom",
      custom_description: "",
      is_active: true,
    });
    setOverrideDialogOpen(true);
  };

  /** Abre o dialog pra excluir uma classificação (exclude). */
  const openExcludeClassification = () => {
    setEditingOverride(null);
    setOverrideForm({
      scope: "all",
      office_external_id: "",
      category: "",
      subcategory: "",
      action: "exclude",
      custom_description: "",
      is_active: true,
    });
    setOverrideDialogOpen(true);
  };

  const openEditOverride = (ov: ClassificationOverride) => {
    setEditingOverride(ov);
    setOverrideForm({
      scope: String(ov.office_external_id),
      office_external_id: String(ov.office_external_id),
      category: ov.category,
      subcategory: ov.subcategory ?? "",
      action: ov.action,
      custom_description: ov.custom_description ?? "",
      is_active: ov.is_active,
    });
    setOverrideDialogOpen(true);
  };

  const handleSaveOverride = async () => {
    if (!overrideForm.category || !overrideForm.action) {
      toast({
        title: "Campos obrigatórios",
        description: "Preencha: categoria e ação.",
        variant: "destructive",
      });
      return;
    }

    const isBulk = !editingOverride && overrideForm.scope === "all";
    const officeId = isBulk
      ? null
      : (overrideForm.scope === "all" ? "" : overrideForm.scope);

    if (!isBulk && !editingOverride && !officeId) {
      toast({
        title: "Selecione um escritório",
        description: "Escolha 'Todos os escritórios' ou um escritório específico.",
        variant: "destructive",
      });
      return;
    }

    setSavingOverride(true);
    try {
      let res: Response;

      if (editingOverride) {
        // Edição só atualiza flags/descrição do override existente.
        res = await apiFetch(
          `/api/v1/publications/classification-overrides/${editingOverride.id}`,
          {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              custom_description: overrideForm.custom_description || null,
              is_active: overrideForm.is_active,
            }),
          }
        );
      } else if (isBulk) {
        // Aplica em todos os escritórios conhecidos.
        res = await apiFetch("/api/v1/publications/classification-overrides/bulk", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            category: overrideForm.category,
            subcategory: overrideForm.subcategory || null,
            action: overrideForm.action,
            custom_description: overrideForm.custom_description || null,
          }),
        });
      } else {
        // Escritório específico.
        res = await apiFetch("/api/v1/publications/classification-overrides", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            office_external_id: parseInt(officeId!),
            category: overrideForm.category,
            subcategory: overrideForm.subcategory || null,
            action: overrideForm.action,
            custom_description: overrideForm.custom_description || null,
          }),
        });
      }

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || "Erro ao salvar.");
      }

      if (isBulk) {
        const data = await res.json().catch(() => ({}));
        toast({
          title: "Classificação aplicada a todos os escritórios",
          description: `Criados: ${data.created ?? 0} • já existentes: ${data.skipped_existing ?? 0} • total de escritórios: ${data.total_offices ?? 0}.`,
        });
      } else {
        toast({ title: editingOverride ? "Override atualizado" : "Override criado" });
      }

      setOverrideDialogOpen(false);
      await loadOverrides(overrideFilterOffice);
    } catch (err: any) {
      toast({ title: "Erro", description: err.message, variant: "destructive" });
    } finally {
      setSavingOverride(false);
    }
  };

  /**
   * Remove um override. Se o usuário confirmar, remove de todos os escritórios
   * (bulk) — usando mesma category+subcategory+action. Caso contrário, só do
   * escritório do registro clicado.
   */
  const handleDeleteOverride = async (ov: ClassificationOverride) => {
    const applyToAll = confirm(
      `Remover "${ov.category}${ov.subcategory ? " › " + ov.subcategory : ""}" de TODOS os escritórios?\n\n` +
        `OK = remover de todos\nCancelar = remover só deste escritório`
    );
    try {
      let res: Response;
      if (applyToAll) {
        const params = new URLSearchParams({
          category: ov.category,
          action: ov.action,
        });
        if (ov.subcategory) params.set("subcategory", ov.subcategory);
        res = await apiFetch(
          `/api/v1/publications/classification-overrides/bulk?${params.toString()}`,
          { method: "DELETE" }
        );
      } else {
        res = await apiFetch(
          `/api/v1/publications/classification-overrides/${ov.id}`,
          { method: "DELETE" }
        );
      }
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || "Erro ao remover.");
      }
      toast({ title: "Override removido" });
      await loadOverrides(overrideFilterOffice);
    } catch (err: any) {
      toast({ title: "Erro", description: err.message, variant: "destructive" });
    }
  };

  const openBulkDialog = () => {
    setBulkForm({
      mode: "apply",
      category: "",
      subcategory: "",
      action: "exclude",
      custom_description: "",
    });
    setBulkDialogOpen(true);
  };

  const handleBulkSubmit = async () => {
    if (!bulkForm.category) {
      toast({ title: "Selecione uma categoria", variant: "destructive" });
      return;
    }
    const subcategory = bulkForm.subcategory || null;

    const confirmMsg =
      bulkForm.mode === "apply"
        ? `Aplicar override "${bulkForm.action === "exclude" ? "Excluir" : "Adicionar customizada"}" da classificação "${bulkForm.category}${subcategory ? " › " + subcategory : ""}" a TODOS os escritórios?`
        : `Remover override da classificação "${bulkForm.category}${subcategory ? " › " + subcategory : ""}" de TODOS os escritórios? Isso não pode ser desfeito.`;
    if (!confirm(confirmMsg)) return;

    setBulkBusy(true);
    try {
      if (bulkForm.mode === "apply") {
        const res = await apiFetch("/api/v1/publications/classification-overrides/bulk", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            category: bulkForm.category,
            subcategory,
            action: bulkForm.action,
            custom_description: bulkForm.custom_description || null,
          }),
        });
        if (!res.ok) {
          const data = await res.json().catch(() => ({}));
          throw new Error(data.detail || "Erro ao aplicar override em massa.");
        }
        const data = await res.json();
        toast({
          title: "Overrides aplicados",
          description: `Criados: ${data.created}, já existentes (ignorados): ${data.skipped_existing}, total de escritórios: ${data.total_offices}.`,
        });
      } else {
        const params = new URLSearchParams({ category: bulkForm.category });
        if (subcategory) params.set("subcategory", subcategory);
        if (bulkForm.action) params.set("action", bulkForm.action);
        const res = await apiFetch(
          `/api/v1/publications/classification-overrides/bulk?${params.toString()}`,
          { method: "DELETE" }
        );
        if (!res.ok) {
          const data = await res.json().catch(() => ({}));
          throw new Error(data.detail || "Erro ao remover overrides em massa.");
        }
        const data = await res.json();
        toast({
          title: "Overrides removidos",
          description: `Removidos: ${data.deleted}.`,
        });
      }
      setBulkDialogOpen(false);
      if (overrideFilterOffice) await loadOverrides(overrideFilterOffice);
    } catch (err: any) {
      toast({ title: "Erro", description: err.message, variant: "destructive" });
    } finally {
      setBulkBusy(false);
    }
  };

  const handleToggleOverride = async (ov: ClassificationOverride) => {
    try {
      const res = await apiFetch(`/api/v1/publications/classification-overrides/${ov.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_active: !ov.is_active }),
      });
      if (!res.ok) throw new Error("Erro ao atualizar override.");
      toast({ title: ov.is_active ? "Override desativado" : "Override ativado" });
      await loadOverrides(overrideFilterOffice);
    } catch (err: any) {
      toast({ title: "Erro", description: err.message, variant: "destructive" });
    }
  };

  // ─── Render ────────────────────────────────────────────────────────────

  const priorityColor = (p: string) => {
    if (p === "High") return "destructive";
    if (p === "Low") return "outline";
    return "secondary";
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
            <Settings className="h-6 w-6" />
            Templates de Agendamento
          </h1>
          <p className="text-muted-foreground">
            Configure o que cada classificação gera como tarefa por escritório.
            O motor usa esses templates para pré-montar tarefas automaticamente.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={loadAll} disabled={loading}>
            <RefreshCw className={`mr-2 h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            Atualizar
          </Button>
          <Button size="sm" onClick={openCreate} disabled={loading}>
            <Plus className="mr-2 h-4 w-4" />
            Novo Template
          </Button>
        </div>
      </div>

      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Erro</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {/* Info card */}
      <Card className="border-blue-200 bg-blue-50/50">
        <CardContent className="pt-4 pb-3">
          <div className="flex gap-3 text-sm text-blue-900">
            <BookTemplate className="mt-0.5 h-4 w-4 flex-shrink-0 text-blue-600" />
            <div>
              <p className="font-medium">Como funciona o motor de agendamento</p>
              <p className="mt-0.5 text-blue-700">
                Após a busca, cada publicação é classificada pela IA (categoria +
                subcategoria). O motor procura o template que combina{" "}
                <strong>categoria + subcategoria + escritório responsável</strong> e
                monta o payload da tarefa automaticamente. O operador só precisa
                revisar e confirmar. Placeholders disponíveis:{" "}
                <code className="rounded bg-blue-100 px-1 text-xs">{"{cnj}"}</code>,{" "}
                <code className="rounded bg-blue-100 px-1 text-xs">
                  {"{publication_date}"}
                </code>
                ,{" "}
                <code className="rounded bg-blue-100 px-1 text-xs">
                  {"{description}"}
                </code>
                .
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-4">
        <div className="flex items-center gap-2">
          <Building2 className="h-4 w-4 text-muted-foreground" />
          <Select value={filterOffice} onValueChange={setFilterOffice}>
            <SelectTrigger className="w-[220px]">
              <SelectValue placeholder="Todos os escritórios" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Todos os escritórios</SelectItem>
              <SelectItem value="_global">✦ Publicações sem processo</SelectItem>
              {offices.map((o) => (
                <SelectItem key={o.external_id} value={String(o.external_id)}>
                  {o.path || o.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex items-center gap-2">
          <Tag className="h-4 w-4 text-muted-foreground" />
          <Select value={filterCategory} onValueChange={setFilterCategory}>
            <SelectTrigger className="w-[260px]">
              <SelectValue placeholder="Todas as categorias" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Todas as categorias</SelectItem>
              {categories.map((c) => (
                <SelectItem key={c.category} value={c.category}>
                  {c.category}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <div className="flex overflow-hidden rounded border">
            <button
              type="button"
              onClick={() => setViewMode("flat")}
              className={`flex items-center gap-1 px-3 py-1 text-xs transition-colors ${
                viewMode === "flat" ? "bg-primary text-primary-foreground" : "bg-background hover:bg-muted"
              }`}
              title="Lista de templates"
            >
              <List className="h-3 w-3" />
              Lista
            </button>
            <button
              type="button"
              onClick={() => setViewMode("by-office")}
              className={`flex items-center gap-1 border-l px-3 py-1 text-xs transition-colors ${
                viewMode === "by-office" ? "bg-primary text-primary-foreground" : "bg-background hover:bg-muted"
              }`}
              title="Cobertura por escritório"
            >
              <LayoutGrid className="h-3 w-3" />
              Por escritório
            </button>
          </div>
          <Badge variant="secondary">
            {viewMode === "flat"
              ? `${filteredTemplates.length} template${filteredTemplates.length !== 1 ? "s" : ""}`
              : `${coverageByOffice.length} escritório${coverageByOffice.length !== 1 ? "s" : ""}`}
          </Badge>
        </div>
      </div>

      {/* Legend + "only missing" toggle for coverage view */}
      {viewMode === "by-office" && (
        <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
          <span className="inline-flex items-center gap-1">
            <span className="inline-block h-2 w-2 rounded-full bg-emerald-500" />
            Coberto
          </span>
          <span className="inline-flex items-center gap-1">
            <span className="inline-block h-2 w-2 rounded-full bg-rose-500" />
            Faltando template
          </span>
          <label className="ml-auto flex cursor-pointer items-center gap-1.5">
            <input
              type="checkbox"
              checked={coverageOnlyMissing}
              onChange={(e) => setCoverageOnlyMissing(e.target.checked)}
              className="h-3.5 w-3.5 rounded"
            />
            Mostrar apenas classificações sem template
          </label>
        </div>
      )}

      {/* Flat table view */}
      {viewMode === "flat" && (
      <Card>
        <CardContent className="p-0">
          {loading ? (
            <div className="flex h-48 items-center justify-center gap-2 text-muted-foreground">
              <Loader2 className="h-5 w-5 animate-spin" />
              Carregando templates...
            </div>
          ) : filteredTemplates.length === 0 ? (
            <div className="flex h-48 flex-col items-center justify-center gap-2 text-muted-foreground">
              <Settings className="h-8 w-8 opacity-30" />
              <p>Nenhum template encontrado.</p>
              <Button variant="outline" size="sm" onClick={openCreate}>
                <Plus className="mr-2 h-4 w-4" />
                Criar primeiro template
              </Button>
            </div>
          ) : (
            <ScrollArea className="rounded-md">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-[180px]">Nome</TableHead>
                    <TableHead>Classificação</TableHead>
                    <TableHead>Escritório</TableHead>
                    <TableHead>Tipo / Subtipo</TableHead>
                    <TableHead>Responsável</TableHead>
                    <TableHead className="w-[80px]">Prazo</TableHead>
                    <TableHead className="w-[80px]">Prioridade</TableHead>
                    <TableHead className="w-[80px]">Status</TableHead>
                    <TableHead className="w-[90px]">Ações</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredTemplates.map((tmpl) => (
                    <TableRow
                      key={tmpl.id}
                      className={!tmpl.is_active ? "opacity-50" : ""}
                    >
                      <TableCell className="font-medium text-sm">
                        {tmpl.name}
                      </TableCell>
                      <TableCell className="text-xs">
                        <div className="font-medium">{tmpl.category}</div>
                        {tmpl.subcategory && tmpl.subcategory !== "-" && (
                          <div className="text-muted-foreground">
                            └ {tmpl.subcategory}
                          </div>
                        )}
                      </TableCell>
                      <TableCell className="text-xs">
                        {tmpl.office_external_id === null ? (
                          <div className="flex items-center gap-1 font-medium text-amber-700">
                            <ShieldAlert className="h-3 w-3" />
                            {tmpl.office_name ?? "Sem processo"}
                          </div>
                        ) : (
                          <div className="flex items-center gap-1">
                            <Building2 className="h-3 w-3 text-muted-foreground" />
                            {tmpl.office_name ?? tmpl.office_external_id}
                          </div>
                        )}
                      </TableCell>
                      <TableCell className="text-xs">
                        {tmpl.task_type_name && (
                          <div className="text-muted-foreground">
                            {tmpl.task_type_name}
                          </div>
                        )}
                        <div className="font-medium">
                          {tmpl.task_subtype_name ?? tmpl.task_subtype_external_id}
                        </div>
                      </TableCell>
                      <TableCell className="text-xs">
                        <div className="flex items-center gap-1">
                          <User className="h-3 w-3 text-muted-foreground" />
                          {tmpl.responsible_user_name ?? tmpl.responsible_user_external_id}
                        </div>
                      </TableCell>
                      <TableCell className="text-xs text-center">
                        {tmpl.due_business_days}d
                        <span className="ml-1 text-[10px] text-muted-foreground">
                          {tmpl.due_date_reference === "today" ? "(hoje)" : "(pub.)"}
                        </span>
                      </TableCell>
                      <TableCell>
                        <Badge
                          variant={priorityColor(tmpl.priority)}
                          className="text-xs"
                        >
                          {tmpl.priority}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <Badge
                          variant={tmpl.is_active ? "default" : "outline"}
                          className="cursor-pointer text-xs"
                          onClick={() => handleToggleActive(tmpl)}
                          title="Clique para ativar/desativar"
                        >
                          {tmpl.is_active ? "Ativo" : "Inativo"}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <div className="flex gap-1">
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-7 w-7 p-0"
                            onClick={() => openEdit(tmpl)}
                            title="Editar"
                          >
                            <Edit2 className="h-3.5 w-3.5" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-7 w-7 p-0 text-red-500 hover:text-red-700"
                            onClick={() => handleDelete(tmpl.id, tmpl.name)}
                            title="Remover"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </ScrollArea>
          )}
        </CardContent>
      </Card>
      )}

      {/* Coverage by Office view */}
      {viewMode === "by-office" && (
        <Card>
          <CardContent className="p-4">
            {loading ? (
              <div className="flex h-48 items-center justify-center gap-2 text-muted-foreground">
                <Loader2 className="h-5 w-5 animate-spin" />
                Carregando cobertura...
              </div>
            ) : coverageByOffice.length === 0 ? (
              <div className="flex h-24 items-center justify-center text-sm text-muted-foreground">
                Nenhum escritório encontrado para os filtros atuais.
              </div>
            ) : (
              <div className="space-y-4">
                {coverageByOffice.map((entry) => {
                  const visibleSlots = coverageOnlyMissing
                    ? entry.slots.filter((s) => !s.covered)
                    : entry.slots;
                  if (coverageOnlyMissing && visibleSlots.length === 0) return null;

                  const coveragePct =
                    entry.total > 0
                      ? Math.round((entry.coveredCount / entry.total) * 100)
                      : 0;

                  // Agrupa slots visíveis por categoria para renderizar
                  const slotsByCategory = new Map<
                    string,
                    typeof entry.slots
                  >();
                  visibleSlots.forEach((s) => {
                    const arr = slotsByCategory.get(s.category) || [];
                    arr.push(s);
                    slotsByCategory.set(s.category, arr);
                  });

                  return (
                    <div key={entry.office.external_id} className="rounded-lg border">
                      {/* Office header */}
                      <div className="flex items-center justify-between border-b bg-muted/40 px-4 py-3">
                        <div className="flex items-center gap-2">
                          <Building2 className="h-4 w-4 text-muted-foreground" />
                          <h3 className="text-sm font-semibold">
                            {entry.office.path || entry.office.name}
                          </h3>
                        </div>
                        <div className="flex items-center gap-3 text-xs">
                          <span className="text-emerald-700">
                            {entry.coveredCount} coberto{entry.coveredCount !== 1 ? "s" : ""}
                          </span>
                          <span className="text-rose-600">
                            {entry.missingCount} faltando
                          </span>
                          <div className="flex items-center gap-1.5">
                            <div className="h-2 w-24 overflow-hidden rounded-full bg-muted">
                              <div
                                className={`h-full transition-all ${
                                  coveragePct === 100
                                    ? "bg-emerald-500"
                                    : coveragePct >= 50
                                    ? "bg-amber-500"
                                    : "bg-rose-500"
                                }`}
                                style={{ width: `${coveragePct}%` }}
                              />
                            </div>
                            <span className="w-10 text-right font-mono text-[11px] text-muted-foreground">
                              {coveragePct}%
                            </span>
                          </div>
                        </div>
                      </div>

                      {/* Slots grouped by category */}
                      <div className="divide-y">
                        {Array.from(slotsByCategory.entries()).map(
                          ([category, slots]) => (
                            <div key={category} className="p-3">
                              <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                                <Tag className="h-3 w-3" />
                                {category}
                              </div>
                              <div className="flex flex-wrap gap-1.5">
                                {slots.map((s) => {
                                  const subLabel =
                                    s.subcategory === "-" ? "—" : s.subcategory;
                                  if (s.covered && s.template) {
                                    return (
                                      <button
                                        key={s.subcategory}
                                        type="button"
                                        onClick={() => openEdit(s.template!)}
                                        className="inline-flex items-center gap-1 rounded-md border border-emerald-300 bg-emerald-50 px-2 py-1 text-xs text-emerald-800 transition-colors hover:bg-emerald-100"
                                        title={`Editar template "${s.template.name}"`}
                                      >
                                        <Check className="h-3 w-3" />
                                        {subLabel}
                                      </button>
                                    );
                                  }
                                  return (
                                    <button
                                      key={s.subcategory}
                                      type="button"
                                      onClick={() => {
                                        setEditingId(null);
                                        setForm({
                                          category: s.category,
                                          subcategory: s.subcategory === "-" ? "" : s.subcategory,
                                          office_external_id: String(entry.office.external_id),
                                          taskBlocks: [{ ...BLANK_TASK_BLOCK }],
                                        });
                                        setDialogOpen(true);
                                      }}
                                      className="inline-flex items-center gap-1 rounded-md border border-dashed border-rose-300 bg-rose-50/60 px-2 py-1 text-xs text-rose-700 transition-colors hover:bg-rose-100"
                                      title="Criar template para esta combinação"
                                    >
                                      <Plus className="h-3 w-3" />
                                      {subLabel}
                                    </button>
                                  );
                                })}
                              </div>
                            </div>
                          )
                        )}
                        {slotsByCategory.size === 0 && (
                          <div className="p-4 text-center text-xs text-muted-foreground">
                            Todas as classificações cobertas para este escritório.
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* ─── Classification Overrides Section ───────────────────────────── */}
      <Separator />
      <div>
        <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="flex items-center gap-2 text-lg font-semibold">
              <ShieldAlert className="h-5 w-5 text-amber-600" />
              Ajustes de Classificação
            </h2>
            <p className="text-sm text-muted-foreground">
              Adicione classificações personalizadas ou exclua classificações existentes — em
              todos os escritórios de uma vez ou só em um específico. Aplicado nas próximas
              classificações da IA.
            </p>
          </div>
          <div className="flex gap-2">
            <Button size="sm" onClick={openAddClassification}>
              <Plus className="mr-2 h-4 w-4" />
              Adicionar classificação
            </Button>
            <Button variant="outline" size="sm" onClick={openExcludeClassification}>
              <ShieldAlert className="mr-2 h-4 w-4" />
              Excluir classificação
            </Button>
          </div>
        </div>

        {/* Filter: escopo da tabela */}
        <div className="mb-4 flex items-center gap-3">
          <Building2 className="h-4 w-4 text-muted-foreground" />
          <Select
            value={overrideFilterOffice || "all"}
            onValueChange={(v) => {
              setOverrideFilterOffice(v === "all" ? "" : v);
            }}
          >
            <SelectTrigger className="w-[320px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Todos os escritórios</SelectItem>
              {offices.map((o) => (
                <SelectItem key={o.external_id} value={String(o.external_id)}>
                  {o.path || o.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {/* Overrides table */}
        <Card>
          <CardContent className="p-0">
            {loadingOverrides ? (
              <div className="flex h-24 items-center justify-center gap-2 text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                Carregando...
              </div>
            ) : (() => {
              // Filtro client-side pelo escritório escolhido na Select acima.
              const visibleOverrides = overrideFilterOffice
                ? overrides.filter(
                    (o) => String(o.office_external_id) === overrideFilterOffice
                  )
                : overrides;

              if (visibleOverrides.length === 0) {
                return (
                  <div className="flex h-24 flex-col items-center justify-center gap-2 text-sm text-muted-foreground">
                    <p>
                      {overrideFilterOffice
                        ? "Nenhum ajuste configurado para este escritório."
                        : "Nenhum ajuste configurado."}
                    </p>
                  </div>
                );
              }

              return (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Escritório</TableHead>
                    <TableHead>Categoria</TableHead>
                    <TableHead>Subcategoria</TableHead>
                    <TableHead className="w-[140px]">Ação</TableHead>
                    <TableHead>Descrição personalizada</TableHead>
                    <TableHead className="w-[80px]">Status</TableHead>
                    <TableHead className="w-[80px]">Ações</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {visibleOverrides.map((ov) => {
                    const office = offices.find((o) => o.external_id === ov.office_external_id);
                    return (
                      <TableRow key={ov.id} className={!ov.is_active ? "opacity-50" : ""}>
                        <TableCell className="text-xs text-muted-foreground max-w-[220px] truncate">
                          {office?.path || office?.name || ov.office_external_id}
                        </TableCell>
                        <TableCell className="text-xs font-medium">{ov.category}</TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {ov.subcategory ?? <span className="italic">todas</span>}
                        </TableCell>
                        <TableCell>
                          <Badge
                            variant={ov.action === "exclude" ? "destructive" : "secondary"}
                            className="text-xs"
                          >
                            {ov.action === "exclude" ? "Excluir" : "Adicionar customizada"}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground max-w-[200px] truncate">
                          {ov.custom_description ?? "—"}
                        </TableCell>
                        <TableCell>
                          <Badge
                            variant={ov.is_active ? "default" : "outline"}
                            className="cursor-pointer text-xs"
                            onClick={() => handleToggleOverride(ov)}
                            title="Clique para ativar/desativar"
                          >
                            {ov.is_active ? "Ativo" : "Inativo"}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          <div className="flex gap-1">
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-7 w-7 p-0"
                              onClick={() => openEditOverride(ov)}
                              title="Editar"
                            >
                              <Edit2 className="h-3.5 w-3.5" />
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-7 w-7 p-0 text-red-500 hover:text-red-700"
                              onClick={() => handleDeleteOverride(ov)}
                              title="Remover (pergunta se é em todos)"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
              );
            })()}
          </CardContent>
        </Card>
      </div>

      {/* Bulk override dialog */}
      <Dialog open={bulkDialogOpen} onOpenChange={setBulkDialogOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>Aplicar/Remover override em massa</DialogTitle>
            <DialogDescription>
              Adicione ou remova uma regra de classificação em <strong>todos os escritórios</strong> de uma vez.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 pt-2">
            <div className="grid gap-1.5">
              <Label>Operação</Label>
              <Select
                value={bulkForm.mode}
                onValueChange={(v) => setBulkForm((p) => ({ ...p, mode: v as "apply" | "remove" }))}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="apply">Aplicar (criar override)</SelectItem>
                  <SelectItem value="remove">Remover (apagar overrides)</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="grid gap-1.5">
                <Label>Categoria *</Label>
                <Select
                  value={bulkForm.category}
                  onValueChange={(v) => setBulkForm((p) => ({ ...p, category: v, subcategory: "" }))}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Selecione..." />
                  </SelectTrigger>
                  <SelectContent>
                    {categories.map((c) => (
                      <SelectItem key={c.category} value={c.category}>
                        {c.category}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="grid gap-1.5">
                <Label>Subcategoria</Label>
                <Select
                  value={bulkForm.subcategory || "__all__"}
                  onValueChange={(v) =>
                    setBulkForm((p) => ({ ...p, subcategory: v === "__all__" ? "" : v }))
                  }
                  disabled={!bulkForm.category}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Todas" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__all__">Todas (categoria inteira)</SelectItem>
                    {bulkSubcategories.map((s) => (
                      <SelectItem key={s} value={s}>
                        {s}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            <div className="grid gap-1.5">
              <Label>Ação do override</Label>
              <Select
                value={bulkForm.action}
                onValueChange={(v) =>
                  setBulkForm((p) => ({ ...p, action: v as "exclude" | "include_custom" }))
                }
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="exclude">Excluir</SelectItem>
                  <SelectItem value="include_custom">Adicionar customizada</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {bulkForm.mode === "apply" && bulkForm.action === "include_custom" && (
              <div className="grid gap-1.5">
                <Label>Descrição personalizada</Label>
                <Input
                  value={bulkForm.custom_description}
                  onChange={(e) =>
                    setBulkForm((p) => ({ ...p, custom_description: e.target.value }))
                  }
                  placeholder="Texto que será usado no prompt da IA"
                />
              </div>
            )}

            <div className="rounded border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
              {bulkForm.mode === "apply"
                ? "Este override será criado em TODOS os escritórios. Escritórios que já têm essa combinação serão ignorados."
                : "Todos os overrides que baterem com essa combinação serão REMOVIDOS de todos os escritórios. Esta ação não pode ser desfeita."}
            </div>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setBulkDialogOpen(false)} disabled={bulkBusy}>
              Cancelar
            </Button>
            <Button
              onClick={handleBulkSubmit}
              disabled={bulkBusy || !bulkForm.category}
              variant={bulkForm.mode === "remove" ? "destructive" : "default"}
            >
              {bulkBusy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
              {bulkForm.mode === "apply" ? "Aplicar a todos" : "Remover de todos"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Override create/edit dialog */}
      <Dialog open={overrideDialogOpen} onOpenChange={setOverrideDialogOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>
              {editingOverride
                ? "Editar ajuste"
                : overrideForm.action === "exclude"
                ? "Excluir classificação"
                : "Adicionar classificação"}
            </DialogTitle>
            <DialogDescription>
              {editingOverride
                ? "Ajuste a descrição ou status deste registro."
                : overrideForm.action === "exclude"
                ? "Remove a classificação selecionada do prompt da IA."
                : "Inclui uma classificação personalizada no prompt da IA."}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 pt-2">
            {/* Escopo — aplicar em todos os escritórios ou em um específico */}
            {!editingOverride && (
              <div className="grid gap-1.5">
                <Label>Escopo *</Label>
                <Select
                  value={overrideForm.scope}
                  onValueChange={(v) =>
                    setOverrideForm((p) => ({ ...p, scope: v }))
                  }
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">Todos os escritórios</SelectItem>
                    {offices.map((o) => (
                      <SelectItem key={o.external_id} value={String(o.external_id)}>
                        Só em: {o.path || o.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}

            {/* Categoria + Subcategoria */}
            <div className="grid grid-cols-2 gap-4">
              <div className="grid gap-1.5">
                <Label>Categoria *</Label>
                <Select
                  value={overrideForm.category}
                  onValueChange={(v) =>
                    setOverrideForm((p) => ({ ...p, category: v, subcategory: "" }))
                  }
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Selecione..." />
                  </SelectTrigger>
                  <SelectContent>
                    {categories.map((c) => (
                      <SelectItem key={c.category} value={c.category}>
                        {c.category}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="grid gap-1.5">
                <Label>Subcategoria</Label>
                <Select
                  value={overrideForm.subcategory || "_all"}
                  onValueChange={(v) =>
                    setOverrideForm((p) => ({ ...p, subcategory: v === "_all" ? "" : v }))
                  }
                  disabled={overrideCategorySubcategories.length === 0}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Todas" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="_all">(todas as subcategorias)</SelectItem>
                    {overrideCategorySubcategories.map((s) => (
                      <SelectItem key={s} value={s}>
                        {s}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            {/* Ação */}
            <div className="grid gap-1.5">
              <Label>Ação *</Label>
              <Select
                value={overrideForm.action}
                onValueChange={(v) =>
                  setOverrideForm((p) => ({
                    ...p,
                    action: v as "exclude" | "include_custom",
                  }))
                }
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="exclude">
                    Excluir — remover esta classificação do prompt para este escritório
                  </SelectItem>
                  <SelectItem value="include_custom">
                    Adicionar customizada — incluir nova classificação com descrição personalizada
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>

            {/* Custom description (only for include_custom) */}
            {overrideForm.action === "include_custom" && (
              <div className="grid gap-1.5">
                <Label>Descrição personalizada</Label>
                <Textarea
                  rows={3}
                  placeholder="Descreva a classificação customizada que será adicionada ao prompt..."
                  value={overrideForm.custom_description}
                  onChange={(e) =>
                    setOverrideForm((p) => ({ ...p, custom_description: e.target.value }))
                  }
                />
              </div>
            )}

            {/* is_active */}
            <div className="flex items-center gap-2">
              <input
                id="ov-active"
                type="checkbox"
                checked={overrideForm.is_active}
                onChange={(e) =>
                  setOverrideForm((p) => ({ ...p, is_active: e.target.checked }))
                }
                className="h-4 w-4 rounded"
              />
              <Label htmlFor="ov-active" className="cursor-pointer">
                Override ativo
              </Label>
            </div>
          </div>

          <div className="mt-4 flex justify-end gap-3">
            <Button
              variant="outline"
              onClick={() => setOverrideDialogOpen(false)}
              disabled={savingOverride}
            >
              Cancelar
            </Button>
            <Button onClick={handleSaveOverride} disabled={savingOverride}>
              {savingOverride ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Check className="mr-2 h-4 w-4" />
              )}
              {editingOverride
                ? "Salvar alterações"
                : overrideForm.scope === "all"
                ? "Aplicar a todos os escritórios"
                : "Aplicar"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Create / Edit Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-h-[90vh] max-w-2xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>
              {editingId ? "Editar Template" : "Novo Template de Agendamento"}
            </DialogTitle>
            <DialogDescription>
              {editingId
                ? "Edite os dados deste template de tarefa."
                : "Defina quais tarefas serão criadas automaticamente no Legal One para esta classificação. Você pode adicionar várias tarefas para a mesma classificação."}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-5 pt-2">
            {/* ── Classificação (compartilhada entre todos os blocos) ── */}
            <div>
              <p className="mb-3 text-sm font-semibold">Critério de classificação</p>
              <div className="grid grid-cols-2 gap-4">
                <div className="grid gap-1.5">
                  <Label>Categoria *</Label>
                  <Select
                    value={form.category}
                    onValueChange={(v) => {
                      setField("category", v);
                      setField("subcategory", "");
                    }}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="Selecione..." />
                    </SelectTrigger>
                    <SelectContent>
                      {categories.map((c) => (
                        <SelectItem key={c.category} value={c.category}>
                          {c.category}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="grid gap-1.5">
                  <Label>Subcategoria</Label>
                  <Select
                    value={form.subcategory || "_none"}
                    onValueChange={(v) =>
                      setField("subcategory", v === "_none" ? "" : v)
                    }
                    disabled={categorySubcategories.length === 0}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="Qualquer subcategoria" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="_none">(qualquer / sem subcategoria)</SelectItem>
                      {categorySubcategories.map((s) => (
                        <SelectItem key={s} value={s}>{s}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>
            </div>

            {/* Escritório */}
            <div className="grid gap-1.5">
              <Label>Escritório responsável</Label>
              <Select
                value={form.office_external_id || "_global"}
                onValueChange={(v) => setField("office_external_id", v)}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Selecione o escritório..." />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="_global">
                    ✦ Publicações sem processo (template global)
                  </SelectItem>
                  {offices.map((o) => (
                    <SelectItem key={o.external_id} value={String(o.external_id)}>
                      {o.path || o.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {(form.office_external_id === "_global" || form.office_external_id === "") && (
                <p className="text-xs text-amber-600">
                  Template global: será usado para publicações sem processo/escritório vinculado.
                </p>
              )}
            </div>

            <Separator />

            {/* ── Blocos de tarefa ── */}
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <p className="text-sm font-semibold">
                  Tarefas a criar{" "}
                  <span className="font-normal text-muted-foreground">
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
                const blockSubtypes = getSubtypesForBlock(idx);
                return (
                  <div
                    key={idx}
                    className="rounded-lg border bg-muted/20 p-4 space-y-4"
                  >
                    {/* Block header */}
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                          Tarefa {idx + 1}
                        </p>
                        {editingId && idx === 0 && (
                          <Badge variant="outline" className="text-[10px] h-4 px-1.5">
                            Editando existente
                          </Badge>
                        )}
                        {editingId && idx > 0 && (
                          <Badge variant="secondary" className="text-[10px] h-4 px-1.5">
                            Nova
                          </Badge>
                        )}
                      </div>
                      {/* Em edição, não deixa remover o bloco original — use o
                          botão de excluir na lista principal para isso. */}
                      {form.taskBlocks.length > 1 && !(editingId && idx === 0) && (
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

                    {/* Tipo / Subtipo */}
                    <div className="grid grid-cols-2 gap-3">
                      <div className="grid gap-1.5">
                        <Label className="text-xs">Tipo de tarefa</Label>
                        <Select
                          value={block.task_type_external_id}
                          onValueChange={(v) => {
                            setBlockField(idx, "task_type_external_id", v);
                            setBlockField(idx, "task_subtype_external_id", "");
                          }}
                        >
                          <SelectTrigger className="h-8 text-sm">
                            <SelectValue placeholder="Selecione..." />
                          </SelectTrigger>
                          <SelectContent>
                            {taskTypes.map((tt) => (
                              <SelectItem key={tt.external_id} value={String(tt.external_id)}>
                                {tt.name}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                      <div className="grid gap-1.5">
                        <Label className="text-xs">Subtipo de tarefa *</Label>
                        <Select
                          value={block.task_subtype_external_id}
                          onValueChange={(v) => setBlockField(idx, "task_subtype_external_id", v)}
                          disabled={blockSubtypes.length === 0}
                        >
                          <SelectTrigger className="h-8 text-sm">
                            <SelectValue placeholder="Selecione..." />
                          </SelectTrigger>
                          <SelectContent>
                            {blockSubtypes.map((s) => (
                              <SelectItem key={s.external_id} value={String(s.external_id)}>
                                {s.name}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                    </div>

                    {/* Responsável */}
                    <div className="grid gap-1.5">
                      <Label className="text-xs">Usuário responsável *</Label>
                      <Select
                        value={block.responsible_user_external_id}
                        onValueChange={(v) => setBlockField(idx, "responsible_user_external_id", v)}
                      >
                        <SelectTrigger className="h-8 text-sm">
                          <SelectValue placeholder="Selecione o usuário..." />
                        </SelectTrigger>
                        <SelectContent>
                          {users.map((u) => (
                            <SelectItem key={u.external_id} value={String(u.external_id)}>
                              {u.name}
                              {u.email && (
                                <span className="ml-1 text-xs text-muted-foreground">
                                  ({u.email})
                                </span>
                              )}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>

                    {/* Prazo, Referência e Prioridade */}
                    <div className="grid grid-cols-3 gap-3">
                      <div className="grid gap-1.5">
                        <Label className="text-xs">Prazo (dias úteis)</Label>
                        <Input
                          type="number"
                          min={0}
                          max={365}
                          value={block.due_business_days}
                          onChange={(e) => setBlockField(idx, "due_business_days", e.target.value)}
                          className="h-8 text-sm"
                        />
                      </div>
                      <div className="grid gap-1.5">
                        <Label className="text-xs">Contar a partir de</Label>
                        <Select
                          value={block.due_date_reference || "publication"}
                          onValueChange={(v) => setBlockField(idx, "due_date_reference", v)}
                        >
                          <SelectTrigger className="h-8 text-sm">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="publication">Data da publicação</SelectItem>
                            <SelectItem value="today">Data atual (hoje)</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                      <div className="grid gap-1.5">
                        <Label className="text-xs">Prioridade</Label>
                        <Select
                          value={block.priority}
                          onValueChange={(v) => setBlockField(idx, "priority", v)}
                        >
                          <SelectTrigger className="h-8 text-sm">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="Low">Baixa</SelectItem>
                            <SelectItem value="Normal">Normal</SelectItem>
                            <SelectItem value="High">Alta</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                    </div>

                    {/* Textos */}
                    <div className="grid gap-2">
                      <p className="text-xs text-muted-foreground">
                        Placeholders:{" "}
                        <code className="rounded bg-muted px-1">{"{cnj}"}</code>{" "}
                        <code className="rounded bg-muted px-1">{"{publication_date}"}</code>{" "}
                        <code className="rounded bg-muted px-1">{"{description}"}</code>
                      </p>
                      <div className="grid gap-1.5">
                        <Label className="text-xs">Descrição da tarefa</Label>
                        <Textarea
                          rows={2}
                          placeholder="Publicação judicial referente ao processo {cnj}..."
                          value={block.description_template}
                          onChange={(e) => setBlockField(idx, "description_template", e.target.value)}
                          className="text-sm"
                        />
                      </div>
                      <div className="grid gap-1.5">
                        <Label className="text-xs">Observações (notas)</Label>
                        <Textarea
                          rows={2}
                          placeholder="Opcional — aparece no campo Notas da tarefa."
                          value={block.notes_template}
                          onChange={(e) => setBlockField(idx, "notes_template", e.target.value)}
                          className="text-sm"
                        />
                      </div>
                    </div>
                  </div>
                );
              })}

              {/* Add another task (bottom shortcut) */}
              <button
                type="button"
                onClick={addTaskBlock}
                className="w-full rounded-lg border border-dashed border-muted-foreground/30 py-2 text-xs text-muted-foreground hover:border-primary/50 hover:text-primary transition-colors flex items-center justify-center gap-1.5"
              >
                <Plus className="h-3.5 w-3.5" />
                Adicionar outra tarefa para esta classificação
              </button>
            </div>
          </div>

          {/* Footer buttons */}
          <div className="mt-4 flex justify-end gap-3">
            <Button
              variant="outline"
              onClick={() => setDialogOpen(false)}
              disabled={saving}
            >
              Cancelar
            </Button>
            <Button onClick={handleSave} disabled={saving}>
              {saving ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Check className="mr-2 h-4 w-4" />
              )}
              {editingId
                ? form.taskBlocks.length > 1
                  ? `Salvar alterações + criar ${form.taskBlocks.length - 1} nova${form.taskBlocks.length - 1 > 1 ? "s" : ""}`
                  : "Salvar alterações"
                : `Criar template (${form.taskBlocks.length} tarefa${form.taskBlocks.length > 1 ? "s" : ""})`}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default TaskTemplatesPage;
