import { useState } from 'react';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { useToast } from '@/hooks/use-toast';
import { apiFetch } from '@/lib/api-client';
import { AlertCircle, Loader2 } from 'lucide-react';

interface ChangePasswordDialogProps {
  isOpen: boolean;
  isMandatory?: boolean;
  onPasswordChanged?: () => void;
}

export const ChangePasswordDialog = ({ isOpen, isMandatory = false, onPasswordChanged }: ChangePasswordDialogProps) => {
  const { toast } = useToast();
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = async () => {
    // Validations
    if (!currentPassword.trim()) {
      toast({
        title: 'Erro',
        description: 'Informe sua senha atual.',
        variant: 'destructive',
      });
      return;
    }

    if (!newPassword.trim()) {
      toast({
        title: 'Erro',
        description: 'Informe uma nova senha.',
        variant: 'destructive',
      });
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
      toast({
        title: 'Erro',
        description: 'As senhas não coincidem.',
        variant: 'destructive',
      });
      return;
    }

    setIsLoading(true);
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

      toast({
        title: 'Sucesso!',
        description: 'Sua senha foi alterada com sucesso.',
      });

      // Reset form
      setCurrentPassword('');
      setNewPassword('');
      setConfirmPassword('');

      // Call callback
      if (onPasswordChanged) {
        onPasswordChanged();
      }
    } catch (error: any) {
      toast({
        title: 'Erro',
        description: error.message,
        variant: 'destructive',
      });
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={() => {}} modal={true}>
      <DialogContent className={!isMandatory ? 'sm:max-w-md' : 'sm:max-w-md'} hideClose={isMandatory}>
        <DialogHeader>
          <DialogTitle>Alterar Senha</DialogTitle>
        </DialogHeader>

        {isMandatory && (
          <Alert className="bg-amber-50 border-amber-200">
            <AlertCircle className="h-4 w-4 text-amber-600" />
            <AlertDescription className="text-amber-800">
              Você deve alterar sua senha antes de continuar. Por favor, defina uma nova senha agora.
            </AlertDescription>
          </Alert>
        )}

        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="current-pwd">Senha Atual</Label>
            <Input
              id="current-pwd"
              type="password"
              placeholder="Digite sua senha atual"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              disabled={isLoading}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="new-pwd">Nova Senha</Label>
            <Input
              id="new-pwd"
              type="password"
              placeholder="Digite uma nova senha (mín. 8 caracteres)"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              disabled={isLoading}
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
              disabled={isLoading}
            />
          </div>
        </div>

        <DialogFooter>
          {!isMandatory && (
            <Button variant="secondary" onClick={() => {}} disabled={isLoading}>
              Cancelar
            </Button>
          )}
          <Button onClick={handleSubmit} disabled={isLoading}>
            {isLoading ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Alterando...
              </>
            ) : (
              'Alterar Senha'
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
