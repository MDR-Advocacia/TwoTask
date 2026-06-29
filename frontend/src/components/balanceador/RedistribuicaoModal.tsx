// Modal amplo de redistribuição: 1 coluna por colaborador escolhido, cards de
// subtipo arrastáveis entre colunas (com quantidade), (i) → detalhe individual,
// e painel de "mudanças pendentes". Rebalanceia visualmente ao vivo.
// MOCK: a aplicação é simulada (não escreve no L1 ainda).

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowRight, Check, Info, Loader2, RotateCcw, Split, Trash2, Users } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useToast } from "@/hooks/use-toast";
import { teamLabel } from "@/lib/teams";
import {
  type MatrizItem,
  type MovePendente,
  type TarefaDetalhe,
  getLivePessoa,
  registrarLog,
} from "@/services/balanceador";
import DetalheSubtipoModal from "@/components/balanceador/DetalheSubtipoModal";
import DistribuicaoFilaDialog from "@/components/balanceador/DistribuicaoFilaDialog";
import ExecProgressOverlay, { type ExecState } from "@/components/balanceador/ExecProgressOverlay";

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

type Pessoa = { id: number; nome: string };
type Dragged = { fromId: number; subtipo: string; total: number } | null;
type DropCtx = { fromId: number; fromNome: string; toId: number; toNome: string; subtipo: string; max: number } | null;

const PERIODO_LABEL: Record<number, string> = {
  0: "todas as pendentes",
  7: "próximos 7 dias",
  15: "próximos 15 dias",
  30: "próximos 30 dias",
  90: "próximos 90 dias",
};

let _moveSeq = 0;

