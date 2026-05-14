// frontend/src/components/classificador/ProcessoDetailDrawer.tsx
//
// Drawer lateral que mostra o detalhe completo de 1 processo do
// Classificador. Carrega via GET /lotes/{id}/processos/{id} quando abre.
//
// 9 secoes colapsaveis: Capa, Classificacao IA, Pedidos, Patrocinio,
// Contestacao, Sentenca/Transito, Primeira Habilitacao Master,
// Metadados, Texto bruto (capa/integra JSON).

import { useEffect, useState } from "react";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  Loader2,
  ChevronDown,
  ChevronRight,
  FileText,
  Sparkles,
  Scale,
  Building2,
  Gavel,
  CalendarCheck2,
  User,
  Settings2,
  FileJson,
  Copy,
} from "lucide-react";
import { useToast } from "@/components/ui/use-toast";
import {
  ClassificadorProcessoDetail,
  fetchClassificadorProcessoDetail,
} from "@/services/api";


interface Props {
  loteId: number | null;
  processoId: number | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}


// ─── Helpers ──────────────────────────────────────────────────────────

function fmtBRL(v: number | null | undefined): string {
  if (v == null) return "—";
  return v.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

function fmtPct(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${(v * 100).toFixed(1)}%`;
}

function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
  } catch {
    return iso;
  }
}

function fmtDate(s: string | null | undefined): string {
  if (!s) return "—";
  try {
    return new Date(s).toLocaleDateString("pt-BR");
  } catch {
    return s;
  }
}

function fmtBool(v: unknown): string {
  if (v === null || v === undefined) return "—";
  return v ? "Sim" : "Nao";
}


// ─── Section + Field components ──────────────────────────────────────

function Section({
  icon: Icon,
  title,
  defaultOpen = true,
  children,
}: {
  icon: React.ElementType;
  title: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <Collapsible open={open} onOpenChange={setOpen} className="border rounded-md">
      <CollapsibleTrigger asChild>
        <button className="flex items-center w-full px-3 py-2 text-left bg-muted/40 hover:bg-muted/60 transition rounded-t-md">
          {open ? <ChevronDown className="h-4 w-4 mr-2" /> : <ChevronRight className="h-4 w-4 mr-2" />}
          <Icon className="h-4 w-4 mr-2 text-primary" />
          <span className="text-sm font-medium">{title}</span>
        </button>
      </CollapsibleTrigger>
      <CollapsibleContent className="px-3 py-3 text-xs">
        {children}
      </CollapsibleContent>
    </Collapsible>
  );
}

function Field({ label, value, mono = false, full = false }: {
  label: string;
  value: React.ReactNode;
  mono?: boolean;
  full?: boolean;
}) {
  const isEmpty = value === null || value === undefined || value === "" || value === "—";
  return (
    <div className={full ? "col-span-2" : "col-span-1"}>
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className={`${mono ? "font-mono" : ""} ${isEmpty ? "text-muted-foreground italic" : ""} text-xs break-words`}>
        {isEmpty ? "—" : value}
      </div>
    </div>
  );
}

function JsonPre({ value }: { value: unknown }) {
  let s: string;
  try {
    s = JSON.stringify(value, null, 2);
  } catch {
    s = String(value);
  }
  return (
    <pre className="text-[10px] bg-muted/30 p-2 rounded max-h-96 overflow-auto whitespace-pre-wrap">
      {s}
    </pre>
  );
}


// ─── Componente principal ────────────────────────────────────────────

export default function ProcessoDetailDrawer({
  loteId, processoId, open, onOpenChange,
}: Props) {
  const { toast } = useToast();
  const [data, setData] = useState<ClassificadorProcessoDetail | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open || !loteId || !processoId) {
      setData(null);
      return;
    }
    let alive = true;
    setLoading(true);
    fetchClassificadorProcessoDetail(loteId, processoId)
      .then(d => { if (alive) setData(d); })
      .catch(err => {
        if (!alive) return;
        toast({
          title: "Falha ao carregar detalhe do processo",
          description: err instanceof Error ? err.message : String(err),
          variant: "destructive",
        });
      })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [open, loteId, processoId, toast]);

  const handleCopyCnj = () => {
    if (data?.cnj_number) {
      navigator.clipboard.writeText(data.cnj_number).catch(() => {});
      toast({ title: "CNJ copiado" });
    }
  };

  // Extrai sentenca / transito / primeira_hab do JSON cru da IA
  const respIA = (data?.classificacao_response_json || {}) as Record<string, any>;
  const sentenca = respIA.sentenca as Record<string, any> | undefined;
  const transito = respIA.transito_julgado as Record<string, any> | undefined;
  const primeiraHab = respIA.primeira_habilitacao_master as Record<string, any> | undefined;
  const patrocinio = (data?.patrocinio_json || {}) as Record<string, any>;
  const contestacao = (data?.contestacao_existente_json || {}) as Record<string, any>;
  const capa = (data?.capa_json || {}) as Record<string, any>;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full sm:max-w-2xl overflow-y-auto">
        <SheetHeader className="space-y-2 pb-3 border-b">
          <SheetTitle className="text-base flex items-center gap-2">
            {loading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <FileText className="h-4 w-4" />
            )}
            Processo #{processoId}
            {data?.cnj_number && (
              <span className="font-mono text-sm text-muted-foreground">· {data.cnj_number}</span>
            )}
            {data?.cnj_number && (
              <Button variant="ghost" size="icon" className="h-6 w-6" onClick={handleCopyCnj}>
                <Copy className="h-3 w-3" />
              </Button>
            )}
          </SheetTitle>
          <SheetDescription className="flex flex-wrap items-center gap-1 text-xs">
            {data && (
              <>
                <Badge variant="outline">{data.status}</Badge>
                {data.extractor_used && (
                  <Badge variant="outline">extractor: {data.extractor_used}</Badge>
                )}
                {data.extraction_confidence && (
                  <Badge variant="outline">conf: {data.extraction_confidence}</Badge>
                )}
                {data.source && <Badge variant="outline">{data.source}</Badge>}
                {data.polo && <Badge variant="outline">polo: {data.polo}</Badge>}
              </>
            )}
          </SheetDescription>
        </SheetHeader>

        {loading && !data ? (
          <div className="py-12 text-center text-sm text-muted-foreground">
            <Loader2 className="inline h-4 w-4 animate-spin mr-2" />
            Carregando detalhe...
          </div>
        ) : !data ? (
          <div className="py-12 text-center text-sm text-muted-foreground">
            Sem dados.
          </div>
        ) : (
          <div className="space-y-3 mt-3">

            {/* ─── 1. Capa do processo ─── */}
            <Section icon={Scale} title="Capa do processo" defaultOpen={true}>
              <div className="grid grid-cols-2 gap-2">
                <Field label="CNJ" value={data.cnj_number} mono />
                <Field label="Lawsuit ID (L1)" value={data.lawsuit_id} mono />
                <Field label="Tribunal" value={capa.tribunal as string} />
                <Field label="Vara" value={(capa.vara || capa.orgao_julgador) as string} />
                <Field label="Classe" value={capa.classe as string} />
                <Field label="Valor da causa" value={fmtBRL(capa.valor_causa as number)} />
                <Field label="Natureza do processo" value={data.natureza_processo} />
                <Field label="Produto" value={data.produto} />
                <Field label="Data distribuicao" value={fmtDate(capa.data_distribuicao as string)} />
                <Field label="Segredo de justica" value={fmtBool(capa.segredo_justica)} />
              </div>
            </Section>

            {/* ─── 2. Partes ─── */}
            <Section icon={User} title="Partes" defaultOpen={false}>
              <div className="space-y-2">
                <div>
                  <div className="text-[10px] uppercase tracking-wide text-muted-foreground mb-1">Polo ativo</div>
                  <JsonPre value={data.polo_ativo} />
                </div>
                <div>
                  <div className="text-[10px] uppercase tracking-wide text-muted-foreground mb-1">Polo passivo</div>
                  <JsonPre value={data.polo_passivo} />
                </div>
              </div>
            </Section>

            {/* ─── 3. Classificacao IA ─── */}
            <Section icon={Sparkles} title="Classificacao IA" defaultOpen={true}>
              <div className="grid grid-cols-2 gap-2">
                <Field label="Categoria" value={data.categoria_nome} full />
                <Field label="Subcategoria" value={data.subcategoria_nome} full />
                <Field label="Polo do MDR" value={data.polo} />
                <Field label="Confianca da IA" value={fmtPct(data.confianca)} />
                <Field label="Valor estimado total" value={fmtBRL(data.valor_estimado)} />
                <Field label="PCOND total (CPC 25)" value={fmtBRL(data.pcond_sugerido)} />
                <Field label="Prob. exito global" value={fmtPct(data.prob_exito)} full />
                <Field label="Analise estrategica" value={data.analise_estrategica} full />
                <Field label="Observacoes" value={data.justificativa} full />
              </div>
            </Section>

            {/* ─── 4. Pedidos ─── */}
            <Section icon={Gavel} title={`Pedidos (${data.pedidos.length})`} defaultOpen={true}>
              {data.pedidos.length === 0 ? (
                <div className="text-muted-foreground italic">Nenhum pedido extraido.</div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-[11px]">
                    <thead>
                      <tr className="border-b text-left text-muted-foreground">
                        <th className="py-1 pr-2">Tipo</th>
                        <th className="py-1 pr-2">Natureza</th>
                        <th className="py-1 pr-2 text-right">Indicado</th>
                        <th className="py-1 pr-2 text-right">Estimado</th>
                        <th className="py-1 pr-2">Prob. perda</th>
                        <th className="py-1 pr-2 text-right">PCOND</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.pedidos.map(p => (
                        <tr key={p.id} className="border-b">
                          <td className="py-1 pr-2 font-mono">{p.tipo_pedido}</td>
                          <td className="py-1 pr-2">{p.natureza || "—"}</td>
                          <td className="py-1 pr-2 text-right tabular-nums">{fmtBRL(p.valor_indicado)}</td>
                          <td className="py-1 pr-2 text-right tabular-nums">{fmtBRL(p.valor_estimado)}</td>
                          <td className="py-1 pr-2">{p.probabilidade_perda || "—"}</td>
                          <td className="py-1 pr-2 text-right tabular-nums">{fmtBRL(p.aprovisionamento)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {/* Fundamentacoes (expanded) */}
                  {data.pedidos.some(p => p.fundamentacao_valor || p.fundamentacao_risco) && (
                    <details className="mt-2">
                      <summary className="cursor-pointer text-[10px] text-muted-foreground">Ver fundamentacoes</summary>
                      <div className="space-y-2 mt-2">
                        {data.pedidos.map(p => (
                          <div key={`f-${p.id}`} className="rounded border p-2 bg-muted/20">
                            <div className="font-mono text-[10px] text-muted-foreground">#{p.id} · {p.tipo_pedido}</div>
                            {p.fundamentacao_valor && (
                              <div className="mt-1"><strong className="text-[10px]">Valor:</strong> {p.fundamentacao_valor}</div>
                            )}
                            {p.fundamentacao_risco && (
                              <div className="mt-1"><strong className="text-[10px]">Risco:</strong> {p.fundamentacao_risco}</div>
                            )}
                          </div>
                        ))}
                      </div>
                    </details>
                  )}
                </div>
              )}
            </Section>

            {/* ─── 5. Patrocinio ─── */}
            <Section icon={Building2} title="Patrocinio (Master)" defaultOpen={true}>
              {!patrocinio.aplicavel ? (
                <div className="text-muted-foreground italic">
                  Nao aplicavel (polo passivo nao bate com vinculadas Master).
                </div>
              ) : (
                <div className="grid grid-cols-2 gap-2">
                  <Field label="Decisao" value={patrocinio.decisao as string} />
                  <Field label="Natureza da acao" value={patrocinio.natureza_acao as string} />
                  <Field label="Outro escritorio" value={patrocinio.outro_escritorio_nome as string} full />
                  <Field label="Outro advogado" value={patrocinio.outro_advogado_nome as string} />
                  <Field label="OAB" value={patrocinio.outro_advogado_oab as string} />
                  <Field label="Data habilitacao" value={fmtDate(patrocinio.outro_advogado_data_habilitacao as string)} />
                  <Field label="Suspeita devolucao" value={fmtBool(patrocinio.suspeita_devolucao)} />
                  <Field label="Motivo suspeita" value={patrocinio.motivo_suspeita as string} full />
                  <Field label="Polo passivo confirmado" value={fmtBool(patrocinio.polo_passivo_confirmado)} />
                  <Field label="Confianca" value={patrocinio.confianca as string} />
                  <Field label="Fundamentacao" value={patrocinio.fundamentacao as string} full />
                </div>
              )}
            </Section>

            {/* ─── 6. Contestacao existente ─── */}
            <Section icon={FileText} title="Contestacao existente" defaultOpen={true}>
              {!contestacao.existe ? (
                <div className="text-muted-foreground italic">
                  Nenhuma contestacao do Master/vinculada detectada.
                </div>
              ) : (
                <div className="grid grid-cols-2 gap-2">
                  <Field label="Apresentada pelo MDR?" value={fmtBool(contestacao.apresentada_por_mdr)} />
                  <Field label="Data apresentacao" value={fmtDate(contestacao.data_apresentacao as string)} />
                  <Field label="Apresentada por (nome)" value={contestacao.apresentada_por_nome as string} />
                  <Field label="OAB" value={contestacao.apresentada_por_oab as string} />
                  <Field label="Parte representada" value={contestacao.parte_representada as string} full />
                  <Field label="Generica (mecanico)" value={fmtBool(contestacao.generica)} />
                  <Field label="Analise da juntada" value={contestacao.analise_qualidade as string} full />
                  <Field label="Justificativa" value={contestacao.justificativa as string} full />
                </div>
              )}
            </Section>

            {/* ─── 7. Sentenca + Transito ─── */}
            <Section icon={CalendarCheck2} title="Sentenca + Transito em julgado" defaultOpen={true}>
              <div className="space-y-3">
                {sentenca?.existe ? (
                  <div className="grid grid-cols-2 gap-2">
                    <Field label="Tipo sentenca" value={sentenca.tipo as string} />
                    <Field label="Data sentenca" value={fmtDate(sentenca.data as string)} />
                    <Field label="Valor condenacao" value={fmtBRL(sentenca.valor_condenacao as number)} />
                    <Field label="Resumo dispositivo" value={sentenca.resumo as string} full />
                    <Field label="Fundamentacao" value={sentenca.fundamentacao as string} full />
                  </div>
                ) : (
                  <div className="text-muted-foreground italic">Sem sentenca registrada.</div>
                )}
                <div className="pt-2 border-t">
                  <div className="text-[10px] uppercase tracking-wide text-muted-foreground mb-1">
                    Transito em julgado
                  </div>
                  {transito?.transitado ? (
                    <div className="grid grid-cols-2 gap-2">
                      <Field label="Transitado" value="Sim" />
                      <Field label="Data" value={fmtDate(transito.data as string)} />
                      <Field label="Fundamentacao" value={transito.fundamentacao as string} full />
                    </div>
                  ) : (
                    <div className="text-muted-foreground italic">Nao transitou.</div>
                  )}
                </div>
              </div>
            </Section>

            {/* ─── 8. Primeira Habilitacao Master ─── */}
            <Section icon={User} title="Primeira habilitacao Master" defaultOpen={true}>
              {!primeiraHab?.existe ? (
                <div className="text-muted-foreground italic">
                  Nenhuma habilitacao em nome do Master/vinculada detectada.
                </div>
              ) : (
                <div className="grid grid-cols-2 gap-2">
                  <Field label="Advogado" value={primeiraHab.advogado_nome as string} />
                  <Field label="OAB" value={primeiraHab.advogado_oab as string} />
                  <Field label="Escritorio" value={primeiraHab.escritorio_nome as string} />
                  <Field label="Data habilitacao" value={fmtDate(primeiraHab.data_habilitacao as string)} />
                  <Field label="Parte representada" value={primeiraHab.parte_representada as string} full />
                </div>
              )}
            </Section>

            {/* ─── 9. Metadados ─── */}
            <Section icon={Settings2} title="Metadados" defaultOpen={false}>
              <div className="grid grid-cols-2 gap-2">
                <Field label="Source" value={data.source} />
                <Field label="Source intake ID (PI)" value={data.source_intake_id} mono />
                <Field label="PDF filename" value={data.pdf_filename_original} />
                <Field label="PDF SHA256" value={data.pdf_sha256 ? `${data.pdf_sha256.slice(0, 16)}...` : null} mono />
                <Field label="PDF bytes" value={data.pdf_bytes != null ? `${(data.pdf_bytes / 1024).toFixed(1)} KB` : null} />
                <Field label="Extractor mecanico" value={data.extractor_used} />
                <Field label="Confidence extracao" value={data.extraction_confidence} />
                <Field label="PDF falhou?" value={fmtBool(data.pdf_extraction_failed)} />
                <Field label="Batch ID classificacao" value={data.classification_batch_id} mono />
                <Field label="Data captura L1" value={fmtDateTime(data.data_captura_l1)} />
                <Field label="Data classificacao" value={fmtDateTime(data.data_classificacao)} />
                <Field label="Criado em" value={fmtDateTime(data.created_at)} />
                {data.error_message && (
                  <Field label="Erro" value={<span className="text-red-700">{data.error_message}</span>} full />
                )}
              </div>
            </Section>

            {/* ─── 10. Texto bruto (capa + integra JSON) ─── */}
            <Section icon={FileJson} title="Texto bruto (capa + integra)" defaultOpen={false}>
              <div className="space-y-2">
                <div>
                  <div className="text-[10px] uppercase tracking-wide text-muted-foreground mb-1">capa_json</div>
                  <JsonPre value={data.capa_json} />
                </div>
                <div>
                  <div className="text-[10px] uppercase tracking-wide text-muted-foreground mb-1">integra_json</div>
                  <JsonPre value={data.integra_json} />
                </div>
                <div>
                  <div className="text-[10px] uppercase tracking-wide text-muted-foreground mb-1">
                    classificacao_response_json (resposta crua da IA)
                  </div>
                  <JsonPre value={data.classificacao_response_json} />
                </div>
              </div>
            </Section>
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
