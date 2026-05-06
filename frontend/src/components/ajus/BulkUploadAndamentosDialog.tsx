import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  FileText,
  Loader2,
  Trash2,
  Upload,
} from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/hooks/use-toast";
import {
  bulkCnjAjusAndamentos,
  bulkUploadAjusAndamentos,
  type AjusBulkResponse,
  type AjusBulkVarsPayload,
} from "@/services/api";
import type { AjusCodAndamento } from "@/types/api";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  codigos: AjusCodAndamento[];
  onSuccess?: (resp: AjusBulkResponse) => void;
}

const MAX_FILE_MB = 10; // limite AJUS

// Mesmo regex do backend — extrai CNJ (com ou sem mascara) do nome.
const CNJ_REGEX =
  /(\d{7})[-.\s]?(\d{2})[-.\s]?(\d{4})[-.\s]?(\d{1})[-.\s]?(\d{2})[-.\s]?(\d{4})/;

function extractCnjFromFilename(filename: string): string | null {
  if (!filename) return null;
  const base = filename.includes(".") ? filename.split(".").slice(0, -1).join(".") : filename;
  const m = base.match(CNJ_REGEX);
  if (!m) return null;
  return m.slice(1).join("");
}

function maskCnj(digits: string): string {
  if (digits.length !== 20) return digits;
  return `${digits.slice(0, 7)}-${digits.slice(7, 9)}.${digits.slice(9, 13)}.${digits.slice(13, 14)}.${digits.slice(14, 16)}.${digits.slice(16, 20)}`;
}

