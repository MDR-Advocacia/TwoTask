import { useState } from "react";
import { Search, Loader2, AlertCircle, ExternalLink } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
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

type TreatmentInfo = {
  id: number;
  queue_status: string;
  target_status: string | null;
  source_record_status: string | null;
  attempt_count: number;
  last_run_id: number | null;
  last_error: string | null;
  treated_at: string | null;
  last_attempt_at: string | null;
  created_at: string | null;
  updated_at: string | null;
};

type RecordDetail = {
  id: number;
  search_id: number;
  legal_one_update_id: number;
  description_preview?: string;
  description?: string;
  publication_date: string | null;
  creation_date: string | null;
  linked_lawsuit_id: number | null;
  linked_lawsuit_cnj: string | null;
  linked_office_id: number | null;
  status: string;
  is_duplicate?: boolean;
  category: string | null;
  subcategory: string | null;
  polo: string | null;
  audiencia_data: string | null;
  audiencia_hora: string | null;
  classifications: unknown;
  treatment: TreatmentInfo | null;
};

type SearchInfo = {
  id: number;
  status: string;
  date_from: string;
  date_to: string | null;
  office_filter: string | null;
  requested_by_email: string | null;
  created_at: string | null;
  finished_at: string | null;
  total_found: number;
  total_new: number;
  total_duplicate: number;
};

type LookupResponse = {
  cnj_input: string;
  cnj_normalized: string;
  cnj_display: string | null;
  lawsuit_id: number | null;
  found: boolean;
  totals: {
    records: number;
    duplicates: number;
    by_status: Record<string, number>;
    by_category: Record<string, number>;
    by_queue_status: Record<string, number>;
  };
  searches: SearchInfo[];
  records: RecordDetail[];
};

function formatDate(value: string | null | undefined) {
  if (!value) return "—";
  if (/^\d{4}-\d{2}-\d{2}/.test(value)) {
    const d = new Date(value);
    if (!isNaN(d.getTime())) {
      return new Intl.DateTimeFormat("pt-BR", {
        dateStyle: "short",
        timeZone: "America/Sao_Paulo",
      }).format(d);
    }
  }
  return value;
}

function statusColor(status: string): string {
  const map: Record<string, string> = {
    NOVO: "bg-slate-100 text-slate-700",
    CLASSIFICADO: "bg-blue-100 text-blue-800",
    AGENDADO: "bg-green-100 text-green-800",
    IGNORADO: "bg-amber-100 text-amber-800",
    ERRO: "bg-red-100 text-red-800",
    DESCARTADO_DUPLICADA: "bg-purple-100 text-purple-800",
    PENDENTE: "bg-slate-100 text-slate-700",
    PROCESSANDO: "bg-blue-100 text-blue-800",
    CONCLUIDO: "bg-green-100 text-green-800",
    FALHA: "bg-red-100 text-red-800",
    CANCELADO: "bg-slate-200 text-slate-800",
  };
  return map[status] || "bg-slate-100 text-slate-700";
}

