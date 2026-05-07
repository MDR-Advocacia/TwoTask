/**
 * Modal dedicado a REVISAO de template legacy v1 -> v2.
 *
 * Usado pelo painel "Templates Pendentes de Revisao" (Admin/Templates).
 * UX intencionalmente focada em UMA acao: re-apontar a classificacao.
 * Demais campos do template (responsavel, prazo, descricao, etc.) ja
 * estao preservados desde a migration tax007 — operador pode edita-los
 * depois pelo modal regular se quiser.
 *
 * Fluxo:
 *  1. Banner amarelo mostra `legacy_label` (cat/sub v1 originais).
 *  2. ClassificationPicker carrega arvore v2 filtrada pelo polo_scope
 *     do escritorio do template (vem como `office_polo_scope` no objeto).
 *     Pra templates "globais" (sem escritorio), o operador escolhe
 *     entre as duas arvores via tab.
 *  3. Botao "Salvar e Migrar" chama POST /task-templates/{id}/migrate
 *     que valida a (cat, sub) v2, atualiza, marca taxonomy_version='v2'
 *     e zera needs_taxonomy_review.
 *
 * O modal nao mexe em is_active: se o template estava is_active=true
 * antes (default tax007), permanece. Se o operador desativou
 * manualmente, mantem desativado.
 */
import { useEffect, useMemo, useState } from "react";
import { AlertTriangle } from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Tabs,
  TabsList,
  TabsTrigger,
  TabsContent,
} from "@/components/ui/tabs";
import {
  ClassificationPicker,
  type ClassificationCategory,
  type ClassificationValue,
} from "@/components/ui/ClassificationPicker";
import { useToast } from "@/hooks/use-toast";
import { apiFetch } from "@/lib/api-client";

export interface TemplateForReview {
  id: number;
  name: string;
  /** Cat/sub atuais (legacy v1) — exibidas como referencia. */
  category: string;
  subcategory: string | null;
  /** "<cat_v1> / <sub_v1>" snapshot da migration tax007. */
  legacy_label: string | null;
  /** Polo do escritorio do template; null pra templates globais. */
  office_polo_scope?: string | null;
  /** Nome (path) do escritorio pra exibicao. */
  office_name?: string | null;
}

export interface TemplateReviewModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  template: TemplateForReview | null;
  /** Chamado depois que o migrate sobe com sucesso (UI recarrega lista). */
  onMigrated?: (templateId: number) => void;
}

type PoloChoice = "ativo" | "passivo";

const TAXONOMY_META_URL = "/api/v1/task-templates/meta/categories";

