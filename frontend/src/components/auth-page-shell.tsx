import Link from "next/link";
import { Icon } from "@/components/icon";

interface AuthPageShellProps {
  eyebrow: string;
  title: string;
  description: string;
  children: React.ReactNode;
}

/** Shared conventional page frame for local account actions. */
export function AuthPageShell({
  eyebrow,
  title,
  description,
  children,
}: AuthPageShellProps) {
  return (
    <div className="site-shell auth-page-shell">
      <header className="site-header">
        <div className="header-inner auth-header-inner">
          <Link href="/" className="brand" aria-label="LicenceIQ home">
            <span className="brand-mark">
              <Icon name="document" />
            </span>
            <span>
              Licence<span className="brand-iq">IQ</span>
            </span>
          </Link>
          <span className="header-caption">Private account access</span>
        </div>
      </header>
      <main className="auth-main">
        <section className="auth-intro" aria-labelledby="auth-page-title">
          <p className="eyebrow">
            <span className="eyebrow-line" /> {eyebrow}
          </p>
          <h1 id="auth-page-title">{title}</h1>
          <p className="hero-description">{description}</p>
        </section>
        {children}
      </main>
    </div>
  );
}
