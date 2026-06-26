// frontend/src/components/performance/RaioXPessoa.tsx
//
// "Raio-X" de uma pessoa — modal grande com passado E futuro:
//   PASSADO — desempenho do período (produção, ritmo/ócio, mix de concluídas).
//   FUTURO  — carga aberta agora (pendentes, atrasadas, por tipo, próximos prazos).
//
// Cada métrica com (?) explicativo. Abre por clique na tabela ou pela busca
// "Análise individual".

import { useEffect, useState } from "react";
import {
  AlertTriangle,
  CalendarClock,
  CheckCircle2,
  Clock,
  Download,
  FileText,
  Gauge,
  History,
  Hourglass,
  TimerReset,
} from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { InfoHint, MetricLabel } from "@/components/performance/InfoHint";
import { type Categoria, type PessoaDetalhe, criarRelatorio, downloadExport, getPessoa } from "@/services/performance";
import { useToast } from "@/hooks/use-toast";

const CAT_STYLE: Record<Categoria, { label: string; cls: string }> = {
  operacional: { label: "Operacional", cls: "bg-sky-100 text-sky-700" },
  profundo: { label: "Profundo", cls: "bg-emerald-100 text-emerald-700" },
  ruido: { label: "Ruído", cls: "bg-slate-100 text-slate-600" },
};

function cargoBadge(cargo: string | null): string {
  const c = (cargo || "").toLowerCase();
  if (c.includes("advog")) return "bg-violet-100 text-violet-700";
  if (c.includes("estag")) return "bg-sky-100 text-sky-700";
  if (c.includes("assist")) return "bg-amber-100 text-amber-700";
  return "bg-slate-100 text-slate-700";
}

const fmtCad = (s: number | null): string =>
  s == null ? "—" : s < 60 ? `${s}s` : s % 60 ? `${Math.floor(s / 60)}m ${s % 60}s` : `${Math.floor(s / 60)}m`;
const pct = (v: number | null): string => (v == null ? "—" : `${v}%`);
const diasFmt = (v: number | null): string => (v == null ? "—" : `${v}d`);
const pad2 = (n: number): string => String(n).padStart(2, "0");
const fmtHora = (h: number | null): string =>
  h == null ? "—" : `${pad2(Math.floor(h))}:${pad2(Math.round((h % 1) * 60))}`;
const fmtJanela = (a: number | null, b: number | null): string | null => {
  if (a == null || b == null || b <= a) return null;
  const m = Math.round((b - a) * 60);
  return `${Math.floor(m / 60)}h${pad2(m % 60)}`;
};

function prazoLabel(dias: number | null): { text: string; cls: string } {
  if (dias == null) return { text: "sem prazo", cls: "text-muted-foreground" };
  if (dias < 0) return { text: `atrasada há ${Math.abs(dias)}d`, cls: "text-rose-700 font-medium" };
  if (dias === 0) return { text: "vence hoje", cls: "text-red-600 font-medium" };
  if (dias <= 7) return { text: `vence em ${dias}d`, cls: "text-amber-700" };
  return { text: `vence em ${dias}d`, cls: "text-emerald-700" };
}

function Tile({ label, hint, value, tone }: { label: string; hint: string; value: string; tone?: string }) {
  return (
    <div className="rounded-lg border bg-muted/30 p-3">
      <div className="text-[11px] text-muted-foreground">
        <MetricLabel label={label} hint={hint} />
      </div>
      <div className={`mt-1 text-xl font-bold leading-none ${tone || ""}`}>{value}</div>
    </div>
  );
}

