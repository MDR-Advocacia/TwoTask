/**
 * Pagina principal do modulo Base Processual (admin/flow).
 *
 * Sub-abas:
 * - Visao Geral (Chunk 2): dashboard com KPIs + serie diaria + movimentacao do dia.
 * - Uploads (Chunk 2): drag-and-drop XLSX + dry-run preview + commit + historico.
 * - Processos (Chunk 3): tabela paginada + drawer + filtros + diff.
 * - Eventos (Chunk 4): auditoria cross-upload.
 * - Relatorios (Chunk 5): exports XLSX templados.
 * - API Keys (Chunk 6): chaves pra consumidores externos.
 */

import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { UploadsTab } from "@/components/base-processual/UploadsTab";
import { VisaoGeralTab } from "@/components/base-processual/VisaoGeralTab";

export function BaseProcessualPage() {
  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-2xl font-semibold tracking-tight">Base Processual</h2>
        <p className="text-sm text-muted-foreground">
          Base centralizada da carteira. Suba o XLSX diario do Legal One pra detectar
          quem entrou, quem saiu e o que mudou.
        </p>
      </div>

      <Tabs defaultValue="visao-geral" className="w-full">
        <TabsList>
          <TabsTrigger value="visao-geral">Visão Geral</TabsTrigger>
          <TabsTrigger value="uploads">Uploads</TabsTrigger>
          <TabsTrigger value="processos" disabled>
            Processos
          </TabsTrigger>
          <TabsTrigger value="eventos" disabled>
            Eventos
          </TabsTrigger>
          <TabsTrigger value="relatorios" disabled>
            Relatórios
          </TabsTrigger>
          <TabsTrigger value="api-keys" disabled>
            API Keys
          </TabsTrigger>
        </TabsList>

        <TabsContent value="visao-geral" className="mt-4">
          <VisaoGeralTab />
        </TabsContent>
        <TabsContent value="uploads" className="mt-4">
          <UploadsTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
