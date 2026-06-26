/** Client-side credentials cho API Basic Auth (sau khi login). */
export const AUTH_STORAGE_KEY = "dashboard_basic_auth";

export function getStoredAuthHeader(): string | null {
  if (typeof window === "undefined") return null;
  const raw = sessionStorage.getItem(AUTH_STORAGE_KEY);
  if (!raw) return null;
  return `Basic ${raw}`;
}

export function storeAuthCredentials(username: string, password: string) {
  const encoded = btoa(`${username}:${password}`);
  sessionStorage.setItem(AUTH_STORAGE_KEY, encoded);
}

export function clearAuthCredentials() {
  sessionStorage.removeItem(AUTH_STORAGE_KEY);
}

export function authFetchInit(): RequestInit {
  const auth = getStoredAuthHeader();
  return {
    cache: "no-store",
    credentials: "same-origin",
    headers: auth ? { Authorization: auth } : {},
  };
}
