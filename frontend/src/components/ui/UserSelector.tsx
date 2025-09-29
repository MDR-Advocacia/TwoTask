// frontend/src/components/ui/UserSelector.tsx

// frontend/src/components/ui/UserSelector.tsx
import React, { useMemo, useState } from 'react';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import { Button } from '@/components/ui/button';
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command';
import { Check, ChevronsUpDown, X } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Badge } from './badge';

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
  // O valor selecionado é o `external_id` do usuário como string, ou null se nada for selecionado
  value: string | null;
  // Callback para notificar a mudança de valor
  onChange: (value: string | null) => void;
  // Permite filtrar os usuários mostrados com base nos IDs dos squads
  filterBySquadIds?: number[];
  disabled?: boolean;
  placeholder?: string;
}

const UserSelector = ({
  users,
  value,
  onChange,
  filterBySquadIds = [],
  disabled = false,
  placeholder = 'Selecione um responsável...',
}: UserSelectorProps) => {
  const [open, setOpen] = useState(false);

  // Deriva o usuário selecionado a partir do `value` (external_id)
  const selectedUser = useMemo(() => {
    return users.find(u => String(u.external_id) === value) || null;
  }, [value, users]);

  // Filtra os usuários com base na busca e nos Squads
  const filteredUsers = useMemo(() => {
    if (filterBySquadIds.length === 0) {
      return users;
    }
    return users.filter(user =>
      user.squads.some(squad => filterBySquadIds.includes(squad.id))
    );
  }, [users, filterBySquadIds]);

  const handleSelect = (currentValue: string) => {
    // Se o mesmo valor for selecionado novamente, desmarque-o. Caso contrário, selecione o novo valor.
    const newValue = currentValue === value ? null : currentValue;
    onChange(newValue);
    setOpen(false);
  };

  const handleClear = (e: React.MouseEvent) => {
    e.stopPropagation(); // Impede que o Popover seja aberto
    onChange(null);
  };

  return (
    <div className="relative">
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            variant="outline"
            role="combobox"
            aria-expanded={open}
            className="w-full justify-between"
            disabled={disabled}
          >
            {selectedUser ? (
              <span className="truncate">{selectedUser.name}</span>
            ) : (
              <span className="text-muted-foreground">{placeholder}</span>
            )}
            <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
          </Button>
        </PopoverTrigger>
        {selectedUser && !disabled && (
          <Button
            variant="ghost"
            size="icon"
            onClick={handleClear}
            className="absolute right-10 top-1/2 -translate-y-1/2 h-6 w-6"
            aria-label="Limpar seleção"
          >
            <X className="h-4 w-4 text-muted-foreground" />
          </Button>
        )}
        <PopoverContent className="w-[--radix-popover-trigger-width] p-0">
          <Command>
            <CommandInput placeholder="Buscar usuário..." />
            <CommandList>
              <CommandEmpty>Nenhum usuário encontrado.</CommandEmpty>
              <CommandGroup>
                {filteredUsers.map(user => (
                  <CommandItem
                    key={user.external_id}
                    value={String(user.external_id)}
                    onSelect={handleSelect}
                  >
                    <Check
                      className={cn(
                        'mr-2 h-4 w-4',
                        value === String(user.external_id)
                          ? 'opacity-100'
                          : 'opacity-0'
                      )}
                    />
                    <div className="flex flex-col">
                      <span>{user.name}</span>
                      <div className="flex flex-wrap gap-1 text-xs">
                        {user.squads.map(squad => (
                          <Badge key={squad.id} variant="secondary">
                            {squad.name}
                          </Badge>
                        ))}
                      </div>
                    </div>
                  </CommandItem>
                ))}
              </CommandGroup>
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
    </div>
  );
};

export default UserSelector;