import { BackendStatus } from "@/components/backend-status";
import { AuthGate } from "@/components/auth-gate";
import { Icon } from "@/components/icon";
import { publicEnv } from "@/lib/env";

const steps = [
  {
    number: "01",
    title: "Bring your document",
    description: "Start with a clear image or PDF of one driving licence.",
    icon: "upload",
  },
  {
    number: "02",
    title: "Review every detail",
    description:
      "Compare extracted information with the original and make corrections.",
    icon: "review",
  },
  {
    number: "03",
    title: "Ask, with context",
    description:
      "Find answers supported by your document, with sources to check.",
    icon: "chat",
  },
] as const;

/** The workspace supports review while keeping later document Q&A unavailable. */
export default function Home() {
  return (
    <div className="site-shell">
      <a href="#workspace" className="skip-link">
        Skip to workspace
      </a>
      <header className="site-header">
        <div className="header-inner">
          <a
            href="#workspace"
            className="brand"
            aria-label="LicenceIQ workspace"
          >
            <span className="brand-mark">
              <Icon name="document" />
            </span>
            <span>
              Licence<span className="brand-iq">IQ</span>
            </span>
          </a>
          <nav aria-label="Main navigation" className="main-nav">
            <a href="#workspace" className="nav-active">
              Workspace
            </a>
            <a href="#how-it-works">How it works</a>
          </nav>
          <div className="header-status">
            {publicEnv.showDevelopmentStatus ? (
              <BackendStatus />
            ) : (
              <span className="header-caption">Document intelligence</span>
            )}
          </div>
        </div>
      </header>
      <main id="workspace" className="main-content">
        <section className="hero" aria-labelledby="page-title">
          <div>
            <p className="eyebrow">
              <span className="eyebrow-line" /> AI DOCUMENT INTELLIGENCE
            </p>
            <h1 id="page-title">
              Your licence.
              <br />
              <span>Clearly understood.</span>
            </h1>
          </div>
          <p className="hero-description">
            Turn a driving licence into information you can review, correct and
            understand. All in one workspace.
          </p>
        </section>
        <AuthGate />
        <section
          id="how-it-works"
          className="how-it-works"
          aria-labelledby="steps-heading"
        >
          <div className="section-label">
            <h2 id="steps-heading">FROM DOCUMENT TO UNDERSTANDING</h2>
            <span>Three simple steps</span>
          </div>
          <ol className="steps-grid">
            {steps.map((step) => (
              <li key={step.number}>
                <span className="step-number">{step.number}</span>
                <div>
                  <h3>{step.title}</h3>
                  <p>{step.description}</p>
                </div>
                <Icon
                  name={step.icon}
                  className="step-icon"
                  width="20"
                  height="20"
                />
              </li>
            ))}
          </ol>
        </section>
      </main>
      <footer className="site-footer">
        <span>
          LicenceIQ <span className="footer-divider">/</span> Document
          intelligence
        </span>
        <span>Read. Review. Understand.</span>
      </footer>
    </div>
  );
}
