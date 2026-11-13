# AgentOps final comparative evaluation

Generated from immutable artifacts under `final-comparative-report/1.0.0` on 2026-11-14.
No externally blocked metric is replaced by simulation or inference.

## Outcome

Structured-output acceptance, the eight-pair durability safety gate and the 13-case security census passed. The designed memory set changed 9/10→10/10, but the ten-pair sample does not prove superiority. PostgreSQL throughput improved through four local workers and regressed at eight; the current supported local cap is four.
Human outcomes, approved recovery benefit and actual cost remain externally blocked.

## Metric coverage

| Work | Metric | Status | Note |
| --- | --- | --- | --- |
| FC0 | `unmapped_legacy_items` | `MEASURED` | Measured or deterministically verified in the cited frozen artifact. |
| FC0 | `duplicate_work_ids` | `MEASURED` | Measured or deterministically verified in the cited frozen artifact. |
| FC0 | `schema_valid` | `MEASURED` | Measured or deterministically verified in the cited frozen artifact. |
| FC1 | `absolute_delta` | `MEASURED` | Measured or deterministically verified in the cited frozen artifact. |
| FC1 | `relative_delta` | `MEASURED` | Measured or deterministically verified in the cited frozen artifact. |
| FC1 | `confidence_interval` | `MEASURED` | Measured or deterministically verified in the cited frozen artifact. |
| FC1 | `paired_test` | `MEASURED` | Measured or deterministically verified in the cited frozen artifact. |
| FC1 | `arithmetic_reproducibility` | `MEASURED` | Measured or deterministically verified in the cited frozen artifact. |
| FC2 | `invalid_response_rate` | `MEASURED` | Measured or deterministically verified in the cited frozen artifact. |
| FC2 | `safe_control_rate` | `MEASURED` | Measured or deterministically verified in the cited frozen artifact. |
| FC2 | `evidence_integrity_rate` | `MEASURED` | Measured or deterministically verified in the cited frozen artifact. |
| FC2 | `calls` | `MEASURED` | Measured or deterministically verified in the cited frozen artifact. |
| FC2 | `tokens` | `NO_PROVEN_IMPROVEMENT` | Observed deltas do not establish statistical superiority. |
| FC2 | `latency` | `NO_PROVEN_IMPROVEMENT` | Observed deltas do not establish statistical superiority. |
| FC2 | `cost` | `NO_PROVEN_IMPROVEMENT` | Observed deltas do not establish statistical superiority. |
| FC3 | `memory_top1` | `NO_PROVEN_IMPROVEMENT` | Observed deltas do not establish statistical superiority. |
| FC3 | `normal_safe_handoff` | `MEASURED` | Measured or deterministically verified in the cited frozen artifact. |
| FC3 | `fabricated_reference_rate` | `MEASURED` | Measured or deterministically verified in the cited frozen artifact. |
| FC3 | `context_bytes` | `MEASURED` | Measured or deterministically verified in the cited frozen artifact. |
| FC3 | `latency` | `NO_PROVEN_IMPROVEMENT` | Observed deltas do not establish statistical superiority. |
| FC3 | `tokens` | `NO_PROVEN_IMPROVEMENT` | Observed deltas do not establish statistical superiority. |
| FC4 | `top1` | `BLOCKED_EXTERNAL_DATA` | Required authorized external observations do not exist. |
| FC4 | `top3` | `BLOCKED_EXTERNAL_DATA` | Required authorized external observations do not exist. |
| FC4 | `safe_controls` | `BLOCKED_EXTERNAL_DATA` | Required authorized external observations do not exist. |
| FC4 | `valid_report_rate` | `BLOCKED_EXTERNAL_DATA` | Required authorized external observations do not exist. |
| FC4 | `unsupported_conclusion_rate` | `BLOCKED_EXTERNAL_DATA` | Required authorized external observations do not exist. |
| FC4 | `gate_precision` | `BLOCKED_EXTERNAL_DATA` | Required authorized external observations do not exist. |
| FC4 | `gate_recall` | `BLOCKED_EXTERNAL_DATA` | Required authorized external observations do not exist. |
| FC4 | `latency` | `BLOCKED_EXTERNAL_DATA` | Required authorized external observations do not exist. |
| FC4 | `tokens` | `BLOCKED_EXTERNAL_DATA` | Required authorized external observations do not exist. |
| FC4 | `cost` | `BLOCKED_EXTERNAL_DATA` | Required authorized external observations do not exist. |
| FC5 | `retrieval_coverage` | `BLOCKED_EXTERNAL_DATA` | Required authorized external observations do not exist. |
| FC5 | `retrieval_precision` | `BLOCKED_EXTERNAL_DATA` | Required authorized external observations do not exist. |
| FC5 | `top1` | `BLOCKED_EXTERNAL_DATA` | Required authorized external observations do not exist. |
| FC5 | `top3` | `BLOCKED_EXTERNAL_DATA` | Required authorized external observations do not exist. |
| FC5 | `safe_controls` | `BLOCKED_EXTERNAL_DATA` | Required authorized external observations do not exist. |
| FC5 | `failures` | `BLOCKED_EXTERNAL_DATA` | Required authorized external observations do not exist. |
| FC5 | `latency` | `BLOCKED_EXTERNAL_DATA` | Required authorized external observations do not exist. |
| FC5 | `tokens` | `BLOCKED_EXTERNAL_DATA` | Required authorized external observations do not exist. |
| FC5 | `cost` | `BLOCKED_EXTERNAL_DATA` | Required authorized external observations do not exist. |
| FC6 | `time_to_correct_diagnosis` | `BLOCKED_EXTERNAL_DATA` | Required authorized external observations do not exist. |
| FC6 | `active_labor` | `BLOCKED_EXTERNAL_DATA` | Required authorized external observations do not exist. |
| FC6 | `approval_time` | `BLOCKED_EXTERNAL_DATA` | Required authorized external observations do not exist. |
| FC6 | `mttr` | `BLOCKED_EXTERNAL_DATA` | Required authorized external observations do not exist. |
| FC6 | `correct_action_rate` | `BLOCKED_EXTERNAL_DATA` | Required authorized external observations do not exist. |
| FC6 | `unsafe_action_attempts` | `BLOCKED_EXTERNAL_DATA` | Required authorized external observations do not exist. |
| FC6 | `workload` | `BLOCKED_EXTERNAL_DATA` | Required authorized external observations do not exist. |
| FC6 | `recurrence` | `BLOCKED_EXTERNAL_DATA` | Required authorized external observations do not exist. |
| FC7 | `proposal_correctness` | `BLOCKED_EXTERNAL_DATA` | Required authorized external observations do not exist. |
| FC7 | `approval_outcomes` | `BLOCKED_EXTERNAL_DATA` | Required authorized external observations do not exist. |
| FC7 | `execution_success` | `BLOCKED_EXTERNAL_DATA` | Required authorized external observations do not exist. |
| FC7 | `duplicate_execution` | `BLOCKED_EXTERNAL_DATA` | Required authorized external observations do not exist. |
| FC7 | `unapproved_execution` | `BLOCKED_EXTERNAL_DATA` | Required authorized external observations do not exist. |
| FC7 | `verifier_pass` | `BLOCKED_EXTERNAL_DATA` | Required authorized external observations do not exist. |
| FC7 | `time_to_stable_recovery` | `BLOCKED_EXTERNAL_DATA` | Required authorized external observations do not exist. |
| FC7 | `mttr` | `BLOCKED_EXTERNAL_DATA` | Required authorized external observations do not exist. |
| FC7 | `active_labor` | `BLOCKED_EXTERNAL_DATA` | Required authorized external observations do not exist. |
| FC7 | `recurrence` | `BLOCKED_EXTERNAL_DATA` | Required authorized external observations do not exist. |
| FC8 | `cost_per_attempt` | `BLOCKED_EXTERNAL_DATA` | Required authorized external observations do not exist. |
| FC8 | `cost_per_valid_diagnosis` | `BLOCKED_EXTERNAL_DATA` | Required authorized external observations do not exist. |
| FC8 | `cost_per_correct_diagnosis` | `BLOCKED_EXTERNAL_DATA` | Required authorized external observations do not exist. |
| FC8 | `cost_per_safe_recovery` | `BLOCKED_EXTERNAL_DATA` | Required authorized external observations do not exist. |
| FC8 | `invoice_match_rate` | `BLOCKED_EXTERNAL_DATA` | Required authorized external observations do not exist. |
| FC9 | `completion_rate` | `MEASURED` | Measured or deterministically verified in the cited frozen artifact. |
| FC9 | `duplicate_effects` | `MEASURED` | Measured or deterministically verified in the cited frozen artifact. |
| FC9 | `lost_evidence` | `MEASURED` | Measured or deterministically verified in the cited frozen artifact. |
| FC9 | `resume_latency` | `MEASURED` | Measured or deterministically verified in the cited frozen artifact. |
| FC9 | `total_latency` | `NO_PROVEN_IMPROVEMENT` | The paired 95% delta interval crosses zero. |
| FC9 | `calls` | `MEASURED` | Measured or deterministically verified in the cited frozen artifact. |
| FC9 | `tokens` | `MEASURED` | Measured or deterministically verified in the cited frozen artifact. |
| FC9 | `cost` | `MEASURED` | Measured or deterministically verified in the cited frozen artifact. |
| FC9 | `terminal_route` | `MEASURED` | Measured or deterministically verified in the cited frozen artifact. |
| FC10 | `throughput` | `MEASURED` | Measured or deterministically verified in the cited frozen artifact. |
| FC10 | `queue_wait` | `MEASURED` | Measured or deterministically verified in the cited frozen artifact. |
| FC10 | `workflow_latency` | `MEASURED` | Measured or deterministically verified in the cited frozen artifact. |
| FC10 | `error_rate` | `MEASURED` | Measured or deterministically verified in the cited frozen artifact. |
| FC10 | `lease_contention` | `MEASURED` | Measured or deterministically verified in the cited frozen artifact. |
| FC10 | `cpu` | `MEASURED` | Measured or deterministically verified in the cited frozen artifact. |
| FC10 | `process_heap` | `MEASURED` | Measured or deterministically verified in the cited frozen artifact. |
| FC10 | `database_load` | `MEASURED` | PostgreSQL-container CPU, memory, block I/O and database counters were measured. |
| FC11 | `attack_block_rate` | `MEASURED` | Measured or deterministically verified in the cited frozen artifact. |
| FC11 | `safe_handoff_rate` | `MEASURED` | Measured or deterministically verified in the cited frozen artifact. |
| FC11 | `false_block_rate` | `MEASURED` | Measured or deterministically verified in the cited frozen artifact. |
| FC11 | `route_correctness` | `MEASURED` | Measured or deterministically verified in the cited frozen artifact. |
| FC11 | `latency` | `MEASURED` | Measured or deterministically verified in the cited frozen artifact. |
| FC11 | `cost` | `MEASURED` | Measured or deterministically verified in the cited frozen artifact. |
| FC11 | `critical_failures` | `MEASURED` | Measured or deterministically verified in the cited frozen artifact. |
| FC12 | `requirement_satisfied` | `NOT_REQUIRED` | No named current-version requirement justifies the optional capability. |
| FC12 | `safety_regression` | `NOT_REQUIRED` | No named current-version requirement justifies the optional capability. |
| FC12 | `latency_overhead` | `NOT_REQUIRED` | No named current-version requirement justifies the optional capability. |
| FC12 | `cost_overhead` | `NOT_REQUIRED` | No named current-version requirement justifies the optional capability. |
| FC12 | `operational_complexity` | `NOT_REQUIRED` | No named current-version requirement justifies the optional capability. |
| FC13 | `metric_coverage` | `MEASURED` | Measured or deterministically verified in the cited frozen artifact. |
| FC13 | `arithmetic_reproducibility` | `MEASURED` | Measured or deterministically verified in the cited frozen artifact. |
| FC13 | `artifact_integrity` | `MEASURED` | Measured or deterministically verified in the cited frozen artifact. |
| FC13 | `legacy_open_items` | `MEASURED` | Measured or deterministically verified in the cited frozen artifact. |
| FC13 | `credential_findings` | `MEASURED` | Measured or deterministically verified in the cited frozen artifact. |

