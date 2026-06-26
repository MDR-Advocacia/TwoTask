// (?) explicativo reusável — toda métrica do "Minha Equipe" carrega um,
// pra ninguém precisar adivinhar o que cada número significa.

import { HelpCircle } from "lucide-react";

import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

export function InfoHint({ text, className }: { text: string; className?: string }) {
  return (
    <TooltipProvider delayDuration={120}>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            aria-label="O que isso significa?"
            onClick={(e) => e.preventDefault()}
            className={
              "inline-flex shrink-0 items-center justify-center text-muted-foreground/50 transition-colors hover:text-foreground focus:text-foreground focus:outline-none " +
              (className || "")
            }
          >
            <HelpCircle className="h-3.5 w-3.5" />
          </button>
        </TooltipTrigger>
        <TooltipContent
          side="top"
          className="max-w-xs whitespace-normal text-xs font-normal leading-relaxed"
        >
          {text}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

// Rótulo + (?) juntos — usado nos cabeçalhos de coluna e nos KPIs.
export function MetricLabel({
  label,
  hint,
  className,
}: {
  label: string;
  hint: string;
  className?: string;
}) {
  return (
    <span className={"inline-flex items-center gap-1 " + (className || "")}>
      {label}
      <InfoHint text={hint} />
    </span>
  );
}
