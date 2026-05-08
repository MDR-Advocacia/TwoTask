import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Inbox,
  Loader2,
  Play,
  RefreshCw,
  Search,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { useToast } from "@/hooks/use-toast";
import {
  dispatchPrazoInicialPendingBatch,
  fetchPrazosIniciaisLegacyTaskCancelQueue,
  fetchPrazosIniciaisLegacyTaskCancelQueueMetrics,
  processPrazosIniciaisLegacyTaskCancelQueue,
  reprocessPrazosIniciaisLegacyTaskCancelItem,
} from "@/services/api";
import type {
  PrazoInicialLegacyTaskCancelQueueItem,
  PrazoInicialLegacyTaskQueueMetrics,
} from "@/types/api";

/**
 * Versao "operador" da tela Tratamento Web. Foco: 1 acao por vez,
 * vocabulario simples, zero jargao tecnico. A versao admin/debug
 * com filtros, metricas, zumbis e tabela completa esta' em
 * `/prazos-iniciais/treatment/detalhes` (PrazosIniciaisTreatmentPage).
 */

// ── Reasons em portugues operacional (sem jargao tecnico) ──────────────
function reasonHumano(reason: string | null | undefined): string {
  if (!reason) return "Não foi possível processar agora.";
  const labels: Record<string, string> = {
    auth_failure: "O Legal One não autenticou. Vou tentar de novo em breve.",
    timeout: "O Legal One está demorando. Vou tentar de novo em breve.",
    layout_drift: "A tela do Legal One mudou. Avise o coordenador.",
    runner_error: "Erro inesperado. O sistema vai tentar de novo automaticamente.",
    verification_failed: "O cancelamento não persistiu. Vou tentar de novo.",
    task_not_found: "Tarefa não encontrada no Legal One (talvez já tenha sido apagada).",
    lawsuit_not_found: "Processo não cadastrado no Legal One.",
    exception: "Erro inesperado. Avise o coordenador se continuar.",
  };
  return labels[reason] || `Outro motivo (${reason})`;
}

function formatCnj(value: string | null | undefined): string {
  if (!value) return "—";
  const digits = value.replace(/\D/g, "");
  if (digits.length !== 20) return value;
  return `${digits.slice(0, 7)}-${digits.slice(7, 9)}.${digits.slice(9, 13)}.${digits.slice(13, 14)}.${digits.slice(14, 16)}.${digits.slice(16)}`;
}

// ── Tipo de estado visual ──────────────────────────────────────────────
type Estado = "carregando" | "vazio" | "pendentes" | "processando" | "falhas";

const POLL_INTERVAL_MS = 5000;