const H = {
  concluido: "Tarefas cumpridas no período, pela data de conclusão efetiva.",
  throughput: "Média de tarefas concluídas por dia ativo (dias em que concluiu ao menos uma).",
  no_prazo: "% das concluídas dentro do prazo previsto. '—' quando não há prazo definido.",
  cycle: "Mediana do tempo entre cadastro e conclusão — quanto a tarefa fica viva até resolver.",
  dias_ativos: "Dias distintos em que a pessoa concluiu ao menos uma tarefa no período.",
  cadencia: "Tempo mediano entre uma conclusão e a próxima no mesmo dia (>30 min = pausa). Custo de tempo por tarefa. Confiável sobretudo no operacional.",
  ocio: "% do tempo da jornada (1ª→última conclusão) gasto em pausas, não em concluir tarefas.",
  oper_share: "Quanto das conclusões é operacional. Quanto maior, mais confiável a leitura de cadência/ócio.",
  jornada: "Horário mediano da 1ª e da última conclusão do dia ao longo do período. É um proxy de chegada/saída pelo registro de tarefas no L1 — não é ponto eletrônico.",
  tempo_tarefa: "Tempo de decisão: mediana do intervalo entre concluir a tarefa anterior e concluir uma deste tipo (pausas >30 min ignoradas). É quanto a pessoa leva, na prática, pra resolver uma tarefa desse tipo.",
  pendente: "Tarefas em aberto (não concluídas) sob responsabilidade da pessoa — a carga futura.",
  atrasado: "Pendentes cujo prazo já passou. É o que está vencido e precisa de ação.",
  sem_prazo: "Pendentes sem data de prazo definida.",
};

