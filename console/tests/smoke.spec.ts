import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

async function expectAccessible(page: Page) {
  const result = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
    .analyze();
  expect(
    result.violations.map((violation) => ({
      id: violation.id,
      impact: violation.impact,
      targets: violation.nodes.map((node) => node.target),
    })),
  ).toEqual([]);
}

async function mockViewerSession(page: Page) {
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
}, testInfo) => {
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
  if (!testInfo.project.name.startsWith("mobile")) {
    await page.keyboard.press("Tab");
    await expect(
      page.getByRole("link", { name: "Skip to content" }),
    ).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.locator("#console-content")).toBeFocused();
  }
  await expectAccessible(page);
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

  await expectAccessible(page);
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
    if (requestUrl.pathname.endsWith("/recovery")) {
      return route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          execution: {
            id: "execution-browser",
            action: "rollback_service",
            approval_id: "approval-browser",
            actor_id: "operator-browser",
            status: "SUCCEEDED",
            version: 2,
            service: "orders",
            environment: "PRODUCTION",
            target_reference: "simulator-orders",
            expected_current_version: "2.0.0",
            stable_version: "1.0.0",
            before: {
              artifact_id: "snapshot-before-browser",
              content_hash: "1".repeat(64),
              deployed_version: "2.0.0",
              observed_at: "2026-10-11T10:05:59Z",
            },
            after: {
              artifact_id: "snapshot-after-browser",
              content_hash: "2".repeat(64),
              deployed_version: "1.0.0",
              observed_at: "2026-10-11T10:06:30Z",
            },
            started_at: "2026-10-11T10:06:00Z",
            completed_at: "2026-10-11T10:07:00Z",
            failure_code: null,
            proposal_fingerprint: "3".repeat(64),
            policy_decision_fingerprint: "4".repeat(64),
            execution_fingerprint: "5".repeat(64),
            schema_version: "1.0.0",
          },
          verification: {
            id: "verification-browser",
            observation_id: "observation-browser",
            scenario: "RELEASE_HTTP_500",
            outcome: "FAIL",
            reasons: ["P95_LATENCY_ABOVE_LIMIT"],
            service: "orders",
            environment: "PRODUCTION",
            expected_stable_version: "1.0.0",
            window_started_at: "2026-10-11T10:08:00Z",
            window_ended_at: "2026-10-11T10:09:00Z",
            window_duration_seconds: 60,
            sample_count: 3,
            first_sample: {
              observed_at: "2026-10-11T10:08:00Z",
              error_rate_basis_points: 50,
              p95_latency_ms: 400,
              health_endpoint_healthy: true,
              deployed_version: "1.0.0",
              new_alert_count: 0,
            },
            last_sample: {
              observed_at: "2026-10-11T10:09:00Z",
              error_rate_basis_points: 75,
              p95_latency_ms: 501,
              health_endpoint_healthy: true,
              deployed_version: "1.0.0",
              new_alert_count: 0,
            },
            evidence: {
              error_rate: "evidence-browser",
              p95_latency: "evidence-p95-browser",
              health_endpoint: "evidence-health-browser",
              deployed_version: "evidence-version-browser",
              new_alerts: "evidence-alerts-browser",
            },
            collected_at: "2026-10-11T10:09:01Z",
            expires_at: "2026-10-18T10:09:01Z",
            evaluated_at: "2026-10-11T10:09:02Z",
            criteria_fingerprint: "6".repeat(64),
            observation_fingerprint: "7".repeat(64),
            execution_fingerprint: "5".repeat(64),
            input_fingerprint: "8".repeat(64),
            decision_fingerprint: "9".repeat(64),
            rules_version: "1.0.0",
            schema_version: "1.0.0",
          },
          route: {
            status: "REDIAGNOSE",
            final_state: "INVESTIGATING",
            transitions: [
              {
                prior_state: "VERIFYING",
                new_state: "INVESTIGATING",
                prior_version: 7,
                new_version: 8,
                reason:
                  "failed rollback verification; route=REDIAGNOSE; compensation=forbidden",
                actor_id: "operator-browser",
                correlation_id: "correlation-recovery-browser",
                causation_id: "verification-browser",
                occurred_at: "2026-10-11T10:09:03Z",
              },
            ],
          },
          compensation: {
            eligible: false,
            separately_authorized: false,
            status: "FORBIDDEN_FOR_ROLLBACK_SERVICE",
            detail:
              "A failed verification routes to bounded re-diagnosis or human handoff.",
          },
        }),
      });
    }
    if (requestUrl.pathname.endsWith("/platform-observability")) {
      return route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          model_calls: [
            {
              id: "model-browser",
              workflow_run_id: "run-browser",
              node: "diagnosis.hypothesis",
              attempt: 1,
              prompt_id: "prompt-browser",
              prompt_version: "1.0.0",
              prompt_fingerprint: "a".repeat(64),
              provider: "mock",
              model: "deterministic",
              status: "SUCCEEDED",
              started_at: "2026-10-11T10:04:00Z",
              completed_at: "2026-10-11T10:04:02Z",
              duration_ms: 2000,
              token_usage: {
                input_tokens: 100,
                output_tokens: 20,
                cached_input_tokens: 10,
                reasoning_tokens: 5,
                total_tokens: 120,
              },
              cost: {
                amount_nanounits: 12345,
                currency: "USD",
                source: "RATE_CARD_CALCULATED",
                rate_card_version: "1.0.0",
              },
              metering_unavailable_reason: null,
              failure_code: null,
              correlation_id: "correlation-browser",
              causation_id: "node-browser",
              request_hash: "b".repeat(64),
              response_hash: "c".repeat(64),
              input_schema_version: "1.0.0",
              output_schema_version: "1.0.0",
              schema_version: "1.0.0",
            },
          ],
          model_calls_truncated: false,
          usage: {
            call_count: 1,
            metered_call_count: 1,
            unavailable_call_count: 0,
            pending_call_count: 0,
            statuses: {
              started: 0,
              succeeded: 1,
              failed: 0,
              timed_out: 0,
              refused: 0,
            },
            tokens: {
              input_tokens: 100,
              output_tokens: 20,
              cached_input_tokens: 10,
              reasoning_tokens: 5,
              total_tokens: 120,
            },
            costs: [{ currency: "USD", amount_nanounits: 12345 }],
          },
          checkpoints: [
            {
              workflow_run_id: "run-browser",
              graph_version: "1.3.0",
              phase: "COMPLETE",
              status: "COMPLETE",
              checkpoint_sequence: 7,
              projection_fingerprint: "d".repeat(64),
              observed_at: "2026-10-11T10:05:00Z",
              scope: "LATEST_DURABLE_PROJECTION",
            },
          ],
          checkpoints_truncated: false,
          audit: {
            status: "COMPLETE",
            complete: true,
            scope: "DISPLAYED_MODEL_CALLS",
            expected_event_count: 2,
            observed_event_count: 2,
            missing_event_count: 0,
            duplicate_event_count: 0,
            requirements: [
              {
                model_call_id: "model-browser",
                event_type: "model.call_started",
                status: "PRESENT",
                observed_sequences: [20],
              },
              {
                model_call_id: "model-browser",
                event_type: "model.call_finished",
                status: "PRESENT",
                observed_sequences: [21],
              },
            ],
            rules_version: "1.0.0",
          },
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
    page.getByRole("heading", { name: "Execution and verification" }),
  ).toBeVisible();
  await expect(page.getByLabel("Deployment version comparison")).toContainText(
    "2.0.0",
  );
  await expect(page.getByText("501 ms")).toBeVisible();
  await expect(page.getByText("P95 LATENCY ABOVE LIMIT")).toBeVisible();
  await expect(page.getByRole("heading", { name: "REDIAGNOSE" })).toBeVisible();
  await expect(page.getByLabel("Compensation authorization")).toContainText(
    "No separate compensation authorization exists",
  );
  await expect(
    page.getByRole("heading", { name: "Agent platform observability" }),
  ).toBeVisible();
  await expect(page.getByLabel("Model usage totals")).toContainText("120");
  await expect(page.getByText("diagnosis.hypothesis")).toBeVisible();
  await expect(page.getByText(/Checkpoint 7/)).toBeVisible();
  await expect(page.getByLabel("Audit completeness")).toContainText(
    "2 observed / 2 expected",
  );
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

  await expectAccessible(page);
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth,
  );
  expect(overflow).toBe(false);
});

