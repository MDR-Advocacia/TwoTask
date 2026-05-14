// frontend/src/components/classificador/LoteVisaoTab.tsx
//
// Aba "Visao geral" do LoteDetailDialog — dashboard interativo do lote
// com KPIs + 4 graficos recharts + tabela top 10.
//
// Reusa GET /classificador/lotes/{id}/dashboard-data (que reusa
// build_report_data — mesmo agregador do XLSX/PDF).

import { useEffect, useState } from "react";
import {
  Bar, BarChart, CartesianGrid, Cell,
  Legend, Pie, PieChart, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from "recharts";
import { Loader2, RefreshCw, Sparkles, Pencil, Check, X, Wand2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/ui/use-toast";
import {
  ClassificadorDashboardData,
  fetchClassificadorDashboardData,
  gerarAnaliseEstrategica,
  updateAnaliseEstrategica,
} from "@/services/api";


interface Props {
  loteId: number | null;
  active: boolean;
}


// Paleta MDR — azul escuro + variações + neutros
const PALETTE = [
  "#1A365D", "#2C5282", "#2B6CB0", "#3182CE", "#4299E1",
  "#63B3ED", "#90CDF4", "#BEE3F8", "#A0AEC0", "#718096",
];

const COR_PRIMARY = "#1A365D";
const COR_ACCENT = "#2C5282";


// ─── Formatadores ────────────────────────────────────────────────────

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


// ─── KPI Card ────────────────────────────────────────────────────────

function KpiCard({
  label, value, sub, accent = COR_PRIMARY,
}: { label: string; value: string; sub?: string; accent?: string }) {
  return (
    <div className="rounded-md border bg-card p-3">
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="text-xl font-semibold mt-1" style={{ color: accent }}>{value}</div>
      {sub && <div className="text-[11px] text-muted-foreground mt-0.5">{sub}</div>}
    </div>
  );
}


// ─── Tooltip customizado pros graficos ───────────────────────────────

function ChartTooltip({ active, payload, label, valueFormatter }: any) {
  if (!active || !payload || !payload.length) return null;
  return (
    <div className="rounded-md border bg-card shadow-sm px-2 py-1.5 text-xs">
      {label && <div className="font-medium mb-0.5">{label}</div>}
      {payload.map((p: any, i: number) => (
        <div key={i} className="flex items-center gap-2">
          <span className="h-2 w-2 inline-block" style={{ background: p.color || p.fill }} />
          <span className="text-muted-foreground">{p.name}:</span>
          <span className="font-mono">
            {valueFormatter ? valueFormatter(p.value) : p.value}
          </span>
        </div>
      ))}
    </div>
  );
}


// ─── Componente principal ────────────────────────────────────────────

export default function LoteVisaoTab({ loteId, active }: Props) {
  const { toast } = useToast();
  const [data, setData] = useState<ClassificadorDashboardData | null>(null);
  const [loading, setLoading] = useState(false);

  // Analise estrategica — gerar/editar inline
  const [gerandoAnalise, setGerandoAnalise] = useState(false);
  const [editandoAnalise, setEditandoAnalise] = useState(false);
  const [analiseDraft, setAnaliseDraft] = useState("");
  const [salvandoAnalise, setSalvandoAnalise] = useState(false);

  const load = async () => {
    if (!loteId) return;
    setLoading(true);
    try {
      const d = await fetchClassificadorDashboardData(loteId);
      setData(d);
    } catch (err) {
      toast({
        title: "Falha ao carregar dashboard",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setLoading(false);
    }
  };

  const handleGerarAnalise = async () => {
    if (!loteId) return;
    if (data?.lote.analise_estrategica_carteira) {
      if (!confirm(
        "Ja existe analise estrategica neste lote. Regerar vai SOBRESCREVER o texto atual (~R$ 0,30 por geração via Sonnet). Continuar?"
      )) return;
    }
    setGerandoAnalise(true);
    try {
      const r = await gerarAnaliseEstrategica(loteId);
      toast({
        title: "Análise gerada",
        description: `${r.tamanho_chars} caracteres. Reload do dashboard...`,
      });
      await load();
    } catch (err) {
      toast({
        title: "Falha ao gerar análise",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setGerandoAnalise(false);
    }
  };

  const handleStartEditAnalise = () => {
    setAnaliseDraft(data?.lote.analise_estrategica_carteira || "");
    setEditandoAnalise(true);
  };

  const handleSaveAnalise = async () => {
    if (!loteId) return;
    setSalvandoAnalise(true);
    try {
      await updateAnaliseEstrategica(loteId, analiseDraft);
      toast({ title: "Análise salva" });
      setEditandoAnalise(false);
      await load();
    } catch (err) {
      toast({
        title: "Falha ao salvar",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setSalvandoAnalise(false);
    }
  };

  const handleCancelEditAnalise = () => {
    setEditandoAnalise(false);
    setAnaliseDraft("");
  };

  useEffect(() => {
    if (active && loteId) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, loteId]);

  if (loading && !data) {
    return (
      <div className="py-12 text-center text-sm text-muted-foreground">
        <Loader2 className="inline h-4 w-4 animate-spin mr-2" />
        Carregando dashboard...
      </div>
    );
  }

  if (!data) {
    return (
      <div className="py-12 text-center text-sm text-muted-foreground">
        Sem dados — talvez o lote ainda não tenha sido classificado.
      </div>
    );
  }

  const kpis = data.kpis;

  // Pizza categoria: top 7 + "Outros"
  const cats = data.por_categoria.slice();
  const cats_top = cats.slice(0, 7);
  const cats_rest_qtd = cats.slice(7).reduce((s, c) => s + (c.qtd || 0), 0);
  const pieData = cats_top.map(c => ({ name: c.label, value: c.qtd || 0 }));
  if (cats_rest_qtd > 0) {
    pieData.push({ name: `Outros (${cats.length - 7})`, value: cats_rest_qtd });
  }

  // Barras patrocinio
  const patrocinioData = data.por_patrocinio.map(p => ({
    name: p.label,
    qtd: p.qtd || 0,
    valor: p.valor_estimado || 0,
    pcond: p.pcond || 0,
  }));

  // Barras UF (top 10)
  const ufData = data.por_uf.slice(0, 10).map(u => ({
    name: u.label,
    qtd: u.qtd || 0,
    valor: u.valor_estimado || 0,
  }));

  // Barras pedidos por tipo (top 8)
  const pedidosData = data.pedidos_por_tipo.slice(0, 8).map(p => ({
    name: p.tipo_pedido,
    qtd: p.qtd,
    valor_estimado: p.valor_estimado || 0,
  }));

  return (
    <div className="space-y-4">
      {/* ─── Header com botão refresh ─── */}
      <div className="flex items-center justify-between">
        <div className="text-xs text-muted-foreground">
          Atualizado em {new Date(data.generated_at).toLocaleString("pt-BR")}
          {" · "}{kpis.total_processos} processos no lote
        </div>
        <Button variant="ghost" size="sm" onClick={load} disabled={loading}>
          {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
        </Button>
      </div>

      {/* ─── 4 KPI cards ─── */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <KpiCard
          label="Processos"
          value={fmtInt(kpis.total_processos)}
          sub={`${fmtInt(kpis.total_classificados)} classificados · ${fmtInt(kpis.total_com_erro)} erro`}
        />
        <KpiCard
          label="Valor estimado total"
          value={fmtCompactBRL(kpis.valor_total_estimado)}
          sub={`Causa: ${fmtCompactBRL(kpis.valor_total_causa)}`}
          accent={COR_ACCENT}
        />
        <KpiCard
          label="PCOND total (CPC 25)"
          value={fmtCompactBRL(kpis.pcond_total)}
          sub="Aprovisionamento"
          accent="#9F7AEA"
        />
        <KpiCard
          label="Prob. êxito média"
          value={fmtPct(kpis.prob_exito_medio)}
          sub="Do MDR/Master"
          accent="#38A169"
        />
      </div>

      {/* ─── Análise estratégica da carteira ─── */}
      <div className="rounded-md border bg-muted/30 p-3">
        <div className="flex items-start justify-between gap-2 mb-2">
          <div className="flex items-center gap-1.5">
            <Sparkles className="h-4 w-4 text-primary" />
            <div className="text-xs font-medium">Análise estratégica da carteira</div>
          </div>
          {!editandoAnalise && (
            <div className="flex items-center gap-1">
              <Button
                variant="ghost"
                size="sm"
                className="h-6 px-2 text-[11px]"
                onClick={handleGerarAnalise}
                disabled={gerandoAnalise}
                title={
                  data.lote.analise_estrategica_carteira
                    ? "Regerar análise via Sonnet (sobrescreve)"
                    : "Gerar análise via Sonnet (~10-30s)"
                }
              >
                {gerandoAnalise ? (
                  <Loader2 className="h-3 w-3 animate-spin mr-1" />
                ) : (
                  <Wand2 className="h-3 w-3 mr-1" />
                )}
                {data.lote.analise_estrategica_carteira ? "Regerar" : "Gerar análise IA"}
              </Button>
              {data.lote.analise_estrategica_carteira && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-6 px-2 text-[11px]"
                  onClick={handleStartEditAnalise}
                  title="Editar manualmente"
                >
                  <Pencil className="h-3 w-3 mr-1" />
                  Editar
                </Button>
              )}
            </div>
          )}
        </div>
        {editandoAnalise ? (
          <div className="space-y-2">
            <Textarea
              value={analiseDraft}
              onChange={e => setAnaliseDraft(e.target.value)}
              rows={12}
              className="text-xs font-mono leading-relaxed"
              placeholder="Cole ou digite a análise estratégica..."
            />
            <div className="flex items-center justify-between">
              <div className="text-[10px] text-muted-foreground">
                {analiseDraft.length} caracteres · markdown light suportado (**negrito**, bullets `-`)
              </div>
              <div className="flex items-center gap-1">
                <Button
                  variant="outline"
                  size="sm"
                  className="h-7 px-2 text-[11px]"
                  onClick={handleCancelEditAnalise}
                  disabled={salvandoAnalise}
                >
                  <X className="h-3 w-3 mr-1" />
                  Cancelar
                </Button>
                <Button
                  size="sm"
                  className="h-7 px-2 text-[11px]"
                  onClick={handleSaveAnalise}
                  disabled={salvandoAnalise}
                >
                  {salvandoAnalise ? (
                    <Loader2 className="h-3 w-3 animate-spin mr-1" />
                  ) : (
                    <Check className="h-3 w-3 mr-1" />
                  )}
                  Salvar
                </Button>
              </div>
            </div>
          </div>
        ) : data.lote.analise_estrategica_carteira ? (
          <div className="text-xs leading-relaxed text-foreground whitespace-pre-wrap">
            {data.lote.analise_estrategica_carteira}
          </div>
        ) : (
          <div className="text-xs italic text-muted-foreground">
            Nenhuma análise estratégica gerada ainda. Clique em "Gerar análise IA" pra criar.
          </div>
        )}
      </div>

      {/* ─── Grid de gráficos ─── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">

        {/* Pizza categoria */}
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

        {/* Barras patrocinio */}
        <div className="rounded-md border p-3">
          <div className="text-xs font-medium mb-2">Por patrocínio (MDR/Master)</div>
          {patrocinioData.length === 0 ? (
            <div className="h-64 flex items-center justify-center text-muted-foreground text-xs">Sem dados</div>
          ) : (
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={patrocinioData} layout="vertical" margin={{ left: 20, right: 10 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis type="number" tick={{ fontSize: 10 }} />
                <YAxis dataKey="name" type="category" tick={{ fontSize: 10 }} width={130} />
                <Tooltip content={<ChartTooltip valueFormatter={(v: number) => fmtInt(v)} />} />
                <Bar dataKey="qtd" fill={COR_ACCENT} name="Quantidade" />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* Barras UF */}
        <div className="rounded-md border p-3">
          <div className="text-xs font-medium mb-2">Distribuição geográfica (UF / Tribunal)</div>
          {ufData.length === 0 ? (
            <div className="h-64 flex items-center justify-center text-muted-foreground text-xs">Sem dados</div>
          ) : (
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={ufData} layout="vertical" margin={{ left: 20, right: 10 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis type="number" tick={{ fontSize: 10 }} />
                <YAxis dataKey="name" type="category" tick={{ fontSize: 10 }} width={80} />
                <Tooltip content={<ChartTooltip valueFormatter={(v: number) => fmtInt(v)} />} />
                <Bar dataKey="qtd" fill={COR_PRIMARY} name="Quantidade" />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* Barras pedidos */}
        <div className="rounded-md border p-3">
          <div className="text-xs font-medium mb-2">Pedidos por tipo (top 8)</div>
          {pedidosData.length === 0 ? (
            <div className="h-64 flex items-center justify-center text-muted-foreground text-xs">Sem pedidos extraídos</div>
          ) : (
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={pedidosData} layout="vertical" margin={{ left: 20, right: 10 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis type="number" tick={{ fontSize: 10 }} />
                <YAxis dataKey="name" type="category" tick={{ fontSize: 10 }} width={140} />
                <Tooltip content={<ChartTooltip valueFormatter={(v: number) => fmtInt(v)} />} />
                <Bar dataKey="qtd" fill="#38A169" name="Quantidade" />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      {/* ─── Top 10 processos por valor ─── */}
      <div className="rounded-md border p-3">
        <div className="text-xs font-medium mb-2">Top 10 processos por valor estimado</div>
        {data.top_n_valor.length === 0 ? (
          <div className="py-6 text-center text-xs text-muted-foreground">Sem dados</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b text-left text-muted-foreground">
                  <th className="py-1 pr-2">#</th>
                  <th className="py-1 pr-2">CNJ</th>
                  <th className="py-1 pr-2">Tribunal</th>
                  <th className="py-1 pr-2">Categoria</th>
                  <th className="py-1 pr-2 text-right">Valor estimado</th>
                  <th className="py-1 pr-2 text-right">PCOND</th>
                  <th className="py-1 pr-2 text-right">P. êxito</th>
                </tr>
              </thead>
              <tbody>
                {data.top_n_valor.slice(0, 10).map(p => (
                  <tr key={p.id} className="border-b hover:bg-muted/30">
                    <td className="py-1 pr-2 font-mono">#{p.id}</td>
                    <td className="py-1 pr-2 font-mono">{p.cnj_number || "—"}</td>
                    <td className="py-1 pr-2">{p.tribunal || "—"}</td>
                    <td className="py-1 pr-2">{p.categoria || "—"}</td>
                    <td className="py-1 pr-2 text-right tabular-nums">{fmtBRL(p.valor_estimado)}</td>
                    <td className="py-1 pr-2 text-right tabular-nums">{fmtBRL(p.pcond_sugerido)}</td>
                    <td className="py-1 pr-2 text-right tabular-nums">{fmtPct(p.prob_exito)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ─── Resumo sentencas + transito ─── */}
      <div className="grid grid-cols-2 gap-3">
        <div className="rounded-md border p-3">
          <div className="text-xs font-medium mb-2">Sentenças no lote</div>
          {Object.keys(data.sentencas_resumo).length === 0 ? (
            <div className="text-xs text-muted-foreground">Sem dados</div>
          ) : (
            <ul className="text-xs space-y-1">
              {Object.entries(data.sentencas_resumo).map(([tipo, count]) => (
                <li key={tipo} className="flex justify-between">
                  <span>{tipo}</span>
                  <Badge variant="outline">{count}</Badge>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="rounded-md border p-3">
          <div className="text-xs font-medium mb-2">Trânsito em julgado</div>
          <ul className="text-xs space-y-1">
            <li className="flex justify-between">
              <span>Transitados</span>
              <Badge variant="default">{data.transito_julgado_resumo.transitados}</Badge>
            </li>
            <li className="flex justify-between">
              <span>Não transitados</span>
              <Badge variant="outline">{data.transito_julgado_resumo.nao_transitados}</Badge>
            </li>
          </ul>
        </div>
      </div>
    </div>
  );
}
