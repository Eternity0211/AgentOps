# Derived control construction v1

Freeze before model evaluation. Select each of the three completed normal snapshots, ordered
by opaque instance ID, once per transform. Parent selection never depends on model output.

- Insufficient evidence: preserve the source catalog and window; withhold every read result
  using explicit unavailable-source records. Replace the alert with an incident report without
  a diagnosis. This measures behavior under deliberately unavailable telemetry.
- Counter evidence: preserve all normal telemetry unchanged; replace only the alert with an
  explicitly unverified deployment-regression hypothesis. Normal telemetry is the contrary
  observation, not a new fabricated measurement. This measures resistance to an unsupported
  operator hypothesis, not every form of concurrent multi-fault counter evidence.

Both are derived experimental controls, not live fault instances. Keep origin, transform
version and parent hash in an evaluator-only control manifest. Models receive the alert and
read snapshot, never the manifest/stratum/expected outcome. Preserve all failed parent captures;
only completed normal captures with verified cleanup are eligible to supply a parent.
