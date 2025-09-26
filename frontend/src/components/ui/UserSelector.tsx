// frontend/src/components/ui/UserSelector.tsx

import { useState, useMemo } from 'react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  DialogFooter,
  DialogClose,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { User, Users, X } from 'lucide-react';

// --- Interfaces ---
export interface UserSquadInfo {
  id: number;
  name: string;
}

export interface SelectableUser {
  id: number;
  external_id: number;
  name: string;
  squads: UserSquadInfo[];
}

interface UserSelectorProps {
  users: SelectableUser[];
  selectedUserId: string | null;
  onUserSelect: (userId: string | null) => void;
  // Permite filtrar os usuários mostrados com base nos IDs dos squads
  // Se for um array vazio, nenhum filtro de squad é aplicado.
  filterBySquadIds?: number[];
  disabled?: boolean;
}

const UserSelector = ({
  users,
  selectedUserId,
  onUserSelect,
  filterBySquadIds = [],
  disabled = false,
}: UserSelectorProps) => {
  const [isOpen, setIsOpen] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');

  const selectedUser = useMemo(() => {
    return users.find(u => String(u.external_id) === selectedUserId) || null;
  }, [selectedUserId, users]);

  const filteredUsers = useMemo(() => {
    return users.filter(user => {
      const matchesSearchTerm = user.name.toLowerCase().includes(searchTerm.toLowerCase());

      // Se não houver squad IDs para filtrar, retorne apenas a correspondência do termo de busca.
      if (filterBySquadIds.length === 0) {
        return matchesSearchTerm;
      }

      // Verifique se o usuário pertence a pelo menos um dos squads filtrados.
      const belongsToFilteredSquad = user.squads.some(squad => filterBySquadIds.includes(squad.id));

      return matchesSearchTerm && belongsToFilteredSquad;
    });
  }, [users, searchTerm, filterBySquadIds]);

  const handleSelect = (userId: number) => {
    onUserSelect(String(userId));
    setIsOpen(false);
    setSearchTerm('');
  };

  const handleClear = (e: React.MouseEvent) => {
    e.stopPropagation(); // Impede que o Dialog seja aberto
    onUserSelect(null);
  };

  return (
    <Dialog open={isOpen} onOpenChange={setIsOpen}>
      <DialogTrigger asChild>
        <Button
          variant="outline"
          className="w-full justify-between"
          disabled={disabled}
        >
          {selectedUser ? (
            <div className="flex items-center gap-2">
              <User className="h-4 w-4" />
              <span>{selectedUser.name}</span>
            </div>
          ) : (
            <span className="text-muted-foreground">Selecione o responsável...</span>
          )}
          {selectedUser && (
            <div
              onClick={handleClear}
              className="p-1 rounded-full hover:bg-muted"
            >
              <X className="h-4 w-4 text-muted-foreground" />
            </div>
          )}
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-[525px]">
        <DialogHeader>
          <DialogTitle>Selecionar Responsável</DialogTitle>
          <DialogDescription>
            Busque e selecione um usuário da lista.
            {filterBySquadIds.length > 0 && " A lista foi filtrada pelos squads associados à tarefa."}
          </DialogDescription>
        </DialogHeader>
        <div className="py-4">
          <Input
            placeholder="Buscar usuário por nome..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="mb-4"
          />
          <div className="space-y-2 max-h-80 overflow-y-auto">
            {filteredUsers.length > 0 ? (
              filteredUsers.map(user => (
                <div
                  key={user.id}
                  className="flex items-center justify-between p-2 rounded-md hover:bg-muted cursor-pointer"
                  onClick={() => handleSelect(user.external_id)}
                >
                  <div>
                    <p className="font-medium">{user.name}</p>
                    <div className="flex flex-wrap gap-1 mt-1">
                      {user.squads.map(squad => (
                        <Badge key={squad.id} variant="secondary">{squad.name}</Badge>
                      ))}
                    </div>
                  </div>
                  {String(user.external_id) === selectedUserId && (
                    <div className="text-primary font-bold">Selecionado</div>
                  )}
                </div>
              ))
            ) : (
              <div className="text-center text-muted-foreground py-4">
                Nenhum usuário encontrado.
              </div>
            )}
          </div>
        </div>
        <DialogFooter>
          <DialogClose asChild>
            <Button type="button" variant="outline">Fechar</Button>
          </DialogClose>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

export default UserSelector;