# Real observation dataset v1

27 immutable inputs: 18 actual local fault captures (three per known fault family), three
actual normal captures, and six explicitly derived controls. Inputs total 1,875,881 bytes.
`index.json` contains opaque IDs and input hashes only. Evaluator labels and capture/cleanup
records are separately stored under `evaluation/real_protocol/v1/evaluator_only`; never pass
that directory to model context or retrieval. Runtime images must not mount either folder.

The real capture ran from revision `0bab8137958e01568014e9b65cd59250e29718a2` with frozen
protocol SHA-256 `0ffed77c73098898276fb48738ddb33dbd2339c39a267e4ffe3ce08036a3fc26`.
All 21 initial and final checkout checks returned 200; all 18 injected faults were cleaned.
No product recovery is credited. Of 420 evaluator-owned read combinations, 374 succeeded and
46 trace combinations were unavailable. All source failures remain in their snapshots.
Availability is a capture observation, not a production reliability rate.

Metric queries use their recorded 60-second lookback, which can include recent pre-window
activity; trace/log queries use recorded capture bounds. Normal means healthy checkout during
that capture, not absence of all preceding error history. Derived counter controls preserve
normal telemetry and change only an explicitly unverified operator hypothesis; missing-evidence
controls deliberately withhold sources. Neither derived control is a live fault measurement.

All 27 hashes/catalogs and three-per-stratum counts were verified before model evaluation;
a bounded credential-pattern scan found no API keys/private keys. Simulator identities and
telemetry are synthetic. The archive is redacted; model-context injection quarantine remains
active. Captures are fixed replay inputs, not production incidents or unseen fault families.

No diagnosis accuracy, model comparison, recovery success, human labor saving or MTTR result
is asserted by publishing this dataset. Provider runs and scoring remain outstanding.

Protocol binding uses canonical JSON SHA-256 for future comparisons, so Git/Windows newline
differences cannot change it. `protocol-binding.json` retains capture raw bytes, Git blob
and canonical hashes and verifies JSON equivalence. Raw capture metadata is unchanged.
