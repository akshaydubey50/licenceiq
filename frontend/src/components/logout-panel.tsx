"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { useAuthSession } from "@/components/auth-session-provider";
import {
  logout,
  logoutErrorMessage,
  sessionAlreadyEnded,
} from "@/lib/auth-client";

type LogoutState = "pending" | "failed";

/** Revoke the active server session before clearing its in-memory token. */
export function LogoutPanel() {
  const router = useRouter();
  const { session, clearSession } = useAuthSession();
  const [state, setState] = useState<LogoutState>("pending");
  const [error, setError] = useState<string | null>(null);
  const controllerRef = useRef<AbortController | null>(null);

  const finishLogout = useCallback(() => {
    clearSession();
    router.replace("/login?logged_out=1");
  }, [clearSession, router]);

  const handleFailure = useCallback(
    (failure: unknown, controller: AbortController) => {
      if (controller.signal.aborted) return;
      if (sessionAlreadyEnded(failure)) {
        finishLogout();
      } else {
        setState("failed");
        setError(logoutErrorMessage());
      }
    },
    [finishLogout],
  );

  useEffect(() => {
    if (!session) {
      router.replace("/login?logged_out=1");
      return;
    }

    const controller = new AbortController();
    controllerRef.current = controller;
    void logout(session.accessToken, controller.signal)
      .then(() => {
        if (!controller.signal.aborted) finishLogout();
      })
      .catch((failure: unknown) => handleFailure(failure, controller))
      .finally(() => {
        if (controllerRef.current === controller) {
          controllerRef.current = null;
        }
      });
    return () => controller.abort();
  }, [finishLogout, handleFailure, router, session]);

  const retryLogout = () => {
    setState("pending");
    setError(null);
    if (!session) {
      router.replace("/login?logged_out=1");
      return;
    }

    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    void logout(session.accessToken, controller.signal)
      .then(() => {
        if (!controller.signal.aborted) finishLogout();
      })
      .catch((failure: unknown) => handleFailure(failure, controller))
      .finally(() => {
        if (controllerRef.current === controller) {
          controllerRef.current = null;
        }
      });
  };

  return (
    <section className="upload-panel auth-card" aria-labelledby="logout-title">
      <div className="panel-heading">
        <div className="panel-title">
          <h2 id="logout-title">
            {state === "pending" ? "Signing you out" : "Sign-out interrupted"}
          </h2>
        </div>
        <span className="subtle-label">SESSION SECURITY</span>
      </div>
      <div className="auth-status-copy" aria-live="polite">
        {state === "pending" ? (
          <p role="status">
            Please wait while LicenceIQ safely ends this browser session.
          </p>
        ) : (
          <>
            <p className="operation-message error-message" role="alert">
              {error}
            </p>
            <p>
              Your session is still available in this tab. Retry when the
              service is reachable.
            </p>
            <button
              type="button"
              className="upload-button save-button"
              onClick={retryLogout}
            >
              Retry sign-out
            </button>
          </>
        )}
      </div>
    </section>
  );
}
