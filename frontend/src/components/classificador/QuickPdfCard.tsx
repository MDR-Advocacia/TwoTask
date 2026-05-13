// frontend/src/components/classificador/QuickPdfCard.tsx
//
// Card "PDF avulso (teste rapido)" — cria lote auto + sobe 1 OU N PDFs
// num shot. Backend e' tolerante a falha: se algum PDF falhar, marca
// como erro mas os outros seguem. Se TODOS falharem, lote nao e' criado.
//
// Util pra operador testar a classificacao sem precisar montar planilha.
// Apos extracao mecanica, mostra status por PDF + ja redireciona pra
// aba Historico — la o operador clica ✨ pra disparar Sonnet.

import { useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Loader2, FileSearch, CheckCircle2, XCircle } from "lucide-react";
import { useToast } from "@/components/ui/use-toast";
import {
  ClassificadorLoteSummary,
  ClassificadorQuickPdfResult,
  createClassificadorLoteFromPdf,
} from "@/services/api";


interface Props {
  onCreated: (lote: ClassificadorLoteSummary, processoIds: number[]) => void;
}

export default function QuickPdfCard({ onCreated }: Props) {
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [nome, setNome] = useState("");
  const [clienteNome, setClienteNome] = useState("");
  const [cnjHint, setCnjHint] = useState("");
  const [produto, setProduto] = useState("");
  const [observacao, setObservacao] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<ClassificadorQuickPdfResult | null>(null);

  const canSubmit = files.length > 0 && !submitting;
  const totalSize = files.reduce((s, f) => s + f.size, 0);

  const handleFilesChange = (selected: FileList | null) => {
    if (!selected) return;
    const arr = Array.from(selected).filter(
      f => f.type === "application/pdf" || f.name.toLowerCase().endsWith(".pdf"),
    );
    if (arr.length !== selected.length) {
      toast({
        title: "Alguns arquivos foram ignorados",
        description: "Apenas PDFs sao aceitos.",
        variant: "destructive",
      });
    }
    setFiles(arr);
    setResult(null);
  };

  const handleSubmit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    setResult(null);
    try {
      const r = await createClassificadorLoteFromPdf(files, {
        nome: nome.trim() || undefined,
        cliente_nome: clienteNome.trim() || undefined,
        cnj_hint: cnjHint.trim() || undefined,
        produto: produto.trim() || undefined,
        observacao: observacao.trim() || undefined,
      });
      setResult(r);
      toast({
        title: `Lote #${r.lote.id} criado`,
        description: `${r.summary.ok} OK · ${r.summary.failed} com falha de ${r.summary.total} PDFs.`,
        variant: r.summary.failed > 0 ? "destructive" : "default",
      });
      const ids = r.processos
        .filter(p => p.ok && p.processo)
        .map(p => p.processo!.id);
      onCreated(r.lote, ids);
    } catch (err) {
      toast({
        title: "Falha ao testar PDFs",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setSubmitting(false);
    }
  };

  const handleClose = () => {
    if (submitting) return;
    setOpen(false);
    setNome("");
    setClienteNome("");
    setCnjHint("");
    setProduto("");
    setObservacao("");
    setFiles([]);
    setResult(null);
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg flex items-center gap-2">
          <FileSearch className="h-5 w-5" />
          PDFs avulsos (teste)
        </CardTitle>
        <CardDescription>
          Sobe 1 ou mais PDFs de processo, cria lote automatico e roda
          extracao mecanica imediatamente. Util pra testar antes de
          virar volume.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button variant="secondary" className="w-full">
              Testar com 1 ou mais PDFs
            </Button>
          </DialogTrigger>
          <DialogContent className="sm:max-w-xl">
            <DialogHeader>
              <DialogTitle>Teste rapido — 1 ou mais PDFs</DialogTitle>
              <DialogDescription>
                Cria lote auto-nomeado + sobe N PDFs + extracao mecanica
                em paralelo. Depois voce classifica no Historico ✨.
              </DialogDescription>
            </DialogHeader>

            <div className="grid gap-3 py-2">
              <div className="grid gap-1">
                <Label htmlFor="qpdf-files">Arquivos PDF *</Label>
                <Input
                  id="qpdf-files"
                  type="file"
                  accept=".pdf,application/pdf"
                  multiple
                  onChange={e => handleFilesChange(e.target.files)}
                  disabled={submitting}
                />
                {files.length > 0 && (
                  <p className="text-xs text-muted-foreground">
                    {files.length} arquivo{files.length > 1 ? "s" : ""} · {(totalSize / 1024 / 1024).toFixed(2)} MB total
                  </p>
                )}
              </div>

              <div className="grid gap-1">
                <Label htmlFor="qpdf-nome">Nome do lote (opcional)</Label>
                <Input
                  id="qpdf-nome"
                  value={nome}
                  onChange={e => setNome(e.target.value)}
                  placeholder="Auto: 'Teste avulso — DD/MM HH:MM'"
                  maxLength={255}
                  disabled={submitting}
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="grid gap-1">
                  <Label htmlFor="qpdf-cliente">Cliente (opcional)</Label>
                  <Input
                    id="qpdf-cliente"
                    value={clienteNome}
                    onChange={e => setClienteNome(e.target.value)}
                    placeholder="Banco Master"
                    disabled={submitting}
                  />
                </div>
                <div className="grid gap-1">
                  <Label htmlFor="qpdf-cnj">CNJ hint (opcional)</Label>
                  <Input
                    id="qpdf-cnj"
                    value={cnjHint}
                    onChange={e => setCnjHint(e.target.value)}
                    placeholder="Fallback se extractor falhar"
                    disabled={submitting}
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="grid gap-1">
                  <Label htmlFor="qpdf-produto">Produto (opcional)</Label>
                  <Input
                    id="qpdf-produto"
                    value={produto}
                    onChange={e => setProduto(e.target.value)}
                    placeholder="Cartao, Cheque..."
                    disabled={submitting}
                  />
                </div>
                <div className="grid gap-1">
                  <Label htmlFor="qpdf-obs">Observacao (opcional)</Label>
                  <Input
                    id="qpdf-obs"
                    value={observacao}
                    onChange={e => setObservacao(e.target.value)}
                    placeholder="Caso piloto..."
                    disabled={submitting}
                  />
                </div>
              </div>

              {result && (
                <div className="rounded-md border max-h-72 overflow-auto">
                  <div className="px-3 py-2 border-b bg-muted/40 text-xs font-medium">
                    Lote #{result.lote.id} · {result.lote.nome}
                    {" · "}
                    <span className="text-green-700">{result.summary.ok} OK</span>
                    {result.summary.failed > 0 && (
                      <>
                        {" · "}
                        <span className="text-red-700">{result.summary.failed} falha{result.summary.failed > 1 ? "s" : ""}</span>
                      </>
                    )}
                  </div>
                  <ul className="divide-y text-xs">
                    {result.processos.map((p, i) => (
                      <li key={i} className="flex items-start gap-2 p-2">
                        {p.ok ? (
                          <CheckCircle2 className="h-4 w-4 text-green-600 shrink-0 mt-0.5" />
                        ) : (
                          <XCircle className="h-4 w-4 text-red-600 shrink-0 mt-0.5" />
                        )}
                        <div className="flex-1 min-w-0">
                          <div className="truncate font-medium">{p.filename}</div>
                          {p.ok && p.processo && (
                            <div className="text-muted-foreground">
                              processo #{p.processo.id}
                              {p.processo.cnj_number && (
                                <> · CNJ <span className="font-mono">{p.processo.cnj_number}</span></>
                              )}
                              <span className="ml-1">
                                <Badge variant="outline" className="text-[10px] py-0">
                                  {p.processo.extractor_used || "—"}
                                </Badge>{" "}
                                <Badge variant="outline" className="text-[10px] py-0">
                                  {p.processo.extraction_confidence || "—"}
                                </Badge>
                              </span>
                            </div>
                          )}
                          {!p.ok && (
                            <div className="text-red-700">{p.error_message}</div>
                          )}
                        </div>
                      </li>
                    ))}
                  </ul>
                  {result.summary.ok > 0 && (
                    <div className="px-3 py-2 border-t bg-green-50 text-green-900 text-[11px]">
                      Vai pra aba Historico pra classificar via Sonnet (botao ✨).
                    </div>
                  )}
                </div>
              )}
            </div>

            <DialogFooter>
              <Button variant="ghost" onClick={handleClose} disabled={submitting}>
                Fechar
              </Button>
              <Button onClick={handleSubmit} disabled={!canSubmit}>
                {submitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Criar lote + extrair {files.length > 0 ? `(${files.length})` : ""}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        <p className="mt-3 text-xs text-muted-foreground">
          Cada submit cria um lote novo. Limpe via Historico 🗑.
        </p>
      </CardContent>
    </Card>
  );
}
