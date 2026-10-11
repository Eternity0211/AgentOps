import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AuthenticatedShell } from "./authenticated-shell";

vi.mock("next/navigation", () => ({ usePathname: () => "/incidents/active" }));

const principal = {
  actor_id: "approver-1",
  tenant_id: "tenant-1",
  roles: ["APPROVER"],
  permissions: ["incident:read", "approval:decide", "audit:read"],
};

function response(body: unknown, status = 200, requestId?: string) {
  return new Response(JSON.stringify(body), {
    status,
    headers: requestId ? { "X-Request-ID": requestId } : undefined,
  });
}

afterEach(() => vi.unstubAllGlobals());

describe("AuthenticatedShell", () => {
  it("loads identity, exposes accessible navigation, and marks the active route", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(principal)));
    render(
      <AuthenticatedShell>
        <p>Authorized content</p>
      </AuthenticatedShell>,
    );

    expect(screen.getByRole("status")).toHaveTextContent("Confirming identity");
    expect(await screen.findByText("Authorized content")).toBeVisible();
    expect(
      screen.getByRole("link", { name: "Skip to content" }),
    ).toHaveAttribute("href", "#console-content");
    expect(screen.getByRole("navigation", { name: "Primary" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Incidents" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("link", { name: "Approvals" })).toBeVisible();
    expect(screen.queryByRole("link", { name: "Operations" })).toBeNull();
    expect(screen.getByText("APPROVER")).toBeVisible();
  });

  it.each([
    [403, "Access denied"],
    [503, "Identity service unavailable"],
    [200, "Invalid identity response"],
  ] as const)("renders a fail-closed %s state", async (status, title) => {
    const body = status === 200 ? { unexpected: true } : {};
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(body, status)));
    render(<AuthenticatedShell>hidden</AuthenticatedShell>);
    expect(await screen.findByRole("heading", { name: title })).toBeVisible();
    expect(screen.queryByText("hidden")).toBeNull();
  });

  it("shows correlation and retries an expired session", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(response({}, 401, "request-auth"))
      .mockResolvedValueOnce(response(principal));
    vi.stubGlobal("fetch", fetcher);
    render(<AuthenticatedShell>Recovered</AuthenticatedShell>);

    expect(await screen.findByText("Request ID: request-auth")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Retry access check" }));
    expect(await screen.findByText("Recovered")).toBeVisible();
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("cancels an in-flight identity request on unmount", async () => {
    const fetcher = vi.fn((_url: string, init: RequestInit) => {
      return new Promise((_resolve, reject) => {
        init.signal?.addEventListener("abort", () =>
          reject(new DOMException("cancelled", "AbortError")),
        );
      });
    });
    vi.stubGlobal("fetch", fetcher);
    const view = render(<AuthenticatedShell>hidden</AuthenticatedShell>);
    view.unmount();
    await waitFor(() => expect(fetcher).toHaveBeenCalledOnce());
  });
});
