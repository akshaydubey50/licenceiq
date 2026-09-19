"use client";

import { useEffect, useState } from "react";
import { ApiError, getHealth } from "@/lib/api-client";

type Connection =
  | { state: "checking" }
  | { state: "connected" }
  | { state: "unavailable"; message: string };

/** Real browser-to-backend health check. Mounted only in development. */
export function BackendStatus() {
  const [connection, setConnection] = useState<Connection>({
    state: "checking",
  });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    getHealth(controller.signal).then(
      () => {
        if (!controller.signal.aborted) setConnection({ state: "connected" });
      },
      (error: unknown) => {
        if (!controller.signal.aborted) {
          setConnection({
            state: "unavailable",
            message:
              error instanceof ApiError
                ? error.message
                : "Connection check failed.",
          });
        }
      },
    );
    return () => controller.abort();
  }, [attempt]);

  return (
    <div className="connection" data-state={connection.state}>
      <span className="connection-label" role="status" aria-live="polite">
        <span className="connection-dot" />
        {connection.state === "checking" && "Checking backend"}
        {connection.state === "connected" && "Backend connected"}
        {connection.state === "unavailable" && "Backend unavailable"}
        <span className="dev-label">DEV</span>
      </span>
      {connection.state === "unavailable" && (
        <>
          <span className="sr-only">{connection.message}</span>
          <button
            type="button"
            className="retry-button"
            title={connection.message}
            onClick={() => {
              setConnection({ state: "checking" });
              setAttempt((value) => value + 1);
            }}
          >
            Retry
          </button>
        </>
      )}
    </div>
  );
}
