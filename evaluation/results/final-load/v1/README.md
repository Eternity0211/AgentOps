# Final capacity and scaling evaluation v1

The source-bound pilot completed all 12 declared repetitions: 64/64 Jobs completed in each run,
with zero errors and zero duplicate ownership. Median throughput was 16.473, 29.223, 30.331 and
24.051 Jobs/s at 1, 2, 4 and 8 workers. Relative to one worker, the descriptive pilot deltas were
0%, +77.4%, +84.1% and +46.0%. The eight-worker pilot was lower than four workers; this pilot is
sizing evidence, not the final broker decision.

The frozen log-throughput variance rule selected 11 repetitions per worker level. The resulting
confirmatory plan was committed before that run. It retains the original joint broker threshold
and requires all 44 repetitions, zero errors, zero duplicate ownership, baseline/candidate values,
deltas and deterministic 95% bootstrap intervals.

CPU and heap observations cover the local Python process only; SQL statement count is not database
CPU or memory. Neither pilot nor confirmatory results may be labeled production capacity,
availability or MTTR.
