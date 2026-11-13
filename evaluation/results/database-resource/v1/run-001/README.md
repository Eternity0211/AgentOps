# FC10 PostgreSQL database-resource supplement

All values are local Docker PostgreSQL-container load, not application benefit or production capacity. Each arm contains eleven paired repetitions.

| Workers | Metric | Baseline median | Candidate median | Arm-median delta | Paired delta median (95% interval) | Relative arm delta |
| ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 2 | `postgres_container_cpu_usage_usec` | 262731.000 | 266184.000 | +3453.000 | +3453.000 [-16575.000, +35924.000] | +1.3% |
| 2 | `postgres_container_memory_peak_observed_bytes` | 122408960.000 | 124018688.000 | +1609728.000 | +516096.000 [-671744.000, +708608.000] | +1.3% |
| 2 | `postgres_container_io_read_bytes` | 0.000 | 0.000 | +0.000 | +0.000 [+0.000, +0.000] | N/A |
| 2 | `postgres_container_io_write_bytes` | 1212416.000 | 1204224.000 | -8192.000 | +0.000 [-196608.000, +385024.000] | -0.7% |
| 2 | `postgres_xact_commit` | 133.000 | 114.000 | -19.000 | -17.000 [-31.000, -3.000] | -14.3% |
| 2 | `postgres_xact_rollback` | 3.000 | 3.000 | +0.000 | +0.000 [+0.000, +1.000] | +0.0% |
| 2 | `postgres_blks_read` | 0.000 | 0.000 | +0.000 | +0.000 [+0.000, +0.000] | N/A |
| 2 | `postgres_blks_hit` | 8849.000 | 6785.000 | -2064.000 | -706.000 [-2911.000, -87.000] | -23.3% |
| 2 | `postgres_temp_bytes` | 0.000 | 0.000 | +0.000 | +0.000 [+0.000, +0.000] | N/A |
| 2 | `postgres_deadlocks` | 0.000 | 0.000 | +0.000 | +0.000 [+0.000, +0.000] | N/A |
| 2 | `postgres_tup_returned` | 31786.000 | 20541.000 | -11245.000 | -3406.000 [-6769.000, +2962.000] | -35.4% |
| 2 | `postgres_tup_fetched` | 2617.000 | 2422.000 | -195.000 | -322.000 [-1138.000, -104.000] | -7.5% |
| 2 | `postgres_tup_inserted` | 65.000 | 65.000 | +0.000 | +0.000 [+0.000, +0.000] | +0.0% |
| 2 | `postgres_tup_updated` | 128.000 | 111.000 | -17.000 | -18.000 [-32.000, +2.000] | -13.3% |
| 2 | `postgres_tup_deleted` | 0.000 | 0.000 | +0.000 | +0.000 [+0.000, +0.000] | N/A |
| 4 | `postgres_container_cpu_usage_usec` | 262731.000 | 263157.000 | +426.000 | +25113.000 [-21493.000, +46754.000] | +0.2% |
| 4 | `postgres_container_memory_peak_observed_bytes` | 122408960.000 | 123187200.000 | +778240.000 | +778240.000 [-389120.000, +2686976.000] | +0.6% |
| 4 | `postgres_container_io_read_bytes` | 0.000 | 0.000 | +0.000 | +0.000 [+0.000, +0.000] | N/A |
| 4 | `postgres_container_io_write_bytes` | 1212416.000 | 1204224.000 | -8192.000 | +0.000 [-24576.000, +303104.000] | -0.7% |
| 4 | `postgres_xact_commit` | 133.000 | 125.000 | -8.000 | -5.000 [-22.000, +13.000] | -6.0% |
| 4 | `postgres_xact_rollback` | 3.000 | 3.000 | +0.000 | +0.000 [+0.000, +1.000] | +0.0% |
| 4 | `postgres_blks_read` | 0.000 | 0.000 | +0.000 | +0.000 [+0.000, +0.000] | N/A |
| 4 | `postgres_blks_hit` | 8849.000 | 8492.000 | -357.000 | -906.000 [-2494.000, +1728.000] | -4.0% |
| 4 | `postgres_temp_bytes` | 0.000 | 0.000 | +0.000 | +0.000 [+0.000, +0.000] | N/A |
| 4 | `postgres_deadlocks` | 0.000 | 0.000 | +0.000 | +0.000 [+0.000, +0.000] | N/A |
| 4 | `postgres_tup_returned` | 31786.000 | 31285.000 | -501.000 | -501.000 [-11789.000, +9159.000] | -1.6% |
| 4 | `postgres_tup_fetched` | 2617.000 | 2503.000 | -114.000 | -153.000 [-1325.000, +369.000] | -4.4% |
| 4 | `postgres_tup_inserted` | 65.000 | 65.000 | +0.000 | +0.000 [+0.000, +0.000] | +0.0% |
| 4 | `postgres_tup_updated` | 128.000 | 123.000 | -5.000 | +0.000 [-19.000, +12.000] | -3.9% |
| 4 | `postgres_tup_deleted` | 0.000 | 0.000 | +0.000 | +0.000 [+0.000, +0.000] | N/A |
| 8 | `postgres_container_cpu_usage_usec` | 262731.000 | 365323.000 | +102592.000 | +96489.000 [+56211.000, +164862.000] | +39.0% |
| 8 | `postgres_container_memory_peak_observed_bytes` | 122408960.000 | 130813952.000 | +8404992.000 | +8040448.000 [+7421952.000, +8478720.000] | +6.9% |
| 8 | `postgres_container_io_read_bytes` | 0.000 | 0.000 | +0.000 | +0.000 [+0.000, +0.000] | N/A |
| 8 | `postgres_container_io_write_bytes` | 1212416.000 | 1196032.000 | -16384.000 | -24576.000 [-49152.000, +147456.000] | -1.4% |
| 8 | `postgres_xact_commit` | 133.000 | 158.000 | +25.000 | +38.000 [+11.000, +45.000] | +18.8% |
| 8 | `postgres_xact_rollback` | 3.000 | 3.000 | +0.000 | +0.000 [+0.000, +1.000] | +0.0% |
| 8 | `postgres_blks_read` | 0.000 | 0.000 | +0.000 | +0.000 [+0.000, +0.000] | N/A |
| 8 | `postgres_blks_hit` | 8849.000 | 13976.000 | +5127.000 | +6118.000 [+3862.000, +7206.000] | +57.9% |
| 8 | `postgres_temp_bytes` | 0.000 | 0.000 | +0.000 | +0.000 [+0.000, +0.000] | N/A |
| 8 | `postgres_deadlocks` | 0.000 | 0.000 | +0.000 | +0.000 [+0.000, +0.000] | N/A |
| 8 | `postgres_tup_returned` | 31786.000 | 50826.000 | +19040.000 | +16173.000 [-638.000, +25298.000] | +59.9% |
| 8 | `postgres_tup_fetched` | 2617.000 | 6221.000 | +3604.000 | +2800.000 [+2349.000, +3876.000] | +137.7% |
| 8 | `postgres_tup_inserted` | 65.000 | 65.000 | +0.000 | +0.000 [+0.000, +0.000] | +0.0% |
| 8 | `postgres_tup_updated` | 128.000 | 146.000 | +18.000 | +13.000 [-4.000, +34.000] | +14.1% |
| 8 | `postgres_tup_deleted` | 0.000 | 0.000 | +0.000 | +0.000 [+0.000, +0.000] | N/A |

Acceptance: `PASS`. The result retains all 44 rows and rejects missing counters, negative cumulative deltas, task errors or duplicate ownership.
