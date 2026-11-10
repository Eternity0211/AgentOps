# Independent holdout v2

Captured at revision 8968131 under the frozen v2 capture plan. The 21 actual captures
cover six known fault families and normal, each with 4, 8 and 12 checkout probes.
All capture and cleanup checks passed. Normal probes returned HTTP 200 in 24/24 cases.
All 420 requested source combinations returned successfully. A returned source can
contain empty or nondiscriminating telemetry. Six derived controls use the frozen v1
transforms, giving 27 total inputs. Cleanup earns no recovery credit.

The runtime directory contains inputs and their index. Capture labels and control
parent bindings are evaluator-only. Freeze precedes model evaluation.
[Capture protocol](../../real_protocol/v2/capture-plan.json)
