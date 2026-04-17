import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  CalendarClock,
  CheckCircle2,
  Clock,
  FileText,
  Inbox,
  Loader2,
  TrendingUp,
} from 'lucide-react';
import {
  Area,
  AreaChart,
  CartesianGrid,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip as RTooltip,
  XAxis,
  YAxis,
} from 'recharts';

import { useAuth } from '@/hooks/useAuth';
import { useToast } from '@/hooks/use-toast';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { apiFetch } from '@/lib/api-client';
import { CaptureHealthWidget } from '@/components/CaptureHealthWidget';

// ──────────────────────────────────────────────────────────────
// Types
// ──────────────────────────────────────────────────────────────

interface SavedFilter {
  id: number;
  name: string;
  module: string;
  filters_json: string;
  is_default: boolean;
}

interface Automation {
  id: number;
  name: string;
  next_run_at: string | null;
  is_enabled: boolean;
}

interface OverviewKpis {
  pendentes_agora: number;
  tratadas_janela: number;
  agendadas_janela: number;
  recebidas_janela: number;
  taxa_erro_pct: number;
  window_days: number;
}

interface OverviewFunnel {
  novo: number;
  classificado: number;
  agendado: number;
  ignorado: number;
  erro: number;
}

interface OverviewSeries {
  date: string; // YYYY-MM-DD
  recebidas: number;
  tratadas: number;
}

interface OverviewPayload {
  kpis: OverviewKpis;
  funnel: OverviewFunnel;
  timeseries: OverviewSeries[];
  generated_at: string;
}

// ──────────────────────────────────────────────────────────────
// Paleta DUNATECH para gráficos (valores HSL das vars do design system)
// ──────────────────────────────────────────────────────────────

const BRAND = {
  navy: 'hsl(220, 74%, 14%)',
  blue: 'hsl(217, 100%, 56%)',
  blueSoft: 'hsl(215, 95%, 72%)',
  muted: 'hsl(220, 15%, 80%)',
  success: 'hsl(140, 70%, 45%)',
  warning: 'hsl(40, 90%, 50%)',
  error: 'hsl(0, 75%, 55%)',
};

const FUNNEL_COLORS: Record<keyof OverviewFunnel, string> = {
  novo: BRAND.blue,
  classificado: BRAND.blueSoft,
  agendado: BRAND.navy,
  ignorado: BRAND.muted,
  erro: BRAND.error,
};

const FUNNEL_LABELS: Record<keyof OverviewFunnel, string> = {
  novo: 'Novas',
  classificado: 'Classificadas',
  agendado: 'Agendadas',
  ignorado: 'Dado ciência',
  erro: 'Com erro',
};

// ──────────────────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────────────────

const formatDateTime = (isoString: string | null) => {
  if (!isoString) return 'N/A';
  return new Intl.DateTimeFormat('pt-BR', {
    dateStyle: 'short',
    timeStyle: 'short',
    timeZone: 'America/Sao_Paulo',
  }).format(new Date(isoString));
};

const formatShortDay = (ymd: string) => {
  // ymd = "2026-04-10" → "10/04"
  const parts = ymd.split('-');
  if (parts.length !== 3) return ymd;
  return `${parts[2]}/${parts[1]}`;
};

// ──────────────────────────────────────────────────────────────
// Componentes menores
// ──────────────────────────────────────────────────────────────

interface KpiCardProps {
  label: string;
  value: string | number;
  caption?: string;
  icon: React.ElementType;
  tone?: 'default' | 'warning' | 'error' | 'success';
  isLoading?: boolean;
  onClick?: () => void;
}

const KpiCard = ({ label, value, caption, icon: Icon, tone = 'default', isLoading, onClick }: KpiCardProps) => {
  const toneClass =
    tone === 'warning'
      ? 'text-amber-600 bg-amber-50'
      : tone === 'error'
      ? 'text-red-600 bg-red-50'
      : tone === 'success'
      ? 'text-emerald-600 bg-emerald-50'
      : 'text-[hsl(var(--dunatech-blue))] bg-[hsl(var(--dunatech-blue)/0.08)]';

  return (
    <Card
      className={`relative overflow-hidden transition-all ${
        onClick ? 'cursor-pointer hover:shadow-md hover:-translate-y-0.5' : ''
      }`}
      onClick={onClick}
    >
      <CardContent className="p-5">
        <div className="flex items-start justify-between gap-3">
          <div className="space-y-1">
            <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
              {label}
            </p>
            {isLoading ? (
              <Loader2 className="h-7 w-7 animate-spin mt-1 text-muted-foreground" />
            ) : (
              <p className="text-3xl font-bold leading-none tracking-tight text-[hsl(var(--dunatech-navy))]">
                {value}
              </p>
            )}
            {caption && <p className="text-xs text-muted-foreground pt-1">{caption}</p>}
          </div>
          <div className={`rounded-xl p-2.5 ${toneClass}`}>
            <Icon className="h-5 w-5" />
          </div>
        </div>
      </CardContent>
    </Card>
  );
};

