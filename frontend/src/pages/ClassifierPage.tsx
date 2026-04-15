import { useEffect, useRef, useState } from "react";
import {
  AlertCircle,
  Brain,
  CheckCircle2,
  Download,
  FileText,
  Loader2,
  Upload,
  XCircle,
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
import { Progress } from "@/components/ui/progress";
import { ScrollArea } from "@/components/ui/scroll-area";
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

const API_BASE = "/api/v1/classifier";

// ─── Tipos ─────────────────────────────────────────

interface PreviewRow {
  row_index: number;
  process_number: string;
  has_publication_text: boolean;
  text_preview: string;
}

interface PreviewResponse {
  total_rows: number;
  rows_with_text: number;
  rows_without_text: number;
  preview: PreviewRow[];
}

interface BatchStatus {
  batch_id: number;
  status: string;
  total_items: number;
  processed: number;
  success_count: number;
  failure_count: number;
  created_at: string | null;
  finished_at: string | null;
}

interface ClassificationResult {
  row_index: number;
  process_number: string;
  publication_text_preview: string;
  status: string;
  category: string | null;
  subcategory: string | null;
  confidence: string | null;
  justification: string | null;
  error_message: string | null;
}

interface BatchListItem {
  id: number;
  source_filename: string | null;
  status: string;
  total_items: number;
  success_count: number;
  failure_count: number;
  model_used: string | null;
  created_at: string | null;
  finished_at: string | null;
}

// ─── Helpers ───────────────────────────────────────

const statusColor = (status: string) => {
  switch (status) {
    case "CONCLUIDO":
      return "default";
    case "CONCLUIDO_COM_FALHAS":
      return "destructive";
    case "PROCESSANDO":
      return "secondary";
    case "CANCELADO":
      return "outline";
    default:
      return "secondary";
  }
};

const confidenceBadge = (confidence: string | null) => {
  switch (confidence) {
    case "alta":
      return <Badge className="bg-green-600 text-white">Alta</Badge>;
    case "media":
      return <Badge className="bg-yellow-500 text-white">Média</Badge>;
    case "baixa":
      return <Badge className="bg-red-500 text-white">Baixa</Badge>;
    default:
      return <Badge variant="outline">-</Badge>;
  }
};

// ─── Componente Principal ──────────────────────────

const ClassifierPage = () => {
  const { toast } = useToast();
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Estado do fluxo
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<PreviewResponse | null>(null);
  const [isPreviewing, setIsPreviewing] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Batch ativo
  const [activeBatchId, setActiveBatchId] = useState<number | null>(null);
  const [batchStatus, setBatchStatus] = useState<BatchStatus | null>(null);
  const [results, setResults] = useState<ClassificationResult[]>([]);

  // Histórico
  const [batches, setBatches] = useState<BatchListItem[]>([]);

  // ─── Upload & Preview ────────────────────────────

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0] ?? null;
    setSelectedFile(file);
    setPreview(null);
    setError(null);
    setActiveBatchId(null);
    setBatchStatus(null);
    setResults([]);
  };

  const handlePreview = async () => {
    if (!selectedFile) return;
    setIsPreviewing(true);
    setError(null);

    try {
      const formData = new FormData();
      formData.append("file", selectedFile);
      const res = await apiFetch(`${API_BASE}/upload-preview`, {
        method: "POST",
        body: formData,
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || "Erro ao gerar preview");
      }
      setPreview(await res.json());
    } catch (err: any) {
      setError(err.message);
    } finally {
      setIsPreviewing(false);
    }
  };

  // ─── Iniciar Classificação ───────────────────────

  const handleStartClassification = async () => {
    if (!selectedFile) return;
    setIsSubmitting(true);
    setError(null);

    try {
      const formData = new FormData();
      formData.append("file", selectedFile);
      const res = await apiFetch(`${API_BASE}/start`, {
        method: "POST",
        body: formData,
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || "Erro ao iniciar classificação");
      }
      const data = await res.json();
      setActiveBatchId(data.batch_id);
      toast({
        title: "Classificação iniciada",
        description: `Batch #${data.batch_id} com ${data.total_items} itens`,
      });
    } catch (err: any) {
      setError(err.message);
    } finally {
      setIsSubmitting(false);
    }
  };

  // ─── Polling de Status ───────────────────────────

  useEffect(() => {
    if (!activeBatchId) return;

    const interval = setInterval(async () => {
      try {
        const res = await apiFetch(`${API_BASE}/batches/${activeBatchId}`);
        if (res.ok) {
          const status: BatchStatus = await res.json();
          setBatchStatus(status);
          if (["CONCLUIDO", "CONCLUIDO_COM_FALHAS", "CANCELADO"].includes(status.status)) {
            clearInterval(interval);
            loadResults(activeBatchId);
            loadBatches();
          }
        }
      } catch {
        // silently ignore polling errors
      }
    }, 2000);

    return () => clearInterval(interval);
  }, [activeBatchId]);

  // ─── Carregar Resultados ─────────────────────────

  const loadResults = async (batchId: number) => {
    try {
      const res = await apiFetch(`${API_BASE}/batches/${batchId}/results`);
      if (res.ok) {
        setResults(await res.json());
      }
    } catch {
      // ignore
    }
  };

  // ─── Exportar XLSX ───────────────────────────────

  const handleExport = async (batchId: number) => {
    try {
      const res = await apiFetch(`${API_BASE}/batches/${batchId}/export`);
      if (!res.ok) throw new Error("Erro ao exportar");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `classificacao_batch_${batchId}.xlsx`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err: any) {
      toast({ title: "Erro", description: err.message, variant: "destructive" });
    }
  };

  // ─── Cancelar Batch ──────────────────────────────

  const handleCancel = async () => {
    if (!activeBatchId) return;
    try {
      await apiFetch(`${API_BASE}/batches/${activeBatchId}/cancel`, { method: "POST" });
      toast({ title: "Classificação cancelada" });
    } catch {
      // ignore
    }
  };

  // ─── Carregar Histórico ──────────────────────────

  const loadBatches = async () => {
    try {
      const res = await apiFetch(`${API_BASE}/batches`);
      if (res.ok) setBatches(await res.json());
    } catch {
      // ignore
    }
  };

  useEffect(() => {
    loadBatches();
  }, []);

  // ─── Selecionar batch do histórico ───────────────

  const handleSelectBatch = (batch: BatchListItem) => {
    setActiveBatchId(batch.id);
    setBatchStatus({
      batch_id: batch.id,
      status: batch.status,
      total_items: batch.total_items,
      processed: batch.success_count + batch.failure_count,
      success_count: batch.success_count,
      failure_count: batch.failure_count,
      created_at: batch.created_at,
      finished_at: batch.finished_at,
    });
    loadResults(batch.id);
  };

  // ─── Render ──────────────────────────────────────

  const isProcessing = batchStatus?.status === "PROCESSANDO";
  const isFinished = batchStatus
    ? ["CONCLUIDO", "CONCLUIDO_COM_FALHAS", "CANCELADO"].includes(batchStatus.status)
    : false;
  const progressPct =
    batchStatus && batchStatus.total_items > 0
      ? Math.round((batchStatus.processed / batchStatus.total_items) * 100)
      : 0;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight">
          <Brain className="mr-2 inline h-6 w-6" />
          Classificador de Publicações
        </h1>
        <p className="text-muted-foreground">
          Faça upload de uma planilha com publicações judiciais para classificação automática via IA.
        </p>
      </div>

      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Erro</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {/* Upload */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Upload className="h-5 w-5" />
            Upload da Planilha
          </CardTitle>
          <CardDescription>
            Selecione a planilha (.xlsx) com os processos na coluna B e publicações na coluna J.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-end gap-4">
            <div className="grid w-full max-w-md gap-1.5">
              <Label htmlFor="file">Arquivo</Label>
              <Input
                id="file"
                ref={fileInputRef}
                type="file"
                accept=".xlsx"
                onChange={handleFileChange}
              />
            </div>
            <Button onClick={handlePreview} disabled={!selectedFile || isPreviewing}>
              {isPreviewing ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <FileText className="mr-2 h-4 w-4" />
              )}
              Visualizar
            </Button>
          </div>

          {/* Preview */}
          {preview && (
            <div className="space-y-4">
              <div className="flex gap-4">
                <Badge variant="secondary">{preview.total_rows} linhas</Badge>
                <Badge className="bg-green-600 text-white">{preview.rows_with_text} com texto</Badge>
                {preview.rows_without_text > 0 && (
                  <Badge variant="destructive">{preview.rows_without_text} sem texto</Badge>
                )}
              </div>

              <ScrollArea className="h-[300px] rounded border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-[50px]">#</TableHead>
                      <TableHead className="w-[250px]">Nº Processo</TableHead>
                      <TableHead>Preview da Publicação</TableHead>
                      <TableHead className="w-[80px]">Texto?</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {preview.preview.map((row) => (
                      <TableRow key={row.row_index}>
                        <TableCell className="font-mono text-xs">{row.row_index}</TableCell>
                        <TableCell className="font-mono text-xs">{row.process_number}</TableCell>
                        <TableCell className="max-w-[400px] truncate text-xs text-muted-foreground">
                          {row.text_preview || "-"}
                        </TableCell>
                        <TableCell>
                          {row.has_publication_text ? (
                            <CheckCircle2 className="h-4 w-4 text-green-500" />
                          ) : (
                            <XCircle className="h-4 w-4 text-red-400" />
                          )}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </ScrollArea>

              <Button
                onClick={handleStartClassification}
                disabled={isSubmitting || preview.total_rows === 0}
                size="lg"
              >
                {isSubmitting ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Brain className="mr-2 h-4 w-4" />
                )}
                Classificar {preview.total_rows} publicações
              </Button>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Progresso do Batch Ativo */}
      {batchStatus && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center justify-between">
              <span>Batch #{batchStatus.batch_id}</span>
              <Badge variant={statusColor(batchStatus.status)}>{batchStatus.status}</Badge>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <Progress value={progressPct} className="h-3" />
            <div className="flex items-center justify-between text-sm text-muted-foreground">
              <span>
                {batchStatus.processed} / {batchStatus.total_items} processados ({progressPct}%)
              </span>
              <span className="flex gap-3">
                <span className="text-green-600">{batchStatus.success_count} ok</span>
                {batchStatus.failure_count > 0 && (
                  <span className="text-red-500">{batchStatus.failure_count} falhas</span>
                )}
              </span>
            </div>

            <div className="flex gap-2">
              {isProcessing && (
                <Button variant="destructive" size="sm" onClick={handleCancel}>
                  Cancelar
                </Button>
              )}
              {isFinished && (
                <Button size="sm" onClick={() => handleExport(batchStatus.batch_id)}>
                  <Download className="mr-2 h-4 w-4" />
                  Exportar XLSX
                </Button>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Resultados */}
      {results.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Resultados da Classificação</CardTitle>
            <CardDescription>{results.length} publicações classificadas</CardDescription>
          </CardHeader>
          <CardContent>
            <ScrollArea className="h-[500px] rounded border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-[50px]">#</TableHead>
                    <TableHead className="w-[230px]">Nº Processo</TableHead>
                    <TableHead>Categoria</TableHead>
                    <TableHead>Subcategoria</TableHead>
                    <TableHead className="w-[80px]">Confiança</TableHead>
                    <TableHead>Justificativa</TableHead>
                    <TableHead className="w-[70px]">Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {results.map((r) => (
                    <TableRow key={r.row_index}>
                      <TableCell className="font-mono text-xs">{r.row_index}</TableCell>
                      <TableCell className="font-mono text-xs">{r.process_number}</TableCell>
                      <TableCell className="text-sm font-medium">{r.category || "-"}</TableCell>
                      <TableCell className="text-sm">{r.subcategory || "-"}</TableCell>
                      <TableCell>{confidenceBadge(r.confidence)}</TableCell>
                      <TableCell className="max-w-[250px] truncate text-xs text-muted-foreground">
                        {r.justification || r.error_message || "-"}
                      </TableCell>
                      <TableCell>
                        {r.status === "SUCESSO" ? (
                          <CheckCircle2 className="h-4 w-4 text-green-500" />
                        ) : (
                          <XCircle className="h-4 w-4 text-red-400" />
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </ScrollArea>
          </CardContent>
        </Card>
      )}

      {/* Histórico de Batches */}
      {batches.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Histórico de Classificações</CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>ID</TableHead>
                  <TableHead>Arquivo</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Total</TableHead>
                  <TableHead>Sucesso</TableHead>
                  <TableHead>Falhas</TableHead>
                  <TableHead>Data</TableHead>
                  <TableHead>Ações</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {batches.map((b) => (
                  <TableRow
                    key={b.id}
                    className="cursor-pointer hover:bg-muted/50"
                    onClick={() => handleSelectBatch(b)}
                  >
                    <TableCell>#{b.id}</TableCell>
                    <TableCell className="max-w-[200px] truncate text-xs">
                      {b.source_filename || "-"}
                    </TableCell>
                    <TableCell>
                      <Badge variant={statusColor(b.status)}>{b.status}</Badge>
                    </TableCell>
                    <TableCell>{b.total_items}</TableCell>
                    <TableCell className="text-green-600">{b.success_count}</TableCell>
                    <TableCell className="text-red-500">{b.failure_count}</TableCell>
                    <TableCell className="text-xs">
                      {b.created_at ? new Date(b.created_at).toLocaleString("pt-BR") : "-"}
                    </TableCell>
                    <TableCell>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleExport(b.id);
                        }}
                      >
                        <Download className="h-4 w-4" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
    </div>
  );
};

export default ClassifierPage;
