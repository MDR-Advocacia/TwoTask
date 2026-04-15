import { useState } from 'react';
import { useAuth } from '@/hooks/useAuth';
import { useQuery } from '@tanstack/react-query';
import { apiFetch } from '@/lib/api-client';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Loader2, AlertCircle, Copy, Trash2 } from 'lucide-react';
import { useToast } from '@/hooks/use-toast';

interface SavedFilter {
  id: number;
  name: string;
  module: string;
  is_default: boolean;
}

interface Office {
  id: number;
  name: string;
}

export const ProfilePage = () => {
  const { user, refreshMe } = useAuth();
  const { toast } = useToast();
  const [showPasswordForm, setShowPasswordForm] = useState(false);
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [isChangingPassword, setIsChangingPassword] = useState(false);

  const { data: savedFilters = [], isLoading: filtersLoading, refetch: refetchFilters } = useQuery({
    queryKey: ['saved-filters'],
    queryFn: async () => {
      const res = await apiFetch('/api/v1/me/saved-filters');
      if (!res.ok) throw new Error('Falha ao carregar filtros');
      return res.json() as Promise<SavedFilter[]>;
    },
  });

  const { data: offices = [], isLoading: officesLoading } = useQuery({
    queryKey: ['offices'],
    queryFn: async () => {
      const res = await apiFetch('/api/v1/offices');
      if (!res.ok) throw new Error('Falha ao carregar escritórios');
      return res.json() as Promise<Office[]>;
    },
  });

  const getOfficeName = (officeId: number | null | undefined) => {
    if (!officeId) return 'Não definido';
    const office = offices.find((o) => o.id === officeId);
    return office?.name || 'Desconhecido';
  };

  const handleChangePassword = async () => {
    if (!currentPassword.trim()) {
      toast({ title: 'Erro', description: 'Informe sua senha atual.', variant: 'destructive' });
      return;
    }
    if (!newPassword.trim()) {
      toast({ title: 'Erro', description: 'Informe uma nova senha.', variant: 'destructive' });
      return;
    }
    if (newPassword.length < 8) {
      toast({
        title: 'Erro',
        description: 'A nova senha deve ter no mínimo 8 caracteres.',
        variant: 'destructive',
      });
      return;
    }
    if (newPassword !== confirmPassword) {
      toast({ title: 'Erro', description: 'As senhas não coincidem.', variant: 'destructive' });
      return;
    }

    setIsChangingPassword(true);
    try {
      const res = await apiFetch('/api/v1/me/change-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword,
        }),
      });

      if (!res.ok) {
        const errorData = await res.json();
        throw new Error(errorData.detail || 'Falha ao alterar senha');
      }

      toast({ title: 'Sucesso!', description: 'Sua senha foi alterada com sucesso.' });
      setShowPasswordForm(false);
      setCurrentPassword('');
      setNewPassword('');
      setConfirmPassword('');
      await refreshMe();
    } catch (error: any) {
      toast({ title: 'Erro', description: error.message, variant: 'destructive' });
    } finally {
      setIsChangingPassword(false);
    }
  };

  const [deletingId, setDeletingId] = useState<number | null>(null);

  const handleDeleteFilter = async (filterId: number) => {
    setDeletingId(filterId);
    try {
      const res = await apiFetch(`/api/v1/me/saved-filters/${filterId}`, {
        method: 'DELETE',
      });

      if (!res.ok) throw new Error('Falha ao excluir filtro');

      toast({ title: 'Filtro excluído', description: 'O filtro foi removido com sucesso.' });
      refetchFilters();
    } catch (error: any) {
      toast({ title: 'Erro', description: error.message, variant: 'destructive' });
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <div className="container mx-auto px-6 py-8 space-y-8">
      <div className="mb-8">
        <h1 className="text-3xl font-bold">Meu Perfil</h1>
        <p className="text-muted-foreground mt-1">Visualize e gerencie suas informações pessoais e preferências.</p>
      </div>

      {/* User Info Card */}
      <Card>
        <CardHeader>
          <CardTitle>Informações Pessoais</CardTitle>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div>
              <Label className="text-sm text-muted-foreground">Nome</Label>
              <p className="text-lg font-medium">{user?.name}</p>
            </div>
            <div>
              <Label className="text-sm text-muted-foreground">E-mail</Label>
              <p className="text-lg font-medium font-mono">{user?.email}</p>
            </div>
            <div>
              <Label className="text-sm text-muted-foreground">Papel</Label>
              <p className="text-lg font-medium">{user?.role === 'admin' ? 'Administrador' : 'Usuário'}</p>
            </div>
            <div>
              <Label className="text-sm text-muted-foreground">Escritório Padrão</Label>
              <p className="text-lg font-medium">{getOfficeName(user?.default_office_id)}</p>
            </div>
          </div>

          <div className="border-t pt-6">
            <h3 className="font-semibold mb-4">Permissões</h3>
            <div className="space-y-2">
              <p className="text-sm">
                <span className="inline-block w-48">Agendar Lotes:</span>
                <span className="font-medium">{user?.can_schedule_batch ? 'Ativado' : 'Desativado'}</span>
              </p>
              <p className="text-sm">
                <span className="inline-block w-48">Usar Publicações:</span>
                <span className="font-medium">{user?.can_use_publications ? 'Ativado' : 'Desativado'}</span>
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Change Password Card */}
      <Card>
        <CardHeader>
          <CardTitle>Alterar Senha</CardTitle>
          <CardDescription>Atualize sua senha com segurança. Mínimo de 8 caracteres.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {showPasswordForm ? (
            <>
              <div className="space-y-2">
                <Label htmlFor="current-pwd">Senha Atual</Label>
                <Input
                  id="current-pwd"
                  type="password"
                  placeholder="Digite sua senha atual"
                  value={currentPassword}
                  onChange={(e) => setCurrentPassword(e.target.value)}
                  disabled={isChangingPassword}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="new-pwd">Nova Senha</Label>
                <Input
                  id="new-pwd"
                  type="password"
                  placeholder="Digite uma nova senha"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  disabled={isChangingPassword}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="confirm-pwd">Confirmar Nova Senha</Label>
                <Input
                  id="confirm-pwd"
                  type="password"
                  placeholder="Confirme sua nova senha"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  disabled={isChangingPassword}
                />
              </div>

              <div className="flex gap-2 pt-4">
                <Button onClick={handleChangePassword} disabled={isChangingPassword}>
                  {isChangingPassword ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      Alterando...
                    </>
                  ) : (
                    'Alterar Senha'
                  )}
                </Button>
                <Button variant="outline" onClick={() => setShowPasswordForm(false)} disabled={isChangingPassword}>
                  Cancelar
                </Button>
              </div>
            </>
          ) : (
            <Button onClick={() => setShowPasswordForm(true)}>Alterar Senha</Button>
          )}
        </CardContent>
      </Card>

      {/* Saved Filters Card */}
      <Card>
        <CardHeader>
          <CardTitle>Meus Filtros Salvos</CardTitle>
          <CardDescription>Filtros que você salvou para reutilização rápida.</CardDescription>
        </CardHeader>
        <CardContent>
          {filtersLoading ? (
            <div className="flex items-center justify-center h-32">
              <Loader2 className="h-6 w-6 animate-spin" />
            </div>
          ) : savedFilters.length === 0 ? (
            <Alert>
              <AlertCircle className="h-4 w-4" />
              <AlertTitle>Nenhum filtro salvo</AlertTitle>
              <AlertDescription>Você não possui filtros salvos. Crie filtros nas seções de Publicações para salvá-los aqui.</AlertDescription>
            </Alert>
          ) : (
            <div className="space-y-3">
              {savedFilters.map((filter) => (
                <div key={filter.id} className="flex items-center justify-between p-3 border rounded-lg hover:bg-muted/50 transition">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <p className="font-medium truncate">{filter.name}</p>
                      {filter.is_default && (
                        <span className="shrink-0 text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded-full">Padrão</span>
                      )}
                    </div>
                    <p className="text-xs text-muted-foreground mt-0.5 capitalize">{filter.module}</p>
                  </div>
                  <Button
                    size="sm"
                    variant="destructive"
                    onClick={() => handleDeleteFilter(filter.id)}
                    disabled={deletingId === filter.id}
                    className="ml-4 shrink-0"
                  >
                    {deletingId === filter.id
                      ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      : <><Trash2 className="h-3.5 w-3.5 mr-1" />Excluir</>
                    }
                  </Button>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
};

export default ProfilePage;
