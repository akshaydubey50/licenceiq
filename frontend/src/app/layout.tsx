import type { Metadata } from "next";
import { AuthSessionProvider } from "@/components/auth-session-provider";
import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "@fontsource/inter/600.css";
import "@fontsource/open-sans/400.css";
import "@fontsource/open-sans/500.css";
import "./globals.css";

export const metadata: Metadata = {
  title: "LicenceIQ — Document intelligence",
  description:
    "A clear workspace for reading, reviewing and understanding driving licences.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <AuthSessionProvider>{children}</AuthSessionProvider>
      </body>
    </html>
  );
}