function PassadoSection({ d }: { d: PessoaDetalhe }) {
  const k = d.passado.kpis;
  const r = d.passado.ritmo;
  return (
    <section>
      <h3 className="mb-2 flex items-center gap-1.5 text-sm font-semibold">
        <History className="h-4 w-4 text-[hsl(var(--dunatech-blue))]" /> Passado — desempenho
        <span className="font-normal text-muted-foreground">(últimos {d.periodo_dias} dias)</span>
      </h3>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
        <Tile label="Concluídas" hint={H.concluido} value={String(k.concluido)} />
        <Tile label="Ritmo/dia" hint={H.throughput} value={String(k.throughput_dia)} />
        <Tile label="No prazo" hint={H.no_prazo} value={pct(k.no_prazo_pct)} />
        <Tile label="Cycle time" hint={H.cycle} value={diasFmt(k.cycle_dias)} />
        <Tile label="Dias ativos" hint={H.dias_ativos} value={String(k.dias_ativos)} />
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg border border-sky-200 bg-sky-50/60 px-3 py-2 text-sm">
        <span className="flex items-center gap-1.5 font-semibold text-[hsl(var(--dunatech-blue))]">
          <Clock className="h-4 w-4" /> Jornada típica
        </span>
        <span>Chega <b className="tabular-nums">~{fmtHora(r.inicio_h)}</b></span>
        <span>Sai <b className="tabular-nums">~{fmtHora(r.fim_h)}</b></span>
        {fmtJanela(r.inicio_h, r.fim_h) && (
          <span className="text-muted-foreground">janela de {fmtJanela(r.inicio_h, r.fim_h)}</span>
        )}
        <InfoHint text={H.jornada} />
      </div>

      <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Tile label="Cadência" hint={H.cadencia} value={fmtCad(r.cadencia_seg)} />
        <Tile label="Ócio" hint={H.ocio} value={pct(r.ocio_pct)} />
        <Tile label="Fatia operacional" hint={H.oper_share} value={pct(r.oper_share)} />
        <Tile label="Dias com ritmo" hint="Dias usados no cálculo de cadência/ócio." value={String(r.dias)} />
      </div>
      {r.oper_share != null && r.oper_share < 50 && (
        <p className="mt-2 flex items-start gap-1.5 rounded-md bg-amber-50 p-2 text-[11px] text-amber-800">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          Trabalho majoritariamente profundo — leia cadência/ócio com cautela; priorize volume, cycle time e prazo.
        </p>
      )}

      <h4 className="mb-1.5 mt-4 text-xs font-semibold text-muted-foreground">
        Composição das concluídas ({d.passado.mix.length} tipos)
      </h4>
      <div className="overflow-x-auto rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Tipo de tarefa</TableHead>
              <TableHead>Natureza</TableHead>
              <TableHead className="text-right">Volume</TableHead>
              <TableHead className="text-right">
                <span className="inline-flex items-center gap-1">Tempo/tarefa <InfoHint text={H.tempo_tarefa} /></span>
              </TableHead>
              <TableHead className="text-right">Cycle</TableHead>
              <TableHead className="text-right">No prazo</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {d.passado.mix.map((m) => (
              <TableRow key={m.subtipo}>
                <TableCell className="max-w-[280px] truncate text-sm" title={m.subtipo}>{m.subtipo}</TableCell>
                <TableCell>
                  <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${CAT_STYLE[m.categoria].cls}`}>
                    {CAT_STYLE[m.categoria].label}
                  </span>
                </TableCell>
                <TableCell className="text-right tabular-nums">{m.volume}</TableCell>
                <TableCell className="text-right tabular-nums font-medium">{fmtCad(m.tempo_tarefa_seg)}</TableCell>
                <TableCell className="text-right tabular-nums">{diasFmt(m.cycle_dias)}</TableCell>
                <TableCell className="text-right tabular-nums">{pct(m.no_prazo_pct)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </section>
  );
}

function FuturoSection({ d, onExport }: { d: PessoaDetalhe; onExport: (escopo: "atrasado" | "pendente") => void }) {
  const f = d.futuro;
  return (
    <section>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold">
          <Hourglass className="h-4 w-4 text-amber-600" /> Futuro — carga aberta agora
        </h3>
        <div className="flex items-center gap-1.5">
          <Button size="sm" variant="outline" className="h-7 gap-1 text-xs" onClick={() => onExport("atrasado")}>
            <Download className="h-3.5 w-3.5" /> Atrasadas
          </Button>
          <Button size="sm" variant="outline" className="h-7 gap-1 text-xs" onClick={() => onExport("pendente")}>
            <Download className="h-3.5 w-3.5" /> Pendentes
          </Button>
        </div>
      </div>
      <div className="grid grid-cols-3 gap-2">
        <Tile label="Pendentes" hint={H.pendente} value={String(f.pendente)} tone="text-amber-700" />
        <Tile label="Atrasadas" hint={H.atrasado} value={String(f.atrasado)} tone={f.atrasado > 0 ? "text-rose-700" : ""} />
        <Tile label="Sem prazo" hint={H.sem_prazo} value={String(f.sem_prazo)} />
      </div>

      {f.por_tipo.length > 0 && (
        <>
          <h4 className="mb-1.5 mt-4 text-xs font-semibold text-muted-foreground">Pendentes por tipo</h4>
          <div className="overflow-x-auto rounded-lg border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Tipo de tarefa</TableHead>
                  <TableHead>Natureza</TableHead>
                  <TableHead className="text-right">Pendentes</TableHead>
                  <TableHead className="text-right">Atrasadas</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {f.por_tipo.map((t) => (
                  <TableRow key={t.subtipo}>
                    <TableCell className="max-w-[280px] truncate text-sm" title={t.subtipo}>{t.subtipo}</TableCell>
                    <TableCell>
                      <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${CAT_STYLE[t.categoria].cls}`}>
                        {CAT_STYLE[t.categoria].label}
                      </span>
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{t.total}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {t.atrasado > 0 ? <span className="font-medium text-rose-700">{t.atrasado}</span> : t.atrasado}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </>
      )}

      <h4 className="mb-1.5 mt-4 flex items-center gap-1 text-xs font-semibold text-muted-foreground">
        <TimerReset className="h-3.5 w-3.5" /> Próximos prazos
        <InfoHint text="As pendentes ordenadas pelo prazo previsto — primeiro as mais vencidas, depois as que vencem em breve." />
      </h4>
      {f.urgentes.length === 0 ? (
        <p className="rounded-lg border bg-muted/20 py-4 text-center text-xs text-muted-foreground">
          Nenhuma pendente com prazo definido.
        </p>
      ) : (
        <div className="space-y-1">
          {f.urgentes.map((u, i) => {
            const lbl = prazoLabel(u.dias);
            return (
              <div key={i} className="flex items-center justify-between gap-2 rounded-md border px-3 py-1.5 text-sm">
                <span className="min-w-0 truncate" title={u.subtipo}>{u.subtipo}</span>
                <div className="flex shrink-0 items-center gap-2 text-xs">
                  <span className="text-muted-foreground">{u.prazo}</span>
                  <span className={lbl.cls}>{lbl.text}</span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

export default function RaioXPessoa({
  pessoaId,
  team,
  days,
  onClose,
  onRelatorioCriado,
}: {
  pessoaId: number | null;
  team: string;
  days: number;
  onClose: () => void;
  onRelatorioCriado?: () => void;
}) {
  const { toast } = useToast();
  const [data, setData] = useState<PessoaDetalhe | null>(null);
  const [loading, setLoading] = useState(false);
  const [gerando, setGerando] = useState(false);

  useEffect(() => {
    if (pessoaId == null) {
      setData(null);
      return;
    }
    setLoading(true);
    getPessoa(pessoaId, team, days)
      .then(setData)
      .catch((e) => toast({ title: "Erro ao carregar a pessoa", description: String((e as Error).message), variant: "destructive" }))
      .finally(() => setLoading(false));
  }, [pessoaId, team, days, toast]);

  const handleExport = (escopo: "atrasado" | "pendente") => {
    if (pessoaId == null) return;
    downloadExport({ escopo, days, team, pessoa_id: pessoaId }).catch((e) =>
      toast({ title: "Erro ao exportar", description: String((e as Error).message), variant: "destructive" }),
    );
  };

  const handleRelatorio = async () => {
    if (pessoaId == null) return;
    setGerando(true);
    try {
      await criarRelatorio("pessoa", team, days, pessoaId);
      onRelatorioCriado?.();
      toast({
        title: "Relatório individual em geração",
        description: "Roda no servidor — pode fechar. Aparece na seção 'Relatórios' da página quando ficar pronto.",
      });
    } catch (e) {
      toast({ title: "Erro ao gerar o relatório", description: String((e as Error).message), variant: "destructive" });
    } finally {
      setGerando(false);
    }
  };

  return (
    <Dialog open={pessoaId != null} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[90vh] max-w-4xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex flex-wrap items-center gap-2">
            <Gauge className="h-5 w-5 text-[hsl(var(--dunatech-blue))]" />
            Raio-X — {data?.pessoa.nome ?? (loading ? "Carregando…" : "Pessoa")}
            {data?.pessoa.cargo && (
              <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${cargoBadge(data.pessoa.cargo)}`}>
                {data.pessoa.cargo}
              </span>
            )}
            {data?.pessoa.squad && (
              <span className="text-xs font-normal text-muted-foreground">Squad {data.pessoa.squad}</span>
            )}
          </DialogTitle>
        </DialogHeader>

        {data && (
          <div className="flex justify-end">
            <Button variant="outline" size="sm" className="gap-2" onClick={handleRelatorio} disabled={gerando}>
              <FileText className="h-4 w-4" /> {gerando ? "Gerando…" : "Relatório (PDF)"}
            </Button>
          </div>
        )}

        {!data ? (
          <p className="py-12 text-center text-sm text-muted-foreground">{loading ? "Carregando…" : "Sem dados."}</p>
        ) : (
          <div className="space-y-6">
            <PassadoSection d={data} />
            <div className="border-t" />
            <FuturoSection d={data} onExport={handleExport} />
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
