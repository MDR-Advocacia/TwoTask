import CancelamentoAutomaticoSection from "@/components/performance/CancelamentoAutomaticoSection";

export default function CancelamentoDuplicadasPage() {
  return (
    <div className="mx-auto max-w-4xl space-y-4 p-4 lg:p-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Cancelar Duplicadas</h1>
        <p className="text-sm text-muted-foreground">
          Whitelist de subtipos liberados + rotina automática da madrugada (sobre o pool fresco) + auditoria das
          execuções. Cancela só duplicadas (mesma pasta + mesmo subtipo) dos subtipos liberados, mantendo a mais antiga.
        </p>
      </div>
      <CancelamentoAutomaticoSection />
    </div>
  );
}
