"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useAuthSession } from "@/components/auth-session-provider";
import {
  login,
  loginErrorMessage,
  signup,
  signupErrorMessage,
} from "@/lib/auth-client";
import { authRouteWithNext } from "@/lib/auth-navigation";

interface AuthFormProps {
  mode: "login" | "signup";
  nextDestination: string;
  showSignup: boolean;
  loggedOut?: boolean;
}

const PASSWORD_MIN_LENGTH = 7;
const PASSWORD_MAX_LENGTH = 256;

/** Submit local account credentials and keep the resulting token in context only. */
export function AuthForm({
  mode,
  nextDestination,
  showSignup,
  loggedOut = false,
}: AuthFormProps) {
  const router = useRouter();
  const { session, startSession } = useAuthSession();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const controllerRef = useRef<AbortController | null>(null);
  const isSignup = mode === "signup";

  useEffect(
    () => () => {
      controllerRef.current?.abort();
    },
    [],
  );

  useEffect(() => {
    if (session) router.replace(nextDestination);
  }, [nextDestination, router, session]);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (pending || !username.trim() || password.length === 0) return;
    if (isSignup && password !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }
    if (
      isSignup &&
      (password.length < PASSWORD_MIN_LENGTH ||
        password.length > PASSWORD_MAX_LENGTH)
    ) {
      setError(
        `Use a password between ${PASSWORD_MIN_LENGTH} and ${PASSWORD_MAX_LENGTH} characters.`,
      );
      return;
    }

    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setPending(true);
    setError(null);
    try {
      const token = isSignup
        ? await signup(username.trim(), password, controller.signal)
        : await login(username.trim(), password, controller.signal);
      if (controller.signal.aborted) return;
      startSession(token);
      setPassword("");
      setConfirmPassword("");
      router.replace(nextDestination);
    } catch (failure) {
      if (!controller.signal.aborted) {
        setError(
          isSignup ? signupErrorMessage(failure) : loginErrorMessage(failure),
        );
      }
    } finally {
      if (controllerRef.current === controller) {
        controllerRef.current = null;
        setPending(false);
      }
    }
  };

  if (session) {
    return (
      <section className="upload-panel auth-card" aria-live="polite">
        <p className="auth-status-copy">Opening your workspace…</p>
      </section>
    );
  }

  return (
    <section
      className="upload-panel auth-card"
      aria-labelledby="auth-form-title"
    >
      <div className="panel-heading">
        <div className="panel-title">
          <h2 id="auth-form-title">
            {isSignup ? "Create your local account" : "Account sign-in"}
          </h2>
        </div>
        <span className="subtle-label">LOCAL ACCESS</span>
      </div>
      <form className="review-form auth-form" onSubmit={submit}>
        {loggedOut && (
          <p className="auth-notice" role="status">
            You have signed out safely.
          </p>
        )}
        <div className="review-fields">
          <div className="review-field review-field-wide">
            <div className="review-label-row">
              <label htmlFor={`${mode}-username`}>Username</label>
            </div>
            <input
              id={`${mode}-username`}
              name="username"
              type="text"
              autoComplete="username"
              autoCapitalize="none"
              spellCheck={false}
              value={username}
              required
              maxLength={isSignup ? 64 : 128}
              pattern={isSignup ? "[A-Za-z0-9][A-Za-z0-9._-]{2,63}" : undefined}
              disabled={pending}
              onChange={(event) => setUsername(event.target.value)}
            />
          </div>
          <div className="review-field review-field-wide">
            <div className="review-label-row">
              <label htmlFor={`${mode}-password`}>Password</label>
            </div>
            <input
              id={`${mode}-password`}
              name="password"
              type="password"
              autoComplete={isSignup ? "new-password" : "current-password"}
              value={password}
              required
              minLength={isSignup ? PASSWORD_MIN_LENGTH : undefined}
              maxLength={isSignup ? PASSWORD_MAX_LENGTH : undefined}
              disabled={pending}
              aria-describedby={
                isSignup
                  ? error
                    ? `${mode}-error signup-password-requirements`
                    : "signup-password-requirements"
                  : error
                    ? `${mode}-error`
                    : undefined
              }
              onChange={(event) => setPassword(event.target.value)}
            />
            {isSignup && (
              <p id="signup-password-requirements" className="auth-field-hint">
                Use 7–256 characters. Confirm the same password below.
              </p>
            )}
          </div>
          {isSignup && (
            <div className="review-field review-field-wide">
              <div className="review-label-row">
                <label htmlFor="signup-confirm-password">
                  Confirm password
                </label>
              </div>
              <input
                id="signup-confirm-password"
                name="confirmPassword"
                type="password"
                autoComplete="new-password"
                value={confirmPassword}
                required
                minLength={PASSWORD_MIN_LENGTH}
                maxLength={PASSWORD_MAX_LENGTH}
                disabled={pending}
                aria-invalid={
                  confirmPassword.length > 0 && password !== confirmPassword
                }
                aria-describedby={
                  error
                    ? "signup-error signup-password-requirements"
                    : "signup-password-requirements"
                }
                onChange={(event) => setConfirmPassword(event.target.value)}
              />
            </div>
          )}
        </div>
        <div className="review-actions auth-actions">
          <button
            type="submit"
            className="upload-button save-button"
            disabled={
              pending ||
              !username.trim() ||
              password.length === 0 ||
              (isSignup && confirmPassword.length === 0)
            }
          >
            {pending
              ? isSignup
                ? "Creating account…"
                : "Signing in…"
              : isSignup
                ? "Create account"
                : "Sign in"}
          </button>
        </div>
        {error && (
          <p
            id={`${mode}-error`}
            className="operation-message error-message"
            role="alert"
          >
            {error}
          </p>
        )}
      </form>
      <div className="panel-footnote auth-footnote">
        <span className="small-dot" />
        {isSignup ? (
          <span>
            Already have an account?{" "}
            <Link href={authRouteWithNext("/login", nextDestination)}>
              Sign in
            </Link>
          </span>
        ) : showSignup ? (
          <span>
            Need an account?{" "}
            <Link href={authRouteWithNext("/signup", nextDestination)}>
              Sign up
            </Link>
          </span>
        ) : (
          <span>Your session stays in this browser tab only.</span>
        )}
      </div>
    </section>
  );
}
