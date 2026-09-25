/** Typed API client. One place for base URL, auth header, error normalisation. */

const BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") ?? "";
const TOKEN_KEY = "tt.token";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details: Record<string, unknown> = {},
    public requestId?: string,
  ) {
    super(message);
  }
  get isAuth() {
    return this.status === 401;
  }
  get isUnavailable() {
    return this.status === 503 || this.status === 0;
  }
}

let token: string | null = null;
try {
  token = localStorage.getItem(TOKEN_KEY);
} catch {
  token = null;
}
const listeners = new Set<() => void>();

export const auth = {
  get token() {
    return token;
  },
  set(t: string | null) {
    token = t;
    try {
      if (t) localStorage.setItem(TOKEN_KEY, t);
      else localStorage.removeItem(TOKEN_KEY);
    } catch {
      /* storage unavailable (private mode) — session stays in memory */
    }
    listeners.forEach((l) => l());
  },
  subscribe(l: () => void) {
    listeners.add(l);
    return () => listeners.delete(l);
  },
};

type Query = Record<string, string | number | boolean | string[] | null | undefined>;

export function qs(params: Query = {}): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    if (Array.isArray(v)) v.forEach((x) => sp.append(k, x));
    else sp.append(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

export function apiUrl(path: string): string {
  return `${BASE}/api/v1${path}`;
}

export async function api<T>(path: string, init: RequestInit & { query?: Query } = {}): Promise<T> {
  const { query, headers, ...rest } = init;
  let res: Response;
  try {
    res = await fetch(apiUrl(path) + qs(query), {
      ...rest,
      headers: {
        ...(rest.body && !(rest.body instanceof FormData) ? { "Content-Type": "application/json" } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...headers,
      },
    });
  } catch {
    throw new ApiError(0, "network_error", "Cannot reach the ThermalTrace API. Check your connection.");
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  let body: any = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = null;
  }
  if (!res.ok) {
    const e = body?.error ?? {};
    const err = new ApiError(res.status, e.code ?? "http_error", e.message ?? `Request failed (${res.status})`, e.details ?? {}, e.request_id);
    if (res.status === 401 && token) auth.set(null);
    throw err;
  }
  return body as T;
}

export const post = <T>(path: string, body?: unknown) => api<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
export const put = <T>(path: string, body: unknown) => api<T>(path, { method: "PUT", body: JSON.stringify(body) });
export const patch = <T>(path: string, body: unknown) => api<T>(path, { method: "PATCH", body: JSON.stringify(body) });
export const del = (path: string) => api<void>(path, { method: "DELETE" });

/** Authenticated binary download (reports). */
export async function downloadFile(path: string, filename: string): Promise<void> {
  const res = await fetch(apiUrl(path), { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!res.ok) throw new ApiError(res.status, "download_failed", "Download failed");
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}

/** Authenticated image fetch → object URL (SWIR renders). */
export async function fetchImage(path: string): Promise<string> {
  const res = await fetch(apiUrl(path), { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!res.ok) {
    let msg = "Image unavailable";
    try {
      msg = (await res.json()).error.message;
    } catch {
      /* non-JSON error */
    }
    throw new ApiError(res.status, "image_unavailable", msg);
  }
  return URL.createObjectURL(await res.blob());
}
