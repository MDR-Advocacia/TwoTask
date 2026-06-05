import { useMemo, useState } from "react";
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
import { Loader2 } from "lucide-react";
import { useToast } from "@/components/ui/use-toast";
import {
  createGedBatchSingle,
  GedDocumentType,
  GedUploadBatch,
} from "@/services/api";
import { GED_ACCEPT, TYPE_NONE, parseCnjList } from "./shared";

interface Props {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  documentTypes: GedDocumentType[];
  onCreated: (batch: GedUploadBatch) => void;
}

export default function UploadSingleFileDialog({
  open,
  onOpenChange,
  documentTypes,
  onCreated,
}: Props) {
  const { toast } = useToast();
  const [nome, setNome] = useState("");
  const [cnjText, setCnjText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [typeId, setTypeId] = useState<string>(TYPE_NONE);
  const [description, setDescription] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const types = documentTypes.length
    ? documentTypes
    : [{ type_id: null, label: "Sem tipo" } as GedDocumentType];

  const parsed = useMemo(() => parseCnjList(cnjText), [cnjText]);
  const canSubmit =
    nome.trim().length > 0 && file != null && parsed.valid.length > 0 && !submitting;

  const reset = () => {
    setNome("");
    setCnjText("");
    setFile(null);
    setTypeId(TYPE_NONE);
    setDescription("");
  };

  const handleSubmit = async () => {
    if (!canSubmit || !file) return;
    setSubmitting(true);
    try {
      const result = await createGedBatchSingle({
        nome: nome.trim(),
        file,
        cnjList: cnjText,
        typeId: typeId === TYPE_NONE ? null : typeId,
        description: description.trim() || undefined,
      });
      const s = result.resolve_summary;
      const extras: string[] = [];
      if (s.nao_encontrado) extras.push(`${s.nao_encontrado} nao encontrado(s)`);
      if (s.invalid_cnjs?.length) extras.push(`${s.invalid_cnjs.length} invalido(s)`);
      if (s.duplicates_removed) extras.push(`${s.duplicates_removed} duplicado(s)`);
      toast({
        title: `Lote #${result.batch.id} criado`,
        description:
          `${s.resolved} CNJ(s) resolvido(s)` +
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
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Enviar 1 arquivo para varios processos</DialogTitle>
          <DialogDescription>
            O mesmo arquivo e' enviado ao GED de cada CNJ informado.
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-3 py-2">
          <div className="grid gap-1">
            <Label htmlFor="gs-nome">Nome do lote *</Label>
            <Input
              id="gs-nome"
              value={nome}
              onChange={(e) => setNome(e.target.value)}
              placeholder="Ex.: Peticao inicial modelo BB"
              maxLength={255}
            />
          </div>

          <div className="grid gap-1">
            <Label htmlFor="gs-file">Arquivo *</Label>
            <Input
              id="gs-file"
              type="file"
              accept={GED_ACCEPT}
              onChange={(e) => setFile(e.target.files?.[0] || null)}
            />
            {file && (
              <p className="text-xs text-muted-foreground">
                {file.name} — {(file.size / 1024).toFixed(1)} KB
              </p>
            )}
          </div>

          <div className="grid gap-1">
            <Label htmlFor="gs-cnjs">
              CNJs (um por linha, ou separados por virgula/ponto-e-virgula) *
            </Label>
            <Textarea
              id="gs-cnjs"
              value={cnjText}
              onChange={(e) => setCnjText(e.target.value)}
              rows={5}
              placeholder={"0001234-56.7890.1.23.4567\n0009876-54.3210.9.87.6543"}
            />
            {cnjText.trim().length > 0 && (
              <p className="text-xs">
                <span className="font-medium text-emerald-700">
                  {parsed.valid.length} valido(s)
                </span>
                {parsed.invalid.length > 0 && (
                  <span className="text-rose-600"> · {parsed.invalid.length} invalido(s)</span>
                )}
                {parsed.duplicates > 0 && (
                  <span className="text-muted-foreground">
                    {" "}· {parsed.duplicates} duplicado(s) removido(s)
                  </span>
                )}
              </p>
            )}
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

          <div className="grid gap-1">
            <Label htmlFor="gs-desc">Descricao (opcional)</Label>
            <Textarea
              id="gs-desc"
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
            Enviar para {parsed.valid.length || 0} processo(s)
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