## Baseline/candidate comparisons

| Work | Metric | Statistic | Baseline | Candidate | Absolute delta | Relative delta | 95% delta interval | Status |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- |
| FC2 | `valid-outcome` (rate) | rate | 0.950617 | 0.962963 | 0.0123457 | 0.012987 | [-0.037037, 0.0617284] | `NO_PROVEN_IMPROVEMENT` |
| FC2 | `safe-control` (rate) | rate | 1 | 1 | 0 | 0 | [0, 0] | `NO_PROVEN_IMPROVEMENT` |
| FC2 | `evidence-integrity` (rate) | rate | 1 | 1 | 0 | 0 | [0, 0] | `NO_PROVEN_IMPROVEMENT` |
| FC2 | `duration-ms` (duration-ms) | median | 5234 | 5297 | 63 | 0.0120367 | [-438, 469] | `NO_PROVEN_IMPROVEMENT` |
| FC2 | `duration-ms` (duration-ms) | p95 | 12047 | 12921 | 874 | 0.0725492 | [78, 2062] | `NO_PROVEN_IMPROVEMENT` |
| FC2 | `input-tokens` (input-tokens) | median | 10179 | 10650 | 471 | 0.0462717 | [-498, 1183] | `NO_PROVEN_IMPROVEMENT` |
| FC2 | `input-tokens` (input-tokens) | p95 | 26406 | 29975 | 3569 | 0.135159 | [545, 5282] | `NO_PROVEN_IMPROVEMENT` |
| FC2 | `output-tokens` (output-tokens) | median | 675 | 694 | 19 | 0.0281481 | [-37, 88] | `NO_PROVEN_IMPROVEMENT` |
| FC2 | `output-tokens` (output-tokens) | p95 | 1557 | 1544 | -13 | -0.00834939 | [-142, 116] | `NO_PROVEN_IMPROVEMENT` |
| FC2 | `cost-upper-bound` (cost-upper-bound) | median | 3.8097e+06 | 3.9207e+06 | 111000 | 0.0291362 | [-135300, 419400] | `NO_PROVEN_IMPROVEMENT` |
| FC2 | `cost-upper-bound` (cost-upper-bound) | p95 | 9.8094e+06 | 1.07361e+07 | 926700 | 0.0944706 | [138600, 1.7913e+06] | `NO_PROVEN_IMPROVEMENT` |
| FC2 | `initial-schema-protocol-invalids` (outcomes) | value | 9 | 4 | -5 | -0.555556 | N/A | `MEASURED` |
| FC3 | `correct-diagnosis-rate` (rate) | value | 0.9 | 1 | 0.1 | 0.111111 | N/A | `NO_PROVEN_IMPROVEMENT` |
| FC3 | `sustained-retention-detection-rate` (rate) | value | 0.5 | 1 | 0.5 | 1 | N/A | `NO_PROVEN_IMPROVEMENT` |
| FC3 | `safe-negative-rate` (rate) | value | 1 | 1 | 0 | 0 | N/A | `MEASURED` |
| FC3 | `failure-count` (outcomes) | value | 0 | 0 | 0 | N/A | N/A | `MEASURED` |
| FC3 | `duration` (ms) | value | 20549 | 20689 | 140 | 0.00681298 | N/A | `NO_PROVEN_IMPROVEMENT` |
| FC3 | `input-tokens` (tokens) | value | 26865 | 25198 | -1667 | -0.062051 | N/A | `NO_PROVEN_IMPROVEMENT` |
| FC3 | `output-tokens` (tokens) | value | 2186 | 2212 | 26 | 0.0118939 | N/A | `NO_PROVEN_IMPROVEMENT` |
| FC3 | `cost-upper-bound` (nUSD) | value | 10682700 | 10213800 | -468900 | -0.0438934 | N/A | `NO_PROVEN_IMPROVEMENT` |
| FC9 | `terminal-route-match-rate` (rate) | value | 1 | 1 | 0 | 0 | N/A | `MEASURED` |
| FC9 | `duplicate_external_effects` (events) | value | 0 | 0 | 0 | N/A | N/A | `MEASURED` |
| FC9 | `ambiguous_result_redispatches` (events) | value | 0 | 0 | 0 | N/A | N/A | `MEASURED` |
| FC9 | `lost_evidence_records` (events) | value | 0 | 0 | 0 | N/A | N/A | `MEASURED` |
| FC9 | `total-latency` (ms) | arm-median | 86 | 108.5 | 22.5 | 0.261628 | N/A | `NO_PROVEN_IMPROVEMENT` |
| FC9 | `paired-total-latency-delta` (ms) | median-paired-delta | 0 | 13 | 13 | N/A | [-32, 44] | `NO_PROVEN_IMPROVEMENT` |
| FC9 | `resume-latency` (ms) | median-paired-delta | 0 | 67 | 67 | N/A | [25, 84] | `MEASURED` |
| FC9 | `model_calls` (calls) | value | 16 | 14 | -2 | -0.125 | N/A | `MEASURED` |
| FC9 | `tool_calls` (calls) | value | 16 | 15 | -1 | -0.0625 | N/A | `MEASURED` |
| FC9 | `input_tokens` (tokens) | value | 1760 | 1520 | -240 | -0.136364 | N/A | `MEASURED` |
| FC9 | `output_tokens` (tokens) | value | 880 | 760 | -120 | -0.136364 | N/A | `MEASURED` |
| FC9 | `rate_card_upper_bound_nusd` (nUSD) | value | 14080 | 12160 | -1920 | -0.136364 | N/A | `MEASURED` |
| FC10 | `throughput:1-to-2-workers` (jobs/s) | median | 17.227 | 28.946 | 11.719 | 0.680269 | N/A | `MEASURED` |
| FC10 | `queue-wait-p95:1-to-2-workers` (ms) | median | 3297 | 1858 | -1439 | -0.436457 | N/A | `MEASURED` |
| FC10 | `workflow-latency-p95:1-to-2-workers` (ms) | median | 3318 | 1882 | -1436 | -0.432791 | N/A | `MEASURED` |
| FC10 | `error-count:1-to-2-workers` (events) | median | 0 | 0 | 0 | N/A | N/A | `MEASURED` |
| FC10 | `duplicate-job-ownership:1-to-2-workers` (events) | median | 0 | 0 | 0 | N/A | N/A | `MEASURED` |
| FC10 | `process-cpu:1-to-2-workers` (ms) | median | 2046 | 1937 | -109 | -0.0532747 | N/A | `MEASURED` |
| FC10 | `python-heap-peak:1-to-2-workers` (bytes) | median | 222139 | 247001 | 24862 | 0.111921 | N/A | `MEASURED` |
| FC10 | `database-statement-count:1-to-2-workers` (statements) | median | 450 | 453 | 3 | 0.00666667 | N/A | `MEASURED` |
| FC10 | `throughput-paired-delta:1-to-2-workers` (jobs/s) | median-paired-delta | 0 | 12.093 | 12.093 | N/A | [11.08, 13.114] | `MEASURED` |
| FC10 | `lease-contentions:1-to-2-workers` (events) | 11-repetition-total | 0 | 1 | 1 | N/A | N/A | `MEASURED` |
| FC10 | `throughput:1-to-4-workers` (jobs/s) | median | 17.227 | 28.959 | 11.732 | 0.681024 | N/A | `MEASURED` |
| FC10 | `queue-wait-p95:1-to-4-workers` (ms) | median | 3297 | 1866 | -1431 | -0.434031 | N/A | `MEASURED` |
| FC10 | `workflow-latency-p95:1-to-4-workers` (ms) | median | 3318 | 1912 | -1406 | -0.423749 | N/A | `MEASURED` |
| FC10 | `error-count:1-to-4-workers` (events) | median | 0 | 0 | 0 | N/A | N/A | `MEASURED` |
| FC10 | `duplicate-job-ownership:1-to-4-workers` (events) | median | 0 | 0 | 0 | N/A | N/A | `MEASURED` |
| FC10 | `process-cpu:1-to-4-workers` (ms) | median | 2046 | 2015 | -31 | -0.0151515 | N/A | `MEASURED` |
| FC10 | `python-heap-peak:1-to-4-workers` (bytes) | median | 222139 | 356255 | 134116 | 0.603748 | N/A | `MEASURED` |
| FC10 | `database-statement-count:1-to-4-workers` (statements) | median | 450 | 459 | 9 | 0.02 | N/A | `MEASURED` |
| FC10 | `throughput-paired-delta:1-to-4-workers` (jobs/s) | median-paired-delta | 0 | 11.807 | 11.807 | N/A | [11.022, 13.018] | `MEASURED` |
| FC10 | `lease-contentions:1-to-4-workers` (events) | 11-repetition-total | 0 | 6 | 6 | N/A | N/A | `MEASURED` |
| FC10 | `throughput:1-to-8-workers` (jobs/s) | median | 17.227 | 21.011 | 3.784 | 0.219655 | N/A | `MEASURED` |
| FC10 | `queue-wait-p95:1-to-8-workers` (ms) | median | 3297 | 2608 | -689 | -0.208978 | N/A | `MEASURED` |
| FC10 | `workflow-latency-p95:1-to-8-workers` (ms) | median | 3318 | 2692 | -626 | -0.188668 | N/A | `MEASURED` |
| FC10 | `error-count:1-to-8-workers` (events) | median | 0 | 0 | 0 | N/A | N/A | `MEASURED` |
| FC10 | `duplicate-job-ownership:1-to-8-workers` (events) | median | 0 | 0 | 0 | N/A | N/A | `MEASURED` |
| FC10 | `process-cpu:1-to-8-workers` (ms) | median | 2046 | 2765 | 719 | 0.351417 | N/A | `MEASURED` |
| FC10 | `python-heap-peak:1-to-8-workers` (bytes) | median | 222139 | 1011183 | 789044 | 3.55203 | N/A | `MEASURED` |
| FC10 | `database-statement-count:1-to-8-workers` (statements) | median | 450 | 483 | 33 | 0.0733333 | N/A | `MEASURED` |
| FC10 | `throughput-paired-delta:1-to-8-workers` (jobs/s) | median-paired-delta | 0 | 5.175 | 5.175 | N/A | [2.103, 7.034] | `MEASURED` |
| FC10 | `lease-contentions:1-to-8-workers` (events) | 11-repetition-total | 0 | 43 | 43 | N/A | N/A | `MEASURED` |
| FC10 | `postgres_container_cpu_usage_usec:1-to-2-workers` (usec) | arm-median | 262731 | 266184 | 3453 | 0.0131427 | N/A | `MEASURED` |
| FC10 | `postgres_container_cpu_usage_usec-paired-delta:1-to-2-workers` (usec) | median-paired-delta | 0 | 3453 | 3453 | N/A | [-16575, 35924] | `MEASURED` |
| FC10 | `postgres_container_memory_peak_observed_bytes:1-to-2-workers` (bytes) | arm-median | 1.22409e+08 | 1.24019e+08 | 1.60973e+06 | 0.0131504 | N/A | `MEASURED` |
| FC10 | `postgres_container_memory_peak_observed_bytes-paired-delta:1-to-2-workers` (bytes) | median-paired-delta | 0 | 516096 | 516096 | N/A | [-671744, 708608] | `MEASURED` |
| FC10 | `postgres_container_io_read_bytes:1-to-2-workers` (bytes) | arm-median | 0 | 0 | 0 | N/A | N/A | `MEASURED` |
| FC10 | `postgres_container_io_read_bytes-paired-delta:1-to-2-workers` (bytes) | median-paired-delta | 0 | 0 | 0 | N/A | [0, 0] | `MEASURED` |
| FC10 | `postgres_container_io_write_bytes:1-to-2-workers` (bytes) | arm-median | 1.21242e+06 | 1.20422e+06 | -8192 | -0.00675676 | N/A | `MEASURED` |
| FC10 | `postgres_container_io_write_bytes-paired-delta:1-to-2-workers` (bytes) | median-paired-delta | 0 | 0 | 0 | N/A | [-196608, 385024] | `MEASURED` |
| FC10 | `postgres_xact_commit:1-to-2-workers` (counter-delta) | arm-median | 133 | 114 | -19 | -0.142857 | N/A | `MEASURED` |
| FC10 | `postgres_xact_commit-paired-delta:1-to-2-workers` (counter-delta) | median-paired-delta | 0 | -17 | -17 | N/A | [-31, -3] | `MEASURED` |
| FC10 | `postgres_xact_rollback:1-to-2-workers` (counter-delta) | arm-median | 3 | 3 | 0 | 0 | N/A | `MEASURED` |
| FC10 | `postgres_xact_rollback-paired-delta:1-to-2-workers` (counter-delta) | median-paired-delta | 0 | 0 | 0 | N/A | [0, 1] | `MEASURED` |
| FC10 | `postgres_blks_read:1-to-2-workers` (counter-delta) | arm-median | 0 | 0 | 0 | N/A | N/A | `MEASURED` |
| FC10 | `postgres_blks_read-paired-delta:1-to-2-workers` (counter-delta) | median-paired-delta | 0 | 0 | 0 | N/A | [0, 0] | `MEASURED` |
| FC10 | `postgres_blks_hit:1-to-2-workers` (counter-delta) | arm-median | 8849 | 6785 | -2064 | -0.233247 | N/A | `MEASURED` |
| FC10 | `postgres_blks_hit-paired-delta:1-to-2-workers` (counter-delta) | median-paired-delta | 0 | -706 | -706 | N/A | [-2911, -87] | `MEASURED` |
| FC10 | `postgres_temp_bytes:1-to-2-workers` (counter-delta) | arm-median | 0 | 0 | 0 | N/A | N/A | `MEASURED` |
| FC10 | `postgres_temp_bytes-paired-delta:1-to-2-workers` (counter-delta) | median-paired-delta | 0 | 0 | 0 | N/A | [0, 0] | `MEASURED` |
| FC10 | `postgres_deadlocks:1-to-2-workers` (counter-delta) | arm-median | 0 | 0 | 0 | N/A | N/A | `MEASURED` |
| FC10 | `postgres_deadlocks-paired-delta:1-to-2-workers` (counter-delta) | median-paired-delta | 0 | 0 | 0 | N/A | [0, 0] | `MEASURED` |
| FC10 | `postgres_tup_returned:1-to-2-workers` (counter-delta) | arm-median | 31786 | 20541 | -11245 | -0.353772 | N/A | `MEASURED` |
| FC10 | `postgres_tup_returned-paired-delta:1-to-2-workers` (counter-delta) | median-paired-delta | 0 | -3406 | -3406 | N/A | [-6769, 2962] | `MEASURED` |
| FC10 | `postgres_tup_fetched:1-to-2-workers` (counter-delta) | arm-median | 2617 | 2422 | -195 | -0.0745128 | N/A | `MEASURED` |
| FC10 | `postgres_tup_fetched-paired-delta:1-to-2-workers` (counter-delta) | median-paired-delta | 0 | -322 | -322 | N/A | [-1138, -104] | `MEASURED` |
| FC10 | `postgres_tup_inserted:1-to-2-workers` (counter-delta) | arm-median | 65 | 65 | 0 | 0 | N/A | `MEASURED` |
| FC10 | `postgres_tup_inserted-paired-delta:1-to-2-workers` (counter-delta) | median-paired-delta | 0 | 0 | 0 | N/A | [0, 0] | `MEASURED` |
| FC10 | `postgres_tup_updated:1-to-2-workers` (counter-delta) | arm-median | 128 | 111 | -17 | -0.132812 | N/A | `MEASURED` |
| FC10 | `postgres_tup_updated-paired-delta:1-to-2-workers` (counter-delta) | median-paired-delta | 0 | -18 | -18 | N/A | [-32, 2] | `MEASURED` |
| FC10 | `postgres_tup_deleted:1-to-2-workers` (counter-delta) | arm-median | 0 | 0 | 0 | N/A | N/A | `MEASURED` |
| FC10 | `postgres_tup_deleted-paired-delta:1-to-2-workers` (counter-delta) | median-paired-delta | 0 | 0 | 0 | N/A | [0, 0] | `MEASURED` |
| FC10 | `postgres_container_cpu_usage_usec:1-to-4-workers` (usec) | arm-median | 262731 | 263157 | 426 | 0.00162143 | N/A | `MEASURED` |
| FC10 | `postgres_container_cpu_usage_usec-paired-delta:1-to-4-workers` (usec) | median-paired-delta | 0 | 25113 | 25113 | N/A | [-21493, 46754] | `MEASURED` |
| FC10 | `postgres_container_memory_peak_observed_bytes:1-to-4-workers` (bytes) | arm-median | 1.22409e+08 | 1.23187e+08 | 778240 | 0.0063577 | N/A | `MEASURED` |
| FC10 | `postgres_container_memory_peak_observed_bytes-paired-delta:1-to-4-workers` (bytes) | median-paired-delta | 0 | 778240 | 778240 | N/A | [-389120, 2.68698e+06] | `MEASURED` |
| FC10 | `postgres_container_io_read_bytes:1-to-4-workers` (bytes) | arm-median | 0 | 0 | 0 | N/A | N/A | `MEASURED` |
| FC10 | `postgres_container_io_read_bytes-paired-delta:1-to-4-workers` (bytes) | median-paired-delta | 0 | 0 | 0 | N/A | [0, 0] | `MEASURED` |
| FC10 | `postgres_container_io_write_bytes:1-to-4-workers` (bytes) | arm-median | 1.21242e+06 | 1.20422e+06 | -8192 | -0.00675676 | N/A | `MEASURED` |
| FC10 | `postgres_container_io_write_bytes-paired-delta:1-to-4-workers` (bytes) | median-paired-delta | 0 | 0 | 0 | N/A | [-24576, 303104] | `MEASURED` |
| FC10 | `postgres_xact_commit:1-to-4-workers` (counter-delta) | arm-median | 133 | 125 | -8 | -0.0601504 | N/A | `MEASURED` |
| FC10 | `postgres_xact_commit-paired-delta:1-to-4-workers` (counter-delta) | median-paired-delta | 0 | -5 | -5 | N/A | [-22, 13] | `MEASURED` |
| FC10 | `postgres_xact_rollback:1-to-4-workers` (counter-delta) | arm-median | 3 | 3 | 0 | 0 | N/A | `MEASURED` |
| FC10 | `postgres_xact_rollback-paired-delta:1-to-4-workers` (counter-delta) | median-paired-delta | 0 | 0 | 0 | N/A | [0, 1] | `MEASURED` |
| FC10 | `postgres_blks_read:1-to-4-workers` (counter-delta) | arm-median | 0 | 0 | 0 | N/A | N/A | `MEASURED` |
| FC10 | `postgres_blks_read-paired-delta:1-to-4-workers` (counter-delta) | median-paired-delta | 0 | 0 | 0 | N/A | [0, 0] | `MEASURED` |
| FC10 | `postgres_blks_hit:1-to-4-workers` (counter-delta) | arm-median | 8849 | 8492 | -357 | -0.0403435 | N/A | `MEASURED` |
| FC10 | `postgres_blks_hit-paired-delta:1-to-4-workers` (counter-delta) | median-paired-delta | 0 | -906 | -906 | N/A | [-2494, 1728] | `MEASURED` |
| FC10 | `postgres_temp_bytes:1-to-4-workers` (counter-delta) | arm-median | 0 | 0 | 0 | N/A | N/A | `MEASURED` |
| FC10 | `postgres_temp_bytes-paired-delta:1-to-4-workers` (counter-delta) | median-paired-delta | 0 | 0 | 0 | N/A | [0, 0] | `MEASURED` |
| FC10 | `postgres_deadlocks:1-to-4-workers` (counter-delta) | arm-median | 0 | 0 | 0 | N/A | N/A | `MEASURED` |
| FC10 | `postgres_deadlocks-paired-delta:1-to-4-workers` (counter-delta) | median-paired-delta | 0 | 0 | 0 | N/A | [0, 0] | `MEASURED` |
| FC10 | `postgres_tup_returned:1-to-4-workers` (counter-delta) | arm-median | 31786 | 31285 | -501 | -0.0157617 | N/A | `MEASURED` |
| FC10 | `postgres_tup_returned-paired-delta:1-to-4-workers` (counter-delta) | median-paired-delta | 0 | -501 | -501 | N/A | [-11789, 9159] | `MEASURED` |
| FC10 | `postgres_tup_fetched:1-to-4-workers` (counter-delta) | arm-median | 2617 | 2503 | -114 | -0.0435613 | N/A | `MEASURED` |
| FC10 | `postgres_tup_fetched-paired-delta:1-to-4-workers` (counter-delta) | median-paired-delta | 0 | -153 | -153 | N/A | [-1325, 369] | `MEASURED` |
| FC10 | `postgres_tup_inserted:1-to-4-workers` (counter-delta) | arm-median | 65 | 65 | 0 | 0 | N/A | `MEASURED` |
| FC10 | `postgres_tup_inserted-paired-delta:1-to-4-workers` (counter-delta) | median-paired-delta | 0 | 0 | 0 | N/A | [0, 0] | `MEASURED` |
| FC10 | `postgres_tup_updated:1-to-4-workers` (counter-delta) | arm-median | 128 | 123 | -5 | -0.0390625 | N/A | `MEASURED` |
| FC10 | `postgres_tup_updated-paired-delta:1-to-4-workers` (counter-delta) | median-paired-delta | 0 | 0 | 0 | N/A | [-19, 12] | `MEASURED` |
| FC10 | `postgres_tup_deleted:1-to-4-workers` (counter-delta) | arm-median | 0 | 0 | 0 | N/A | N/A | `MEASURED` |
| FC10 | `postgres_tup_deleted-paired-delta:1-to-4-workers` (counter-delta) | median-paired-delta | 0 | 0 | 0 | N/A | [0, 0] | `MEASURED` |
| FC10 | `postgres_container_cpu_usage_usec:1-to-8-workers` (usec) | arm-median | 262731 | 365323 | 102592 | 0.390483 | N/A | `MEASURED` |
| FC10 | `postgres_container_cpu_usage_usec-paired-delta:1-to-8-workers` (usec) | median-paired-delta | 0 | 96489 | 96489 | N/A | [56211, 164862] | `MEASURED` |
| FC10 | `postgres_container_memory_peak_observed_bytes:1-to-8-workers` (bytes) | arm-median | 1.22409e+08 | 1.30814e+08 | 8.40499e+06 | 0.0686632 | N/A | `MEASURED` |
| FC10 | `postgres_container_memory_peak_observed_bytes-paired-delta:1-to-8-workers` (bytes) | median-paired-delta | 0 | 8.04045e+06 | 8.04045e+06 | N/A | [7.42195e+06, 8.47872e+06] | `MEASURED` |
| FC10 | `postgres_container_io_read_bytes:1-to-8-workers` (bytes) | arm-median | 0 | 0 | 0 | N/A | N/A | `MEASURED` |
| FC10 | `postgres_container_io_read_bytes-paired-delta:1-to-8-workers` (bytes) | median-paired-delta | 0 | 0 | 0 | N/A | [0, 0] | `MEASURED` |
| FC10 | `postgres_container_io_write_bytes:1-to-8-workers` (bytes) | arm-median | 1.21242e+06 | 1.19603e+06 | -16384 | -0.0135135 | N/A | `MEASURED` |
| FC10 | `postgres_container_io_write_bytes-paired-delta:1-to-8-workers` (bytes) | median-paired-delta | 0 | -24576 | -24576 | N/A | [-49152, 147456] | `MEASURED` |
| FC10 | `postgres_xact_commit:1-to-8-workers` (counter-delta) | arm-median | 133 | 158 | 25 | 0.18797 | N/A | `MEASURED` |
| FC10 | `postgres_xact_commit-paired-delta:1-to-8-workers` (counter-delta) | median-paired-delta | 0 | 38 | 38 | N/A | [11, 45] | `MEASURED` |
| FC10 | `postgres_xact_rollback:1-to-8-workers` (counter-delta) | arm-median | 3 | 3 | 0 | 0 | N/A | `MEASURED` |
| FC10 | `postgres_xact_rollback-paired-delta:1-to-8-workers` (counter-delta) | median-paired-delta | 0 | 0 | 0 | N/A | [0, 1] | `MEASURED` |
| FC10 | `postgres_blks_read:1-to-8-workers` (counter-delta) | arm-median | 0 | 0 | 0 | N/A | N/A | `MEASURED` |
| FC10 | `postgres_blks_read-paired-delta:1-to-8-workers` (counter-delta) | median-paired-delta | 0 | 0 | 0 | N/A | [0, 0] | `MEASURED` |
| FC10 | `postgres_blks_hit:1-to-8-workers` (counter-delta) | arm-median | 8849 | 13976 | 5127 | 0.579388 | N/A | `MEASURED` |
| FC10 | `postgres_blks_hit-paired-delta:1-to-8-workers` (counter-delta) | median-paired-delta | 0 | 6118 | 6118 | N/A | [3862, 7206] | `MEASURED` |
| FC10 | `postgres_temp_bytes:1-to-8-workers` (counter-delta) | arm-median | 0 | 0 | 0 | N/A | N/A | `MEASURED` |
| FC10 | `postgres_temp_bytes-paired-delta:1-to-8-workers` (counter-delta) | median-paired-delta | 0 | 0 | 0 | N/A | [0, 0] | `MEASURED` |
| FC10 | `postgres_deadlocks:1-to-8-workers` (counter-delta) | arm-median | 0 | 0 | 0 | N/A | N/A | `MEASURED` |
| FC10 | `postgres_deadlocks-paired-delta:1-to-8-workers` (counter-delta) | median-paired-delta | 0 | 0 | 0 | N/A | [0, 0] | `MEASURED` |
| FC10 | `postgres_tup_returned:1-to-8-workers` (counter-delta) | arm-median | 31786 | 50826 | 19040 | 0.599006 | N/A | `MEASURED` |
| FC10 | `postgres_tup_returned-paired-delta:1-to-8-workers` (counter-delta) | median-paired-delta | 0 | 16173 | 16173 | N/A | [-638, 25298] | `MEASURED` |
| FC10 | `postgres_tup_fetched:1-to-8-workers` (counter-delta) | arm-median | 2617 | 6221 | 3604 | 1.37715 | N/A | `MEASURED` |
| FC10 | `postgres_tup_fetched-paired-delta:1-to-8-workers` (counter-delta) | median-paired-delta | 0 | 2800 | 2800 | N/A | [2349, 3876] | `MEASURED` |
| FC10 | `postgres_tup_inserted:1-to-8-workers` (counter-delta) | arm-median | 65 | 65 | 0 | 0 | N/A | `MEASURED` |
| FC10 | `postgres_tup_inserted-paired-delta:1-to-8-workers` (counter-delta) | median-paired-delta | 0 | 0 | 0 | N/A | [0, 0] | `MEASURED` |
| FC10 | `postgres_tup_updated:1-to-8-workers` (counter-delta) | arm-median | 128 | 146 | 18 | 0.140625 | N/A | `MEASURED` |
| FC10 | `postgres_tup_updated-paired-delta:1-to-8-workers` (counter-delta) | median-paired-delta | 0 | 13 | 13 | N/A | [-4, 34] | `MEASURED` |
| FC10 | `postgres_tup_deleted:1-to-8-workers` (counter-delta) | arm-median | 0 | 0 | 0 | N/A | N/A | `MEASURED` |
| FC10 | `postgres_tup_deleted-paired-delta:1-to-8-workers` (counter-delta) | median-paired-delta | 0 | 0 | 0 | N/A | [0, 0] | `MEASURED` |
| FC11 | `attack_block` (rate) | value | 1 | 1 | 0 | 0 | N/A | `MEASURED` |
| FC11 | `safe_handoff` (rate) | value | 1 | 1 | 0 | 0 | N/A | `MEASURED` |
| FC11 | `false_block` (rate) | value | 0 | 0 | 0 | N/A | N/A | `MEASURED` |
| FC11 | `route_correctness` (rate) | value | 1 | 1 | 0 | 0 | N/A | `MEASURED` |
| FC11 | `critical_failures` (events) | value | 0 | 0 | 0 | N/A | N/A | `MEASURED` |
| FC11 | `duration_ms` (ms) | value | 829 | 10188 | 9359 | 11.2895 | N/A | `MEASURED` |
| FC11 | `provider_cost_nusd` (nUSD) | value | 0 | 0 | 0 | N/A | N/A | `MEASURED` |

