import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Clock,
  Inbox,
  Loader2,
  Play,
  RefreshCw,
  Search,
  TrendingUp,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
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
 * Tela "operador" do Tratamento Web. Dashboard com:
 *  - Banner de saude (verde/amarelo/vermelho com frase resumida)
 *  - 4 KPIs (na fila, 24h, total, tempo medio)
 *  - Hero card de acao (Processar agora)
 *  - Live: items em execucao agora + ultimos cancelados (com tempo relativo)
 *
 * A versao admin/debug com filtros, metricas, zumbis, tabela completa e
 * controles avancados esta' em /prazos-iniciais/treatment/detalhes.
 */

// ── Helpers ────────────────────────────────────────────────────────────

function reasonHumano(reason: string | null | undefined): string {
  if (!reason) return "Não foi possível processar agora.";
  const labels: Record<string, string> = {
    auth_failure: "Legal One não autenticou. Vou tentar de novo em breve.",
    timeout: "Legal One está demorando. Vou tentar de novo em breve.",
    layout_drift: "A tela do Legal One mudou. Avise o coordenador.",
    runner_error: "Erro inesperado. O sistema vai tentar de novo automaticamente.",
    verification_failed: "O cancelamento não persistiu. Vou tentar de novo.",
    task_not_found: "Tarefa não encontrada (talvez já apagada).",
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

function tempoRelativo(iso: string | null | undefined, agoraMs: number): string {
  if (!iso) return "";
  const ts = new Date(iso).getTime();
  if (Number.isNaN(ts)) return "";
  const diffSec = Math.max(0, Math.floor((agoraMs - ts) / 1000));
  if (diffSec < 60) return `há ${diffSec}s`;
  if (diffSec < 3600) return `há ${Math.floor(diffSec / 60)} min`;
  if (diffSec < 86400) return `há ${Math.floor(diffSec / 3600)}h`;
  return `há ${Math.floor(diffSec / 86400)}d`;
}

function formatLatencia(ms: number | null | undefined): string {
  if (ms == null || Number.isNaN(ms)) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)} s`;
  return `${Math.round(s / 60)} min`;
}

function formatNumero(n: number): string {
  return n.toLocaleString("pt-BR");
}

function formatEta(pendentes: number, avgLatencyMs: number | null | undefined): string {
  if (!pendentes || avgLatencyMs == null || avgLatencyMs <= 0) return "";
  const totalSec = (pendentes * avgLatencyMs) / 1000;
  if (totalSec < 60) return `~${Math.ceil(totalSec)}s pra esvaziar a fila`;
  if (totalSec < 3600) return `~${Math.ceil(totalSec / 60)} min pra esvaziar a fila`;
  return `~${Math.round(totalSec / 3600)}h pra esvaziar a fila`;
}

type Estado = "carregando" | "vazio" | "pendentes" | "processando" | "falhas";
type Saude = "ok" | "atencao" | "problema";

const POLL_INTERVAL_MS = 5000;

export default function PrazosIniciaisTreatmentPageOperator() {
  const { toast } = useToast();

  const [items, setItems] = useState<PrazoInicialLegacyTaskCancelQueueItem[]>([]);
  const [metrics, setMetrics] = useState<PrazoInicialLegacyTaskQueueMetrics | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);
  const [agoraMs, setAgoraMs] = useState<number>(Date.now());
  const [pulseRefresh, setPulseRefresh] = useState(false);

  const [acaoEmCurso, setAcaoEmCurso] = useState<
    null | "buscando" | "processando" | "tentando_de_novo"
  >(null);

  const acaoEmCursoRef = useRef(acaoEmCurso);
  acaoEmCursoRef.current = acaoEmCurso;

  // ── Carga + auto-refresh ───────────────────────────────────────────
  const carregarDados = async () => {
    try {
      const [payload, metricsPayload] = await Promise.all([
        fetchPrazosIniciaisLegacyTaskCancelQueue({ limit: 50, offset: 0 }),
        fetchPrazosIniciaisLegacyTaskCancelQueueMetrics(24).catch(() => null),
      ]);
      setItems(payload.items);
      setMetrics(metricsPayload);
      setErro(null);
      setAgoraMs(Date.now());
      setPulseRefresh(true);
      setTimeout(() => setPulseRefresh(false), 800);
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
      if (acaoEmCursoRef.current) return;
      carregarDados();
    }, POLL_INTERVAL_MS);
    const tickerId = setInterval(() => setAgoraMs(Date.now()), 1000);
    return () => {
      clearInterval(intervalId);
      clearInterval(tickerId);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Contadores ─────────────────────────────────────────────────────
  const contagens = useMemo(() => {
    const totals = metrics?.totals_by_status ?? {};
    const pendentes = (totals.PENDENTE ?? 0) + (totals.FALHA ?? 0);
    const processando = totals.PROCESSANDO ?? 0;
    const cancelados24h = metrics?.completed_in_window ?? 0;
    const falhas24h = metrics?.failures_in_window ?? 0;
    const canceladosTotais = totals.CONCLUIDO ?? 0;
    const falhasAtuais = totals.FALHA ?? 0;
    const naFila = pendentes + processando;
    const avgLatencyMs = metrics?.avg_latency_ms_in_window ?? null;
    const eta = formatEta(pendentes, avgLatencyMs);
    return {
      pendentes,
      processando,
      cancelados24h,
      falhas24h,
      canceladosTotais,
      falhasAtuais,
      naFila,
      avgLatencyMs,
      eta,
    };
  }, [metrics]);

  const itensFalha = useMemo(
    () => items.filter((it) => it.queue_status === "FALHA"),
    [items],
  );
  const itensProcessando = useMemo(
    () => items.filter((it) => it.queue_status === "PROCESSANDO"),
    [items],
  );
  const ultimosConcluidos = useMemo(
    () =>
      items
        .filter((it) => it.queue_status === "CONCLUIDO" && it.completed_at)
        .sort((a, b) => (b.completed_at ?? "").localeCompare(a.completed_at ?? ""))
        .slice(0, 8),
    [items],
  );

  // ── Saude do sistema (verde/amarelo/vermelho) ──────────────────────
  const saude: { nivel: Saude; mensagem: string } = useMemo(() => {
    const cb = metrics?.circuit_breaker;
    if (cb?.tripped) {
      return {
        nivel: "problema",
        mensagem:
          "Sistema travado por causa de erros consecutivos. Vai tentar de novo em alguns minutos.",
      };
    }
    if (contagens.falhasAtuais > 5) {
      return {
        nivel: "atencao",
        mensagem: `${contagens.falhasAtuais} processos com falha agora — vale ficar de olho.`,
      };
    }
    if (contagens.falhas24h > 0 && contagens.falhas24h > contagens.cancelados24h * 0.2) {
      return {
        nivel: "atencao",
        mensagem: `Taxa de falha alta nas últimas 24h: ${contagens.falhas24h} falhas em ${contagens.cancelados24h + contagens.falhas24h} processados.`,
      };
    }
    if (contagens.naFila === 0 && contagens.cancelados24h === 0) {
      return {
        nivel: "ok",
        mensagem: "Sem atividade nas últimas 24h. Aguardando novos processos.",
      };
    }
    if (contagens.naFila === 0) {
      return {
        nivel: "ok",
        mensagem: `Tudo em dia — ${formatNumero(contagens.cancelados24h)} cancelados nas últimas 24h sem problema.`,
      };
    }
    const partes = [
      `${formatNumero(contagens.naFila)} processo${contagens.naFila === 1 ? "" : "s"} na fila`,
    ];
    if (contagens.avgLatencyMs != null) {
      partes.push(`média de ${formatLatencia(contagens.avgLatencyMs)} cada`);
    }
    if (contagens.eta) {
      partes.push(contagens.eta);
    }
    return {
      nivel: "ok",
      mensagem: `Funcionando bem — ${partes.join(" · ")}.`,
    };
  }, [metrics, contagens]);

  // ── Estado da hero card ────────────────────────────────────────────
  const estado: Estado = carregando
    ? "carregando"
    : acaoEmCurso === "processando" || acaoEmCurso === "tentando_de_novo"
      ? "processando"
      : contagens.processando > 0 && contagens.pendentes === 0
        ? "processando"
        : contagens.falhasAtuais > 0
          ? "falhas"
          : contagens.pendentes > 0
            ? "pendentes"
            : "vazio";

  // Ultima execucao do worker
  const ultimoTickRelativo = useMemo(() => {
    const finishedAt = metrics?.last_tick?.finished_at;
    return finishedAt ? tempoRelativo(finishedAt, agoraMs) : "";
  }, [metrics, agoraMs]);

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
          description: "O sistema já vai começar a processar.",
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
            ? `${falha} não foi possível re-agendar agora.`
            : "O sistema vai tentar de novo automaticamente.",
        variant: falha > 0 ? "destructive" : undefined,
      });
      await carregarDados();
    } finally {
      setAcaoEmCurso(null);
    }
  };

  // ── Render ─────────────────────────────────────────────────────────

  return (
    <div className="space-y-5 px-6 py-6 lg:px-8">
      {/* Header */}
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Tratamento Web</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Cancela tarefas antigas no Legal One assim que processos novos chegam.
          </p>
        </div>
        <div className="flex items-center gap-4 text-xs text-muted-foreground">
          {ultimoTickRelativo ? (
            <span className="inline-flex items-center gap-1.5">
              <Activity className="h-3.5 w-3.5" />
              Última execução: {ultimoTickRelativo}
            </span>
          ) : null}
          <span className="inline-flex items-center gap-1.5">
            <span
              className={`inline-block h-2 w-2 rounded-full bg-green-500 ${pulseRefresh ? "animate-ping" : "animate-pulse"}`}
            />
            Atualiza a cada 5s
          </span>
        </div>
      </header>

      {erro ? (
        <Card className="border-red-200 bg-red-50">
          <CardContent className="flex items-start gap-3 pt-6">
            <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-red-700" />
            <div>
              <p className="text-sm font-medium text-red-900">
                Não consegui carregar a página: {erro}
              </p>
              <p className="mt-1 text-xs text-red-900/80">
                Tente atualizar daqui a alguns segundos. Se continuar, avise o coordenador.
              </p>
            </div>
          </CardContent>
        </Card>
      ) : null}

      {/* Banner de saúde */}
      {!carregando ? <BannerSaude saude={saude} /> : null}

      {/* KPIs */}
      {!carregando ? (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Kpi
            icone={<Inbox className="h-5 w-5" />}
            label="Na fila agora"
            valor={formatNumero(contagens.naFila)}
            sublinha={
              contagens.processando > 0
                ? `${contagens.processando} em execução`
                : contagens.pendentes > 0
                  ? "esperando processar"
                  : "fila vazia"
            }
            cor={contagens.naFila > 0 ? "blue" : "neutral"}
          />
          <Kpi
            icone={<TrendingUp className="h-5 w-5" />}
            label="Cancelados (24h)"
            valor={formatNumero(contagens.cancelados24h)}
            sublinha={
              contagens.falhas24h > 0
                ? `${contagens.falhas24h} falha${contagens.falhas24h === 1 ? "" : "s"}`
                : "0 falhas"
            }
            cor={contagens.falhas24h > 0 ? "amber" : "green"}
          />
          <Kpi
            icone={<CheckCircle2 className="h-5 w-5" />}
            label="Total cancelados"
            valor={formatNumero(contagens.canceladosTotais)}
            sublinha="acumulado"
            cor="neutral"
          />
          <Kpi
            icone={<Clock className="h-5 w-5" />}
            label="Tempo médio"
            valor={formatLatencia(contagens.avgLatencyMs)}
            sublinha={
              metrics?.latency_samples_in_window
                ? `${metrics.latency_samples_in_window} amostra${metrics.latency_samples_in_window === 1 ? "" : "s"} (24h)`
                : "sem amostras (24h)"
            }
            cor="neutral"
          />
        </div>
      ) : null}

      {/* Hero ação + cards live */}
      <div className="grid grid-cols-1 items-start gap-5 lg:grid-cols-3">
        <div className="lg:col-span-2">
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
              eta={contagens.eta}
              onProcessarAgora={handleProcessarAgora}
              processando={acaoEmCurso === "processando"}
              onBuscarNovos={handleBuscarNovos}
              buscando={acaoEmCurso === "buscando"}
            />
          ) : estado === "processando" ? (
            <CardProcessando emExecucao={contagens.processando} />
          ) : (
            <CardFalhas
              itensFalha={itensFalha}
              onTentarTodasDeNovo={handleTentarTodasDeNovo}
              tentando={acaoEmCurso === "tentando_de_novo"}
              onBuscarNovos={handleBuscarNovos}
              buscando={acaoEmCurso === "buscando"}
            />
          )}
        </div>

        <aside className="space-y-4">
          <CardAgoraMesmo itens={itensProcessando} agoraMs={agoraMs} />
          <CardUltimosCancelados itens={ultimosConcluidos} agoraMs={agoraMs} />
        </aside>
      </div>

      <div className="flex items-center justify-end pt-2">
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

// ── Sub-componentes ────────────────────────────────────────────────────

function BannerSaude({ saude }: { saude: { nivel: Saude; mensagem: string } }) {
  const cores = {
    ok: {
      card: "border-green-200 bg-green-50",
      icone: "bg-green-600 text-white",
      texto: "text-green-900",
      label: "Funcionando bem",
      Icon: CheckCircle2,
    },
    atencao: {
      card: "border-amber-200 bg-amber-50",
      icone: "bg-amber-500 text-white",
      texto: "text-amber-900",
      label: "Atenção",
      Icon: AlertTriangle,
    },
    problema: {
      card: "border-red-200 bg-red-50",
      icone: "bg-red-600 text-white",
      texto: "text-red-900",
      label: "Sistema travado",
      Icon: AlertTriangle,
    },
  }[saude.nivel];

  const Icon = cores.Icon;

  return (
    <Card className={`border ${cores.card}`}>
      <CardContent className="flex items-center gap-4 py-4">
        <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full ${cores.icone}`}>
          <Icon className="h-5 w-5" />
        </div>
        <div className="min-w-0 flex-1">
          <div className={`text-sm font-semibold ${cores.texto}`}>{cores.label}</div>
          <div className={`text-sm ${cores.texto}/80`}>{saude.mensagem}</div>
        </div>
      </CardContent>
    </Card>
  );
}

