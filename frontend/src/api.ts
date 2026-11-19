const apiOrigin = (import.meta.env.VITE_API_URL ?? "").trim().replace(/\/+$/, "");

export const usesHostedApi = Boolean(apiOrigin);

export function apiFetch(path: string, init?: RequestInit) {
  return fetch(`${apiOrigin}${path}`, init);
}
