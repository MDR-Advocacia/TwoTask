// frontend/src/components/ui/UserSelector.tsx

import { useState, useMemo, useEffect } from 'react';
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
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion"
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { User, Users, X, Dice5, CheckCircle2 } from 'lucide-react';

// --- Interfaces ---
export interface UserSquadInfo {
  id: number;
  name: string;
  is_leader: boolean;
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
  filterBySquadIds?: number[];
  disabled?: boolean;
}

// Helper para agrupar usuários por squad
const groupUsersBySquad = (users: SelectableUser[], filterBySquadIds: number[]) => {
  const squads: { [key: string]: { id: number; members: (SelectableUser & { is_leader: boolean })[] } } = {};

  users.forEach(user => {
    user.squads.forEach(squadInfo => {
      // Filtra para mostrar apenas squads relevantes
      if (filterBySquadIds.length > 0 && !filterBySquadIds.includes(squadInfo.id)) {
        return;
      }

      if (!squads[squadInfo.name]) {
        squads[squadInfo.name] = { id: squadInfo.id, members: [] };
      }
      // Adiciona o usuário ao grupo do squad com a informação de liderança
      squads[squadInfo.name].members.push({ ...user, is_leader: squadInfo.is_leader });
    });
  });
  return squads;
};


const UserSelector = ({
  users,
  selectedUserId,
  onUserSelect,
  filterBySquadIds = [],
  disabled = false,
}: UserSelectorProps) => {
  const [isOpen, setIsOpen] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');

  // Encontra o objeto do usuário selecionado para exibição no botão
  const selectedUser = useMemo(() => {
    return users.find(u => String(u.external_id) === selectedUserId) || null;
  }, [selectedUserId, users]);

  // Filtra os usuários com base no termo de busca
  const searchedUsers = useMemo(() => {
    if (!searchTerm) return users;
    return users.filter(user => user.name.toLowerCase().includes(searchTerm.toLowerCase()));
  }, [users, searchTerm]);

  // Agrupa os usuários filtrados por squad
  const squadsGroup = useMemo(() => {
    return groupUsersBySquad(searchedUsers, filterBySquadIds);
  }, [searchedUsers, filterBySquadIds]);

  const handleSelect = (userId: number) => {
    onUserSelect(String(userId));
    setIsOpen(false);
    setSearchTerm('');
  };

  const handleRandomSelect = (squadName: string) => {
    const squad = squadsGroup[squadName];
    if (!squad) return;

    // Filtra para pegar apenas membros que não são líderes
    const nonLeaderMembers = squad.members.filter(m => !m.is_leader);

    if (nonLeaderMembers.length > 0) {
      const randomIndex = Math.floor(Math.random() * nonLeaderMembers.length);
      const randomUser = nonLeaderMembers[randomIndex];
      handleSelect(randomUser.external_id);
    } else {
      // Opcional: Adicionar um feedback caso não haja membros para selecionar
      console.warn(`Não há membros que não sejam líderes no squad ${squadName} para selecionar.`);
    }
  };

  const handleClear = (e: React.MouseEvent) => {
    e.stopPropagation();
    onUserSelect(null);
  };

  // Reseta o termo de busca quando o modal é fechado
  useEffect(() => {
    if (!isOpen) {
      setSearchTerm('');
    }
  }, [isOpen]);

  return (
    <Dialog open={isOpen} onOpenChange={setIsOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" className="w-full justify-between" disabled={disabled}>
          {selectedUser ? (
            <div className="flex items-center gap-2">
              <User className="h-4 w-4" />
              <span className="truncate">{selectedUser.name}</span>
            </div>
          ) : (
            <span className="text-muted-foreground">Selecione o responsável...</span>
          )}
          {selectedUser && (
            <div onClick={handleClear} className="p-1 rounded-full hover:bg-muted">
              <X className="h-4 w-4 text-muted-foreground" />
            </div>
          )}
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-[625px]">
        <DialogHeader>
          <DialogTitle>Selecionar Responsável</DialogTitle>
          <DialogDescription>
            Selecione um membro da equipe ou use a seleção aleatória por squad.
          </DialogDescription>
        </DialogHeader>
        <div className="py-4">
          <Input
            placeholder="Buscar usuário por nome..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="mb-4"
          />
          <div className="space-y-2 max-h-[400px] overflow-y-auto">
            {Object.keys(squadsGroup).length > 0 ? (
              <Accordion type="single" collapsible className="w-full">
                {Object.entries(squadsGroup).map(([squadName, squadData]) => (
                  <AccordionItem value={squadName} key={squadData.id}>
                    <AccordionTrigger>{squadName}</AccordionTrigger>
                    <AccordionContent>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="w-full justify-start mb-2"
                        onClick={() => handleRandomSelect(squadName)}
                        disabled={squadData.members.every(m => m.is_leader)}
                      >
                        <Dice5 className="h-4 w-4 mr-2" />
                        Selecionar Membro Aleatoriamente (Não-Líder)
                      </Button>
                      <div className="space-y-1">
                        {squadData.members.map(member => (
                          <div
                            key={member.id}
                            className="flex items-center justify-between p-2 rounded-md hover:bg-muted cursor-pointer"
                            onClick={() => handleSelect(member.external_id)}
                          >
                            <div className="flex items-center">
                              <p className="font-medium">{member.name}</p>
                              {member.is_leader && (
                                <Badge variant="outline" className="ml-2">Líder</Badge>
                              )}
                            </div>
                            {String(member.external_id) === selectedUserId && (
                              <CheckCircle2 className="h-5 w-5 text-primary" />
                            )}
                          </div>
                        ))}
                      </div>
                    </AccordionContent>
                  </AccordionItem>
                ))}
              </Accordion>
            ) : (
              <div className="text-center text-muted-foreground py-4">
                Nenhum usuário encontrado para os squads filtrados.
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