export default function PrazosIniciaisTreatmentPageOperator() {
  const { toast } = useToast();

  // Estado de dados
  const [items, setItems] = useState<PrazoInicialLegacyTaskCancelQueueItem[]>([]);
  const [metrics, setMetrics] = useState<PrazoInicialLegacyTaskQueueMetrics | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);

  // Estado de acoes em andamento (so 1 acao por vez pra nao confundir)
  const [acaoEmCurso, setAcaoEmCurso] = useState<
    null | "buscando" | "processando" | "tentando_de_novo"
  >(null);

  // Pra evitar polling racing com a propria acao do operador
  const acaoEmCursoRef = useRef(acaoEmCurso);
  acaoEmCursoRef.current = acaoEmCurso;

  // ── Carga inicial + auto-refresh ───────────────────────────────────
  const carregarDados = async () => {
    try {
      // Pega 25 items mais recentes — suficiente pra exibir top falhas/pending.
      const [payload, metricsPayload] = await Promise.all([
        fetchPrazosIniciaisLegacyTaskCancelQueue({ limit: 50, offset: 0 }),
        fetchPrazosIniciaisLegacyTaskCancelQueueMetrics(24).catch(() => null),
      ]);
      setItems(payload.items);
      setMetrics(metricsPayload);
      setErro(null);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erro ao carregar a página.";
      setErro(msg);
    } finally {
      setCarregando(false);
    }
  };

  useEffect(() => {
    carregarDados();
    const intervalId = setInterval(() => {
      // Pula refresh enquanto operador esta executando uma acao —
      // evita race com optimistic update.
      if (acaoEmCursoRef.current) return;
      carregarDados();
    }, POLL_INTERVAL_MS);
    return () => clearInterval(intervalId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Contadores derivados (do /metrics, fonte da verdade global) ────
  const contagens = useMemo(() => {
    const totals = metrics?.totals_by_status ?? {};
    const pendentes = (totals.PENDENTE ?? 0) + (totals.FALHA ?? 0);
    const processando = totals.PROCESSANDO ?? 0;
    const concluidos = totals.CONCLUIDO ?? 0;
    const falhas = totals.FALHA ?? 0;
    const cancelados = totals.CANCELADO ?? 0;
    const totalGeral = pendentes + processando + concluidos + cancelados;
    const progresso = totalGeral > 0 ? Math.round((concluidos / totalGeral) * 100) : 0;
    return { pendentes, processando, concluidos, falhas, cancelados, totalGeral, progresso };
  }, [metrics]);

  // ── Listas derivadas ───────────────────────────────────────────────
  const itensFalha = useMemo(
    () => items.filter((it) => it.queue_status === "FALHA"),
    [items],
  );
  const ultimosConcluidos = useMemo(
    () =>
      items
        .filter((it) => it.queue_status === "CONCLUIDO")
        .slice(0, 3),
    [items],
  );

  // ── Estado visual da tela ──────────────────────────────────────────
  const estado: Estado = carregando
    ? "carregando"
    : acaoEmCurso === "processando" || acaoEmCurso === "tentando_de_novo" || contagens.processando > 0
      ? "processando"
      : contagens.falhas > 0
        ? "falhas"
        : contagens.pendentes > 0
          ? "pendentes"
          : "vazio";

  // ── Acoes ──────────────────────────────────────────────────────────
  const handleBuscarNovos = async () => {
    setAcaoEmCurso("buscando");
    try {
      const result = await dispatchPrazoInicialPendingBatch(100);
      const novos = result.success_count ?? 0;
      if (novos === 0 && (result.candidates ?? 0) === 0) {
        toast({
          title: "Nenhum processo novo",
          description: "Não havia processos esperando pra entrar na fila.",
        });
      } else {
        toast({
          title: `${novos} processo${novos === 1 ? "" : "s"} adicionado${novos === 1 ? "" : "s"} à fila`,
          description: "O sistema já vai começar a processar. Aguarde alguns segundos.",
        });
      }
      await carregarDados();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Falha ao buscar processos novos.";
      toast({ title: "Não foi possível buscar agora", description: msg, variant: "destructive" });
    } finally {
      setAcaoEmCurso(null);
    }
  };

  const handleProcessarAgora = async () => {
    setAcaoEmCurso("processando");
    try {
      await processPrazosIniciaisLegacyTaskCancelQueue(20);
      toast({
        title: "Processamento iniciado",
        description: "Aguarde alguns segundos. A página atualiza sozinha.",
      });
      await carregarDados();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Falha ao processar a fila.";
      toast({ title: "Não foi possível processar agora", description: msg, variant: "destructive" });
    } finally {
      setAcaoEmCurso(null);
    }
  };

  const handleTentarTodasDeNovo = async () => {
    if (itensFalha.length === 0) return;
    setAcaoEmCurso("tentando_de_novo");
    try {
      // Itera em sequencia pra nao estourar o L1 (cada reprocess re-enfileira
      // pro proximo tick do worker; o worker em si serializa).
      let sucesso = 0;
      let falha = 0;
      for (const item of itensFalha) {
        try {
          await reprocessPrazosIniciaisLegacyTaskCancelItem(item.id);
          sucesso += 1;
        } catch {
          falha += 1;
        }
      }
      toast({
        title: `${sucesso} processo${sucesso === 1 ? "" : "s"} re-agendado${sucesso === 1 ? "" : "s"}`,
        description:
          falha > 0
            ? `${falha} não foi possível re-agendar agora. A página atualiza em alguns segundos.`
            : "O sistema vai tentar de novo automaticamente. A página atualiza em alguns segundos.",
        variant: falha > 0 ? "destructive" : undefined,
      });
      await carregarDados();
    } finally {
      setAcaoEmCurso(null);
    }
  };

  // ── Render ─────────────────────────────────────────────────────────

  return (
    <div className="mx-auto max-w-3xl space-y-6 py-6">
      <header>
        <h1 className="text-2xl font-bold tracking-tight">Tratamento Web</h1>
        <p className="text-sm text-muted-foreground">
          Esse painel cancela tarefas antigas no Legal One assim que processos novos chegam.
        </p>
      </header>

      {erro ? (
        <Card className="border-red-200 bg-red-50">
          <CardContent className="pt-6">
            <p className="text-sm text-red-900">
              <AlertTriangle className="mr-2 inline-block h-4 w-4" />
              Não consegui carregar a página: {erro}
            </p>
            <p className="mt-2 text-xs text-red-900/80">
              Tente atualizar daqui a alguns segundos. Se continuar, avise o coordenador.
            </p>
          </CardContent>
        </Card>
      ) : null}

      {/* Card principal — muda conforme o estado */}
      {estado === "carregando" ? (
        <CardCarregando />
      ) : estado === "vazio" ? (
        <CardVazio
          onBuscarNovos={handleBuscarNovos}
          buscando={acaoEmCurso === "buscando"}
        />
      ) : estado === "pendentes" ? (
        <CardPendentes
          quantidade={contagens.pendentes}
          ultimosConcluidos={ultimosConcluidos}
          onProcessarAgora={handleProcessarAgora}
          processando={acaoEmCurso === "processando"}
          onBuscarNovos={handleBuscarNovos}
          buscando={acaoEmCurso === "buscando"}
        />
      ) : estado === "processando" ? (
        <CardProcessando
          processando={contagens.processando}
          concluidos={contagens.concluidos}
          totalGeral={contagens.totalGeral}
          progresso={contagens.progresso}
        />
      ) : (
        <CardFalhas
          itensFalha={itensFalha}
          onTentarTodasDeNovo={handleTentarTodasDeNovo}
          tentando={acaoEmCurso === "tentando_de_novo"}
          onBuscarNovos={handleBuscarNovos}
          buscando={acaoEmCurso === "buscando"}
        />
      )}

      <div className="flex justify-end">
        <Link
          to="/prazos-iniciais/treatment/detalhes"
          className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
        >
          Ver detalhes técnicos
          <ArrowRight className="h-3 w-3" />
        </Link>
      </div>
    </div>
  );
}

// ── Sub-componentes por estado ──────────────────────────────────────────

function CardCarregando() {
  return (
    <Card>
      <CardContent className="flex items-center justify-center py-16 text-muted-foreground">
        <Loader2 className="mr-2 h-5 w-5 animate-spin" />
        Carregando…
      </CardContent>
    </Card>
  );
}

function CardVazio({
  onBuscarNovos,
  buscando,
}: {
  onBuscarNovos: () => void;
  buscando: boolean;
}) {
  return (
    <Card className="border-green-200 bg-green-50/40">
      <CardHeader className="text-center">
        <div className="mx-auto mb-2 flex h-14 w-14 items-center justify-center rounded-full bg-green-100">
          <CheckCircle2 className="h-8 w-8 text-green-700" />
        </div>
        <CardTitle className="text-lg">Tudo em ordem</CardTitle>
        <CardDescription>
          Nenhum processo aguardando agora. A fila se atualiza sozinha.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex justify-center">
        <Button variant="outline" size="sm" onClick={onBuscarNovos} disabled={buscando}>
          {buscando ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <Search className="mr-2 h-4 w-4" />
          )}
          Buscar processos novos
        </Button>
      </CardContent>
    </Card>
  );
}

function CardPendentes({
  quantidade,
  ultimosConcluidos,
  onProcessarAgora,
  processando,
  onBuscarNovos,
  buscando,
}: {
  quantidade: number;
  ultimosConcluidos: PrazoInicialLegacyTaskCancelQueueItem[];
  onProcessarAgora: () => void;
  processando: boolean;
  onBuscarNovos: () => void;
  buscando: boolean;
}) {
  return (
    <Card className="border-blue-200 bg-blue-50/40">
      <CardHeader>
        <div className="flex items-start gap-3">
          <div className="mt-1 flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-blue-100">
            <Inbox className="h-5 w-5 text-blue-700" />
          </div>
          <div>
            <CardTitle className="text-lg">
              {quantidade} processo{quantidade === 1 ? "" : "s"} esperando
            </CardTitle>
            <CardDescription>
              Cada um tem uma tarefa antiga "Verificar Prazos e Habilitação" pra cancelar
              no Legal One. O sistema faz isso sozinho a cada 1 minuto. Se quiser que rode
              agora, clique abaixo.
            </CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          <Button size="lg" onClick={onProcessarAgora} disabled={processando || buscando}>
            {processando ? (
              <Loader2 className="mr-2 h-5 w-5 animate-spin" />
            ) : (
              <Play className="mr-2 h-5 w-5" />
            )}
            Processar agora
          </Button>
          <Button variant="outline" size="sm" onClick={onBuscarNovos} disabled={processando || buscando}>
            {buscando ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Search className="mr-2 h-4 w-4" />
            )}
            Buscar processos novos
          </Button>
        </div>

        {ultimosConcluidos.length > 0 ? (
          <div className="border-t border-blue-200 pt-4">
            <p className="mb-2 text-xs font-medium text-muted-foreground">
              Últimos processados:
            </p>
            <ul className="space-y-1 text-sm">
              {ultimosConcluidos.map((item) => (
                <li key={item.id} className="flex items-center gap-2">
                  <CheckCircle2 className="h-4 w-4 shrink-0 text-green-600" />
                  <span className="font-mono text-xs">{formatCnj(item.cnj_number)}</span>
                  <span className="text-muted-foreground">cancelado</span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

function CardProcessando({
  processando,
  concluidos,
  totalGeral,
  progresso,
}: {
  processando: number;
  concluidos: number;
  totalGeral: number;
  progresso: number;
}) {
  return (
    <Card className="border-amber-200 bg-amber-50/40">
      <CardHeader>
        <div className="flex items-start gap-3">
          <div className="mt-1 flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-amber-100">
            <Loader2 className="h-5 w-5 animate-spin text-amber-700" />
          </div>
          <div>
            <CardTitle className="text-lg">
              Processando {processando > 0 ? `${processando} processo${processando === 1 ? "" : "s"}` : "agora"}…
            </CardTitle>
            <CardDescription>
              Pode fechar essa aba — o trabalho continua rodando no servidor. A página atualiza sozinha.
            </CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <Progress value={progresso} className="h-3" />
        <p className="mt-2 text-xs text-muted-foreground">
          {concluidos} de {totalGeral} concluídos ({progresso}%)
        </p>
      </CardContent>
    </Card>
  );
}

function CardFalhas({
  itensFalha,
  onTentarTodasDeNovo,
  tentando,
  onBuscarNovos,
  buscando,
}: {
  itensFalha: PrazoInicialLegacyTaskCancelQueueItem[];
  onTentarTodasDeNovo: () => void;
  tentando: boolean;
  onBuscarNovos: () => void;
  buscando: boolean;
}) {
  // Limita a 8 falhas pra nao explodir a UI; resto fica em "ver detalhes
  // tecnicos" se o operador quiser inspecionar item-a-item.
  const visiveis = itensFalha.slice(0, 8);
  const restantes = itensFalha.length - visiveis.length;

  return (
    <Card className="border-red-200 bg-red-50/40">
      <CardHeader>
        <div className="flex items-start gap-3">
          <div className="mt-1 flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-red-100">
            <AlertTriangle className="h-5 w-5 text-red-700" />
          </div>
          <div>
            <CardTitle className="text-lg">
              {itensFalha.length} processo{itensFalha.length === 1 ? "" : "s"} falharam
            </CardTitle>
            <CardDescription>
              O sistema já vai tentar de novo sozinho. Se continuar dando erro depois de
              algumas tentativas, fale com o coordenador.
            </CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <ul className="space-y-2">
          {visiveis.map((item) => (
            <li key={item.id} className="flex items-start gap-2 text-sm">
              <span className="mt-0.5 text-red-600">•</span>
              <div className="min-w-0 flex-1">
                <span className="font-mono text-xs">{formatCnj(item.cnj_number)}</span>
                <span className="ml-2 text-muted-foreground">— {reasonHumano(item.last_reason)}</span>
              </div>
            </li>
          ))}
        </ul>

        {restantes > 0 ? (
          <p className="text-xs text-muted-foreground">
            …e mais {restantes} (clique em "ver detalhes técnicos" no fim da página).
          </p>
        ) : null}

        <div className="flex flex-wrap items-center gap-2 border-t border-red-200 pt-4">
          <Button size="lg" onClick={onTentarTodasDeNovo} disabled={tentando || buscando}>
            {tentando ? (
              <Loader2 className="mr-2 h-5 w-5 animate-spin" />
            ) : (
              <RefreshCw className="mr-2 h-5 w-5" />
            )}
            Tentar todas de novo
          </Button>
          <Button variant="outline" size="sm" onClick={onBuscarNovos} disabled={tentando || buscando}>
            {buscando ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Search className="mr-2 h-4 w-4" />
            )}
            Buscar processos novos
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

