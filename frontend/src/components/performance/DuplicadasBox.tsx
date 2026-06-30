// Bloco de duplicadas dentro do detalhe do subtipo. O preview (snapshot) é só
// estimativa; ao cancelar, o backend VARRE o L1 ao vivo pra achar as duplicadas
// reais de agora (mantém a mais antiga) e só então cancela. Mostra as 2 fases
// (varredura → cancelamento) com barra de progresso + botão Parar.

import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  type CancelStatus,
  type DuplicadasResp,
  abortCancelarDuplicadas,
  getCancelStatus,
  startCancelarDuplicadas,
} from "@/services/performance";
import { useToast } from "@/hooks/use-toast";

const fmtEta = (sec: number): string => {
  if (!isFinite(sec) || sec <= 0) return "";
  if (sec < 60) return `~${Math.round(sec)}s`;
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  return s ? `~${m}min ${s}s` : `~${m}min`;
};

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
  const jobIdRef = useRef<string | null>(null);
  const pollRef = useRef<number | null>(null);
  const startedAtRef = useRef<number>(0); // p/ ETA observado (ms)
  const cancelStartRef = useRef<number>(0);

  useEffect(() => {
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
    };
  }, []);

  const start = async () => {
    setConfirming(false);
    startedAtRef.current = Date.now();
    cancelStartRef.current = 0;
    setJob({
      job_id: "",
      status: "running",
      fase: "scanning",
      scan_total: 0,
      scan_feito: 0,
      total: 0,
      feito: 0,
      cancelled: 0,
      preservadas: 0,
      falhas: 0,
      erros: [],
    });
    try {
      const { job_id } = await startCancelarDuplicadas(team, dups.subtipo);
      jobIdRef.current = job_id;
      const tick = async () => {
        try {
          const st = await getCancelStatus(team, job_id);
          if (st.fase === "cancelling" && !cancelStartRef.current) cancelStartRef.current = Date.now();
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
      toast({ title: "Erro ao iniciar", description: String((e as Error).message), variant: "destructive" });
    }
  };

  const stop = async () => {
    if (!jobIdRef.current) return;
    try {
      await abortCancelarDuplicadas(team, jobIdRef.current);
    } catch {
      /* ignora */
    }
  };

  if (dups.total_cancelar === 0 && !job) {
    return <p className="text-[11px] font-medium text-emerald-700">✓ Sem duplicadas neste tipo (snapshot).</p>;
  }

  const scanning = !!job && job.fase === "scanning";
  const done = !!job && job.status === "done";
  const pct = done
    ? 100
    : job
      ? scanning
        ? job.scan_total
          ? Math.round((100 * job.scan_feito) / job.scan_total)
          : 0
        : job.total
          ? Math.round((100 * job.feito) / job.total)
          : 0
      : 0;

  // ETA pelo ritmo REAL observado (auto-calibra): ms/pasta na varredura, ms/tarefa no cancelamento.
  let eta = "";
  if (job && !done) {
    if (scanning && job.scan_feito >= 2 && startedAtRef.current) {
      const rate = (Date.now() - startedAtRef.current) / job.scan_feito;
      eta = fmtEta(((job.scan_total - job.scan_feito) * rate) / 1000);
    } else if (!scanning && job.feito >= 2 && cancelStartRef.current && job.total) {
      const rate = (Date.now() - cancelStartRef.current) / job.feito;
      eta = fmtEta(((job.total - job.feito) * rate) / 1000);
    }
  }

  return (
    <div className="rounded-lg border border-rose-300 bg-rose-50/60 p-2.5">
      <div className="flex items-center justify-between gap-2">
        <div className="text-[11px] font-semibold text-rose-700">Tarefas duplicadas</div>
        <div className="text-sm font-bold tabular-nums text-rose-700">
          ~{dups.total_cancelar} no snapshot · {dups.total_grupos} pasta(s)
        </div>
      </div>
      <div className="mt-0.5 text-[10px] leading-snug text-muted-foreground">
        Mesma pasta + mesmo subtipo (desvio de fluxo). Ao cancelar, o sistema <b>varre o L1 ao vivo</b> pra confirmar as
        duplicadas reais de agora (mantém a mais antiga) — o número do snapshot é só estimativa.
      </div>
      <details className="mt-1.5">
        <summary className="cursor-pointer text-[11px] text-rose-700">Ver pastas (snapshot)</summary>
        <div className="mt-1 max-h-36 space-y-1 overflow-y-auto">
          {dups.grupos.map((g) => (
            <div key={g.pasta} className="rounded border bg-background px-2 py-1 text-[11px]">
              <span className="font-medium">{g.pasta}</span>
              {g.cnj ? <span className="text-muted-foreground"> · {g.cnj}</span> : null}
              <span className="ml-1 font-medium text-rose-700">— ~{g.cancelar.length}</span>
            </div>
          ))}
        </div>
      </details>

      {job ? (
        <div className="mt-2">
          <div className="mb-1 flex items-center justify-between text-[11px]">
            <span className="font-medium">
              {done ? "Concluído" : scanning ? "Varrendo o L1…" : "Cancelando no L1…"}
            </span>
            <span className="tabular-nums text-muted-foreground">
              {done
                ? ""
                : scanning
                  ? `${job.scan_feito}/${job.scan_total} pastas${eta ? ` · ${eta} restantes` : ""}`
                  : `${job.feito}/${job.total}${eta ? ` · ${eta} restantes` : ""}`}
            </span>
          </div>
          <div className="h-2 overflow-hidden rounded bg-rose-100">
            <div
              className={`h-full transition-all ${scanning ? "bg-amber-500" : "bg-rose-500"}`}
              style={{ width: `${pct}%` }}
            />
          </div>
          {done ? (
            <p className="mt-1 text-[10px] text-muted-foreground">
              Varreu {job.scan_total} pasta(s) ao vivo → <b className="text-rose-700">{job.cancelled}</b> canceladas ·{" "}
              {job.preservadas} preservadas · {job.falhas} falhas.
            </p>
          ) : (
            <div className="mt-1 flex items-center justify-between gap-2">
              <span className="text-[10px] text-muted-foreground">
                {scanning ? "Achando as duplicadas reais…" : "Roda em background — pode fechar, continua no servidor."}
              </span>
              <Button
                size="sm"
                variant="outline"
                className="h-6 px-2 text-[10px]"
                onClick={stop}
                disabled={job.status === "aborting"}
              >
                {job.status === "aborting" ? "Parando…" : "Parar"}
              </Button>
            </div>
          )}
        </div>
      ) : confirming ? (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <span className="text-[11px] font-medium text-rose-700">Varrer o L1 e cancelar as duplicadas reais?</span>
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
          Cancelar duplicadas (varredura ao vivo)
        </Button>
      )}
    </div>
  );
}
