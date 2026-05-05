import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, Pencil, Plus, Power, RotateCcw } from "lucide-react";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useToast } from "@/components/ui/use-toast";
import { apiFetch } from "@/lib/api-client";
import {
  createPrazosIniciaisTemplate,
  deletePrazosIniciaisTemplate,
  fetchPrazosIniciaisEnums,
  listPrazosIniciaisTemplates,
  updatePrazosIniciaisTemplate,
} from "@/services/api";
import {
  PrazoInicialEnums,
  PrazoInicialTaskTemplate,
  PrazoInicialTaskTemplateCreatePayload,
  PrazoInicialTaskTemplateFilters,
} from "@/types/api";

import { TemplateFormDialog } from "@/components/prazos-iniciais/TemplateFormDialog";

// ─── Tipos auxiliares (carregados de outros endpoints) ───────────────

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

// ─── Filtros iniciais ────────────────────────────────────────────────

const DEFAULT_FILTERS: PrazoInicialTaskTemplateFilters = {
  limit: 200,
  offset: 0,
};

// Sentinela usada nos <Select> pra representar "sem filtro" (o shadcn/ui
// Select não aceita value="" e o backend usa "" pra filtrar NULLs, então
// usamos "__all__" como chave de UI, convertida antes do fetch).
const ALL = "__all__";
// Sentinela pra valor NULL (genérico/global) — o backend usa "" ou 0.
const NULL_VALUE = "__null__";

// ─── Página ─────────────────────────────────────────────────────────

