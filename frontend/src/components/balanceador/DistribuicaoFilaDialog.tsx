// Distribuição em fila (round-robin): pega N tarefas de um subtipo de uma pessoa
// e espalha igualmente entre vários colaboradores escolhidos. Ex.: 7 tarefas pra
// 3 estagiários → 3 / 2 / 2.

import { useEffect, useMemo, useState } from "react";
import { ArrowRight, Split, UserPlus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { getUsuarios } from "@/services/balanceador";

type Pessoa = { id: number; nome: string };
export type DistItem = { toId: number; toNome: string; qtd: number };

export default function DistribuicaoFilaDialog({
  team,
  fromPessoa,
  subtipo,
  max,
  alvos,
  onConfirm,
  onClose,
}: {
  team: string;
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
  const [externos, setExternos] = useState<Pessoa[]>([]);
  const [searchOpen, setSearchOpen] = useState(false);
  const [busca, setBusca] = useState("");
  const [cand, setCand] = useState<Pessoa[]>([]);

  useEffect(() => {
    if (!searchOpen) return;
    getUsuarios(team, busca)
      .then(setCand)
      .catch(() => undefined);
  }, [searchOpen, busca, team]);

  const pool = useMemo(() => [...outros, ...externos], [outros, externos]);
  const n = todos ? max : Math.max(1, Math.min(qtd || 0, max));
  const targets = pool.filter((o) => sel.has(o.id));

  const addExterno = (u: Pessoa) => {
    setSearchOpen(false);
    setBusca("");
    if (u.id === fromPessoa.id) return; // não distribui pra própria origem
    const jaNaTabela = outros.find((o) => o.nome.toLowerCase() === u.nome.toLowerCase());
    if (jaNaTabela) {
      setSel((s) => new Set(s).add(jaNaTabela.id)); // já está na tabela: só marca
    } else {
      if (!externos.some((e) => e.id === u.id)) setExternos((prev) => [...prev, u]);
      setSel((s) => new Set(s).add(u.id));
    }
  };

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

        {/* pra quem (multiselect da tabela + busca de qualquer colaborador) */}
        <div className="space-y-2 rounded-lg border p-3">
          <div className="flex items-center justify-between gap-2">
            <div className="text-xs font-medium text-muted-foreground">Para quem? ({targets.length} selecionado/s)</div>
            <Popover open={searchOpen} onOpenChange={setSearchOpen}>
              <PopoverTrigger asChild>
                <Button size="sm" variant="outline" className="h-7 gap-1 text-xs">
                  <UserPlus className="h-3.5 w-3.5" /> Buscar colaborador
                </Button>
              </PopoverTrigger>
              <PopoverContent className="w-72 p-0" align="end">
                <Command shouldFilter={false}>
                  <CommandInput placeholder="Buscar no L1…" value={busca} onValueChange={setBusca} />
                  <CommandList>
                    <CommandEmpty>Ninguém encontrado.</CommandEmpty>
                    <CommandGroup>
                      {cand.map((u) => (
                        <CommandItem key={u.id} value={u.nome} onSelect={() => addExterno(u)}>
                          {u.nome}
                        </CommandItem>
                      ))}
                    </CommandGroup>
                  </CommandList>
                </Command>
              </PopoverContent>
            </Popover>
          </div>
          <p className="text-[10px] text-muted-foreground">
            Mistura os da tabela com qualquer colaborador buscado — destino só recebe (não carrega as tarefas dele).
          </p>
          {pool.length === 0 ? (
            <p className="text-xs text-muted-foreground">Use a busca pra escolher pra quem distribuir.</p>
          ) : (
            <div className="max-h-40 space-y-1 overflow-y-auto">
              {pool.map((o) => (
                <label key={o.id} className="flex cursor-pointer items-center gap-2 rounded px-1.5 py-1 text-sm hover:bg-muted/50">
                  <Checkbox checked={sel.has(o.id)} onCheckedChange={() => toggle(o.id)} />
                  <span className="flex-1">{o.nome}</span>
                  {externos.some((e) => e.id === o.id) && (
                    <span className="text-[10px] text-muted-foreground">buscado</span>
                  )}
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
