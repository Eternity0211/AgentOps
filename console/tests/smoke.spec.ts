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

test("shows incident lifecycle details and cursor-paged workflow history", async ({
  page,
}) => {
  await mockViewerSession(page);
  await page.route("**/api/v1/incidents/incident-detail**", (route) => {
    const requestUrl = new URL(route.request().url());
    if (requestUrl.pathname.endsWith("/evidence/evidence-browser/artifact")) {
      const hash = "a".repeat(64);
      return route.fulfill({
        contentType: "application/json",
        headers: {
          "Cache-Control": "private, no-store",
          ETag: `"sha256:${hash}"`,
          "X-Artifact-ID": "artifact-browser",
          "X-Content-SHA256": hash,
          "X-Content-Schema-Version": "1.0.0",
          "X-Redaction-Status": "REDACTED",
        },
        body: JSON.stringify({ pattern: "HTTP 500", count: 42 }),
      });
    }
    if (requestUrl.pathname.endsWith("/evidence")) {
      const continued = requestUrl.searchParams.has("cursor");
      return route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          items: [
            {
              id: continued ? "evidence-expired" : "evidence-browser",
              incident_id: "incident-detail",
              source_type: continued ? "DEPLOYMENT" : "LOG",
              source_instance: continued ? "deployment-events" : "loki-primary",
              tool_name: continued ? "query_deployments" : "query_logs",
              tool_version: "1.0.0",
              tool_schema_version: "1.0.0",
              normalized_query: continued
                ? { service: "orders" }
                : { service: "orders", level: "error" },
              observed_from: "2026-10-11T10:00:00Z",
              observed_to: "2026-10-11T10:01:00Z",
              collected_at: continued
                ? "2026-10-11T10:03:00Z"
                : "2026-10-11T10:02:00Z",
              artifact_id: continued ? "artifact-expired" : "artifact-browser",
              content_hash: continued ? "b".repeat(64) : "a".repeat(64),
              parser_version: "1.0.0",
              normalizer_version: "1.0.0",
              quality_score_basis_points: continued ? 7000 : 9500,
              quality_reasons: ["complete-window"],
              tool_call_id: continued ? "tool-expired" : "tool-browser",
              workflow_run_id: "run-browser",
              redaction_transform_id: continued ? null : "redaction-browser",
              parent_evidence_ids: continued ? ["evidence-browser"] : [],
              trust: continued ? "UNTRUSTED_INPUT" : "DIRECT_OBSERVATION",
              prompt_injection_status: continued ? "QUARANTINED" : "NONE",
              expires_at: continued
                ? "2026-10-11T10:04:00Z"
                : "2026-10-18T10:02:00Z",
              expired: continued,
              schema_version: "1.0.0",
            },
          ],
          next_cursor: continued ? null : "evidence-next",
        }),
      });
    }
    if (requestUrl.pathname.endsWith("/investigation")) {
      return route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          run: {
            schema_version: "1.0.0",
            workflow_run_id: "run-browser",
            graph_version: "1.0.0",
            phase: "EVIDENCE_REVIEW",
            status: "FAILED",
            budgets: {
              steps: { used: 2, maximum: 4, remaining: 2 },
              replans: { used: 1, maximum: 1, remaining: 0 },
              tool_calls: { used: 2, maximum: 4, remaining: 2 },
              model_calls: { used: 3, maximum: 6, remaining: 3 },
              tokens: { used: 300, maximum: 1000, remaining: 700 },
              cost_nanounits: { used: 30, maximum: 100, remaining: 70 },
            },
            plans: [
              {
                attempt: 1,
                plan_id: "plan-browser",
                summary: "Correlate metric and log evidence",
                model_call_id: "model-browser",
                created_at: "2026-10-11T10:01:00Z",
                steps: [
                  {
                    position: 1,
                    step_id: "metric-step",
                    objective: "Inspect order error rate",
                    expected_source: "METRIC",
                    depends_on: [],
                    parallel_group: 0,
                    tool_call_id: "tool-browser",
                    tool_name: "query_metrics",
                    tool_version: "1.0.0",
                    status: "FAILED",
                    failure_code: "TOOL_TIMEOUT",
                    started_at: "2026-10-11T10:02:00Z",
                    completed_at: "2026-10-11T10:03:00Z",
                  },
                ],
              },
            ],
            replans: [
              {
                completed_attempt: 1,
                next_attempt: 2,
                decision_fingerprint: "a".repeat(64),
                reason_code: "MORE_EVIDENCE_REQUIRED",
                occurred_at: "2026-10-11T10:04:00Z",
              },
            ],
            checkpoint_sequence: 7,
            error_code: "TOOL_TIMEOUT",
            updated_at: "2026-10-11T10:05:00Z",
          },
        }),
      });
    }
    if (requestUrl.pathname.endsWith("/diagnosis")) {
      return route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          result: {
            workflow_run_id: "run-browser",
            model_call_id: "model-diagnosis",
            report_fingerprint: "c".repeat(64),
            produced_at: "2026-10-11T10:04:00Z",
            disposition: "CANDIDATES",
            candidates: [
              {
                candidate_id: "candidate-browser",
                rank: 1,
                statement: "Connection pool exhaustion",
                supporting_evidence_ids: ["evidence-browser"],
                counter_evidence_ids: [],
                counter_evidence_treatment: "NOT_APPLICABLE",
                counter_evidence_explanation: null,
                missing_evidence: ["Per-pod saturation"],
                uncertainty: "One trace window is unavailable.",
                confidence_basis_points: 8200,
                gate: null,
              },
            ],
            missing_evidence: ["Per-pod saturation"],
            explanation: "Ranked from immutable evidence.",
            schema_version: "1.0.0",
          },
        }),
      });
    }
    if (requestUrl.pathname.endsWith("/timeline")) {
      const continued = requestUrl.searchParams.has("cursor");
      return route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          items: [
            continued
              ? {
                  kind: "cancellation_request",
                  prior_version: 2,
                  new_version: 3,
                  actor_id: "operator-browser",
                  reason: "stop at the next safe boundary",
                  correlation_id: "correlation-browser",
                  causation_id: "command-cancel-browser",
                  occurred_at: "2026-10-11T10:10:00Z",
                  prior_state: null,
                  new_state: null,
                  state_when_requested: "EXECUTING",
                  disposition: "DEFERRED_TO_SAFE_BOUNDARY",
                }
              : {
                  kind: "transition",
                  prior_version: 1,
                  new_version: 2,
                  actor_id: "operator-browser",
                  reason: "begin bounded diagnosis",
                  correlation_id: "correlation-browser",
                  causation_id: "command-start-browser",
                  occurred_at: "2026-10-11T10:05:00Z",
                  prior_state: "TRIAGED",
                  new_state: "INVESTIGATING",
                  state_when_requested: null,
                  disposition: null,
                },
          ],
          next_cursor: continued ? null : "opaque-next",
        }),
      });
    }
    return route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        id: "incident-detail",
        service: "orders",
        severity: "SEV2",
        state: "INVESTIGATING",
        version: 2,
        opened_at: "2026-10-11T10:00:00Z",
        updated_at: "2026-10-11T10:05:00Z",
        closed_at: null,
        cancelled_at: null,
        cancellation_requested_at: null,
      }),
    });
  });

  await page.goto("/incidents/incident-detail");
  await expect(
    page.getByRole("heading", { level: 1, name: "incident-detail" }),
  ).toBeVisible();
  await expect(
    page.locator(".incident-badges").getByText("orders", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: /TRIAGED.*INVESTIGATING/ }),
  ).toBeVisible();
  await expect(page.getByText("1 events loaded")).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Investigation progress" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Correlate metric and log evidence" }),
  ).toBeVisible();
  await expect(page.getByText("Failure: TOOL_TIMEOUT")).toBeVisible();
  await expect(
    page.getByText("Replan budget exhausted.", { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByText(/Attempt 1.*2: MORE EVIDENCE REQUIRED/),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Ranked diagnosis" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Connection pool exhaustion" }),
  ).toBeVisible();
  await expect(page.getByText("82.00% model confidence")).toBeVisible();
  await expect(page.getByText("Evidence gate not evaluated.")).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Evidence and artifacts" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "evidence-browser" }),
  ).toBeVisible();
  await expect(page.getByText("95.00% · complete-window")).toBeVisible();
  await expect(page.getByText("SHA-256 " + "a".repeat(64))).toBeVisible();
  await page.getByRole("button", { name: "View verified artifact" }).click();
  await expect(page.getByLabel("Verified artifact content")).toContainText(
    '"pattern":"HTTP 500"',
  );
  await expect(page.getByText("REDACTED")).toBeVisible();
  await page.getByRole("button", { name: "Load more evidence" }).click();
  await expect(
    page.getByRole("heading", { name: "evidence-expired" }),
  ).toBeVisible();
  await expect(page.getByText("Injection: QUARANTINED")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Artifact expired" }),
  ).toBeDisabled();
  await expect(page.getByText("2 evidence records loaded")).toBeVisible();

  await page.getByRole("button", { name: "Load more events" }).click();
  await expect(
    page.getByRole("heading", {
      name: "Cancellation requested while EXECUTING",
    }),
  ).toBeVisible();
  await expect(page.getByText("2 events loaded")).toBeVisible();
  await expect(page.getByRole("button", { name: /events/ })).toHaveCount(0);

  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth,
  );
  expect(overflow).toBe(false);
});
