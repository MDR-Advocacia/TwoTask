/**
 * RelatoriosTab — Chunk 5.
 *
 * UX: 6 cards (1 por template) — operador clica num card pra selecionar,
 * forma de params adapta dinamicamente, botao "Gerar" dispara POST /exports
 * (sincrono no v1, retorna PRONTO/FALHOU direto). Historico abaixo lista
 * os ultimos 20 relatorios com botao download por linha.
 *
 * 6 templates implementados no backend:
 * - movimentacao_semanal: ultimos 7d (default) ou range custom
 * - carteira_responsavel: agrupa por usuario_responsavel + somatorias
 * - sumicos_periodo: REMOVIDO_NA_BASE no periodo (default mes corrente)
 * - variacao_valores: valor_causa mudou ≥ X% historico
 * - carteira_uf_comarca: pivot UF × comarca + agregado UF
 * - snapshot_completo: 1 linha por processo ATIVO (igual planilha)
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  AlertTriangle,
  CheckCircle2,
  Download,
  FileSpreadsheet,
  Loader2,
  TrendingUp,
  Users,
  XCircle,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

import {
  type ExportOut,
  type ExportTemplate,
  createExport,
  downloadExportUrl,
  downloadFileWithAuth,
  listExports,
} from "@/lib/api-base-processual";
import { cn } from "@/lib/utils";

type TemplateMeta = {
  key: ExportTemplate;
  label: string;
  description: string;
  icon: React.ReactNode;
  fields: Array<
    | { kind: "date"; name: string; label: string; defaultValue?: string }
    | { kind: "number"; name: string; label: string; defaultValue?: number; min?: number; max?: number; step?: number }
    | { kind: "text"; name: string; label: string; defaultValue?: string; placeholder?: string }
    | { kind: "select"; name: string; label: string; options: Array<{ value: string; label: string }>; defaultValue?: string }
  >;
};

function isoDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function today(): string {
  return isoDate(new Date());
}

function daysAgo(n: number): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() - n);
  return isoDate(d);
}

function firstOfMonth(): string {
  const d = new Date();
  d.setUTCDate(1);
  return isoDate(d);
}

const TEMPLATES: TemplateMeta[] = [
  {
    key: "movimentacao_semanal",
    label: "Movimentação semanal",
    description: "Entradas/saídas/atualizações por dia + listas detalhadas.",
    icon: <TrendingUp className="h-5 w-5" />,
    fields: [
      { kind: "date", name: "from_date", label: "De", defaultValue: daysAgo(6) },
      { kind: "date", name: "to_date", label: "Até", defaultValue: today() },
    ],
  },
  {
    key: "carteira_responsavel",
    label: "Carteira por responsável",
    description: "Agrupa carteira ATIVA por usuario_responsavel com totalizadores.",
    icon: <Users className="h-5 w-5" />,
    fields: [
      { kind: "text", name: "empresa", label: "Empresa (opcional)", placeholder: "Ex.: banco_master" },
    ],
  },
  {
    key: "sumicos_periodo",
    label: "Sumiços do período",
    description: "Processos REMOVIDOs no período. Munição pra cobrar o cliente.",
    icon: <XCircle className="h-5 w-5" />,
    fields: [
      { kind: "date", name: "from_date", label: "De", defaultValue: firstOfMonth() },
      { kind: "date", name: "to_date", label: "Até", defaultValue: today() },
    ],
  },
  {
    key: "variacao_valores",
    label: "Variação de valores",
    description: "Processos com mudança de valor_causa ≥ X% (comparando 1º snapshot vs atual).",
    icon: <TrendingUp className="h-5 w-5" />,
    fields: [
      { kind: "number", name: "threshold_pct", label: "Mudança ≥ (%)", defaultValue: 50, min: 1, max: 1000, step: 1 },
    ],
  },
  {
    key: "carteira_uf_comarca",
    label: "Carteira UF/Comarca",
    description: "Pivot espacial: UF × Comarca detalhado + UF agregado.",
    icon: <FileSpreadsheet className="h-5 w-5" />,
    fields: [
      { kind: "text", name: "empresa", label: "Empresa (opcional)", placeholder: "Ex.: banco_master" },
    ],
  },
  {
    key: "snapshot_completo",
    label: "Snapshot completo",
    description: "1 linha por processo (igual planilha original do L1). Pesado pra >5k processos.",
    icon: <FileSpreadsheet className="h-5 w-5" />,
    fields: [
      {
        kind: "select",
        name: "presenca_status",
        label: "Presença",
        defaultValue: "ATIVO_NA_BASE",
        options: [
          { value: "ATIVO_NA_BASE", label: "Apenas ativos" },
          { value: "REMOVIDO_NA_BASE", label: "Apenas removidos" },
          { value: "ambos", label: "Ativos + removidos" },
        ],
      },
    ],
  },
];

function fmtBR(s: string | null): string {
  if (!s) return "—";
  try {
    return new Date(s).toLocaleString("pt-BR", { timeZone: "America/Sao_Paulo" });
  } catch {
    return s;
  }
}

function fmtBytes(n: number | null): string {
  if (n === null || n === undefined) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function statusBadge(s: string): JSX.Element {
  const map: Record<string, string> = {
    PRONTO: "bg-emerald-100 text-emerald-900 dark:bg-emerald-900/30 dark:text-emerald-300",
    PROCESSANDO: "bg-amber-100 text-amber-900 dark:bg-amber-900/30 dark:text-amber-300",
    PENDENTE: "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300",
    FALHOU: "bg-red-100 text-red-900 dark:bg-red-900/30 dark:text-red-300",
  };
  return <Badge className={`${map[s] ?? "bg-zinc-100 text-zinc-800"} font-normal`}>{s}</Badge>;
}

export function RelatoriosTab() {
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<ExportTemplate>("movimentacao_semanal");
  const [params, setParams] = useState<Record<string, string | number>>({});

  const selectedTemplate = TEMPLATES.find((t) => t.key === selected)!;

  // Reset params quando trocar de template
  const handleSelectTemplate = (key: ExportTemplate) => {
    setSelected(key);
    const tpl = TEMPLATES.find((t) => t.key === key);
    if (!tpl) return;
    const defaults: Record<string, string | number> = {};
    tpl.fields.forEach((f) => {
      if (f.defaultValue !== undefined) {
        defaults[f.name] = f.defaultValue as string | number;
      }
    });
    setParams(defaults);
  };

  // Inicializa defaults na 1a renderizacao
  if (Object.keys(params).length === 0) {
    const defaults: Record<string, string | number> = {};
    selectedTemplate.fields.forEach((f) => {
      if (f.defaultValue !== undefined) defaults[f.name] = f.defaultValue as string | number;
    });
    if (Object.keys(defaults).length > 0) {
      // setState durante render — useState com lazy init resolveria mais limpo,
      // mas pra simplicidade do componente fica assim.
      setTimeout(() => setParams(defaults), 0);
    }
  }

  const historyQ = useQuery({
    queryKey: ["base-processual-exports"],
    queryFn: () => listExports({ limit: 20 }),
    refetchInterval: (data) => {
      const items = data?.state?.data?.items ?? [];
      const hasInFlight = items.some(
        (e) => e.status === "PROCESSANDO" || e.status === "PENDENTE",
      );
      return hasInFlight ? 3000 : false;
    },
  });

  const createMut = useMutation({
    mutationFn: createExport,
    onSuccess: (result) => {
      if (result.status === "FALHOU") {
        toast.error("Geração falhou", {
          description: result.error_message ?? "Erro desconhecido.",
        });
      } else {
        toast.success(`Relatório gerado: ${result.total_rows} linha(s)`, {
          description: `${selectedTemplate.label} · ${fmtBytes(result.file_bytes)}`,
          duration: 10_000,
          action: {
            label: "Baixar",
            onClick: () => {
              const filename = `base-processual-${result.template_name}-${result.id}.xlsx`;
              downloadFileWithAuth(downloadExportUrl(result.id), filename).catch(
                (err) => toast.error("Falha no download", { description: err.message }),
              );
            },
          },
        });
      }
      queryClient.invalidateQueries({ queryKey: ["base-processual-exports"] });
    },
    onError: (err: Error) =>
      toast.error("Falha", { description: err.message }),
  });

  const handleGenerate = () => {
    const cleanParams: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== "" && v !== null) {
        cleanParams[k] = v;
      }
    }
    createMut.mutate({ template: selected, params: cleanParams });
  };

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Escolha o relatório</CardTitle>
          <CardDescription>
            6 templates pré-prontos. Cada um aceita parâmetros próprios — sem
            código, só preencher e gerar XLSX.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {TEMPLATES.map((t) => (
              <button
                key={t.key}
                type="button"
                onClick={() => handleSelectTemplate(t.key)}
                className={cn(
                  "text-left rounded-lg border p-3 transition cursor-pointer",
                  "hover:border-primary/60 hover:bg-muted/30",
                  selected === t.key
                    ? "border-primary ring-2 ring-primary/30 bg-primary/5"
                    : "border-muted-foreground/20",
                )}
              >
                <div className="flex items-start gap-2">
                  <div className="text-muted-foreground mt-0.5">{t.icon}</div>
                  <div>
                    <div className="font-medium text-sm">{t.label}</div>
                    <div className="text-xs text-muted-foreground mt-1">
                      {t.description}
                    </div>
                  </div>
                </div>
              </button>
            ))}
          </div>

          {selectedTemplate.fields.length > 0 && (
            <div className="mt-4 pt-4 border-t">
              <div className="text-sm font-medium mb-2">Parâmetros</div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {selectedTemplate.fields.map((f) => (
                  <div key={f.name}>
                    <Label className="text-xs">{f.label}</Label>
                    {f.kind === "date" && (
                      <Input
                        type="date"
                        value={(params[f.name] as string) ?? ""}
                        onChange={(e) =>
                          setParams((p) => ({ ...p, [f.name]: e.target.value }))
                        }
                      />
                    )}
                    {f.kind === "number" && (
                      <Input
                        type="number"
                        min={f.min}
                        max={f.max}
                        step={f.step}
                        value={(params[f.name] as number) ?? ""}
                        onChange={(e) =>
                          setParams((p) => ({
                            ...p,
                            [f.name]: Number(e.target.value),
                          }))
                        }
                      />
                    )}
                    {f.kind === "text" && (
                      <Input
                        type="text"
                        placeholder={f.placeholder}
                        value={(params[f.name] as string) ?? ""}
                        onChange={(e) =>
                          setParams((p) => ({ ...p, [f.name]: e.target.value }))
                        }
                      />
                    )}
                    {f.kind === "select" && (
                      <Select
                        value={(params[f.name] as string) ?? ""}
                        onValueChange={(v) =>
                          setParams((p) => ({ ...p, [f.name]: v }))
                        }
                      >
                        <SelectTrigger className="h-9">
                          <SelectValue placeholder="Selecione..." />
                        </SelectTrigger>
                        <SelectContent>
                          {f.options.map((o) => (
                            <SelectItem key={o.value} value={o.value}>
                              {o.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="flex justify-end mt-4">
            <Button onClick={handleGenerate} disabled={createMut.isPending}>
              {createMut.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin mr-2" /> Gerando...
                </>
              ) : (
                <>
                  <CheckCircle2 className="h-4 w-4 mr-2" /> Gerar relatório
                </>
              )}
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Histórico</CardTitle>
          <CardDescription>
            Últimos 20 relatórios. Baixe quando o status for PRONTO. Relatórios
            expiram após 90 dias.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {historyQ.isLoading ? (
            <div className="py-6 text-center text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin mx-auto" />
            </div>
          ) : (historyQ.data?.items.length ?? 0) === 0 ? (
            <div className="py-6 text-center text-muted-foreground text-sm">
              Nenhum relatório gerado ainda.
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-16">#</TableHead>
                  <TableHead>Template</TableHead>
                  <TableHead>Quando</TableHead>
                  <TableHead className="text-right">Linhas</TableHead>
                  <TableHead className="text-right">Tamanho</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="w-24"></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(historyQ.data?.items ?? []).map((e) => (
                  <ExportRow key={e.id} e={e} />
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function ExportRow({ e }: { e: ExportOut }) {
  return (
    <TableRow>
      <TableCell className="font-mono text-xs">#{e.id}</TableCell>
      <TableCell>
        <div className="text-sm">{e.template_name}</div>
        {e.error_message && (
          <div className="text-xs text-red-600 dark:text-red-400 mt-1 flex items-start gap-1">
            <AlertTriangle className="h-3 w-3 mt-[2px] shrink-0" />
            <span className="line-clamp-2">{e.error_message}</span>
          </div>
        )}
      </TableCell>
      <TableCell className="text-xs text-muted-foreground">
        {fmtBR(e.requested_at)}
      </TableCell>
      <TableCell className="text-right tabular-nums">
        {e.total_rows?.toLocaleString("pt-BR") ?? "—"}
      </TableCell>
      <TableCell className="text-right text-xs text-muted-foreground tabular-nums">
        {fmtBytes(e.file_bytes)}
      </TableCell>
      <TableCell>{statusBadge(e.status)}</TableCell>
      <TableCell>
        {e.status === "PRONTO" && e.file_path && (
          <Button
            variant="ghost"
            size="sm"
            title="Baixar XLSX"
            onClick={() => {
              const filename = `base-processual-${e.template_name}-${e.id}.xlsx`;
              downloadFileWithAuth(downloadExportUrl(e.id), filename).catch(
                (err) => toast.error("Falha no download", { description: err.message }),
              );
            }}
          >
            <Download className="h-4 w-4" />
          </Button>
        )}
      </TableCell>
    </TableRow>
  );
}