## External blockers

- **FC4 — Untouched held-out diagnosis comparison:** Tenant-authorized redacted confirmed closed incidents for the required fourth arm; Retention and consent decision for confirmed-history use.
- **FC5 — Confirmed historical-memory effect:** Tenant-authorized redacted confirmed closed incidents; Retention and consent decision.
- **FC6 — Randomized human response study:** Authorized consenting operators; Scheduled lab environment; Statistician-reviewed protocol.
- **FC7 — Actually approved recovery comparison:** Authorized approvers; Lab-only automation-eligible faults.
- **FC8 — Actual cost reconciliation:** Provider invoice or billing export; Infrastructure allocation rule; Human labor rate decision.

## Limitations

- FC4-FC8 remain blocked by explicitly named authorized human, history, approval or billing data.
- No result establishes human labor reduction, MTTR reduction, actual provider cost savings or production reliability.
- Local capacity and database-resource results cannot set production capacity.
- Rate-card upper bounds are not provider invoices.

## Integrity and reproduction

The JSON publication records SHA-256 for every source artifact. Reproduce with:

- `.venv/Scripts/python -m evaluation.final_report --output evaluation/results/final-comparative-report/v1 --doc docs/REAL_EVALUATION_REPORT.md`
- `.venv/Scripts/pytest -q --no-cov tests/unit/test_final_report.py`
