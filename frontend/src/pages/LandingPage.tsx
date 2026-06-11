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
        hover:border-[hsl(var(--dunatech-blue)/0.45)]
        hover:bg-white/70
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
                : 'bg-gradient-to-br from-[#1668d6] to-[#1fc4ff] text-white shadow-[0_4px_12px_-2px_rgba(22,104,214,0.5)]'}
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
  onDark?: boolean;
}

const PulseChip = ({ icon: Icon, text, onDark = false }: PulseChipProps) => (
  <div
    className={
      onDark
        ? 'inline-flex items-center gap-2 px-4 py-2 rounded-full backdrop-blur-md bg-white/[0.13] border border-white/25 text-sm text-white'
        : 'inline-flex items-center gap-2 px-4 py-2 rounded-full backdrop-blur-xl bg-white/50 dark:bg-white/[0.06] border border-white/40 shadow-[0_4px_16px_0_rgba(31,38,135,0.06)] text-sm text-[hsl(var(--dunatech-navy))]'
    }
  >
    <Icon className={onDark ? 'h-4 w-4 text-cyan-200' : 'h-4 w-4 text-[hsl(var(--dunatech-blue))]'} />
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
    <div className="relative space-y-8 px-3 pt-4 sm:px-6 sm:pt-6">
      {/* Hero de boas-vindas — identidade DunaTech (navy -> ciano + ondas) */}
      <section
        className="relative overflow-hidden rounded-2xl px-6 py-8 sm:px-10 sm:py-10 shadow-[0_14px_44px_-12px_rgba(13,33,71,0.55)]"
        style={{
          background:
            'linear-gradient(118deg, #081226 0%, #0d2147 38%, #1668d6 72%, #1fc4ff 100%)',
        }}
      >
        {/* Ondas/dunas fluidas da marca */}
        <svg
          aria-hidden="true"
          viewBox="0 0 820 320"
          preserveAspectRatio="none"
          className="pointer-events-none absolute inset-0 h-full w-full opacity-50"
        >
          <path d="M-20,150 C180,90 360,210 600,140 C720,104 800,150 840,130" fill="none" stroke="rgba(255,255,255,0.45)" strokeWidth="1.3" />
          <path d="M-20,200 C200,140 420,250 660,180 C760,150 820,190 840,175" fill="none" stroke="rgba(255,255,255,0.30)" strokeWidth="1" />
          <path d="M-20,250 C240,196 460,290 720,224 C780,208 820,232 840,222" fill="none" stroke="rgba(255,255,255,0.20)" strokeWidth="1" />
          <path d="M-20,104 C160,64 320,150 520,104 C660,72 760,108 840,92" fill="none" stroke="rgba(120,210,255,0.40)" strokeWidth="1" />
        </svg>

        <div className="relative z-10 space-y-5">
          {/* Wordmark DunaFlow */}
          <div className="flex items-center gap-2 text-white">
            <svg width="28" height="17" viewBox="0 0 40 24" aria-hidden="true">
              <path d="M2,15 C9,8 13,8 20,13 C26,17 31,16 38,10" fill="none" stroke="#fff" strokeWidth="3" strokeLinecap="round" />
              <path d="M3,21 C10,15 14,15 20,19 C25,22 30,21 37,16" fill="none" stroke="#fff" strokeWidth="2.4" strokeLinecap="round" opacity="0.75" />
            </svg>
            <span className="text-sm font-medium tracking-[0.18em]">
              DUNA<span className="font-normal opacity-80">FLOW</span>
            </span>
          </div>

          {/* Saudação */}
          <div className="space-y-2">
            <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-white">
              {greeting}
              {user?.name ? `, ${firstName(user.name)}` : ''}.
            </h1>
            <p className="text-sm text-white/80 max-w-xl leading-relaxed">
              Central DunaFlow de tratamento jurídico automatizado. Publicações, prazos
              iniciais e andamentos em um só lugar.
            </p>
          </div>

          {/* Pulso da equipe (chips de vidro sobre o hero) */}
          {canUsePublications && pubsOverview?.kpis && (
            <div className="flex flex-wrap gap-3 pt-1">
              <PulseChip
                onDark
                icon={Flame}
                text={`${pubsOverview.kpis.tratadas_janela ?? 0} publicações tratadas pela equipe nos últimos 7 dias`}
              />
              {nextAutomation?.next_run_at && (
                <PulseChip
                  onDark
                  icon={CalendarCheck2}
                  text={`Próximo agendamento automático: ${formatTimeBR(nextAutomation.next_run_at)}`}
                />
              )}
              <PulseChip
                onDark
                icon={CheckCircle2}
                text={`Backlog: ${pubsOverview.kpis.pendentes_agora ?? 0} pendentes`}
              />
            </div>
          )}
        </div>
      </section>

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
          DunaFlow · MDR Advocacia
        </span>
        <span className="hidden sm:inline">
          Use o botão de feedback no canto inferior direito para reportar qualquer coisa.
        </span>
      </footer>
    </div>
  );
};

export default LandingPage;
