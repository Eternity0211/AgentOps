# FC10 database-resource supplement

This supplement closes the resource scope that the original capacity confirmation explicitly left
unmeasured. It reuses the same PostgreSQL queue workload and 1/2/4/8 worker levels, while measuring
the PostgreSQL container rather than only the Python evaluator.

The frozen plan requires 44 rows and captures container CPU, observed memory peak and block I/O,
plus transaction, cache, temporary-byte, deadlock and tuple counters from `pg_stat_database`.
Resource growth is load, not product improvement. Results remain local Docker evidence and cannot
be extrapolated to production sizing.
