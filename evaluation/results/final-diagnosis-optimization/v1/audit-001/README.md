# FC4f development audit 001

This is a label-free development audit, not a new confirmation result. Its frozen plan permits one
run and forbids access to FC4d inputs, labels, reports, candidates, or per-case errors.

The deterministic transport fixture reproduces the terminal validity defect: an initial invalid
diagnosis and its only repair both violate the schema, resulting in `INVALID_RESPONSE` after two
calls. The failed path consumes 200 input tokens, 200 output tokens, and a 300,000 nUSD rate-card
upper bound, but produces no valid terminal report.

The separate archived resource comparison pairs 27 previously published `structured-reliability`
development inputs. In ordinary non-replan cases, controlled graph versus single model changes
median/P95 latency by only +16/+31 ms, input tokens by 0/-3, model calls by 0/0, and tool calls by
0/0. Median/P95 rate-card upper bound changes by -15,300/-18,900 nUSD. This does not reproduce the
large confirmation-tail regression, so the next development optimization is restricted to the
terminal invalid-output path and an explicit bounded-replan fixture. Normal evidence context must
not be reduced based on the FC4d result.
