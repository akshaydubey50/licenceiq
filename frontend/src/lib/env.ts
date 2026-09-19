import type { AuthMode } from "@/types/auth";

/** Public browser configuration only. Provider keys must remain on the backend. */
function apiBaseUrl(): string {
  const value = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";
  const parsed = new URL(value);

  if (
    !["http:", "https:"].includes(parsed.protocol) ||
    parsed.username ||
    parsed.password ||
    parsed.search ||
    parsed.hash
  ) {
    throw new Error(
      "NEXT_PUBLIC_API_BASE_URL must be an HTTP(S) URL without credentials or a query.",
    );
  }

  return value.replace(/\/+$/, "");
}

function authMode(): AuthMode {
  const value = process.env.NEXT_PUBLIC_AUTH_MODE ?? "capability";
  if (value !== "capability" && value !== "jwt" && value !== "hybrid") {
    throw new Error(
      "NEXT_PUBLIC_AUTH_MODE must be capability, jwt, or hybrid.",
    );
  }
  return value;
}

export const publicEnv = {
  apiBaseUrl: apiBaseUrl(),
  authMode: authMode(),
  showDevelopmentStatus: process.env.NODE_ENV === "development",
} as const;