function Kpi({
  icone,
  label,
  valor,
  sublinha,
  cor,
}: {
  icone: React.ReactNode;
  label: string;
  valor: string;
  sublinha: string;
  cor: "blue" | "green" | "amber" | "red" | "neutral";
}) {
  const corValor = {
    blue: "text-blue-700",
    green: "text-green-700",
    amber: "text-amber-700",
    red: "text-red-700",
    neutral: "text-foreground",
  }[cor];
  const corIcone = {
    blue: "text-blue-600 bg-blue-100",
    green: "text-green-600 bg-green-100",
    amber: "text-amber-600 bg-amber-100",
    red: "text-red-600 bg-red-100",
    neutral: "text-muted-foreground bg-muted",
  }[cor];

  return (
    <Card>
      <CardContent className="space-y-2 p-4">
        <div className="flex items-center justify-between">
          <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            {label}
          </span>
          <span className={`flex h-8 w-8 items-center justify-center rounded-md ${corIcone}`}>
            {icone}
          </span>
        </div>
        <div className={`text-3xl font-bold tabular-nums ${corValor}`}>{valor}</div>
        <div className="text-xs text-muted-foreground">{sublinha}</div>
      </CardContent>
    </Card>
  );
}

function CardCarregando() {
  return (
    <Card>
      <CardContent className="flex items-center justify-center py-24 text-muted-foreground">
        <Loader2 className="mr-3 h-6 w-6 animate-spin" />
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
    <Card className="border-green-200">
      <CardContent className="flex flex-col items-center gap-3 py-8 text-center">
        <div className="flex h-14 w-14 items-center justify-center rounded-full bg-green-100">
          <CheckCircle2 className="h-7 w-7 text-green-600" />
        </div>
        <div>
          <h2 className="text-lg font-semibold">Tudo em ordem</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Nenhum processo aguardando agora. A fila se atualiza sozinha.
          </p>
        </div>
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
  eta,
  onProcessarAgora,
  processando,
  onBuscarNovos,
  buscando,
}: {
  quantidade: number;
  eta: string;
  onProcessarAgora: () => void;
  processando: boolean;
  onBuscarNovos: () => void;
  buscando: boolean;
}) {
  return (
    <Card className="border-blue-200">
      <CardContent className="flex flex-col items-center gap-4 py-7 text-center">
        <div className="flex h-14 w-14 items-center justify-center rounded-full bg-blue-100">
          <Inbox className="h-7 w-7 text-blue-600" />
        </div>
        <div>
          <div className="flex items-baseline justify-center gap-2">
            <span className="text-5xl font-bold leading-none text-blue-700">
              {formatNumero(quantidade)}
            </span>
            <span className="text-lg font-medium text-muted-foreground">
              processo{quantidade === 1 ? "" : "s"} esperando
            </span>
          </div>
          {eta ? (
            <p className="mt-1.5 text-sm text-muted-foreground">
              No ritmo atual, {eta}.
            </p>
          ) : null}
          <p className="mt-1 max-w-md text-sm text-muted-foreground">
            O sistema processa sozinho a cada 1 minuto. Se quiser que rode agora, clique abaixo.
          </p>
        </div>
        <div className="flex flex-col items-center gap-1.5">
          <Button
            size="lg"
            className="h-12 px-8 text-base font-semibold shadow-sm"
            onClick={onProcessarAgora}
            disabled={processando || buscando}
          >
            {processando ? (
              <Loader2 className="mr-2 h-5 w-5 animate-spin" />
            ) : (
              <Play className="mr-2 h-5 w-5 fill-current" />
            )}
            Processar agora
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={onBuscarNovos}
            disabled={processando || buscando}
          >
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

function CardProcessando({ emExecucao }: { emExecucao: number }) {
  return (
    <Card className="border-amber-200 bg-amber-50/30">
      <CardContent className="flex flex-col items-center gap-3 py-7 text-center">
        <div className="flex h-14 w-14 items-center justify-center rounded-full bg-amber-100">
          <Loader2 className="h-7 w-7 animate-spin text-amber-600" />
        </div>
        <div>
          <h2 className="text-lg font-semibold text-amber-900">
            Processando {emExecucao > 0 ? `${formatNumero(emExecucao)} processo${emExecucao === 1 ? "" : "s"}` : "agora"}…
          </h2>
          <p className="mt-1 max-w-md text-sm text-amber-900/70">
            Pode fechar essa aba — o trabalho continua rodando no servidor.
          </p>
        </div>
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
  const visiveis = itensFalha.slice(0, 6);
  const restantes = itensFalha.length - visiveis.length;

  return (
    <Card className="border-red-200">
      <CardContent className="space-y-4 py-6">
        <div className="flex flex-col items-center gap-2 text-center">
          <div className="flex h-14 w-14 items-center justify-center rounded-full bg-red-100">
            <AlertTriangle className="h-7 w-7 text-red-600" />
          </div>
          <div className="flex items-baseline justify-center gap-2">
            <span className="text-5xl font-bold leading-none text-red-700">
              {formatNumero(itensFalha.length)}
            </span>
            <span className="text-lg font-medium text-muted-foreground">
              processo{itensFalha.length === 1 ? "" : "s"} com falha
            </span>
          </div>
          <p className="max-w-md text-sm text-muted-foreground">
            O sistema já vai tentar de novo sozinho. Se continuar dando erro, fale com o
            coordenador.
          </p>
        </div>

        <ul className="mx-auto max-w-2xl space-y-2 rounded-md border bg-muted/30 p-3">
          {visiveis.map((item) => (
            <li key={item.id} className="flex items-start gap-2 text-sm">
              <span className="mt-1 inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-red-500" />
              <div className="min-w-0 flex-1">
                <span className="font-mono text-xs font-medium">
                  {formatCnj(item.cnj_number)}
                </span>
                <span className="ml-2 text-muted-foreground">
                  — {reasonHumano(item.last_reason)}
                </span>
              </div>
            </li>
          ))}
          {restantes > 0 ? (
            <li className="pt-1 text-xs italic text-muted-foreground">
              …e mais {restantes}.
            </li>
          ) : null}
        </ul>

        <div className="flex flex-col items-center gap-2">
          <Button
            size="lg"
            className="h-12 px-8 text-base font-semibold shadow-sm"
            onClick={onTentarTodasDeNovo}
            disabled={tentando || buscando}
          >
            {tentando ? (
              <Loader2 className="mr-2 h-5 w-5 animate-spin" />
            ) : (
              <RefreshCw className="mr-2 h-5 w-5" />
            )}
            Tentar todas de novo
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={onBuscarNovos}
            disabled={tentando || buscando}
          >
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

function CardAgoraMesmo({
  itens,
  agoraMs,
}: {
  itens: PrazoInicialLegacyTaskCancelQueueItem[];
  agoraMs: number;
}) {
  return (
    <Card>
      <CardContent className="space-y-3 pt-6">
        <div className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
          <Activity className="h-3.5 w-3.5" />
          Agora mesmo
        </div>
        {itens.length === 0 ? (
          <p className="text-sm text-muted-foreground">Nenhum processo em execução.</p>
        ) : (
          <>
            <p className="text-sm">
              <span className="font-semibold text-amber-700">{itens.length}</span>
              <span className="ml-1 text-muted-foreground">
                em execução
              </span>
            </p>
            <ul className="space-y-2">
              {itens.slice(0, 5).map((item) => (
                <li key={item.id} className="flex items-start gap-2 text-sm">
                  <Loader2 className="mt-0.5 h-3.5 w-3.5 shrink-0 animate-spin text-amber-600" />
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-mono text-xs">
                      {formatCnj(item.cnj_number)}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      iniciado {tempoRelativo(item.last_attempt_at, agoraMs) || "agora"}
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          </>
        )}
      </CardContent>
    </Card>
  );
}

function CardUltimosCancelados({
  itens,
  agoraMs,
}: {
  itens: PrazoInicialLegacyTaskCancelQueueItem[];
  agoraMs: number;
}) {
  return (
    <Card>
      <CardContent className="space-y-3 pt-6">
        <div className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
          <CheckCircle2 className="h-3.5 w-3.5" />
          Últimos cancelados
        </div>
        {itens.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Nenhum cancelamento recente nessa janela.
          </p>
        ) : (
          <ul className="space-y-2">
            {itens.map((item) => (
              <li key={item.id} className="flex items-start gap-2 text-sm">
                <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-green-600" />
                <div className="min-w-0 flex-1">
                  <div className="truncate font-mono text-xs">
                    {formatCnj(item.cnj_number)}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {tempoRelativo(item.completed_at, agoraMs) || "agora"}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
