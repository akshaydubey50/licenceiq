import type { Metadata } from "next";
import { AuthForm } from "@/components/auth-form";
import { AuthPageShell } from "@/components/auth-page-shell";
import { safeNextDestination } from "@/lib/auth-navigation";
import { publicEnv } from "@/lib/env";

export const metadata: Metadata = { title: "Sign in — LicenceIQ" };

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{
    next?: string | string[];
    logged_out?: string | string[];
  }>;
}) {
  const params = await searchParams;
  const nextDestination = safeNextDestination(params.next);
  const loggedOut =
    (Array.isArray(params.logged_out)
      ? params.logged_out[0]
      : params.logged_out) === "1";

  return (
    <AuthPageShell
      eyebrow="PRIVATE WORKSPACE"
      title="Welcome back."
      description="Sign in to review documents owned by your local LicenceIQ account."
    >
      <AuthForm
        mode="login"
        nextDestination={nextDestination}
        showSignup={publicEnv.selfRegistrationEnabled}
        loggedOut={loggedOut}
      />
    </AuthPageShell>
  );
}
