// frontend/src/pages/OnerequestDashboardPage.tsx
//
// Dashboard do OneRequest (DMIs do Banco do Brasil) — visão operacional + risco.
// KPIs, série diária recebimentos × agendamentos, situação dos prazos (farol),
// distribuição por setor e carga por responsável. Estilo do dashboard de
// Publicações. Acesso pela mesma permissão can_use_onerequest.

import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip as RTooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  CalendarClock,
  CheckCircle2,
  Inbox,
  type LucideIcon,
  RefreshCw,
  UserX,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useToast } from "@/hooks/use-toast";
import { DashboardData, getDashboard } from "@/services/onerequest";

const PERIODOS = [7, 14, 30, 60, 90];

const FAROL_META: { key: string; label: string; color: string }[] = [
  { key: "atrasado", label: "Atrasadas", color: "#be123c" },
  { key: "vermelho", label: "Vence hoje", color: "#ef4444" },
  { key: "amarelo", label: "Amanhã", color: "#f59e0b" },
  { key: "roxo", label: "Fim de semana", color: "#a855f7" },
  { key: "verde", label: "Futuras", color: "#10b981" },
  { key: "cinza", label: "Sem prazo", color: "#94a3b8" },
];

function fmtDia(iso: string): string {
  const [, m, d] = iso.split("-");
  return `${d}/${m}`;
}

