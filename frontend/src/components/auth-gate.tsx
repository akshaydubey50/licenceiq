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

type HybridRoute = "choice" | "guest" | "login";

/** Selects guest or demo-login access without persisting either credential. */
export function AuthGate() {
  const [session, setSession] = useState<Session | null>(null);
  const [hybridRoute, setHybridRoute] = useState<HybridRoute>("choice");
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
        if (publicEnv.authMode === "hybrid") setHybridRoute("choice");
        setNotice("Your session expired. Sign in again to continue.");
      },
      Math.min(remainingMs, 2_147_483_647),
    );
    return () => window.clearTimeout(timeout);
  }, [session]);

  if (publicEnv.authMode === "capability") {
    return <DocumentWorkspace accessMode="capability" />;
  }

  const endSession = (message: string) => {
    setSession(null);
    if (publicEnv.authMode === "hybrid") setHybridRoute("choice");
    setNotice(message);
  };

  const showLogin = () => {
    setHybridRoute("login");
    setError(null);
    setNotice(null);
  };

  const showChoice = (message?: string) => {
    loginControllerRef.current?.abort();
    setHybridRoute("choice");
    setUsername("");
    setPassword("");
    setPending(false);
    setError(null);
    setNotice(message ?? null);
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
            {publicEnv.authMode === "hybrid"
              ? "Demo authenticated session"
              : "Authenticated session"}
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
          accessMode="jwt"
          sessionAccessToken={session.accessToken}
          onUnauthorized={() =>
            endSession("Your session ended. Sign in again to continue.")
          }
        />
      </>
    );
  }

  if (publicEnv.authMode === "hybrid" && hybridRoute === "guest") {
    return (
      <>
        <div className="review-actions" aria-label="Guest session">
          <span className="save-state" role="status">
            Guest workspace · temporary document access
          </span>
          <button
            type="button"
            className="secondary-button"
            onClick={() =>
              showChoice(
                "The guest workspace was closed. Its upload remains temporary and expires under the server retention policy.",
              )
            }
          >
            Leave guest workspace
          </button>
        </div>
        <DocumentWorkspace accessMode="hybrid-guest" />
      </>
    );
  }

  if (publicEnv.authMode === "hybrid" && hybridRoute === "choice") {
    return (
      <div className="workspace-grid">
        <section className="upload-panel" aria-labelledby="guest-heading">
          <div className="panel-heading">
            <div className="panel-title">
              <Icon name="document" />
              <h2 id="guest-heading">Continue as guest</h2>
            </div>
            <span className="subtle-label">QUICK DEMO</span>
          </div>
          <div style={{ padding: "8px 24px 28px" }}>
            <p className="hero-description">
              Upload and review one licence without creating an account. Guest
              uploads are temporary and expire under the server&apos;s
              configured retention policy.
            </p>
            <div className="review-actions">
              <button
                type="button"
                className="upload-button save-button"
                onClick={() => {
                  setNotice(null);
                  setHybridRoute("guest");
                }}
              >
                Continue as guest
              </button>
            </div>
          </div>
        </section>
        <section className="details-panel" aria-labelledby="demo-login-heading">
          <div className="panel-heading">
            <div className="panel-title">
              <Icon name="review" />
              <h2 id="demo-login-heading">Demo sign-in</h2>
            </div>
            <span className="subtle-label">PRIVATE WORKSPACE</span>
          </div>
          <div style={{ padding: "8px 24px 28px" }}>
            <p className="hero-description">
              Use the administrator-provided demo credentials to show user-owned
              document access. This is a technical demonstration, not account
              registration.
            </p>
            <div className="review-actions">
              <button
                type="button"
                className="secondary-button"
                onClick={showLogin}
              >
                Demo sign-in
              </button>
            </div>
            {notice && (
              <p className="operation-message" role="status">
                {notice}
              </p>
            )}
          </div>
        </section>
      </div>
    );
  }

  const isHybridLogin = publicEnv.authMode === "hybrid";
  return (
    <div className="workspace-grid">
      <section className="upload-panel" aria-labelledby="sign-in-heading">
        <div className="panel-heading">
          <div className="panel-title">
            <Icon name="document" />
            <h2 id="sign-in-heading">
              {isHybridLogin ? "Demo sign-in" : "Sign in to LicenceIQ"}
            </h2>
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
            {isHybridLogin && (
              <button
                type="button"
                className="secondary-button"
                disabled={pending}
                onClick={() => showChoice()}
              >
                Back
              </button>
            )}
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
            {isHybridLogin
              ? "This demo sign-in shows authenticated document ownership; it does not create or manage user accounts."
              : "Sign in with the account configured by your administrator. Your session is cleared when you sign out, close this tab, or the token expires."}
          </p>
        </div>
      </section>
    </div>
  );
}
