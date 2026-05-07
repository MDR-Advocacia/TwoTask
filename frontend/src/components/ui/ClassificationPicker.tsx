/**
 * ClassificationPicker — combobox com busca para o par
 * (categoria, subcategoria) da taxonomia v2.
 *
 * Mesmo padrao do SubtypePicker (Popover + cmdk), 2 niveis. Ao inves
 * de tipo/subtipo de tarefa, mostra Categoria > Subcategoria filtrada
 * pelo polo_scope do escritorio.
 *
 * O caller carrega `categories` do endpoint
 * GET /api/v1/task-templates/meta/categories?polo_scope=...&taxonomy_version=v2
 * — esse endpoint ja entrega filtrado pelo polo certo (ou herda do
 * escritorio se passar office_external_id).
 *
 * Categorias sem subcategorias renderizam um item unico "(sem
 * subcategoria)" que retorna subcategory=null no onChange.
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

export interface ClassificationCategory {
  category: string;
  subcategories: string[];
}

export interface ClassificationValue {
  category: string;
  subcategory: string | null;
}

export interface ClassificationPickerProps {
  value: ClassificationValue | null;
  categories: ClassificationCategory[];
  onChange: (value: ClassificationValue) => void;
  /** "ativo" | "passivo" | "ambos" — exibido no placeholder pra orientar
   *  o operador qual arvore esta sendo mostrada. */
  polo?: string | null;
  label?: string;
  required?: boolean;
  placeholder?: string;
  searchPlaceholder?: string;
  triggerClassName?: string;
  disabled?: boolean;
}

const NO_SUB_LABEL = "(sem subcategoria)";

const normalize = (s: string) =>
  s.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");

export const ClassificationPicker = ({
  value,
  categories,
  onChange,
  polo,
  label = "Classificação",
  required = false,
  placeholder,
  searchPlaceholder = "Buscar por categoria ou subcategoria...",
  triggerClassName,
  disabled = false,
}: ClassificationPickerProps) => {
  const [open, setOpen] = useState(false);

  const effectivePlaceholder =
    placeholder ??
    (polo
      ? `Selecione a classificação (polo ${polo})`
      : "Selecione a classificação");

  // Label do botao: "Categoria · Subcategoria" quando ha selecao.
  // Quando subcategory e null, mostra so a categoria.
  const selectedLabel = (() => {
    if (!value) return null;
    return {
      catName: value.category,
      subName: value.subcategory,
    };
  })();

  return (
    <div className="grid gap-1.5">
      {label ? (
        <Label className="text-xs font-medium">
          {label}
          {required ? " *" : ""}
          {polo ? (
            <span className="ml-2 text-muted-foreground font-normal">
              · árvore: {polo}
            </span>
          ) : null}
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
                  {selectedLabel.catName}
                  {selectedLabel.subName ? " · " : ""}
                </span>
                {selectedLabel.subName ? (
                  <span className="font-medium">{selectedLabel.subName}</span>
                ) : (
                  <span className="text-muted-foreground italic text-xs">
                    {" "}
                    sem sub
                  </span>
                )}
              </span>
            ) : (
              <span className="text-muted-foreground">
                {effectivePlaceholder}
              </span>
            )}
            <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
          </Button>
        </PopoverTrigger>
        <PopoverContent
          className="w-[--radix-popover-trigger-width] p-0"
          align="start"
        >
          <Command
            // Matcher: busca case-insensitive sem acento em
            // "categoria | subcategoria". value do CommandItem e
            // "<categoria>::<subcategoria-ou-marker>".
            filter={(itemValue, search) =>
              normalize(itemValue).includes(normalize(search)) ? 1 : 0
            }
          >
            <CommandInput placeholder={searchPlaceholder} />
            <CommandList className="max-h-80">
              <CommandEmpty>Nenhum resultado.</CommandEmpty>
              {categories.map((c) => {
                if (c.subcategories.length === 0) {
                  // Categoria sem subs: render como item unico no nivel raiz.
                  const itemValue = `${c.category}::__no_sub__`;
                  const isSelected =
                    value?.category === c.category && value?.subcategory === null;
                  return (
                    <CommandGroup key={c.category} heading={c.category}>
                      <CommandItem
                        value={itemValue}
                        onSelect={() => {
                          onChange({ category: c.category, subcategory: null });
                          setOpen(false);
                        }}
                      >
                        <Check
                          className={cn(
                            "mr-2 h-4 w-4",
                            isSelected ? "opacity-100" : "opacity-0",
                          )}
                        />
                        <span className="truncate text-muted-foreground italic">
                          {NO_SUB_LABEL}
                        </span>
                      </CommandItem>
                    </CommandGroup>
                  );
                }
                return (
                  <CommandGroup key={c.category} heading={c.category}>
                    {c.subcategories.map((sub) => {
                      const itemValue = `${c.category}::${sub}`;
                      const isSelected =
                        value?.category === c.category &&
                        value?.subcategory === sub;
                      return (
                        <CommandItem
                          key={sub}
                          value={itemValue}
                          onSelect={() => {
                            onChange({
                              category: c.category,
                              subcategory: sub,
                            });
                            setOpen(false);
                          }}
                        >
                          <Check
                            className={cn(
                              "mr-2 h-4 w-4",
                              isSelected ? "opacity-100" : "opacity-0",
                            )}
                          />
                          <span className="truncate">{sub}</span>
                        </CommandItem>
                      );
                    })}
                  </CommandGroup>
                );
              })}
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
    </div>
  );
};

export default ClassificationPicker;
