/**
 * VisaoGeralTab — dashboard operacional do Base Processual.
 *
 * Estrutura (north star = "operador abre e em 10s sabe se o cliente sacaneou hoje"):
 *
 * 1. Alerta de inatividade (banner amarelo se >24h sem upload).
 * 2. 4 cards superiores: Ativos / Entraram hoje / Saíram hoje / Atualizados hoje.
 * 3. Painel "Movimentação do dia" — duas colunas: 🟢 entraram, 🔴 saíram.
 * 4. Gráfico linha (3 séries) de eventos por dia, ultimos 90d.
 * 5. (opcional) Top responsáveis + distribuição UF — placeholder lateral.
 */

import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowDownLeft,
  ArrowUpRight,
  PencilLine,
  Users,
} from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import {
  Alert,
  AlertDescription,
  AlertTitle,
} from "@/components/ui/alert";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

import {
  type MovimentacaoItem,
  getDashboardInatividade,
  getDashboardMovimentacaoDoDia,
  getDashboardResumo,
  getDashboardSerieDiaria,
} from "@/lib/api-base-processual";
import { cn } from "@/lib/utils";

function fmtNum(n: number): string {
  return n.toLocaleString("pt-BR");
}

function fmtDateBR(dateStr: string | null): string {
  if (!dateStr) return "—";
  try {
    return new Date(dateStr).toLocaleString("pt-BR", {
      timeZone: "America/Sao_Paulo",
    });
  } catch {
    return dateStr;
  }
}

function fmtDayBR(dateStr: string): string {
  try {
    return new Date(dateStr).toLocaleDateString("pt-BR", {
      day: "2-digit",
      month: "2-digit",
    });
  } catch {
    return dateStr;
  }
}

