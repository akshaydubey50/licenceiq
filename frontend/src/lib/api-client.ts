import { publicEnv } from "@/lib/env";

/** A safe error the UI can display without exposing provider details. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly code: string,
    readonly status?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

export interface RequestOptions<T> {
  method?: "DELETE" | "GET" | "POST" | "PUT";
  headers?: HeadersInit;
  body?: BodyInit | null;
  signal?: AbortSignal;
  /** Defaults to ten seconds; longer document reads set their own bounded timeout. */
  timeoutMs?: number;
  decode: (response: Response) => Promise<T>;
}

/** Bound every API call and validate response data at the network boundary. */
export async function request<T>(
  path: string,
  {
    method = "GET",
    headers,
    body,
    signal,
    timeoutMs = 10_000,
    decode,
  }: RequestOptions<T>,
): Promise<T> {
  const controller = new AbortController();
  let timedOut = false;
  const forwardAbort = () => controller.abort();
  signal?.addEventListener("abort", forwardAbort, { once: true });
  if (signal?.aborted) controller.abort();
  const timeout = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  const requestHeaders = new Headers(headers);
  requestHeaders.set(
    "Accept",
    requestHeaders.get("Accept") ?? "application/json",
  );

  try {
    const response = await fetch(`${publicEnv.apiBaseUrl}${path}`, {
      method,
      headers: requestHeaders,
      body,
      cache: "no-store",
      signal: controller.signal,
    });

    if (!response.ok) {
      const body: unknown = await response.json().catch(() => null);
      const error = isRecord(body) && isRecord(body.error) ? body.error : null;
      throw new ApiError(
        typeof error?.message === "string"
          ? error.message
          : "The service could not complete the request.",
        typeof error?.code === "string" ? error.code : "HTTP_ERROR",
        response.status,
      );
    }

    return await decode(response);
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (timedOut) {
      throw new ApiError(
        "The request timed out. Please try again.",
        "REQUEST_TIMEOUT",
      );
    }
    if (controller.signal.aborted) {
      throw new ApiError("The request was interrupted.", "REQUEST_ABORTED");
    }
    throw new ApiError(
      "Could not connect to the backend. Check that it is running.",
      "NETWORK_ERROR",
    );
  } finally {
    clearTimeout(timeout);
    signal?.removeEventListener("abort", forwardAbort);
  }
}

export interface HealthResponse {
  status: "ok";
}

/** The only application API operation implemented in Phase 0. */
export function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  return request("/health", {
    signal,
    decode: async (response) => {
      const value: unknown = await response.json().catch(() => null);
      if (!isRecord(value) || value.status !== "ok") {
        throw new ApiError(
          "The backend returned an unexpected health response.",
          "INVALID_RESPONSE",
        );
      }
      return { status: "ok" };
    },
  });
}
