"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { type ReactNode, useEffect, useState } from "react";

import { isActivePath, navigationFor } from "@/lib/navigation";
import {
  loadSession,
  SessionLoadError,
  type SessionPrincipal,
} from "@/lib/session";

type ShellState =
  | { status: "loading" }
  | { status: "ready"; principal: SessionPrincipal }
  | { status: "error"; error: SessionLoadError };

const errorCopy = {
  unauthenticated: [
    "Sign in required",
    "Your session is missing or has expired.",
  ],
  forbidden: [
    "Access denied",
    "This account cannot open the administration console.",
  ],
  unavailable: [
    "Identity service unavailable",
    "No control-plane action was attempted.",
  ],
  invalid: [
    "Invalid identity response",
    "The console rejected an unexpected session payload.",
  ],
} as const;

export function AuthenticatedShell({
  children,
}: Readonly<{ children: ReactNode }>) {
  const pathname = usePathname();
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<ShellState>({ status: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    setState({ status: "loading" });
    void loadSession(controller.signal).then(
      (principal) => setState({ status: "ready", principal }),
      (error: SessionLoadError | DOMException) => {
        if (!(error instanceof DOMException && error.name === "AbortError")) {
          setState({ status: "error", error: error as SessionLoadError });
        }
      },
    );
    return () => controller.abort();
  }, [attempt]);

  if (state.status === "loading") {
    return (
      <main id="console-content" aria-busy="true" className="centered-state">
        <p className="eyebrow">AUTHENTICATING</p>
        <h1>Loading your console</h1>
        <p role="status">Confirming identity and permissions…</p>
      </main>
    );
  }

  if (state.status === "error") {
    const [title, detail] = errorCopy[state.error.kind];
    return (
      <main id="console-content" className="centered-state">
        <p className="eyebrow">ACCESS CHECK</p>
        <h1>{title}</h1>
        <p>{detail}</p>
        {state.error.requestId ? (
          <p>Request ID: {state.error.requestId}</p>
        ) : null}
        <button type="button" onClick={() => setAttempt((value) => value + 1)}>
          Retry access check
        </button>
      </main>
    );
  }

  const items = navigationFor(state.principal);
  return (
    <div className="app-shell">
      <a className="skip-link" href="#console-content">
        Skip to content
      </a>
      <header className="shell-header">
        <Link className="wordmark" href="/">
          AgentOps
        </Link>
        <div className="principal-summary">
          <span>{state.principal.actorId}</span>
          <span>{state.principal.tenantId}</span>
          <span>{state.principal.roles.join(" · ")}</span>
        </div>
      </header>
      <nav aria-label="Primary" className="primary-nav">
        {items.map((item) => (
          <Link
            aria-current={
              isActivePath(pathname, item.href) ? "page" : undefined
            }
            href={item.href}
            key={item.href}
          >
            {item.label}
          </Link>
        ))}
      </nav>
      <div id="console-content" tabIndex={-1}>
        {children}
      </div>
    </div>
  );
}
