/** Valid browser authentication modes. */
export type AuthMode = "capability" | "jwt" | "hybrid";

/** How one mounted workspace authenticates its document API calls. */
export type WorkspaceAccessMode = "capability" | "jwt" | "hybrid-guest";

/** Validated authentication response retained only in React memory. */
export interface SessionTokenResponse {
  accessToken: string;
  expiresIn: number;
}

/** One active browser session held by the root React provider. */
export interface BrowserSession {
  accessToken: string;
  expiresAt: number;
}