const LookupByCnjPage = () => {
  const { toast } = useToast();
  const [cnj, setCnj] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<LookupResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const doSearch = async () => {
    if (!cnj.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await apiFetch(
        `/api/v1/publications/lookup-by-cnj?cnj=${encodeURIComponent(cnj.trim())}`,
      );
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || `HTTP ${res.status}`);
      }
      const data = (await res.json()) as LookupResponse;
      setResult(data);
      if (!data.found) {
        toast({
          title: "Nenhuma publicação encontrada",
          description: `Nada indexado no sistema para o CNJ ${data.cnj_normalized}.`,
        });
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
      toast({ title: "Erro na busca", description: msg, variant: "destructive" });
    } finally {
      setLoading(false);
    }
  };

  const onSubmit = (ev: React.FormEvent) => {
    ev.preventDefault();
    doSearch();
  };

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Consulta por CNJ</h1>
        <p className="text-sm text-muted-foreground">
          Verifica o que o robô já capturou, como classificou e se foi enviado pra fila do RPA.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Número do processo</CardTitle>
          <CardDescription>
            Pode colar com ou sem formatação (0000000-00.0000.0.00.0000 ou só dígitos).
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={onSubmit} className="flex gap-2">
            <Input
              value={cnj}
              onChange={(e) => setCnj(e.target.value)}
              placeholder="Ex: 1234567-89.2024.8.26.0100"
              autoFocus
            />
            <Button type="submit" disabled={loading || !cnj.trim()}>
              {loading ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Search className="h-4 w-4" />
              )}
              <span className="ml-2">Buscar</span>
            </Button>
          </form>
        </CardContent>
      </Card>

      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Falha na consulta</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {result && result.found && (
        <>
          <Card>
            <CardHeader>
              <CardTitle className="text-base">
                Processo {result.cnj_display || result.cnj_normalized}
              </CardTitle>
              <CardDescription>
                {result.lawsuit_id ? (
                  <>Legal One lawsuit_id: <code>{result.lawsuit_id}</code></>
                ) : (
                  "lawsuit_id não resolvido nos registros"
                )}
              </CardDescription>
            </CardHeader>
            <CardContent className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
              <div>
                <div className="text-muted-foreground">Publicações</div>
                <div className="text-xl font-semibold">{result.totals.records}</div>
              </div>
              <div>
                <div className="text-muted-foreground">Duplicatas</div>
                <div className="text-xl font-semibold">{result.totals.duplicates}</div>
              </div>
              <div>
                <div className="text-muted-foreground">Buscas que o alcançaram</div>
                <div className="text-xl font-semibold">{result.searches.length}</div>
              </div>
              <div>
                <div className="text-muted-foreground">Na fila RPA</div>
                <div className="text-xl font-semibold">
                  {Object.values(result.totals.by_queue_status).reduce((a, b) => a + b, 0)}
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Totais detalhados */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium">Por status</CardTitle>
              </CardHeader>
              <CardContent className="space-y-1 text-sm">
                {Object.entries(result.totals.by_status).map(([k, v]) => (
                  <div key={k} className="flex items-center justify-between">
                    <Badge variant="outline" className={statusColor(k)}>{k}</Badge>
                    <span className="font-medium">{v}</span>
                  </div>
                ))}
                {Object.keys(result.totals.by_status).length === 0 && (
                  <div className="text-muted-foreground">—</div>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium">Por classificação</CardTitle>
              </CardHeader>
              <CardContent className="space-y-1 text-sm">
                {Object.entries(result.totals.by_category).map(([k, v]) => (
                  <div key={k} className="flex items-center justify-between gap-2">
                    <span className="truncate" title={k}>{k}</span>
                    <span className="font-medium shrink-0">{v}</span>
                  </div>
                ))}
                {Object.keys(result.totals.by_category).length === 0 && (
                  <div className="text-muted-foreground">Nenhuma classificada ainda</div>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium">Fila RPA</CardTitle>
              </CardHeader>
              <CardContent className="space-y-1 text-sm">
                {Object.entries(result.totals.by_queue_status).map(([k, v]) => (
                  <div key={k} className="flex items-center justify-between">
                    <Badge variant="outline" className={statusColor(k)}>{k}</Badge>
                    <span className="font-medium">{v}</span>
                  </div>
                ))}
                {Object.keys(result.totals.by_queue_status).length === 0 && (
                  <div className="text-muted-foreground">Nenhuma enfileirada</div>
                )}
              </CardContent>
            </Card>
          </div>

          {/* Buscas */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Buscas que capturaram publicações deste processo</CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>#</TableHead>
                    <TableHead>Período</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Escritório</TableHead>
                    <TableHead className="text-right">Encontradas</TableHead>
                    <TableHead className="text-right">Novas</TableHead>
                    <TableHead className="text-right">Duplicatas</TableHead>
                    <TableHead>Criada</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {result.searches.map((s) => (
                    <TableRow key={s.id}>
                      <TableCell className="font-mono">#{s.id}</TableCell>
                      <TableCell className="text-xs">
                        {s.date_from} → {s.date_to || "—"}
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline" className={statusColor(s.status)}>{s.status}</Badge>
                      </TableCell>
                      <TableCell className="text-xs">{s.office_filter || "—"}</TableCell>
                      <TableCell className="text-right">{s.total_found}</TableCell>
                      <TableCell className="text-right">{s.total_new}</TableCell>
                      <TableCell className="text-right">{s.total_duplicate}</TableCell>
                      <TableCell className="text-xs">{formatDate(s.created_at)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>

          {/* Publicações */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Publicações deste processo</CardTitle>
              <CardDescription>
                Ordenadas da mais recente para a mais antiga.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {result.records.map((r) => (
                <div key={r.id} className="border rounded-lg p-4 space-y-2">
                  <div className="flex items-start justify-between gap-4 flex-wrap">
                    <div className="space-y-1">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-mono text-xs text-muted-foreground">
                          update_id: {r.legal_one_update_id}
                        </span>
                        <Badge variant="outline" className={statusColor(r.status)}>{r.status}</Badge>
                        {r.is_duplicate && (
                          <Badge variant="outline" className={statusColor("DESCARTADO_DUPLICADA")}>
                            duplicata
                          </Badge>
                        )}
                        {r.polo && (
                          <Badge variant="outline">polo: {r.polo}</Badge>
                        )}
                      </div>
                      <div className="text-sm">
                        <span className="text-muted-foreground">Publicação:</span>{" "}
                        <strong>{formatDate(r.publication_date)}</strong>{" "}
                        <span className="text-muted-foreground">· Criação Ajus:</span>{" "}
                        {formatDate(r.creation_date)}{" "}
                        <span className="text-muted-foreground">· Busca:</span>{" "}
                        #{r.search_id}
                      </div>
                    </div>
                    {r.legal_one_update_id && (
                      <a
                        href={`https://firm.legalone.com.br/publications?publicationId=${r.legal_one_update_id}&treatStatus=3`}
                        target="_blank"
                        rel="noreferrer"
                        className="text-xs inline-flex items-center gap-1 text-blue-600 hover:underline"
                      >
                        abrir no Legal One <ExternalLink className="h-3 w-3" />
                      </a>
                    )}
                  </div>

                  <div className="text-sm">
                    <span className="text-muted-foreground">Classificação:</span>{" "}
                    {r.category ? (
                      <>
                        <strong>{r.category}</strong>
                        {r.subcategory && r.subcategory !== "-" && (
                          <> / {r.subcategory}</>
                        )}
                      </>
                    ) : (
                      <em className="text-muted-foreground">não classificada</em>
                    )}
                    {(r.audiencia_data || r.audiencia_hora) && (
                      <span className="ml-2 text-muted-foreground">
                        · audiência: {r.audiencia_data || "?"} {r.audiencia_hora || ""}
                      </span>
                    )}
                  </div>

                  {r.description && (
                    <details className="text-xs">
                      <summary className="cursor-pointer text-muted-foreground hover:text-foreground">
                        ver texto da publicação
                      </summary>
                      <pre className="mt-2 whitespace-pre-wrap font-sans text-xs bg-slate-50 p-3 rounded">
                        {r.description}
                      </pre>
                    </details>
                  )}

                  <div className="text-xs border-t pt-2">
                    <span className="text-muted-foreground">Fila RPA:</span>{" "}
                    {r.treatment ? (
                      <>
                        <Badge variant="outline" className={statusColor(r.treatment.queue_status)}>
                          {r.treatment.queue_status}
                        </Badge>{" "}
                        <span className="text-muted-foreground">alvo:</span>{" "}
                        {r.treatment.target_status || "—"}{" "}
                        <span className="text-muted-foreground">· tentativas:</span>{" "}
                        {r.treatment.attempt_count}
                        {r.treatment.treated_at && (
                          <>
                            {" "}
                            <span className="text-muted-foreground">· tratada em</span>{" "}
                            {formatDate(r.treatment.treated_at)}
                          </>
                        )}
                        {r.treatment.last_error && (
                          <div className="text-red-600 mt-1">
                            erro: {r.treatment.last_error}
                          </div>
                        )}
                      </>
                    ) : (
                      <em className="text-muted-foreground">não enfileirada</em>
                    )}
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>
        </>
      )}

      {result && !result.found && (
        <Alert>
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Nenhum registro</AlertTitle>
          <AlertDescription>
            O sistema não tem nenhuma publicação indexada para o CNJ{" "}
            <code>{result.cnj_normalized}</code>. Pode ser que o robô ainda não tenha passado
            pelo período onde esse processo teve publicação, ou que o processo não esteja
            no escritório buscado.
          </AlertDescription>
        </Alert>
      )}
    </div>
  );
};

export default LookupByCnjPage;
