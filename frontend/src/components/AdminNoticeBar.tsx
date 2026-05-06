import { useEffect, useState, useCallback, useContext } from "react";
import { AlertTriangle, Info, Megaphone, X } from "lucide-react";

import { AuthContext } from "@/contexts/AuthContext";
import { dismissAdminNotice, fetchActiveAdminNotices } from "@/services/api";
import type { AdminNoticeActive, AdminNoticeSeverity } from "@/types/api";

const POLL_INTERVAL_MS = 30_000;

const SEVERITY_STYLES: Record<AdminNoticeSeverity, {
  container: string;
  icon: string;
  Icon: React.ComponentType<{ className?: string }>;
}> = {
  info: {
    container: "bg-blue-50 border-blue-200 text-blue-900",
    icon: "text-blue-600",
    Icon: Info,
  },
  warning: {
    container: "bg-amber-50 border-amber-300 text-amber-900",
    icon: "text-amber-700",
    Icon: AlertTriangle,
  },
  danger: {
    container: "bg-red-50 border-red-300 text-red-900",
    icon: "text-red-700",
    Icon: Megaphone,
  },
};

/**
 * Banner de avisos broadcast emitidos pelo admin (manutencao, downtime,
 * comunicados gerais). Polling de 30s no GET /admin/notices/active —
 * backend ja' filtra (a) janela starts_at..ends_at e (b) dismissals do
 * usuario corrente, entao a UI so renderiza o que esta' realmente ativo
 * + nao foi fechado.
 *
 * Quando o usuario clica no X de um aviso:
 *  1. POST /dismiss persiste a marca pra ele (banner nao volta, mesmo
 *     se ele relogar).
 *  2. Removemos otimisticamente do state local (sem esperar o proximo
 *     poll, evita flicker).
 *
 * Multiplas notices empilham — cada uma e' um banner separado pra o
 * operador poder fechar uma a uma. Renderizado como `position: sticky`
 * no topo do AppContent — sempre visivel mesmo quando a pagina rola.
 */
export function AdminNoticeBar() {
  const auth = useContext(AuthContext);
  const isAuthenticated = auth?.isAuthenticated ?? false;
  const [notices, setNotices] = useState<AdminNoticeActive[]>([]);
  const [dismissingIds, setDismissingIds] = useState<Set<number>>(new Set());

  const load = useCallback(async () => {
    try {
      const data = await fetchActiveAdminNotices();
      setNotices(data);
    } catch (err) {
      // Silencioso — falhas de rede sao normais (laptop dormindo, VPN
      // caindo). O proximo tick reten ta'.
      console.warn("AdminNoticeBar: falha ao carregar avisos:", err);
    }
  }, []);

  useEffect(() => {
    if (!isAuthenticated) {
      setNotices([]);
      return;
    }
    // Carrega imediatamente + a cada 30s.
    load();
    const id = setInterval(load, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [isAuthenticated, load]);

  const handleDismiss = async (noticeId: number) => {
    setDismissingIds((s) => new Set(s).add(noticeId));
    // Otimistico: tira da UI antes da chamada terminar.
    setNotices((prev) => prev.filter((n) => n.id !== noticeId));
    try {
      await dismissAdminNotice(noticeId);
    } catch (err) {
      console.warn("AdminNoticeBar: falha ao dispensar aviso:", err);
      // Reload pra pegar estado real do servidor.
      load();
    } finally {
      setDismissingIds((s) => {
        const next = new Set(s);
        next.delete(noticeId);
        return next;
      });
    }
  };

  if (!isAuthenticated || notices.length === 0) return null;

  return (
    <div className="sticky top-0 z-50 flex flex-col gap-px">
      {notices.map((n) => {
        const style = SEVERITY_STYLES[n.severity] || SEVERITY_STYLES.info;
        const { Icon } = style;
        const isDismissing = dismissingIds.has(n.id);
        return (
          <div
            key={n.id}
            className={`border-b px-4 py-2.5 ${style.container}`}
            role="alert"
          >
            <div className="mx-auto flex max-w-screen-2xl items-start gap-3">
              <Icon className={`mt-0.5 h-5 w-5 shrink-0 ${style.icon}`} />
              <div className="flex-1 min-w-0">
                <div className="text-sm font-semibold">{n.title}</div>
                <div className="text-xs whitespace-pre-wrap">{n.message}</div>
                {n.ends_at ? (
                  <div className="text-[10px] mt-0.5 opacity-70">
                    Ate {new Date(n.ends_at).toLocaleString("pt-BR", {
                      timeZone: "America/Fortaleza",
                      dateStyle: "short",
                      timeStyle: "short",
                    })}
                  </div>
                ) : null}
              </div>
              <button
                type="button"
                onClick={() => handleDismiss(n.id)}
                disabled={isDismissing}
                className="shrink-0 rounded-md p-1 hover:bg-black/5 disabled:opacity-50"
                title="Dispensar este aviso (nao volta a aparecer pra voce)"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default AdminNoticeBar;
