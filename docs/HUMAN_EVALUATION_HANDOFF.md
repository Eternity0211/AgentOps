# Human evaluation handoff

The automated experiments do not approve or execute recovery. Local live Evidence/Artifact
records are experiment records, not queued production Approval records in the console.
A real recovery trial first needs an admitted proposal, deterministic policy record and
persisted approval request. Do not treat the report label HUMAN_REVIEW_REQUIRED as an approval.

## Paired human trial

Use the same scenario variants and resource budgets for manual and assisted runs. Randomize
order; avoid showing the same participant the same answer twice. Keep evaluation labels
hidden until each attempt is complete. Declare diagnosis correctness criteria and timeouts
before running. Include failed/abandoned attempts rather than counting only successes.

Record UTC start/end, first useful evidence time, first correct diagnosis time, active human
minutes, query count, page switches, interventions, postmortem editing minutes and final
correctness. Record approval waiting separately from system processing time.

| Trial ID | Mode | Opaque scenario ID | Start UTC | Correct diagnosis UTC | Active minutes | Queries | Switches | Interventions | Correct? |
| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| | manual / assisted | | | | | | | | |

## Recovery trial

Only HTTP-500 and the deployment-linked memory-leak scenarios may be rollback eligible.
Verify stable predecessor evidence, exact proposal/policy fingerprints, independent approver
identity and expiry before authorizing. Never bypass an Evidence Gate failure to collect a
recovery number. Failed verification must re-diagnose within budget or hand off, never redeploy
the known faulty version. Observe the full configured five-signal stability window.

Record Approval ID and timing, ActionExecution ID, idempotency key hash, deployed-version
observations, verifier decision, final incident route and declared recurrence follow-up window.
Evaluator fault cleanup is not a recovery action and cannot earn recovery credit.

## Cost and outcome claims

Reconcile provider billing if actual fees are needed. The automated report contains only
versioned rate-card bounds, not an invoice. Use measured infrastructure billing or declared
cost allocation rather than converting memory snapshots into guessed costs. Publish paired
raw distributions and sample denominators before claiming MTTR or labor reduction.
