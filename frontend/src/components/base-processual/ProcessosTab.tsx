/**
 * ProcessosTab — Chunk 3.
 *
 * Tabela paginada de processos da Base Processual, com filtros principais
 * (presenca, UF, polo, situacao, responsavel) + busca livre + ordenacao.
 * Clicar numa linha abre o ProcessoDrawer com 3 sub-tabs.
 *
 * Defaults: presenca=ATIVO_NA_BASE, sort=ult_andamento_desc, 50/pag.
 * Filtros tem state local + debounce de 350ms na busca.
 */

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  BookmarkPlus,
  Eye,
  Filter,
  Layers,
  Loader2,
  Pin,
  PinOff,
  RotateCcw,
  Search,
  Trash2,
} from "lucide-react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useSavedViews } from "@/lib/use-saved-views";

import { BulkUpdateDialog } from "./BulkUpdateDialog";

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
  type ProcessosFilters,
  listProcessos,
} from "@/lib/api-base-processual";
import { cn } from "@/lib/utils";

import { ProcessoDrawer } from "./ProcessoDrawer";

const PAGE_SIZE_OPTIONS = [25, 50, 100];
const UFs = [
  "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS",
  "MT", "PA", "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC",
  "SE", "SP", "TO",
];

const SITUACOES = ["Ativo", "Suspenso", "Baixado", "Arquivado", "Encerrado"];
const POLOS = ["Ativo", "Passivo"];
const PRESENCAS = [
  { value: "ATIVO_NA_BASE", label: "Ativos na base" },
  { value: "REMOVIDO_NA_BASE", label: "Removidos" },
];

const SORT_OPTIONS = [
  { value: "ult_andamento_desc", label: "Últ. andamento (mais recente)" },
  { value: "ult_andamento_asc", label: "Últ. andamento (mais antigo)" },
  { value: "cod_ajus_asc", label: "Cód AJUS ↑" },
  { value: "cod_ajus_desc", label: "Cód AJUS ↓" },
  { value: "valor_causa_desc", label: "Valor causa (maior)" },
  { value: "valor_causa_asc", label: "Valor causa (menor)" },
  { value: "distribuido_desc", label: "Distribuído (mais recente)" },
  { value: "updated_desc", label: "Atualizado em (mais recente)" },
];

function fmtBR(s: string | null | undefined): string {
  if (!s) return "—";
  try {
    return new Date(s).toLocaleDateString("pt-BR", {
      timeZone: "America/Sao_Paulo",
    });
  } catch {
    return s;
  }
}

function fmtMoney(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString("pt-BR", {
    style: "currency",
    currency: "BRL",
  });
}

function PresencaBadge({ status }: { status: string }) {
  return status === "ATIVO_NA_BASE" ? (
    <Badge className="bg-emerald-100 text-emerald-900 dark:bg-emerald-900/30 dark:text-emerald-300 font-normal">
      Ativo
    </Badge>
  ) : (
    <Badge className="bg-red-100 text-red-900 dark:bg-red-900/30 dark:text-red-300 font-normal">
      Removido
    </Badge>
  );
}

type SavedViewFilters = {
  searchInput: string;
  presencaStatus: string;
  uf: string;
  polo: string;
  situacao: string;
  usuarioResp: string;
  sortBy: string;
};

