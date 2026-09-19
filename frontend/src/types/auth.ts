/** Valid browser authentication modes. */
export type AuthMode = "capability" | "jwt";

/** Validated bootstrap-login response retained only in React memory. */
export interface LoginSession {
  accessToken: string;
  expiresIn: number;
}
