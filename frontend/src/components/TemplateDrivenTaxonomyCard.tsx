/**
 * TemplateDrivenTaxonomyCard — toggle do modo arvore enxuta (fase 13).
 *
 * Quando ligado, a arvore aplicavel a um escritorio so inclui cats que
 * tem pelo menos um template ativo. Cats "Para Analise" sempre entram
 * via whitelist (catch-all). Granularidade GROSSA: presenca de template
 * em uma cat libera a categoria inteira.
 *
 * Backend: GET / PATCH /api/v1/admin/template-driven-taxonomy/settings.
 * Mudanca aqui invalida cache de taxonomia inteiro — proxima
 * classificacao reflete imediatamente.
 */
import { useEffect, useState } from "react";
import {
  Filter,
  Layers,
  Loader2,
  CheckCircle2,
  AlertCircle,
} from "lucide-react";
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

interface State {
  enabled: boolean;
  description: string;
}

const ENDPOINT = "/api/v1/admin/template-driven-taxonomy/settings";

export function TemplateDrivenTaxonomyCard() {
  const { toast } = useToast();
  const [state, setState] = useState<State | null>(null);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const res = await apiFetch(ENDPOINT);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setState((await res.json()) as State);
    } catch (err: any) {
      toast({
        title: "Falha lendo modo árvore enxuta",
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

  const apply = async (enabled: boolean) => {
    setSubmitting(true);
    try {
      const res = await apiFetch(ENDPOINT, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(
          (typeof data?.detail === "string" && data.detail) ||
            "Falha ao atualizar.",
        );
      }
      setState((await res.json()) as State);
      toast({
        title: enabled ? "Modo enxuto ativado" : "Modo enxuto desativado",
        description: enabled
          ? "IA agora vê apenas cats com template do escritório."
          : "IA voltou a ver a árvore completa filtrada por polo/versão.",
      });
    } catch (err: any) {
      toast({
        title: "Erro",
        description: err?.message || String(err),
        variant: "destructive",
      });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {state?.enabled ? (
            <Filter className="h-5 w-5 text-green-600" />
          ) : (
            <Layers className="h-5 w-5 text-muted-foreground" />
          )}
          Modo árvore enxuta (template-driven)
          {state && (
            <Badge
              variant={state.enabled ? "default" : "secondary"}
              className={
                state.enabled
                  ? "bg-green-600 hover:bg-green-700"
                  : ""
              }
            >
              {state.enabled ? "ativo" : "desligado"}
            </Badge>
          )}
        </CardTitle>
        <CardDescription>
          Quando ativo, a IA só vê categorias que têm pelo menos um{" "}
          <Link
            to="/publications/templates"
            className="underline hover:text-foreground"
          >
            template ativo
          </Link>{" "}
          do escritório (ou global). Sem template = cat fica fora do
          prompt. Categorias <em>"Para Análise"</em> sempre aparecem
          (catch-all). Granularidade grossa: 1 template na cat libera
          a categoria inteira.
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
            <div className="text-sm flex items-start gap-2 p-3 rounded-md border bg-muted/30">
              {state.enabled ? (
                <CheckCircle2 className="h-4 w-4 text-green-600 shrink-0 mt-0.5" />
              ) : (
                <AlertCircle className="h-4 w-4 text-muted-foreground shrink-0 mt-0.5" />
              )}
              <span>{state.description}</span>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              {state.enabled ? (
                <AlertDialog>
                  <AlertDialogTrigger asChild>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={submitting}
                    >
                      Desligar (voltar a árvore completa)
                    </Button>
                  </AlertDialogTrigger>
                  <AlertDialogContent>
                    <AlertDialogHeader>
                      <AlertDialogTitle>
                        Desligar modo árvore enxuta?
                      </AlertDialogTitle>
                      <AlertDialogDescription>
                        A IA voltará a enxergar a árvore inteira (filtrada
                        apenas por polo/versão). Vai propor classificações
                        em cats sem template — você verá no painel de
                        publicações sem proposta automática.
                        <br />
                        <br />
                        Pode reativar a qualquer momento sem efeito
                        colateral.
                      </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                      <AlertDialogCancel>Cancelar</AlertDialogCancel>
                      <AlertDialogAction onClick={() => apply(false)}>
                        Desligar
                      </AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              ) : (
                <Button
                  size="sm"
                  onClick={() => apply(true)}
                  disabled={submitting}
                >
                  {submitting ? (
                    <Loader2 className="h-4 w-4 mr-1 animate-spin" />
                  ) : null}
                  Ligar modo árvore enxuta
                </Button>
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
          </>
        ) : null}
      </CardContent>
    </Card>
  );
}

export default TemplateDrivenTaxonomyCard;
