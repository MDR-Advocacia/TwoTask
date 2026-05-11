/**
 * EventosTab — Chunk 4.
 *
 * Tabela cross-upload de eventos (auditoria geral). Filtros por tipo,
 * upload_id, cod_ajus, periodo + busca. Click numa linha abre o
 * ProcessoDrawer focado no processo daquele evento (sub-tab Eventos
 * pre-selecionada). Cap=100 por pagina.
 *
 * Drag-to-multiselect (Linear style) fica pra Chunk 4.5 polish — v1
 * usa checkboxes simples se precisar de multi-select no futuro.
 */

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Calendar,
  Eye,
  Filter,
  Loader2,
  RotateCcw,
  Search,
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
  type EventosCrossFilters,
  listEventosCrossUpload,
} from "@/lib/api-base-processual";

import { ProcessoDrawer } from "./ProcessoDrawer";

const PAGE_SIZE = 50;

const TIPOS = [
  { value: "__all__", label: "Todos" },
  { value: "ENTROU", label: "Entrou" },
  { value: "SAIU", label: "Saiu" },
  { value: "ATUALIZADO", label: "Atualizado (auto)" },
  { value: "ATUALIZADO_MANUAL", label: "Atualizado manual" },
];

function fmtBR(s: string | null | undefined): string {
  if (!s) return "—";
  try {
    return new Date(s).toLocaleString("pt-BR", { timeZone: "America/Sao_Paulo" });
  } catch {
    return s;
  }
}

function tipoBadge(t: string): JSX.Element {
  const cls = {
    ENTROU: "bg-emerald-100 text-emerald-900 dark:bg-emerald-900/30 dark:text-emerald-300",
    SAIU: "bg-red-100 text-red-900 dark:bg-red-900/30 dark:text-red-300",
    ATUALIZADO: "bg-amber-100 text-amber-900 dark:bg-amber-900/30 dark:text-amber-300",
    ATUALIZADO_MANUAL: "bg-purple-100 text-purple-900 dark:bg-purple-900/30 dark:text-purple-300",
  }[t] ?? "bg-zinc-100 text-zinc-800";
  return <Badge className={`${cls} font-normal`}>{t}</Badge>;
}

