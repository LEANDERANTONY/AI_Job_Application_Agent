"use client";

import { useEffect, useState } from "react";

import { getBackendHealth } from "@/lib/api";
import type { BackendHealth } from "@/lib/api-types";

type HealthState =
  | { status: "loading"; payload: null; error: null }
  | { status: "ready"; payload: BackendHealth; error: null }
  | { status: "error"; payload: null; error: string };

export function BackendHealthCard() {
  const [state, setState] = useState<HealthState>({
    status: "loading",
    payload: null,
    error: null,
  });

  useEffect(() => {
    let cancelled = false;

    async function loadHealth() {
      try {
        const payload = await getBackendHealth();
        if (!cancelled) {
          setState({ status: "ready", payload, error: null });
        }
      } catch (error) {
        if (!cancelled) {
          setState({
            status: "error",
            payload: null,
            error:
              error instanceof Error
                ? error.message
                : "Backend health check failed.",
          });
        }
      }
    }

    void loadHealth();

    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <article className="card card-highlight">
      <div className="card-header">
        <div>
          <p className="section-kicker">Live API Check</p>
          <h2>FastAPI reachability from the frontend</h2>
        </div>
        <span
          className={
            state.status === "ready"
              ? "status-badge status-success"
              : state.status === "error"
                ? "status-badge status-warning"
                : "status-badge"
          }
        >
          {state.status === "ready"
            ? "Connected"
            : state.status === "error"
              ? "Unreachable"
              : "Checking"}
        </span>
      </div>

      {state.status === "ready" ? (
        <div className="stats-grid">
          <div className="stat-block">
            <span>Status</span>
            <strong>{state.payload.status}</strong>
          </div>
          <div className="stat-block">
            <span>Service</span>
            <strong>{state.payload.service}</strong>
          </div>
          <div className="stat-block">
            <span>Version</span>
            <strong>{state.payload.version}</strong>
          </div>
        </div>
      ) : (
        <p className="muted-copy">
          {state.status === "error"
            ? state.error
            : "Waiting for the backend to answer through the Next.js rewrite path."}
        </p>
      )}
    </article>
  );
}