function todayISO(): string {
  const now = new Date();
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, "0");
  const d = String(now.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

interface FileRow {
  file: File;
  cnj: string | null; // 20 digitos ou null
  oversize: boolean;
}

export function BulkUploadAndamentosDialog({
  open,
  onOpenChange,
  codigos,
  onSuccess,
}: Props) {
  const { toast } = useToast();
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const [mode, setMode] = useState<"files" | "cnj_list">("files");

  // Variaveis comuns
  const defaultCod = useMemo(
    () => codigos.find((c) => c.is_default && c.is_active) ?? codigos.find((c) => c.is_active),
    [codigos],
  );
  const [codAndamentoId, setCodAndamentoId] = useState<string>("");
  const [situacao, setSituacao] = useState<"A" | "C">("A");
  const [dataEvento, setDataEvento] = useState<string>(todayISO());
  const [dataAgendamento, setDataAgendamento] = useState<string>("");
  const [dataFatal, setDataFatal] = useState<string>("");
  const [horaAgendamento, setHoraAgendamento] = useState<string>("");
  const [informacaoOverride, setInformacaoOverride] = useState<string>("");

  // Modo "files"
  const [rows, setRows] = useState<FileRow[]>([]);

  // Modo "cnj_list"
  const [cnjText, setCnjText] = useState<string>("");

  const [submitting, setSubmitting] = useState(false);

  const selectedCod = useMemo(
    () => codigos.find((c) => String(c.id) === codAndamentoId) ?? null,
    [codigos, codAndamentoId],
  );

  // Quando abre o dialog, restaura defaults baseado no codigo escolhido.
  useEffect(() => {
    if (!open) return;
    if (defaultCod && !codAndamentoId) {
      setCodAndamentoId(String(defaultCod.id));
    }
  }, [open, defaultCod, codAndamentoId]);

  useEffect(() => {
    if (!selectedCod) return;
    setSituacao((selectedCod.situacao as "A" | "C") || "A");
  }, [selectedCod]);

  // Reset ao fechar
  useEffect(() => {
    if (open) return;
    setRows([]);
    setCnjText("");
    setSubmitting(false);
    // mantem codAndamentoId/situacao/datas pra reabrir mais rapido
  }, [open]);

  const cnjListParsed = useMemo(() => {
    return cnjText
      .split(/[\n,;]/)
      .map((s) => s.trim())
      .filter(Boolean);
  }, [cnjText]);

  const cnjListInvalid = useMemo(() => {
    return cnjListParsed.filter((raw) => raw.replace(/\D/g, "").length !== 20);
  }, [cnjListParsed]);

  const handleFiles = (filesList: FileList | null) => {
    if (!filesList) return;
    const arr = Array.from(filesList);
    const newRows: FileRow[] = arr.map((file) => {
      const cnj = extractCnjFromFilename(file.name);
      return {
        file,
        cnj,
        oversize: file.size > MAX_FILE_MB * 1024 * 1024,
      };
    });
    setRows((prev) => [...prev, ...newRows]);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const handleRemoveRow = (idx: number) => {
    setRows((prev) => prev.filter((_, i) => i !== idx));
  };

  const filesSummary = useMemo(() => {
    const total = rows.length;
    const ok = rows.filter((r) => r.cnj && !r.oversize).length;
    const noCnj = rows.filter((r) => !r.cnj).length;
    const oversize = rows.filter((r) => r.oversize).length;
    return { total, ok, noCnj, oversize };
  }, [rows]);

  const buildVars = (): AjusBulkVarsPayload | null => {
    if (!codAndamentoId) {
      toast({
        title: "Selecione um código de andamento",
        variant: "destructive",
      });
      return null;
    }
    const id = Number(codAndamentoId);
    if (!Number.isFinite(id) || id < 1) {
      toast({ title: "Código de andamento inválido", variant: "destructive" });
      return null;
    }
    return {
      cod_andamento_id: id,
      situacao,
      data_evento: dataEvento || null,
      data_agendamento: dataAgendamento || null,
      data_fatal: dataFatal || null,
      hora_agendamento: horaAgendamento || null,
      informacao_template_override: informacaoOverride.trim() || null,
    };
  };

  const showSummary = (resp: AjusBulkResponse) => {
    const lines = [`${resp.created} item(ns) enfileirado(s).`];
    if (resp.skipped.length > 0) {
      lines.push(`${resp.skipped.length} ignorado(s).`);
    }
    toast({
      title: "Upload em lote concluído",
      description: lines.join(" "),
      variant: resp.skipped.length > 0 ? "destructive" : "default",
    });
    if (resp.skipped.length > 0) {
      console.warn("AJUS bulk skipped:", resp.skipped);
    }
  };

  const handleSubmitFiles = async () => {
    const vars = buildVars();
    if (!vars) return;
    if (rows.length === 0) {
      toast({ title: "Adicione ao menos um arquivo", variant: "destructive" });
      return;
    }
    setSubmitting(true);
    try {
      const resp = await bulkUploadAjusAndamentos(
        rows.map((r) => r.file),
        vars,
      );
      showSummary(resp);
      onSuccess?.(resp);
      if (resp.created > 0) {
        onOpenChange(false);
      }
    } catch (e: unknown) {
      toast({
        title: "Falha no upload em lote",
        description: e instanceof Error ? e.message : String(e),
        variant: "destructive",
      });
    } finally {
      setSubmitting(false);
    }
  };

  const handleSubmitCnjList = async () => {
    const vars = buildVars();
    if (!vars) return;
    if (cnjListParsed.length === 0) {
      toast({
        title: "Cole ao menos um CNJ na lista",
        variant: "destructive",
      });
      return;
    }
    setSubmitting(true);
    try {
      const resp = await bulkCnjAjusAndamentos(cnjListParsed, vars);
      showSummary(resp);
      onSuccess?.(resp);
      if (resp.created > 0) {
        onOpenChange(false);
      }
    } catch (e: unknown) {
      toast({
        title: "Falha no envio em lote",
        description: e instanceof Error ? e.message : String(e),
        variant: "destructive",
      });
    } finally {
      setSubmitting(false);
    }
  };

  const activeCodigos = codigos.filter((c) => c.is_active);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] max-w-3xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Upload className="h-4 w-4" />
            Upload em lote — Andamentos AJUS
          </DialogTitle>
          <DialogDescription>
            Envia N andamentos de uma vez. Os itens criados aparecem na fila
            como "pendente"; depois você clica em "Enviar próximos 20" pra
            disparar o lote pra AJUS.
          </DialogDescription>
        </DialogHeader>

        {activeCodigos.length === 0 && (
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertTitle>Sem código de andamento ativo</AlertTitle>
            <AlertDescription>
              Cadastre ao menos um código ativo na aba "Códigos de Andamento"
              antes de usar o upload em lote.
            </AlertDescription>
          </Alert>
        )}

        <div className="space-y-4">
          {/* Variaveis comuns */}
          <div className="grid gap-3 rounded-md border bg-muted/30 p-3 sm:grid-cols-2">
            <div className="space-y-1 sm:col-span-2">
              <Label className="text-xs uppercase tracking-wide">
                Código de Andamento *
              </Label>
              <Select
                value={codAndamentoId}
                onValueChange={setCodAndamentoId}
                disabled={submitting || activeCodigos.length === 0}
              >
                <SelectTrigger className="h-9">
                  <SelectValue placeholder="Selecione um código…" />
                </SelectTrigger>
                <SelectContent>
                  {activeCodigos.map((c) => (
                    <SelectItem key={c.id} value={String(c.id)}>
                      <span className="font-mono text-xs">{c.codigo}</span>
                      <span className="ml-2">{c.label}</span>
                      {c.is_default && (
                        <Badge className="ml-2 bg-emerald-100 text-emerald-800">
                          Default
                        </Badge>
                      )}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {selectedCod && (
                <p className="text-xs text-muted-foreground">
                  Offsets: agendamento +{selectedCod.dias_agendamento_offset_uteis}d ·
                  fatal +{selectedCod.dias_fatal_offset_uteis}d (úteis)
                </p>
              )}
            </div>

            <div className="space-y-1">
              <Label className="text-xs uppercase tracking-wide">Situação</Label>
              <Select
                value={situacao}
                onValueChange={(v) => setSituacao(v as "A" | "C")}
                disabled={submitting}
              >
                <SelectTrigger className="h-9">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="A">A — Aberto</SelectItem>
                  <SelectItem value="C">C — Concluído</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1">
              <Label className="text-xs uppercase tracking-wide">
                Data Evento
              </Label>
              <Input
                type="date"
                value={dataEvento}
                onChange={(e) => setDataEvento(e.target.value)}
                disabled={submitting}
                className="h-9"
              />
            </div>

            <div className="space-y-1">
              <Label className="text-xs uppercase tracking-wide">
                Data Agendamento
              </Label>
              <Input
                type="date"
                value={dataAgendamento}
                onChange={(e) => setDataAgendamento(e.target.value)}
                disabled={submitting}
                placeholder="auto via offset"
                className="h-9"
              />
              <p className="text-[10px] text-muted-foreground">
                Vazio = calcula auto pelo offset do código.
              </p>
            </div>

            <div className="space-y-1">
              <Label className="text-xs uppercase tracking-wide">
                Data Fatal
              </Label>
              <Input
                type="date"
                value={dataFatal}
                onChange={(e) => setDataFatal(e.target.value)}
                disabled={submitting}
                placeholder="auto via offset"
                className="h-9"
              />
              <p className="text-[10px] text-muted-foreground">
                Vazio = calcula auto pelo offset do código.
              </p>
            </div>

            <div className="space-y-1">
              <Label className="text-xs uppercase tracking-wide">
                Hora Agendamento (opcional)
              </Label>
              <Input
                type="time"
                value={horaAgendamento}
                onChange={(e) => setHoraAgendamento(e.target.value)}
                disabled={submitting}
                className="h-9"
              />
            </div>

            <div className="space-y-1 sm:col-span-2">
              <Label className="text-xs uppercase tracking-wide">
                Informação (override do template)
              </Label>
              <Textarea
                value={informacaoOverride}
                onChange={(e) => setInformacaoOverride(e.target.value)}
                placeholder={
                  selectedCod?.informacao_template
                    || "Vazio = usa template do código."
                }
                disabled={submitting}
                rows={2}
                className="text-sm"
              />
              <p className="text-[10px] text-muted-foreground">
                Placeholders aceitos: {"{cnj}"}, {"{data_recebimento}"},
                {" {motivo}"}.
              </p>
            </div>
          </div>

          {/* Modo */}
          <Tabs
            value={mode}
            onValueChange={(v) => setMode(v as "files" | "cnj_list")}
          >
            <TabsList className="grid grid-cols-2">
              <TabsTrigger value="files">Com arquivos</TabsTrigger>
              <TabsTrigger value="cnj_list">Só lista de CNJs</TabsTrigger>
            </TabsList>

            <TabsContent value="files" className="space-y-3 pt-3">
              <div
                className="rounded-md border-2 border-dashed border-muted bg-muted/20 p-4 text-center hover:bg-muted/30"
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => {
                  e.preventDefault();
                  handleFiles(e.dataTransfer.files);
                }}
              >
                <Input
                  ref={fileInputRef}
                  type="file"
                  multiple
                  accept=".pdf"
                  onChange={(e) => handleFiles(e.target.files)}
                  disabled={submitting}
                  className="cursor-pointer"
                />
                <p className="mt-2 text-xs text-muted-foreground">
                  Selecione vários PDFs. O CNJ será extraído do nome do arquivo
                  (com ou sem máscara). Limite por arquivo: {MAX_FILE_MB} MB.
                </p>
              </div>

              {rows.length > 0 && (
                <>
                  <div className="flex flex-wrap items-center gap-2 text-xs">
                    <Badge variant="outline">{filesSummary.total} arquivo(s)</Badge>
                    <Badge className="bg-emerald-100 text-emerald-800">
                      {filesSummary.ok} OK
                    </Badge>
                    {filesSummary.noCnj > 0 && (
                      <Badge variant="destructive">
                        {filesSummary.noCnj} sem CNJ no nome
                      </Badge>
                    )}
                    {filesSummary.oversize > 0 && (
                      <Badge variant="destructive">
                        {filesSummary.oversize} {">"} {MAX_FILE_MB}MB
                      </Badge>
                    )}
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setRows([])}
                      disabled={submitting}
                      className="ml-auto h-7 px-2 text-xs"
                    >
                      Limpar tudo
                    </Button>
                  </div>

                  <div className="max-h-[260px] overflow-y-auto rounded-md border">
                    <table className="w-full text-xs">
                      <thead className="sticky top-0 bg-muted/60">
                        <tr>
                          <th className="p-2 text-left">Arquivo</th>
                          <th className="p-2 text-left">CNJ</th>
                          <th className="p-2 text-right">Tamanho</th>
                          <th className="p-2"></th>
                        </tr>
                      </thead>
                      <tbody>
                        {rows.map((r, idx) => (
                          <tr key={`${r.file.name}-${idx}`} className="border-t">
                            <td className="p-2">
                              <div className="flex items-center gap-1">
                                <FileText className="h-3.5 w-3.5 text-muted-foreground" />
                                <span className="truncate" title={r.file.name}>
                                  {r.file.name}
                                </span>
                              </div>
                            </td>
                            <td className="p-2 font-mono text-[11px]">
                              {r.cnj ? (
                                maskCnj(r.cnj)
                              ) : (
                                <span className="text-destructive">
                                  não encontrado
                                </span>
                              )}
                            </td>
                            <td className="p-2 text-right tabular-nums">
                              <span
                                className={
                                  r.oversize ? "text-destructive font-medium" : ""
                                }
                              >
                                {(r.file.size / 1024 / 1024).toFixed(1)} MB
                              </span>
                            </td>
                            <td className="p-2 text-right">
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-6 w-6 p-0"
                                onClick={() => handleRemoveRow(idx)}
                                disabled={submitting}
                                aria-label="Remover"
                              >
                                <Trash2 className="h-3.5 w-3.5" />
                              </Button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              )}
            </TabsContent>

            <TabsContent value="cnj_list" className="space-y-3 pt-3">
              <Label className="text-xs uppercase tracking-wide">
                CNJs (1 por linha — vírgula ou ponto-e-vírgula também aceitos)
              </Label>
              <Textarea
                value={cnjText}
                onChange={(e) => setCnjText(e.target.value)}
                placeholder={
                  "0001234-56.2026.8.05.0001\n0007654-32.2026.8.05.0001"
                }
                rows={6}
                className="font-mono text-xs"
                disabled={submitting}
              />
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <Badge variant="outline">{cnjListParsed.length} CNJ(s)</Badge>
                {cnjListInvalid.length > 0 && (
                  <Badge variant="destructive">
                    {cnjListInvalid.length} com tamanho ≠ 20 dígitos
                  </Badge>
                )}
              </div>
              {cnjListInvalid.length > 0 && (
                <Alert variant="destructive">
                  <AlertCircle className="h-4 w-4" />
                  <AlertTitle>CNJs com formato inválido</AlertTitle>
                  <AlertDescription>
                    {cnjListInvalid.slice(0, 5).join(", ")}
                    {cnjListInvalid.length > 5 && ` e mais ${cnjListInvalid.length - 5}…`}
                    <br />
                    O backend ignora esses (vão pro `skipped` na resposta).
                  </AlertDescription>
                </Alert>
              )}
            </TabsContent>
          </Tabs>
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={submitting}
          >
            Cancelar
          </Button>
          {mode === "files" ? (
            <Button
              onClick={handleSubmitFiles}
              disabled={
                submitting
                || rows.length === 0
                || activeCodigos.length === 0
                || !codAndamentoId
              }
            >
              {submitting ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <CheckCircle2 className="mr-2 h-4 w-4" />
              )}
              Enfileirar {filesSummary.ok}/{filesSummary.total} arquivo(s)
            </Button>
          ) : (
            <Button
              onClick={handleSubmitCnjList}
              disabled={
                submitting
                || cnjListParsed.length === 0
                || activeCodigos.length === 0
                || !codAndamentoId
              }
            >
              {submitting ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <CheckCircle2 className="mr-2 h-4 w-4" />
              )}
              Enfileirar {cnjListParsed.length} CNJ(s)
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
