/**
 * OfficeTemplateTree — arvore por escritorio com cobertura visual.
 *
 * Renderiza a arvore de classificacoes aplicavel ao escritorio (ja
 * filtrada por polo + versao ativa) e marca cada linha com:
 *   - ✅ tem template ativo (clica e edita)
 *   - ⚪ sem template (clica "+ adicionar")
 *   - 🟡 pendente de migracao v1->v2 (clica "Migrar")
 *
 * Backend: GET /api/v1/task-templates/coverage?office_external_id=N.
 * Resposta unica que ja traz arvore + templates ativos + pendentes.
 *
 * Acoes inline disparam callbacks que o pai (TaskTemplatesPage) usa
 * pra abrir o modal correto (criar / editar / migrar / desativar).
 */
import { useEffect, useMemo, useState } from "react";
import {
  CheckCircle2,
  CircleDashed,
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  Pencil,
  Plus,
  PowerOff,
  RefreshCw,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useToast } from "@/hooks/use-toast";
import { apiFetch } from "@/lib/api-client";

// ─── Types do payload do endpoint coverage ───────────────────────

export interface CoverageTemplateInfo {
  id: number;
  name: string;
  category: string;
  subcategory: string | null;
  task_subtype_name: string | null;
  task_type_name: string | null;
  responsible_user_name: string | null;
  due_business_days: number;
  priority: string;
  is_active: boolean;
  taxonomy_version: string;
  legacy_label: string | null;
  needs_taxonomy_review: boolean;
}

interface SubNode {
  name: string;
  templates: CoverageTemplateInfo[];
  pending_templates: CoverageTemplateInfo[];
}

interface CategoryNode {
  category: string;
  polo_scope: string | null;
  subcategories: SubNode[];
  category_only_templates: CoverageTemplateInfo[];
  category_only_pending: CoverageTemplateInfo[];
}

interface CoverageResponse {
  office: {
    external_id: number;
    name: string;
    path: string;
    polo_scope: string;
  };
  taxonomy: {
    active_version: string;
    template_driven_mode: boolean;
  };
  tree: CategoryNode[];
  summary: {
    total_categories: number;
    categories_with_template: number;
    categories_without_template: number;
    pending_review_total: number;
  };
}

export interface OfficeTemplateTreeProps {
  officeExternalId: number;
  /** Callback chamado quando o operador clica "+ adicionar" numa cat/sub. */
  onAddTemplate: (
    category: string,
    subcategory: string | null,
    officeExternalId: number,
    polo: string,
  ) => void;
  /** Callback chamado quando o operador clica "editar" num template ativo. */
  onEditTemplate: (template: CoverageTemplateInfo) => void;
  /** Callback chamado quando o operador clica "Migrar" num template pendente. */
  onMigrateTemplate: (template: CoverageTemplateInfo) => void;
  /** Quando muda algo no servidor (deactivate, etc.), pai pode forçar reload. */
  reloadKey?: number;
}

// ─── Helper: aciona desativacao via PUT — endpoint regular ──────

