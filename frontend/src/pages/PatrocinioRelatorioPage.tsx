import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  AlertCircle,
  ChevronLeft,
  ChevronRight,
  Download,
  Eraser,
  ExternalLink,
  FileText,
  Loader2,
  RefreshCw,
} from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
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
import { useToast } from "@/hooks/use-toast";
import {
  downloadPatrocinioRelatorioCsv,
  fetchPatrocinioRelatorio,
} from "@/services/api";
import type {
  PatrocinioRelatorioFilters,
  PatrocinioRelatorioItem,
} from "@/types/api";

/**
 * Pagina /prazos-iniciais/patrocinio/relatorio
 *
 * Lista os casos de devolucao aprovados pelo operador (patrocinio
 * marcado como suspeita_devolucao=true + review_status=aprovado). Cada
 * linha vira uma entrada no relatorio que vai pro banco — daqui o
 * operador exporta CSV pra anexar ao envio mensal.
 */
export default function PatrocinioRelatorioPage() {
  const { toast } = useToast();
  const [items, setItems] = useState<PatrocinioRelatorioItem[]>([]);
  const [total, setTotal] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isExporting, setIsExporting] = useState(false);

  // Filtros
  const [sinceFilter, setSinceFilter] = useState("");
  const [untilFilter, setUntilFilter] = useState("");
  const [officeFilter, setOfficeFilter] = useState("");

  // Paginacao
  const [pageSize, setPageSize] = useState<25 | 50 | 100>(50);
  const [offset, setOffset] = useState(0);

  const filters = useMemo<PatrocinioRelatorioFilters>(() => {
    const f: PatrocinioRelatorioFilters = {
      limit: pageSize,
      offset,
    };
    if (sinceFilter) f.since = new Date(sinceFilter).toISOString();
    if (untilFilter) f.until = new Date(untilFilter).toISOString();
    if (officeFilter && /^\d+$/.test(officeFilter.trim())) {
      f.office_id = Number(officeFilter.trim());
    }
    return f;
  }, [pageSize, offset, sinceFilter, untilFilter, officeFilter]);

  const hasActiveFilters =
    sinceFilter !== "" || untilFilter !== "" || officeFilter !== "";

  const handleClear = () => {
    setSinceFilter("");
    setUntilFilter("");
    setOfficeFilter("");
    setOffset(0);
  };

  const load = async () => {
    setIsLoading(true);
    try {
      const payload = await fetchPatrocinioRelatorio(filters);
      setItems(payload.items);
      setTotal(payload.total);
      setError(null);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Falha ao carregar.";
      setError(message);
    } finally {
      setIsLoading(false);
    }
  };

  // Reset offset quando filtros mudam.
  useEffect(() => {
    setOffset(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sinceFilter, untilFilter, officeFilter]);

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pageSize, offset, sinceFilter, untilFilter, officeFilter]);

  const handleExport = async () => {
    setIsExporting(true);
    try {
      const blob = await downloadPatrocinioRelatorioCsv({
        since: filters.since ?? null,
        until: filters.until ?? null,
        office_id: filters.office_id ?? null,
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `patrocinio-relatorio-${new Date()
        .toISOString()
        .replace(/[:.]/g, "-")}.csv`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
      toast({ title: "CSV exportado", description: "Arquivo baixado." });
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Falha ao exportar.";
      toast({
        title: "Falha ao exportar CSV",
        description: msg,
        variant: "destructive",
      });
    } finally {
      setIsExporting(false);
    }
  };

  const formatDateTime = (value: string | null | undefined) => {
    if (!value) return "—";
    return new Intl.DateTimeFormat("pt-BR", {
      dateStyle: "short",
      timeStyle: "short",
      timeZone: "America/Fortaleza",
    }).format(new Date(value));
  };

  const formatDate = (value: string | null | undefined) => {
    if (!value) return "—";
    return new Intl.DateTimeFormat("pt-BR", {
      dateStyle: "short",
      timeZone: "America/Fortaleza",
    }).format(new Date(`${value}T00:00:00`));
  };

  const formatCnj = (value: string | null | undefined) => {
    if (!value) return "—";
    const digits = value.replace(/\D/g, "");
    if (digits.length === 20) {
      return `${digits.slice(0, 7)}-${digits.slice(7, 9)}.${digits.slice(9, 13)}.${digits.slice(13, 14)}.${digits.slice(14, 16)}.${digits.slice(16, 20)}`;
    }
    return value;
  };

  const ajusBadge = (status: string | null | undefined) => {
    if (!status) return <span className="text-muted-foreground">—</span>;
    const cls: Record<string, string> = {
      pendente: "bg-slate-100 text-slate-700",
      enviando: "bg-blue-100 text-blue-800",
      sucesso: "bg-emerald-100 text-emerald-800",
      erro: "bg-red-100 text-red-800",
      cancelado: "bg-slate-200 text-slate-800",
    };
    return <Badge className={cls[status] || "bg-slate-100"}>{status}</Badge>;
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
            <FileText className="h-6 w-6" />
            Relatório de Patrocínio (Devoluções)
          </h1>
          <p className="text-muted-foreground">
            Casos aprovados pelo operador como devolução (patrocínio não é do
            MDR). Use o CSV pra anexar ao envio ao banco.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => load()}
            disabled={isLoading}
          >
            <RefreshCw
              className={`mr-2 h-4 w-4 ${isLoading ? "animate-spin" : ""}`}
            />
            Atualizar
          </Button>
          <Button
            size="sm"
            onClick={handleExport}
            disabled={isExporting || total === 0}
            title="Exporta os filtros atuais (sem paginacao) em CSV BOM-utf-8 pronto pro Excel pt-BR."
          >
            {isExporting ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Download className="mr-2 h-4 w-4" />
            )}
            Exportar CSV
          </Button>
        </div>
      </div>

      {error ? (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Falha ao carregar relatório</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      <Card className="border-0 shadow-sm">
        <CardHeader className="flex flex-row items-start justify-between gap-4">
          <div>
            <CardTitle>Filtros</CardTitle>
            <CardDescription>
              Aplicam tanto na lista quanto no CSV exportado.
            </CardDescription>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={handleClear}
            disabled={!hasActiveFilters}
          >
            <Eraser className="mr-2 h-4 w-4" />
            Limpar filtros
          </Button>
        </CardHeader>
        <CardContent>
          <div className="grid gap-3 md:grid-cols-3">
            <div>
              <Label className="mb-1 block text-xs font-medium text-muted-foreground">
                Aprovado desde
              </Label>
              <Input
                type="datetime-local"
                value={sinceFilter}
                onChange={(e) => setSinceFilter(e.target.value)}
              />
            </div>
            <div>
              <Label className="mb-1 block text-xs font-medium text-muted-foreground">
                Aprovado até
              </Label>
              <Input
                type="datetime-local"
                value={untilFilter}
                onChange={(e) => setUntilFilter(e.target.value)}
              />
            </div>
            <div>
              <Label className="mb-1 block text-xs font-medium text-muted-foreground">
                Office ID (interno)
              </Label>
              <Input
                inputMode="numeric"
                placeholder="Ex.: 12"
                value={officeFilter}
                onChange={(e) => setOfficeFilter(e.target.value)}
              />
            </div>
          </div>
        </CardContent>
      </Card>

      <Card className="border-0 shadow-sm">
        <CardHeader>
          <CardTitle>Casos aprovados ({total})</CardTitle>
          <CardDescription>
            Cada linha representa um intake encaminhado pra devolução. Clique no
            CNJ pra abrir o intake e revisar o caso.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Intake</TableHead>
                  <TableHead>CNJ</TableHead>
                  <TableHead>Decisão</TableHead>
                  <TableHead>Natureza</TableHead>
                  <TableHead>Outro Adv.</TableHead>
                  <TableHead>OAB</TableHead>
                  <TableHead>Habilitado em</TableHead>
                  <TableHead>Motivo</TableHead>
                  <TableHead>AJUS</TableHead>
                  <TableHead>Aprovado em</TableHead>
                  <TableHead>Por</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.length === 0 ? (
                  <TableRow>
                    <TableCell
                      colSpan={11}
                      className="py-10 text-center text-muted-foreground"
                    >
                      {isLoading
                        ? "Carregando..."
                        : "Nenhum caso aprovado para os filtros atuais."}
                    </TableCell>
                  </TableRow>
                ) : (
                  items.map((item) => (
                    <TableRow key={item.intake_id}>
                      <TableCell>
                        <Link
                          to={`/prazos-iniciais?intake=${item.intake_id}`}
                          className="text-primary hover:underline"
                        >
                          #{item.intake_id}
                        </Link>
                      </TableCell>
                      <TableCell className="font-mono text-xs">
                        {formatCnj(item.cnj_number)}
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline" className="text-[10px]">
                          {item.decisao}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-xs">
                        {item.natureza_acao || "—"}
                      </TableCell>
                      <TableCell className="text-xs">
                        {item.outro_advogado_nome || "—"}
                      </TableCell>
                      <TableCell className="text-xs">
                        {item.outro_advogado_oab || "—"}
                      </TableCell>
                      <TableCell className="text-xs">
                        {formatDate(item.outro_advogado_data_habilitacao)}
                      </TableCell>
                      <TableCell
                        className="max-w-[280px] truncate text-xs text-muted-foreground"
                        title={item.motivo_suspeita || ""}
                      >
                        {item.motivo_suspeita || "—"}
                      </TableCell>
                      <TableCell>{ajusBadge(item.ajus_queue_status)}</TableCell>
                      <TableCell className="text-xs">
                        {formatDateTime(item.reviewed_at)}
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {item.reviewed_by_name || item.reviewed_by_email || "—"}
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>

          {/* Paginador (mesmo padrao da PrazosIniciaisTreatmentPage). */}
          <div className="flex flex-col items-center justify-between gap-3 pt-4 sm:flex-row">
            <div className="text-sm text-muted-foreground">
              {total === 0
                ? "Nenhum caso para os filtros atuais."
                : `Mostrando ${offset + 1}–${Math.min(offset + pageSize, total)} de ${total} caso(s).`}
            </div>
            <div className="flex items-center gap-3">
              <Select
                value={String(pageSize)}
                onValueChange={(v) => {
                  setPageSize(Number(v) as 25 | 50 | 100);
                  setOffset(0);
                }}
                disabled={isLoading}
              >
                <SelectTrigger className="h-8 w-[140px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="25">25 por página</SelectItem>
                  <SelectItem value="50">50 por página</SelectItem>
                  <SelectItem value="100">100 por página</SelectItem>
                </SelectContent>
              </Select>
              <div className="flex items-center gap-1">
                <Button
                  variant="outline"
                  size="sm"
                  className="h-8 w-8 p-0"
                  disabled={offset === 0 || isLoading}
                  onClick={() => setOffset(Math.max(0, offset - pageSize))}
                  title="Página anterior"
                >
                  <ChevronLeft className="h-4 w-4" />
                </Button>
                <span className="min-w-[110px] px-2 text-center text-sm font-medium">
                  {total === 0
                    ? "—"
                    : `Página ${Math.floor(offset / pageSize) + 1} de ${Math.max(1, Math.ceil(total / pageSize))}`}
                </span>
                <Button
                  variant="outline"
                  size="sm"
                  className="h-8 w-8 p-0"
                  disabled={offset + pageSize >= total || isLoading}
                  onClick={() => setOffset(offset + pageSize)}
                  title="Próxima página"
                >
                  <ChevronRight className="h-4 w-4" />
                </Button>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      <div className="text-xs text-muted-foreground">
        Tip: o relatório lista apenas casos onde o operador aprovou a sugestão
        de devolução (review_status=aprovado + suspeita_devolucao=true). Casos
        rejeitados ou ainda pendentes de revisão não aparecem aqui.
      </div>

      <div className="flex items-center justify-end">
        <Link
          to="/prazos-iniciais"
          className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
        >
          <ExternalLink className="h-3 w-3" />
          Voltar ao Agendar Prazos Iniciais
        </Link>
      </div>
    </div>
  );
}