test("reviews and decides an immutable Approval", async ({ page }) => {
  await page.route("**/api/v1/session", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        actor_id: "approver-browser",
        tenant_id: "tenant-browser",
        roles: ["APPROVER"],
        permissions: [
          "incident:read",
          "evidence:read",
          "audit:read",
          "approval:decide",
        ],
      }),
    }),
  );
  let status = "PENDING";
  let version = 1;
  const summary = () => ({
    id: "approval-browser",
    incident_id: "incident-browser",
    proposal_id: "proposal-browser",
    proposal_version: 1,
    proposal_fingerprint: "a".repeat(64),
    policy_decision_fingerprint: "b".repeat(64),
    proposer_actor_id: "operator-browser",
    risk_level: "HIGH",
    status,
    version,
    requested_at: "2026-10-13T01:00:00Z",
    expires_at: "2026-10-13T02:00:00Z",
    decided_at: status === "PENDING" ? null : "2026-10-13T01:10:00Z",
    decided_by: status === "PENDING" ? null : "approver-browser",
    decision_reason: status === "PENDING" ? null : "Reviewed in browser.",
    expired: false,
    invalidated: false,
    separation_of_duties: {
      required: true,
      satisfied: true,
      code: "INDEPENDENT_APPROVER_PRESENT",
      detail: "The current approver is independent from the proposer.",
    },
    schema_version: "1.0.0",
  });
  await page.route("**/api/v1/approvals**", (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    if (request.method() === "POST") {
      status = "APPROVED";
      version = 2;
      return route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ approval: summary() }),
      });
    }
    if (pathname.endsWith("/approval-browser")) {
      return route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          approval: summary(),
          proposal: {
            schema_version: "1.0.0",
            proposal_id: "proposal-browser",
            proposal_version: 1,
            incident_id: "incident-browser",
            candidate_id: "candidate-browser",
            evidence_gate_input_fingerprint: "c".repeat(64),
            evidence_gate_decision_fingerprint: "d".repeat(64),
            action: "rollback_service",
            parameters: {
              service: "orders",
              introducing_deployment_evidence_id: "evidence-deployment",
            },
            prerequisites: { current_version_evidence_id: "evidence-current" },
            verification_conditions: {
              max_error_rate_basis_points: 100,
              max_p95_latency_ms: 500,
              stability_window_seconds: 300,
            },
            failure_handling: {
              route: "HUMAN_HANDOFF",
              max_rediagnosis_attempts: 0,
            },
            compensation_eligible: false,
            risk_assumptions: ["The current deployment is faulty."],
          },
          policy: {
            decision_id: "policy-browser",
            policy_version: "1.0.0",
            outcome: "APPROVAL_REQUIRED",
            risk_level: "HIGH",
            reasons: [
              {
                code: "APPROVAL_REQUIRED",
                detail: "Human approval is required.",
              },
            ],
            environment: "PRODUCTION",
            blast_radius: "SINGLE_SERVICE",
            maintenance_window: "ACTIVE",
            service: "orders",
            requester_roles: ["OPERATOR"],
            separation_of_duties_required: true,
            evaluated_at: "2026-10-13T01:00:00Z",
            approval_ttl_seconds: 3600,
            input_fingerprint: "e".repeat(64),
            decision_fingerprint: "f".repeat(64),
            schema_version: "1.0.0",
          },
          review_fingerprint: "1".repeat(64),
          replacement_proposal: null,
          proposal_diff: [],
          invalidation: null,
        }),
      });
    }
    return route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ items: [summary()], next_cursor: null }),
    });
  });

  await page.goto("/approvals");
  await expect(
    page.getByRole("link", { name: "approval-browser" }),
  ).toBeVisible();
  await expectAccessible(page);
  await Promise.all([
    page.waitForURL("**/approvals/approval-browser"),
    page.getByRole("link", { name: "approval-browser" }).click(),
  ]);
  await expect(
    page.getByRole("heading", { name: "Rollback orders" }),
  ).toBeVisible();
  await expect(page.getByText("Human approval is required.")).toBeVisible();
  await expectAccessible(page);
  await page.getByLabel("Decision reason").fill("Reviewed in browser.");
  await page.getByRole("button", { name: "Approve proposal" }).click();
  await expect(
    page.getByText("No decision is available for this record."),
  ).toBeVisible();
  await expect(
    page.locator(".approval-badges").getByText("APPROVED"),
  ).toBeVisible();
  await expectAccessible(page);
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth,
  );
  expect(overflow).toBe(false);
});
