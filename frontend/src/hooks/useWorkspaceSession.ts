"use client";

// Hook owning the auth session + workspace-save-meta lifecycle.
//
// CRITICAL ORDERING (handoff hard rule, paraphrased):
//   1. Auth restore (URL ?code= -> exchange OR cookie -> /session/restore).
//   2. Session restored; `authStatus` flips to `"signed_in"`.
//   3. `useSavedJobs` reacts to `authStatus` change and pulls saved jobs.
//   4. `WorkspaceShell` reads URL ?tab=... via the `ui` slice's
//      `hydrateUiFromUrl()` action (called separately by the shell).
//
// This hook owns step 1 only. Steps 2-4 happen via the dependent hooks
// reacting to the state we publish here. Wrong order = lost state on
// refresh. Do not change without re-reading the handoff.
//
// Tokens live in HttpOnly cookies (see backend/services/auth_cookies.py
// and frontend/src/lib/auth-session.ts). The frontend never sees them
// directly: every `fetch` is sent with `credentials: "include"` and the
// browser handles the rest.

import {
  useEffect,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";

import {
  exchangeGoogleCode,
  loadSavedWorkspace,
  restoreAuthSession,
  saveWorkspaceSnapshot,
  signOutAuthSession,
  startGoogleSignIn,
} from "@/lib/api";
import type {
  AuthSessionResponse,
  DailyQuotaStatus,
  LoadSavedWorkspaceResponse,
  SavedWorkspaceMeta,
  WorkspaceAnalysisResponse,
} from "@/lib/api-types";
import {
  buildAuthRedirectUrl,
  clearAuthQueryParams,
  clearLegacyAuthTokens,
} from "@/lib/auth-session";

type Notice =
  | { level: "info" | "success" | "warning"; message: string }
  | null;

export type AuthStatus = "loading" | "restoring" | "signed_out" | "signed_in";

export type UseWorkspaceSessionOptions = {
  setNotice: (notice: Notice) => void;
};

export type ReloadSavedWorkspaceResult =
  | { kind: "snapshot"; response: LoadSavedWorkspaceResponse }
  | { kind: "expired" }
  | { kind: "unavailable" };

export type UseWorkspaceSessionReturn = {
  authStatus: AuthStatus;
  setAuthStatus: Dispatch<SetStateAction<AuthStatus>>;
  authSession: AuthSessionResponse | null;
  setAuthSession: Dispatch<SetStateAction<AuthSessionResponse | null>>;
  authError: string | null;
  setAuthError: Dispatch<SetStateAction<string | null>>;
  authActionLoading: boolean;
  setAuthActionLoading: Dispatch<SetStateAction<boolean>>;
  workspaceSaveMeta: SavedWorkspaceMeta | null;
  setWorkspaceSaveMeta: Dispatch<SetStateAction<SavedWorkspaceMeta | null>>;
  workspaceReloading: boolean;
  setWorkspaceReloading: Dispatch<SetStateAction<boolean>>;
  autoSaving: boolean;
  dailyQuota: DailyQuotaStatus | null;
  signIn: () => Promise<void>;
  /**
   * Server sign-out + clear local auth/session state. Caller is
   * responsible for resetting cross-slice state (saved jobs, resume
   * builder, etc.) since those live in other hooks.
   */
  signOutAuth: () => Promise<void>;
  /**
   * Persist the current snapshot. Returns the new save-meta record
   * (or null on failure). Used both by the auto-save effect in the
   * shell and by `useAnalysisJob`'s onCompleted callback.
   */
  persistLatestWorkspace: (
    snapshot: WorkspaceAnalysisResponse,
  ) => Promise<SavedWorkspaceMeta | null>;
  /**
   * Fetch the saved-workspace snapshot for the current user. The
   * caller applies the snapshot across other slices; this hook only
   * updates the auth/save-meta side.
   */
  reloadSavedWorkspace: () => Promise<ReloadSavedWorkspaceResult>;
};

export function useWorkspaceSession({
  setNotice,
}: UseWorkspaceSessionOptions): UseWorkspaceSessionReturn {
  const [authStatus, setAuthStatus] = useState<AuthStatus>("loading");
  const [authSession, setAuthSession] = useState<AuthSessionResponse | null>(
    null,
  );
  const [authError, setAuthError] = useState<string | null>(null);
  const [authActionLoading, setAuthActionLoading] = useState(false);
  const [workspaceSaveMeta, setWorkspaceSaveMeta] =
    useState<SavedWorkspaceMeta | null>(null);
  const [workspaceReloading, setWorkspaceReloading] = useState(false);
  const [autoSaving, setAutoSaving] = useState(false);

  const dailyQuota = authSession?.daily_quota ?? null;

  // Bootstrap on mount: handle ?code= token exchange OR
  // probe /auth/session/restore. Backend reads the cookie, returns
  // the user record on success or a 400 on no cookie / expired session.
  useEffect(() => {
    let cancelled = false;

    async function bootstrapAuth() {
      if (typeof window === "undefined") {
        return;
      }

      // One-shot migration: drop the legacy localStorage token blob.
      // Cookies replace it; this is just hygiene so the old key doesn't
      // sit in users' browsers forever. Safe to delete in a few weeks.
      clearLegacyAuthTokens();

      const params = new URLSearchParams(window.location.search);
      const authCode = params.get("code");
      const authFlow = params.get("auth_flow") ?? "";
      const authErrorDescription =
        params.get("error_description") ?? params.get("error");

      if (authErrorDescription) {
        clearAuthQueryParams();
        if (!cancelled) {
          setAuthSession(null);
          setAuthStatus("signed_out");
          setAuthError(authErrorDescription);
        }
        return;
      }

      if (authCode) {
        setAuthStatus("restoring");
        setAuthError(null);
        try {
          const response = await exchangeGoogleCode(
            authCode,
            authFlow,
            buildAuthRedirectUrl("/workspace"),
          );
          if (!cancelled) {
            setAuthSession(response);
            setAuthStatus("signed_in");
            setNotice({
              level: "success",
              message: `Signed in as ${
                response.app_user.display_name ||
                response.app_user.email ||
                "your account"
              }.`,
            });
          }
        } catch (error) {
          if (!cancelled) {
            setAuthSession(null);
            setAuthStatus("signed_out");
            setAuthError(
              error instanceof Error
                ? error.message
                : "Google sign-in failed unexpectedly.",
            );
          }
        } finally {
          clearAuthQueryParams();
        }
        return;
      }

      // No URL code: try a silent restore. The browser will attach
      // the auth cookie if one is present; the backend returns the
      // session on success or 400 on absent/expired cookie. We treat
      // any failure here as "not signed in" without surfacing an
      // error, because a fresh first-time visitor will hit this path
      // legitimately and shouldn't see an error toast.
      setAuthStatus("restoring");
      setAuthError(null);
      try {
        const response = await restoreAuthSession();
        if (!cancelled) {
          setAuthSession(response);
          setAuthStatus("signed_in");
        }
      } catch {
        if (!cancelled) {
          setAuthSession(null);
          setAuthStatus("signed_out");
        }
      }
    }

    void bootstrapAuth();

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- bootstrap runs once
  }, []);

  async function signIn() {
    setAuthActionLoading(true);
    setAuthError(null);
    try {
      const response = await startGoogleSignIn(
        buildAuthRedirectUrl("/workspace"),
      );
      window.location.href = response.url;
    } catch (error) {
      setAuthError(
        error instanceof Error
          ? error.message
          : "Google sign-in could not be started.",
      );
      setNotice({
        level: "warning",
        message:
          error instanceof Error
            ? error.message
            : "Google sign-in could not be started.",
      });
      setAuthActionLoading(false);
    }
  }

  async function signOutAuth() {
    setAuthActionLoading(true);
    try {
      await signOutAuthSession();
    } catch {
      // Server-side sign-out failure is non-fatal; the backend clears
      // cookies on failure too, and we always reset local state below
      // so the user is logged out from this device regardless.
    } finally {
      setAuthSession(null);
      setAuthStatus("signed_out");
      setAuthError(null);
      setWorkspaceSaveMeta(null);
      setAuthActionLoading(false);
      setNotice({
        level: "info",
        message:
          "Signed out. Local account session and saved-state access were cleared.",
      });
    }
  }

  async function persistLatestWorkspace(
    snapshot: WorkspaceAnalysisResponse,
  ): Promise<SavedWorkspaceMeta | null> {
    if (
      authStatus !== "signed_in" ||
      !authSession?.features.saved_workspace_enabled
    ) {
      return null;
    }

    setAutoSaving(true);
    try {
      const response = await saveWorkspaceSnapshot(snapshot);
      setWorkspaceSaveMeta(response.saved_workspace);
      return response.saved_workspace;
    } catch (error) {
      setNotice({
        level: "warning",
        message:
          error instanceof Error
            ? error.message
            : "The latest workspace could not be saved.",
      });
      return null;
    } finally {
      setAutoSaving(false);
    }
  }

  async function reloadSavedWorkspace(): Promise<ReloadSavedWorkspaceResult> {
    if (authStatus !== "signed_in") {
      setNotice({
        level: "warning",
        message: "Sign in with Google before reloading a saved workspace.",
      });
      return { kind: "unavailable" };
    }

    setWorkspaceReloading(true);
    try {
      const response = await loadSavedWorkspace();
      if (response.status !== "available" || !response.workspace_snapshot) {
        setNotice({
          level: response.status === "expired" ? "warning" : "info",
          message:
            response.status === "expired"
              ? "Your saved workspace expired after 24 hours. Run the flow again to save a fresh one."
              : "No saved workspace is available to reload yet.",
        });
        return {
          kind: response.status === "expired" ? "expired" : "unavailable",
        };
      }

      setWorkspaceSaveMeta(response.saved_workspace ?? null);
      return { kind: "snapshot", response };
    } catch (error) {
      setNotice({
        level: "warning",
        message:
          error instanceof Error
            ? error.message
            : "Saved workspace reload failed unexpectedly.",
      });
      return { kind: "unavailable" };
    } finally {
      setWorkspaceReloading(false);
    }
  }

  return {
    authStatus,
    setAuthStatus,
    authSession,
    setAuthSession,
    authError,
    setAuthError,
    authActionLoading,
    setAuthActionLoading,
    workspaceSaveMeta,
    setWorkspaceSaveMeta,
    workspaceReloading,
    setWorkspaceReloading,
    autoSaving,
    dailyQuota,
    signIn,
    signOutAuth,
    persistLatestWorkspace,
    reloadSavedWorkspace,
  };
}
