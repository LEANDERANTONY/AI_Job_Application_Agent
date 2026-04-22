import Link from "next/link";
import type { ReactNode } from "react";

type MigrationShellProps = {
  children: ReactNode;
  currentPath: "/" | "/workspace";
  eyebrow: string;
  title: string;
  intro: string;
  actions?: Array<{
    href: string;
    label: string;
    variant?: "primary" | "secondary";
  }>;
};

const navigation = [
  { href: "/", label: "Overview" },
  { href: "/workspace", label: "Workspace" },
];

export function MigrationShell({
  children,
  currentPath,
  eyebrow,
  title,
  intro,
  actions = [],
}: MigrationShellProps) {
  return (
    <div className="app-shell">
      <div className="bg-orb bg-orb-one" />
      <div className="bg-orb bg-orb-two" />
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">AJ</div>
          <div>
            <p className="brand-title">AI Job Application Agent</p>
            <p className="brand-copy">Next.js + FastAPI transition branch</p>
          </div>
        </div>

        <nav className="nav-links" aria-label="Primary">
          {navigation.map((item) => {
            const active = currentPath === item.href;
            return (
              <Link
                className={active ? "nav-link nav-link-active" : "nav-link"}
                href={item.href}
                key={item.href}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
      </header>

      <main className="page-frame">
        <section className="hero">
          <p className="eyebrow">{eyebrow}</p>
          <h1>{title}</h1>
          <p className="hero-copy">{intro}</p>
          {actions.length ? (
            <div className="hero-actions">
              {actions.map((action) => (
                <Link
                  className={
                    action.variant === "secondary"
                      ? "button button-secondary"
                      : "button"
                  }
                  href={action.href}
                  key={`${action.href}-${action.label}`}
                >
                  {action.label}
                </Link>
              ))}
            </div>
          ) : null}
        </section>

        {children}
      </main>
    </div>
  );
}