export default function RedistribuicaoModal({
  team,
  pessoas,
  dias,
  incluirAtrasadas = true,
  onClose,
  onAplicado,
}: {
  team: string;
  pessoas: Pessoa[];
  dias: number;
  incluirAtrasadas?: boolean;
  onClose: () => void;
  onAplicado?: () => void;
}) {
  const { toast } = useToast();
  const [matriz, setMatriz] = useState<MatrizItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [tarefas, setTarefas] = useState<Record<number, TarefaDetalhe[]>>({});
  const [totais, setTotais] = useState<Record<number, { carregadas: number; total: number | null; capado: boolean }>>({});
  const [progresso, setProgresso] = useState<{ done: number; total: number; nome: string } | null>(null);
  const [naoResolvidos, setNaoResolvidos] = useState<string[]>([]);
  const [moves, setMoves] = useState<MovePendente[]>([]);
  const [dropCtx, setDropCtx] = useState<DropCtx>(null);
  const [qtd, setQtd] = useState<number>(0);
  const [detalhe, setDetalhe] = useState<{ fromPessoa: Pessoa; subtipo: string } | null>(null);
  const [filaCtx, setFilaCtx] = useState<{ fromPessoa: Pessoa; subtipo: string; max: number } | null>(null);
  const [exec, setExec] = useState<ExecState | null>(null);
  const dragged = useRef<Dragged>(null);

  const nomeById = useMemo(() => Object.fromEntries(pessoas.map((p) => [p.id, p.nome])), [pessoas]);

  const load = useCallback(async () => {
    // Puxa AO VIVO do L1, uma pessoa por vez (com progresso). Monta a matriz e
    // guarda as tarefas (com descrição) pro detalhe — sem fetch extra depois.
    setLoading(true);
    setProgresso({ done: 0, total: pessoas.length, nome: "" });
    const mat: MatrizItem[] = [];
    const tar: Record<number, TarefaDetalhe[]> = {};
    const tot: Record<number, { carregadas: number; total: number | null; capado: boolean }> = {};
    const naoRes: string[] = [];
    for (let i = 0; i < pessoas.length; i++) {
      const p = pessoas[i];
      setProgresso({ done: i, total: pessoas.length, nome: p.nome });
      try {
        const lp = await getLivePessoa(team, p.id, dias, incluirAtrasadas);
        if (!lp.resolvido) naoRes.push(p.nome);
        for (const s of lp.subtipos) {
          mat.push({ pessoa_id: p.id, subtipo: s.subtipo, total: s.total, atrasado: s.atrasado, fatal_hoje: s.fatal_hoje });
        }
        tar[p.id] = lp.tarefas;
        tot[p.id] = { carregadas: lp.carregadas ?? lp.tarefas.length, total: lp.total_real ?? null, capado: lp.capado ?? false };
      } catch {
        naoRes.push(p.nome);
      }
    }
    setMatriz(mat);
    setTarefas(tar);
    setTotais(tot);
    setNaoResolvidos(naoRes);
    setProgresso(null);
    setLoading(false);
  }, [team, pessoas, dias, incluirAtrasadas]);

  useEffect(() => {
    load();
  }, [load]);

  // Salvaguarda do bug conhecido do Radix: ao fechar um Dialog aninhado (detalhe /
  // quantidade) ou desmontar este modal enquanto `open`, o body pode ficar com
  // pointer-events:none e travar os cliques. Restaura sempre que não há modal
  // aninhado aberto, e também no unmount.
  useEffect(() => {
    if (!detalhe && !dropCtx && !filaCtx) document.body.style.pointerEvents = "";
  }, [detalhe, dropCtx, filaCtx]);
  useEffect(() => () => {
    document.body.style.pointerEvents = "";
  }, []);

  // aplica um move no estado local (rebalanceia as colunas ao vivo)
  const applyMove = (fromId: number, toId: number, subtipo: string, q: number) => {
    setMatriz((prev) => {
      const next = prev.map((m) => ({ ...m }));
      const src = next.find((m) => m.pessoa_id === fromId && m.subtipo === subtipo);
      if (src) {
        src.total -= q;
        src.atrasado = Math.min(src.atrasado, src.total);
        src.fatal_hoje = Math.min(src.fatal_hoje, src.total);
      }
      let dst = next.find((m) => m.pessoa_id === toId && m.subtipo === subtipo);
      if (!dst) {
        dst = { pessoa_id: toId, subtipo, total: 0, atrasado: 0, fatal_hoje: 0 };
        next.push(dst);
      }
      dst.total += q;
      return next.filter((m) => m.total > 0);
    });
  };

  const registrar = (m: Omit<MovePendente, "id">) => {
    setMoves((prev) => [{ ...m, id: `mv${++_moveSeq}` }, ...prev]);
    applyMove(m.fromId, m.toId, m.subtipo, m.qtd);
  };

  const onDrop = (toId: number) => {
    const d = dragged.current;
    dragged.current = null;
    if (!d || d.fromId === toId || d.total <= 0) return;
    setQtd(d.total);
    setDropCtx({ fromId: d.fromId, fromNome: nomeById[d.fromId], toId, toNome: nomeById[toId], subtipo: d.subtipo, max: d.total });
  };

  const confirmarDrop = () => {
    if (!dropCtx) return;
    const q = Math.max(1, Math.min(qtd || 0, dropCtx.max));
    registrar({
      fromId: dropCtx.fromId, fromNome: dropCtx.fromNome, toId: dropCtx.toId, toNome: dropCtx.toNome,
      subtipo: dropCtx.subtipo, qtd: q, individual: false,
    });
    setDropCtx(null);
  };

  const removerMove = (id: string) => {
    const mv = moves.find((m) => m.id === id);
    if (mv) applyMove(mv.toId, mv.fromId, mv.subtipo, mv.qtd); // desfaz
    setMoves((prev) => prev.filter((m) => m.id !== id));
  };

  const aplicar = async () => {
    if (!moves.length || exec) return;
    const lista = [...moves];
    setExec({ mode: "aplicar", total: lista.length, done: 0, label: "", finished: false });
    for (let i = 0; i < lista.length; i++) {
      const m = lista[i];
      setExec((e) => (e ? { ...e, done: i, label: `${m.qtd}× ${m.subtipo} · ${m.fromNome} → ${m.toNome}` } : e));
      await sleep(450); // mock: 1 passo = 1 reatribuição (API/Workflow) na versão real
    }
    setExec((e) => (e ? { ...e, done: lista.length, finished: true, label: "" } : e));
    registrarLog(team, lista)
      .then(() => onAplicado?.())
      .catch(() => undefined);
    toast({
      title: "Redistribuição aplicada (mock)",
      description: "Log gerado na aba Relatórios. Não escreve no L1 ainda — a versão real troca responsável + executante (mantém o solicitante).",
    });
  };

  const reverterTudo = async () => {
    if (!moves.length || exec) return;
    const lista = [...moves];
    setExec({ mode: "reverter", total: lista.length, done: 0, label: "", finished: false });
    for (let i = 0; i < lista.length; i++) {
      const m = lista[lista.length - 1 - i]; // ordem inversa
      applyMove(m.toId, m.fromId, m.subtipo, m.qtd); // desfaz o movimento
      setExec((e) => (e ? { ...e, done: i, label: `Revertendo ${m.qtd}× ${m.subtipo} · ${m.toNome} → ${m.fromNome}` } : e));
      await sleep(350);
    }
    setMoves([]);
    setExec((e) => (e ? { ...e, done: lista.length, finished: true, label: "" } : e));
  };

  return (
    <>
      <Dialog open onOpenChange={(o) => { if (!o && !exec) onClose(); }}>
        <DialogContent className="flex max-h-[92vh] w-[94vw] max-w-[1400px] flex-col overflow-hidden">
          <DialogHeader>
            <DialogTitle className="flex flex-wrap items-center gap-2">
              <Users className="h-5 w-5 text-[hsl(var(--dunatech-blue))]" />
              Redistribuição — {teamLabel(team)}
              <span className="text-sm font-normal text-muted-foreground">
                {pessoas.length} colaborador(es) · {PERIODO_LABEL[dias] ?? `${dias} dias`}
              </span>
            </DialogTitle>
          </DialogHeader>
          <p className="text-xs text-muted-foreground">
            Arraste um tipo de tarefa de uma pessoa para outra e informe a quantidade — ou clique no{" "}
            <Info className="inline h-3 w-3" /> pra escolher tarefa a tarefa. Troca <b>responsável + executante</b>,
            mantém o solicitante. <span className="text-amber-700">Leitura ao vivo do L1 · aplicação simulada.</span>
          </p>

          {naoResolvidos.length > 0 && (
            <p className="rounded-md bg-amber-50 px-3 py-1.5 text-[11px] text-amber-800">
              ⚠ Não consegui resolver no L1: {naoResolvidos.join(", ")} — o nome diverge do catálogo de usuários (sai das colunas).
            </p>
          )}

          {loading ? (
            <div className="py-16 text-center">
              <Loader2 className="mb-3 inline h-5 w-5 animate-spin text-[hsl(var(--dunatech-blue))]" />
              <p className="text-sm text-muted-foreground">
                Puxando do L1 ao vivo{progresso ? ` — ${progresso.done}/${progresso.total}` : ""}…
              </p>
              {progresso?.nome && <p className="mt-1 text-xs text-muted-foreground">{progresso.nome}</p>}
              {progresso && progresso.total > 0 && (
                <div className="mx-auto mt-3 h-2 w-64 overflow-hidden rounded-full bg-muted">
                  <div
                    className="h-full bg-[hsl(var(--dunatech-blue))] transition-all"
                    style={{ width: `${(progresso.done / progresso.total) * 100}%` }}
                  />
                </div>
              )}
            </div>
          ) : (
            <div className="flex min-h-0 flex-1 gap-3">
              {/* colunas por colaborador */}
              <div className="flex min-h-0 flex-1 gap-3 overflow-x-auto pb-2">
                {pessoas.map((p) => {
                  const cards = matriz
                    .filter((m) => m.pessoa_id === p.id)
                    .sort((a, b) => b.total - a.total);
                  const totalP = cards.reduce((s, c) => s + c.total, 0);
                  return (
                    <div
                      key={p.id}
                      onDragOver={(e) => e.preventDefault()}
                      onDrop={() => onDrop(p.id)}
                      className="flex w-64 shrink-0 flex-col rounded-lg border bg-muted/20"
                    >
                      <div className="sticky top-0 rounded-t-lg border-b bg-background/95 px-3 py-2">
                        <div className="truncate text-sm font-semibold" title={p.nome}>{p.nome}</div>
                        <div className="text-[11px] text-muted-foreground">
                          {totalP} tarefa(s) · {cards.length} tipos
                          {totais[p.id]?.capado && (
                            <span className="text-amber-700"> · mais urgentes (de {totais[p.id]!.total} c/ prazo)</span>
                          )}
                        </div>
                      </div>
                      <div className="flex-1 space-y-1.5 overflow-y-auto p-2">
                        {cards.length === 0 && (
                          <p className="py-6 text-center text-[11px] text-muted-foreground">Sem carga no período</p>
                        )}
                        {cards.map((c) => (
                          <div
                            key={c.subtipo}
                            draggable
                            onDragStart={() => (dragged.current = { fromId: p.id, subtipo: c.subtipo, total: c.total })}
                            className="group cursor-grab rounded-md border bg-background p-2 shadow-sm active:cursor-grabbing"
                          >
                            <div className="flex items-start justify-between gap-1">
                              <span className="text-xs font-medium leading-tight" title={c.subtipo}>
                                {c.subtipo}
                              </span>
                              <div className="flex shrink-0 items-center gap-1">
                                <button
                                  className="text-muted-foreground hover:text-[hsl(var(--dunatech-blue))]"
                                  title="Distribuir em fila (round-robin) entre vários"
                                  onClick={() => setFilaCtx({ fromPessoa: p, subtipo: c.subtipo, max: c.total })}
                                >
                                  <Split className="h-3.5 w-3.5" />
                                </button>
                                <button
                                  className="text-muted-foreground hover:text-[hsl(var(--dunatech-blue))]"
                                  title="Detalhar / escolher tarefas"
                                  onClick={() => setDetalhe({ fromPessoa: p, subtipo: c.subtipo })}
                                >
                                  <Info className="h-3.5 w-3.5" />
                                </button>
                              </div>
                            </div>
                            <div className="mt-1 flex items-center gap-1.5">
                              <span className="text-lg font-bold leading-none tabular-nums">{c.total}</span>
                              {c.atrasado > 0 && (
                                <span className="rounded-full bg-rose-100 px-1.5 py-0.5 text-[10px] font-medium text-rose-700">
                                  {c.atrasado} atras.
                                </span>
                              )}
                              {c.fatal_hoje > 0 && (
                                <span className="rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-800">
                                  {c.fatal_hoje} hoje
                                </span>
                              )}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* painel de mudanças pendentes */}
              <div className="flex w-72 shrink-0 flex-col rounded-lg border">
                <div className="border-b px-3 py-2 text-sm font-semibold">
                  Mudanças pendentes <span className="text-muted-foreground">({moves.length})</span>
                </div>
                <div className="flex-1 space-y-1.5 overflow-y-auto p-2">
                  {moves.length === 0 && (
                    <p className="py-8 text-center text-[11px] text-muted-foreground">
                      Arraste tipos entre as colunas pra montar a redistribuição.
                    </p>
                  )}
                  {moves.map((m) => (
                    <div key={m.id} className="rounded-md border bg-muted/20 p-2 text-[11px]">
                      <div className="flex items-center justify-between">
                        <span className="font-semibold tabular-nums">
                          {m.qtd}× {m.individual ? "(escolhidas)" : ""}
                        </span>
                        <button className="text-muted-foreground hover:text-rose-600" onClick={() => removerMove(m.id)}>
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                      <div className="truncate font-medium" title={m.subtipo}>{m.subtipo}</div>
                      <div className="flex items-center gap-1 text-muted-foreground">
                        <span className="truncate">{m.fromNome}</span>
                        <ArrowRight className="h-3 w-3 shrink-0" />
                        <span className="truncate">{m.toNome}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          <DialogFooter className="gap-2 border-t pt-3 sm:justify-between">
            <Button variant="outline" disabled={!!exec} onClick={onClose}>Fechar</Button>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                className="gap-1.5 text-amber-700 hover:text-amber-800"
                disabled={moves.length === 0 || !!exec}
                onClick={reverterTudo}
              >
                <RotateCcw className="h-4 w-4" /> Reverter tudo
              </Button>
              <Button className="gap-1.5" disabled={moves.length === 0 || !!exec} onClick={aplicar}>
                <Check className="h-4 w-4" /> Aplicar {moves.length > 0 ? `(${moves.length})` : ""}
              </Button>
            </div>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* dialog de quantidade no drop */}
      <Dialog open={dropCtx != null} onOpenChange={(o) => !o && setDropCtx(null)}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle className="text-base">Mover quantas?</DialogTitle>
          </DialogHeader>
          {dropCtx && (
            <div className="space-y-3">
              <p className="text-sm">
                <b>{dropCtx.subtipo}</b>
                <br />
                <span className="text-muted-foreground">{dropCtx.fromNome}</span> →{" "}
                <span className="font-medium">{dropCtx.toNome}</span>
              </p>
              <div className="flex items-center gap-2">
                <Input
                  type="number"
                  min={1}
                  max={dropCtx.max}
                  value={qtd}
                  onChange={(e) => setQtd(Number(e.target.value))}
                  className="w-28"
                  autoFocus
                  onKeyDown={(e) => e.key === "Enter" && confirmarDrop()}
                />
                <span className="text-xs text-muted-foreground">de {dropCtx.max} disponível(eis)</span>
              </div>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setDropCtx(null)}>Cancelar</Button>
            <Button onClick={confirmarDrop}>Mover</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* drill individual */}
      {detalhe && (
        <DetalheSubtipoModal
          team={team}
          dias={dias}
          fromPessoa={detalhe.fromPessoa}
          subtipo={detalhe.subtipo}
          alvos={pessoas}
          tarefasIniciais={(tarefas[detalhe.fromPessoa.id] || []).filter((t) => t.subtipo === detalhe.subtipo)}
          onClose={() => setDetalhe(null)}
          onTransfer={(taskIds, toId, toNome) =>
            registrar({
              fromId: detalhe.fromPessoa.id, fromNome: detalhe.fromPessoa.nome, toId, toNome,
              subtipo: detalhe.subtipo, qtd: taskIds.length, individual: true, taskIds,
            })
          }
        />
      )}

      {/* distribuição em fila (round-robin) */}
      {filaCtx && (
        <DistribuicaoFilaDialog
          team={team}
          fromPessoa={filaCtx.fromPessoa}
          subtipo={filaCtx.subtipo}
          max={filaCtx.max}
          alvos={pessoas}
          onClose={() => setFilaCtx(null)}
          onConfirm={(dist) => {
            dist.forEach((d) =>
              registrar({
                fromId: filaCtx.fromPessoa.id, fromNome: filaCtx.fromPessoa.nome,
                toId: d.toId, toNome: d.toNome, subtipo: filaCtx.subtipo, qtd: d.qtd, individual: false,
              }),
            );
            setFilaCtx(null);
          }}
        />
      )}

      {/* progresso bloqueante (aplicar / reverter) */}
      <ExecProgressOverlay exec={exec} onClose={() => setExec(null)} />
    </>
  );
}
