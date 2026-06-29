// Distribuição em fila (round-robin): pega N tarefas de um subtipo de uma pessoa
// e espalha igualmente entre vários colaboradores escolhidos. Ex.: 7 tarefas pra
// 3 estagiários → 3 / 2 / 2.

import { useMemo, useState } from "react";
import { ArrowRight, Split } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";

type Pessoa = { id: number; nome: string };
export type DistItem = { toId: number; toNome: string; qtd: number };

export default function DistribuicaoFilaDialog({
  fromPessoa,
  subtipo,
  max,
  alvos,
  onConfirm,
  onClose,
}: {
  fromPessoa: Pessoa;
  subtipo: string;
  max: number;
  alvos: Pessoa[];
  onConfirm: (dist: DistItem[]) => void;
  onClose: () => void;
}) {
  const outros = useMemo(() => alvos.filter((a) => a.id !== fromPessoa.id), [alvos, fromPessoa.id]);
  const [todos, setTodos] = useState(true);
  const [qtd, setQtd] = useState(max);
  const [sel, setSel] = useState<Set<number>>(new Set());

  const n = todos ? max : Math.max(1, Math.min(qtd || 0, max));
  const targets = outros.filter((o) => sel.has(o.id));

  const dist = useMemo<DistItem[]>(() => {
    if (!targets.length || n <= 0) return [];
    const base = Math.floor(n / targets.length);
    const rem = n % targets.length;
    return targets
      .map((t, i) => ({ toId: t.id, toNome: t.nome, qtd: base + (i < rem ? 1 : 0) }))
      .filter((d) => d.qtd > 0);
  }, [n, targets]);

  const toggle = (id: number) =>
    setSel((s) => {
      const c = new Set(s);
      c.has(id) ? c.delete(id) : c.add(id);
      return c;
    });

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[88vh] max-w-lg overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-base">
            <Split className="h-4 w-4 text-[hsl(var(--dunatech-blue))]" /> Distribuir em fila
          </DialogTitle>
        </DialogHeader>
        <p className="text-xs text-muted-foreground">
          <b>{subtipo}</b> · de {fromPessoa.nome}. Espalha igualmente (round-robin) entre os escolhidos.
        </p>

        {/* quantas */}
        <div className="space-y-2 rounded-lg border p-3">
          <div className="text-xs font-medium text-muted-foreground">Quantas distribuir?</div>
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-1.5 text-sm">
              <Checkbox checked={todos} onCheckedChange={(c) => setTodos(!!c)} /> Todas ({max})
            </label>
            {!todos && (
              <Input
                type="number"
                min={1}
                max={max}
                value={qtd}
                onChange={(e) => setQtd(Number(e.target.value))}
                className="h-8 w-24"
              />
            )}
          </div>
        </div>

        {/* pra quem (multiselect) */}
        <div className="space-y-1 rounded-lg border p-3">
          <div className="mb-1 text-xs font-medium text-muted-foreground">Para quem? ({targets.length} selecionado/s)</div>
          {outros.length === 0 ? (
            <p className="text-xs text-muted-foreground">Selecione mais colaboradores na tabela pra ter destinos.</p>
          ) : (
            <div className="max-h-44 space-y-1 overflow-y-auto">
              {outros.map((o) => (
                <label key={o.id} className="flex cursor-pointer items-center gap-2 rounded px-1.5 py-1 text-sm hover:bg-muted/50">
                  <Checkbox checked={sel.has(o.id)} onCheckedChange={() => toggle(o.id)} />
                  {o.nome}
                </label>
              ))}
            </div>
          )}
        </div>

        {/* prévia da fila */}
        {dist.length > 0 && (
          <div className="rounded-lg border bg-muted/20 p-3 text-xs">
            <div className="mb-1 font-medium">Prévia da fila ({n} tarefa/s):</div>
            <div className="flex flex-wrap gap-x-3 gap-y-1">
              {dist.map((d) => (
                <span key={d.toId} className="tabular-nums">
                  <span className="font-semibold">{d.qtd}×</span> {d.toNome}
                </span>
              ))}
            </div>
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancelar</Button>
          <Button className="gap-1.5" disabled={dist.length === 0} onClick={() => onConfirm(dist)}>
            Distribuir <ArrowRight className="h-4 w-4" />
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
