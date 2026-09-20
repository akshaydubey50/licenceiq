import { ApiError, request } from "@/lib/api-client";
import type { SessionTokenResponse } from "@/types/auth";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

const TOKEN_RESPONSE_KEYS = ["access_token", "expires_in", "token_type"];

async function decodeTokenResponse(
  response: Response,
  expectedStatus: number,
  operation: string,
): Promise<SessionTokenResponse> {
  const value: unknown = await response.json().catch(() => null);
  const hasExactKeys =
    isRecord(value) &&
    Object.keys(value).length === TOKEN_RESPONSE_KEYS.length &&
    TOKEN_RESPONSE_KEYS.every((key) => Object.hasOwn(value, key));

  if (
    response.status !== expectedStatus ||
    !hasExactKeys ||
    typeof value.access_token !== "string" ||
    value.access_token.length === 0 ||
    value.token_type !== "bearer" ||
    typeof value.expires_in !== "number" ||
    !Number.isSafeInteger(value.expires_in) ||
    value.expires_in <= 0
  ) {
    throw new ApiError(
      `The backend returned an unexpected ${operation} response.`,
      "INVALID_RESPONSE",
    );
  }
  return {
    accessToken: value.access_token,
    expiresIn: value.expires_in,
  };
}

function exchangeCredentials(
  path: "/api/auth/login" | "/api/auth/signup",
  expectedStatus: number,
  operation: string,
  username: string,
  password: string,
  signal?: AbortSignal,
): Promise<SessionTokenResponse> {
  return request(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
    signal,
    decode: (response) =>
      decodeTokenResponse(response, expectedStatus, operation),
  });
}

/** Exchange account credentials for a short-lived token without persisting it. */
export function login(
  username: string,
  password: string,
  signal?: AbortSignal,
): Promise<SessionTokenResponse> {
  return exchangeCredentials(
    "/api/auth/login",
    200,
    "sign-in",
    username,
    password,
    signal,
  );
}

/** Create a local account and accept only the documented 201 token response. */
export function signup(
  username: string,
  password: string,
  signal?: AbortSignal,
): Promise<SessionTokenResponse> {
  return exchangeCredentials(
    "/api/auth/signup",
    201,
    "sign-up",
    username,
    password,
    signal,
  );
}

/** Revoke one active JWT session before its in-memory browser state is cleared. */
export function logout(
  accessToken: string,
  signal?: AbortSignal,
): Promise<void> {
  return request("/api/auth/logout", {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken}` },
    signal,
    decode: async (response) => {
      if (response.status !== 204) {
        throw new ApiError(
          "The backend returned an unexpected sign-out response.",
          "INVALID_RESPONSE",
        );
      }
    },
  });
}

/** An expired or already-revoked token means there is no server session left to retain. */
export function sessionAlreadyEnded(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401;
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

/** Avoid exposing whether a local account name is already registered. */
export function signupErrorMessage(error: unknown): string {
  if (
    error instanceof ApiError &&
    error.status !== undefined &&
    error.status >= 400 &&
    error.status < 500
  ) {
    return "Account creation could not be completed with those details. Please review them and try again.";
  }
  return error instanceof ApiError
    ? error.message
    : "Account creation could not be completed. Please try again.";
}

/** Keep revocation failures generic while leaving the token available for a retry. */
export function logoutErrorMessage(): string {
  return "Sign-out could not be completed. Please try again.";
}
