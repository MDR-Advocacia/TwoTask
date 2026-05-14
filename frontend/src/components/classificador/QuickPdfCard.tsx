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
  uploadClassificadorProcessoPdf,
} from "@/services/api";


// Limite por arquivo (deve casar com settings.prazos_iniciais_max_pdf_mb
// no backend e client_max_body_size do nginx — atualmente 200MB).
// Backend roda pikepdf compress apos upload, reduzindo o que persiste.
const MAX_BYTES_PER_FILE = 200 * 1024 * 1024;


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
  const [progress, setProgress] = useState<{ current: number; total: number } | null>(null);
  const [result, setResult] = useState<ClassificadorQuickPdfResult | null>(null);

  const oversized = files.filter(f => f.size > MAX_BYTES_PER_FILE);
  const canSubmit = files.length > 0 && oversized.length === 0 && !submitting;
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
    setProgress({ current: 0, total: files.length });

    const opts = {
      nome: nome.trim() || undefined,
      cliente_nome: clienteNome.trim() || undefined,
      cnj_hint: cnjHint.trim() || undefined,
      produto: produto.trim() || undefined,
      observacao: observacao.trim() || undefined,
    };

    // Estrategia: N+1 requests sequenciais (1 PDF por request).
    // Evita estourar limite de proxy (~210MB por payload) e isola falhas.
    //   - 1ª req: createClassificadorLoteFromPdf (cria lote + sobe 1º PDF)
    //   - 2ª..N: uploadClassificadorProcessoPdf (sobe PDF no lote criado)
    const processos_out: ClassificadorQuickPdfResult["processos"] = [];
    let lote: ClassificadorLoteSummary | null = null;

    try {
      // 1º PDF — cria lote
      try {
        const r1 = await createClassificadorLoteFromPdf([files[0]], opts);
        lote = r1.lote;
        processos_out.push(...r1.processos);
        setProgress({ current: 1, total: files.length });
      } catch (err) {
        // Falha catastrofica no 1º — aborta tudo
        throw err;
      }

      // 2º..N — anexa no lote criado
      for (let i = 1; i < files.length; i++) {
        const file = files[i];
        try {
          const r = await uploadClassificadorProcessoPdf(lote.id, file, {
            cnj_hint: opts.cnj_hint,
            produto: opts.produto,
            observacao: opts.observacao,
          });
          const p = r.processo;
          const isWarning = p.pdf_extraction_failed || p.extraction_confidence === "low";
          processos_out.push({
            filename: file.name,
            ok: !isWarning,
            error_message: isWarning ? (p.error_message || "Extracao parcial — confidence low") : null,
            processo: p,
          });
        } catch (err) {
          processos_out.push({
            filename: file.name,
            ok: false,
            error_message: err instanceof Error ? err.message : String(err),
            processo: null,
          });
        }
        setProgress({ current: i + 1, total: files.length });
      }

      // Resumo
      const ok = processos_out.filter(p => p.ok).length;
      const failed = processos_out.length - ok;
      const summary = { total: processos_out.length, ok, failed };
      const r: ClassificadorQuickPdfResult = { lote, processos: processos_out, summary };
      setResult(r);

      toast({
        title: `Lote #${lote.id} criado`,
        description: `${ok} OK · ${failed} com falha de ${processos_out.length} PDFs.`,
        variant: failed > 0 ? "destructive" : "default",
      });
      const ids = processos_out.filter(p => p.ok && p.processo).map(p => p.processo!.id);
      onCreated(lote, ids);
    } catch (err) {
      toast({
        title: "Falha ao testar PDFs",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setSubmitting(false);
      setProgress(null);
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
                    {files.length > 1 && " · enviados 1 por vez"}
                  </p>
                )}
                {oversized.length > 0 && (
                  <div className="rounded-md border border-red-300 bg-red-50 p-2 text-[11px] text-red-900 mt-1">
                    <strong>{oversized.length} arquivo{oversized.length > 1 ? "s" : ""}</strong> excede{oversized.length === 1 ? "" : "m"} o
                    limite de {(MAX_BYTES_PER_FILE / 1024 / 1024).toFixed(0)}MB por PDF:
                    <ul className="list-disc pl-4 mt-1">
                      {oversized.slice(0, 5).map((f, i) => (
                        <li key={i} className="truncate">{f.name} — {(f.size / 1024 / 1024).toFixed(1)} MB</li>
                      ))}
                      {oversized.length > 5 && <li>+ {oversized.length - 5} mais</li>}
                    </ul>
                  </div>
                )}
                {progress && (
                  <div className="text-xs text-muted-foreground">
                    Enviando {progress.current} de {progress.total}...
                  </div>
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