export function TemplateReviewModal({
  open,
  onOpenChange,
  template,
  onMigrated,
}: TemplateReviewModalProps) {
  const { toast } = useToast();

  // Pra templates "globais" (sem escritorio) ou escritorios com
  // polo_scope='ambos', operador precisa escolher manualmente em qual
  // arvore reapontar. Pra escritorios com polo definido, o tab fica
  // travado nesse polo.
  const officePolo = template?.office_polo_scope ?? null;
  const lockedPolo: PoloChoice | null =
    officePolo === "ativo" || officePolo === "passivo" ? officePolo : null;

  const [activePolo, setActivePolo] = useState<PoloChoice>(lockedPolo ?? "ativo");
  const [selected, setSelected] = useState<ClassificationValue | null>(null);
  const [categoriesByPolo, setCategoriesByPolo] = useState<{
    ativo: ClassificationCategory[];
    passivo: ClassificationCategory[];
  }>({ ativo: [], passivo: [] });
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  // Reset ao reabrir / trocar template
  useEffect(() => {
    if (open && template) {
      setActivePolo(lockedPolo ?? "ativo");
      setSelected(null);
    }
  }, [open, template?.id, lockedPolo]);

  // Carrega arvores v2 (ativo e passivo) ao abrir.
  useEffect(() => {
    if (!open || !template) return;
    let cancelled = false;
    setLoading(true);
    Promise.all([
      apiFetch(`${TAXONOMY_META_URL}?polo_scope=ativo&taxonomy_version=v2`),
      apiFetch(`${TAXONOMY_META_URL}?polo_scope=passivo&taxonomy_version=v2`),
    ])
      .then(async ([rA, rP]) => {
        if (!rA.ok || !rP.ok) throw new Error("Falha carregando taxonomia v2");
        const [dA, dP] = await Promise.all([rA.json(), rP.json()]);
        if (cancelled) return;
        setCategoriesByPolo({
          ativo: (dA.categories ?? []) as ClassificationCategory[],
          passivo: (dP.categories ?? []) as ClassificationCategory[],
        });
      })
      .catch((err) => {
        if (cancelled) return;
        toast({
          title: "Erro carregando taxonomia v2",
          description: String(err?.message ?? err),
          variant: "destructive",
        });
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, template?.id, toast]);

  const categoriesActive = useMemo(() => categoriesByPolo[activePolo], [
    categoriesByPolo,
    activePolo,
  ]);

  const handleMigrate = async () => {
    if (!template) return;
    if (!selected) {
      toast({
        title: "Selecione a classificação v2",
        description:
          "Escolha categoria e subcategoria na árvore antes de migrar.",
      });
      return;
    }
    setSubmitting(true);
    try {
      const res = await apiFetch(
        `/api/v1/task-templates/${template.id}/migrate`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            category: selected.category,
            subcategory: selected.subcategory,
          }),
        },
      );
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(
          (typeof data?.detail === "string" && data.detail) ||
            "Falha ao migrar template.",
        );
      }
      toast({
        title: "Template migrado para v2",
        description: `${selected.category}${
          selected.subcategory ? ` / ${selected.subcategory}` : ""
        }`,
      });
      onMigrated?.(template.id);
      onOpenChange(false);
    } catch (err: any) {
      toast({
        title: "Erro ao migrar",
        description: err?.message || String(err),
        variant: "destructive",
      });
    } finally {
      setSubmitting(false);
    }
  };

  if (!template) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>Revisar classificação do template</DialogTitle>
          <DialogDescription>
            Re-aponte para a classificação correspondente na taxonomia
            nova. Demais campos do template (responsável, prazo, descrição)
            permanecem como estavam — você pode editá-los depois pelo
            modal regular.
          </DialogDescription>
        </DialogHeader>

        {/* Banner amarelo: legacy_label */}
        <div className="rounded-md border border-amber-300 bg-amber-50 dark:bg-amber-950/30 dark:border-amber-700/50 p-3 flex gap-3">
          <AlertTriangle className="h-5 w-5 text-amber-600 dark:text-amber-400 shrink-0 mt-0.5" />
          <div className="text-sm space-y-1">
            <div className="font-medium text-amber-900 dark:text-amber-200">
              Classificação legada (taxonomia v1)
            </div>
            <div className="text-amber-800 dark:text-amber-200/80">
              <span className="font-mono text-xs">
                {template.legacy_label ??
                  `${template.category}${
                    template.subcategory ? ` / ${template.subcategory}` : ""
                  }`}
              </span>
            </div>
            <div className="text-xs text-amber-700 dark:text-amber-300/70 pt-1">
              Template:{" "}
              <span className="font-medium">{template.name}</span>
              {template.office_name ? (
                <>
                  {" · "}
                  <span>{template.office_name}</span>
                </>
              ) : (
                <>
                  {" · "}
                  <Badge variant="outline" className="text-xs">
                    Template global
                  </Badge>
                </>
              )}
            </div>
          </div>
        </div>

        {/* Picker da nova classificacao */}
        <div className="pt-2">
          {lockedPolo ? (
            <ClassificationPicker
              value={selected}
              categories={categoriesActive}
              onChange={setSelected}
              polo={lockedPolo}
              label="Nova classificação (taxonomia v2)"
              required
              placeholder={
                loading
                  ? "Carregando árvore..."
                  : `Selecione na árvore do polo ${lockedPolo}`
              }
              disabled={loading}
            />
          ) : (
            <Tabs
              value={activePolo}
              onValueChange={(v) => {
                setActivePolo(v as PoloChoice);
                setSelected(null);
              }}
            >
              <TabsList className="grid w-full grid-cols-2">
                <TabsTrigger value="ativo">Polo ativo</TabsTrigger>
                <TabsTrigger value="passivo">Polo passivo</TabsTrigger>
              </TabsList>
              <TabsContent value="ativo" className="pt-3">
                <ClassificationPicker
                  value={selected}
                  categories={categoriesByPolo.ativo}
                  onChange={setSelected}
                  polo="ativo"
                  label="Nova classificação (taxonomia v2)"
                  required
                  disabled={loading}
                />
              </TabsContent>
              <TabsContent value="passivo" className="pt-3">
                <ClassificationPicker
                  value={selected}
                  categories={categoriesByPolo.passivo}
                  onChange={setSelected}
                  polo="passivo"
                  label="Nova classificação (taxonomia v2)"
                  required
                  disabled={loading}
                />
              </TabsContent>
            </Tabs>
          )}
        </div>

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
            onClick={handleMigrate}
            disabled={submitting || loading || !selected}
          >
            {submitting ? "Migrando..." : "Salvar e Migrar"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default TemplateReviewModal;
