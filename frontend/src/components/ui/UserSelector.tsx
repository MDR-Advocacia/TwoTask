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
import { Check, ChevronsUpDown, X, Building, Users } from 'lucide-react';
import { cn } from '@/lib/utils';

// --- Interfaces ---
export interface SectorInfo {
  id: number;
  name: string;
}
export interface UserSquadInfo {
  id: number;
  name: string;
  sector: SectorInfo;
}

export interface SelectableUser {
  id: number;
  external_id: number;
  name: string;
  squads: UserSquadInfo[];
}

interface UserSelectorProps {
  users: SelectableUser[];
  value: string | null;
  onChange: (value: string | null) => void;
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

  const selectedUser = useMemo(() => {
    return users.find(u => String(u.external_id) === value) || null;
  }, [value, users]);

  // Filtra e ordena os usuários
  const filteredAndSortedUsers = useMemo(() => {
    const squadFiltered = filterBySquadIds.length === 0
      ? users
      : users.filter(user =>
          user.squads.some(squad => filterBySquadIds.includes(squad.id))
        );

    // Ordena alfabeticamente pelo nome
    return squadFiltered.sort((a, b) => a.name.localeCompare(b.name));

  }, [users, filterBySquadIds]);

  const handleSelect = (currentValue: string) => {
    const newValue = currentValue === value ? null : currentValue;
    onChange(newValue);
    setOpen(false);
  };

  const handleClear = (e: React.MouseEvent) => {
    e.stopPropagation();
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
                {filteredAndSortedUsers.map(user => (
                  <CommandItem
                    key={user.external_id}
                    value={user.name} // Usa o nome para a busca (habilita busca parcial)
                    onSelect={() => handleSelect(String(user.external_id))}
                  >
                    <Check
                      className={cn(
                        'mr-2 h-4 w-4',
                        value === String(user.external_id)
                          ? 'opacity-100'
                          : 'opacity-0'
                      )}
                    />
                    <div className="flex flex-col flex-grow">
                      <span className="font-medium">{user.name}</span>
                      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground mt-1">
                        {user.squads.map(squad => (
                          <div key={squad.id} className="flex items-center gap-1">
                            <Building className="h-3 w-3" />
                            <span>{squad.sector.name}</span>
                            <span className="text-gray-400">/</span>
                            <Users className="h-3 w-3" />
                            <span>{squad.name}</span>
                          </div>
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