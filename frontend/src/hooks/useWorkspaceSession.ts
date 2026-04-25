"use client";

// Hook owning the auth session + workspace-save-meta lifecycle.
// Lifted from `WorkspaceShell.tsx` as part of the Item 2 frontend
// split (see `docs/NEXT-STEPS-FRONTEND.md`, task #13).
//
// CRITICAL ORDERING (handoff hard rule, paraphrased):
//   1. Auth restore (URL ?code= → exchange OR localStorage → restore)
//   2. Session restored — `authStatus` flips to `"signed_in"`.
//   3. `useSavedJobs` reacts to `authStatus` change and pulls saved jobs.
//   4. `WorkspaceShell` reads URL ?tab=… via the `ui` slice's
//      `hydrateUiFromUrl()` action (called separately by the shell).
//
// This hook owns step 1 only. Steps 2-4 happen via the dependent hooks
// reacting to the state we publish here. Wrong order = lost state on
// refresh — do not change without re-reading the handoff.

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
  AuthTokens,
  DailyQuotaStatus,
  LoadSavedWorkspaceResponse,
  SavedWorkspaceMeta,
  WorkspaceAnalysisResponse,
} from "@/lib/api-types";
import {
  buildAuthRedirectUrl,
  clearAuthQueryParams,
  clearStoredAuthTokens,
  persistAuthTokens,
  readStoredAuthTokens,
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
  authTokens: AuthTokens | null;
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

  const authTokens = authSession?.session ?? null;
  const dailyQuota = authSession?.daily_quota ?? null;

  // Bootstrap on mount: handle ?code= → token exchange OR
  // localStorage → session restore. See ORDERING note at top of file.
  useEffect(() => {
    let cancelled = false;

    async function bootstrapAuth() {
      if (typeof window === "undefined") {
        return;
      }

      const params = new URLSearchParams(window.location.search);
      const authCode = params.get("code");
      const authFlow = params.get("auth_flow") ?? "";
      const authErrorDescription =
        params.get("error_description") ?? params.get("error");

      if (authErrorDescription) {
        clearStoredAuthTokens();
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
            persistAuthTokens(response.session);
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
          clearStoredAuthTokens();
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

      const storedTokens = readStoredAuthTokens();
      if (!storedTokens) {
        if (!cancelled) {
          setAuthStatus("signed_out");
        }
        return;
      }

      setAuthStatus("restoring");
      setAuthError(null);
      try {
        const response = await restoreAuthSession(storedTokens);
        if (!cancelled) {
          persistAuthTokens(response.session);
          setAuthSession(response);
          setAuthStatus("signed_in");
        }
      } catch (error) {
        clearStoredAuthTokens();
        if (!cancelled) {
          setAuthSession(null);
          setAuthStatus("signed_out");
          setAuthError(
            error instanceof Error
              ? error.message
              : "The saved login session could not be restored.",
          );
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
    if (!authTokens) {
      return;
    }

    setAuthActionLoading(true);
    try {
      await signOutAuthSession(authTokens);
    } catch {
      // Server-side sign-out failure is non-fatal; we still clear
      // local state so the user is logged out from this device.
    } finally {
      clearStoredAuthTokens();
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
    if (!authTokens || !authSession?.features.saved_workspace_enabled) {
      return null;
    }

    setAutoSaving(true);
    try {
      const response = await saveWorkspaceSnapshot(snapshot, authTokens);
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
    if (!authTokens) {
      setNotice({
        level: "warning",
        message: "Sign in with Google before reloading a saved workspace.",
      });
      return { kind: "unavailable" };
    }

    setWorkspaceReloading(true);
    try {
      const response = await loadSavedWorkspace(authTokens);
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
    authTokens,
    dailyQuota,
    signIn,
    signOutAuth,
    persistLatestWorkspace,
    reloadSavedWorkspace,
  };
}
