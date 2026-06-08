import { useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  ArrowRight,
  CalendarCheck2,
  CalendarClock,
  CheckCircle2,
  FileUp,
  Flame,
  Newspaper,
  Sparkles,
  Users,
  Workflow,
} from 'lucide-react';

import { useAuth } from '@/hooks/useAuth';
import { apiFetch } from '@/lib/api-client';
import { fetchBatchExecutions } from '@/services/api';
import { Button } from '@/components/ui/button';

// ──────────────────────────────────────────────────────────────
// Tipos auxiliares (subset do que cada endpoint devolve)
// ──────────────────────────────────────────────────────────────

interface OverviewKpisLite {
  pendentes_agora: number;
  tratadas_janela: number;
  recebidas_janela: number;
  window_days: number;
}

interface OverviewPayloadLite {
  kpis: OverviewKpisLite;
}

interface AutomationLite {
  id: number;
  name: string;
  next_run_at: string | null;
  is_enabled: boolean;
}

interface IntakeListResponseLite {
  total: number;
  items: unknown[];
}

// ──────────────────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────────────────

const greetingFor = (hour: number): string => {
  if (hour < 12) return 'Bom dia';
  if (hour < 18) return 'Boa tarde';
  return 'Boa noite';
};

const firstName = (fullName?: string | null): string => {
  if (!fullName) return '';
  return fullName.trim().split(/\s+/)[0] ?? '';
};

const formatTimeBR = (isoString: string | null): string => {
  if (!isoString) return '—';
  return new Intl.DateTimeFormat('pt-BR', {
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'America/Sao_Paulo',
  }).format(new Date(isoString));
};

const batchProgressLabel = (
  batch: { total_items: number; success_count: number; failure_count: number; status: string } | undefined,
): string => {
  if (!batch) return 'Nenhum lote recente';
  const done = (batch.success_count ?? 0) + (batch.failure_count ?? 0);
  const total = batch.total_items ?? 0;
  if (total === 0) return batch.status ?? '—';
  const pct = Math.round((done / total) * 100);
  return `Último lote: ${pct}% concluído`;
};

// ──────────────────────────────────────────────────────────────
// Componentes locais
// ──────────────────────────────────────────────────────────────

interface SectionCardProps {
  title: string;
  subtitle: string;
  icon: React.ElementType;
  metric?: string | number;
  metricCaption?: string;
  ctaLabel?: string;
  onClick: () => void;
  discreet?: boolean;
}

const SectionCard = ({
  title,
  subtitle,
  icon: Icon,
  metric,
  metricCaption,
  ctaLabel = 'Entrar',
  onClick,
  discreet = false,
}: SectionCardProps) => {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`
        group relative overflow-hidden rounded-2xl text-left
        backdrop-blur-xl
        ${discreet
          ? 'bg-white/30 dark:bg-white/[0.03] border border-white/20'
          : 'bg-white/45 dark:bg-white/5 border border-white/30'}
        shadow-[0_8px_32px_0_rgba(31,38,135,0.08)]
        ring-1 ring-white/10
        transition-all duration-300
        hover:-translate-y-1
        hover:shadow-[0_12px_40px_0_rgba(31,38,135,0.14)]
        hover:bg-white/60
        focus:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--dunatech-blue))]
      `}
    >
      <div className="flex flex-col gap-4 p-6 h-full">
        <div className="flex items-start justify-between">
          <div
            className={`
              rounded-xl p-2.5
              ${discreet
                ? 'bg-slate-500/10 text-slate-600'
                : 'bg-[hsl(var(--dunatech-blue)/0.12)] text-[hsl(var(--dunatech-blue))]'}
            `}
          >
            <Icon className="h-5 w-5" />
          </div>
          <ArrowRight
            className={`
              h-4 w-4 text-muted-foreground
              transition-transform duration-300 group-hover:translate-x-1
            `}
          />
        </div>

        <div className="space-y-1">
          <h3 className="font-semibold tracking-tight text-lg text-[hsl(var(--dunatech-navy))]">
            {title}
          </h3>
          <p className="text-xs text-muted-foreground leading-relaxed">{subtitle}</p>
        </div>

        {!discreet && (
          <div className="mt-auto pt-2 space-y-0.5">
            {metric !== undefined && metric !== null && (
              <p className="text-4xl font-bold text-[hsl(var(--dunatech-navy))] tabular-nums leading-none">
                {metric}
              </p>
            )}
            {metricCaption && (
              <p className="text-[11px] uppercase tracking-wider text-muted-foreground">
                {metricCaption}
              </p>
            )}
          </div>
        )}

        <div className="pt-3 border-t border-white/30 mt-2">
          <span className="text-xs font-medium text-[hsl(var(--dunatech-blue))] group-hover:underline">
            {ctaLabel} →
          </span>
        </div>
      </div>
    </button>
  );
};

