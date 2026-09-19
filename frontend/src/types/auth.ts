/** Valid browser authentication modes. */
export type AuthMode = "capability" | "jwt" | "hybrid";

/** How one mounted workspace authenticates its document API calls. */
export type WorkspaceAccessMode = "capability" | "jwt" | "hybrid-guest";

/** Validated bootstrap-login response retained only in React memory. */
export interface LoginSession {
  accessToken: string;
  expiresIn: number;
}
