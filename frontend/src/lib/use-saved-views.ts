/**
 * Saved Views — hook generico de persistencia em localStorage.
 *
 * Usado pelo ProcessosTab pra salvar combos de filtros nomeados. Plan
 * section 7.0.3 patternD: localStorage v1, sync com tabela
 * `base_processual_saved_view` em v2.
 */

import { useCallback, useEffect, useState } from "react";

export interface SavedView<F> {
  id: string;
  name: string;
  filters: F;
  pinned?: boolean;
  created_at: string;
}

function keyFor(module: string): string {
  return `base-processual.saved-views.${module}`;
}

function read<F>(module: string): SavedView<F>[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(keyFor(module));
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function write<F>(module: string, views: SavedView<F>[]): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(keyFor(module), JSON.stringify(views));
  } catch {
    // localStorage cheio ou desabilitado — silently ignore
  }
}

export function useSavedViews<F>(module: string) {
  const [views, setViews] = useState<SavedView<F>[]>(() => read<F>(module));

  // Sincroniza entre abas do mesmo browser (storage event do MDN)
  useEffect(() => {
    const handler = (e: StorageEvent) => {
      if (e.key === keyFor(module)) {
        setViews(read<F>(module));
      }
    };
    window.addEventListener("storage", handler);
    return () => window.removeEventListener("storage", handler);
  }, [module]);

  const save = useCallback(
    (name: string, filters: F) => {
      setViews((prev) => {
        const next = [
          ...prev.filter((v) => v.name !== name),
          {
            id:
              typeof crypto !== "undefined" && "randomUUID" in crypto
                ? crypto.randomUUID()
                : Math.random().toString(36).slice(2),
            name,
            filters,
            pinned: false,
            created_at: new Date().toISOString(),
          },
        ];
        write(module, next);
        return next;
      });
    },
    [module],
  );

  const remove = useCallback(
    (id: string) => {
      setViews((prev) => {
        const next = prev.filter((v) => v.id !== id);
        write(module, next);
        return next;
      });
    },
    [module],
  );

  const togglePin = useCallback(
    (id: string) => {
      setViews((prev) => {
        const next = prev.map((v) =>
          v.id === id ? { ...v, pinned: !v.pinned } : v,
        );
        write(module, next);
        return next;
      });
    },
    [module],
  );

  return { views, save, remove, togglePin };
}
