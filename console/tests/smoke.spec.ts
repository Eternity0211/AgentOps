import { expect, test } from "@playwright/test";

async function mockViewerSession(page: import("@playwright/test").Page) {
  await page.route("**/api/v1/session", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        actor_id: "viewer-browser",
        tenant_id: "tenant-browser",
        roles: ["VIEWER"],
        permissions: ["incident:read", "evidence:read", "audit:read"],
      }),
    }),
  );
}

test("renders a readable console foundation without horizontal overflow", async ({
  page,
}) => {
  await mockViewerSession(page);
  await page.goto("/");

  await expect(
    page.getByRole("heading", {
      level: 1,
      name: "AgentOps Incident Commander",
    }),
  ).toBeVisible();
  await expect(page.getByRole("status")).toHaveText("Console foundation ready");
  await expect(page.getByRole("navigation", { name: "Primary" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Incidents" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Audit" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Approvals" })).toHaveCount(0);
  await expect(page.getByRole("listitem")).toHaveCount(3);
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth,
  );
  expect(overflow).toBe(false);
});

test("filters and pages through authorized incidents", async ({ page }) => {
  await mockViewerSession(page);
  await page.route("**/api/v1/incidents?**", (route) => {
    const requestUrl = new URL(route.request().url());
    const cursor = requestUrl.searchParams.get("cursor");
    const service = requestUrl.searchParams.get("service") ?? "orders";
    const severity = requestUrl.searchParams.get("severity") ?? "SEV2";
    return route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        items: [
          {
            id: cursor ? "incident-2" : "incident-1",
            service,
            severity,
            state: requestUrl.searchParams.get("state") ?? "INVESTIGATING",
            version: 4,
            opened_at: "2026-10-11T10:00:00Z",
            updated_at: "2026-10-11T10:05:00Z",
          },
        ],
        next_cursor: cursor ? null : "opaque-next",
      }),
    });
  });

  await page.goto(
    "/incidents?severity=SEV2&state=INVESTIGATING&service=orders",
  );
  await expect(
    page.getByRole("heading", { level: 1, name: "Incidents" }),
  ).toBeVisible();
  await expect(page.getByLabel("Severity")).toHaveValue("SEV2");
  await expect(page.getByLabel("State")).toHaveValue("INVESTIGATING");
  await expect(page.getByLabel("Service")).toHaveValue("orders");
  await expect(page.getByRole("link", { name: "incident-1" })).toBeVisible();

  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page).toHaveURL(/cursor=opaque-next/);
  await expect(page.getByRole("link", { name: "incident-2" })).toBeVisible();
  await page.getByRole("button", { name: "Previous" }).click();
  await expect(page).not.toHaveURL(/cursor=/);
  await expect(page.getByRole("link", { name: "incident-1" })).toBeVisible();

  await page.getByLabel("Severity").selectOption("SEV1");
  await page.getByLabel("Service").fill("payments");
  await page.getByRole("button", { name: "Apply filters" }).click();
  await expect(page).toHaveURL(/severity=SEV1/);
  await expect(page).toHaveURL(/service=payments/);
  await expect(
    page.locator("tbody").getByText("payments", { exact: true }),
  ).toBeVisible();
  await expect(
    page.locator("tbody").getByText("SEV1", { exact: true }),
  ).toBeVisible();

  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth,
  );
  expect(overflow).toBe(false);
});
