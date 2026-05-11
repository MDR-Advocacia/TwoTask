/**
 * ProcessoDrawer — Sheet lateral aberto ao clicar numa linha da tabela
 * Processos. Tres sub-tabs:
 *
 * 1. Estado atual: campos principais (read-only por default) com botao
 *    "Editar" que ativa edicao inline em usuario_responsavel / situacao /
 *    polo / materia / risco. Salvar dispara PATCH + toast com undo 60s.
 * 2. Historico: lista de snapshots cronologica. Selecionar 2 -> diff
 *    side-by-side dos campos significativos (cor vermelho/verde).
 * 3. Eventos: lista de eventos com badge cromatico + changed_fields
 *    expandido inline pra ATUALIZADO/ATUALIZADO_MANUAL.
 */

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  ArrowRightLeft,
  CheckCircle2,
  Loader2,
  Pencil,
  X,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

import {
  type ProcessoOut,
  type SnapshotOut,
  getProcesso,
  getProcessoEventos,
  getProcessoHistorico,
  patchProcesso,
} from "@/lib/api-base-processual";
import { cn } from "@/lib/utils";

type Props = {
  codAjus: string | null;
  onClose: () => void;
};

function fmtBR(s: string | null | undefined): string {
  if (!s) return "—";
  try {
    return new Date(s).toLocaleString("pt-BR", { timeZone: "America/Sao_Paulo" });
  } catch {
    return s;
  }
}

function fmtDataBR(s: string | null | undefined): string {
  if (!s) return "—";
  try {
    return new Date(s).toLocaleDateString("pt-BR", { timeZone: "America/Sao_Paulo" });
  } catch {
    return s;
  }
}

function fmtMoney(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString("pt-BR", {
    style: "currency",
    currency: "BRL",
    minimumFractionDigits: 2,
  });
}

function presencaBadge(status: string): JSX.Element {
  return status === "ATIVO_NA_BASE" ? (
    <Badge className="bg-emerald-100 text-emerald-900 dark:bg-emerald-900/30 dark:text-emerald-300">
      Ativo na base
    </Badge>
  ) : (
    <Badge className="bg-red-100 text-red-900 dark:bg-red-900/30 dark:text-red-300">
      Removido
    </Badge>
  );
}

const SIGNIFICANT_FIELDS_LABEL: Record<string, string> = {
  situacao_processo: "Situação",
  polo: "Polo",
  materia: "Matéria",
  risco_prob_perda: "Risco/Prob. perda",
  tipo_acao: "Tipo de ação",
  natureza: "Natureza",
  numero_vara: "Nº Vara",
  foro: "Foro",
  comarca: "Comarca",
  uf: "UF",
  grupo_responsavel: "Grupo responsável",
  usuario_responsavel: "Usuário responsável",
  escritorio_responsavel: "Escritório responsável",
  valor_causa: "Valor causa",
  valor_prev_acordo: "Valor prev. acordo",
  valor_acordo: "Valor acordo",
  valor_discutido: "Valor discutido",
  valor_exito: "Valor êxito",
  valor_condenacao: "Valor condenação",
  valor_contingencia: "Valor contingência",
  ult_andamento: "Último andamento",
  autores_json: "Autores",
  reus_json: "Réus",
  numero_processo: "Nº processo",
  numero_pasta: "Nº pasta",
  numero_interno: "Nº interno",
  numero_contrato: "Nº contrato",
  acao_principal: "Ação principal",
  processo_virtual: "Processo virtual",
  justica_honorario: "Justiça/Honorário",
  distribuido_em: "Distribuído em",
};

function fieldLabel(k: string): string {
  return SIGNIFICANT_FIELDS_LABEL[k] ?? k;
}

function fmtFieldValue(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "boolean") return v ? "Sim" : "Não";
  if (Array.isArray(v)) {
    return v
      .map((x) => {
        if (x && typeof x === "object" && "nome" in x) {
          return (x as { nome?: string }).nome ?? "";
        }
        return JSON.stringify(x);
      })
      .filter(Boolean)
      .join("; ");
  }
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