export function VisaoGeralTab() {
  const resumoQ = useQuery({
    queryKey: ["base-processual-dashboard", "resumo"],
    queryFn: getDashboardResumo,
  });
  const inatividadeQ = useQuery({
    queryKey: ["base-processual-dashboard", "inatividade"],
    queryFn: getDashboardInatividade,
  });
  const serieQ = useQuery({
    queryKey: ["base-processual-dashboard", "serie-diaria"],
    queryFn: () => getDashboardSerieDiaria(),
  });
  const movimentacaoQ = useQuery({
    queryKey: ["base-processual-dashboard", "movimentacao-do-dia"],
    queryFn: () => getDashboardMovimentacaoDoDia(),
  });

  const resumo = resumoQ.data;
  const inatividade = inatividadeQ.data;
  const movimentacao = movimentacaoQ.data;
  const serie = serieQ.data;

  // recharts data formatado
  const chartData =
    serie?.items.map((i) => ({
      data: fmtDayBR(i.data),
      Novos: i.novos,
      Saídos: i.removidos,
      Atualizados: i.atualizados,
    })) ?? [];

  return (
    <div className="space-y-6">
      {/* Banner de inatividade */}
      {inatividade?.alerta && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>Atenção: sem uploads recentes</AlertTitle>
          <AlertDescription>
            {inatividade.horas_desde_ultimo
              ? `Último upload concluído há ${inatividade.horas_desde_ultimo.toFixed(
                  1,
                )}h (limite: ${inatividade.threshold_horas}h).`
              : "Nenhum upload concluído até agora. Suba a planilha do dia."}
          </AlertDescription>
        </Alert>
      )}

      {/* 4 KPI cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <KpiCard
          label="Ativos na base"
          value={resumo?.total_ativos_na_base ?? 0}
          loading={resumoQ.isLoading}
          icon={<Users className="h-4 w-4" />}
          subtitle={
            resumo?.total_removidos_na_base
              ? `${fmtNum(resumo.total_removidos_na_base)} removidos`
              : undefined
          }
          tone="default"
        />
        <KpiCard
          label="Entraram hoje"
          value={resumo?.novos_hoje ?? 0}
          loading={resumoQ.isLoading}
          icon={<ArrowDownLeft className="h-4 w-4" />}
          tone="success"
        />
        <KpiCard
          label="Saíram hoje"
          value={resumo?.saidos_hoje ?? 0}
          loading={resumoQ.isLoading}
          icon={<ArrowUpRight className="h-4 w-4" />}
          tone="danger"
        />
        <KpiCard
          label="Atualizados hoje"
          value={resumo?.atualizados_hoje ?? 0}
          loading={resumoQ.isLoading}
          icon={<PencilLine className="h-4 w-4" />}
          tone="warning"
        />
      </div>

      {/* Movimentação do dia — destaque do dashboard */}
      <Card>
        <CardHeader>
          <CardTitle>Movimentação de hoje</CardTitle>
          <CardDescription>
            Quem entrou (lado esquerdo) e quem saiu (direito). Carteira saiu da
            planilha = soft-remove (não é deletado, vira <em>removido</em>).
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <MovimentacaoColuna
              titulo="🟢 Entraram"
              total={movimentacao?.entraram_total ?? 0}
              items={movimentacao?.entraram ?? []}
              loading={movimentacaoQ.isLoading}
              tone="success"
            />
            <MovimentacaoColuna
              titulo="🔴 Saíram"
              total={movimentacao?.sairam_total ?? 0}
              items={movimentacao?.sairam ?? []}
              loading={movimentacaoQ.isLoading}
              tone="danger"
              vistoEmLabel="visto pela última vez"
            />
          </div>
          {(movimentacao?.atualizados_total ?? 0) > 0 && (
            <div className="mt-4 pt-4 border-t">
              <MovimentacaoColuna
                titulo="🟡 Atualizados"
                total={movimentacao?.atualizados_total ?? 0}
                items={movimentacao?.atualizados ?? []}
                loading={movimentacaoQ.isLoading}
                tone="warning"
                showChangedFields
              />
            </div>
          )}
        </CardContent>
      </Card>

      {/* Gráfico série diária */}
      <Card>
        <CardHeader>
          <CardTitle>Movimentação dos últimos 90 dias</CardTitle>
          <CardDescription>Entradas, saídas e atualizações por dia.</CardDescription>
        </CardHeader>
        <CardContent>
          {serieQ.isLoading ? (
            <div className="h-64 flex items-center justify-center text-muted-foreground text-sm">
              Carregando...
            </div>
          ) : chartData.length === 0 ? (
            <div className="h-64 flex items-center justify-center text-muted-foreground text-sm">
              Sem dados pra esse período.
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                <XAxis dataKey="data" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} />
                <Tooltip />
                <Legend />
                <Line
                  type="monotone"
                  dataKey="Novos"
                  stroke="#10b981"
                  strokeWidth={2}
                  dot={false}
                />
                <Line
                  type="monotone"
                  dataKey="Saídos"
                  stroke="#ef4444"
                  strokeWidth={2}
                  dot={false}
                />
                <Line
                  type="monotone"
                  dataKey="Atualizados"
                  stroke="#f59e0b"
                  strokeWidth={2}
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          )}
        </CardContent>
      </Card>

      {/* Top responsáveis + distribuição UF */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card>
          <CardHeader>
            <CardTitle>Top responsáveis (carteira ativa)</CardTitle>
          </CardHeader>
          <CardContent>
            {resumoQ.isLoading ? (
              <div className="text-sm text-muted-foreground">Carregando...</div>
            ) : (resumo?.top_responsaveis ?? []).length === 0 ? (
              <div className="text-sm text-muted-foreground">
                Nenhum processo na carteira.
              </div>
            ) : (
              <ul className="space-y-2">
                {resumo!.top_responsaveis.map((r, i) => (
                  <li
                    key={`${r.usuario_responsavel ?? "—"}-${i}`}
                    className="flex justify-between items-baseline border-b last:border-0 pb-1"
                  >
                    <span className="text-sm truncate">
                      {r.usuario_responsavel ?? (
                        <em className="text-muted-foreground">
                          (sem responsável)
                        </em>
                      )}
                    </span>
                    <span className="font-mono tabular-nums text-sm">
                      {fmtNum(r.total)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Distribuição por UF</CardTitle>
          </CardHeader>
          <CardContent>
            {resumoQ.isLoading ? (
              <div className="text-sm text-muted-foreground">Carregando...</div>
            ) : (resumo?.distribuicao_uf ?? []).length === 0 ? (
              <div className="text-sm text-muted-foreground">
                Nenhum processo na carteira.
              </div>
            ) : (
              <ResponsiveContainer width="100%" height={Math.max(160, (resumo!.distribuicao_uf.length) * 24)}>
                <BarChart
                  data={resumo!.distribuicao_uf
                    .slice(0, 12)
                    .map((u) => ({ uf: u.uf ?? "—", total: u.total }))}
                  layout="vertical"
                >
                  <XAxis type="number" tick={{ fontSize: 11 }} />
                  <YAxis
                    type="category"
                    dataKey="uf"
                    tick={{ fontSize: 11 }}
                    width={32}
                  />
                  <Tooltip />
                  <Bar dataKey="total" fill="#6366f1" />
                </BarChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Footer info */}
      {resumo?.ultimo_upload_em && (
        <div className="text-xs text-muted-foreground">
          Último upload:{" "}
          <strong>{resumo.ultimo_upload_filename ?? "—"}</strong> em{" "}
          {fmtDateBR(resumo.ultimo_upload_em)} (status:{" "}
          {resumo.ultimo_upload_status}).
        </div>
      )}
    </div>
  );
}

function KpiCard({
  label,
  value,
  loading,
  icon,
  subtitle,
  tone,
}: {
  label: string;
  value: number;
  loading: boolean;
  icon: React.ReactNode;
  subtitle?: string;
  tone: "default" | "success" | "danger" | "warning";
}) {
  const toneClass: Record<typeof tone, string> = {
    default: "text-foreground",
    success: "text-emerald-600 dark:text-emerald-400",
    danger: "text-red-600 dark:text-red-400",
    warning: "text-amber-600 dark:text-amber-400",
  };
  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-center justify-between text-muted-foreground text-xs uppercase tracking-wide">
          <span>{label}</span>
          {icon}
        </div>
        <div
          className={cn(
            "mt-2 text-3xl font-semibold tabular-nums",
            toneClass[tone],
          )}
        >
          {loading ? "—" : fmtNum(value)}
        </div>
        {subtitle && (
          <div className="text-xs text-muted-foreground mt-1">{subtitle}</div>
        )}
      </CardContent>
    </Card>
  );
}

function MovimentacaoColuna({
  titulo,
  total,
  items,
  loading,
  tone,
  vistoEmLabel,
  showChangedFields,
}: {
  titulo: string;
  total: number;
  items: MovimentacaoItem[];
  loading: boolean;
  tone: "success" | "danger" | "warning";
  vistoEmLabel?: string;
  showChangedFields?: boolean;
}) {
  const toneClass: Record<typeof tone, string> = {
    success: "text-emerald-600 dark:text-emerald-400",
    danger: "text-red-600 dark:text-red-400",
    warning: "text-amber-600 dark:text-amber-400",
  };
  return (
    <div>
      <div className="flex items-baseline justify-between mb-2">
        <h4 className={cn("text-sm font-semibold", toneClass[tone])}>
          {titulo}
        </h4>
        <span className="text-xs text-muted-foreground tabular-nums">
          {fmtNum(total)} total
        </span>
      </div>
      {loading ? (
        <div className="text-sm text-muted-foreground py-6 text-center">
          Carregando...
        </div>
      ) : items.length === 0 ? (
        <div className="text-sm text-muted-foreground py-6 text-center">
          Nenhuma movimentação.
        </div>
      ) : (
        <ul className="space-y-1 max-h-72 overflow-y-auto pr-1">
          {items.map((i) => (
            <li
              key={i.evento_id}
              className="flex flex-col gap-0.5 text-xs border-b last:border-0 py-1"
            >
              <div className="flex items-center gap-2">
                <span className="font-mono font-medium">{i.cod_ajus}</span>
                {i.numero_processo_mascarado && (
                  <span className="text-muted-foreground truncate">
                    {i.numero_processo_mascarado}
                  </span>
                )}
              </div>
              <div className="text-muted-foreground flex gap-2 items-center flex-wrap">
                {i.uf && i.comarca && (
                  <span>
                    {i.uf} · {i.comarca}
                  </span>
                )}
                {i.usuario_responsavel && (
                  <span>· {i.usuario_responsavel}</span>
                )}
                {vistoEmLabel && i.visto_em && (
                  <span>
                    · {vistoEmLabel}: {fmtDateBR(i.visto_em)}
                  </span>
                )}
              </div>
              {showChangedFields && i.changed_fields && (
                <div className="text-[10px] text-muted-foreground font-mono truncate">
                  {Object.keys(i.changed_fields).join(", ")}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