function Kpi({
  label,
  value,
  icon: Icon,
  tone,
}: {
  label: string;
  value: number;
  icon: LucideIcon;
  tone: string;
}) {
  return (
    <Card>
      <CardContent className="flex items-center gap-3 p-4">
        <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full ${tone}`}>
          <Icon className="h-4 w-4" />
        </span>
        <div className="min-w-0">
          <div className="text-2xl font-bold leading-none">{value}</div>
          <div className="truncate text-xs text-muted-foreground">{label}</div>
        </div>
      </CardContent>
    </Card>
  );
}

export default function OnerequestDashboardPage() {
  const { toast } = useToast();
  const navigate = useNavigate();
  const [days, setDays] = useState(30);
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await getDashboard(days));
    } catch (e) {
      toast({
        title: "Erro ao carregar dashboard",
        description: String((e as Error).message),
        variant: "destructive",
      });
    } finally {
      setLoading(false);
    }
  }, [days, toast]);

  useEffect(() => {
    load();
  }, [load]);

  const k = data?.kpis ?? {};

  // Série combinada (recebidas × agendadas) alinhada por índice de dia.
  const serie = useMemo(
    () =>
      (data?.recebimentos ?? []).map((r, i) => ({
        dia: fmtDia(r.dia),
        recebidas: r.n,
        agendadas: data?.agendamentos?.[i]?.n ?? 0,
      })),
    [data],
  );

  const farolData = useMemo(() => {
    const rows = FAROL_META.map((f) => ({ ...f, n: data?.farol?.[f.key] ?? 0 })).filter((f) => f.n > 0);
    const total = rows.reduce((s, x) => s + x.n, 0) || 1;
    return { rows, total };
  }, [data]);

  const setorData = (data?.por_setor ?? []).slice(0, 8);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <button
            type="button"
            onClick={() => navigate("/onerequest")}
            className="mb-1 flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="h-3 w-3" /> Voltar ao painel de DMIs
          </button>
          <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
            <Activity className="h-6 w-6 text-[hsl(var(--dunatech-blue))]" />
            Dashboard — OneRequest
          </h1>
          <p className="text-sm text-muted-foreground">
            Visão operacional e de risco das DMIs do Banco do Brasil.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Select value={String(days)} onValueChange={(v) => setDays(Number(v))}>
            <SelectTrigger className="w-36">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PERIODOS.map((p) => (
                <SelectItem key={p} value={String(p)}>
                  Últimos {p} dias
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button variant="outline" size="icon" onClick={() => load()} disabled={loading}>
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          </Button>
        </div>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <Kpi label="Abertas (em tratamento)" value={k.abertas ?? 0} icon={Inbox} tone="bg-blue-100 text-blue-700" />
        <Kpi label="Atrasadas" value={k.atrasadas ?? 0} icon={AlertTriangle} tone="bg-rose-100 text-rose-700" />
        <Kpi label="Vencem hoje" value={k.hoje ?? 0} icon={CalendarClock} tone="bg-red-100 text-red-700" />
        <Kpi label="Sem responsável" value={k.sem_responsavel ?? 0} icon={UserX} tone="bg-amber-100 text-amber-700" />
        <Kpi label="Agendadas no L1" value={k.agendadas ?? 0} icon={CheckCircle2} tone="bg-emerald-100 text-emerald-700" />
        <Kpi label="Concluídas (total)" value={k.concluidas ?? 0} icon={CheckCircle2} tone="bg-slate-100 text-slate-700" />
      </div>

      {/* Recebimentos × Agendamentos */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Recebimentos × Agendamentos por dia</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="h-72 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={serie} margin={{ top: 5, right: 10, left: -12, bottom: 0 }}>
                <defs>
                  <linearGradient id="gRec" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.35} />
                    <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                  </linearGradient>
                  <linearGradient id="gAge" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#10b981" stopOpacity={0.35} />
                    <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                <XAxis dataKey="dia" fontSize={11} tickLine={false} minTickGap={16} />
                <YAxis fontSize={11} tickLine={false} axisLine={false} allowDecimals={false} width={28} />
                <RTooltip />
                <Legend />
                <Area type="monotone" dataKey="recebidas" name="Recebidas" stroke="#3b82f6" fill="url(#gRec)" strokeWidth={2} />
                <Area type="monotone" dataKey="agendadas" name="Agendadas" stroke="#10b981" fill="url(#gAge)" strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>

      {/* Situação dos prazos (farol) + Por setor */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Situação dos prazos (DMIs abertas)</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2.5">
            {farolData.rows.length === 0 ? (
              <p className="py-8 text-center text-sm text-muted-foreground">Sem DMIs abertas.</p>
            ) : (
              farolData.rows.map((f) => (
                <div key={f.key} className="flex items-center gap-2">
                  <span className="w-28 shrink-0 text-xs text-muted-foreground">{f.label}</span>
                  <div className="h-4 flex-1 overflow-hidden rounded bg-muted">
                    <div
                      className="h-full rounded"
                      style={{ width: `${(f.n / farolData.total) * 100}%`, background: f.color }}
                    />
                  </div>
                  <span className="w-8 text-right text-xs font-medium tabular-nums">{f.n}</span>
                </div>
              ))
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">DMIs abertas por setor</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="h-64 w-full">
              {setorData.length === 0 ? (
                <p className="py-8 text-center text-sm text-muted-foreground">Sem dados.</p>
              ) : (
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={setorData} layout="vertical" margin={{ left: 12, right: 16 }}>
                    <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="hsl(var(--border))" />
                    <XAxis type="number" fontSize={11} allowDecimals={false} />
                    <YAxis type="category" dataKey="setor" width={120} fontSize={11} tickLine={false} />
                    <RTooltip />
                    <Bar dataKey="n" name="Abertas" fill="#3b82f6" radius={[0, 4, 4, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Carga por responsável (risco) */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Carga por responsável</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Responsável</TableHead>
                  <TableHead className="text-right">Abertas</TableHead>
                  <TableHead className="text-right">Atrasadas</TableHead>
                  <TableHead className="text-right">Agendadas</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(data?.por_responsavel ?? []).length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={4} className="py-8 text-center text-muted-foreground">
                      {loading ? "Carregando…" : "Nenhuma DMI aberta distribuída."}
                    </TableCell>
                  </TableRow>
                ) : (
                  (data?.por_responsavel ?? []).map((r) => (
                    <TableRow key={r.nome}>
                      <TableCell className="text-sm">{r.nome}</TableCell>
                      <TableCell className="text-right tabular-nums">{r.abertas}</TableCell>
                      <TableCell className="text-right tabular-nums">
                        {r.atrasadas > 0 ? (
                          <span className="font-medium text-rose-700">{r.atrasadas}</span>
                        ) : (
                          r.atrasadas
                        )}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">{r.agendadas}</TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
