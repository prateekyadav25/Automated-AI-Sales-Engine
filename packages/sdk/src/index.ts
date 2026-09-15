import type { Envelope } from "@agrayian/types";

const LOGIN_PATH = "/api/v1/auth/login";
const REFRESH_PATH = "/api/v1/auth/refresh";
const LOGOUT_PATH = "/api/v1/auth/logout";

export function getApiBase(): string {
  return process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
}

export function readToken(): string | null {
  if (typeof window === "undefined") return null;
  return sessionStorage.getItem("access_token");
}

export function writeToken(token: string | null): void {
  if (typeof window === "undefined") return;
  if (token) sessionStorage.setItem("access_token", token);
  else sessionStorage.removeItem("access_token");
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function skipBearer(path: string): boolean {
  return path === LOGIN_PATH || path === REFRESH_PATH || path === LOGOUT_PATH;
}

function errorMessage(json: unknown, fallback: string): string {
  if (!json || typeof json !== "object") return fallback;
  const body = json as { error?: { message?: string }; detail?: unknown };
  if (body.error?.message) return body.error.message;
  if (typeof body.detail === "string") return body.detail;
  return fallback;
}

let refreshInFlight: Promise<boolean> | null = null;

async function refreshAccessToken(): Promise<boolean> {
  if (!refreshInFlight) {
    refreshInFlight = (async () => {
      try {
        const response = await fetch(`${getApiBase()}${REFRESH_PATH}`, {
          method: "POST",
          credentials: "include",
          headers: { Accept: "application/json" },
        });
        if (!response.ok) {
          writeToken(null);
          return false;
        }
        const json = (await response.json()) as Envelope<{ access_token: string }>;
        const token = json.data?.access_token;
        if (!token) {
          writeToken(null);
          return false;
        }
        writeToken(token);
        return true;
      } catch {
        return false;
      }
    })().finally(() => {
      refreshInFlight = null;
    });
  }
  return refreshInFlight;
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<Envelope<T>> {
  return request<T>(path, init, true);
}

async function request<T>(path: string, init: RequestInit, allowRefresh: boolean): Promise<Envelope<T>> {
  const headers = new Headers(init.headers);
  if (!headers.has("Content-Type") && init.body) {
    headers.set("Content-Type", "application/json");
  }
  const token = skipBearer(path) ? null : readToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${getApiBase()}${path}`, {
    ...init,
    headers,
    credentials: "include",
  });
  const raw = await response.text();
  let json: Envelope<T> | unknown;
  try {
    json = JSON.parse(raw) as Envelope<T>;
  } catch {
    throw new ApiError(response.status, response.statusText || "Invalid JSON");
  }
  if (!response.ok) {
    if (allowRefresh && response.status === 401 && !skipBearer(path) && (await refreshAccessToken())) {
      return request<T>(path, init, false);
    }
    throw new ApiError(response.status, errorMessage(json, response.statusText));
  }
  return json as Envelope<T>;
}
