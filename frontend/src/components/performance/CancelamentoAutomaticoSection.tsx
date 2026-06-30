// Admin: gestão do cancelamento AUTOMÁTICO de duplicadas (rotina da madrugada).
// Whitelist incrementável de subtipos + "rodar agora" (dry-run/real) + auditoria.

import { useEffect, useRef, useState } from "react";
import { Loader2, Play, Plus, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  type MassaLog,
  type SubtipoCatalogo,
  type WhitelistItem,
  addWhitelist,
  getCatalogo,
  getMassaLogs,
  getWhitelist,
  removeWhitelist,
  runMassa,
  toggleWhitelist,
} from "@/services/cancelAutomatico";
import { useToast } from "@/hooks/use-toast";

const fmtDt = (s: string | null): string => {
  if (!s) return "—";
  const d = new Date(s);
  return isNaN(d.getTime()) ? "—" : d.toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
};

export default function CancelamentoAutomaticoSection() {
  const { toast } = useToast();
  const [wl, setWl] = useState<WhitelistItem[]>([]);
  const [logs, setLogs] = useState<MassaLog[]>([]);
  const [cat, setCat] = useState<SubtipoCatalogo[]>([]);
  const [busca, setBusca] = useState("");
  const [addOpen, setAddOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [confirm, setConfirm] = useState<null | "dry" | "real">(null);
  const pollRef = useRef<number | null>(null);

  const carregar = () => {
    getWhitelist().then(setWl).catch(() => undefined);
    getMassaLogs().then(setLogs).catch(() => undefined);
  };

  useEffect(() => {
    carregar();
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
    };
  }, []);

  useEffect(() => {
    if (!addOpen) return;
    getCatalogo(busca).then(setCat).catch(() => undefined);
  }, [addOpen, busca]);

  const wrap = (p: Promise<WhitelistItem[]>, erro: string) => {
    setSaving(true);
    p.then(setWl)
      .catch((e) => toast({ title: erro, description: String((e as Error).message), variant: "destructive" }))
      .finally(() => setSaving(false));
  };

  const run = (dryRun: boolean) => {
    setConfirm(null);
    runMassa(dryRun)
      .then(() => {
        toast({ title: dryRun ? "Pré-visualização iniciada" : "Cancelamento em massa iniciado", description: "Rodando em background — a auditoria atualiza abaixo." });
        // poll a auditoria por ~2min pra mostrar o resultado
        let n = 0;
        if (pollRef.current) window.clearInterval(pollRef.current);
        pollRef.current = window.setInterval(() => {
          getMassaLogs().then(setLogs).catch(() => undefined);
          if (++n >= 40 && pollRef.current) window.clearInterval(pollRef.current);
        }, 3000);
      })
      .catch((e) => toast({ title: "Erro ao disparar", description: String((e as Error).message), variant: "destructive" }));
  };

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>Cancelamento automático de duplicadas</CardTitle>
          <CardDescription>
            Toda madrugada (4h), após atualizar o pool, a rotina cancela as tarefas duplicadas (mesma pasta + mesmo
            subtipo, mantendo a mais antiga) de <b>todas as carteiras</b> — mas <b>só</b> dos subtipos liberados abaixo.
            O resto é preservado. Pré-check ao vivo nunca toca tarefa já encerrada.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-center justify-between gap-2">
            <span className="text-sm font-medium">Subtipos liberados ({wl.filter((w) => w.ativo).length} ativos)</span>
            <div className="flex items-center gap-2">
              <Popover open={addOpen} onOpenChange={setAddOpen}>
                <PopoverTrigger asChild>
                  <Button size="sm" variant="outline" className="gap-1.5" disabled={saving}>
                    <Plus className="h-4 w-4" /> Liberar subtipo
                  </Button>
                </PopoverTrigger>
                <PopoverContent className="w-96 p-0" align="end">
                  <Command shouldFilter={false}>
                    <CommandInput placeholder="Buscar subtipo…" value={busca} onValueChange={setBusca} />
                    <CommandList>
                      <CommandEmpty>Nenhum subtipo.</CommandEmpty>
                      <CommandGroup>
                        {cat.map((c) => (
                          <CommandItem
                            key={c.subtipo}
                            value={c.subtipo}
                            onSelect={() => {
                              setAddOpen(false);
                              setBusca("");
                              wrap(addWhitelist(c.subtipo), "Erro ao liberar");
                            }}
                          >
                            <span className="flex-1 truncate">{c.subtipo}</span>
                            <span className="ml-auto shrink-0 text-[10px] text-muted-foreground">{c.volume}</span>
                          </CommandItem>
                        ))}
                      </CommandGroup>
                    </CommandList>
                  </Command>
                </PopoverContent>
              </Popover>
            </div>
          </div>

          <div className="space-y-1.5">
            {wl.length === 0 ? (
              <p className="rounded-lg border border-dashed p-3 text-center text-xs text-muted-foreground">
                Nenhum subtipo liberado — a rotina não cancela nada.
              </p>
            ) : (
              wl.map((w) => (
                <div key={w.id} className="flex items-center gap-2 rounded-lg border px-2.5 py-1.5 text-sm">
                  <span className="flex-1 truncate">{w.subtipo}</span>
                  <Button
                    size="sm"
                    variant={w.ativo ? "default" : "outline"}
                    className="h-6 px-2 text-[10px]"
                    disabled={saving}
                    onClick={() => wrap(toggleWhitelist(w.subtipo, !w.ativo), "Erro ao alternar")}
                  >
                    {w.ativo ? "Ativo" : "Inativo"}
                  </Button>
                  <Button
                    size="icon"
                    variant="ghost"
                    className="h-6 w-6 text-rose-600 hover:text-rose-700"
                    disabled={saving}
                    onClick={() => wrap(removeWhitelist(w.subtipo), "Erro ao remover")}
                    title="Remover da whitelist"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </div>
              ))
            )}
          </div>

          <div className="flex flex-wrap items-center gap-2 border-t pt-3">
            {confirm === null ? (
              <>
                <Button size="sm" variant="outline" className="gap-1.5" onClick={() => setConfirm("dry")}>
                  <Play className="h-4 w-4" /> Pré-visualizar (dry-run)
                </Button>
                <Button size="sm" variant="destructive" className="gap-1.5" onClick={() => setConfirm("real")}>
                  <Play className="h-4 w-4" /> Cancelar agora (real)
                </Button>
                <span className="text-[11px] text-muted-foreground">
                  Dry-run só conta o que cancelaria; real cancela de verdade no L1.
                </span>
              </>
            ) : (
              <>
                <span className="text-[11px] font-medium text-rose-700">
                  {confirm === "real" ? "Cancelar de verdade as duplicadas dos subtipos ativos?" : "Rodar a prévia (sem cancelar)?"}
                </span>
                <Button size="sm" variant={confirm === "real" ? "destructive" : "default"} onClick={() => run(confirm === "dry")}>
                  Sim
                </Button>
                <Button size="sm" variant="outline" onClick={() => setConfirm(null)}>
                  Não
                </Button>
              </>
            )}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Auditoria das execuções</CardTitle>
          <CardDescription>Cada rodada (madrugada ou manual) — total e quebra por subtipo.</CardDescription>
        </CardHeader>
        <CardContent>
          {logs.length === 0 ? (
            <p className="text-xs text-muted-foreground">Nenhuma execução ainda.</p>
          ) : (
            <div className="space-y-2">
              {logs.map((l) => (
                <details key={l.id} className="rounded-lg border p-2.5 text-sm">
                  <summary className="cursor-pointer">
                    <span className="font-medium">{fmtDt(l.iniciado_em)}</span>
                    {l.dry_run && <span className="ml-2 rounded bg-slate-200 px-1.5 text-[10px]">dry-run</span>}
                    <span className="ml-2 text-[11px] text-muted-foreground">({l.origem || "?"})</span>
                    {l.status === "running" && <Loader2 className="ml-2 inline h-3 w-3 animate-spin" />}
                    <span className="ml-2 text-[12px]">
                      <b className="text-rose-700">{l.cancelled}</b> canceladas · {l.preservadas} preserv. · {l.falhas}{" "}
                      falhas · {l.total_candidatos} candidatos
                    </span>
                  </summary>
                  <div className="mt-1.5 space-y-1">
                    {Object.entries(l.detalhe || {}).map(([sub, d]) => (
                      <div key={sub} className="rounded bg-muted/40 px-2 py-1 text-[11px]">
                        <span className="font-medium">{sub}</span>
                        <span className="ml-2 text-muted-foreground">
                          {d.dry_run
                            ? `${d.candidatos ?? 0} candidatos (prévia)`
                            : `${d.cancelled ?? 0} canceladas / ${d.candidatos ?? 0} candidatos · ${d.preservadas ?? 0} preserv. · ${d.falhas ?? 0} falhas`}
                        </span>
                      </div>
                    ))}
                  </div>
                </details>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