export function ProcessoDrawer({ codAjus, onClose }: Props) {
  const open = !!codAjus;
  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full sm:max-w-2xl overflow-y-auto">
        {codAjus ? (
          <DrawerContent codAjus={codAjus} onClose={onClose} />
        ) : null}
      </SheetContent>
    </Sheet>
  );
}

function DrawerContent({
  codAjus,
  onClose,
}: {
  codAjus: string;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const processoQ = useQuery({
    queryKey: ["base-processual-processo", codAjus],
    queryFn: () => getProcesso(codAjus),
  });

  const p = processoQ.data;
  const isLoading = processoQ.isLoading;

  return (
    <>
      <SheetHeader>
        <div className="flex items-center justify-between gap-4">
          <div className="min-w-0">
            <SheetTitle className="font-mono truncate">
              {p?.cod_ajus ?? codAjus}
            </SheetTitle>
            <SheetDescription className="truncate">
              {p?.numero_processo_mascarado ?? "—"}
            </SheetDescription>
          </div>
          {p && presencaBadge(p.presenca_status)}
        </div>
      </SheetHeader>

      {isLoading || !p ? (
        <div className="py-12 flex items-center justify-center text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin mr-2" /> Carregando...
        </div>
      ) : (
        <Tabs defaultValue="atual" className="mt-4">
          <TabsList className="w-full grid grid-cols-3">
            <TabsTrigger value="atual">Estado atual</TabsTrigger>
            <TabsTrigger value="historico">Histórico</TabsTrigger>
            <TabsTrigger value="eventos">Eventos</TabsTrigger>
          </TabsList>

          <TabsContent value="atual" className="mt-4">
            <EstadoAtualTab processo={p} onUpdate={onClose} />
          </TabsContent>
          <TabsContent value="historico" className="mt-4">
            <HistoricoTab codAjus={codAjus} />
          </TabsContent>
          <TabsContent value="eventos" className="mt-4">
            <EventosTab codAjus={codAjus} />
          </TabsContent>
        </Tabs>
      )}
    </>
  );
}

function EstadoAtualTab({
  processo,
  onUpdate,
}: {
  processo: ProcessoOut;
  onUpdate: () => void;
}) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<{
    situacao_processo: string;
    usuario_responsavel: string;
    polo: string;
    materia: string;
    risco_prob_perda: string;
  }>({
    situacao_processo: processo.situacao_processo,
    usuario_responsavel: processo.usuario_responsavel ?? "",
    polo: processo.polo ?? "",
    materia: processo.materia ?? "",
    risco_prob_perda: processo.risco_prob_perda ?? "",
  });

  const patchMutation = useMutation({
    mutationFn: async (vars: {
      changes: Record<string, string>;
      motivo?: string;
      previous: Record<string, string | null>;
    }) => {
      return patchProcesso(processo.cod_ajus, {
        ...vars.changes,
        motivo: vars.motivo,
      });
    },
    onSuccess: (result, vars) => {
      queryClient.setQueryData(
        ["base-processual-processo", processo.cod_ajus],
        result,
      );
      queryClient.invalidateQueries({ queryKey: ["base-processual-processos"] });
      queryClient.invalidateQueries({
        queryKey: ["base-processual-processo-eventos", processo.cod_ajus],
      });
      queryClient.invalidateQueries({
        queryKey: ["base-processual-processo-historico", processo.cod_ajus],
      });
      queryClient.invalidateQueries({ queryKey: ["base-processual-dashboard"] });
      setEditing(false);
      // Toast com undo de 60s — reverte usando os valores anteriores
      const undoChanges: Record<string, string> = {};
      for (const k of Object.keys(vars.changes)) {
        undoChanges[k] = (vars.previous[k] ?? "") as string;
      }
      toast.success("Alterações aplicadas", {
        description: `${Object.keys(vars.changes).length} campo(s) atualizado(s) em ${processo.cod_ajus}.`,
        duration: 60_000,
        action: {
          label: "Desfazer",
          onClick: () => {
            patchMutation.mutate({
              changes: undoChanges,
              motivo: "Undo via toast (60s window)",
              previous: vars.changes as Record<string, string | null>,
            });
          },
        },
      });
    },
    onError: (err: Error) =>
      toast.error("Falha ao salvar", { description: err.message }),
  });

  const handleSave = () => {
    const current = {
      situacao_processo: processo.situacao_processo,
      usuario_responsavel: processo.usuario_responsavel ?? "",
      polo: processo.polo ?? "",
      materia: processo.materia ?? "",
      risco_prob_perda: processo.risco_prob_perda ?? "",
    };
    const changes: Record<string, string> = {};
    for (const k of Object.keys(draft) as Array<keyof typeof draft>) {
      if (draft[k] !== current[k]) {
        changes[k] = draft[k];
      }
    }
    if (Object.keys(changes).length === 0) {
      setEditing(false);
      return;
    }
    patchMutation.mutate({
      changes,
      motivo: "Edição manual via UI",
      previous: current,
    });
  };

  const isPatching = patchMutation.isPending;

  return (
    <div className="space-y-4 text-sm">
      <div className="flex justify-end gap-2">
        {!editing ? (
          <Button
            variant="outline"
            size="sm"
            onClick={() => setEditing(true)}
            disabled={isPatching}
          >
            <Pencil className="h-3 w-3 mr-2" /> Editar
          </Button>
        ) : (
          <>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setEditing(false);
                setDraft({
                  situacao_processo: processo.situacao_processo,
                  usuario_responsavel: processo.usuario_responsavel ?? "",
                  polo: processo.polo ?? "",
                  materia: processo.materia ?? "",
                  risco_prob_perda: processo.risco_prob_perda ?? "",
                });
              }}
              disabled={isPatching}
            >
              Cancelar
            </Button>
            <Button size="sm" onClick={handleSave} disabled={isPatching}>
              {isPatching ? (
                <Loader2 className="h-3 w-3 animate-spin mr-2" />
              ) : (
                <CheckCircle2 className="h-3 w-3 mr-2" />
              )}
              Salvar
            </Button>
          </>
        )}
      </div>

      <Section title="Identificação">
        <ReadField label="Cód AJUS" value={processo.cod_ajus} mono />
        <ReadField
          label="Nº Processo (CNJ)"
          value={processo.numero_processo_mascarado}
          mono
        />
        <ReadField label="Nº Pasta" value={processo.numero_pasta} />
        <ReadField label="Nº Interno" value={processo.numero_interno} />
        <ReadField label="Empresa" value={processo.empresa} />
      </Section>

      <Section title="Classificação">
        {editing ? (
          <EditField label="Situação">
            <Select
              value={draft.situacao_processo}
              onValueChange={(v) =>
                setDraft((d) => ({ ...d, situacao_processo: v }))
              }
            >
              <SelectTrigger className="h-8">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="Ativo">Ativo</SelectItem>
                <SelectItem value="Suspenso">Suspenso</SelectItem>
                <SelectItem value="Baixado">Baixado</SelectItem>
                <SelectItem value="Arquivado">Arquivado</SelectItem>
                <SelectItem value="Encerrado">Encerrado</SelectItem>
              </SelectContent>
            </Select>
          </EditField>
        ) : (
          <ReadField label="Situação" value={processo.situacao_processo} />
        )}
        {editing ? (
          <EditField label="Polo">
            <Select
              value={draft.polo}
              onValueChange={(v) => setDraft((d) => ({ ...d, polo: v }))}
            >
              <SelectTrigger className="h-8">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="Ativo">Ativo</SelectItem>
                <SelectItem value="Passivo">Passivo</SelectItem>
              </SelectContent>
            </Select>
          </EditField>
        ) : (
          <ReadField label="Polo" value={processo.polo} />
        )}
        {editing ? (
          <EditField label="Matéria">
            <Input
              value={draft.materia}
              onChange={(e) =>
                setDraft((d) => ({ ...d, materia: e.target.value }))
              }
              className="h-8"
            />
          </EditField>
        ) : (
          <ReadField label="Matéria" value={processo.materia} />
        )}
        {editing ? (
          <EditField label="Risco/Prob. perda">
            <Input
              value={draft.risco_prob_perda}
              onChange={(e) =>
                setDraft((d) => ({ ...d, risco_prob_perda: e.target.value }))
              }
              className="h-8"
            />
          </EditField>
        ) : (
          <ReadField label="Risco/Prob. perda" value={processo.risco_prob_perda} />
        )}
        <ReadField label="Tipo de ação" value={processo.tipo_acao} />
        <ReadField label="Natureza" value={processo.natureza} />
      </Section>

      <Section title="Localização">
        <ReadField label="UF" value={processo.uf} />
        <ReadField label="Comarca" value={processo.comarca} />
        <ReadField label="Foro" value={processo.foro} />
        <ReadField label="Nº Vara" value={processo.numero_vara} />
        <ReadField
          label="Processo virtual"
          value={
            processo.processo_virtual === null
              ? null
              : processo.processo_virtual
                ? "Sim"
                : "Não"
          }
        />
      </Section>

      <Section title="Responsabilidade">
        {editing ? (
          <EditField label="Usuário responsável">
            <Input
              value={draft.usuario_responsavel}
              onChange={(e) =>
                setDraft((d) => ({ ...d, usuario_responsavel: e.target.value }))
              }
              className="h-8"
            />
          </EditField>
        ) : (
          <ReadField
            label="Usuário responsável"
            value={processo.usuario_responsavel}
          />
        )}
        <ReadField label="Grupo responsável" value={processo.grupo_responsavel} />
        <ReadField
          label="Escritório responsável"
          value={processo.escritorio_responsavel}
        />
      </Section>

      <Section title="Valores">
        <ReadField label="Valor causa" value={fmtMoney(processo.valor_causa)} />
        <ReadField
          label="Prev. acordo"
          value={fmtMoney(processo.valor_prev_acordo)}
        />
        <ReadField label="Acordo" value={fmtMoney(processo.valor_acordo)} />
        <ReadField label="Discutido" value={fmtMoney(processo.valor_discutido)} />
        <ReadField label="Êxito" value={fmtMoney(processo.valor_exito)} />
        <ReadField
          label="Condenação"
          value={fmtMoney(processo.valor_condenacao)}
        />
        <ReadField
          label="Contingência"
          value={fmtMoney(processo.valor_contingencia)}
        />
      </Section>

      <Section title="Andamento">
        <ReadField label="Último andamento" value={processo.ult_andamento} />
        <ReadField
          label="Data último andamento"
          value={fmtBR(processo.data_ult_andamento)}
        />
        <ReadField
          label="Dias últ. atualização"
          value={processo.dias_ult_atualizacao}
        />
        <ReadField
          label="Distribuído em"
          value={fmtDataBR(processo.distribuido_em)}
        />
      </Section>

      <Section title="Partes">
        <div className="col-span-2">
          <div className="text-xs text-muted-foreground mb-1">Autores</div>
          <PartesList partes={processo.autores_json} />
        </div>
        <div className="col-span-2">
          <div className="text-xs text-muted-foreground mb-1">Réus</div>
          <PartesList partes={processo.reus_json} />
        </div>
      </Section>

      <Section title="Auditoria">
        <ReadField
          label="Primeiro visto (upload)"
          value={processo.first_seen_upload_id ?? "—"}
        />
        <ReadField
          label="Último visto (upload)"
          value={processo.last_seen_upload_id ?? "—"}
        />
        <ReadField
          label="Removido em (upload)"
          value={processo.removed_at_upload_id ?? "—"}
        />
        <ReadField
          label="Snapshot atual"
          value={processo.current_snapshot_id ?? "—"}
        />
        <ReadField label="Criado em" value={fmtBR(processo.created_at)} />
        <ReadField label="Atualizado em" value={fmtBR(processo.updated_at)} />
      </Section>
    </div>
  );
}

