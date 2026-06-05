import { useRef, useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Loader2, UploadCloud, Trash2 } from "lucide-react";
import { useToast } from "@/components/ui/use-toast";
import {
  createGedBatchMulti,
  GedDocumentType,
  GedUploadBatch,
} from "@/services/api";
import {
  GED_ACCEPT,
  TYPE_NONE,
  extractCnjFromFilename,
  fmtBytes,
  maskCnj,
  normalizeCnj,
} from "./shared";

interface FileRow {
  file: File;
  cnj: string; // editavel — prefilled do nome do arquivo
}

interface Props {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  documentTypes: GedDocumentType[];
  onCreated: (batch: GedUploadBatch) => void;
}

export default function UploadMultiFileDialog({
  open,
  onOpenChange,
  documentTypes,
  onCreated,
}: Props) {
  const { toast } = useToast();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [nome, setNome] = useState("");
  const [typeId, setTypeId] = useState<string>(TYPE_NONE);
  const [description, setDescription] = useState("");
  const [rows, setRows] = useState<FileRow[]>([]);
  const [dragActive, setDragActive] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const types = documentTypes.length
    ? documentTypes
    : [{ type_id: null, label: "Sem tipo" } as GedDocumentType];

  const validCount = rows.filter((r) => normalizeCnj(r.cnj) !== null).length;
  const invalidCount = rows.length - validCount;
  const canSubmit = nome.trim().length > 0 && rows.length > 0 && validCount > 0 && !submitting;

  const addFiles = (selected: FileList | File[] | null) => {
    if (!selected) return;
    const incoming = Array.from(selected);
    setRows((prev) => {
      const seen = new Set(prev.map((r) => `${r.file.name}_${r.file.size}`));
      const merged = [...prev];
      for (const f of incoming) {
        const key = `${f.name}_${f.size}`;
        if (seen.has(key)) continue;
        seen.add(key);
        const cnjDigits = extractCnjFromFilename(f.name);
        merged.push({ file: f, cnj: cnjDigits ? maskCnj(cnjDigits) : "" });
      }
      return merged;
    });
  };

  const setRowCnj = (idx: number, value: string) => {
    setRows((prev) => prev.map((r, i) => (i === idx ? { ...r, cnj: value } : r)));
  };

  const removeRow = (idx: number) => {
    setRows((prev) => prev.filter((_, i) => i !== idx));
  };

  const reset = () => {
    setNome("");
    setTypeId(TYPE_NONE);
    setDescription("");
    setRows([]);
  };

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragActive(false);
    if (submitting) return;
    addFiles(e.dataTransfer.files);
  };

  const handleSubmit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    try {
      const overrides: Record<string, string> = {};
      for (const r of rows) {
        if (r.cnj.trim()) overrides[r.file.name] = r.cnj.trim();
      }
      const result = await createGedBatchMulti({
        nome: nome.trim(),
        files: rows.map((r) => r.file),
        typeId: typeId === TYPE_NONE ? null : typeId,
        description: description.trim() || undefined,
        cnjOverrides: overrides,
      });
      const s = result.resolve_summary;
      const extras: string[] = [];
      if (s.nao_encontrado) extras.push(`${s.nao_encontrado} sem CNJ/nao encontrado(s)`);
      toast({
        title: `Lote #${result.batch.id} criado`,
        description:
          `${s.resolved} arquivo(s) resolvido(s)` +
          (extras.length ? ` · ${extras.join(" · ")}` : "") +
          ". Envio em andamento.",
      });
      reset();
      onOpenChange(false);
      onCreated(result.batch);
    } catch (err) {
      toast({
        title: "Falha ao criar lote",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => !submitting && onOpenChange(v)}>
      <DialogContent className="sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>Enviar varios arquivos para varios processos</DialogTitle>
          <DialogDescription>
            Cada arquivo e' enviado ao GED de um CNJ. O CNJ e' extraido do nome
            do arquivo — corrija ou preencha o que faltar na tabela.
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-3 py-2">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="grid gap-1">
              <Label htmlFor="gm-nome">Nome do lote *</Label>
              <Input
                id="gm-nome"
                value={nome}
                onChange={(e) => setNome(e.target.value)}
                placeholder="Ex.: Comprovantes Q2/2026"
                maxLength={255}
              />
            </div>
            <div className="grid gap-1">
              <Label>Tipo no GED</Label>
              <Select value={typeId} onValueChange={setTypeId}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {types.map((t) => (
                    <SelectItem key={t.type_id ?? TYPE_NONE} value={t.type_id ?? TYPE_NONE}>
                      {t.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          {/* Drop zone */}
          <div
            onDrop={handleDrop}
            onDragOver={(e) => {
              e.preventDefault();
              if (!submitting) setDragActive(true);
            }}
            onDragLeave={() => setDragActive(false)}
            onClick={() => !submitting && inputRef.current?.click()}
            className={`flex min-h-[96px] cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed p-4 text-center transition-colors ${
              dragActive
                ? "border-primary bg-primary/5"
                : "border-muted-foreground/40 hover:border-primary hover:bg-muted/30"
            } ${submitting ? "pointer-events-none opacity-50" : ""}`}
          >
            <UploadCloud
              className={`h-7 w-7 ${dragActive ? "text-primary" : "text-muted-foreground"}`}
            />
            <div className="text-sm font-medium">
              {rows.length === 0
                ? "Arraste arquivos aqui ou clique pra selecionar"
                : `${rows.length} arquivo(s) — arraste mais ou clique pra adicionar`}
            </div>
            <input
              ref={inputRef}
              type="file"
              accept={GED_ACCEPT}
              multiple
              className="hidden"
              onChange={(e) => {
                addFiles(e.target.files);
                e.target.value = "";
              }}
            />
          </div>

          {/* Tabela editavel */}
          {rows.length > 0 && (
            <div className="max-h-64 overflow-y-auto rounded-md border">
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-muted/60 text-left text-xs text-muted-foreground">
                  <tr>
                    <th className="px-2 py-1.5">Arquivo</th>
                    <th className="px-2 py-1.5 w-[230px]">CNJ</th>
                    <th className="px-2 py-1.5 w-10" />
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r, idx) => {
                    const ok = normalizeCnj(r.cnj) !== null;
                    return (
                      <tr key={`${r.file.name}_${idx}`} className="border-t">
                        <td className="px-2 py-1.5">
                          <div className="truncate max-w-[280px]" title={r.file.name}>
                            {r.file.name}
                          </div>
                          <div className="text-xs text-muted-foreground">
                            {fmtBytes(r.file.size)}
                          </div>
                        </td>
                        <td className="px-2 py-1.5">
                          <Input
                            value={r.cnj}
                            onChange={(e) => setRowCnj(idx, e.target.value)}
                            placeholder="CNJ (20 digitos)"
                            className={`h-8 font-mono text-xs ${
                              r.cnj && !ok ? "border-rose-400 bg-rose-50" : ""
                            }`}
                          />
                        </td>
                        <td className="px-2 py-1.5 text-right">
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-7 w-7"
                            onClick={() => removeRow(idx)}
                            disabled={submitting}
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {rows.length > 0 && (
            <p className="text-xs">
              <span className="font-medium text-emerald-700">{validCount} com CNJ valido</span>
              {invalidCount > 0 && (
                <span className="text-rose-600"> · {invalidCount} sem CNJ valido (irao falhar)</span>
              )}
            </p>
          )}

          <div className="grid gap-1">
            <Label htmlFor="gm-desc">Descricao (opcional)</Label>
            <Textarea
              id="gm-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={2}
            />
          </div>
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={submitting}>
            Cancelar
          </Button>
          <Button onClick={handleSubmit} disabled={!canSubmit}>
            {submitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            Enviar {validCount || 0} arquivo(s)
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
