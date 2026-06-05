// frontend/src/pages/GedLegalOnePage.tsx
//
// Pagina do modulo GED LegalOne — envio em lote de arquivos pro GED (ECM)
// de processos no Legal One a partir de CNJ + arquivo.
//
// - Aba "Enviar": 2 modos (1 arquivo -> N processos | N arquivos -> N processos).
// - Aba "Lotes": tabela paginada dos envios, com acompanhamento ao vivo.

import { useCallback, useEffect, useState } from "react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Upload, FileUp, Files, ListChecks } from "lucide-react";
import {
  listGedDocumentTypes,
  GedDocumentType,
  GedUploadBatch,
} from "@/services/api";
import UploadSingleFileDialog from "@/components/ged-legalone/UploadSingleFileDialog";
import UploadMultiFileDialog from "@/components/ged-legalone/UploadMultiFileDialog";
import BatchesTable from "@/components/ged-legalone/BatchesTable";
import BatchDetailDialog from "@/components/ged-legalone/BatchDetailDialog";

export default function GedLegalOnePage() {
  const [tab, setTab] = useState("enviar");
  const [reloadKey, setReloadKey] = useState(0);
  const [documentTypes, setDocumentTypes] = useState<GedDocumentType[]>([]);
  const [singleOpen, setSingleOpen] = useState(false);
  const [multiOpen, setMultiOpen] = useState(false);
  // Abre o acompanhamento do lote recem-criado.
  const [createdBatchId, setCreatedBatchId] = useState<number | null>(null);

  useEffect(() => {
    listGedDocumentTypes()
      .then(setDocumentTypes)
      .catch(() => setDocumentTypes([]));
  }, []);

  const refresh = useCallback(() => setReloadKey((k) => k + 1), []);

  const handleCreated = useCallback(
    (batch: GedUploadBatch) => {
      refresh();
      setTab("lotes");
      setCreatedBatchId(batch.id);
    },
    [refresh],
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
          <Upload className="h-6 w-6 text-primary" />
          GED LegalOne
        </h1>
        <p className="text-sm text-muted-foreground">
          Envio em lote de arquivos pro GED (ECM) de processos no Legal One, a
          partir de CNJ + arquivo. Aceita PDF, Word, Excel, imagens e mais.
        </p>
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
          <div className="grid gap-4 md:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-lg">
                  <FileUp className="h-5 w-5" />
                  Um arquivo para varios processos
                </CardTitle>
                <CardDescription>
                  Envia o MESMO arquivo pro GED de todos os CNJs que voce colar.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <Button className="w-full" onClick={() => setSingleOpen(true)}>
                  Enviar arquivo unico
                </Button>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-lg">
                  <Files className="h-5 w-5" />
                  Varios arquivos para varios processos
                </CardTitle>
                <CardDescription>
                  Cada arquivo vai pro CNJ do seu nome (corrigivel na tabela).
                </CardDescription>
              </CardHeader>
              <CardContent>
                <Button className="w-full" variant="outline" onClick={() => setMultiOpen(true)}>
                  Enviar varios arquivos
                </Button>
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        <TabsContent value="lotes" className="mt-4">
          <BatchesTable reloadKey={reloadKey} onChanged={refresh} />
        </TabsContent>
      </Tabs>

      <UploadSingleFileDialog
        open={singleOpen}
        onOpenChange={setSingleOpen}
        documentTypes={documentTypes}
        onCreated={handleCreated}
      />
      <UploadMultiFileDialog
        open={multiOpen}
        onOpenChange={setMultiOpen}
        documentTypes={documentTypes}
        onCreated={handleCreated}
      />
      <BatchDetailDialog
        batchId={createdBatchId}
        open={createdBatchId != null}
        onOpenChange={(v) => !v && setCreatedBatchId(null)}
        onChanged={refresh}
      />
    </div>
  );
}
