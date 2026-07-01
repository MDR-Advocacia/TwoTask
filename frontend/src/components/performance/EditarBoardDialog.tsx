// Editor da curadoria do board "Tarefas mais importantes": adiciona/remove os
// subtipos exibidos. Sem nenhum fixado → board automático (top-12 por volume).

import { useEffect, useState } from "react";
import { Plus, Settings2, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
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
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  type BoardCatalogoItem,
  addBoardTarefa,
  getBoardCatalogo,
  getBoardTarefas,
  removeBoardTarefa,
} from "@/services/performance";
import { useToast } from "@/hooks/use-toast";

export default function EditarBoardDialog({
  team,
  onClose,
  onChanged,
}: {
  team: string;
  onClose: () => void;
  onChanged: () => void;
}) {
  const { toast } = useToast();
  const [curado, setCurado] = useState(false);
  const [subtipos, setSubtipos] = useState<string[]>([]);
  const [cat, setCat] = useState<BoardCatalogoItem[]>([]);
  const [busca, setBusca] = useState("");
  const [addOpen, setAddOpen] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    getBoardTarefas(team)
      .then((c) => {
        setCurado(c.curado);
        setSubtipos(c.subtipos);
      })
      .catch(() => undefined);
  }, [team]);

  useEffect(() => {
    if (!addOpen) return;
    getBoardCatalogo(team, busca).then(setCat).catch(() => undefined);
  }, [addOpen, busca, team]);

  const apply = (p: Promise<{ curado: boolean; subtipos: string[] }>, erro: string) => {
    setSaving(true);
    p.then((c) => {
      setCurado(c.curado);
      setSubtipos(c.subtipos);
      onChanged();
    })
      .catch((e) => toast({ title: erro, description: String((e as Error).message), variant: "destructive" }))
      .finally(() => setSaving(false));
  };

  const add = (s: string) => {
    setAddOpen(false);
    setBusca("");
    apply(addBoardTarefa(team, s), "Erro ao adicionar");
  };
  const remove = (s: string) => apply(removeBoardTarefa(team, s), "Erro ao remover");

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-base">
            <Settings2 className="h-4 w-4 text-[hsl(var(--dunatech-blue))]" /> Tarefas do board
          </DialogTitle>
        </DialogHeader>
        <p className="text-xs text-muted-foreground">
          {curado
            ? "O board mostra exatamente os tipos abaixo, nesta ordem. Remova todos pra voltar ao automático (top-12 por volume)."
            : "O board está no automático (top-12 por volume, abaixo). Remova os que não quiser ou adicione outros — ao editar, sua seleção passa a ser fixa."}
        </p>

        <div className="space-y-1.5">
          {subtipos.length === 0 ? (
            <p className="rounded-lg border border-dashed p-3 text-center text-xs text-muted-foreground">
              Nenhum tipo fixado — board automático.
            </p>
          ) : (
            subtipos.map((s, i) => (
              <div key={s} className="flex items-center gap-2 rounded-lg border px-2.5 py-1.5 text-sm">
                <span className="w-5 text-center text-xs text-muted-foreground">{i + 1}</span>
                <span className="flex-1 truncate">{s}</span>
                <Button
                  size="icon"
                  variant="ghost"
                  className="h-6 w-6 text-rose-600 hover:text-rose-700"
                  disabled={saving}
                  onClick={() => remove(s)}
                  title="Remover do board"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </div>
            ))
          )}
        </div>

        <Popover open={addOpen} onOpenChange={setAddOpen}>
          <PopoverTrigger asChild>
            <Button variant="outline" size="sm" className="gap-1.5" disabled={saving}>
              <Plus className="h-4 w-4" /> Adicionar tipo
            </Button>
          </PopoverTrigger>
          <PopoverContent className="w-80 p-0" align="start">
            <Command shouldFilter={false}>
              <CommandInput placeholder="Buscar subtipo do time…" value={busca} onValueChange={setBusca} />
              <CommandList>
                <CommandEmpty>Nenhum subtipo.</CommandEmpty>
                <CommandGroup>
                  {cat.map((c) => (
                    <CommandItem key={c.subtipo} value={c.subtipo} onSelect={() => add(c.subtipo)}>
                      <span className="flex-1 truncate">{c.subtipo}</span>
                      <span className="ml-auto shrink-0 text-[10px] text-muted-foreground">{c.volume}</span>
                    </CommandItem>
                  ))}
                </CommandGroup>
              </CommandList>
            </Command>
          </PopoverContent>
        </Popover>

        <DialogFooter>
          <Button onClick={onClose}>Fechar</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
