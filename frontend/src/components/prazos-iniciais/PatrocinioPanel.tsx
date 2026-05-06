import { useCallback, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Edit3,
  Loader2,
  Scale,
  XCircle,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
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
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/ui/use-toast";
import {
  encaminharIntakeParaDevolucao,
  patchPrazoInicialPatrocinio,
} from "@/services/api";
import type {
  PrazoInicialPatrocinio,
  PrazoInicialPatrocinioPatch,
} from "@/types/api";


const DECISAO_LABEL: Record<string, string> = {
  MDR_ADVOCACIA: "MDR Advocacia",
  OUTRO_ESCRITORIO: "Outro escritório",
  CONDUCAO_INTERNA: "Condução interna",
};

const DECISAO_BADGE_CLASS: Record<string, string> = {
  MDR_ADVOCACIA: "bg-emerald-50 text-emerald-800 border-emerald-300",
  OUTRO_ESCRITORIO: "bg-orange-50 text-orange-800 border-orange-300",
  CONDUCAO_INTERNA: "bg-blue-50 text-blue-800 border-blue-300",
};

const NATUREZA_LABEL: Record<string, string> = {
  CONSUMERISTA: "Consumerista",
  CIVIL_PUBLICA: "Ação civil pública",
  INQUERITO_ADMINISTRATIVO: "Inquérito / administrativo",
  TRABALHISTA: "Trabalhista",
  OUTRO: "Outro",
};

const REVIEW_LABEL: Record<string, string> = {
  pendente: "Pendente",
  aprovado: "Aprovado",
  editado: "Editado",
  rejeitado: "Rejeitado",
};

const REVIEW_BADGE_VARIANT: Record<string, "default" | "outline" | "secondary"> = {
  pendente: "outline",
  aprovado: "default",
  editado: "secondary",
  rejeitado: "outline",
};


function formatDate(d: string | null | undefined): string {
  if (!d) return "—";
  try {
    return new Date(`${d}T00:00:00`).toLocaleDateString("pt-BR");
  } catch {
    return d;
  }
}


interface Props {
  patrocinio: PrazoInicialPatrocinio;
  onUpdated: (next: PrazoInicialPatrocinio) => void;
}


/**
 * Painel HITL pra revisar a decisão de patrocínio gerada pela IA.
 *
 * Estados:
 * - read-only padrão (mostra dados + botões aprovar/editar/rejeitar)
 * - modo edição (formulário com campos editáveis)
 *
 * Pin018: análise paralela à classificação de prazos. Não cria task,
 * só registra decisão pra fila de devolução / relatório.
 */
export function PatrocinioPanel({ patrocinio, onUpdated }: Props) {
  const { toast } = useToast();
  const [editing, setEditing] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  // Form state — inicializa com os valores atuais
  const [decisao, setDecisao] = useState(patrocinio.decisao);
  const [naturezaAcao, setNaturezaAcao] = useState(patrocinio.natureza_acao || "");
  const [outroEscritorio, setOutroEscritorio] = useState(
    patrocinio.outro_escritorio_nome || "",
  );
  const [outroAdvogadoNome, setOutroAdvogadoNome] = useState(
    patrocinio.outro_advogado_nome || "",
  );
  const [outroAdvogadoOab, setOutroAdvogadoOab] = useState(
    patrocinio.outro_advogado_oab || "",
  );
  const [outroAdvogadoData, setOutroAdvogadoData] = useState(
    patrocinio.outro_advogado_data_habilitacao || "",
  );
  const [suspeitaDevolucao, setSuspeitaDevolucao] = useState(
    patrocinio.suspeita_devolucao,
  );
  const [motivoSuspeita, setMotivoSuspeita] = useState(
    patrocinio.motivo_suspeita || "",
  );
  const [poloPassivoConfirmado, setPoloPassivoConfirmado] = useState(
    patrocinio.polo_passivo_confirmado,
  );
  const [poloPassivoObservacao, setPoloPassivoObservacao] = useState(
    patrocinio.polo_passivo_observacao || "",
  );

  const handleAction = useCallback(
    async (action: "aprovado" | "editado" | "rejeitado") => {
      setSubmitting(true);
      try {
        // Caso especial: aprovacao quando ha suspeita de devolucao na
        // sugestao da IA. Em vez de so carimbar review_status=aprovado,
        // dispara o fluxo completo de devolucao — marca patrocinio
        // aprovado, transiciona intake pra DEVOLUCAO_PENDENTE,
        // dispatch_pending=True (worker cancela legada + GED) e
        // enfileira AJUS com cod_andamento.is_devolucao=True. Tudo na
        // mesma transacao do backend.
        if (action === "aprovado" && patrocinio.suspeita_devolucao) {
          await encaminharIntakeParaDevolucao(
            patrocinio.intake_id,
            patrocinio.motivo_suspeita || undefined,
          );
          toast({
            title: "Patrocínio aprovado e encaminhado p/ devolução",
            description:
              "Caso entrou na fila do AJUS e o worker vai cancelar a task legada do L1 + subir habilitação no GED.",
          });
          // Forca refresh da pagina pai pra puxar o estado novo
          // (intake.status, ajus_queue, dispatch_pending). O backend
          // tambem atualizou o patrocinio (review_status=aprovado).
          onUpdated({
            ...patrocinio,
            review_status: "aprovado",
            reviewed_at: new Date().toISOString(),
          });
          setEditing(false);
          return;
        }
        const payload: PrazoInicialPatrocinioPatch = { review_action: action };
        if (action === "editado") {
          payload.decisao = decisao as PrazoInicialPatrocinioPatch["decisao"];
          payload.natureza_acao = (naturezaAcao ||
            undefined) as PrazoInicialPatrocinioPatch["natureza_acao"];
          payload.outro_escritorio_nome = outroEscritorio || null;
          payload.outro_advogado_nome = outroAdvogadoNome || null;
          payload.outro_advogado_oab = outroAdvogadoOab || null;
          payload.outro_advogado_data_habilitacao = outroAdvogadoData || null;
          payload.suspeita_devolucao = suspeitaDevolucao;
          payload.motivo_suspeita = motivoSuspeita || null;
          payload.polo_passivo_confirmado = poloPassivoConfirmado;
          payload.polo_passivo_observacao = poloPassivoObservacao || null;
        }
        const result = await patchPrazoInicialPatrocinio(
          patrocinio.intake_id,
          payload,
        );
        toast({
          title:
            action === "aprovado"
              ? "Patrocínio aprovado"
              : action === "editado"
                ? "Patrocínio editado"
                : "Patrocínio rejeitado",
        });
        onUpdated(result);
        setEditing(false);
      } catch (err) {
        const msg = err instanceof Error ? err.message : "Erro desconhecido";
        toast({
          title: "Falha ao atualizar patrocínio",
          description: msg,
          variant: "destructive",
        });
      } finally {
        setSubmitting(false);
      }
    },
    [
      patrocinio.intake_id,
      decisao,
      naturezaAcao,
      outroEscritorio,
      outroAdvogadoNome,
      outroAdvogadoOab,
      outroAdvogadoData,
      suspeitaDevolucao,
      motivoSuspeita,
      poloPassivoConfirmado,
      poloPassivoObservacao,
      toast,
      onUpdated,
    ],
  );

  const showOutroAdvogadoFields =
    decisao === "OUTRO_ESCRITORIO" || suspeitaDevolucao;

  return (
    <div className="space-y-4 rounded-lg border bg-card p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <Scale className="h-4 w-4 text-muted-foreground" />
            <h3 className="text-base font-semibold">Patrocínio</h3>
            <Badge
              variant={REVIEW_BADGE_VARIANT[patrocinio.review_status] || "outline"}
              className="text-xs"
            >
              {REVIEW_LABEL[patrocinio.review_status] || patrocinio.review_status}
            </Badge>
          </div>
          <p className="text-xs text-muted-foreground">
            Análise paralela — não interfere em tasks. Decida quem patrocina o
            caso e marque pra devolução se não for nosso.
          </p>
        </div>
        {patrocinio.review_status === "pendente" && !editing ? (
          <div className="flex shrink-0 gap-2">
            <Button
              size="sm"
              variant="default"
              disabled={submitting}
              onClick={() => handleAction("aprovado")}
              title={
                patrocinio.suspeita_devolucao
                  ? "Aprova diagnostico + encaminha caso pra fila de devolucao do AJUS (cancela legada do L1, sobe GED, manda AJUS)."
                  : "Confirma a decisao de patrocinio sem alterar campos."
              }
            >
              <CheckCircle2 className="mr-1 h-4 w-4" />
              {patrocinio.suspeita_devolucao
                ? "Aprovar e encaminhar p/ devolução"
                : "Aprovar"}
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={submitting}
              onClick={() => setEditing(true)}
            >
              <Edit3 className="mr-1 h-4 w-4" />
              Editar
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="text-red-700 hover:bg-red-50"
              disabled={submitting}
              onClick={() => handleAction("rejeitado")}
            >
              <XCircle className="mr-1 h-4 w-4" />
              Rejeitar
            </Button>
          </div>
        ) : null}
        {editing ? (
          <div className="flex shrink-0 gap-2">
            <Button
              size="sm"
              variant="outline"
              disabled={submitting}
              onClick={() => setEditing(false)}
            >
              Cancelar
            </Button>
            <Button
              size="sm"
              variant="default"
              disabled={submitting}
              onClick={() => handleAction("editado")}
            >
              {submitting ? (
                <Loader2 className="mr-1 h-4 w-4 animate-spin" />
              ) : (
                <CheckCircle2 className="mr-1 h-4 w-4" />
              )}
              Salvar edição
            </Button>
          </div>
        ) : null}
      </div>

      <Separator />

      {patrocinio.suspeita_devolucao ? (
        <div className="flex gap-2 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm">
          <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5 text-amber-700" />
          <div>
            <div className="font-medium text-amber-900">Suspeita de devolução</div>
            <div className="text-xs text-amber-800">
              {patrocinio.motivo_suspeita || "Sem justificativa registrada."}
            </div>
          </div>
        </div>
      ) : null}

      {!editing ? (
        <div className="space-y-3">
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <div>
              <div className="text-xs uppercase tracking-wide text-muted-foreground">
                Decisão
              </div>
              <Badge
                variant="outline"
                className={
                  "mt-1 " + (DECISAO_BADGE_CLASS[patrocinio.decisao] || "")
                }
              >
                {DECISAO_LABEL[patrocinio.decisao] || patrocinio.decisao}
              </Badge>
            </div>
            <div>
              <div className="text-xs uppercase tracking-wide text-muted-foreground">
                Natureza da ação
              </div>
              <div className="mt-1 text-sm">
                {NATUREZA_LABEL[patrocinio.natureza_acao || ""] ||
                  patrocinio.natureza_acao ||
                  "—"}
              </div>
            </div>
          </div>

          {patrocinio.outro_advogado_nome ||
          patrocinio.outro_escritorio_nome ? (
            <div className="rounded-md border border-muted bg-muted/30 p-3 text-sm">
              <div className="text-xs uppercase tracking-wide text-muted-foreground">
                Outro escritório / advogado
              </div>
              {patrocinio.outro_escritorio_nome ? (
                <div>{patrocinio.outro_escritorio_nome}</div>
              ) : null}
              {patrocinio.outro_advogado_nome ? (
                <div>
                  {patrocinio.outro_advogado_nome}
                  {patrocinio.outro_advogado_oab
                    ? ` · ${patrocinio.outro_advogado_oab}`
                    : ""}
                  {patrocinio.outro_advogado_data_habilitacao
                    ? ` · habilitado em ${formatDate(
                        patrocinio.outro_advogado_data_habilitacao,
                      )}`
                    : ""}
                </div>
              ) : null}
            </div>
          ) : null}

          {!patrocinio.polo_passivo_confirmado ? (
            <div className="rounded-md border border-orange-300 bg-orange-50 p-3 text-xs text-orange-900">
              <strong>Polo passivo divergente entre capa e PI.</strong>
              {patrocinio.polo_passivo_observacao
                ? " " + patrocinio.polo_passivo_observacao
                : ""}
            </div>
          ) : null}

          {patrocinio.fundamentacao ? (
            <div>
              <div className="text-xs uppercase tracking-wide text-muted-foreground">
                Fundamentação da IA
                {patrocinio.confianca
                  ? ` · confiança ${patrocinio.confianca}`
                  : ""}
              </div>
              <p className="mt-1 whitespace-pre-wrap text-sm text-muted-foreground">
                {patrocinio.fundamentacao}
              </p>
            </div>
          ) : null}

          {patrocinio.reviewed_by_name ? (
            <div className="text-xs text-muted-foreground">
              Revisado por <strong>{patrocinio.reviewed_by_name}</strong>
              {patrocinio.reviewed_at
                ? " em " +
                  new Date(patrocinio.reviewed_at).toLocaleString("pt-BR")
                : ""}
            </div>
          ) : null}
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <div className="space-y-1">
            <Label className="text-xs uppercase tracking-wide text-muted-foreground">
              Decisão
            </Label>
            <Select value={decisao} onValueChange={setDecisao}>
              <SelectTrigger className="h-9 text-sm">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="MDR_ADVOCACIA">MDR Advocacia</SelectItem>
                <SelectItem value="OUTRO_ESCRITORIO">Outro escritório</SelectItem>
                <SelectItem value="CONDUCAO_INTERNA">Condução interna</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1">
            <Label className="text-xs uppercase tracking-wide text-muted-foreground">
              Natureza da ação
            </Label>
            <Select value={naturezaAcao} onValueChange={setNaturezaAcao}>
              <SelectTrigger className="h-9 text-sm">
                <SelectValue placeholder="Selecione" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="CONSUMERISTA">Consumerista</SelectItem>
                <SelectItem value="CIVIL_PUBLICA">Ação civil pública</SelectItem>
                <SelectItem value="INQUERITO_ADMINISTRATIVO">
                  Inquérito / administrativo
                </SelectItem>
                <SelectItem value="TRABALHISTA">Trabalhista</SelectItem>
                <SelectItem value="OUTRO">Outro</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {showOutroAdvogadoFields ? (
            <>
              <div className="space-y-1">
                <Label className="text-xs uppercase tracking-wide text-muted-foreground">
                  Outro escritório (nome)
                </Label>
                <Input
                  className="h-9 text-sm"
                  value={outroEscritorio}
                  onChange={(e) => setOutroEscritorio(e.target.value)}
                  placeholder="Pinheiro Neto, Mattos Filho..."
                />
              </div>
              <div className="space-y-1">
                <Label className="text-xs uppercase tracking-wide text-muted-foreground">
                  Outro advogado (nome)
                </Label>
                <Input
                  className="h-9 text-sm"
                  value={outroAdvogadoNome}
                  onChange={(e) => setOutroAdvogadoNome(e.target.value)}
                />
              </div>
              <div className="space-y-1">
                <Label className="text-xs uppercase tracking-wide text-muted-foreground">
                  OAB
                </Label>
                <Input
                  className="h-9 text-sm"
                  value={outroAdvogadoOab}
                  onChange={(e) => setOutroAdvogadoOab(e.target.value)}
                  placeholder="OAB/SP 123.456"
                />
              </div>
              <div className="space-y-1">
                <Label className="text-xs uppercase tracking-wide text-muted-foreground">
                  Data de habilitação
                </Label>
                <Input
                  type="date"
                  className="h-9 text-sm"
                  value={outroAdvogadoData}
                  onChange={(e) => setOutroAdvogadoData(e.target.value)}
                />
              </div>
            </>
          ) : null}

          <div className="space-y-1 md:col-span-2">
            <div className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={suspeitaDevolucao}
                onChange={(e) => setSuspeitaDevolucao(e.target.checked)}
                className="h-4 w-4"
                id="suspeita-checkbox"
              />
              <Label
                htmlFor="suspeita-checkbox"
                className="text-sm font-medium"
              >
                Suspeita de devolução
              </Label>
            </div>
            {suspeitaDevolucao ? (
              <Textarea
                className="text-sm"
                rows={2}
                value={motivoSuspeita}
                onChange={(e) => setMotivoSuspeita(e.target.value)}
                placeholder="Justificativa da devolução"
              />
            ) : null}
          </div>

          <div className="space-y-1 md:col-span-2">
            <div className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={poloPassivoConfirmado}
                onChange={(e) => setPoloPassivoConfirmado(e.target.checked)}
                className="h-4 w-4"
                id="polo-checkbox"
              />
              <Label htmlFor="polo-checkbox" className="text-sm font-medium">
                Polo passivo confirmado pela petição inicial
              </Label>
            </div>
            {!poloPassivoConfirmado ? (
              <Textarea
                className="text-sm"
                rows={2}
                value={poloPassivoObservacao}
                onChange={(e) => setPoloPassivoObservacao(e.target.value)}
                placeholder="Observação sobre divergência"
              />
            ) : null}
          </div>
        </div>
      )}
    </div>
  );
}

export default PatrocinioPanel;