interface PulseChipProps {
  icon: React.ElementType;
  text: string;
}

const PulseChip = ({ icon: Icon, text }: PulseChipProps) => (
  <div
    className={`
      inline-flex items-center gap-2 px-4 py-2 rounded-full
      backdrop-blur-xl bg-white/50 dark:bg-white/[0.06]
      border border-white/40
      shadow-[0_4px_16px_0_rgba(31,38,135,0.06)]
      text-sm text-[hsl(var(--dunatech-navy))]
    `}
  >
    <Icon className="h-4 w-4 text-[hsl(var(--dunatech-blue))]" />
    <span>{text}</span>
  </div>
);

// ──────────────────────────────────────────────────────────────
// Página principal
// ──────────────────────────────────────────────────────────────

const LandingPage = () => {
  const navigate = useNavigate();
  const {
    user,
    canScheduleBatch,
    canUsePublications,
    canUsePrazosIniciais,
    isAdmin,
  } = useAuth();

  const now = new Date();
  const greeting = useMemo(() => greetingFor(now.getHours()), [now]);

  // Publicações overview (também alimenta a faixa "Pulso da equipe").
  // days=7 é o mínimo aceito pelo endpoint (Query ge=7). pendentes_agora
  // é estoque atual (status NOVO), independe da janela; tratadas_janela
  // reflete a janela de 7 dias.
  const { data: pubsOverview } = useQuery({
    queryKey: ['landing', 'publications-overview-7d'],
    queryFn: async () => {
      const res = await apiFetch('/api/v1/dashboard/publications-overview?days=7');
      if (!res.ok) return null;
      return (await res.json()) as OverviewPayloadLite;
    },
    enabled: canUsePublications,
    staleTime: 60_000,
  });

  // Prazos iniciais — contagem total (proxy de "carteira aberta")
  const { data: prazosTotal } = useQuery({
    queryKey: ['landing', 'prazos-iniciais-total'],
    queryFn: async () => {
      const res = await apiFetch('/api/v1/prazos-iniciais/intakes?limit=1');
      if (!res.ok) return null;
      const json = (await res.json()) as IntakeListResponseLite;
      return json.total ?? 0;
    },
    enabled: canUsePrazosIniciais || isAdmin,
    staleTime: 60_000,
  });

  // Automations — próxima rodagem
  const { data: automations } = useQuery({
    queryKey: ['landing', 'automations'],
    queryFn: async () => {
      const res = await apiFetch('/api/v1/automations');
      if (!res.ok) return [] as AutomationLite[];
      const data = await res.json();
      return (Array.isArray(data) ? data : data.items || []) as AutomationLite[];
    },
    enabled: canUsePublications,
    staleTime: 60_000,
  });

  // Último lote
  const { data: batches } = useQuery({
    queryKey: ['landing', 'batches'],
    queryFn: () => fetchBatchExecutions(),
    enabled: canScheduleBatch,
    staleTime: 60_000,
  });

  const nextAutomation = useMemo(() => {
    if (!automations || automations.length === 0) return null;
    const enabled = automations.filter((a) => a.is_enabled && a.next_run_at);
    if (enabled.length === 0) return null;
    return enabled.sort(
      (a, b) =>
        new Date(a.next_run_at || '').getTime() - new Date(b.next_run_at || '').getTime(),
    )[0];
  }, [automations]);

  const lastBatch = batches?.[0];

  return (
    <div className="relative isolate space-y-8">
      {/* Camada decorativa liquid glass — atrás do conteúdo, contida na área
          da página (não afeta o fluxo nem o enquadramento padrão). */}
      <div className="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-br from-white/60 via-transparent to-blue-50/40 dark:from-slate-950/60 dark:via-transparent dark:to-slate-900/40" />
        <div className="absolute top-[-30%] left-[-5%] h-[500px] w-[500px] rounded-full bg-[hsl(var(--dunatech-blue))] opacity-[0.18] blur-[120px]" />
        <div className="absolute bottom-[-30%] right-[-5%] h-[450px] w-[450px] rounded-full bg-[hsl(var(--dunatech-navy))] opacity-[0.12] blur-[120px]" />
      </div>

      {/* Header de saudação contextual */}
      <header className="space-y-2">
        <h1 className="text-3xl font-bold tracking-tight text-[hsl(var(--dunatech-navy))]">
          {greeting}
          {user?.name ? `, ${firstName(user.name)}` : ''}.
        </h1>
        <p className="text-sm italic text-muted-foreground max-w-2xl">
          Central DunaFlow de tratamento jurídico automatizado. Publicações, prazos
          iniciais e andamentos em um só lugar.
        </p>
      </header>

      {/* Pulso da equipe hoje (chips opcionais) */}
      {canUsePublications && pubsOverview?.kpis && (
        <div className="flex flex-wrap gap-3">
          <PulseChip
            icon={Flame}
            text={`${pubsOverview.kpis.tratadas_janela ?? 0} publicações tratadas pela equipe nos últimos 7 dias`}
          />
          {nextAutomation?.next_run_at && (
            <PulseChip
              icon={CalendarCheck2}
              text={`Próximo agendamento automático: ${formatTimeBR(nextAutomation.next_run_at)}`}
            />
          )}
          <PulseChip
            icon={CheckCircle2}
            text={`Backlog: ${pubsOverview.kpis.pendentes_agora ?? 0} pendentes`}
          />
        </div>
      )}

      {/* Grid de seções */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-5">
        {canUsePublications && (
          <SectionCard
            title="Publicações"
            subtitle="Capture, classifique e agende tarefas a partir das publicações do Legal One."
            icon={Newspaper}
            metric={pubsOverview?.kpis?.pendentes_agora ?? '—'}
            metricCaption="Pendentes agora"
            onClick={() => navigate('/publications/dashboard')}
          />
        )}

        {(canUsePrazosIniciais || isAdmin) && (
          <SectionCard
            title="Prazos Iniciais"
            subtitle="Receba, classifique e dispare as primeiras providências dos novos processos."
            icon={CalendarClock}
            metric={prazosTotal ?? '—'}
            metricCaption="Intakes na carteira"
            onClick={() => navigate('/prazos-iniciais')}
          />
        )}

        {(canUsePrazosIniciais || isAdmin) && (
          <SectionCard
            title="AJUS — Andamentos"
            subtitle="Fila de andamentos derivados dos intakes, com dispatch manual."
            icon={Workflow}
            metricCaption="Abrir AJUS"
            onClick={() => navigate('/ajus')}
          />
        )}

        {canScheduleBatch && (
          <SectionCard
            title="Tarefas em Lote"
            subtitle="Crie tarefas em massa a partir de planilhas e acompanhe a execução."
            icon={FileUp}
            metricCaption={batchProgressLabel(lastBatch)}
            onClick={() => navigate('/tasks/spreadsheet-batch')}
          />
        )}

        {isAdmin && (
          <SectionCard
            title="Administração"
            subtitle="Usuários, permissões, taxonomia, escritórios e configurações gerais."
            icon={Users}
            ctaLabel="Abrir"
            onClick={() => navigate('/admin')}
            discreet
          />
        )}
      </div>

      {/* Rodapé */}
      <footer className="pt-6 flex items-center justify-between text-xs text-muted-foreground">
        <span className="inline-flex items-center gap-1.5">
          <Sparkles className="h-3.5 w-3.5 text-[hsl(var(--dunatech-blue))]" />
          DunaFlow
        </span>
        <span className="hidden sm:inline">
          Use o botão de feedback no canto inferior direito para reportar qualquer coisa.
        </span>
      </footer>
    </div>
  );
};

export default LandingPage;