async function deactivateTemplate(templateId: number): Promise<void> {
  const res = await apiFetch(`/api/v1/task-templates/${templateId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ is_active: false }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(
      (typeof data?.detail === "string" && data.detail) ||
        "Falha ao desativar.",
    );
  }
}

// ─── Componente ─────────────────────────────────────────────────

export function OfficeTemplateTree({
  officeExternalId,
  onAddTemplate,
  onEditTemplate,
  onMigrateTemplate,
  reloadKey = 0,
}: OfficeTemplateTreeProps) {
  const { toast } = useToast();
  const [data, setData] = useState<CoverageResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [busyTemplateId, setBusyTemplateId] = useState<number | null>(null);

  const load = async () => {
    setLoading(true);
    try {
      const res = await apiFetch(
        `/api/v1/task-templates/coverage?office_external_id=${officeExternalId}`,
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = (await res.json()) as CoverageResponse;
      setData(json);
      // Default: expande categorias que tem pendência ou que tem
      // pelo menos 1 template (operador foca no que ja existe). Cats
      // totalmente vazias ficam recolhidas (cabem em "+ adicionar").
      const expandSet = new Set<string>();
      json.tree.forEach((c) => {
        const hasPending =
          c.category_only_pending.length > 0 ||
          c.subcategories.some((s) => s.pending_templates.length > 0);
        const hasTemplate =
          c.category_only_templates.length > 0 ||
          c.subcategories.some((s) => s.templates.length > 0);
        if (hasPending || hasTemplate) expandSet.add(c.category);
      });
      setExpanded(expandSet);
    } catch (err: any) {
      toast({
        title: "Falha carregando cobertura do escritório",
        description: err?.message || String(err),
        variant: "destructive",
      });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [officeExternalId, reloadKey]);

  const toggleExpanded = (cat: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(cat)) next.delete(cat);
      else next.add(cat);
      return next;
    });
  };

  const expandAll = () => {
    if (!data) return;
    setExpanded(new Set(data.tree.map((c) => c.category)));
  };
  const collapseAll = () => setExpanded(new Set());

  // Filtragem por busca (cat OR sub)
  const filteredTree = useMemo(() => {
    if (!data) return [] as CategoryNode[];
    const q = query.trim().toLowerCase();
    if (!q) return data.tree;
    return data.tree
      .map((c) => {
        if (c.category.toLowerCase().includes(q)) return c;
        const subs = c.subcategories.filter((s) =>
          s.name.toLowerCase().includes(q),
        );
        if (subs.length === 0) return null;
        return { ...c, subcategories: subs };
      })
      .filter((c): c is CategoryNode => c !== null);
  }, [data, query]);

  // Ao buscar, expande automaticamente as cats com matches
  useEffect(() => {
    if (query.trim() && data) {
      setExpanded(new Set(filteredTree.map((c) => c.category)));
    }
  }, [query, filteredTree, data]);

  const handleDeactivate = async (t: CoverageTemplateInfo) => {
    if (!confirm(`Desativar template "${t.name}"?`)) return;
    setBusyTemplateId(t.id);
    try {
      await deactivateTemplate(t.id);
      toast({ title: "Template desativado", description: t.name });
      await load();
    } catch (err: any) {
      toast({
        title: "Erro ao desativar",
        description: err?.message || String(err),
        variant: "destructive",
      });
    } finally {
      setBusyTemplateId(null);
    }
  };

  if (!data && !loading) {
    return null;
  }

  return (
    <div className="space-y-4">
      {/* Header com busca + recarregar */}
      <div className="flex items-center gap-2">
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Buscar categoria ou subcategoria..."
          className="max-w-md"
        />
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={expandAll}
          disabled={!data}
        >
          Expandir tudo
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={collapseAll}
          disabled={expanded.size === 0}
        >
          Recolher
        </Button>
        <div className="ml-auto">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={load}
            disabled={loading}
          >
            <RefreshCw
              className={`h-4 w-4 mr-1 ${loading ? "animate-spin" : ""}`}
            />
            Recarregar
          </Button>
        </div>
      </div>

      {/* Banner pre-config: polo do escritorio nao foi definido ainda.
          Operador medio nao tem acesso ao Admin pra setar polo, entao
          mostra um aviso amigavel pra ele saber pedir pra o admin. */}
      {data && data.office.polo_scope === "ambos" && (
        <Card className="border-amber-300 bg-amber-50 dark:bg-amber-950/30 dark:border-amber-700/50">
          <CardContent className="pt-4 pb-4 flex gap-3">
            <AlertTriangle className="h-5 w-5 text-amber-600 dark:text-amber-400 shrink-0 mt-0.5" />
            <div className="text-sm space-y-1">
              <div className="font-medium text-amber-900 dark:text-amber-200">
                Configuração de polo deste escritório está pendente
              </div>
              <p className="text-amber-800 dark:text-amber-200/80">
                A árvore abaixo está mostrando todas as categorias (ativo + passivo).
                Peça pra um administrador definir o polo deste escritório
                (passivo / ativo) — assim a lista fica mais enxuta.
              </p>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Resumo: contagens visiveis. Detalhes tecnicos (polo, taxonomia,
          modo enxuto) ficam num tooltip discreto pra nao confundir
          operador medio. */}
      {data && (
        <Card>
          <CardContent className="pt-4 pb-3 flex flex-wrap gap-3 items-center">
            <Badge variant="outline" className="border-green-300 text-green-800 dark:border-green-700 dark:text-green-300">
              <CheckCircle2 className="h-3 w-3 mr-1" />
              {data.summary.categories_with_template} cats com template
            </Badge>
            <Badge variant="outline">
              <CircleDashed className="h-3 w-3 mr-1" />
              {data.summary.categories_without_template} cats sem template
            </Badge>
            {data.summary.pending_review_total > 0 && (
              <Badge variant="outline" className="border-amber-300 text-amber-800 dark:border-amber-700 dark:text-amber-300">
                <AlertTriangle className="h-3 w-3 mr-1" />
                {data.summary.pending_review_total} precisa(m) atualizar
              </Badge>
            )}
            <span
              className="ml-auto text-xs text-muted-foreground cursor-help"
              title={
                `Polo: ${data.office.polo_scope}\n` +
                `Taxonomia: ${data.taxonomy.active_version}\n` +
                (data.taxonomy.template_driven_mode
                  ? "IA só vê categorias com template configurado"
                  : "IA vê a árvore completa")
              }
            >
              ℹ️ detalhes técnicos
            </span>
          </CardContent>
        </Card>
      )}

      {/* Árvore */}
      <div className="space-y-2">
        {filteredTree.length === 0 ? (
          <Card>
            <CardContent className="text-center text-sm text-muted-foreground py-12">
              {query
                ? "Nenhuma categoria corresponde à busca."
                : "Sem categorias na árvore aplicável."}
            </CardContent>
          </Card>
        ) : (
          filteredTree.map((cat) => (
            <CategoryRow
              key={cat.category}
              cat={cat}
              expanded={expanded.has(cat.category)}
              onToggle={() => toggleExpanded(cat.category)}
              onAddTemplate={(category, sub) =>
                onAddTemplate(category, sub, officeExternalId, data!.office.polo_scope)
              }
              onEditTemplate={onEditTemplate}
              onMigrateTemplate={onMigrateTemplate}
              onDeactivate={handleDeactivate}
              busyTemplateId={busyTemplateId}
            />
          ))
        )}
      </div>
    </div>
  );
}

// ─── Subcomponente: linha de categoria expansível ───────────────

interface CategoryRowProps {
  cat: CategoryNode;
  expanded: boolean;
  onToggle: () => void;
  onAddTemplate: (category: string, subcategory: string | null) => void;
  onEditTemplate: (t: CoverageTemplateInfo) => void;
  onMigrateTemplate: (t: CoverageTemplateInfo) => void;
  onDeactivate: (t: CoverageTemplateInfo) => Promise<void>;
  busyTemplateId: number | null;
}

function CategoryRow({
  cat,
  expanded,
  onToggle,
  onAddTemplate,
  onEditTemplate,
  onMigrateTemplate,
  onDeactivate,
  busyTemplateId,
}: CategoryRowProps) {
  const totalTemplates =
    cat.category_only_templates.length +
    cat.subcategories.reduce((acc, s) => acc + s.templates.length, 0);
  const totalPending =
    cat.category_only_pending.length +
    cat.subcategories.reduce((acc, s) => acc + s.pending_templates.length, 0);
  const totalSubs = cat.subcategories.length;
  const subsCovered = cat.subcategories.filter(
    (s) => s.templates.length > 0,
  ).length;

  return (
    <Card>
      <CardContent className="p-0">
        {/* Cabeçalho da categoria (clicável) */}
        <button
          type="button"
          onClick={onToggle}
          className="w-full flex items-center gap-2 px-4 py-3 hover:bg-accent/40 transition-colors text-left"
        >
          {expanded ? (
            <ChevronDown className="h-4 w-4 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-4 w-4 text-muted-foreground" />
          )}
          <span className="font-medium">{cat.category}</span>
          {totalSubs > 0 && (
            <span className="text-xs text-muted-foreground">
              ({subsCovered}/{totalSubs} subs)
            </span>
          )}
          <div className="ml-auto flex items-center gap-1">
            {totalPending > 0 && (
              <Badge
                variant="outline"
                className="text-xs border-amber-300 text-amber-800 dark:border-amber-700 dark:text-amber-300"
              >
                {totalPending} pendente
              </Badge>
            )}
            {totalTemplates > 0 ? (
              <Badge variant="secondary" className="text-xs">
                {totalTemplates} template{totalTemplates === 1 ? "" : "s"}
              </Badge>
            ) : (
              <Badge variant="outline" className="text-xs text-muted-foreground">
                sem template
              </Badge>
            )}
          </div>
        </button>

        {/* Conteúdo expandido */}
        {expanded && (
          <div className="border-t bg-muted/10 p-2 space-y-1">
            {/* Categoria sem subs */}
            {cat.subcategories.length === 0 && (
              <SubRow
                name="(categoria sem subcategoria)"
                italic
                templates={cat.category_only_templates}
                pendings={cat.category_only_pending}
                onAddTemplate={() => onAddTemplate(cat.category, null)}
                onEditTemplate={onEditTemplate}
                onMigrateTemplate={onMigrateTemplate}
                onDeactivate={onDeactivate}
                busyTemplateId={busyTemplateId}
              />
            )}
            {/* Subs */}
            {cat.subcategories.map((sub) => (
              <SubRow
                key={sub.name}
                name={sub.name}
                templates={sub.templates}
                pendings={sub.pending_templates}
                onAddTemplate={() => onAddTemplate(cat.category, sub.name)}
                onEditTemplate={onEditTemplate}
                onMigrateTemplate={onMigrateTemplate}
                onDeactivate={onDeactivate}
                busyTemplateId={busyTemplateId}
              />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ─── Subcomponente: linha de sub (✅/⚪/🟡 + ações) ────────────────

interface SubRowProps {
  name: string;
  italic?: boolean;
  templates: CoverageTemplateInfo[];
  pendings: CoverageTemplateInfo[];
  onAddTemplate: () => void;
  onEditTemplate: (t: CoverageTemplateInfo) => void;
  onMigrateTemplate: (t: CoverageTemplateInfo) => void;
  onDeactivate: (t: CoverageTemplateInfo) => Promise<void>;
  busyTemplateId: number | null;
}

function SubRow({
  name,
  italic,
  templates,
  pendings,
  onAddTemplate,
  onEditTemplate,
  onMigrateTemplate,
  onDeactivate,
  busyTemplateId,
}: SubRowProps) {
  const hasTemplate = templates.length > 0;
  const hasPending = pendings.length > 0;

  // Status icon + cor
  let StatusIcon = CircleDashed;
  let statusColor = "text-muted-foreground";
  if (hasPending) {
    StatusIcon = AlertTriangle;
    statusColor = "text-amber-500";
  } else if (hasTemplate) {
    StatusIcon = CheckCircle2;
    statusColor = "text-green-600";
  }

  return (
    <div className="rounded border bg-card px-3 py-2">
      <div className="flex items-start gap-2">
        <StatusIcon className={`h-4 w-4 mt-0.5 shrink-0 ${statusColor}`} />
        <div className="flex-1 min-w-0">
          <div className={`text-sm ${italic ? "italic text-muted-foreground" : ""}`}>
            {name}
          </div>
          {/* Templates ativos */}
          {templates.map((t) => (
            <div
              key={t.id}
              className="mt-1 flex items-center gap-2 text-xs text-muted-foreground"
            >
              <span className="truncate">
                <span className="font-medium text-foreground">{t.name}</span>
                {t.task_subtype_name && (
                  <>
                    {" · "}
                    {t.task_subtype_name}
                  </>
                )}
                {t.responsible_user_name && (
                  <>
                    {" · resp: "}
                    <span className="text-foreground">
                      {t.responsible_user_name}
                    </span>
                  </>
                )}
                {" · "}
                {t.due_business_days}d úteis
              </span>
              <div className="ml-auto flex items-center gap-1 shrink-0">
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-6 px-2"
                  onClick={() => onEditTemplate(t)}
                  disabled={busyTemplateId === t.id}
                >
                  <Pencil className="h-3 w-3 mr-1" />
                  editar
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-6 px-2 text-muted-foreground hover:text-destructive"
                  onClick={() => onDeactivate(t)}
                  disabled={busyTemplateId === t.id}
                >
                  <PowerOff className="h-3 w-3 mr-1" />
                  desativar
                </Button>
              </div>
            </div>
          ))}
          {/* Templates legacy precisando atualizar classificacao.
              Linguagem natural — "atualizar" em vez de "migrar pra v2". */}
          {pendings.map((t) => (
            <div
              key={t.id}
              className="mt-1 flex items-center gap-2 text-xs"
            >
              <Badge
                variant="outline"
                className="text-xs border-amber-300 text-amber-800 dark:border-amber-700 dark:text-amber-300"
              >
                precisa atualizar
              </Badge>
              <span className="truncate text-muted-foreground">
                {t.name}
                {t.legacy_label && (
                  <span className="ml-1 italic">
                    (classificação antiga: {t.legacy_label})
                  </span>
                )}
              </span>
              <div className="ml-auto flex items-center gap-1 shrink-0">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="h-6 px-2 border-amber-300 text-amber-800 hover:bg-amber-50 dark:border-amber-700 dark:text-amber-300 dark:hover:bg-amber-950/30"
                  onClick={() => onMigrateTemplate(t)}
                  disabled={busyTemplateId === t.id}
                >
                  Atualizar classificação
                </Button>
              </div>
            </div>
          ))}
          {/* Sem template e sem pendente: mostra "+ adicionar" em destaque. */}
          {!hasTemplate && !hasPending && (
            <div className="mt-1">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-6 px-2 text-xs"
                onClick={onAddTemplate}
              >
                <Plus className="h-3 w-3 mr-1" />
                adicionar template
              </Button>
            </div>
          )}
          {/* Ja tem template — link discreto pra operador avancado que
              quer adicionar uma SEGUNDA tarefa pra mesma classificacao
              (caso raro: multi-tarefa). Default: estagiario nao precisa
              ver isso em destaque. */}
          {hasTemplate && (
            <div className="mt-1">
              <button
                type="button"
                onClick={onAddTemplate}
                className="text-[11px] text-muted-foreground/70 hover:text-foreground hover:underline"
              >
                + criar uma segunda tarefa pra esta classificação
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default OfficeTemplateTree;
