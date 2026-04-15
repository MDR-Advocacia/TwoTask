import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { CheckCircle2, AlertTriangle, AlertCircle, Clock, Loader2, RefreshCw } from 'lucide-react';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { useToast } from '@/hooks/use-toast';
import { useAuth } from '@/hooks/useAuth';
import { apiFetch } from '@/lib/api-client';

interface OfficeHealth {
  office_id: number;
  office_name: string | null;
  last_successful_date: string | null;
  last_run_at: string | null;
  last_status: string | null;
  last_error: string | null;
  consecutive_failures: number;
  next_retry_at: string | null;
  health: 'ok' | 'warning' | 'critical' | 'dead_letter' | 'never_ran';
}

interface CaptureHealthSummary {
  total_offices: number;
  ok: number;
  warning: number;
  critical: number;
  dead_letter: number;
  never_ran: number;
  offices: OfficeHealth[];
}

const healthMeta: Record<OfficeHealth['health'], { label: string; color: string; icon: typeof CheckCircle2 }> = {
  ok:          { label: 'OK',           color: 'bg-green-100 text-green-800 border-green-300',   icon: CheckCircle2 },
  warning:     { label: 'Atenção',      color: 'bg-yellow-100 text-yellow-800 border-yellow-300', icon: AlertTriangle },
  critical:    { label: 'Crítico',      color: 'bg-orange-100 text-orange-800 border-orange-300', icon: AlertCircle },
  dead_letter: { label: 'Dead-letter',  color: 'bg-red-100 text-red-800 border-red-300',          icon: AlertCircle },
  never_ran:   { label: 'Sem histórico', color: 'bg-gray-100 text-gray-700 border-gray-300',      icon: Clock },
};

const formatRelative = (iso: string | null) => {
  if (!iso) return 'nunca';
  const diffMs = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return 'agora';
  if (mins < 60) return `há ${mins} min`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `há ${hours}h`;
  return `há ${Math.floor(hours / 24)}d`;
};

const formatAbsolute = (iso: string | null) => {
  if (!iso) return '—';
  return new Intl.DateTimeFormat('pt-BR', {
    dateStyle: 'short',
    timeStyle: 'short',
    timeZone: 'America/Sao_Paulo',
  }).format(new Date(iso));
};

export const CaptureHealthWidget = () => {
  const { toast } = useToast();
  const { isAdmin } = useAuth();
  const queryClient = useQueryClient();
  const [resetting, setResetting] = useState<number | null>(null);

  const { data, isLoading } = useQuery<CaptureHealthSummary>({
    queryKey: ['capture-health'],
    queryFn: async () => {
      const res = await apiFetch('/api/v1/admin/capture-health');
      if (!res.ok) throw new Error('Falha ao carregar saúde da captura.');
      return res.json();
    },
    refetchInterval: 60000, // atualiza a cada 1 min
  });

  const handleReset = async (officeId: number) => {
    if (!confirm('Resetar o contador de falhas deste escritório? A próxima execução tentará normalmente.')) return;
    setResetting(officeId);
    try {
      const res = await apiFetch(`/api/v1/admin/capture-health/${officeId}/reset`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      if (!res.ok) throw new Error((await res.json()).detail || 'Erro ao resetar.');
      toast({ title: 'Captura resetada', description: 'O escritório voltará a ser processado na próxima rodada.' });
      queryClient.invalidateQueries({ queryKey: ['capture-health'] });
    } catch (e: any) {
      toast({ title: 'Erro', description: e.message, variant: 'destructive' });
    } finally {
      setResetting(null);
    }
  };

  if (isLoading) {
    return (
      <Card>
        <CardContent className="p-6 flex justify-center">
          <Loader2 className="h-6 w-6 animate-spin" />
        </CardContent>
      </Card>
    );
  }

  if (!data) return null;

  const hasProblems = data.warning + data.critical + data.dead_letter > 0;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between">
          <span>Saúde da Captura de Publicações</span>
          {hasProblems && (
            <Badge variant="destructive">
              {data.critical + data.dead_letter} problema(s) ativo(s)
            </Badge>
          )}
        </CardTitle>
        <CardDescription>
          Estado por escritório — janela de tolerância: 6h. Atualiza a cada 1 minuto.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Contadores resumidos */}
        <div className="grid grid-cols-5 gap-2 text-center">
          <div className="p-2 rounded border bg-green-50">
            <div className="text-2xl font-bold text-green-700">{data.ok}</div>
            <div className="text-xs text-muted-foreground">OK</div>
          </div>
          <div className="p-2 rounded border bg-yellow-50">
            <div className="text-2xl font-bold text-yellow-700">{data.warning}</div>
            <div className="text-xs text-muted-foreground">Atenção</div>
          </div>
          <div className="p-2 rounded border bg-orange-50">
            <div className="text-2xl font-bold text-orange-700">{data.critical}</div>
            <div className="text-xs text-muted-foreground">Crítico</div>
          </div>
          <div className="p-2 rounded border bg-red-50">
            <div className="text-2xl font-bold text-red-700">{data.dead_letter}</div>
            <div className="text-xs text-muted-foreground">Dead-letter</div>
          </div>
          <div className="p-2 rounded border bg-gray-50">
            <div className="text-2xl font-bold text-gray-700">{data.never_ran}</div>
            <div className="text-xs text-muted-foreground">Sem histórico</div>
          </div>
        </div>

        {/* Lista por escritório - só mostra os com algum problema ou nunca rodaram */}
        {data.offices.filter(o => o.health !== 'ok').length > 0 && (
          <div className="space-y-2 border-t pt-4">
            <h4 className="text-sm font-medium">Escritórios que exigem atenção</h4>
            {data.offices
              .filter(o => o.health !== 'ok')
              .map(o => {
                const meta = healthMeta[o.health];
                const Icon = meta.icon;
                return (
                  <div key={o.office_id} className={`flex items-center justify-between p-3 rounded border ${meta.color}`}>
                    <div className="flex items-start gap-3 flex-1">
                      <Icon className="h-5 w-5 mt-0.5 shrink-0" />
                      <div className="flex-1 min-w-0">
                        <div className="font-medium">{o.office_name || `Escritório ${o.office_id}`}</div>
                        <div className="text-xs opacity-80">
                          Última captura OK: <strong>{formatRelative(o.last_run_at)}</strong>
                          {o.consecutive_failures > 0 && ` · ${o.consecutive_failures} falha(s) seguidas`}
                          {o.next_retry_at && ` · próximo retry: ${formatAbsolute(o.next_retry_at)}`}
                        </div>
                        {o.last_error && (
                          <div className="text-xs opacity-70 mt-1 font-mono truncate" title={o.last_error}>
                            {o.last_error}
                          </div>
                        )}
                      </div>
                    </div>
                    {isAdmin && (o.health === 'critical' || o.health === 'dead_letter') && (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => handleReset(o.office_id)}
                        disabled={resetting === o.office_id}
                      >
                        {resetting === o.office_id ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <><RefreshCw className="h-4 w-4 mr-1" /> Resetar</>
                        )}
                      </Button>
                    )}
                  </div>
                );
              })}
          </div>
        )}

        {!hasProblems && data.never_ran === 0 && (
          <div className="text-center py-4 text-sm text-green-700 flex items-center justify-center gap-2">
            <CheckCircle2 className="h-5 w-5" />
            Todos os escritórios saudáveis.
          </div>
        )}
      </CardContent>
    </Card>
  );
};
