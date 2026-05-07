/**
 * TaxonomyToggleCard — switch global v1 <-> v2 (fase 11).
 *
 * Mostra:
 *  - Estado atual da taxonomia (v1 | v2) em destaque
 *  - Contagem de templates/overrides pendentes de revisao
 *  - Botao "Ativar v2" desabilitado se houver pendentes acima do
 *    threshold do backend (default 0 — todos os pendentes precisam
 *    ser revisados antes). Operador pode clicar "Forcar" pra burlar.
 *  - Botao "Reverter pra v1" sempre habilitado (rollback livre).
 *
 * Backend: GET / PATCH /api/v1/admin/taxonomy/settings.
 * Mudanca aqui dispara invalidate_taxonomy_cache() no servidor —
 * proximo classifier ja vai usar a versao nova sem esperar TTL.
 */
import { useEffect, useState } from "react";
import { ArrowRightLeft, CheckCircle2, AlertTriangle, Loader2 } from "lucide-react";
import { Link } from "react-router-dom";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { useToast } from "@/hooks/use-toast";
import { apiFetch } from "@/lib/api-client";

interface ToggleState {
  active_version: string;
  pending_templates: number;
  pending_overrides: number;
  can_activate_v2: boolean;
  threshold: number;
}

const ENDPOINT = "/api/v1/admin/taxonomy/settings";