function HistoricoTab({ codAjus }: { codAjus: string }) {
  const histQ = useQuery({
    queryKey: ["base-processual-processo-historico", codAjus],
    queryFn: () => getProcessoHistorico(codAjus, { limit: 100 }),
  });
  const [selA, setSelA] = useState<number | null>(null);
  const [selB, setSelB] = useState<number | null>(null);

  const snapshots = histQ.data?.items ?? [];

  const snapA = useMemo(
    () => snapshots.find((s) => s.id === selA),
    [selA, snapshots],
  );
  const snapB = useMemo(
    () => snapshots.find((s) => s.id === selB),
    [selB, snapshots],
  );

  const diff = useMemo(() => {
    if (!snapA || !snapB) return null;
    return computeFieldDiff(snapA.payload_normalized, snapB.payload_normalized);
  }, [snapA, snapB]);

  if (histQ.isLoading) {
    return (
      <div className="py-8 flex items-center justify-center text-muted-foreground text-sm">
        <Loader2 className="h-4 w-4 animate-spin mr-2" /> Carregando...
      </div>
    );
  }
  if (snapshots.length === 0) {
    return (
      <div className="py-8 text-center text-muted-foreground text-sm">
        Sem snapshots ainda.
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="text-xs text-muted-foreground">
        Selecione 2 snapshots pra comparar (diff side-by-side dos campos
        significativos).
      </div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-10"></TableHead>
            <TableHead className="w-10"></TableHead>
            <TableHead>Capturado em</TableHead>
            <TableHead>Upload</TableHead>
            <TableHead>Hash</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {snapshots.map((s) => (
            <TableRow key={s.id}>
              <TableCell>
                <input
                  type="radio"
                  name="snap-a"
                  checked={selA === s.id}
                  onChange={() => setSelA(s.id)}
                />
              </TableCell>
              <TableCell>
                <input
                  type="radio"
                  name="snap-b"
                  checked={selB === s.id}
                  onChange={() => setSelB(s.id)}
                />
              </TableCell>
              <TableCell className="font-mono text-xs">
                {fmtBR(s.captured_at)}
              </TableCell>
              <TableCell className="font-mono text-xs">#{s.upload_id}</TableCell>
              <TableCell className="font-mono text-[10px] text-muted-foreground">
                {s.diff_hash.slice(0, 12)}…
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      {snapA && snapB && diff && (
        <div className="border rounded-md p-3 bg-muted/30">
          <div className="flex items-center gap-2 text-sm font-medium mb-2">
            <ArrowRightLeft className="h-4 w-4" /> Diff
            <span className="text-xs text-muted-foreground font-normal">
              ({diff.length} campo{diff.length !== 1 ? "s" : ""} diferente
              {diff.length !== 1 ? "s" : ""})
            </span>
          </div>
          {diff.length === 0 ? (
            <div className="text-xs text-muted-foreground">
              Sem diferenças nos campos significativos.
            </div>
          ) : (
            <table className="w-full text-xs">
              <thead>
                <tr className="text-muted-foreground">
                  <th className="text-left w-1/4 py-1">Campo</th>
                  <th className="text-left w-3/8 py-1">
                    {fmtBR(snapA.captured_at)}
                  </th>
                  <th className="text-left w-3/8 py-1">
                    {fmtBR(snapB.captured_at)}
                  </th>
                </tr>
              </thead>
              <tbody>
                {diff.map((d) => (
                  <tr key={d.field} className="border-t border-border/40">
                    <td className="py-1 pr-2 text-muted-foreground">
                      {fieldLabel(d.field)}
                    </td>
                    <td className="py-1 pr-2 text-red-600 dark:text-red-400 font-mono">
                      {fmtFieldValue(d.a)}
                    </td>
                    <td className="py-1 text-emerald-600 dark:text-emerald-400 font-mono">
                      {fmtFieldValue(d.b)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}

function EventosTab({ codAjus }: { codAjus: string }) {
  const evtsQ = useQuery({
    queryKey: ["base-processual-processo-eventos", codAjus],
    queryFn: () => getProcessoEventos(codAjus, { limit: 100 }),
  });
  if (evtsQ.isLoading) {
    return (
      <div className="py-8 flex items-center justify-center text-muted-foreground text-sm">
        <Loader2 className="h-4 w-4 animate-spin mr-2" /> Carregando...
      </div>
    );
  }
  const items = evtsQ.data?.items ?? [];
  if (items.length === 0) {
    return (
      <div className="py-8 text-center text-muted-foreground text-sm">
        Sem eventos ainda.
      </div>
    );
  }
  return (
    <ul className="space-y-3">
      {items.map((e) => (
        <li
          key={e.id}
          className="border-l-2 pl-3 py-1"
          style={{
            borderLeftColor:
              e.tipo_evento === "ENTROU"
                ? "rgb(16 185 129)"
                : e.tipo_evento === "SAIU"
                  ? "rgb(239 68 68)"
                  : "rgb(245 158 11)",
          }}
        >
          <div className="flex items-center gap-2 text-xs">
            <Badge
              variant={
                e.tipo_evento === "ENTROU"
                  ? "default"
                  : e.tipo_evento === "SAIU"
                    ? "destructive"
                    : "secondary"
              }
            >
              {e.tipo_evento}
            </Badge>
            <span className="text-muted-foreground">{fmtBR(e.created_at)}</span>
            <span className="text-muted-foreground">· upload #{e.upload_id}</span>
          </div>
          {e.changed_fields && Object.keys(e.changed_fields).length > 0 && (
            <ul className="mt-1 text-xs space-y-0.5">
              {Object.entries(e.changed_fields).map(([k, v]) => {
                const val = v as { de?: unknown; para?: unknown } | unknown;
                const hasDePara =
                  val &&
                  typeof val === "object" &&
                  "de" in (val as object) &&
                  "para" in (val as object);
                return (
                  <li key={k} className="font-mono">
                    <span className="text-muted-foreground">
                      {fieldLabel(k)}:
                    </span>{" "}
                    {hasDePara ? (
                      <>
                        <span className="text-red-600 dark:text-red-400">
                          {fmtFieldValue((val as { de: unknown }).de)}
                        </span>
                        <span className="text-muted-foreground"> → </span>
                        <span className="text-emerald-600 dark:text-emerald-400">
                          {fmtFieldValue((val as { para: unknown }).para)}
                        </span>
                      </>
                    ) : (
                      <span>{fmtFieldValue(val)}</span>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </li>
      ))}
    </ul>
  );
}

// --- Helpers UI internos ---

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-md border p-3">
      <h4 className="text-xs uppercase tracking-wide text-muted-foreground mb-2">
        {title}
      </h4>
      <div className="grid grid-cols-2 gap-x-4 gap-y-2">{children}</div>
    </div>
  );
}

function ReadField({
  label,
  value,
  mono,
}: {
  label: string;
  value: string | number | null | undefined;
  mono?: boolean;
}) {
  return (
    <div>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={cn("truncate", mono && "font-mono text-sm")}>
        {value ?? "—"}
      </div>
    </div>
  );
}

function EditField({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="text-xs text-muted-foreground mb-0.5">{label}</div>
      {children}
    </div>
  );
}

function PartesList({
  partes,
}: {
  partes: Array<{ nome: string | null; documento: string | null }> | null;
}) {
  if (!partes || partes.length === 0) {
    return <div className="text-sm text-muted-foreground">—</div>;
  }
  return (
    <ul className="space-y-1">
      {partes.map((p, i) => (
        <li key={i} className="text-sm">
          <span>{p.nome ?? "—"}</span>
          {p.documento && (
            <span className="text-muted-foreground font-mono ml-2">
              ({p.documento})
            </span>
          )}
        </li>
      ))}
    </ul>
  );
}

// --- Diff helper ---

const _DIFF_FIELDS = [
  "situacao_processo",
  "polo",
  "materia",
  "risco_prob_perda",
  "tipo_acao",
  "natureza",
  "numero_vara",
  "foro",
  "comarca",
  "uf",
  "grupo_responsavel",
  "usuario_responsavel",
  "escritorio_responsavel",
  "valor_causa",
  "valor_prev_acordo",
  "valor_acordo",
  "valor_discutido",
  "valor_exito",
  "valor_condenacao",
  "valor_contingencia",
  "ult_andamento",
  "autores_json",
  "reus_json",
  "numero_processo",
  "numero_pasta",
  "numero_interno",
  "numero_contrato",
  "acao_principal",
  "processo_virtual",
  "justica_honorario",
  "distribuido_em",
];

function computeFieldDiff(
  a: Record<string, unknown>,
  b: Record<string, unknown>,
): Array<{ field: string; a: unknown; b: unknown }> {
  const result: Array<{ field: string; a: unknown; b: unknown }> = [];
  for (const f of _DIFF_FIELDS) {
    const va = a?.[f] ?? null;
    const vb = b?.[f] ?? null;
    if (JSON.stringify(va) !== JSON.stringify(vb)) {
      result.push({ field: f, a: va, b: vb });
    }
  }
  return result;
}
