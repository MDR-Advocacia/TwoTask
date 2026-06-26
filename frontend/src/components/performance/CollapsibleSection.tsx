// Seção recolhível reusável do "Minha Equipe". A página vai ter VÁRIAS seções
// (desempenho agora; outras depois) — cada uma embrulhada aqui, abre/fecha no
// cabeçalho. Estado local; default aberto.

import { useState } from "react";
import { ChevronDown } from "lucide-react";

export default function CollapsibleSection({
  title,
  subtitle,
  right,
  defaultOpen = true,
  children,
}: {
  title: string;
  subtitle?: string;
  right?: React.ReactNode;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section className="overflow-hidden rounded-xl border bg-card/40">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left transition-colors hover:bg-muted/40"
      >
        <div className="flex items-center gap-2">
          <ChevronDown
            className={`h-4 w-4 shrink-0 text-muted-foreground transition-transform ${open ? "" : "-rotate-90"}`}
          />
          <h2 className="text-base font-semibold">{title}</h2>
          {subtitle && <span className="text-xs font-normal text-muted-foreground">{subtitle}</span>}
        </div>
        {right && <div onClick={(e) => e.stopPropagation()}>{right}</div>}
      </button>
      {open && <div className="space-y-4 px-4 pb-4 pt-1">{children}</div>}
    </section>
  );
}
