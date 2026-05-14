// frontend/src/components/classificador/PainelGlobalTab.tsx
//
// Painel cross-lote — visao consolidada de TODOS os lotes que casam
// com os filtros (cliente, periodo, only_classified). Substitui o
// placeholder da aba "Painel" do ClassificadorPage.

import { useEffect, useState } from "react";
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell,
  Legend, Line, LineChart, Pie, PieChart, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from "recharts";
import { Loader2, RefreshCw, Filter } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useToast } from "@/components/ui/use-toast";
import {
  ClassificadorDashboardGlobal,
  fetchClassificadorDashboardGlobal,
} from "@/services/api";


const PALETTE = [
  "#1A365D", "#2C5282", "#2B6CB0", "#3182CE", "#4299E1",
  "#63B3ED", "#90CDF4", "#BEE3F8", "#A0AEC0", "#718096",
];
const COR_PRIMARY = "#1A365D";
const COR_ACCENT = "#2C5282";


function fmtBRL(v: number | null | undefined): string {
  if (v == null) return "—";
  return v.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

function fmtCompactBRL(v: number | null | undefined): string {
  if (v == null) return "—";
  if (Math.abs(v) >= 1_000_000) return `R$ ${(v / 1_000_000).toFixed(1)}M`;
  if (Math.abs(v) >= 1_000) return `R$ ${(v / 1_000).toFixed(1)}k`;
  return fmtBRL(v);
}

function fmtPct(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${(v * 100).toFixed(1)}%`;
}

function fmtInt(v: number | null | undefined): string {
  if (v == null) return "—";
  return v.toLocaleString("pt-BR");
}

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleDateString("pt-BR"); } catch { return iso; }
}


function KpiCard({
  label, value, sub, accent = COR_PRIMARY,
}: { label: string; value: string; sub?: string; accent?: string }) {
  return (
    <div className="rounded-md border bg-card p-3">
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="text-2xl font-semibold mt-1" style={{ color: accent }}>{value}</div>
      {sub && <div className="text-[11px] text-muted-foreground mt-0.5">{sub}</div>}
    </div>
  );
}

function ChartTooltip({ active, payload, label, valueFormatter }: any) {
  if (!active || !payload || !payload.length) return null;
  return (
    <div className="rounded-md border bg-card shadow-sm px-2 py-1.5 text-xs">
      {label && <div className="font-medium mb-0.5">{label}</div>}
      {payload.map((p: any, i: number) => (
        <div key={i} className="flex items-center gap-2">
          <span className="h-2 w-2 inline-block" style={{ background: p.color || p.fill || p.stroke }} />
          <span className="text-muted-foreground">{p.name}:</span>
          <span className="font-mono">
            {valueFormatter ? valueFormatter(p.value) : p.value}
          </span>
        </div>
      ))}
    </div>
  );
}


export default function PainelGlobalTab() {
  const { toast } = useToast();
  const [clienteNome, setClienteNome] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [onlyClassified, setOnlyClassified] = useState(false);
  const [data, setData] = useState<ClassificadorDashboardGlobal | null>(null);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const r = await fetchClassificadorDashboardGlobal({
        cliente_nome: clienteNome.trim() || undefined,
        start: start || undefined,
        end: end || undefined,
        only_classified: onlyClassified || undefined,
      });
      setData(r);
    } catch (err) {
      toast({
        title: "Falha ao carregar painel global",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setLoading(false);
    }
  };

  // 1ª carga sem filtros
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Pizza categoria — top 7 + outros
  const cats = (data?.por_categoria || []).slice();
  const cats_top = cats.slice(0, 7);
  const cats_rest_qtd = cats.slice(7).reduce((s, c) => s + (c.qtd || 0), 0);
  const pieData = cats_top.map(c => ({ name: c.label, value: c.qtd || 0 }));
  if (cats_rest_qtd > 0) pieData.push({ name: `Outros (${cats.length - 7})`, value: cats_rest_qtd });

  // Barras patrocinio
  const patrocinioData = (data?.por_patrocinio || []).map(p => ({
    name: p.label,
    qtd: p.qtd || 0,
    valor: p.valor_estimado || 0,
  }));

  // Timeline (LineChart)
  const timelineData = (data?.timeline || []).map(t => ({
    date: t.date,
    label: new Date(t.date).toLocaleDateString("pt-BR", { day: "2-digit", month: "short" }),
    lotes: t.qtd_lotes,
    processos: t.qtd_processos,
    valor: t.valor / 1000, // em milhares pra escala caber
  }));

  // Top lotes por valor
  const topLotes = [...(data?.lotes || [])]
    .sort((a, b) => (b.valor_total_estimado || 0) - (a.valor_total_estimado || 0))
    .slice(0, 10);

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-2 mb-1">
        <div>
          <h2 className="text-lg font-semibold tracking-tight">Painel Global</h2>
          <p className="text-xs text-muted-foreground">
            Visão consolidada de todos os lotes que casam com os filtros.
            Dados atualizados em tempo real do banco.
          </p>
        </div>
        <Button variant="ghost" size="sm" onClick={load} disabled={loading}>
          {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
        </Button>
      </div>

      {/* ─── Filtros ─── */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-2">
            <Filter className="h-3.5 w-3.5" />
            Filtros
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
            <div>
              <Label htmlFor="g-cli" className="text-[10px]">Cliente</Label>
              <Input
                id="g-cli"
                value={clienteNome}
                onChange={e => setClienteNome(e.target.value)}
                placeholder="Banco Master, ..."
                className="h-8 text-xs"
              />
            </div>
            <div>
              <Label htmlFor="g-start" className="text-[10px]">Data criação ≥</Label>
              <Input
                id="g-start"
                type="date"
                value={start}
                onChange={e => setStart(e.target.value)}
                className="h-8 text-xs"
              />
            </div>
            <div>
              <Label htmlFor="g-end" className="text-[10px]">Data criação ≤</Label>
              <Input
                id="g-end"
                type="date"
                value={end}
                onChange={e => setEnd(e.target.value)}
                className="h-8 text-xs"
              />
            </div>
            <div className="flex items-end gap-2">
              <label className="flex items-center gap-1.5 text-xs">
                <input
                  type="checkbox"
                  checked={onlyClassified}
                  onChange={e => setOnlyClassified(e.target.checked)}
                />
                Só lotes classificados
              </label>
            </div>
          </div>
          <div className="flex gap-2 mt-3">
            <Button size="sm" onClick={load} disabled={loading}>
              {loading && <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />}
              Aplicar
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setClienteNome(""); setStart(""); setEnd(""); setOnlyClassified(false);
                setTimeout(load, 0);
              }}
            >
              Limpar
            </Button>
          </div>
        </CardContent>
      </Card>

      {loading && !data ? (
        <div className="py-12 text-center text-sm text-muted-foreground">
          <Loader2 className="inline h-4 w-4 animate-spin mr-2" />
          Carregando...
        </div>
      ) : !data || data.total_lotes === 0 ? (
        <div className="py-12 text-center text-sm text-muted-foreground">
          Nenhum lote casa com os filtros. Ajuste ou crie um novo lote.
        </div>
      ) : (
        <>
          {/* ─── Resumo ─── */}
          <div className="text-xs text-muted-foreground">
            Mostrando agregado de <strong>{data.total_lotes}</strong> lote{data.total_lotes > 1 ? "s" : ""}
            {" "}atualizado em {new Date(data.generated_at).toLocaleString("pt-BR")}
          </div>

          {/* ─── 4 KPI cards ─── */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <KpiCard
              label="Processos (total)"
              value={fmtInt(data.kpis.total_processos)}
              sub={`${fmtInt(data.kpis.total_classificados)} classificados`}
            />
            <KpiCard
              label="Valor estimado"
              value={fmtCompactBRL(data.kpis.valor_total_estimado)}
              sub={`Causa: ${fmtCompactBRL(data.kpis.valor_total_causa)}`}
              accent={COR_ACCENT}
            />
            <KpiCard
              label="PCOND total"
              value={fmtCompactBRL(data.kpis.pcond_total)}
              sub="Aprovisionamento agregado"
              accent="#9F7AEA"
            />
            <KpiCard
              label="Prob. êxito média"
              value={fmtPct(data.kpis.prob_exito_medio)}
              sub="Ponderada entre lotes"
              accent="#38A169"
            />
          </div>

          {/* ─── Timeline + Pizza ─── */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            <div className="rounded-md border p-3">
              <div className="text-xs font-medium mb-2">Timeline — lotes criados por dia</div>
              {timelineData.length === 0 ? (
                <div className="h-64 flex items-center justify-center text-muted-foreground text-xs">Sem dados</div>
              ) : (
                <ResponsiveContainer width="100%" height={260}>
                  <AreaChart data={timelineData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="label" tick={{ fontSize: 10 }} />
                    <YAxis tick={{ fontSize: 10 }} />
                    <Tooltip content={<ChartTooltip valueFormatter={(v: number) => fmtInt(v)} />} />
                    <Area
                      type="monotone"
                      dataKey="processos"
                      stroke={COR_PRIMARY}
                      fill={COR_ACCENT}
                      fillOpacity={0.3}
                      name="Processos"
                    />
                  </AreaChart>
                </ResponsiveContainer>
              )}
            </div>

            <div className="rounded-md border p-3">
              <div className="text-xs font-medium mb-2">Distribuição por categoria</div>
              {pieData.length === 0 ? (
                <div className="h-64 flex items-center justify-center text-muted-foreground text-xs">Sem dados</div>
              ) : (
                <ResponsiveContainer width="100%" height={260}>
                  <PieChart>
                    <Pie
                      data={pieData}
                      dataKey="value"
                      nameKey="name"
                      cx="50%" cy="50%"
                      outerRadius={80}
                      label={(p: any) => `${p.value}`}
                      labelLine={false}
                    >
                      {pieData.map((_, i) => (
                        <Cell key={i} fill={PALETTE[i % PALETTE.length]} />
                      ))}
                    </Pie>
                    <Tooltip content={<ChartTooltip valueFormatter={(v: number) => fmtInt(v)} />} />
                    <Legend wrapperStyle={{ fontSize: 10 }} />
                  </PieChart>
                </ResponsiveContainer>
              )}
            </div>
          </div>

          {/* ─── Patrocínio + Ranking lotes ─── */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            <div className="rounded-md border p-3">
              <div className="text-xs font-medium mb-2">Distribuição por patrocínio</div>
              {patrocinioData.length === 0 ? (
                <div className="h-64 flex items-center justify-center text-muted-foreground text-xs">Sem dados</div>
              ) : (
                <ResponsiveContainer width="100%" height={260}>
                  <BarChart data={patrocinioData} layout="vertical" margin={{ left: 20, right: 10 }}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis type="number" tick={{ fontSize: 10 }} />
                    <YAxis dataKey="name" type="category" tick={{ fontSize: 10 }} width={140} />
                    <Tooltip content={<ChartTooltip valueFormatter={(v: number) => fmtInt(v)} />} />
                    <Bar dataKey="qtd" fill={COR_ACCENT} name="Quantidade" />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </div>

            <div className="rounded-md border p-3">
              <div className="text-xs font-medium mb-2">Top 10 lotes por valor estimado</div>
              {topLotes.length === 0 ? (
                <div className="py-6 text-center text-xs text-muted-foreground">Sem dados</div>
              ) : (
                <div className="overflow-x-auto max-h-64 overflow-y-auto">
                  <table className="w-full text-xs">
                    <thead className="sticky top-0 bg-card">
                      <tr className="border-b text-left text-muted-foreground">
                        <th className="py-1 pr-2">#</th>
                        <th className="py-1 pr-2">Nome</th>
                        <th className="py-1 pr-2 text-right">Proc.</th>
                        <th className="py-1 pr-2 text-right">Valor</th>
                        <th className="py-1 pr-2 text-right">PCOND</th>
                      </tr>
                    </thead>
                    <tbody>
                      {topLotes.map(l => (
                        <tr key={l.id} className="border-b hover:bg-muted/30">
                          <td className="py-1 pr-2 font-mono">#{l.id}</td>
                          <td className="py-1 pr-2">
                            <div className="truncate max-w-[180px]" title={l.nome}>{l.nome}</div>
                            <div className="text-[10px] text-muted-foreground">
                              {l.cliente_nome || "—"} · {fmtDate(l.created_at)}
                            </div>
                          </td>
                          <td className="py-1 pr-2 text-right tabular-nums">
                            {l.total_classificados}/{l.total_processos}
                          </td>
                          <td className="py-1 pr-2 text-right tabular-nums">{fmtCompactBRL(l.valor_total_estimado)}</td>
                          <td className="py-1 pr-2 text-right tabular-nums">{fmtCompactBRL(l.pcond_total)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>

          {/* ─── Lista completa de lotes ─── */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">Todos os lotes ({data.total_lotes})</CardTitle>
              <CardDescription className="text-xs">
                Ranking por data de criação. Click no lote no Histórico pra abrir detalhes.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b text-left text-muted-foreground">
                      <th className="py-1.5 pr-2">#</th>
                      <th className="py-1.5 pr-2">Nome</th>
                      <th className="py-1.5 pr-2">Cliente</th>
                      <th className="py-1.5 pr-2">Status</th>
                      <th className="py-1.5 pr-2 text-right">Processos</th>
                      <th className="py-1.5 pr-2 text-right">Valor estimado</th>
                      <th className="py-1.5 pr-2 text-right">PCOND</th>
                      <th className="py-1.5 pr-2 text-right">Êxito</th>
                      <th className="py-1.5 pr-2">Criado em</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.lotes.map(l => (
                      <tr key={l.id} className="border-b hover:bg-muted/30">
                        <td className="py-1 pr-2 font-mono">#{l.id}</td>
                        <td className="py-1 pr-2">{l.nome}</td>
                        <td className="py-1 pr-2 text-muted-foreground">{l.cliente_nome || "—"}</td>
                        <td className="py-1 pr-2">
                          <Badge variant="outline" className="text-[10px]">{l.status}</Badge>
                        </td>
                        <td className="py-1 pr-2 text-right tabular-nums">
                          {l.total_classificados}/{l.total_processos}
                        </td>
                        <td className="py-1 pr-2 text-right tabular-nums">{fmtCompactBRL(l.valor_total_estimado)}</td>
                        <td className="py-1 pr-2 text-right tabular-nums">{fmtCompactBRL(l.pcond_total)}</td>
                        <td className="py-1 pr-2 text-right tabular-nums">{fmtPct(l.prob_exito_medio)}</td>
                        <td className="py-1 pr-2 text-muted-foreground">{fmtDate(l.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
