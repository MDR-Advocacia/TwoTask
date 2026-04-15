import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  Activity,
  CheckCircle2,
  Clock,
  Loader2,
  AlertCircle,
  ArrowRight,
  FileText,
} from 'lucide-react';

import { useAuth } from '@/hooks/useAuth';
import { useToast } from '@/hooks/use-toast';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { apiFetch } from '@/lib/api-client';
import { CaptureHealthWidget } from '@/components/CaptureHealthWidget';

interface SavedFilter {
  id: number;
  name: string;
  module: string;
  filters_json: string;
  is_default: boolean;
}

interface Automation {
  id: number;
  name: string;
  next_run_at: string | null;
  is_enabled: boolean;
}

interface PublicationStats {
  count: number;
}

const DashboardHome = () => {
  const navigate = useNavigate();
  const { toast } = useToast();
  const { tokenData, canUsePublications, isAdmin } = useAuth();

  const { data: savedFilters = [], isLoading: filtersLoading } = useQuery({
    queryKey: ['saved-filters', 'publications'],
    queryFn: async () => {
      const res = await apiFetch('/api/v1/me/saved-filters?module=publications');
      if (!res.ok) return [];
      return res.json() as Promise<SavedFilter[]>;
    },
    enabled: canUsePublications,
  });

  const { data: automations = [], isLoading: automationsLoading } = useQuery({
    queryKey: ['automations'],
    queryFn: async () => {
      const res = await apiFetch('/api/v1/automations');
      if (!res.ok) return [];
      const data = await res.json();
      return (Array.isArray(data) ? data : data.items || []) as Automation[];
    },
  });

  const { data: publicationsStats = { count: 0 }, isLoading: pubStatsLoading } = useQuery({
    queryKey: ['publications-pending'],
    queryFn: async () => {
      const res = await apiFetch(`/api/v1/publications/records?status=NOVO&limit=1`);
      if (!res.ok) return { count: 0 };
      const data = await res.json();
      return { count: data.total ?? data.total_records ?? (Array.isArray(data.items) ? data.items.length : 0) };
    },
    enabled: canUsePublications,
  });

  const { data: recentClassifications = [], isLoading: classLoading } = useQuery({
    queryKey: ['classifications-recent'],
    queryFn: async () => {
      const res = await apiFetch('/api/v1/publications/records?status=CLASSIFICADO&limit=5');
      if (!res.ok) return [];
      const data = await res.json();
      const items = Array.isArray(data) ? data : data.items || [];
      return items.slice(0, 5);
    },
    enabled: canUsePublications,
  });

  const nextAutomation = automations.find((a) => a.is_enabled && a.next_run_at)
    ? automations.filter((a) => a.is_enabled && a.next_run_at).sort((a, b) =>
        new Date(a.next_run_at || '').getTime() - new Date(b.next_run_at || '').getTime()
      )[0]
    : null;

  const defaultFilter = savedFilters.find((f) => f.is_default);

  const handleApplyFilter = (filter: SavedFilter) => {
    try {
      const filterState = typeof filter.filters_json === 'string' ? JSON.parse(filter.filters_json) : filter.filters_json;
      navigate('/publications', { state: { appliedFilter: filterState } });
    } catch (e) {
      toast({
        title: 'Erro',
        description: 'Não foi possível aplicar o filtro.',
        variant: 'destructive',
      });
    }
  };

  const formatDateTime = (isoString: string | null) => {
    if (!isoString) return 'N/A';
    return new Intl.DateTimeFormat('pt-BR', {
      dateStyle: 'short',
      timeStyle: 'short',
      timeZone: 'America/Sao_Paulo',
    }).format(new Date(isoString));
  };

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold">Dashboard</h1>
        <p className="text-muted-foreground mt-2">
          Bem-vindo! Aqui está um resumo das suas atividades recentes.
        </p>
      </div>

      {isAdmin && <CaptureHealthWidget />}

      {canUsePublications && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {/* Card: Publicações Pendentes */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
                <FileText className="h-4 w-4" />
                Publicações Pendentes
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {pubStatsLoading ? (
                <Loader2 className="h-6 w-6 animate-spin" />
              ) : (
                <>
                  <div className="text-3xl font-bold">{publicationsStats.count}</div>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => navigate('/publications?status=novo')}
                    className="w-full"
                  >
                    Ver Pendentes
                    <ArrowRight className="h-4 w-4 ml-2" />
                  </Button>
                </>
              )}
            </CardContent>
          </Card>

          {/* Card: Próxima Rodagem Automática */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
                <Clock className="h-4 w-4" />
                Próxima Rodagem
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {automationsLoading ? (
                <Loader2 className="h-6 w-6 animate-spin" />
              ) : nextAutomation ? (
                <>
                  <div className="text-sm font-medium">{nextAutomation.name}</div>
                  <div className="text-xs text-muted-foreground">
                    {formatDateTime(nextAutomation.next_run_at)}
                  </div>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => navigate('/automations')}
                    className="w-full"
                  >
                    Ver Agendamentos
                    <ArrowRight className="h-4 w-4 ml-2" />
                  </Button>
                </>
              ) : (
                <p className="text-sm text-muted-foreground">Nenhum agendamento ativo.</p>
              )}
            </CardContent>
          </Card>

          {/* Card: Últimas Classificações */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
                <CheckCircle2 className="h-4 w-4" />
                Últimas Classificações
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {classLoading ? (
                <Loader2 className="h-6 w-6 animate-spin" />
              ) : recentClassifications.length > 0 ? (
                <>
                  <div className="text-3xl font-bold">{recentClassifications.length}</div>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => navigate('/publications?status=classificado')}
                    className="w-full"
                  >
                    Ver Classificações
                    <ArrowRight className="h-4 w-4 ml-2" />
                  </Button>
                </>
              ) : (
                <p className="text-sm text-muted-foreground">Nenhuma classificação recente.</p>
              )}
            </CardContent>
          </Card>
        </div>
      )}

      {/* Meus Filtros Salvos */}
      {canUsePublications && (
        <Card>
          <CardHeader>
            <CardTitle>Meus Filtros Salvos</CardTitle>
            <CardDescription>
              Acesse rapidamente seus filtros de publicações favoritos.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {filtersLoading ? (
              <Loader2 className="h-6 w-6 animate-spin" />
            ) : savedFilters.length > 0 ? (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {savedFilters.map((filter) => (
                  <div
                    key={filter.id}
                    className="p-4 border rounded-lg cursor-pointer hover:bg-muted transition-colors"
                    onClick={() => handleApplyFilter(filter)}
                  >
                    <div className="flex items-start justify-between">
                      <div className="flex-1">
                        <h3 className="font-medium">{filter.name}</h3>
                        {filter.is_default && (
                          <Badge variant="secondary" className="mt-2">
                            Padrão
                          </Badge>
                        )}
                      </div>
                      <ArrowRight className="h-4 w-4 text-muted-foreground mt-1" />
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-center py-8 text-muted-foreground">
                <p>Nenhum filtro salvo ainda.</p>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => navigate('/publications')}
                  className="mt-4"
                >
                  Ir para Publicações
                </Button>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Quick Actions */}
      {canUsePublications && (
        <Card>
          <CardHeader>
            <CardTitle>Ações Rápidas</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-3">
            <Button onClick={() => navigate('/publications?status=novo')}>
              <Activity className="h-4 w-4 mr-2" />
              Classificar Pendentes
            </Button>
            <Button variant="outline" onClick={() => navigate('/publications/templates')}>
              <FileText className="h-4 w-4 mr-2" />
              Templates de Agendamento
            </Button>
            <Button variant="outline" onClick={() => navigate('/publications')}>
              <ArrowRight className="h-4 w-4 mr-2" />
              Ver Publicações
            </Button>
            <Button variant="outline" onClick={() => navigate('/publications/lookup')}>
              <FileText className="h-4 w-4 mr-2" />
              Consultar por CNJ
            </Button>
          </CardContent>
        </Card>
      )}
    </div>
  );
};

export default DashboardHome;
