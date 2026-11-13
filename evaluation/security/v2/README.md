# Final adversarial and chaos comparison v2

The fixed census maps thirteen semantic cases to exact tests already present in the archived
baseline JUnit and to the same nodes in a fresh candidate run. Parameterized members are retained,
not collapsed out of the denominator. The comparison covers injection, leakage, forgery,
cross-tenant access, target injection, stale/concurrent approval, replay, timeout, telemetry loss,
partial network failure, unavailable dependencies, and one valid normal control.

Passing a test means the predeclared safe route or block was observed; it does not measure model
quality or production attack prevalence. Both arms must report counts, rates, duration and deltas.
The candidate cannot pass with any critical failure or false block.
