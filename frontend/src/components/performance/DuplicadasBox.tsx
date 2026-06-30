// Bloco de duplicadas dentro do detalhe do subtipo: preview (mantém a mais
// antiga) + cancelamento real em lote com confirmação e barra de progresso
// (job persistido no backend, polling a cada 1,5s).

import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  type CancelStatus,
  type DuplicadasResp,
  getCancelStatus,
  startCancelarDuplicadas,
} from "@/services/performance";
import { useToast } from "@/hooks/use-toast";

export default function DuplicadasBox({
  team,
  dups,
  onDone,
}: {
  team: string;
  dups: DuplicadasResp;
  onDone: () => void;
}) {
  const { toast } = useToast();
  const [confirming, setConfirming] = useState(false);
  const [job, setJob] = useState<CancelStatus | null>(null);
  const pollRef = useRef<number | null>(null);

  const cancelIds = dups.grupos.flatMap((g) => g.cancelar.map((c) => c.task_id));

  useEffect(() => {
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
    };
  }, []);

  const start = async () => {
    setConfirming(false);
    setJob({
      job_id: "",
      status: "running",
      total: cancelIds.length,
      feito: 0,
      cancelled: 0,
      preservadas: 0,
      falhas: 0,
      erros: [],
    });
    try {
      const { job_id } = await startCancelarDuplicadas(team, dups.subtipo, cancelIds);
      const tick = async () => {
        try {
          const st = await getCancelStatus(job_id);
          setJob(st);
          if (st.status === "done") {
            if (pollRef.current) window.clearInterval(pollRef.current);
            pollRef.current = null;
            onDone();
          }
        } catch {
          /* ignora erro transitório de polling */
        }
      };
      await tick();
      pollRef.current = window.setInterval(tick, 1500);
    } catch (e) {
      setJob(null);
      toast({
        title: "Erro ao iniciar o cancelamento",
        description: String((e as Error).message),
        variant: "destructive",
      });
    }
  };

  if (dups.total_cancelar === 0 && !job) {
    return <p className="text-[11px] font-medium text-emerald-700">✓ Sem duplicadas neste tipo.</p>;
  }

  const pct = job && job.total ? Math.round((100 * job.feito) / job.total) : 0;

  return (
    <div className="rounded-lg border border-rose-300 bg-rose-50/60 p-2.5">
      <div className="flex items-center justify-between gap-2">
        <div className="text-[11px] font-semibold text-rose-700">Tarefas duplicadas</div>
        <div className="text-sm font-bold tabular-nums text-rose-700">
          {dups.total_cancelar} a cancelar · {dups.total_grupos} pasta(s)
        </div>
      </div>
      <div className="mt-0.5 text-[10px] leading-snug text-muted-foreground">
        Mesma pasta + mesmo subtipo (desvio de fluxo). Mantém a mais antiga (original) e cancela as criadas depois.
      </div>
      <details className="mt-1.5">
        <summary className="cursor-pointer text-[11px] text-rose-700">Ver pastas</summary>
        <div className="mt-1 max-h-36 space-y-1 overflow-y-auto">
          {dups.grupos.map((g) => (
            <div key={g.pasta} className="rounded border bg-background px-2 py-1 text-[11px]">
              <span className="font-medium">{g.pasta}</span>
              {g.cnj ? <span className="text-muted-foreground"> · {g.cnj}</span> : null}
              <span className="ml-1 font-medium text-rose-700">— cancela {g.cancelar.length}</span>
            </div>
          ))}
        </div>
      </details>

      {job ? (
        <div className="mt-2">
          <div className="mb-1 flex items-center justify-between text-[11px]">
            <span className="font-medium">{job.status === "done" ? "Concluído" : "Cancelando no L1…"}</span>
            <span className="tabular-nums text-muted-foreground">
              {job.feito}/{job.total}
            </span>
          </div>
          <div className="h-2 overflow-hidden rounded bg-rose-100">
            <div className="h-full bg-rose-500 transition-all" style={{ width: `${pct}%` }} />
          </div>
          {job.status === "done" ? (
            <p className="mt-1 text-[10px] text-muted-foreground">
              <b className="text-rose-700">{job.cancelled}</b> canceladas · {job.preservadas} preservadas (já
              encerradas) · {job.falhas} falhas.
            </p>
          ) : (
            <p className="mt-1 text-[10px] text-muted-foreground">
              Roda em background (~0,3/s). Pode fechar — o lote continua no servidor.
            </p>
          )}
        </div>
      ) : confirming ? (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <span className="text-[11px] font-medium text-rose-700">Cancelar {dups.total_cancelar} tarefa(s) no L1?</span>
          <Button size="sm" variant="destructive" className="h-7 text-xs" onClick={start}>
            Sim, cancelar
          </Button>
          <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => setConfirming(false)}>
            Não
          </Button>
        </div>
      ) : (
        <Button
          size="sm"
          variant="destructive"
          className="mt-2 h-7 gap-1 text-xs"
          onClick={() => setConfirming(true)}
        >
          Cancelar {dups.total_cancelar} duplicadas
        </Button>
      )}
    </div>
  );
}
