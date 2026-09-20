"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useAuthSession } from "@/components/auth-session-provider";
import { DocumentWorkspace } from "@/components/document-workspace";
import { Icon } from "@/components/icon";
import { authRouteWithNext } from "@/lib/auth-navigation";
import { publicEnv } from "@/lib/env";

type HybridRoute = "choice" | "guest";

/** Selects guest or account access while the root layout owns JWT state. */
export function AuthGate() {
  const router = useRouter();
  const { session, clearSession } = useAuthSession();
  const [hybridRoute, setHybridRoute] = useState<HybridRoute>("choice");
  const [notice, setNotice] = useState<string | null>(null);
  const [workspaceDirty, setWorkspaceDirty] = useState(false);

  useEffect(() => {
    if (publicEnv.authMode === "jwt" && !session) {
      router.replace("/login?next=/");
    }
  }, [router, session]);

  if (publicEnv.authMode === "capability") {
    return <DocumentWorkspace accessMode="capability" />;
  }

  const confirmWorkspaceExit = (action: string): boolean =>
    !workspaceDirty ||
    window.confirm(
      `You have unsaved review changes. ${action} will discard them. Continue?`,
    );

  const confirmGuestExit = (): boolean =>
    window.confirm(
      workspaceDirty
        ? "You have unsaved review changes. Leaving the guest workspace will discard them and remove this browser's access to the temporary document. The server copy remains until it expires under the retention policy. Continue?"
        : "Leaving the guest workspace will remove this browser's access to the temporary document, so you will not be able to reopen it. The server copy remains until it expires under the retention policy. Continue?",
    );

  const showChoice = (message?: string) => {
    setHybridRoute("choice");
    setWorkspaceDirty(false);
    setNotice(message ?? null);
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
            onClick={() => {
              if (confirmWorkspaceExit("Signing out")) {
                router.push("/logout");
              }
            }}
          >
            Sign out
          </button>
        </div>
        <DocumentWorkspace
          accessMode="jwt"
          sessionAccessToken={session.accessToken}
          onDirtyChange={setWorkspaceDirty}
          onUnauthorized={() => {
            clearSession();
            setWorkspaceDirty(false);
            setNotice(
              "Your account session ended. Sign in again or continue as a guest.",
            );
          }}
        />
      </>
    );
  }

  if (publicEnv.authMode === "jwt") {
    return (
      <section className="upload-panel auth-redirect" aria-live="polite">
        <p>Taking you to sign in…</p>
      </section>
    );
  }

  if (hybridRoute === "guest") {
    return (
      <>
        <div className="review-actions" aria-label="Guest session">
          <span className="save-state" role="status">
            Guest workspace · temporary document access
          </span>
          <button
            type="button"
            className="secondary-button"
            onClick={() => {
              if (confirmGuestExit()) {
                showChoice(
                  "The guest workspace was closed. Its upload remains temporary and expires under the server retention policy.",
                );
              }
            }}
          >
            Leave guest workspace
          </button>
        </div>
        <DocumentWorkspace
          accessMode="hybrid-guest"
          onDirtyChange={setWorkspaceDirty}
        />
      </>
    );
  }

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
        <div className="auth-choice-content">
          <p className="hero-description">
            Upload and review one licence without creating an account. Guest
            uploads are temporary and expire under the server&apos;s configured
            retention policy.
          </p>
          <div className="review-actions">
            <button
              type="button"
              className="upload-button save-button"
              onClick={() => {
                setNotice(null);
                setWorkspaceDirty(false);
                setHybridRoute("guest");
              }}
            >
              Continue as guest
            </button>
          </div>
        </div>
      </section>
      <section className="details-panel" aria-labelledby="account-heading">
        <div className="panel-heading">
          <div className="panel-title">
            <Icon name="review" />
            <h2 id="account-heading">Private account access</h2>
          </div>
          <span className="subtle-label">PRIVATE WORKSPACE</span>
        </div>
        <div className="auth-choice-content">
          <p className="hero-description">
            Sign in to a private workspace where documents are tied to your
            local account.
          </p>
          <div className="review-actions auth-actions">
            <Link
              className="secondary-button auth-inline-link"
              href={authRouteWithNext("/login", "/")}
            >
              Sign in
            </Link>
            {publicEnv.selfRegistrationEnabled && (
              <Link
                className="secondary-button auth-inline-link"
                href={authRouteWithNext("/signup", "/")}
              >
                Sign up
              </Link>
            )}
          </div>
        </div>
      </section>
      {notice && (
        <p className="operation-message" role="status">
          {notice}
        </p>
      )}
    </div>
  );
}
