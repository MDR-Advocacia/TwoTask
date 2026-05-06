/**
 * Wrapper de `fetch` que cuida de:
 *   - Authorization header (JWT do localStorage).
 *   - Content-Type default: quando o caller passa um body string (ex.:
 *     `JSON.stringify(payload)`) e nao definiu Content-Type, assumimos
 *     application/json. Isso evita bugs recorrentes (FastAPI devolve
 *     422 sem o header, porque sem ele nao parsea o body).
 *
 *   FormData / Blob / ArrayBuffer NAO recebem default — o browser seta
 *   o Content-Type correto (com boundary do multipart, no caso do
 *   FormData) e nos forcarmos quebraria.
 */
export async function apiFetch(
  input: RequestInfo | URL,
  init: RequestInit = {},
): Promise<Response> {
  const headers = new Headers(init.headers ?? {});
  const token = localStorage.getItem("authToken");

  if (token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  // Default Content-Type pra body de string. Casos com FormData/Blob/etc
  // ficam fora — o browser ja' constroi o header correto pra esses.
  if (
    init.body !== undefined
    && init.body !== null
    && typeof init.body === "string"
    && !headers.has("Content-Type")
  ) {
    headers.set("Content-Type", "application/json");
  }

  return fetch(input, {
    ...init,
    headers,
  });
}
