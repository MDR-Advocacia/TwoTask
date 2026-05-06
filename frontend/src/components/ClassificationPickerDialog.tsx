/**
 * Modal pra adicionar VÁRIAS classificações de uma vez a um escritório.
 *
 * Substitui o fluxo um-por-um do form individual de override no regime
 * manual. Operador vê toda a taxonomia base agrupada por categoria, marca
 * as combinações que quer e elas viram overrides `include_custom` em
 * batch via POST /classification-overrides/bulk-for-office.
 *
 * Pré-existentes (já no escritório) aparecem desabilitadas + check
 * permanente, com label "já adicionada".
 */
import { useEffect, useMemo, useState } from "react";
import {
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  Search,
  X,
} from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useToast } from "@/hooks/use-toast";
import { apiFetch } from "@/lib/api-client";

const PAGE_SIZE_OPTIONS = [10, 25, 50, 100] as const;
const DEFAULT_PAGE_SIZE: (typeof PAGE_SIZE_OPTIONS)[number] = 10;

export interface CategoryEntry {
  category: string;
  subcategories: string[];
}

export interface ExistingClassification {
  category: string;
  subcategory: string | null;
}

export interface ClassificationPickerDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Escritório-alvo. */
  officeId: number;
  /** Nome (path) exibido no header. */
  officeName: string;
  /**
   * Lista de categorias mostradas no modal:
   *  - mode="include": taxonomia base (operador adiciona via include_custom)
   *  - mode="exclude": taxonomia efetiva ATUAL do escritório (operador
   *    marca o que quer remover via override exclude)
   */
  categories: CategoryEntry[];
  /**
   * Combinações que devem aparecer DESABILITADAS (já presentes):
   *  - mode="include": já existe no escritório (include_custom + templates)
   *  - mode="exclude": passar [] — taxonomia efetiva já filtra excluídas
   */
  existing: ExistingClassification[];
  /**
   * "include" (default) cria overrides include_custom; "exclude" cria
   * overrides exclude — ambos via /classification-overrides/bulk-for-office.
   */
  mode?: "include" | "exclude";
  /** Chamado depois que o batch sobe com sucesso. */
  onAdded?: (created: number, skipped: number) => void;
}

/**
 * Chave de identidade pra cada combinação. Usamos um separador ASCII improvável ("||") nos campos de
 * domínio. Cat/sub nunca contêm essa sequência.
 */
const keyOf = (cat: string, sub: string | null): string =>
  `${cat}||${sub ?? ""}`;

