import type { Metadata } from "next";
import { AuthPageShell } from "@/components/auth-page-shell";
import { LogoutPanel } from "@/components/logout-panel";

export const metadata: Metadata = { title: "Sign out — LicenceIQ" };

export default function LogoutPage() {
  return (
    <AuthPageShell
      eyebrow="SESSION SECURITY"
      title="Sign out safely."
      description="LicenceIQ confirms that the server session has ended before removing it from this browser tab."
    >
      <LogoutPanel />
    </AuthPageShell>
  );
}