// ──────────────────────────────────────────────────────────────
// Página principal
// ──────────────────────────────────────────────────────────────

const DashboardHome = () => {
  const navigate = useNavigate();
  const { toast } = useToast();
  const { canUsePublications, isAdmin } = useAuth();

  // Overview (KPIs + funil + série) — tudo numa chamada só
  const { data: overview, isLoading: overviewLoading } = useQuery({
    queryKey: ['dashboard-overview', 14],
    queryFn: async () => {
      const res = await apiFetch('/api/v1/dashboard/publications-overview?days=14');
      if (!res.ok) throw new Error('Falha ao carregar overview');
      return (await res.json()) as OverviewPayload;
    },
    enabled: canUsePublications,
    refetchInterval: 60_000,
  });

  const { data: savedFilters = [], isLoading: filtersLoading } = useQuery({
    queryKey: ['saved-filters', 'publications'],
    queryFn: async () => {
      const res = await apiFetch('/api/v1/me/saved-filters?module=publications');
      if (!res.ok) return [];
      return res.json() as Promise<SavedFilter[]>;
    },
    enabled: canUsePublications,
  });

  const { data: automations = [], isLoading: automationsLoading } = useQuery({
    queryKey: ['automations'],
    queryFn: async () => {
      const res = await apiFetch('/api/v1/automations');
      if (!res.ok) return [];
      const data = await res.json();
      return (Array.isArray(data) ? data : data.items || []) as Automation[];
    },
  });

  const nextAutomation = automations.find((a) => a.is_enabled && a.next_run_at)
    ? automations
        .filter((a) => a.is_enabled && a.next_run_at)
        .sort(
          (a, b) => new Date(a.next_run_at || '').getTime() - new Date(b.next_run_at || '').getTime()
        )[0]
    : null;

  const handleApplyFilter = (filter: SavedFilter) => {
    try {
      const filterState =
        typeof filter.filters_json === 'string' ? JSON.parse(filter.filters_json) : filter.filters_json;
      navigate('/publications', { state: { appliedFilter: filterState } });
    } catch {
      toast({
        title: 'Erro',
        description: 'Não foi possível aplicar o filtro.',
        variant: 'destructive',
      });
    }
  };

  const kpis = overview?.kpis;
  const funnel = overview?.funnel;
  const series = overview?.timeseries ?? [];
  const windowDays = kpis?.window_days ?? 14;

  const funnelData = funnel
    ? (Object.keys(funnel) as Array<keyof OverviewFunnel>)
        .filter((k) => (funnel[k] ?? 0) > 0)
        .map((k) => ({
          name: FUNNEL_LABELS[k],
          key: k,
          value: funnel[k],
          fill: FUNNEL_COLORS[k],
        }))
    : [];

  const chartSeries = series.map((s) => ({
    ...s,
    label: formatShortDay(s.date),
  }));

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
          <Activity className="h-6 w-6 text-[hsl(var(--dunatech-blue))]" />
          Dashboard
        </h1>
        <p className="text-sm text-muted-foreground">
          Visão operacional das publicações — últimos {windowDays} dias.
        </p>
      </div>

      {isAdmin && <CaptureHealthWidget />}

      {canUsePublications && (
        <>
          {/* KPIs */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <KpiCard
              label="Pendentes agora"
              value={kpis?.pendentes_agora ?? 0}
              caption="Aguardando classificação"
              icon={Inbox}
              tone={kpis && kpis.pendentes_agora > 0 ? 'warning' : 'default'}
              isLoading={overviewLoading}
              onClick={() => navigate('/publications?status=novo')}
            />
            <KpiCard
              label={`Tratadas em ${windowDays}d`}
              value={kpis?.tratadas_janela ?? 0}
              caption="Classificadas, agendadas ou ciência"
              icon={CheckCircle2}
              tone="success"
              isLoading={overviewLoading}
            />
            <KpiCard
              label={`Agendadas em ${windowDays}d`}
              value={kpis?.agendadas_janela ?? 0}
              caption="Tarefas geradas no Legal One"
              icon={CalendarClock}
              isLoading={overviewLoading}
              onClick={() => navigate('/publications?status=agendado')}
            />
            <KpiCard
              label={`Taxa de erro (${windowDays}d)`}
              value={`${kpis?.taxa_erro_pct ?? 0}%`}
              caption={`${kpis?.recebidas_janela ?? 0} recebidas no período`}
              icon={AlertTriangle}
              tone={kpis && kpis.taxa_erro_pct > 5 ? 'error' : 'default'}
              isLoading={overviewLoading}
            />
          </div>

          {/* Linha de gráficos: Velocidade (2/3) + Funil (1/3) */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            {/* Velocidade de tratamento */}
            <Card className="lg:col-span-2">
              <CardHeader className="pb-2">
                <div className="flex items-center justify-between gap-2 flex-wrap">
                  <div>
                    <CardTitle className="text-base flex items-center gap-2">
                      <TrendingUp className="h-4 w-4 text-[hsl(var(--dunatech-blue))]" />
                      Velocidade de tratamento
                    </CardTitle>
                    <CardDescription className="text-xs">
                      Publicações recebidas vs. tratadas por dia
                    </CardDescription>
                  </div>
                  <Badge variant="secondary" className="text-[10px]">
                    Últimos {windowDays} dias
                  </Badge>
                </div>
              </CardHeader>
              <CardContent>
                {overviewLoading ? (
                  <div className="h-[240px] flex items-center justify-center">
                    <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                  </div>
                ) : chartSeries.length === 0 ? (
                  <div className="h-[240px] flex items-center justify-center text-sm text-muted-foreground">
                    Sem dados no período.
                  </div>
                ) : (
                  <ResponsiveContainer width="100%" height={240}>
                    <AreaChart data={chartSeries} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                      <defs>
                        <linearGradient id="gRecebidas" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor={BRAND.blueSoft} stopOpacity={0.6} />
                          <stop offset="95%" stopColor={BRAND.blueSoft} stopOpacity={0} />
                        </linearGradient>
                        <linearGradient id="gTratadas" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor={BRAND.blue} stopOpacity={0.7} />
                          <stop offset="95%" stopColor={BRAND.blue} stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke="hsl(220,15%,90%)" vertical={false} />
                      <XAxis
                        dataKey="label"
                        stroke="hsl(220,15%,45%)"
                        fontSize={11}
                        tickLine={false}
                        axisLine={false}
                      />
                      <YAxis
                        stroke="hsl(220,15%,45%)"
                        fontSize={11}
                        tickLine={false}
                        axisLine={false}
                        allowDecimals={false}
                      />
                      <RTooltip
                        contentStyle={{
                          borderRadius: 10,
                          border: '1px solid hsl(220,20%,85%)',
                          fontSize: 12,
                        }}
                        labelStyle={{ color: BRAND.navy, fontWeight: 600 }}
                      />
                      <Legend
                        iconType="circle"
                        wrapperStyle={{ fontSize: 12, paddingTop: 8 }}
                      />
                      <Area
                        type="monotone"
                        dataKey="recebidas"
                        name="Recebidas"
                        stroke={BRAND.blueSoft}
                        strokeWidth={2}
                        fill="url(#gRecebidas)"
                      />
                      <Area
                        type="monotone"
                        dataKey="tratadas"
                        name="Tratadas"
                        stroke={BRAND.blue}
                        strokeWidth={2}
                        fill="url(#gTratadas)"
                      />
                    </AreaChart>
                  </ResponsiveContainer>
                )}
              </CardContent>
            </Card>

            {/* Funil de status */}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base flex items-center gap-2">
                  <FileText className="h-4 w-4 text-[hsl(var(--dunatech-blue))]" />
                  Funil atual
                </CardTitle>
                <CardDescription className="text-xs">
                  Distribuição das publicações por status
                </CardDescription>
              </CardHeader>
              <CardContent>
                {overviewLoading ? (
                  <div className="h-[240px] flex items-center justify-center">
                    <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                  </div>
                ) : funnelData.length === 0 ? (
                  <div className="h-[240px] flex items-center justify-center text-sm text-muted-foreground">
                    Sem publicações.
                  </div>
                ) : (
                  <ResponsiveContainer width="100%" height={240}>
                    <PieChart>
                      <RTooltip
                        contentStyle={{
                          borderRadius: 10,
                          border: '1px solid hsl(220,20%,85%)',
                          fontSize: 12,
                        }}
                      />
                      <Pie
                        data={funnelData}
                        dataKey="value"
                        nameKey="name"
                        innerRadius={50}
                        outerRadius={80}
                        paddingAngle={2}
                        stroke="none"
                      >
                        {funnelData.map((entry) => (
                          <Cell key={entry.key} fill={entry.fill} />
                        ))}
                      </Pie>
                      <Legend
                        iconType="circle"
                        verticalAlign="bottom"
                        wrapperStyle={{ fontSize: 11, paddingTop: 8 }}
                      />
                    </PieChart>
                  </ResponsiveContainer>
                )}
              </CardContent>
            </Card>
          </div>

          {/* Próxima rodagem + Quick Actions lado a lado */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <Card className="lg:col-span-1">
              <CardHeader className="pb-2">
                <CardTitle className="text-base flex items-center gap-2">
                  <Clock className="h-4 w-4 text-[hsl(var(--dunatech-blue))]" />
                  Próxima rodagem automática
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                {automationsLoading ? (
                  <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                ) : nextAutomation ? (
                  <>
                    <div className="text-sm font-medium">{nextAutomation.name}</div>
                    <div className="text-xs text-muted-foreground">
                      {formatDateTime(nextAutomation.next_run_at)}
                    </div>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => navigate('/automations')}
                      className="w-full"
                    >
                      Ver agendamentos
                      <ArrowRight className="h-4 w-4 ml-2" />
                    </Button>
                  </>
                ) : (
                  <p className="text-sm text-muted-foreground">Nenhum agendamento ativo.</p>
                )}
              </CardContent>
            </Card>

            <Card className="lg:col-span-2">
              <CardHeader className="pb-2">
                <CardTitle className="text-base">Ações rápidas</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-wrap gap-2">
                <Button size="sm" onClick={() => navigate('/publications?status=novo')}>
                  <Activity className="h-4 w-4 mr-2" />
                  Classificar pendentes
                </Button>
                <Button size="sm" variant="outline" onClick={() => navigate('/publications/templates')}>
                  <FileText className="h-4 w-4 mr-2" />
                  Templates
                </Button>
                <Button size="sm" variant="outline" onClick={() => navigate('/publications')}>
                  <ArrowRight className="h-4 w-4 mr-2" />
                  Ver publicações
                </Button>
                <Button size="sm" variant="outline" onClick={() => navigate('/publications/lookup')}>
                  <FileText className="h-4 w-4 mr-2" />
                  Consultar CNJ
                </Button>
              </CardContent>
            </Card>
          </div>

          {/* Meus Filtros Salvos */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Meus filtros salvos</CardTitle>
              <CardDescription className="text-xs">
                Acesse rapidamente seus filtros de publicações favoritos.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {filtersLoading ? (
                <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
              ) : savedFilters.length > 0 ? (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                  {savedFilters.map((filter) => (
                    <div
                      key={filter.id}
                      className="p-3 border rounded-lg cursor-pointer hover:bg-muted transition-colors"
                      onClick={() => handleApplyFilter(filter)}
                    >
                      <div className="flex items-start justify-between">
                        <div className="flex-1">
                          <h3 className="font-medium text-sm">{filter.name}</h3>
                          {filter.is_default && (
                            <Badge variant="secondary" className="mt-1 text-[10px]">
                              Padrão
                            </Badge>
                          )}
                        </div>
                        <ArrowRight className="h-4 w-4 text-muted-foreground mt-0.5" />
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-center py-6 text-sm text-muted-foreground">
                  <p>Nenhum filtro salvo ainda.</p>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => navigate('/publications')}
                    className="mt-3"
                  >
                    Ir para Publicações
                  </Button>
                </div>
              )}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
};

export default DashboardHome;
