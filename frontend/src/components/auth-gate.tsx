"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { DocumentWorkspace } from "@/components/document-workspace";
import { Icon } from "@/components/icon";
import { login, loginErrorMessage } from "@/lib/auth-client";
import { publicEnv } from "@/lib/env";

type Session = {
  accessToken: string;
  expiresAt: number;
};

/** Gates JWT deployments while leaving the local capability demo unchanged. */
export function AuthGate() {
  const [session, setSession] = useState<Session | null>(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const loginControllerRef = useRef<AbortController | null>(null);

  useEffect(
    () => () => {
      loginControllerRef.current?.abort();
    },
    [],
  );

  useEffect(() => {
    if (!session) return;
    const remainingMs = Math.max(0, session.expiresAt - Date.now());
    const timeout = window.setTimeout(
      () => {
        setSession(null);
        setNotice("Your session expired. Sign in again to continue.");
      },
      Math.min(remainingMs, 2_147_483_647),
    );
    return () => window.clearTimeout(timeout);
  }, [session]);

  if (publicEnv.authMode === "capability") {
    return <DocumentWorkspace />;
  }

  const endSession = (message: string) => {
    setSession(null);
    setNotice(message);
  };

  const submitLogin = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (pending || !username.trim() || password.length === 0) return;
    loginControllerRef.current?.abort();
    const controller = new AbortController();
    loginControllerRef.current = controller;
    setPending(true);
    setError(null);
    setNotice(null);
    try {
      const result = await login(username.trim(), password, controller.signal);
      if (controller.signal.aborted) return;
      setSession({
        accessToken: result.accessToken,
        expiresAt: Date.now() + result.expiresIn * 1_000,
      });
      setUsername("");
      setPassword("");
    } catch (loginFailure) {
      if (!controller.signal.aborted) {
        setError(loginErrorMessage(loginFailure));
      }
    } finally {
      if (loginControllerRef.current === controller) {
        loginControllerRef.current = null;
        setPending(false);
      }
    }
  };

  if (session) {
    return (
      <>
        <div className="review-actions" aria-label="Signed-in session">
          <span className="save-state" role="status">
            Authenticated session
          </span>
          <button
            type="button"
            className="secondary-button"
            onClick={() => endSession("You signed out safely.")}
          >
            Sign out
          </button>
        </div>
        <DocumentWorkspace
          sessionAccessToken={session.accessToken}
          onUnauthorized={() =>
            endSession("Your session ended. Sign in again to continue.")
          }
        />
      </>
    );
  }

  return (
    <div className="workspace-grid">
      <section className="upload-panel" aria-labelledby="sign-in-heading">
        <div className="panel-heading">
          <div className="panel-title">
            <Icon name="document" />
            <h2 id="sign-in-heading">Sign in to LicenceIQ</h2>
          </div>
          <span className="subtle-label">PRIVATE WORKSPACE</span>
        </div>
        <form
          className="review-form"
          onSubmit={submitLogin}
          style={{ padding: "8px 24px 24px" }}
        >
          <div className="review-fields">
            <div className="review-field review-field-wide">
              <div className="review-label-row">
                <label htmlFor="login-username">Username</label>
              </div>
              <input
                id="login-username"
                name="username"
                type="text"
                autoComplete="username"
                value={username}
                required
                disabled={pending}
                onChange={(event) => setUsername(event.target.value)}
              />
            </div>
            <div className="review-field review-field-wide">
              <div className="review-label-row">
                <label htmlFor="login-password">Password</label>
              </div>
              <input
                id="login-password"
                name="password"
                type="password"
                autoComplete="current-password"
                value={password}
                required
                disabled={pending}
                onChange={(event) => setPassword(event.target.value)}
              />
            </div>
          </div>
          <div className="review-actions">
            <button
              type="submit"
              className="upload-button save-button"
              disabled={pending || !username.trim() || password.length === 0}
            >
              {pending ? "Signing in…" : "Sign in"}
            </button>
          </div>
          {error && (
            <p className="operation-message error-message" role="alert">
              {error}
            </p>
          )}
          {notice && (
            <p className="operation-message" role="status">
              {notice}
            </p>
          )}
        </form>
        <div className="panel-footnote">
          <span className="small-dot" />
          Session details stay in this browser tab only
        </div>
      </section>
      <section className="details-panel" aria-labelledby="private-heading">
        <div className="panel-heading">
          <div className="panel-title">
            <Icon name="review" />
            <h2 id="private-heading">Private document access</h2>
          </div>
        </div>
        <div style={{ padding: "8px 24px 28px" }}>
          <p className="hero-description">
            Sign in with the account configured by your administrator. Your
            session is cleared when you sign out, close this tab, or the token
            expires.
          </p>
        </div>
      </section>
    </div>
  );
}