export function TaxonomyToggleCard() {
  const { toast } = useToast();
  const [state, setState] = useState<ToggleState | null>(null);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const res = await apiFetch(ENDPOINT);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as ToggleState;
      setState(data);
    } catch (err: any) {
      toast({
        title: "Falha lendo toggle de taxonomia",
        description: err?.message || String(err),
        variant: "destructive",
      });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const apply = async (target: "v1" | "v2", force = false) => {
    setSubmitting(true);
    try {
      const res = await apiFetch(ENDPOINT, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ active_version: target, force }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(
          (typeof data?.detail === "string" && data.detail) ||
            "Falha ao atualizar toggle.",
        );
      }
      const data = (await res.json()) as ToggleState;
      setState(data);
      toast({
        title:
          target === "v2" ? "Taxonomia v2 ativa" : "Taxonomia revertida pra v1",
        description: force
          ? "Aplicado com force=true (pendentes ignorados)."
          : "Cache do classificador foi invalidado.",
      });
    } catch (err: any) {
      toast({
        title: "Erro ao alternar versao",
        description: err?.message || String(err),
        variant: "destructive",
      });
    } finally {
      setSubmitting(false);
    }
  };

  const totalPending =
    (state?.pending_templates ?? 0) + (state?.pending_overrides ?? 0);

  const isV2 = state?.active_version === "v2";

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ArrowRightLeft className="h-5 w-5" />
          Toggle Taxonomy v1 ↔ v2
          {state && (
            <Badge
              variant={isV2 ? "default" : "secondary"}
              className={
                isV2
                  ? "bg-green-600 hover:bg-green-700"
                  : "bg-amber-100 text-amber-900 hover:bg-amber-100 dark:bg-amber-900/40 dark:text-amber-200"
              }
            >
              ativa: {state.active_version}
            </Badge>
          )}
        </CardTitle>
        <CardDescription>
          Define qual taxonomia a IA emite e o engine de propostas usa.
          Ativar a v2 com pendentes acima do threshold é bloqueado por
          padrão — revise tudo via{" "}
          <Link
            to="/publications/templates/review-pending"
            className="underline hover:text-foreground"
          >
            Templates Pendentes
          </Link>{" "}
          antes de virar a chave.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {loading && !state ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            Carregando...
          </div>
        ) : state ? (
          <>
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <span className="text-muted-foreground">Pendentes:</span>
              <Badge
                variant={state.pending_templates > 0 ? "outline" : "secondary"}
                className={
                  state.pending_templates > 0
                    ? "border-amber-300 text-amber-900 dark:border-amber-700 dark:text-amber-200"
                    : ""
                }
              >
                templates: {state.pending_templates}
              </Badge>
              <Badge
                variant={state.pending_overrides > 0 ? "outline" : "secondary"}
                className={
                  state.pending_overrides > 0
                    ? "border-amber-300 text-amber-900 dark:border-amber-700 dark:text-amber-200"
                    : ""
                }
              >
                overrides: {state.pending_overrides}
              </Badge>
              {totalPending === 0 && (
                <Badge variant="default" className="bg-green-600 hover:bg-green-700">
                  <CheckCircle2 className="h-3 w-3 mr-1" />
                  Sem pendências
                </Badge>
              )}
            </div>

            <div className="flex flex-wrap items-center gap-2 pt-2">
              {!isV2 && (
                <>
                  <Button
                    onClick={() => apply("v2")}
                    disabled={submitting || !state.can_activate_v2}
                    size="sm"
                  >
                    {submitting ? (
                      <Loader2 className="h-4 w-4 mr-1 animate-spin" />
                    ) : null}
                    Ativar v2
                  </Button>
                  {!state.can_activate_v2 && totalPending > 0 && (
                    <AlertDialog>
                      <AlertDialogTrigger asChild>
                        <Button variant="outline" size="sm" disabled={submitting}>
                          <AlertTriangle className="h-4 w-4 mr-1 text-amber-500" />
                          Forçar ativação (ignorar pendentes)
                        </Button>
                      </AlertDialogTrigger>
                      <AlertDialogContent>
                        <AlertDialogHeader>
                          <AlertDialogTitle>
                            Forçar ativação da v2?
                          </AlertDialogTitle>
                          <AlertDialogDescription>
                            Existem <strong>{totalPending}</strong> item(ns)
                            pendente(s) de revisão ({state.pending_templates}{" "}
                            templates + {state.pending_overrides} overrides).
                            <br />
                            <br />
                            Ao forçar, esses templates ficarão{" "}
                            <strong>dormentes</strong> até serem revisados —
                            propostas automáticas para esses casos não serão
                            geradas. Você pode reverter pra v1 a qualquer
                            momento sem perder o trabalho de revisão.
                          </AlertDialogDescription>
                        </AlertDialogHeader>
                        <AlertDialogFooter>
                          <AlertDialogCancel>Cancelar</AlertDialogCancel>
                          <AlertDialogAction onClick={() => apply("v2", true)}>
                            Forçar ativação
                          </AlertDialogAction>
                        </AlertDialogFooter>
                      </AlertDialogContent>
                    </AlertDialog>
                  )}
                </>
              )}
              {isV2 && (
                <AlertDialog>
                  <AlertDialogTrigger asChild>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={submitting}
                    >
                      Reverter pra v1
                    </Button>
                  </AlertDialogTrigger>
                  <AlertDialogContent>
                    <AlertDialogHeader>
                      <AlertDialogTitle>Reverter pra v1?</AlertDialogTitle>
                      <AlertDialogDescription>
                        A IA voltará a emitir labels da taxonomia v1 e o
                        engine usará templates v1. Templates já migrados
                        para v2 ficarão dormentes (não casam com nada
                        emitido pela v1) — mas a revisão fica{" "}
                        <strong>preservada</strong>: ao reativar v2 depois,
                        eles voltam a casar imediatamente.
                      </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                      <AlertDialogCancel>Cancelar</AlertDialogCancel>
                      <AlertDialogAction onClick={() => apply("v1")}>
                        Reverter
                      </AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              )}
              <Button
                variant="ghost"
                size="sm"
                onClick={load}
                disabled={loading}
              >
                Recarregar
              </Button>
            </div>

            {!state.can_activate_v2 && totalPending > 0 && !isV2 && (
              <p className="text-xs text-muted-foreground">
                ⚠️ Threshold do backend: {state.threshold}. Revise os
                pendentes ou use "Forçar ativação".
              </p>
            )}
          </>
        ) : null}
      </CardContent>
    </Card>
  );
}

export default TaxonomyToggleCard;
