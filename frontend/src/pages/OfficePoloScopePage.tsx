/**
 * OfficePoloScopePage — Admin pra configurar polo_scope dos escritorios.
 *
 * Cada escritorio declara qual polo do processo ele atende:
 *  - 'ativo'    → so cats da arvore v2 ativo (ex: recuperacao de credito)
 *  - 'passivo'  → so cats da arvore v2 passivo (ex: contencioso bancario)
 *  - 'ambos'    → ambas as arvores (default; util pra escritorios mistos)
 *
 * Esse polo determina:
 *  1. Qual arvore aparece no modal de templates desse escritorio
 *  2. Qual arvore e injetada no prompt do classificador (so quando o
 *     toggle global v2 estiver ativo)
 *  3. Qual arvore o ClassificationPicker filtra na revisao de pendentes
 *
 * Mudanca aqui NAO migra templates/overrides do escritorio — operador
 * faz isso revisando cada um pelo painel "Templates Pendentes de Revisao".
 *
 * Endpoint: PATCH /api/v1/offices/{external_id}/polo-scope (fase 5).
 */
import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, RefreshCw, Search } from "lucide-react";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
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
import { apiFetch } from "@/lib/api-client";

interface OfficeRow {
  id: number;
  external_id: number;
  name: string;
  path: string;
  polo_scope?: string;
}

const POLO_OPTIONS = [
  {
    value: "ambos",
    label: "Ambos (default)",
    description: "Escritório enxerga as duas árvores",
  },
  {
    value: "ativo",
    label: "Polo ativo",
    description: "Ex.: recuperação de crédito, execuções como exequente",
  },
  {
    value: "passivo",
    label: "Polo passivo",
    description: "Ex.: contencioso defensivo, cliente como réu/executado",
  },
] as const;

export default function OfficePoloScopePage() {
  const { toast } = useToast();
  const [offices, setOffices] = useState<OfficeRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [savingId, setSavingId] = useState<number | null>(null);
  const [query, setQuery] = useState("");

  const load = async () => {
    setLoading(true);
    try {
      const res = await apiFetch("/api/v1/offices");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as OfficeRow[];
      setOffices(data ?? []);
    } catch (err: any) {
      toast({
        title: "Falha carregando escritórios",
        description: err?.message || String(err),
        variant: "destructive",
      });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const handleChangePolo = async (
    office: OfficeRow,
    newPolo: string,
  ) => {
    if (newPolo === office.polo_scope) return;
    setSavingId(office.external_id);
    try {
      const res = await apiFetch(
        `/api/v1/offices/${office.external_id}/polo-scope`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ polo_scope: newPolo }),
        },
      );
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(
          (typeof data?.detail === "string" && data.detail) ||
            "Falha ao atualizar.",
        );
      }
      // Atualiza state local sem reload total — mais responsivo.
      setOffices((prev) =>
        prev.map((o) =>
          o.external_id === office.external_id
            ? { ...o, polo_scope: newPolo }
            : o,
        ),
      );
      toast({
        title: "Polo atualizado",
        description: `${office.path || office.name} → ${newPolo}`,
      });
    } catch (err: any) {
      toast({
        title: "Erro ao atualizar polo",
        description: err?.message || String(err),
        variant: "destructive",
      });
    } finally {
      setSavingId(null);
    }
  };

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return offices;
    return offices.filter(
      (o) =>
        (o.path || "").toLowerCase().includes(q) ||
        (o.name || "").toLowerCase().includes(q),
    );
  }, [offices, query]);

  // Stats por polo pra cabeçalho
  const stats = useMemo(() => {
    const counts: Record<string, number> = { ativo: 0, passivo: 0, ambos: 0 };
    offices.forEach((o) => {
      const p = o.polo_scope || "ambos";
      counts[p] = (counts[p] ?? 0) + 1;
    });
    return counts;
  }, [offices]);

  return (
    <div className="container mx-auto py-6 max-w-5xl">
      <div className="flex items-start justify-between gap-3 mb-4">
        <div>
          <Button asChild variant="ghost" size="sm" className="mb-2 -ml-2">
            <Link to="/admin">
              <ArrowLeft className="h-4 w-4 mr-1" />
              Voltar para Admin
            </Link>
          </Button>
          <h1 className="text-2xl font-semibold">
            Polo dos Escritórios
            <Badge variant="outline" className="ml-3 align-middle text-xs">
              Taxonomy v2
            </Badge>
          </h1>
          <p className="text-sm text-muted-foreground mt-1 max-w-3xl">
            Configure a qual polo do processo cada escritório atende. Isso
            determina qual árvore (ativo / passivo) aparece nos templates
            daquele escritório e é usada pela IA quando o toggle global
            v2 estiver ativo. Default <code>ambos</code> preserva
            comportamento anterior.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={load} disabled={loading}>
          <RefreshCw
            className={`h-4 w-4 mr-1 ${loading ? "animate-spin" : ""}`}
          />
          Recarregar
        </Button>
      </div>

      {/* Stats */}
      <div className="flex flex-wrap items-center gap-2 mb-3 text-sm">
        <span className="text-muted-foreground">Distribuição atual:</span>
        <Badge variant="outline">
          ativo: <span className="font-semibold ml-1">{stats.ativo}</span>
        </Badge>
        <Badge variant="outline">
          passivo: <span className="font-semibold ml-1">{stats.passivo}</span>
        </Badge>
        <Badge variant="outline">
          ambos: <span className="font-semibold ml-1">{stats.ambos}</span>
        </Badge>
      </div>

      {/* Busca */}
      <div className="relative mb-3">
        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Buscar escritório por nome ou hierarquia..."
          className="pl-8"
        />
      </div>

      {/* Tabela */}
      <div className="rounded-md border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-[60%]">Escritório</TableHead>
              <TableHead className="w-[40%]">Polo</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filtered.length === 0 && !loading && (
              <TableRow>
                <TableCell
                  colSpan={2}
                  className="text-center text-sm text-muted-foreground py-12"
                >
                  {query
                    ? "Nenhum escritório corresponde à busca."
                    : "Nenhum escritório carregado."}
                </TableCell>
              </TableRow>
            )}
            {filtered.map((o) => {
              const currentPolo = o.polo_scope || "ambos";
              const isSaving = savingId === o.external_id;
              return (
                <TableRow key={o.external_id}>
                  <TableCell className="text-sm">
                    {o.path || o.name}
                  </TableCell>
                  <TableCell>
                    <Select
                      value={currentPolo}
                      disabled={isSaving}
                      onValueChange={(v) => handleChangePolo(o, v)}
                    >
                      <SelectTrigger className="h-8 w-[260px] text-sm">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {POLO_OPTIONS.map((opt) => (
                          <SelectItem
                            key={opt.value}
                            value={opt.value}
                            className="text-sm"
                          >
                            <div className="flex flex-col">
                              <span>{opt.label}</span>
                              <span className="text-xs text-muted-foreground">
                                {opt.description}
                              </span>
                            </div>
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>

      <div className="mt-4 text-xs text-muted-foreground">
        ⚠️ Mudar o polo de um escritório <strong>não migra</strong> os
        templates/overrides existentes. O operador continua revisando-os
        individualmente pelo painel "Templates Pendentes de Revisão".
      </div>
    </div>
  );
}
