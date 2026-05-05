// frontend/src/components/TaxonomiaAdminTab.tsx
//
// Tab Taxonomia da AdminPage. Lista categorias + subcategorias do
// classificador, permite criar/editar/inativar e tem botão "Sugerir
// com IA" que chama o endpoint /admin/taxonomy/suggest pra estruturar
// um cadastro novo (pega prazo CPC, polo padrão, exemplo de publicação).
//
// Barra de progresso TTL 60s: depois de salvar uma mudança o cache do
// classifier é invalidado no backend mas o `_get_active_tree()` lê do
// DB no próximo request e cacheia por 60s. A barra mostra a janela
// pra que o admin saiba quando a mudança vai estar 100% propagada
// (especialmente útil em ambiente com múltiplos workers).

import { useEffect, useMemo, useRef, useState } from "react";
import { useToast } from "@/hooks/use-toast";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Progress } from "@/components/ui/progress";
import { Badge } from "@/components/ui/badge";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Loader2, Plus, Pencil, Trash2, RefreshCw, Sparkles, RotateCcw } from "lucide-react";
import { apiFetch } from "@/lib/api-client";

// ─── Tipos ─────────────────────────────────────────────────────────────

interface Subcategory {
  id: number;
  category_id: number;
  name: string;
  description: string | null;
  default_polo: string | null;
  default_prazo_dias: number | null;
  default_prazo_tipo: string | null;
  default_prazo_fundamentacao: string | null;
  example_publication: string | null;
  example_response_json: string | null;
  display_order: number;
  is_active: boolean;
}

interface Category {
  id: number;
  name: string;
  description: string | null;
  default_polo: string | null;
  default_prazo_dias: number | null;
  default_prazo_tipo: string | null;
  default_prazo_fundamentacao: string | null;
  example_publication: string | null;
  example_response_json: string | null;
  display_order: number;
  is_active: boolean;
  subcategories: Subcategory[];
}

interface SuggestResponse {
  description: string | null;
  default_polo: string | null;
  default_prazo_dias: number | null;
  default_prazo_tipo: string | null;
  default_prazo_fundamentacao: string | null;
  example_publication: string | null;
  example_response_summary: string | null;
}

interface DialogState {
  open: boolean;
  mode: "create-category" | "edit-category" | "create-subcategory" | "edit-subcategory";
  parentCategory?: Category; // pra subcategorias
  editing?: Category | Subcategory;
}

// Form state — espelha os campos editáveis
interface FormState {
  name: string;
  description: string;
  default_polo: string; // 'autor' | 'reu' | 'ambos' | ''
  default_prazo_dias: string;
  default_prazo_tipo: string; // 'util' | 'corrido' | ''
  default_prazo_fundamentacao: string;
  example_publication: string;
  hint: string; // só usado pelo botão de IA, não é enviado no save
}

const EMPTY_FORM: FormState = {
  name: "",
  description: "",
  default_polo: "",
  default_prazo_dias: "",
  default_prazo_tipo: "",
  default_prazo_fundamentacao: "",
  example_publication: "",
  hint: "",
};

// ─── Componente principal ──────────────────────────────────────────────

