import { ApiError, request } from "@/lib/api-client";
import type { LoginSession } from "@/types/auth";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

/** Exchange bootstrap credentials for a short-lived token without persisting it. */
export function login(
  username: string,
  password: string,
  signal?: AbortSignal,
): Promise<LoginSession> {
  return request("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
    signal,
    decode: async (response) => {
      const value: unknown = await response.json().catch(() => null);
      if (
        !isRecord(value) ||
        typeof value.access_token !== "string" ||
        value.access_token.length === 0 ||
        value.token_type !== "bearer" ||
        typeof value.expires_in !== "number" ||
        !Number.isSafeInteger(value.expires_in) ||
        value.expires_in <= 0
      ) {
        throw new ApiError(
          "The backend returned an unexpected login response.",
          "INVALID_RESPONSE",
        );
      }
      return {
        accessToken: value.access_token,
        expiresIn: value.expires_in,
      };
    },
  });
}

/** Keep authentication failures generic so credentials are never disclosed. */
export function loginErrorMessage(error: unknown): string {
  if (error instanceof ApiError && error.status === 401) {
    return "The username or password is incorrect.";
  }
  return error instanceof ApiError
    ? error.message
    : "Sign-in could not be completed. Please try again.";
}
