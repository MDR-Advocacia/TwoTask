import { useCallback, useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Download,
  FileUp,
  HelpCircle,
  ListChecks,
  Loader2,
  Upload,
  Users,
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
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useToast } from "@/components/ui/use-toast";
import {
  ContatoIssue,
  ContatoPreview,
  createContatosBatch,
  downloadContatosTemplate,
  previewContatosCsv,
} from "@/services/contatosApi";
import ContatosBatchesTable from "@/components/contatos-legalone/ContatosBatchesTable";

function rowLabel(n: number): string {
  return n === 0 ? "Cabeçalho" : `Linha ${n}`;
}

export default function ContatosLegalOnePage() {
  const { toast } = useToast();
  const [tab, setTab] = useState("enviar");
  const [reloadKey, setReloadKey] = useState(0);

  const [file, setFile] = useState<File | null>(null);
  const [nome, setNome] = useState("");
  const [description, setDescription] = useState("");
  const [dryRun, setDryRun] = useState(true);
  const [preview, setPreview] = useState<ContatoPreview | null>(null);
  const [isPreviewing, setIsPreviewing] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isDownloadingTemplate, setIsDownloadingTemplate] = useState(false);
  const [showIssues, setShowIssues] = useState(false);

  const refresh = useCallback(() => setReloadKey((k) => k + 1), []);

  const errors = useMemo(
    () => (preview?.issues ?? []).filter((i) => i.severity === "error"),
    [preview],
  );
  const warnings = useMemo(
    () => (preview?.issues ?? []).filter((i) => i.severity === "warning"),
    [preview],
  );
  const blocked = errors.length > 0;

  const runPreview = useCallback(
    async (f: File) => {
      setIsPreviewing(true);
      try {
        const data = await previewContatosCsv(f);
        setPreview(data);
        if (data.has_blocking) {
          setShowIssues(true);
          toast({
            title: "Planilha bloqueada",
            description: `${data.summary.erros ?? 0} célula(s) fora do padrão impedem o envio.`,
            variant: "destructive",
          });
        }
      } catch (err) {
        toast({
          title: "Falha ao validar a planilha",
          description: err instanceof Error ? err.message : String(err),
          variant: "destructive",
        });
      } finally {
        setIsPreviewing(false);
      }
    },
    [toast],
  );

  const onFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0] ?? null;
    setFile(f);
    setPreview(null);
    if (f) {
      if (!nome) setNome(f.name.replace(/\.csv$/i, ""));
      void runPreview(f);
    }
  };

  const handleTemplateDownload = async () => {
    setIsDownloadingTemplate(true);
    try {
      const blob = await downloadContatosTemplate();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "modelo_atualizacao_contatos.csv";
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      toast({
        title: "Falha ao baixar modelo",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setIsDownloadingTemplate(false);
    }
  };

  const handleSubmit = async () => {
    if (!file || !nome.trim()) {
      toast({ title: "Preencha nome e selecione o CSV.", variant: "destructive" });
      return;
    }
    if (blocked) {
      setShowIssues(true);
      toast({
        title: "Corrija as células bloqueantes antes de enviar.",
        variant: "destructive",
      });
      return;
    }
    setIsSubmitting(true);
    try {
      const { batch } = await createContatosBatch({
        nome: nome.trim(),
        description: description.trim() || undefined,
        dryRun,
        file,
      });
      toast({
        title: dryRun ? "Lote de simulação criado" : "Lote de escrita criado",
        description: `Lote #${batch.id} com ${batch.total_itens} item(ns). Acompanhe na aba Lotes.`,
      });
      setFile(null);
      setNome("");
      setDescription("");
      setPreview(null);
      refresh();
      setTab("lotes");
    } catch (err) {
      // Rede de segurança: o backend também bloqueia (422 com issues).
      if ((err as any)?.issues?.length) {
        setShowIssues(true);
      }
      toast({
        title: "Falha ao criar lote",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  const s = preview?.summary;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-start justify-between gap-2">
        <div className="flex flex-col gap-1">
          <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
            <Users className="h-6 w-6 text-primary" />
            Atualização de Contatos
          </h1>
          <p className="text-sm text-muted-foreground">
            Enriquece contatos já existentes no Legal One (achados pelo CPF/CNPJ) com
            telefones, e-mail e endereço a partir de um CSV. Não cria contatos novos.
          </p>
        </div>
        <InstructionsDialog />
      </div>

      <Tabs value={tab} onValueChange={setTab} className="w-full">
        <TabsList>
          <TabsTrigger value="enviar" className="gap-2">
            <Upload className="h-4 w-4" />
            Enviar
          </TabsTrigger>
          <TabsTrigger value="lotes" className="gap-2">
            <ListChecks className="h-4 w-4" />
            Lotes
          </TabsTrigger>
        </TabsList>

        <TabsContent value="enviar" className="mt-4">
          <Card className="mx-auto max-w-3xl">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-lg">
                <FileUp className="h-5 w-5" />
                Enviar CSV (Dossie com CPF/CNPJ)
              </CardTitle>
              <CardDescription>
                Ao selecionar o arquivo, validamos as células. Se houver erros, o envio
                fica bloqueado até a correção. O arquivo não é guardado — só processado.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-5">
              <div className="flex items-center justify-between rounded-md bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
                <span>Não sabe o formato? Baixe o modelo ou veja "Como preencher".</span>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleTemplateDownload}
                  disabled={isDownloadingTemplate}
                >
                  {isDownloadingTemplate ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <Download className="mr-2 h-4 w-4" />
                  )}
                  Baixar modelo (.csv)
                </Button>
              </div>

              <div className="grid gap-1.5">
                <Label htmlFor="contatos-file">Arquivo CSV</Label>
                <Input
                  id="contatos-file"
                  type="file"
                  accept=".csv,text/csv"
                  onChange={onFileChange}
                  disabled={isSubmitting}
                />
                {isPreviewing && (
                  <p className="flex items-center gap-1 text-xs text-muted-foreground">
                    <Loader2 className="h-3 w-3 animate-spin" /> Validando células...
                  </p>
                )}
              </div>

              <div className="grid gap-1.5">
                <Label htmlFor="contatos-nome">Nome do lote</Label>
                <Input
                  id="contatos-nome"
                  value={nome}
                  onChange={(e) => setNome(e.target.value)}
                  placeholder="Ex.: Dossie cobrança junho/2026"
                  disabled={isSubmitting}
                />
              </div>

              <div className="grid gap-1.5">
                <Label htmlFor="contatos-desc">Descrição (opcional)</Label>
                <Textarea
                  id="contatos-desc"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  rows={2}
                  disabled={isSubmitting}
                />
              </div>

              <div className="flex items-start gap-3 rounded-md border p-3">
                <Checkbox
                  id="contatos-dry"
                  checked={dryRun}
                  onCheckedChange={(c) => setDryRun(!!c)}
                  className="mt-0.5"
                />
                <div className="space-y-0.5">
                  <Label htmlFor="contatos-dry" className="cursor-pointer font-medium">
                    Modo simulação (dry-run)
                  </Label>
                  <p className="text-xs text-muted-foreground">
                    Ligado: mostra o que seria enviado ao Legal One, sem escrever nada.
                    Recomendado na 1ª rodada pra conferir o plano.
                  </p>
                </div>
              </div>

              {!dryRun && (
                <Alert variant="destructive">
                  <AlertTriangle className="h-4 w-4" />
                  <AlertTitle>Escrita real em produção</AlertTitle>
                  <AlertDescription>
                    Com a simulação desligada, telefones/e-mail/endereço serão gravados
                    de verdade nos contatos do Legal One. A operação é idempotente (não
                    duplica), mas é escrita em produção.
                  </AlertDescription>
                </Alert>
              )}

              {preview && s && (
                <Alert variant={blocked ? "destructive" : undefined}>
                  {blocked ? <AlertTriangle className="h-4 w-4" /> : <CheckCircle2 className="h-4 w-4" />}
                  <AlertTitle>
                    {blocked
                      ? `Planilha bloqueada — ${errors.length} erro(s) a corrigir`
                      : `Planilha validada — ${preview.filename}`}
                  </AlertTitle>
                  <AlertDescription>
                    <div className="mt-1 flex flex-wrap gap-2">
                      <Badge variant="outline">Linhas: {s.total_linhas}</Badge>
                      <Badge className="bg-green-100 text-green-800">Válidas: {s.validas}</Badge>
                      {(s.erros ?? 0) > 0 && <Badge variant="destructive">Erros: {s.erros}</Badge>}
                      {(s.alertas ?? 0) > 0 && (
                        <Badge className="bg-amber-100 text-amber-800">Alertas: {s.alertas}</Badge>
                      )}
                      <Badge variant="outline">CPF: {s.cpf}</Badge>
                      <Badge variant="outline">CNPJ: {s.cnpj}</Badge>
                      <Badge variant="outline">c/ nome: {s.com_nome}</Badge>
                      <Badge variant="outline">c/ telefone: {s.com_telefone}</Badge>
                      <Badge variant="outline">c/ e-mail: {s.com_email}</Badge>
                      <Badge variant="outline">c/ endereço: {s.com_endereco}</Badge>
                    </div>
                    {(errors.length > 0 || warnings.length > 0) && (
                      <Button
                        variant="link"
                        className="mt-1 h-auto p-0 text-xs"
                        onClick={() => setShowIssues(true)}
                      >
                        Ver problemas ({errors.length + warnings.length})
                      </Button>
                    )}
                  </AlertDescription>
                </Alert>
              )}

              <div className="flex flex-col gap-3 sm:flex-row">
                <Button
                  variant="outline"
                  className="flex-1"
                  onClick={() => file && runPreview(file)}
                  disabled={!file || isPreviewing || isSubmitting}
                >
                  {isPreviewing ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <CheckCircle2 className="mr-2 h-4 w-4" />}
                  Revalidar
                </Button>
                <Button
                  className="flex-1"
                  onClick={handleSubmit}
                  disabled={!file || !nome.trim() || isSubmitting || isPreviewing || blocked}
                  variant={dryRun ? "default" : "destructive"}
                  title={blocked ? "Corrija as células bloqueantes primeiro" : undefined}
                >
                  {isSubmitting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Upload className="mr-2 h-4 w-4" />}
                  {dryRun ? "Criar lote (simulação)" : "Criar lote (escrita real)"}
                </Button>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="lotes" className="mt-4">
          <ContatosBatchesTable reloadKey={reloadKey} onChanged={refresh} />
        </TabsContent>
      </Tabs>

      <IssuesDialog
        open={showIssues}
        onOpenChange={setShowIssues}
        errors={errors}
        warnings={warnings}
      />
    </div>
  );
}

// ─── Modal de problemas (célula + erro) ──────────────────────────────────

function IssuesDialog({
  open,
  onOpenChange,
  errors,
  warnings,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  errors: ContatoIssue[];
  warnings: ContatoIssue[];
}) {
  const all = [...errors, ...warnings];
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <AlertTriangle className="h-5 w-5 text-amber-600" />
            Revisão da planilha
          </DialogTitle>
          <DialogDescription>
            {errors.length > 0
              ? `${errors.length} erro(s) impedem o envio. Corrija as células no arquivo e selecione de novo.`
              : "Nenhum erro bloqueante. Os alertas abaixo serão ignorados/tratados no processamento."}
          </DialogDescription>
        </DialogHeader>

        <div className="rounded-md border">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left text-xs text-muted-foreground">
                <th className="p-2">Onde</th>
                <th className="p-2">Coluna</th>
                <th className="p-2">Valor</th>
                <th className="p-2">Problema</th>
              </tr>
            </thead>
            <tbody>
              {all.map((it, i) => (
                <tr key={i} className="border-b align-top last:border-0">
                  <td className="whitespace-nowrap p-2">
                    <span
                      className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${
                        it.severity === "error"
                          ? "bg-red-100 text-red-700"
                          : "bg-amber-100 text-amber-800"
                      }`}
                    >
                      {it.severity === "error" ? "Erro" : "Alerta"}
                    </span>
                    <div className="mt-0.5 text-xs text-muted-foreground">{rowLabel(it.row_number)}</div>
                  </td>
                  <td className="p-2 font-mono text-xs">{it.column}</td>
                  <td className="max-w-[12rem] truncate p-2 font-mono text-xs" title={it.value}>
                    {it.value || "—"}
                  </td>
                  <td className="p-2 text-xs">{it.error}</td>
                </tr>
              ))}
              {all.length === 0 && (
                <tr>
                  <td colSpan={4} className="p-6 text-center text-sm text-muted-foreground">
                    Nenhum problema encontrado.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="flex justify-end">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Fechar
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

// ─── Modal de instruções de preenchimento ────────────────────────────────

function InstructionsDialog() {
  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" className="shrink-0">
          <HelpCircle className="mr-2 h-4 w-4" />
          Como preencher
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-2xl max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Como preencher o CSV de contatos</DialogTitle>
          <DialogDescription>
            Cada linha enriquece um contato já existente no Legal One, localizado pelo
            CPF/CNPJ. O arquivo não cria contatos novos.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4 text-sm">
          <section className="space-y-1">
            <h4 className="font-semibold">Identificação (obrigatória)</h4>
            <ul className="list-disc space-y-1 pl-5 text-muted-foreground">
              <li>
                <strong>CPF_CNPJ</strong> — com máscara. <strong>11 dígitos</strong> = CPF
                (pessoa física), <strong>14</strong> = CNPJ (pessoa jurídica). Qualquer
                outra quantidade <strong>bloqueia</strong> o envio.
              </li>
              <li>
                É a <strong>única coluna obrigatória</strong>. Todas as outras são
                opcionais — dá pra subir <strong>atualizações parciais</strong> (ex.: só o
                nome, ou só o e-mail). Colunas que faltarem são simplesmente ignoradas.
              </li>
            </ul>
          </section>
          <section className="space-y-1">
            <h4 className="font-semibold">Nome (opcional)</h4>
            <ul className="list-disc space-y-1 pl-5 text-muted-foreground">
              <li>
                <strong>NOME</strong> — ajusta o nome da pessoa/empresa no Legal One. Só é
                alterado quando preenchido e diferente do atual; célula vazia não apaga o
                nome existente. Bom pra completar lotes enviados sem nome.
              </li>
              <li>
                <strong>NOME_ABREVIADO</strong> é só rótulo da campanha — <em>não</em> é o
                nome da pessoa e não altera o contato.
              </li>
            </ul>
          </section>
          <section className="space-y-1">
            <h4 className="font-semibold">Telefones (opcional, até 3)</h4>
            <ul className="list-disc space-y-1 pl-5 text-muted-foreground">
              <li><strong>DDD</strong> + <strong>TELEFONE</strong> (e DDD2/TELEFONE2, DDD3/TELEFONE3).</li>
              <li>O número é montado como DDD+telefone. Esperado 10 ou 11 dígitos com DDD.</li>
            </ul>
          </section>
          <section className="space-y-1">
            <h4 className="font-semibold">E-mail e endereço (opcional)</h4>
            <ul className="list-disc space-y-1 pl-5 text-muted-foreground">
              <li><strong>EMAIL</strong> — precisa ter "@"; fora do padrão é ignorado.</li>
              <li>
                <strong>LOGRADOURO, NUMERO, COMPLEMENTO, BAIRRO, CIDADE, UF, CEP</strong> —
                o endereço só é enviado se tiver pelo menos <strong>LOGRADOURO + CIDADE + UF</strong>.
                UF com 2 letras; CEP com 8 dígitos.
              </li>
            </ul>
          </section>
          <section className="space-y-1">
            <h4 className="font-semibold">Vários telefones / e-mails / endereços</h4>
            <ul className="list-disc space-y-1 pl-5 text-muted-foreground">
              <li>
                <strong>Telefones:</strong> até 3 por linha (DDD/TELEFONE, DDD2/TELEFONE2,
                DDD3/TELEFONE3).
              </li>
              <li>
                <strong>Mais de um e-mail ou endereço</strong> (ou mais de 3 telefones):
                repita o <strong>mesmo CPF/CNPJ em linhas diferentes</strong>, cada uma com
                um valor. O sistema acumula sem duplicar — o 1º e-mail/endereço vira o
                principal e os seguintes entram como adicionais.
              </li>
            </ul>
          </section>
          <section className="space-y-1">
            <h4 className="font-semibold">Convenções</h4>
            <ul className="list-disc space-y-1 pl-5 text-muted-foreground">
              <li>O literal <code>NULL</code> (e célula vazia) = ausente.</li>
              <li>Delimitador <code>;</code> (padrão BR); o sistema também aceita <code>,</code>.</li>
              <li>
                Nada é gravado em duplicidade: telefone/e-mail/endereço já existentes no
                contato são pulados.
              </li>
              <li>Comece pelo <strong>modelo</strong> e rode em <strong>simulação</strong> antes da escrita real.</li>
            </ul>
          </section>
        </div>
      </DialogContent>
    </Dialog>
  );
}