export function EventosTab() {
  const [tipo, setTipo] = useState("__all__");
  const [searchInput, setSearchInput] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [uploadId, setUploadId] = useState("");
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [page, setPage] = useState(0);
  const [openCod, setOpenCod] = useState<string | null>(null);

  useEffect(() => {
    const t = setTimeout(() => {
      setDebouncedSearch(searchInput.trim());
      setPage(0);
    }, 350);
    return () => clearTimeout(t);
  }, [searchInput]);

  const filters: EventosCrossFilters = useMemo(() => {
    const f: EventosCrossFilters = {
      limit: PAGE_SIZE,
      offset: page * PAGE_SIZE,
    };
    if (tipo !== "__all__") f.tipo_evento = tipo;
    if (debouncedSearch) f.search = debouncedSearch;
    if (uploadId) f.upload_id = Number(uploadId) || undefined;
    if (fromDate) f.from_date = fromDate;
    if (toDate) f.to_date = toDate;
    return f;
  }, [tipo, debouncedSearch, uploadId, fromDate, toDate, page]);

  const evtsQ = useQuery({
    queryKey: ["base-processual-eventos", filters],
    queryFn: () => listEventosCrossUpload(filters),
  });

  const data = evtsQ.data;
  const total = data?.total ?? 0;
  const items = data?.items ?? [];
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const from = total === 0 ? 0 : page * PAGE_SIZE + 1;
  const to = Math.min(total, (page + 1) * PAGE_SIZE);

  const resetFilters = () => {
    setTipo("__all__");
    setSearchInput("");
    setDebouncedSearch("");
    setUploadId("");
    setFromDate("");
    setToDate("");
    setPage(0);
  };

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Filter className="h-4 w-4" /> Filtros
          </CardTitle>
          <CardDescription>
            Auditoria cross-upload. Veja exatamente o que mudou na base, quando
            e por qual upload (incluindo overrides manuais e bulk updates).
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-3">
            <div>
              <Label className="text-xs">Tipo</Label>
              <Select value={tipo} onValueChange={(v) => { setTipo(v); setPage(0); }}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {TIPOS.map((t) => (
                    <SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="text-xs">Cód AJUS (busca)</Label>
              <div className="relative">
                <Search className="h-4 w-4 absolute left-2 top-1/2 -translate-y-1/2 text-muted-foreground" />
                <Input
                  value={searchInput}
                  onChange={(e) => setSearchInput(e.target.value)}
                  placeholder="Ex.: 99580"
                  className="pl-8"
                />
              </div>
            </div>
            <div>
              <Label className="text-xs">Upload ID</Label>
              <Input
                type="number"
                value={uploadId}
                onChange={(e) => { setUploadId(e.target.value); setPage(0); }}
                placeholder="Ex.: 10"
              />
            </div>
            <div>
              <Label className="text-xs">De</Label>
              <Input
                type="date"
                value={fromDate}
                onChange={(e) => { setFromDate(e.target.value); setPage(0); }}
              />
            </div>
            <div>
              <Label className="text-xs">Até</Label>
              <Input
                type="date"
                value={toDate}
                onChange={(e) => { setToDate(e.target.value); setPage(0); }}
              />
            </div>
          </div>
          <div className="flex justify-end mt-3">
            <Button variant="ghost" size="sm" onClick={resetFilters}>
              <RotateCcw className="h-3 w-3 mr-2" /> Limpar filtros
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Eventos</CardTitle>
          <CardDescription>
            {evtsQ.isLoading
              ? "Carregando..."
              : `${total.toLocaleString("pt-BR")} evento(s) · Pág. ${page + 1} de ${totalPages}`}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {evtsQ.isLoading ? (
            <div className="py-8 text-center text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin mx-auto" />
            </div>
          ) : evtsQ.isError ? (
            <div className="py-8 text-center text-red-600 text-sm">
              Erro: {(evtsQ.error as Error).message}
            </div>
          ) : items.length === 0 ? (
            <div className="py-8 text-center text-muted-foreground text-sm">
              Nenhum evento bate com esses filtros.
            </div>
          ) : (
            <>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-40">Quando</TableHead>
                    <TableHead className="w-32">Tipo</TableHead>
                    <TableHead className="w-24">Cód AJUS</TableHead>
                    <TableHead className="w-20">Upload</TableHead>
                    <TableHead>Mudanças</TableHead>
                    <TableHead className="w-10"></TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {items.map((e) => (
                    <TableRow
                      key={e.id}
                      className="cursor-pointer hover:bg-muted/50"
                      onClick={() => setOpenCod(e.cod_ajus)}
                    >
                      <TableCell className="font-mono text-xs">
                        {fmtBR(e.created_at)}
                      </TableCell>
                      <TableCell>{tipoBadge(e.tipo_evento)}</TableCell>
                      <TableCell className="font-mono text-xs">
                        {e.cod_ajus}
                      </TableCell>
                      <TableCell className="font-mono text-xs text-muted-foreground">
                        #{e.upload_id}
                      </TableCell>
                      <TableCell className="text-xs">
                        <ChangedFieldsCell changed={e.changed_fields} />
                      </TableCell>
                      <TableCell>
                        <Eye className="h-4 w-4 text-muted-foreground" />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              <div className="flex items-center justify-between mt-4 text-sm">
                <span className="text-muted-foreground">
                  {from}–{to} de {total.toLocaleString("pt-BR")}
                </span>
                <div className="flex items-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setPage((p) => Math.max(0, p - 1))}
                    disabled={page === 0}
                  >
                    Anterior
                  </Button>
                  <span className="text-muted-foreground">
                    Pág. {page + 1} de {totalPages}
                  </span>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() =>
                      setPage((p) => (p + 1 < totalPages ? p + 1 : p))
                    }
                    disabled={page + 1 >= totalPages}
                  >
                    Próxima
                  </Button>
                </div>
              </div>
            </>
          )}
        </CardContent>
      </Card>

      <ProcessoDrawer codAjus={openCod} onClose={() => setOpenCod(null)} />
    </div>
  );
}

function ChangedFieldsCell({
  changed,
}: {
  changed: Record<string, unknown> | null;
}) {
  if (!changed || Object.keys(changed).length === 0) {
    return <span className="text-muted-foreground">—</span>;
  }
  const entries = Object.entries(changed).slice(0, 3);
  return (
    <div className="space-y-0.5">
      {entries.map(([k, v]) => {
        const hasDePara =
          v &&
          typeof v === "object" &&
          "de" in (v as object) &&
          "para" in (v as object);
        const de = hasDePara ? (v as { de: unknown }).de : null;
        const para = hasDePara ? (v as { para: unknown }).para : null;
        return (
          <div key={k} className="font-mono truncate">
            <span className="text-muted-foreground">{k}:</span>{" "}
            {hasDePara ? (
              <>
                <span className="text-red-600 dark:text-red-400">
                  {fmtV(de)}
                </span>
                <span className="text-muted-foreground"> → </span>
                <span className="text-emerald-600 dark:text-emerald-400">
                  {fmtV(para)}
                </span>
              </>
            ) : (
              <span>{fmtV(v)}</span>
            )}
          </div>
        );
      })}
      {Object.keys(changed).length > 3 && (
        <div className="text-muted-foreground text-[10px]">
          +{Object.keys(changed).length - 3} campo(s)
        </div>
      )}
    </div>
  );
}

function fmtV(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "boolean") return v ? "Sim" : "Não";
  if (Array.isArray(v)) {
    return v
      .map((x) =>
        x && typeof x === "object" && "nome" in x
          ? (x as { nome?: string }).nome ?? ""
          : String(x),
      )
      .filter(Boolean)
      .join("; ");
  }
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}
