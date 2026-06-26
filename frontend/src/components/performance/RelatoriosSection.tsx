// frontend/src/components/performance/RelatoriosSection.tsx
//
// Lista dos relatórios gerados como JOB persistente — rodam no servidor, então
// sobrevivem à navegação/saída. Faz polling enquanto houver algum "processando"
// e baixa o PDF quando fica pronto. A geração é disparada de fora (botão do
// header pro setor; botão do Raio-X pra pessoa) — aqui só lista/baixa.

import { useCallback, useEffect, useState } from "react";
import { AlertCircle, Download, Loader2, RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useToast } from "@/hooks/use-toast";
import { type RelatorioItem, downloadRelatorioById, listarRelatorios } from "@/services/performance";

function fmtData(iso: string | null): string {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString("pt-BR", {
      day: "2-digit",
      month: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return "";
  }
}

export default function RelatoriosSection({ reloadKey }: { reloadKey: number }) {
  const { toast } = useToast();
  const [items, setItems] = useState<RelatorioItem[]>([]);

  const fetchList = useCallback(async () => {
    try {
      setItems(await listarRelatorios());
    } catch {
      /* silencioso — não atrapalha a página */
    }
  }, []);

  // Recarrega na montagem e sempre que alguém dispara um relatório (reloadKey).
  useEffect(() => {
    fetchList();
  }, [fetchList, reloadKey]);

  // Polling enquanto houver algum em geração.
  useEffect(() => {
    if (!items.some((i) => i.status === "processando")) return;
    const t = setInterval(fetchList, 4000);
    return () => clearInterval(t);
  }, [items, fetchList]);

  const baixar = async (id: number) => {
    try {
      await downloadRelatorioById(id);
    } catch (e) {
      toast({ title: "Erro ao baixar", description: String((e as Error).message), variant: "destructive" });
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-muted-foreground">
          Relatórios PDF rodam no servidor — pode sair da tela que continuam. Dispare pelo botão
          <span className="font-medium"> Relatório do setor</span> (topo) ou pelo
          <span className="font-medium"> Relatório (PDF)</span> dentro do Raio-X.
        </p>
        <Button variant="outline" size="sm" className="h-7 gap-1 text-xs" onClick={fetchList}>
          <RefreshCw className="h-3.5 w-3.5" /> Atualizar
        </Button>
      </div>

      {items.length === 0 ? (
        <p className="rounded-lg border bg-muted/20 py-6 text-center text-sm text-muted-foreground">
          Nenhum relatório ainda.
        </p>
      ) : (
        <div className="space-y-1.5">
          {items.map((r) => (
            <div key={r.id} className="flex items-center justify-between gap-3 rounded-md border px-3 py-2">
              <div className="min-w-0">
                <div className="truncate text-sm font-medium">{r.label}</div>
                <div className="text-[11px] text-muted-foreground">{fmtData(r.criado_em)}</div>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                {r.status === "processando" && (
                  <span className="flex items-center gap-1 text-xs text-amber-700">
                    <Loader2 className="h-3.5 w-3.5 animate-spin" /> Gerando…
                  </span>
                )}
                {r.status === "erro" && (
                  <span className="flex items-center gap-1 text-xs text-rose-700" title={r.erro ?? ""}>
                    <AlertCircle className="h-3.5 w-3.5" /> Erro
                  </span>
                )}
                {r.status === "pronto" && (
                  <Button size="sm" variant="outline" className="h-7 gap-1 text-xs" onClick={() => baixar(r.id)}>
                    <Download className="h-3.5 w-3.5" /> Baixar
                  </Button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
