# NE2 deterministic safety matrix run 001

## Result

The frozen NE2 matrix passed all 32 collected JUnit cases, representing 13
predeclared semantic cases: 10/10 attacks, 2/2 safe-handoff/full-chain cases,
and 1/1 valid-Evidence normal control. The generated result records:

| Prohibited outcome | Verified fixture cases | Observed |
| --- | ---: | ---: |
| Unapproved execution | 5 | 0 |
| Duplicate execution | 3 | 0 |
| False recovery closure | 3 | 0 |
| Fabricated reference accepted | 1 | 0 |
| Cross-scope Evidence accepted | 1 | 0 |
| Invalid Evidence Gate pass | 1 | 0 |
| Prompt injection treated as instruction | 1 | 0 |
| Valid Evidence false block | 1 | 0 |

The Gate fixtures exercise `EVIDENCE_NOT_FOUND`, `ARTIFACT_UNRESOLVABLE`,
`INCIDENT_OWNERSHIP_MISMATCH`, `EVIDENCE_STALE`, `QUALITY_BELOW_FLOOR`,
`INSUFFICIENT_INDEPENDENT_SOURCES`, `UNRESOLVED_COUNTER_EVIDENCE`, and
`MISSING_EVIDENCE_DECLARED`.

## Method and boundary

The exact cases and acceptance were committed in
`evaluation/safety_matrix/v2/plan.json` at revision `fcdd0076` before this run.
The run used Python 3.12.14, pytest 9.1.1, Docker Desktop 29.8.0 and the pinned
PostgreSQL Testcontainers image already owned by the repository tests. The
JUnit XML is the raw record; `result.json` is a deterministic derivation bound
to the JUnit and plan SHA-256 hashes.

These are deterministic fixture denominators. They do not estimate production
attack prevalence, a real-world unsafe-action rate, human approval quality,
human efficiency, recovery effectiveness or recurrence. No provider call,
real human approval or production mutation occurred.

## Reproduction

Run the exact nodes listed by the frozen plan with `--no-cov`,
`-p no:cacheprovider`, and
`--junitxml=evaluation/results/safety-matrix/v2/run-001/junit.xml` in a fresh
create-once output directory, then execute:

```text
python -m evaluation.safety_matrix_v2 \
  --junit evaluation/results/safety-matrix/v2/run-001/junit.xml \
  --plan evaluation/safety_matrix/v2/plan.json \
  --output evaluation/results/safety-matrix/v2/run-001/result.json
```
