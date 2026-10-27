# Performance

Measured with `python3 scripts/bench.py --n 20000`: the demo seed plus 20,000 synthetic signed punches,
20,353 events in all. Same machine, before and after this change. Repeated calls are best of 3 to 5.

| metric | before | after |
|---|---|---|
| append throughput | 13.6k events/s | 12.3k events/s (no change, within noise) |
| verify, cold (full re-check) | 1,193 ms | 1,148 ms |
| verify, warm (nothing changed) | 1,115 ms | **0.65 ms** |
| verify after 100 appends | 1,081 ms | **7.4 ms** (only the new tail is checked) |
| GET /api/console/overview | 19,809 ms | **5.7 ms** (warm), about 1.2 s after any write |
| GET /api/sdg8/scorecard | 18,479 ms | **3.8 ms** |
| payslip(W001) | 1,160 ms | 0.9 ms |
| fairness() | 18,348 ms | under 1 ms (warm) |

Before this change, the console polled every 3 s from two apps, and each poll ran about 20 full ledger checks:
one per payslip, nine payslips for each fairness run, and fairness ran twice (once for the overview, once for the
scorecard).

## What changed
- `Ledger.verify()` caches the full result under a fingerprint:
  `(conn.total_changes, PRAGMA data_version, COUNT(*), MAX(seq))`. Callers get a deep copy and a fresh `checked_at`.
- **Incremental check.** The ledger keeps a checkpoint: the head hash, the last seq, any problems found and the
  content hashes for each day. On a cache miss, it checks only the events after the checkpoint, and only if the
  miss is provably append-only. "Append-only" means all of these hold:
  - every row change on this connection since the checkpoint was made by the ledger itself. `append`,
    `_issue_receipt` and `publish_root` count their own row writes, and the counter is only incremented after each
    successful `execute`;
  - `data_version` is unchanged, so no other connection has committed anything;
  - the event count has grown by exactly the number of new rows.
  If any of these fails, every event is checked again from genesis.
- **Daily roots** are recomputed from the checkpoint's content hashes and are no longer re-read or re-hashed from
  every event. A root is memoised only when the checkpoint covers all its events. `roots_status()` reuses `verify()`.
- **Public keys** are cached for each verify pass.
- `Ledger.memo(key, fn)` is a cache keyed by `(connection, total_changes, data_version)`, so any write to any table
  through any connection invalidates it. `pay.hours()` and `pay.fairness()` use it. That means the console overview,
  the scorecard and `/api/pay/fairness` share one computation for each database state.
- `payslip(..., verification=None)` takes an optional verify result. `fairness()` and `run()` verify once and pass the
  result down.

## Why the cache cannot hide a tamper
A tamper has to change a row. SQLite counts every row a statement writes in `total_changes` for the connection that
ran it. This includes raw SQL, and it is how `POST /api/demo/tamper` writes. Any commit from another connection or
process, such as `scripts/tamper.py` or a SQL client, changes `PRAGMA data_version` on our connection.

The fingerprint is read under the lock *before* the rows are read. So any write is either already in the rows that
were checked, or it changes the fingerprint and forces a new check. Both counters only ever move forward, so an old
fingerprint cannot come back.

The incremental path is taken only when every changed row on this connection is accounted for by the ledger's own
appends. A tamper that runs at the same moment as an append still shows up as an unexplained change, so it triggers a
full check. The counter is never incremented ahead of a successful write, so it can only under-count the ledger's own
writes, which means more full checks, never fewer.

Rolled-back writes, new key rows and writes to other tables also cause a full check. Those cases are safe and simply
cost more time.

Tests: `tests/test_perf.py` covers a cache hit and the copy it returns, a tamper through the same connection, a tamper
through a separate sqlite3 connection, incremental versus full results, a tamper after appends, and an overview
latency bound.

## Production path
- **One chain per site** (and per line if needed) keeps each chain short. A worker's proof only touches their own
  site's chain.
- **Checkpointed roots.** Persist a signed checkpoint `(seq, head, merkle root of each day)` after each daily root is
  published. On a cold start, check the signed checkpoint and the tail after it, instead of the whole history. Run a
  full re-check from genesis on a background schedule. Keep publishing the roots outside the system (to workers'
  phones and to an auditor) so the checkpoints themselves can be cross-checked.
- **Move off SQLite** when there are many writers (Postgres with an append-only role), and use a triggered audit
  table instead of `total_changes`/`data_version`.
