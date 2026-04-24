"use client";

import type { AuthTokens } from "@/lib/api-types";

export const AUTH_SESSION_STORAGE_KEY = "workspace-auth-session-v1";

export function readStoredAuthTokens(): AuthTokens | null {
  if (typeof window === "undefined") {
    return null;
  }

  try {
    const raw = window.localStorage.getItem(AUTH_SESSION_STORAGE_KEY);
    if (!raw) {
      return null;
    }
    const payload = JSON.parse(raw);
    if (
      typeof payload?.access_token === "string" &&
      typeof payload?.refresh_token === "string" &&
      payload.access_token.trim() &&
      payload.refresh_token.trim()
    ) {
      return {
        access_token: payload.access_token,
        refresh_token: payload.refresh_token,
      };
    }
  } catch {
    return null;
  }

  return null;
}

export function persistAuthTokens(tokens: AuthTokens) {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(AUTH_SESSION_STORAGE_KEY, JSON.stringify(tokens));
}

export function clearStoredAuthTokens() {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.removeItem(AUTH_SESSION_STORAGE_KEY);
}

export function buildAuthRedirectUrl(path = "/") {
  if (typeof window === "undefined") {
    return "";
  }
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${window.location.origin}${normalizedPath}`;
}

export function clearAuthQueryParams() {
  if (typeof window === "undefined") {
    return;
  }
  const url = new URL(window.location.href);
  url.searchParams.delete("code");
  url.searchParams.delete("auth_flow");
  url.searchParams.delete("error");
  url.searchParams.delete("error_description");
  window.history.replaceState({}, document.title, url.toString());
}
