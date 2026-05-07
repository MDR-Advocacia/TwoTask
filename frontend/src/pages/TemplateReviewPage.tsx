/**
 * Pagina "Templates Pendentes de Revisao" — fluxo da migracao taxonomy v1 -> v2.
 *
 * Lista todos os task_templates com `needs_taxonomy_review=true` (marcados
 * pela tax007). Cada linha mostra o legacy_label e abre o
 * TemplateReviewModal pra o operador re-apontar pra cat/sub da v2.
 *
 * Paginacao obrigatoria pela regra da casa (CLAUDE.md): controles
 * Anterior/Proxima · Pagina X de Y · N-M de T resultados + seletor
 * de page size. API e o GET /api/v1/task-templates/pending-review
 * (paginado).
 *
 * Filtro por escritorio respeita o setup do operador: quando ele
 * configura `polo_scope` num escritorio especifico, faz sentido
 * revisar os templates desse escritorio em batch.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowLeft, AlertTriangle, RefreshCw } from "lucide-react";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
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
  TemplateReviewModal,
  type TemplateForReview,
} from "@/components/TemplateReviewModal";
import { useToast } from "@/hooks/use-toast";
import { apiFetch } from "@/lib/api-client";

const PAGE_SIZE_OPTIONS = [25, 50, 100] as const;

interface PendingTemplate {
  id: number;
  name: string;
  category: string;
  subcategory: string | null;
  office_external_id: number | null;
  office_name: string | null;
  office_polo_scope: string | null;
  task_subtype_name: string | null;
  legacy_label: string | null;
  taxonomy_version: string;
  needs_taxonomy_review: boolean;
  is_active: boolean;
}

interface PendingResponse {
  total: number;
  items: PendingTemplate[];
  limit: number;
  offset: number;
}

interface OfficeOption {
  external_id: number;
  name: string;
  path?: string;
}

export default function TemplateReviewPage() {
  const { toast } = useToast();

  const [data, setData] = useState<PendingResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [pageSize, setPageSize] =
    useState<(typeof PAGE_SIZE_OPTIONS)[number]>(50);
  const [page, setPage] = useState(0);
  const [officeFilter, setOfficeFilter] = useState<string>("__all__");
  const [offices, setOffices] = useState<OfficeOption[]>([]);

  const [modalOpen, setModalOpen] = useState(false);
  const [reviewing, setReviewing] = useState<TemplateForReview | null>(null);

  const offset = page * pageSize;

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      params.set("limit", String(pageSize));
      params.set("offset", String(offset));
      if (officeFilter !== "__all__") {
        params.set("office_external_id", officeFilter);
      }
      const res = await apiFetch(
        `/api/v1/task-templates/pending-review?${params.toString()}`,
      );
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
      const json = (await res.json()) as PendingResponse;
      setData(json);
    } catch (err: any) {
      toast({
        title: "Falha carregando pendentes",
        description: err?.message || String(err),
        variant: "destructive",
      });
    } finally {
      setLoading(false);
    }
  }, [pageSize, offset, officeFilter, toast]);

  useEffect(() => {
    load();
  }, [load]);

  // Carrega lista de escritorios pra filtro (uma vez)
  useEffect(() => {
    apiFetch("/api/v1/offices")
      .then((r) => (r.ok ? r.json() : []))
      .then((rows: any[]) => {
        const opts = (rows ?? []).map((o) => ({
          external_id: o.external_id,
          name: o.path || o.name,
        }));
        setOffices(opts);
      })
      .catch(() => {
        // Filtro de escritorio nao critico — silencia.
      });
  }, []);

  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const pageStart = total === 0 ? 0 : offset + 1;
  const pageEnd = Math.min(offset + pageSize, total);

  // Defensivo: se filtros encolherem o total e a pagina atual ficar
  // fora do range, volta pra ultima pagina valida.
  useEffect(() => {
    if (page >= totalPages) setPage(Math.max(0, totalPages - 1));
  }, [page, totalPages]);

  const handleOpenReview = (t: PendingTemplate) => {
    setReviewing({
      id: t.id,
      name: t.name,
      category: t.category,
      subcategory: t.subcategory,
      legacy_label: t.legacy_label,
      office_polo_scope: t.office_polo_scope,
      office_name: t.office_name,
    });
    setModalOpen(true);
  };

  const handleMigrated = () => {
    toast({ title: "Template revisado", description: "Lista atualizada." });
    load();
  };

  const officeOptions = useMemo(() => {
    return offices.sort((a, b) => a.name.localeCompare(b.name));
  }, [offices]);

  return (
    <div className="container mx-auto py-6 max-w-6xl">
      {/* Header */}
      <div className="flex items-start justify-between gap-3 mb-4">
        <div>
          <Button asChild variant="ghost" size="sm" className="mb-2 -ml-2">
            <Link to="/publications/templates">
              <ArrowLeft className="h-4 w-4 mr-1" />
              Voltar para Templates
            </Link>
          </Button>
          <h1 className="text-2xl font-semibold flex items-center gap-2">
            <AlertTriangle className="h-6 w-6 text-amber-500" />
            Templates Pendentes de Revisão
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Templates da taxonomia v1 que precisam ser re-apontados para
            categorias da nova taxonomia (v2). Enquanto não revisados, esses
            templates não geram proposta automática de tarefa.
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={load}
          disabled={loading}
        >
          <RefreshCw
            className={`h-4 w-4 mr-1 ${loading ? "animate-spin" : ""}`}
          />
          Recarregar
        </Button>
      </div>

      {/* Filtros */}
      <div className="flex items-center gap-3 mb-3">
        <div className="text-sm text-muted-foreground">Escritório:</div>
        <Select
          value={officeFilter}
          onValueChange={(v) => {
            setOfficeFilter(v);
            setPage(0);
          }}
        >
          <SelectTrigger className="h-8 w-[280px] text-sm">
            <SelectValue placeholder="Todos" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__all__">Todos os escritórios</SelectItem>
            {officeOptions.map((o) => (
              <SelectItem
                key={o.external_id}
                value={String(o.external_id)}
                className="text-sm"
              >
                {o.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <div className="text-sm text-muted-foreground ml-auto">
          {total > 0 ? (
            <>
              <span className="font-medium text-foreground">{total}</span>{" "}
              pendente{total === 1 ? "" : "s"}
            </>
          ) : loading ? (
            "Carregando…"
          ) : (
            "Nenhum pendente"
          )}
        </div>
      </div>

      {/* Lista */}
      <div className="rounded-md border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-[28%]">Nome</TableHead>
              <TableHead className="w-[28%]">Classificação legada (v1)</TableHead>
              <TableHead className="w-[24%]">Escritório</TableHead>
              <TableHead className="w-[10%]">Subtipo</TableHead>
              <TableHead className="w-[10%] text-right">Ação</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data && data.items.length === 0 && !loading && (
              <TableRow>
                <TableCell
                  colSpan={5}
                  className="text-center text-sm text-muted-foreground py-12"
                >
                  Nenhum template pendente de revisão
                  {officeFilter !== "__all__" ? " para esse escritório" : ""}.
                </TableCell>
              </TableRow>
            )}
            {data?.items.map((t) => (
              <TableRow key={t.id}>
                <TableCell>
                  <div className="font-medium text-sm">{t.name}</div>
                  {!t.is_active && (
                    <Badge variant="outline" className="text-xs mt-1">
                      desativado
                    </Badge>
                  )}
                </TableCell>
                <TableCell>
                  <span className="font-mono text-xs">
                    {t.legacy_label ??
                      `${t.category}${
                        t.subcategory ? ` / ${t.subcategory}` : ""
                      }`}
                  </span>
                </TableCell>
                <TableCell className="text-sm">
                  {t.office_name ?? (
                    <Badge variant="outline" className="text-xs">
                      Global
                    </Badge>
                  )}
                  {t.office_polo_scope && t.office_polo_scope !== "ambos" && (
                    <Badge
                      variant="secondary"
                      className="text-xs ml-2"
                      title="Polo do escritório"
                    >
                      {t.office_polo_scope}
                    </Badge>
                  )}
                </TableCell>
                <TableCell className="text-xs text-muted-foreground">
                  {t.task_subtype_name ?? "-"}
                </TableCell>
                <TableCell className="text-right">
                  <Button
                    size="sm"
                    variant="default"
                    onClick={() => handleOpenReview(t)}
                  >
                    Revisar
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      {/* Paginacao */}
      {total > 0 && (
        <div className="flex items-center justify-between gap-3 mt-3 text-sm text-muted-foreground">
          <div className="flex items-center gap-2">
            <span>Por página</span>
            <Select
              value={String(pageSize)}
              onValueChange={(v) => {
                setPageSize(
                  Number(v) as (typeof PAGE_SIZE_OPTIONS)[number],
                );
                setPage(0);
              }}
            >
              <SelectTrigger className="h-7 w-[68px] text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {PAGE_SIZE_OPTIONS.map((opt) => (
                  <SelectItem
                    key={opt}
                    value={String(opt)}
                    className="text-xs"
                  >
                    {opt}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <span className="ml-2">
              {pageStart}–{pageEnd} de{" "}
              <span className="font-medium text-foreground">{total}</span>
            </span>
          </div>
          <div className="flex items-center gap-1">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={page === 0 || loading}
            >
              Anterior
            </Button>
            <span className="px-2 tabular-nums">
              <span className="font-medium text-foreground">{page + 1}</span>{" "}
              / {totalPages}
            </span>
            <Button
              variant="ghost"
              size="sm"
              onClick={() =>
                setPage((p) => Math.min(totalPages - 1, p + 1))
              }
              disabled={page >= totalPages - 1 || loading}
            >
              Próxima
            </Button>
          </div>
        </div>
      )}

      <TemplateReviewModal
        open={modalOpen}
        onOpenChange={setModalOpen}
        template={reviewing}
        onMigrated={handleMigrated}
      />
    </div>
  );
}
