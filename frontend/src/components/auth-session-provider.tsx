"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import type { BrowserSession, SessionTokenResponse } from "@/types/auth";

interface AuthSessionContextValue {
  session: BrowserSession | null;
  startSession: (token: SessionTokenResponse) => void;
  clearSession: () => void;
}

const AuthSessionContext = createContext<AuthSessionContextValue | null>(null);
const MAX_TIMER_DELAY_MS = 2_147_483_647;

/** Owns the short-lived token in React memory across App Router navigation. */
export function AuthSessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<BrowserSession | null>(null);

  const startSession = useCallback((token: SessionTokenResponse) => {
    setSession({
      accessToken: token.accessToken,
      expiresAt: Date.now() + token.expiresIn * 1_000,
    });
  }, []);

  const clearSession = useCallback(() => setSession(null), []);

  useEffect(() => {
    if (!session) return;
    let timeout: number | undefined;

    const expireWhenDue = () => {
      const remainingMs = session.expiresAt - Date.now();
      if (remainingMs <= 0) {
        setSession((current) =>
          current?.accessToken === session.accessToken ? null : current,
        );
        return;
      }
      timeout = window.setTimeout(
        expireWhenDue,
        Math.min(remainingMs, MAX_TIMER_DELAY_MS),
      );
    };

    expireWhenDue();
    return () => {
      if (timeout !== undefined) window.clearTimeout(timeout);
    };
  }, [session]);

  const value = useMemo(
    () => ({ session, startSession, clearSession }),
    [clearSession, session, startSession],
  );

  return (
    <AuthSessionContext.Provider value={value}>
      {children}
    </AuthSessionContext.Provider>
  );
}

/** Access the layout-owned browser session without any persistent storage. */
export function useAuthSession(): AuthSessionContextValue {
  const value = useContext(AuthSessionContext);
  if (!value) {
    throw new Error("useAuthSession must be used inside AuthSessionProvider.");
  }
  return value;
}