export function ClassificationPickerDialog({
  open,
  onOpenChange,
  officeId,
  officeName,
  categories,
  existing,
  mode = "include",
  onAdded,
}: ClassificationPickerDialogProps) {
  const { toast } = useToast();
  const isExcludeMode = mode === "exclude";

  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState("");
  const [submitting, setSubmitting] = useState(false);
  // Paginação por categoria — a taxonomia tem 30+ cats e estoura o
  // modal sem ela. Page é zero-indexed.
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] =
    useState<(typeof PAGE_SIZE_OPTIONS)[number]>(DEFAULT_PAGE_SIZE);

  // ─── Reset ao reabrir ─────────────────────────────────────────────
  useEffect(() => {
    if (open) {
      setSelected(new Set());
      setQuery("");
      // Por padrão deixa tudo recolhido — taxonomia pode ter 30+ cats e
      // o operador geralmente quer scrollar primeiro.
      setExpanded(new Set());
      setPage(0);
    }
  }, [open]);

  // ─── Set lookup das existentes ────────────────────────────────────
  const existingKeys = useMemo(() => {
    const s = new Set<string>();
    existing.forEach((e) => s.add(keyOf(e.category, e.subcategory || null)));
    // Também marca "categoria sem subcategoria" como existente quando
    // houver QUALQUER sub da categoria já registrada — assim o operador
    // pode adicionar as subs faltantes individualmente.
    return s;
  }, [existing]);

  const isExisting = (cat: string, sub: string | null) =>
    existingKeys.has(keyOf(cat, sub));

  // ─── Filtragem pela busca ─────────────────────────────────────────
  const normalizedQuery = query.trim().toLowerCase();

  const filteredCategories = useMemo(() => {
    if (!normalizedQuery) return categories;
    return categories
      .map((c) => {
        const catMatches = c.category.toLowerCase().includes(normalizedQuery);
        if (catMatches) {
          // Categoria casa → mostra TUDO dela
          return c;
        }
        const filteredSubs = c.subcategories.filter((s) =>
          s.toLowerCase().includes(normalizedQuery),
        );
        if (filteredSubs.length > 0) {
          return { category: c.category, subcategories: filteredSubs };
        }
        return null;
      })
      .filter((c): c is CategoryEntry => c !== null);
  }, [categories, normalizedQuery]);

  // Quando há busca, expandir automaticamente as categorias com matches.
  useEffect(() => {
    if (normalizedQuery) {
      setExpanded(new Set(filteredCategories.map((c) => c.category)));
    }
  }, [normalizedQuery, filteredCategories]);

  // ─── Paginação ──────────────────────────────────────────────────
  // Recalcula sempre que filteredCategories mudar (busca filtra) ou
  // pageSize mudar. Volta pra primeira página em qualquer mudança que
  // possa invalidar a página atual.
  const totalPages = Math.max(1, Math.ceil(filteredCategories.length / pageSize));

  // Reset de página quando busca muda ou pageSize muda — evita
  // "página vazia" porque a página atual ficou fora do range.
  useEffect(() => {
    setPage(0);
  }, [normalizedQuery, pageSize]);

  // Defensivo: se a página ficou fora do range (ex: filteredCategories
  // encolheu), volta pra última página válida.
  useEffect(() => {
    if (page >= totalPages) setPage(Math.max(0, totalPages - 1));
  }, [page, totalPages]);

  const paginatedCategories = useMemo(() => {
    const start = page * pageSize;
    return filteredCategories.slice(start, start + pageSize);
  }, [filteredCategories, page, pageSize]);

  const pageStart = filteredCategories.length === 0 ? 0 : page * pageSize + 1;
  const pageEnd = Math.min(filteredCategories.length, (page + 1) * pageSize);

  // ─── Helpers de seleção ───────────────────────────────────────────
  const toggleOne = (cat: string, sub: string | null) => {
    if (isExisting(cat, sub)) return;
    setSelected((prev) => {
      const next = new Set(prev);
      const k = keyOf(cat, sub);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      return next;
    });
  };

  const isSelected = (cat: string, sub: string | null) =>
    selected.has(keyOf(cat, sub));

  /**
   * Estado do checkbox-mestre da categoria:
   *  - "all"   → todas as subs disponíveis (não-existentes) marcadas
   *  - "some"  → algumas marcadas (renderiza indeterminate)
   *  - "none"  → nenhuma marcada
   *
   * Caso especial: categoria SEM subcategorias (subcategories.length=0) —
   * o estado representa o template "categoria-only" (subcategory=NULL).
   */
  const categoryState = (c: CategoryEntry): "all" | "some" | "none" => {
    if (c.subcategories.length === 0) {
      // Categoria sem subs: opera no template (cat, null).
      if (isExisting(c.category, null)) return "all";
      return isSelected(c.category, null) ? "all" : "none";
    }
    const available = c.subcategories.filter((s) => !isExisting(c.category, s));
    if (available.length === 0) return "none";
    const checkedCount = available.filter((s) => isSelected(c.category, s)).length;
    if (checkedCount === 0) return "none";
    if (checkedCount === available.length) return "all";
    return "some";
  };

  const toggleCategory = (c: CategoryEntry) => {
    // Categoria sem subs → toggle do template (cat, null)
    if (c.subcategories.length === 0) {
      if (isExisting(c.category, null)) return;
      setSelected((prev) => {
        const next = new Set(prev);
        const k = keyOf(c.category, null);
        if (next.has(k)) next.delete(k);
        else next.add(k);
        return next;
      });
      return;
    }
    const state = categoryState(c);
    setSelected((prev) => {
      const next = new Set(prev);
      const available = c.subcategories.filter(
        (s) => !isExisting(c.category, s),
      );
      if (state === "all") {
        // Desmarca todas as desta categoria
        available.forEach((s) => next.delete(keyOf(c.category, s)));
      } else {
        // Marca todas as disponíveis (incluindo no estado "some")
        available.forEach((s) => next.add(keyOf(c.category, s)));
      }
      return next;
    });
  };

  const toggleExpanded = (cat: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(cat)) next.delete(cat);
      else next.add(cat);
      return next;
    });
  };

  const expandAll = () => {
    // Expande só o que está visível na página atual — evita
    // explodir o modal quando o operador clica "Expandir tudo" com 30+
    // categorias.
    setExpanded(new Set(paginatedCategories.map((c) => c.category)));
  };

  const collapseAll = () => setExpanded(new Set());

  const clearSelection = () => setSelected(new Set());

  // ─── Submit ───────────────────────────────────────────────────────
  const handleSubmit = async () => {
    if (selected.size === 0) {
      toast({
        title: "Nenhuma classificação selecionada",
        description: isExcludeMode
          ? "Marque pelo menos uma combinação antes de excluir."
          : "Marque pelo menos uma combinação antes de adicionar.",
      });
      return;
    }
    setSubmitting(true);
    try {
      // Reconstroi (cat, sub) a partir das chaves
      const items: { category: string; subcategory: string | null }[] = [];
      selected.forEach((k) => {
        const [cat, sub] = k.split("||");
        items.push({
          category: cat,
          subcategory: sub === "" ? null : sub,
        });
      });

      const res = await apiFetch(
        "/api/v1/publications/classification-overrides/bulk-for-office",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            office_external_id: officeId,
            items,
            action: isExcludeMode ? "exclude" : "include_custom",
          }),
        },
      );
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(
          (typeof data?.detail === "string" && data.detail) ||
            (isExcludeMode
              ? "Falha ao excluir classificações."
              : "Falha ao adicionar classificações."),
        );
      }
      const data = await res.json();
      const created = data.created ?? 0;
      const skipped = data.skipped_existing ?? 0;
      toast({
        title: isExcludeMode
          ? `${created} classificação${created === 1 ? "" : "ões"} excluída${created === 1 ? "" : "s"}`
          : `${created} classificação${created === 1 ? "" : "ões"} adicionada${created === 1 ? "" : "s"}`,
        description: skipped
          ? `${skipped} já existiam e foram ignoradas.`
          : undefined,
      });
      onAdded?.(created, skipped);
      onOpenChange(false);
    } catch (err: any) {
      toast({
        title: isExcludeMode ? "Erro ao excluir" : "Erro ao adicionar",
        description: err?.message || String(err),
        variant: "destructive",
      });
    } finally {
      setSubmitting(false);
    }
  };

  // ─── Stats pro footer ─────────────────────────────────────────────
  const totalAvailable = useMemo(() => {
    let n = 0;
    categories.forEach((c) => {
      if (c.subcategories.length === 0) {
        // Categoria-only conta como 1 disponivel se nao existe ainda
        if (!isExisting(c.category, null)) n++;
      } else {
        c.subcategories.forEach((s) => {
          if (!isExisting(c.category, s)) n++;
        });
      }
    });
    return n;
  }, [categories, existingKeys]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl p-0 gap-0 max-h-[90vh] flex flex-col">
        <DialogHeader className="px-6 pt-6 pb-4 border-b">
          <DialogTitle className="text-lg">
            {isExcludeMode ? "Excluir classificações" : "Adicionar classificações"}
          </DialogTitle>
          <DialogDescription className="text-sm">
            Escritório:{" "}
            <span className="font-medium text-foreground">{officeName}</span>
            {" • "}
            {isExcludeMode
              ? "Marque tudo que NÃO deve mais aparecer pra esse escritório e clique em \"Excluir\". Pra desfazer, vá em \"Ajustes de Classificação\" e remova o override correspondente."
              : "Marque tudo que quiser adicionar e clique em \"Adicionar\" no final. Combinações já presentes aparecem desabilitadas."}
          </DialogDescription>

          {/* Busca + ações de expansão */}
          <div className="flex items-center gap-2 pt-3">
            <div className="relative flex-1">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Buscar por categoria ou subcategoria…"
                className="pl-8 pr-8"
              />
              {query && (
                <button
                  type="button"
                  onClick={() => setQuery("")}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                  aria-label="Limpar busca"
                >
                  <X className="h-4 w-4" />
                </button>
              )}
            </div>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={expandAll}
              disabled={filteredCategories.length === 0}
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
          </div>
        </DialogHeader>

        {/* Lista de categorias */}
        <ScrollArea className="flex-1 px-6 py-3">
          {filteredCategories.length === 0 ? (
            <div className="text-center text-sm text-muted-foreground py-12">
              Nenhuma classificação corresponde à busca.
            </div>
          ) : (
            <div className="space-y-1">
              {paginatedCategories.map((c) => {
                const isExpanded = expanded.has(c.category);
                const state = categoryState(c);
                // Categoria sem subs: o "disponivel" e' a propria categoria
                // (cat, null) quando ainda nao existe.
                const availableCount =
                  c.subcategories.length === 0
                    ? isExisting(c.category, null) ? 0 : 1
                    : c.subcategories.filter(
                        (s) => !isExisting(c.category, s),
                      ).length;
                const selectedInCat =
                  c.subcategories.length === 0
                    ? (isSelected(c.category, null) ? 1 : 0)
                    : c.subcategories.filter((s) =>
                        isSelected(c.category, s),
                      ).length;
                return (
                  <div
                    key={c.category}
                    className="border rounded-md bg-card overflow-hidden"
                  >
                    <div className="flex items-center gap-2 px-3 py-2 hover:bg-accent/40 transition-colors">
                      <button
                        type="button"
                        onClick={() => toggleExpanded(c.category)}
                        className="flex items-center gap-1 flex-1 text-left text-sm font-medium"
                      >
                        {isExpanded ? (
                          <ChevronDown className="h-4 w-4 text-muted-foreground" />
                        ) : (
                          <ChevronRight className="h-4 w-4 text-muted-foreground" />
                        )}
                        <span>{c.category}</span>
                        <span className="text-xs text-muted-foreground font-normal ml-1">
                          ({c.subcategories.length})
                        </span>
                        {selectedInCat > 0 && (
                          <Badge
                            variant="secondary"
                            className="ml-2 text-xs px-1.5 py-0"
                          >
                            {selectedInCat} marcada
                            {selectedInCat === 1 ? "" : "s"}
                          </Badge>
                        )}
                      </button>
                      <Checkbox
                        checked={
                          state === "all"
                            ? true
                            : state === "some"
                              ? "indeterminate"
                              : false
                        }
                        disabled={availableCount === 0}
                        onCheckedChange={() => toggleCategory(c)}
                        aria-label={`Marcar todas de ${c.category}`}
                      />
                    </div>
                    {isExpanded && (
                      <div className="border-t bg-muted/20 px-3 py-2 space-y-1">
                        {c.subcategories.length === 0 ? (
                          <div className="text-xs text-muted-foreground py-1">
                            (categoria sem subcategorias)
                          </div>
                        ) : (
                          c.subcategories.map((sub) => {
                            const exists = isExisting(c.category, sub);
                            const checked = isSelected(c.category, sub);
                            return (
                              <label
                                key={sub}
                                className={`flex items-center gap-2 px-2 py-1 rounded text-sm cursor-pointer ${
                                  exists
                                    ? "opacity-50 cursor-not-allowed"
                                    : "hover:bg-accent/50"
                                }`}
                              >
                                <Checkbox
                                  checked={exists ? true : checked}
                                  disabled={exists}
                                  onCheckedChange={() =>
                                    toggleOne(c.category, sub)
                                  }
                                />
                                <span className="flex-1">{sub}</span>
                                {exists && (
                                  <Badge
                                    variant="outline"
                                    className="text-xs font-normal"
                                  >
                                    já adicionada
                                  </Badge>
                                )}
                              </label>
                            );
                          })
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </ScrollArea>

        {/* Barra de paginação */}
        {filteredCategories.length > pageSize && (
          <div className="border-t px-6 py-2 flex items-center justify-between gap-3 bg-muted/10 text-xs text-muted-foreground">
            <div className="flex items-center gap-2">
              <span>
                Categorias <span className="font-medium text-foreground">{pageStart}–{pageEnd}</span> de{" "}
                <span className="font-medium text-foreground">{filteredCategories.length}</span>
              </span>
              <span className="text-muted-foreground/50">·</span>
              <span>por página</span>
              <Select
                value={String(pageSize)}
                onValueChange={(v) =>
                  setPageSize(
                    Number(v) as (typeof PAGE_SIZE_OPTIONS)[number],
                  )
                }
              >
                <SelectTrigger className="h-7 w-[72px] text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {PAGE_SIZE_OPTIONS.map((opt) => (
                    <SelectItem key={opt} value={String(opt)} className="text-xs">
                      {opt}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex items-center gap-1">
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-7 w-7"
                onClick={() => setPage(0)}
                disabled={page === 0}
                aria-label="Primeira página"
              >
                <ChevronsLeft className="h-4 w-4" />
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-7 w-7"
                onClick={() => setPage((p) => Math.max(0, p - 1))}
                disabled={page === 0}
                aria-label="Página anterior"
              >
                <ChevronLeft className="h-4 w-4" />
              </Button>
              <span className="px-2 tabular-nums">
                <span className="font-medium text-foreground">{page + 1}</span>
                {" / "}
                {totalPages}
              </span>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-7 w-7"
                onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
                disabled={page >= totalPages - 1}
                aria-label="Próxima página"
              >
                <ChevronRight className="h-4 w-4" />
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-7 w-7"
                onClick={() => setPage(totalPages - 1)}
                disabled={page >= totalPages - 1}
                aria-label="Última página"
              >
                <ChevronsRight className="h-4 w-4" />
              </Button>
            </div>
          </div>
        )}

        {/* Footer */}
        <div className="border-t px-6 py-3 flex items-center justify-between gap-3 bg-muted/30">
          <div className="text-sm text-muted-foreground">
            {selected.size === 0 ? (
              <>
                Nenhuma marcada
                {totalAvailable > 0 && (
                  <span className="text-xs ml-1">
                    ({totalAvailable} disponíve
                    {totalAvailable === 1 ? "l" : "is"})
                  </span>
                )}
              </>
            ) : (
              <>
                <span className="font-medium text-foreground">
                  {selected.size}
                </span>{" "}
                marcada{selected.size === 1 ? "" : "s"}
                <button
                  type="button"
                  onClick={clearSelection}
                  className="ml-2 text-xs underline hover:text-foreground"
                >
                  limpar
                </button>
              </>
            )}
          </div>
          <div className="flex items-center gap-2">
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
              disabled={submitting || selected.size === 0}
              variant={isExcludeMode ? "destructive" : "default"}
            >
              {submitting
                ? isExcludeMode
                  ? "Excluindo…"
                  : "Adicionando…"
                : selected.size === 0
                  ? isExcludeMode
                    ? "Excluir"
                    : "Adicionar"
                  : isExcludeMode
                    ? `Excluir ${selected.size} classificaç${selected.size === 1 ? "ão" : "ões"}`
                    : `Adicionar ${selected.size} classificaç${selected.size === 1 ? "ão" : "ões"}`}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

export default ClassificationPickerDialog;
