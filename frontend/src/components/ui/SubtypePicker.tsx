/**
 * SubtypePicker — combobox com busca para o campo "Subtipo de tarefa".
 *
 * O catalogo do Legal One tem ~900 subtipos divididos em ~80 tipos. Um
 * <Select> tradicional vira inutil nessa escala (scroll infinito sem
 * filtro). Aqui usamos Popover + cmdk (Command) pra permitir busca por
 * texto livre tanto no nome do subtipo quanto no nome do tipo pai.
 *
 * O matcher concatena "tipo::subtipo" no `value` de cada CommandItem
 * para que o cmdk filtre por ambos. A normalizacao remove acentos e
 * caixa.
 *
 * Props:
 * - value: id do subtipo selecionado (null = nada).
 * - taskTypes: lista completa de tipos com seus subtipos.
 * - onChange: callback recebendo o subtype id e o tipo pai (uteis para
 *   estado derivado, ex.: armazenar `task_type_external_id` no form).
 * - disabledSubtypeIds: subtypes a serem renderizados como `disabled`
 *   (ex.: "ja em uso por outro template" para evitar 409 de duplicata).
 * - disabledLabel: texto exibido ao lado do subtype desabilitado.
 * - placeholder/searchPlaceholder/label: customizacoes opcionais.
 */
import { useState } from "react";
import { Check, ChevronsUpDown } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { Label } from "@/components/ui/label";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { cn } from "@/lib/utils";

export interface SubtypePickerTaskSubtype {
  external_id: number;
  name: string;
}

export interface SubtypePickerTaskType {
  external_id: number;
  name: string;
  subtypes: SubtypePickerTaskSubtype[];
}

export interface SubtypePickerProps {
  value: number | null;
  taskTypes: SubtypePickerTaskType[];
  onChange: (subtypeId: number, parentType: SubtypePickerTaskType | null) => void;
  disabledSubtypeIds?: Set<number>;
  disabledLabel?: string;
  label?: string;
  required?: boolean;
  placeholder?: string;
  searchPlaceholder?: string;
  triggerClassName?: string;
  disabled?: boolean;
}

export const SubtypePicker = ({
  value,
  taskTypes,
  onChange,
  disabledSubtypeIds,
  disabledLabel = "(já em uso)",
  label = "Subtipo de tarefa",
  required = false,
  placeholder = "Selecione o subtipo",
  searchPlaceholder = "Buscar por tipo ou subtipo...",
  triggerClassName,
  disabled = false,
}: SubtypePickerProps) => {
  const [open, setOpen] = useState(false);

  // Label do botao: "Tipo · Subtipo" quando ha selecao, placeholder caso contrario.
  const selectedLabel = (() => {
    if (!value) return null;
    for (const t of taskTypes) {
      const s = t.subtypes.find((x) => x.external_id === value);
      if (s) return { typeName: t.name, subName: s.name };
    }
    return null;
  })();

  return (
    <div className="grid gap-1.5">
      {label ? (
        <Label className="text-xs font-medium">
          {label}
          {required ? " *" : ""}
        </Label>
      ) : null}
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            type="button"
            variant="outline"
            role="combobox"
            aria-expanded={open}
            disabled={disabled}
            className={cn(
              "h-9 w-full justify-between text-sm font-normal",
              triggerClassName,
            )}
          >
            {selectedLabel ? (
              <span className="truncate">
                <span className="text-muted-foreground">
                  {selectedLabel.typeName} ·{" "}
                </span>
                <span className="font-medium">{selectedLabel.subName}</span>
              </span>
            ) : (
              <span className="text-muted-foreground">{placeholder}</span>
            )}
            <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
          </Button>
        </PopoverTrigger>
        <PopoverContent
          className="w-[--radix-popover-trigger-width] p-0"
          align="start"
        >
          <Command
            // Matcher customizado: busca case-insensitive sem acento em
            // "tipo | subtipo". O cmdk passa o `value` bruto do CommandItem
            // (que cadastramos como "tipo::subtipo::id") e o termo digitado.
            filter={(itemValue, search) => {
              const norm = (s: string) =>
                s.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
              return norm(itemValue).includes(norm(search)) ? 1 : 0;
            }}
          >
            <CommandInput placeholder={searchPlaceholder} />
            <CommandList className="max-h-80">
              <CommandEmpty>Nenhum resultado.</CommandEmpty>
              {taskTypes.map((t) => (
                <CommandGroup key={t.external_id} heading={t.name}>
                  {t.subtypes.map((s) => {
                    const itemValue = `${t.name}::${s.name}::${s.external_id}`;
                    const isSelected = value === s.external_id;
                    const isDisabled =
                      disabledSubtypeIds?.has(s.external_id) && !isSelected;
                    return (
                      <CommandItem
                        key={s.external_id}
                        value={itemValue}
                        disabled={isDisabled}
                        onSelect={() => {
                          if (isDisabled) return;
                          onChange(s.external_id, t);
                          setOpen(false);
                        }}
                      >
                        <Check
                          className={cn(
                            "mr-2 h-4 w-4",
                            isSelected ? "opacity-100" : "opacity-0",
                          )}
                        />
                        <span className="truncate">{s.name}</span>
                        {isDisabled ? (
                          <span className="ml-2 text-xs text-muted-foreground">
                            {disabledLabel}
                          </span>
                        ) : null}
                      </CommandItem>
                    );
                  })}
                </CommandGroup>
              ))}
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
    </div>
  );
};

export default SubtypePicker;
