# Registered real-model evaluation protocol v1

This predeclares 27 observation instances per mode, including 18 faults and nine normal,
insufficient-evidence and counter-evidence controls. The three model modes require 81 total
instances. These are new instances of known fault families, not unseen-family generalization.
No captures or results are asserted by this plan.

The JSON plan is evaluator-only. A model may receive only its public cause taxonomy, never
the strata, expected outcomes, case mapping or scoring labels. Capture and replay adapters must
bind exact hashes and reject mismatched paired inputs. Runtime modules must not import this
folder. Collection/scoring validation and all 81 provider instances remain to be implemented
and run before this protocol can support outcome claims.