export function ProcessosTab() {
  const [searchInput, setSearchInput] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [presencaStatus, setPresencaStatus] = useState<string>("ATIVO_NA_BASE");
  const [uf, setUf] = useState<string>("__all__");
  const [polo, setPolo] = useState<string>("__all__");
  const [situacao, setSituacao] = useState<string>("__all__");
  const [usuarioResp, setUsuarioResp] = useState<string>("");
  const [debouncedUsuario, setDebouncedUsuario] = useState("");
  const [sortBy, setSortBy] = useState<string>("ult_andamento_desc");
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(50);
  const [openCodAjus, setOpenCodAjus] = useState<string | null>(null);
  const [bulkOpen, setBulkOpen] = useState(false);

  const savedViews = useSavedViews<SavedViewFilters>("processos");

  // Debounce search (350ms)
  useEffect(() => {
    const t = setTimeout(() => {
      setDebouncedSearch(searchInput.trim());
      setPage(0);
    }, 350);
    return () => clearTimeout(t);
  }, [searchInput]);

  useEffect(() => {
    const t = setTimeout(() => {
      setDebouncedUsuario(usuarioResp.trim());
      setPage(0);
    }, 350);
    return () => clearTimeout(t);
  }, [usuarioResp]);

  const filters: ProcessosFilters = {
    limit: pageSize,
    offset: page * pageSize,
    sort_by: sortBy,
  };
  if (presencaStatus) filters.presenca_status = presencaStatus;
  if (uf !== "__all__") filters.uf = uf;
  if (polo !== "__all__") filters.polo = polo;
  if (situacao !== "__all__") filters.situacao_processo = situacao;
  if (debouncedUsuario) filters.usuario_responsavel = debouncedUsuario;
  if (debouncedSearch) filters.search = debouncedSearch;

  const processosQ = useQuery({
    queryKey: ["base-processual-processos", filters],
    queryFn: () => listProcessos(filters),
  });

  const data = processosQ.data;
  const total = data?.total ?? 0;
  const items = data?.items ?? [];
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const from = total === 0 ? 0 : page * pageSize + 1;
  const to = Math.min(total, (page + 1) * pageSize);

  const resetFilters = () => {
    setSearchInput("");
    setDebouncedSearch("");
    setPresencaStatus("ATIVO_NA_BASE");
    setUf("__all__");
    setPolo("__all__");
    setSituacao("__all__");
    setUsuarioResp("");
    setDebouncedUsuario("");
    setSortBy("ult_andamento_desc");
    setPage(0);
  };

  const loadSavedView = (vf: SavedViewFilters) => {
    setSearchInput(vf.searchInput);
    setDebouncedSearch(vf.searchInput);
    setPresencaStatus(vf.presencaStatus);
    setUf(vf.uf);
    setPolo(vf.polo);
    setSituacao(vf.situacao);
    setUsuarioResp(vf.usuarioResp);
    setDebouncedUsuario(vf.usuarioResp);
    setSortBy(vf.sortBy);
    setPage(0);
  };

  const handleSaveView = () => {
    const name = window.prompt("Nome desta visão:");
    if (!name || !name.trim()) return;
    savedViews.save(name.trim(), {
      searchInput,
      presencaStatus,
      uf,
      polo,
      situacao,
      usuarioResp,
      sortBy,
    });
    toast.success(`Visão "${name.trim()}" salva.`);
  };

  // Filtros pro bulk dialog — mesmos campos enviados pro backend.
  const bulkFilter = {
    presenca_status: presencaStatus || undefined,
    uf: uf !== "__all__" ? uf : undefined,
    polo: polo !== "__all__" ? polo : undefined,
    situacao_processo: situacao !== "__all__" ? situacao : undefined,
    usuario_responsavel: debouncedUsuario || undefined,
    search: debouncedSearch || undefined,
  };
  const sortedViews = [...savedViews.views].sort((a, b) => {
    if (a.pinned === b.pinned) {
      return a.name.localeCompare(b.name);
    }
    return a.pinned ? -1 : 1;
  });

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Filter className="h-4 w-4" /> Filtros
          </CardTitle>
          <CardDescription>
            Filtra a carteira por presença, UF, polo, situação, responsável.
            Busca livre cobre CNJ (com/sem máscara), Cód AJUS, Nº Pasta e nomes
            de partes (autor/réu).
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
            <div className="col-span-1 md:col-span-2">
              <Label htmlFor="search" className="text-xs">
                Busca
              </Label>
              <div className="relative">
                <Search className="h-4 w-4 absolute left-2 top-1/2 -translate-y-1/2 text-muted-foreground" />
                <Input
                  id="search"
                  value={searchInput}
                  onChange={(e) => setSearchInput(e.target.value)}
                  placeholder="CNJ, Cód AJUS, Nº Pasta, autor ou réu..."
                  className="pl-8"
                />
              </div>
            </div>
            <div>
              <Label className="text-xs">Presença</Label>
              <Select value={presencaStatus} onValueChange={(v) => { setPresencaStatus(v); setPage(0); }}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {PRESENCAS.map((p) => (
                    <SelectItem key={p.value} value={p.value}>{p.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="text-xs">Ordenação</Label>
              <Select value={sortBy} onValueChange={(v) => { setSortBy(v); setPage(0); }}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {SORT_OPTIONS.map((s) => (
                    <SelectItem key={s.value} value={s.value}>{s.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="text-xs">UF</Label>
              <Select value={uf} onValueChange={(v) => { setUf(v); setPage(0); }}>
                <SelectTrigger><SelectValue placeholder="Todas" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="__all__">Todas</SelectItem>
                  {UFs.map((u) => (
                    <SelectItem key={u} value={u}>{u}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="text-xs">Polo</Label>
              <Select value={polo} onValueChange={(v) => { setPolo(v); setPage(0); }}>
                <SelectTrigger><SelectValue placeholder="Todos" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="__all__">Todos</SelectItem>
                  {POLOS.map((p) => (
                    <SelectItem key={p} value={p}>{p}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="text-xs">Situação</Label>
              <Select value={situacao} onValueChange={(v) => { setSituacao(v); setPage(0); }}>
                <SelectTrigger><SelectValue placeholder="Todas" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="__all__">Todas</SelectItem>
                  {SITUACOES.map((s) => (
                    <SelectItem key={s} value={s}>{s}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="text-xs">Responsável (contém)</Label>
              <Input
                value={usuarioResp}
                onChange={(e) => setUsuarioResp(e.target.value)}
                placeholder="Ex.: Thays"
              />
            </div>
          </div>
          <div className="flex flex-wrap justify-end gap-2 mt-3">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" size="sm">
                  <BookmarkPlus className="h-3 w-3 mr-2" />
                  Visões salvas{" "}
                  {sortedViews.length > 0 && (
                    <span className="ml-1 text-xs text-muted-foreground">
                      ({sortedViews.length})
                    </span>
                  )}
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-72">
                <DropdownMenuLabel>Visões salvas</DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuItem onSelect={handleSaveView}>
                  <BookmarkPlus className="h-3 w-3 mr-2" /> Salvar visão atual
                </DropdownMenuItem>
                {sortedViews.length > 0 && <DropdownMenuSeparator />}
                {sortedViews.map((v) => (
                  <DropdownMenuItem
                    key={v.id}
                    className="flex items-center justify-between gap-2"
                    onSelect={(e) => {
                      e.preventDefault();
                      loadSavedView(v.filters);
                      toast.info(`Visão "${v.name}" carregada.`);
                    }}
                  >
                    <span className="truncate flex-1">{v.name}</span>
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        savedViews.togglePin(v.id);
                      }}
                      className="text-muted-foreground hover:text-foreground"
                      title={v.pinned ? "Desafixar" : "Fixar no topo"}
                    >
                      {v.pinned ? (
                        <PinOff className="h-3 w-3" />
                      ) : (
                        <Pin className="h-3 w-3" />
                      )}
                    </button>
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        savedViews.remove(v.id);
                      }}
                      className="text-muted-foreground hover:text-destructive"
                      title="Remover visão"
                    >
                      <Trash2 className="h-3 w-3" />
                    </button>
                  </DropdownMenuItem>
                ))}
                {sortedViews.length === 0 && (
                  <div className="px-2 py-1 text-xs text-muted-foreground">
                    Nenhuma visão salva ainda.
                  </div>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setBulkOpen(true)}
              disabled={(data?.total ?? 0) === 0}
            >
              <Layers className="h-3 w-3 mr-2" /> Atualizar em lote
            </Button>
            <Button variant="ghost" size="sm" onClick={resetFilters}>
              <RotateCcw className="h-3 w-3 mr-2" /> Limpar filtros
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0">
          <div>
            <CardTitle>Processos</CardTitle>
            <CardDescription>
              {processosQ.isLoading ? (
                "Carregando..."
              ) : (
                <>
                  {total.toLocaleString("pt-BR")} resultado
                  {total !== 1 ? "s" : ""} · Pág. {page + 1} de {totalPages}
                </>
              )}
            </CardDescription>
          </div>
          <Select
            value={String(pageSize)}
            onValueChange={(v) => {
              setPageSize(Number(v));
              setPage(0);
            }}
          >
            <SelectTrigger className="w-24 h-8">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PAGE_SIZE_OPTIONS.map((s) => (
                <SelectItem key={s} value={String(s)}>{s}/pág</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </CardHeader>
        <CardContent>
          {processosQ.isLoading ? (
            <div className="py-8 text-center text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin mx-auto" />
            </div>
          ) : processosQ.isError ? (
            <div className="py-8 text-center text-red-600 text-sm">
              Erro: {(processosQ.error as Error).message}
            </div>
          ) : items.length === 0 ? (
            <div className="py-8 text-center text-muted-foreground text-sm">
              Nenhum processo bate com esses filtros.
            </div>
          ) : (
            <>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-24">Cód AJUS</TableHead>
                    <TableHead>CNJ</TableHead>
                    <TableHead>Polo</TableHead>
                    <TableHead>Situação</TableHead>
                    <TableHead>UF · Comarca</TableHead>
                    <TableHead>Responsável</TableHead>
                    <TableHead className="text-right">Valor causa</TableHead>
                    <TableHead>Últ. andamento</TableHead>
                    <TableHead className="w-20">Presença</TableHead>
                    <TableHead className="w-10"></TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {items.map((p) => (
                    <TableRow
                      key={p.id}
                      className={cn(
                        "cursor-pointer hover:bg-muted/50",
                        p.presenca_status === "REMOVIDO_NA_BASE" && "opacity-60",
                      )}
                      onClick={() => setOpenCodAjus(p.cod_ajus)}
                    >
                      <TableCell className="font-mono">{p.cod_ajus}</TableCell>
                      <TableCell className="font-mono text-xs">
                        {p.numero_processo_mascarado ?? "—"}
                      </TableCell>
                      <TableCell>{p.polo ?? "—"}</TableCell>
                      <TableCell>{p.situacao_processo}</TableCell>
                      <TableCell className="text-xs">
                        {p.uf ?? "—"}
                        {p.comarca && (
                          <span className="text-muted-foreground">
                            {" "}· {p.comarca}
                          </span>
                        )}
                      </TableCell>
                      <TableCell className="max-w-[12rem] truncate text-xs">
                        {p.usuario_responsavel ?? "—"}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {fmtMoney(p.valor_causa)}
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {fmtBR(p.data_ult_andamento)}
                      </TableCell>
                      <TableCell>
                        <PresencaBadge status={p.presenca_status} />
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

      <ProcessoDrawer codAjus={openCodAjus} onClose={() => setOpenCodAjus(null)} />

      <BulkUpdateDialog
        open={bulkOpen}
        filters={bulkFilter}
        previewTotal={total}
        onClose={() => setBulkOpen(false)}
      />
    </div>
  );
}
