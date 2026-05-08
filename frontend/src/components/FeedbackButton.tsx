import { useContext, useState } from "react";
import { Bot, Bug, HelpCircle, Lightbulb, Loader2, MessageCircle, Sparkles, Send } from "lucide-react";

import { AuthContext } from "@/contexts/AuthContext";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/hooks/use-toast";
import { createUserFeedback } from "@/services/api";
import type { UserFeedbackCategory } from "@/types/api";

/**
 * Botao flutuante (canto inferior direito) que abre um modal pra
 * usuario mandar feedback livre pra equipe. Aparece em toda pagina
 * autenticada — fica oculto na tela de login. Captura page_url +
 * user_agent automaticamente pra ajudar o admin a contextualizar
 * bug reports sem precisar perguntar "em qual tela?".
 *
 * Visual "liquid glass": backdrop-blur + cor translucida + borda sutil
 * + shadow longa. Tamanho moderado (h-12 w-12 = 48px) pra nao
 * atrapalhar a operacao em telas pequenas.
 *
 * 5 categorias fixas (alinhadas com o backend): bug, sugestao, duvida,
 * elogio, outro. Editar em conjunto com FEEDBACK_CATEGORIES_VALIDAS
 * em app/models/user_feedback.py.
 */

interface CategoryOption {
  value: UserFeedbackCategory;
  label: string;
  description: string;
  Icon: React.ComponentType<{ className?: string }>;
  iconColor: string;
}

const CATEGORIES: CategoryOption[] = [
  {
    value: "bug",
    label: "Bug / problema",
    description: "Algo nao funcionou como esperado",
    Icon: Bug,
    iconColor: "text-red-600",
  },
  {
    value: "sugestao",
    label: "Sugestao",
    description: "Ideia de melhoria ou recurso novo",
    Icon: Lightbulb,
    iconColor: "text-amber-600",
  },
  {
    value: "duvida",
    label: "Duvida",
    description: "Pergunta sobre como usar ou onde achar algo",
    Icon: HelpCircle,
    iconColor: "text-blue-600",
  },
  {
    value: "elogio",
    label: "Elogio",
    description: "Algo legal aconteceu, conta pra gente",
    Icon: Sparkles,
    iconColor: "text-emerald-600",
  },
  {
    value: "outro",
    label: "Outro",
    description: "Nao se encaixa nas opcoes acima",
    Icon: MessageCircle,
    iconColor: "text-slate-600",
  },
];

const MIN_MESSAGE_LEN = 10;

export function FeedbackButton() {
  const auth = useContext(AuthContext);
  const isAuthenticated = auth?.isAuthenticated ?? false;
  const { toast } = useToast();

  const [open, setOpen] = useState(false);
  const [category, setCategory] = useState<UserFeedbackCategory | null>(null);
  const [message, setMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);

  if (!isAuthenticated) return null;

  const reset = () => {
    setCategory(null);
    setMessage("");
  };

  const handleClose = (next: boolean) => {
    if (submitting) return;
    setOpen(next);
    if (!next) reset();
  };

  const handleSubmit = async () => {
    if (!category) {
      toast({
        title: "Escolha uma categoria",
        description: "Marque o tipo do feedback antes de enviar.",
        variant: "destructive",
      });
      return;
    }
    const trimmed = message.trim();
    if (trimmed.length < MIN_MESSAGE_LEN) {
      toast({
        title: "Mensagem muito curta",
        description: `Conta um pouco mais (minimo ${MIN_MESSAGE_LEN} caracteres) pra equipe entender.`,
        variant: "destructive",
      });
      return;
    }
    setSubmitting(true);
    try {
      await createUserFeedback({
        category,
        message: trimmed,
        page_url: typeof window !== "undefined" ? window.location.href : null,
        user_agent: typeof navigator !== "undefined" ? navigator.userAgent : null,
      });
      toast({
        title: "Feedback enviado!",
        description: "Obrigado — a equipe vai dar uma olhada.",
      });
      setOpen(false);
      reset();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Falha ao enviar.";
      toast({
        title: "Nao consegui enviar",
        description: msg,
        variant: "destructive",
      });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      {/*
        Botao flutuante — liquid glass.
        - fixed bottom-5 right-5: longe das bordas, nao gruda na quina.
        - h-12 w-12 (48px): visivel mas nao atrapalha a operacao.
        - backdrop-blur-xl + bg-white/40: efeito de vidro fosco.
        - shadow-2xl + ring sutil: profundidade que destaca da pagina.
        - z-40: abaixo do AdminNoticeBar (z-50) e de Dialogs (z-50+).
      */}
      <button
        type="button"
        aria-label="Mandar feedback pra equipe"
        title="Mandar feedback pra equipe"
        onClick={() => setOpen(true)}
        className="
          fixed bottom-5 right-5 z-40
          flex h-12 w-12 items-center justify-center
          rounded-full
          bg-white/40 backdrop-blur-xl
          border border-white/60
          shadow-[0_8px_32px_rgba(31,38,135,0.25)]
          ring-1 ring-black/5
          text-blue-700
          transition-all duration-200
          hover:scale-105 hover:bg-white/55 hover:shadow-[0_12px_40px_rgba(31,38,135,0.35)]
          active:scale-95
          focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500
        "
      >
        <Bot className="h-6 w-6" />
      </button>

      <Dialog open={open} onOpenChange={handleClose}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Bot className="h-5 w-5 text-blue-600" />
              Mandar feedback pra equipe
            </DialogTitle>
            <DialogDescription>
              Escreva livre — bug, sugestao, duvida, qualquer coisa.
              A pagina atual e o navegador sao registrados automaticamente
              pra ajudar a equipe a entender o contexto.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-2">
            <div>
              <Label className="text-xs">Tipo *</Label>
              <div className="mt-1.5 grid grid-cols-1 gap-1.5 sm:grid-cols-2">
                {CATEGORIES.map((opt) => {
                  const { Icon } = opt;
                  const selected = category === opt.value;
                  return (
                    <button
                      key={opt.value}
                      type="button"
                      onClick={() => setCategory(opt.value)}
                      className={`
                        flex items-start gap-2 rounded-lg border px-3 py-2 text-left
                        transition-colors
                        ${selected
                          ? "border-blue-500 bg-blue-50"
                          : "border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50"}
                      `}
                    >
                      <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${opt.iconColor}`} />
                      <div className="min-w-0">
                        <div className="text-sm font-medium">{opt.label}</div>
                        <div className="text-[11px] text-muted-foreground">
                          {opt.description}
                        </div>
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>

            <div>
              <Label className="text-xs">Mensagem *</Label>
              <Textarea
                rows={5}
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                placeholder="Descreva o que aconteceu, o que voce esperava, ou o que sugere..."
                maxLength={5000}
                disabled={submitting}
              />
              <div className="mt-0.5 flex justify-between text-[10px] text-muted-foreground">
                <span>Minimo {MIN_MESSAGE_LEN} caracteres.</span>
                <span>{message.length} / 5000</span>
              </div>
            </div>
          </div>

          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => handleClose(false)}
              disabled={submitting}
            >
              Cancelar
            </Button>
            <Button onClick={handleSubmit} disabled={submitting}>
              {submitting ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Send className="mr-2 h-4 w-4" />
              )}
              Enviar feedback
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

export default FeedbackButton;