export default function PrazosIniciaisTemplatesAdminPage() {
  const { toast } = useToast();

  // Dados auxiliares
  const [enums, setEnums] = useState<PrazoInicialEnums | null>(null);
  const [offices, setOffices] = useState<OfficeOption[]>([]);
  const [taskTypes, setTaskTypes] = useState<TaskTypeOption[]>([]);
  const [users, setUsers] = useState<UserOption[]>([]);
  const [supportSquads, setSupportSquads] = useState<Array<{ id: number; name: string; office_external_id: number | null }>>([]);

  // Estado da listagem
  const [templates, setTemplates] = useState<PrazoInicialTaskTemplate[]>([]);
  const [totalCount, setTotalCount] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const [filters, setFilters] = useState<PrazoInicialTaskTemplateFilters>(
    DEFAULT_FILTERS,
  );

  // UI filters (antes de aplicar — permitem "__all__" / "__null__")
  const [uiTipo, setUiTipo] = useState<string>(ALL);
  const [uiNatureza, setUiNatureza] = useState<string>(ALL);
  const [uiOffice, setUiOffice] = useState<string>(ALL);
  const [uiIsActive, setUiIsActive] = useState<string>("true");

  // Dialog state
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingTemplate, setEditingTemplate] =
    useState<PrazoInicialTaskTemplate | null>(null);

  // ─── Load auxiliares ──────────────────────────────────────────────

  const loadAuxData = async () => {
    try {
      const [enumsData, officesRes, taskRes, usersRes, sqRes] = await Promise.all([
        fetchPrazosIniciaisEnums(),
        apiFetch("/api/v1/offices"),
        apiFetch("/api/v1/tasks/task-creation-data"),
        apiFetch("/api/v1/users/with-squads"),
        apiFetch("/api/v1/squads?kind=support"),
      ]);
      if (!officesRes.ok || !taskRes.ok || !usersRes.ok) {
        throw new Error("Falha carregando dados auxiliares.");
      }
      const officesJson = (await officesRes.json()) as OfficeOption[];
      const taskJson = await taskRes.json();
      const usersJson = (await usersRes.json()) as UserOption[];

      setEnums(enumsData);
      setOffices(officesJson);
      setTaskTypes(taskJson.task_types as TaskTypeOption[]);
      setUsers(usersJson);
      if (sqRes.ok) {
        const sqJson = await sqRes.json();
        setSupportSquads(sqJson.map((s: any) => ({
          id: s.id,
          name: s.name,
          office_external_id: s.office_external_id,
        })));
      }
    } catch (err: unknown) {
      toast({
        title: "Erro ao carregar dados",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    }
  };

  // ─── Load templates ───────────────────────────────────────────────

  const loadTemplates = async (f: PrazoInicialTaskTemplateFilters) => {
    setIsLoading(true);
    try {
      const res = await listPrazosIniciaisTemplates(f);
      setTemplates(res.items);
      setTotalCount(res.total);
    } catch (err: unknown) {
      toast({
        title: "Erro ao listar templates",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadAuxData();
  }, []);

  useEffect(() => {
    loadTemplates(filters);
  }, [filters]);

  // ─── Aplicar filtros UI → backend ─────────────────────────────────

  const applyFilters = () => {
    const next: PrazoInicialTaskTemplateFilters = { limit: 200, offset: 0 };
    if (uiTipo !== ALL) next.tipo_prazo = uiTipo;
    if (uiNatureza !== ALL) {
      next.natureza_aplicavel = uiNatureza === NULL_VALUE ? "" : uiNatureza;
    }
    if (uiOffice !== ALL) {
      next.office_external_id = uiOffice === NULL_VALUE ? 0 : Number(uiOffice);
    }
    if (uiIsActive !== ALL) {
      next.is_active = uiIsActive === "true";
    }
    setFilters(next);
  };

  const clearFilters = () => {
    setUiTipo(ALL);
    setUiNatureza(ALL);
    setUiOffice(ALL);
    setUiIsActive("true");
    setFilters({ ...DEFAULT_FILTERS, is_active: true });
  };

  // ─── CRUD actions ─────────────────────────────────────────────────

  const handleCreate = async (payload: PrazoInicialTaskTemplateCreatePayload) => {
    await createPrazosIniciaisTemplate(payload);
    toast({ title: "Template criado" });
    setDialogOpen(false);
    setEditingTemplate(null);
    loadTemplates(filters);
  };

  const handleUpdate = async (
    templateId: number,
    payload: Partial<PrazoInicialTaskTemplateCreatePayload>,
  ) => {
    await updatePrazosIniciaisTemplate(templateId, payload);
    toast({ title: "Template atualizado" });
    setDialogOpen(false);
    setEditingTemplate(null);
    loadTemplates(filters);
  };

  const handleDelete = async (tpl: PrazoInicialTaskTemplate) => {
    if (
      !confirm(
        `Desativar template "${tpl.name}"?\nEle deixa de casar novos intakes mas fica preservado pra auditoria.`,
      )
    ) {
      return;
    }
    try {
      await deletePrazosIniciaisTemplate(tpl.id);
      toast({ title: "Template desativado" });
      loadTemplates(filters);
    } catch (err: unknown) {
      toast({
        title: "Erro ao desativar",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    }
  };

  const handleReactivate = async (tpl: PrazoInicialTaskTemplate) => {
    try {
      await updatePrazosIniciaisTemplate(tpl.id, { is_active: true });
      toast({ title: "Template reativado" });
      loadTemplates(filters);
    } catch (err: unknown) {
      toast({
        title: "Erro ao reativar",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    }
  };

  // ─── Render ───────────────────────────────────────────────────────

  const officeOptions = useMemo(
    () =>
      [...offices].sort((a, b) =>
        (a.path || a.name).localeCompare(b.path || b.name),
      ),
    [offices],
  );

  return (
    <div className="container mx-auto p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2 text-sm text-muted-foreground mb-1">
            <Link to="/prazos-iniciais" className="hover:underline inline-flex items-center gap-1">
              <ArrowLeft className="h-3 w-3" />
              Prazos Iniciais
            </Link>
            <span>/</span>
            <span>Templates</span>
          </div>
          <h1 className="text-2xl font-bold">Templates de Prazos Iniciais</h1>
          <p className="text-muted-foreground text-sm">
            Configure quais tasks o sistema sugere pra cada combinação de{" "}
            <em>tipo de prazo</em>, <em>natureza</em> e <em>escritório</em>.
            Você pode cadastrar <strong>vários templates</strong> na mesma
            combinação — cada um vira uma sugestão separada no HITL.
          </p>
        </div>
        <Button
          onClick={() => {
            setEditingTemplate(null);
            setDialogOpen(true);
          }}
          disabled={!enums}
        >
          <Plus className="h-4 w-4 mr-2" />
          Novo template
        </Button>
      </div>

      {/* Filtros */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Filtros</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-5 gap-3">
            <div className="space-y-1">
              <Label className="text-xs">Tipo de prazo</Label>
              <Select value={uiTipo} onValueChange={setUiTipo}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL}>Todos</SelectItem>
                  {enums?.tipos_prazo.map((t) => (
                    <SelectItem key={t} value={t}>
                      {t}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1">
              <Label className="text-xs">Natureza</Label>
              <Select value={uiNatureza} onValueChange={setUiNatureza}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL}>Todas</SelectItem>
                  <SelectItem value={NULL_VALUE}>Genérica (sem natureza)</SelectItem>
                  {enums?.naturezas.map((n) => (
                    <SelectItem key={n} value={n}>
                      {n}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1">
              <Label className="text-xs">Escritório</Label>
              <Select value={uiOffice} onValueChange={setUiOffice}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL}>Todos</SelectItem>
                  <SelectItem value={NULL_VALUE}>Global (sem escritório)</SelectItem>
                  {officeOptions.map((o) => (
                    <SelectItem key={o.external_id} value={String(o.external_id)}>
                      {o.path || o.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1">
              <Label className="text-xs">Status</Label>
              <Select value={uiIsActive} onValueChange={setUiIsActive}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL}>Todos</SelectItem>
                  <SelectItem value="true">Ativos</SelectItem>
                  <SelectItem value="false">Inativos</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="flex items-end gap-2">
              <Button onClick={applyFilters} className="flex-1">
                Aplicar
              </Button>
              <Button variant="outline" size="icon" onClick={clearFilters} title="Limpar">
                <RotateCcw className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Tabela */}
      <Card>
        <CardHeader className="pb-3 flex-row items-center justify-between space-y-0">
          <CardTitle className="text-base">
            {isLoading ? "Carregando..." : `${totalCount} templates`}
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Nome</TableHead>
                <TableHead>Tipo / Subtipo</TableHead>
                <TableHead>Natureza</TableHead>
                <TableHead>Escritório</TableHead>
                <TableHead>Task (Legal One)</TableHead>
                <TableHead>Responsável</TableHead>
                <TableHead>Prazo</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Ações</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {templates.length === 0 && !isLoading && (
                <TableRow>
                  <TableCell colSpan={9} className="text-center text-muted-foreground py-8">
                    Nenhum template encontrado com os filtros atuais.
                  </TableCell>
                </TableRow>
              )}
              {templates.map((t) => (
                <TableRow key={t.id} className={t.is_active ? "" : "opacity-60"}>
                  <TableCell className="font-medium">{t.name}</TableCell>
                  <TableCell>
                    <div className="text-sm">{t.tipo_prazo}</div>
                    {t.subtipo && (
                      <div className="text-xs text-muted-foreground">{t.subtipo}</div>
                    )}
                  </TableCell>
                  <TableCell>
                    {t.natureza_aplicavel ? (
                      <Badge variant="secondary">{t.natureza_aplicavel}</Badge>
                    ) : (
                      <span className="text-xs text-muted-foreground italic">
                        Genérica
                      </span>
                    )}
                  </TableCell>
                  <TableCell>
                    {t.office_name ? (
                      <span className="text-sm">{t.office_name}</span>
                    ) : (
                      <span className="text-xs text-muted-foreground italic">Global</span>
                    )}
                  </TableCell>
                  <TableCell>
                    <span className="text-sm">
                      {t.task_subtype_name || `#${t.task_subtype_external_id}`}
                    </span>
                  </TableCell>
                  <TableCell>
                    <span className="text-sm">
                      {t.responsible_user_name ||
                        `#${t.responsible_user_external_id}`}
                    </span>
                  </TableCell>
                  <TableCell>
                    <span className="text-sm whitespace-nowrap">
                      {t.due_business_days}d úteis
                    </span>
                    <div className="text-xs text-muted-foreground whitespace-nowrap">
                      {t.due_date_reference}
                    </div>
                  </TableCell>
                  <TableCell>
                    {t.is_active ? (
                      <Badge variant="default">Ativo</Badge>
                    ) : (
                      <Badge variant="outline">Inativo</Badge>
                    )}
                  </TableCell>
                  <TableCell className="text-right space-x-1">
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => {
                        setEditingTemplate(t);
                        setDialogOpen(true);
                      }}
                    >
                      <Pencil className="h-3 w-3" />
                    </Button>
                    {t.is_active ? (
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => handleDelete(t)}
                        title="Desativar"
                      >
                        <Power className="h-3 w-3" />
                      </Button>
                    ) : (
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => handleReactivate(t)}
                        title="Reativar"
                      >
                        <RotateCcw className="h-3 w-3" />
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* Dialog */}
      {enums && dialogOpen && (
        <TemplateFormDialog
          open={dialogOpen}
          onOpenChange={(open) => {
            setDialogOpen(open);
            if (!open) setEditingTemplate(null);
          }}
          enums={enums}
          offices={officeOptions}
          taskTypes={taskTypes}
          users={users}
          supportSquads={supportSquads}
          template={editingTemplate}
          onCreate={handleCreate}
          onUpdate={handleUpdate}
        />
      )}
    </div>
  );
}
