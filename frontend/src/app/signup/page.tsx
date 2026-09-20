import type { Metadata } from "next";
import Link from "next/link";
import { AuthForm } from "@/components/auth-form";
import { AuthPageShell } from "@/components/auth-page-shell";
import { authRouteWithNext, safeNextDestination } from "@/lib/auth-navigation";
import { publicEnv } from "@/lib/env";

export const metadata: Metadata = { title: "Sign up — LicenceIQ" };

export default async function SignupPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string | string[] }>;
}) {
  const nextDestination = safeNextDestination((await searchParams).next);

  return (
    <AuthPageShell
      eyebrow="LOCAL ACCOUNT"
      title="Create your account."
      description="Use a local account to keep each private document tied to your signed-in identity."
    >
      {publicEnv.selfRegistrationEnabled ? (
        <AuthForm mode="signup" nextDestination={nextDestination} showSignup />
      ) : (
        <section className="upload-panel auth-card">
          <div className="panel-heading">
            <div className="panel-title">
              <h2>Account creation is unavailable</h2>
            </div>
          </div>
          <div className="auth-status-copy">
            <p>Self-registration is not enabled for this LicenceIQ instance.</p>
            <Link
              className="secondary-button auth-inline-link"
              href={authRouteWithNext("/login", nextDestination)}
            >
              Go to sign in
            </Link>
          </div>
        </section>
      )}
    </AuthPageShell>
  );
}
