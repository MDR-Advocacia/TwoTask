// Helpers compartilhados do modulo GED LegalOne (frontend).

// Extensoes aceitas no <input type=file> — espelha o allow-list do backend
// (settings.ged_legalone_allowed_extensions).
export const GED_ACCEPT =
  ".pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.jpg,.jpeg,.png,.txt,.csv,.zip";

// Sentinela do Select pra "sem tipo" (Radix Select nao aceita value vazio).
export const TYPE_NONE = "__none__";

const CNJ_REGEX =
  /(\d{7})[-.\s]?(\d{2})[-.\s]?(\d{4})[-.\s]?(\d{1})[-.\s]?(\d{2})[-.\s]?(\d{4})/;

export function extractCnjFromFilename(filename: string): string | null {
  if (!filename) return null;
  const base = filename.includes(".")
    ? filename.split(".").slice(0, -1).join(".")
    : filename;
  const m = base.match(CNJ_REGEX);
  return m ? m.slice(1).join("") : null;
}

export function normalizeCnj(raw: string): string | null {
  const digits = (raw || "").replace(/\D/g, "");
  return digits.length === 20 ? digits : null;
}

export function maskCnj(value: string): string {
  const d = (value || "").replace(/\D/g, "");
  if (d.length !== 20) return value || "";
  return `${d.slice(0, 7)}-${d.slice(7, 9)}.${d.slice(9, 13)}.${d.slice(13, 14)}.${d.slice(14, 16)}.${d.slice(16, 20)}`;
}

export interface ParsedCnjList {
  valid: string[];
  invalid: string[];
  duplicates: number;
}

export function parseCnjList(raw: string): ParsedCnjList {
  const tokens = (raw || "")
    .split(/[\n,;]+/)
    .map((t) => t.trim())
    .filter(Boolean);
  const valid: string[] = [];
  const invalid: string[] = [];
  const seen = new Set<string>();
  let duplicates = 0;
  for (const tok of tokens) {
    const norm = normalizeCnj(tok);
    if (!norm) {
      invalid.push(tok);
      continue;
    }
    if (seen.has(norm)) {
      duplicates++;
      continue;
    }
    seen.add(norm);
    valid.push(norm);
  }
  return { valid, invalid, duplicates };
}

export function fmtBytes(n: number | null | undefined): string {
  if (n == null) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("pt-BR", {
      dateStyle: "short",
      timeStyle: "short",
    });
  } catch {
    return iso;
  }
}

type BadgeVariant = "default" | "secondary" | "destructive" | "outline";

export const BATCH_STATUS_BADGE: Record<string, { label: string; variant: BadgeVariant }> = {
  DRAFT: { label: "Rascunho", variant: "secondary" },
  RESOLVING: { label: "Resolvendo CNJs", variant: "secondary" },
  PROCESSING: { label: "Enviando", variant: "default" },
  DONE: { label: "Concluido", variant: "default" },
  DONE_WITH_ERRORS: { label: "Concluido c/ erros", variant: "destructive" },
  CANCELLED: { label: "Cancelado", variant: "outline" },
};

export const ITEM_STATUS_BADGE: Record<string, { label: string; variant: BadgeVariant }> = {
  PENDENTE: { label: "Pendente", variant: "secondary" },
  PROCESSANDO: { label: "Enviando", variant: "default" },
  SUCESSO: { label: "Sucesso", variant: "default" },
  ERRO: { label: "Erro", variant: "destructive" },
  CNJ_NAO_ENCONTRADO: { label: "CNJ nao encontrado", variant: "destructive" },
};

export const MODE_LABEL: Record<string, string> = {
  SINGLE_FILE: "1 arquivo -> N processos",
  MULTI_FILE: "N arquivos -> N processos",
};