export const TaxonomiaAdminTab = () => {
  const { toast } = useToast();
  const [categories, setCategories] = useState<Category[]>([]);
  const [loading, setLoading] = useState(false);
  const [includeInactive, setIncludeInactive] = useState(false);
  const [search, setSearch] = useState("");
  const [dialog, setDialog] = useState<DialogState>({ open: false, mode: "create-category" });
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [suggesting, setSuggesting] = useState(false);

  // ─── Barra de progresso TTL 60s ──
  // Quando o admin salva qualquer mutação, dispara um countdown de 60s
  // (TTL do cache do classifier). Depois disso a árvore lida do DB já
  // está nos workers todos.
  const [cacheCountdown, setCacheCountdown] = useState<number | null>(null);
  const countdownRef = useRef<number | null>(null);

  const startCacheCountdown = () => {
    if (countdownRef.current !== null) {
      window.clearInterval(countdownRef.current);
    }
    setCacheCountdown(60);
    countdownRef.current = window.setInterval(() => {
      setCacheCountdown((prev) => {
        if (prev === null || prev <= 1) {
          if (countdownRef.current !== null) {
            window.clearInterval(countdownRef.current);
            countdownRef.current = null;
          }
          return null;
        }
        return prev - 1;
      });
    }, 1000);
  };

  useEffect(() => {
    return () => {
      if (countdownRef.current !== null) {
        window.clearInterval(countdownRef.current);
      }
    };
  }, []);

  // ─── Fetch ──
  const fetchTaxonomy = async () => {
    setLoading(true);
    try {
      const res = await apiFetch(
        `/api/v1/admin/taxonomy?include_inactive=${includeInactive ? "true" : "false"}`
      );
      if (!res.ok) {
        const detail = await res.text();
        throw new Error(`HTTP ${res.status}: ${detail.slice(0, 200)}`);
      }
      const data = await res.json();
      setCategories(data.categories || []);
    } catch (err) {
      toast({
        title: "Erro ao carregar taxonomia",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTaxonomy();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [includeInactive]);

  // ─── Filtragem ──
  const filteredCategories = useMemo(() => {
    if (!search.trim()) return categories;
    const q = search.toLowerCase();
    return categories.filter((c) => {
      if (c.name.toLowerCase().includes(q)) return true;
      return c.subcategories.some((s) => s.name.toLowerCase().includes(q));
    });
  }, [categories, search]);

  // ─── Dialog handlers ──
  const openCreateCategory = () => {
    setForm(EMPTY_FORM);
    setDialog({ open: true, mode: "create-category" });
  };

  const openEditCategory = (cat: Category) => {
    setForm({
      name: cat.name,
      description: cat.description || "",
      default_polo: cat.default_polo || "",
      default_prazo_dias: cat.default_prazo_dias?.toString() || "",
      default_prazo_tipo: cat.default_prazo_tipo || "",
      default_prazo_fundamentacao: cat.default_prazo_fundamentacao || "",
      example_publication: cat.example_publication || "",
      hint: "",
    });
    setDialog({ open: true, mode: "edit-category", editing: cat });
  };

  const openCreateSubcategory = (cat: Category) => {
    setForm(EMPTY_FORM);
    setDialog({ open: true, mode: "create-subcategory", parentCategory: cat });
  };

  const openEditSubcategory = (cat: Category, sub: Subcategory) => {
    setForm({
      name: sub.name,
      description: sub.description || "",
      default_polo: sub.default_polo || "",
      default_prazo_dias: sub.default_prazo_dias?.toString() || "",
      default_prazo_tipo: sub.default_prazo_tipo || "",
      default_prazo_fundamentacao: sub.default_prazo_fundamentacao || "",
      example_publication: sub.example_publication || "",
      hint: "",
    });
    setDialog({
      open: true,
      mode: "edit-subcategory",
      parentCategory: cat,
      editing: sub,
    });
  };

  const closeDialog = () => {
    setDialog((d) => ({ ...d, open: false }));
    setForm(EMPTY_FORM);
  };

  // ─── Save ──
  const handleSave = async () => {
    if (!form.name.trim()) {
      toast({
        title: "Nome obrigatório",
        description: "Informe um nome para a categoria/subcategoria.",
        variant: "destructive",
      });
      return;
    }
    setSaving(true);
    try {
      const body: Record<string, unknown> = {
        name: form.name.trim(),
        description: form.description.trim() || null,
        default_polo: form.default_polo || null,
        default_prazo_dias: form.default_prazo_dias
          ? parseInt(form.default_prazo_dias, 10)
          : null,
        default_prazo_tipo: form.default_prazo_tipo || null,
        default_prazo_fundamentacao: form.default_prazo_fundamentacao.trim() || null,
        example_publication: form.example_publication.trim() || null,
      };

      let url = "";
      let method = "POST";

      if (dialog.mode === "create-category") {
        url = "/api/v1/admin/taxonomy/categories";
        method = "POST";
      } else if (dialog.mode === "edit-category") {
        url = `/api/v1/admin/taxonomy/categories/${(dialog.editing as Category).id}`;
        method = "PATCH";
      } else if (dialog.mode === "create-subcategory") {
        url = `/api/v1/admin/taxonomy/categories/${dialog.parentCategory!.id}/subcategories`;
        method = "POST";
      } else if (dialog.mode === "edit-subcategory") {
        url = `/api/v1/admin/taxonomy/subcategories/${(dialog.editing as Subcategory).id}`;
        method = "PATCH";
      }

      const res = await apiFetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      if (!res.ok) {
        const errText = await res.text();
        let errMsg = errText;
        try {
          const errJson = JSON.parse(errText);
          errMsg = errJson.detail || errText;
        } catch {
          // não é JSON, mantém texto
        }
        throw new Error(errMsg);
      }

      toast({ title: "Salvo com sucesso", description: form.name });
      closeDialog();
      await fetchTaxonomy();
      startCacheCountdown();
    } catch (err) {
      toast({
        title: "Erro ao salvar",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setSaving(false);
    }
  };

  // ─── Delete (soft) ──
  const handleSoftDelete = async (
    kind: "category" | "subcategory",
    item: Category | Subcategory,
  ) => {
    const label = kind === "category" ? "categoria" : "subcategoria";
    if (!window.confirm(`Inativar ${label} "${item.name}"? Classificações antigas continuam visíveis, mas a IA não usará mais.`)) {
      return;
    }
    try {
      const url =
        kind === "category"
          ? `/api/v1/admin/taxonomy/categories/${item.id}`
          : `/api/v1/admin/taxonomy/subcategories/${item.id}`;
      const res = await apiFetch(url, { method: "DELETE" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      toast({ title: `${label[0].toUpperCase()}${label.slice(1)} inativada`, description: item.name });
      await fetchTaxonomy();
      startCacheCountdown();
    } catch (err) {
      toast({
        title: "Erro ao inativar",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    }
  };

  // ─── Restore ──
  const handleRestore = async (
    kind: "category" | "subcategory",
    item: Category | Subcategory,
  ) => {
    try {
      const url =
        kind === "category"
          ? `/api/v1/admin/taxonomy/categories/${item.id}/restore`
          : `/api/v1/admin/taxonomy/subcategories/${item.id}/restore`;
      const res = await apiFetch(url, { method: "POST" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      toast({ title: "Reativada", description: item.name });
      await fetchTaxonomy();
      startCacheCountdown();
    } catch (err) {
      toast({
        title: "Erro ao reativar",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    }
  };

  // ─── Sonnet helper ──
  const handleSuggest = async () => {
    if (!form.name.trim()) {
      toast({
        title: "Informe o nome primeiro",
        description: "A IA precisa do nome pra estruturar os campos.",
        variant: "destructive",
      });
      return;
    }
    setSuggesting(true);
    try {
      const isSubcategory =
        dialog.mode === "create-subcategory" || dialog.mode === "edit-subcategory";
      const body = {
        name: form.name.trim(),
        parent_category_name: isSubcategory ? dialog.parentCategory?.name : null,
        hint: form.hint.trim() || null,
      };
      const res = await apiFetch("/api/v1/admin/taxonomy/suggest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const errText = await res.text();
        throw new Error(errText.slice(0, 300));
      }
      const data: SuggestResponse = await res.json();
      // Aplica só os campos vazios — não sobrescreve o que o admin já preencheu
      setForm((prev) => ({
        ...prev,
        description: prev.description || data.description || "",
        default_polo: prev.default_polo || data.default_polo || "",
        default_prazo_dias:
          prev.default_prazo_dias || (data.default_prazo_dias?.toString() ?? ""),
        default_prazo_tipo: prev.default_prazo_tipo || data.default_prazo_tipo || "",
        default_prazo_fundamentacao:
          prev.default_prazo_fundamentacao || data.default_prazo_fundamentacao || "",
        example_publication:
          prev.example_publication || data.example_publication || "",
      }));
      toast({
        title: "Sugestão aplicada",
        description: data.example_response_summary || "Campos preenchidos pela IA. Revise antes de salvar.",
      });
    } catch (err) {
      toast({
        title: "Erro ao sugerir com IA",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setSuggesting(false);
    }
  };

  // ─── Render ──
  const isEditing =
    dialog.mode === "edit-category" || dialog.mode === "edit-subcategory";
  const isSubcategoryDialog =
    dialog.mode === "create-subcategory" || dialog.mode === "edit-subcategory";

  return (
    <div className="space-y-4">
      {/* Header com ações */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h2 className="text-xl font-semibold">Taxonomia de Classificações</h2>
          <p className="text-sm text-muted-foreground">
            Categorias e subcategorias usadas pela IA pra classificar publicações.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={fetchTaxonomy} disabled={loading}>
            <RefreshCw className={`mr-2 h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            Recarregar
          </Button>
          <Button onClick={openCreateCategory}>
            <Plus className="mr-2 h-4 w-4" />
            Nova categoria
          </Button>
        </div>
      </div>

      {/* Filtros */}
      <div className="flex items-center gap-3 flex-wrap">
        <Input
          placeholder="Buscar por nome..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="max-w-sm"
        />
        <label className="flex items-center gap-2 text-sm cursor-pointer">
          <input
            type="checkbox"
            checked={includeInactive}
            onChange={(e) => setIncludeInactive(e.target.checked)}
          />
          Mostrar inativas
        </label>
      </div>

      {/* Barra de progresso TTL 60s */}
      {cacheCountdown !== null && (
        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center gap-3">
              <Loader2 className="h-4 w-4 animate-spin text-blue-600" />
              <div className="flex-1">
                <div className="text-sm font-medium mb-1">
                  Propagando alteração para os workers do classificador...
                </div>
                <Progress value={((60 - cacheCountdown) / 60) * 100} className="h-2" />
                <div className="text-xs text-muted-foreground mt-1">
                  TTL do cache: {cacheCountdown}s restantes. A IA já vê a mudança nos novos
                  requests; este timer é só pra propagação total entre processos.
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Lista */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Categorias ({filteredCategories.length})</CardTitle>
          <CardDescription>
            Clique em uma categoria pra ver/editar suas subcategorias.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : filteredCategories.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground text-sm">
              {search ? "Nenhum resultado." : "Nenhuma categoria cadastrada ainda."}
            </div>
          ) : (
            <Accordion type="multiple" className="w-full">
              {filteredCategories.map((cat) => (
                <AccordionItem key={cat.id} value={`cat-${cat.id}`}>
                  <AccordionTrigger className="hover:no-underline">
                    <div className="flex items-center gap-2 flex-1 text-left">
                      <span className={cat.is_active ? "" : "line-through text-muted-foreground"}>
                        {cat.name}
                      </span>
                      <Badge variant="secondary" className="ml-2">
                        {cat.subcategories.length} sub
                      </Badge>
                      {!cat.is_active && (
                        <Badge variant="outline" className="text-orange-600 border-orange-300">
                          inativa
                        </Badge>
                      )}
                    </div>
                  </AccordionTrigger>
                  <AccordionContent>
                    <div className="space-y-3 pl-2">
                      {cat.description && (
                        <div className="text-sm text-muted-foreground italic">
                          {cat.description}
                        </div>
                      )}
                      <div className="flex flex-wrap gap-2 text-xs">
                        {cat.default_polo && (
                          <Badge variant="outline">Polo: {cat.default_polo}</Badge>
                        )}
                        {cat.default_prazo_dias != null && (
                          <Badge variant="outline">
                            Prazo: {cat.default_prazo_dias}d {cat.default_prazo_tipo || ""}
                          </Badge>
                        )}
                        {cat.default_prazo_fundamentacao && (
                          <Badge variant="outline">{cat.default_prazo_fundamentacao}</Badge>
                        )}
                      </div>
                      <div className="flex items-center gap-2">
                        <Button size="sm" variant="outline" onClick={() => openEditCategory(cat)}>
                          <Pencil className="mr-1 h-3 w-3" />
                          Editar
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => openCreateSubcategory(cat)}
                        >
                          <Plus className="mr-1 h-3 w-3" />
                          Adicionar subcategoria
                        </Button>
                        {cat.is_active ? (
                          <Button
                            size="sm"
                            variant="outline"
                            className="text-red-600"
                            onClick={() => handleSoftDelete("category", cat)}
                          >
                            <Trash2 className="mr-1 h-3 w-3" />
                            Inativar
                          </Button>
                        ) : (
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => handleRestore("category", cat)}
                          >
                            <RotateCcw className="mr-1 h-3 w-3" />
                            Reativar
                          </Button>
                        )}
                      </div>

                      {/* Subcategorias */}
                      {cat.subcategories.length > 0 && (
                        <div className="border-l-2 border-muted pl-3 space-y-2 mt-3">
                          {cat.subcategories.map((sub) => (
                            <div
                              key={sub.id}
                              className="flex items-center justify-between gap-2 py-1"
                            >
                              <div className="flex items-center gap-2 flex-1">
                                <span
                                  className={
                                    sub.is_active
                                      ? "text-sm"
                                      : "text-sm line-through text-muted-foreground"
                                  }
                                >
                                  {sub.name}
                                </span>
                                {!sub.is_active && (
                                  <Badge variant="outline" className="text-orange-600 border-orange-300 text-xs">
                                    inativa
                                  </Badge>
                                )}
                                {sub.default_prazo_dias != null && (
                                  <span className="text-xs text-muted-foreground">
                                    ({sub.default_prazo_dias}d{" "}
                                    {sub.default_prazo_tipo || ""})
                                  </span>
                                )}
                              </div>
                              <div className="flex items-center gap-1">
                                <Button
                                  size="sm"
                                  variant="ghost"
                                  onClick={() => openEditSubcategory(cat, sub)}
                                >
                                  <Pencil className="h-3 w-3" />
                                </Button>
                                {sub.is_active ? (
                                  <Button
                                    size="sm"
                                    variant="ghost"
                                    className="text-red-600"
                                    onClick={() => handleSoftDelete("subcategory", sub)}
                                  >
                                    <Trash2 className="h-3 w-3" />
                                  </Button>
                                ) : (
                                  <Button
                                    size="sm"
                                    variant="ghost"
                                    onClick={() => handleRestore("subcategory", sub)}
                                  >
                                    <RotateCcw className="h-3 w-3" />
                                  </Button>
                                )}
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </AccordionContent>
                </AccordionItem>
              ))}
            </Accordion>
          )}
        </CardContent>
      </Card>

      {/* Dialog de create/edit */}
      <Dialog open={dialog.open} onOpenChange={(o) => !o && closeDialog()}>
        <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>
              {dialog.mode === "create-category" && "Nova categoria"}
              {dialog.mode === "edit-category" && `Editar categoria: ${(dialog.editing as Category)?.name}`}
              {dialog.mode === "create-subcategory" &&
                `Nova subcategoria em "${dialog.parentCategory?.name}"`}
              {dialog.mode === "edit-subcategory" &&
                `Editar subcategoria: ${(dialog.editing as Subcategory)?.name}`}
            </DialogTitle>
          </DialogHeader>

          <div className="space-y-4 py-2">
            <div>
              <Label htmlFor="tax-name">Nome *</Label>
              <Input
                id="tax-name"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder={
                  isSubcategoryDialog
                    ? "Ex.: Sentença Procedente"
                    : "Ex.: Tutela"
                }
              />
            </div>

            {!isEditing && (
              <div className="bg-muted/50 rounded p-3 space-y-2">
                <Label htmlFor="tax-hint" className="flex items-center gap-2">
                  <Sparkles className="h-3.5 w-3.5 text-purple-600" />
                  Dica para a IA (opcional)
                </Label>
                <Textarea
                  id="tax-hint"
                  value={form.hint}
                  onChange={(e) => setForm({ ...form, hint: e.target.value })}
                  placeholder="Ex.: usar quando o juiz determina penhora online via SISBAJUD"
                  rows={2}
                />
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={handleSuggest}
                  disabled={suggesting || !form.name.trim()}
                >
                  {suggesting ? (
                    <Loader2 className="mr-2 h-3 w-3 animate-spin" />
                  ) : (
                    <Sparkles className="mr-2 h-3 w-3" />
                  )}
                  Sugerir campos com IA
                </Button>
              </div>
            )}

            <div>
              <Label htmlFor="tax-desc">Descrição</Label>
              <Textarea
                id="tax-desc"
                value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
                placeholder="Quando aplicar essa classificação?"
                rows={2}
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label htmlFor="tax-polo">Polo padrão</Label>
                <Select
                  value={form.default_polo || "none"}
                  onValueChange={(v) =>
                    setForm({ ...form, default_polo: v === "none" ? "" : v })
                  }
                >
                  <SelectTrigger id="tax-polo">
                    <SelectValue placeholder="Selecionar..." />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="none">— sem padrão —</SelectItem>
                    <SelectItem value="autor">Autor</SelectItem>
                    <SelectItem value="reu">Réu</SelectItem>
                    <SelectItem value="ambos">Ambos</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label htmlFor="tax-tipo">Tipo de prazo</Label>
                <Select
                  value={form.default_prazo_tipo || "none"}
                  onValueChange={(v) =>
                    setForm({ ...form, default_prazo_tipo: v === "none" ? "" : v })
                  }
                >
                  <SelectTrigger id="tax-tipo">
                    <SelectValue placeholder="Selecionar..." />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="none">— sem padrão —</SelectItem>
                    <SelectItem value="util">Dias úteis</SelectItem>
                    <SelectItem value="corrido">Dias corridos</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label htmlFor="tax-dias">Prazo (dias)</Label>
                <Input
                  id="tax-dias"
                  type="number"
                  min={0}
                  value={form.default_prazo_dias}
                  onChange={(e) =>
                    setForm({ ...form, default_prazo_dias: e.target.value })
                  }
                  placeholder="Ex.: 15"
                />
              </div>
              <div>
                <Label htmlFor="tax-fund">Fundamentação CPC</Label>
                <Input
                  id="tax-fund"
                  value={form.default_prazo_fundamentacao}
                  onChange={(e) =>
                    setForm({ ...form, default_prazo_fundamentacao: e.target.value })
                  }
                  placeholder="Ex.: Art. 335 do CPC"
                />
              </div>
            </div>

            <div>
              <Label htmlFor="tax-example">Exemplo de publicação</Label>
              <Textarea
                id="tax-example"
                value={form.example_publication}
                onChange={(e) =>
                  setForm({ ...form, example_publication: e.target.value })
                }
                placeholder="Trecho realista de uma publicação que se classifica assim (use [PROCESSO], [JUIZ] como placeholders)"
                rows={3}
              />
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={closeDialog} disabled={saving}>
              Cancelar
            </Button>
            <Button onClick={handleSave} disabled={saving}>
              {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Salvar
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default TaxonomiaAdminTab;
