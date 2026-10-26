# Testing recovery code

Recovery code runs rarely and under the worst conditions, so untested paths
are the norm. Gray's rule of thumb quoted in EDBS Crash Recovery — a
recoverable action is about 30% harder and needs about 20% more code than a
non-recoverable one — understates the testing cost. This file gives a test
architecture, the oracle, the fault model to inject, and the assertions that
catch the classic bugs early.

## 1. Test architecture

```
 workload generator ──► engine under test ──► storage shim (fault injector)
        │                    │                        │
        ▼                    ▼                        ▼
  oracle (model)      in-engine assertions     persisted "disk" image
        │                                             │
        └────────── compare after restart ◄───────────┘
```

- **Storage shim**: interpose every write, fsync/fdatasync, rename, file
  create/delete and directory sync. Keep two views: what the process
  believes was written, and what is *durable* given the device model. A
  crash = discard the volatile view and materialise a durable state chosen
  by the fault model.
- **Deterministic execution**: seed all randomness; run the engine
  single-threaded or under a deterministic scheduler so a failing seed
  reproduces. FoundationDB-style deterministic simulation (all I/O, time and
  network virtualised) is the gold standard for distributed recovery.
- **Workload**: small key space (forces page sharing and splits), mixed
  sizes (forces overflow/large records), long transactions (pins log),
  savepoint rollbacks, aborts, DDL, bulk load, and concurrent backup.

## 2. The oracle

The model tracks, per transaction: submitted, commit-requested,
commit-acknowledged. After restart the database must satisfy:

1. Every **acknowledged** transaction's effects are present (durability).
2. No effect of a transaction that was **never commit-requested** or that
   aborted is present (atomicity).
3. Transactions whose commit was requested but not acknowledged are either
   wholly present or wholly absent (each one independently, but consistent
   with dependency order: if T2 read T1's write and T2 is present, T1 is present).
4. Structural integrity: every index matches its table, B-tree invariants
   (key order, fence keys, sibling links), free-space maps consistent with
   page contents, catalog consistent.
5. Restart is **idempotent**: crashing during restart and restarting again
   yields the same logical state.

Implement 1–3 as a set comparison of logical rows against the model's
expected-state set; 4 with a full consistency checker (amcheck-style) run
after every restart in CI.

## 3. Fault model to inject

| Fault | How to simulate | Expected engine behaviour |
|---|---|---|
| Crash at a point | stop at the k-th I/O call, enumerate k | restart restores oracle state |
| Lost un-synced writes | drop any subset of writes issued since the last fsync on that file | as above; WAL rule must prevent damage |
| Reordered un-synced writes | persist a random subset in random order | as above |
| Torn page | persist only the first j sectors (512 B or 4 KiB) of a page write | detect by checksum; repair from FPI/doublewrite/backup |
| Torn log tail | truncate the last log block mid-record, or leave stale bytes from a recycled segment | end-of-log detection stops cleanly at last valid record |
| Bit flip / misdirected write | corrupt a byte; write page to wrong offset | checksum (with page id in seed) detects; page repair or fail loudly |
| Lost write | acknowledge write, persist nothing | detected via LSN cross-check where implemented; document if not |
| fsync failure | return EIO once, then success | engine treats as fatal and runs crash recovery; never "retries and continues" |
| Directory entry not durable | create/rename file without fsync of directory, crash | engine syncs directories after create/rename |
| ENOSPC on log | fail log write | refuse new work; rollbacks still complete (reserved CLR space) |
| Crash during recovery | apply all of the above inside analysis, redo, undo, and the post-restart checkpoint | converges; bounded extra log |

> **Beyond EDBS:** (1) In 2018 PostgreSQL developers found that on Linux a
> failed fsync could clear the error and drop the dirty pages, so a later
> retry reported success although data was lost; PostgreSQL changed to treat
> fsync failure as a PANIC followed by crash recovery from WAL. Assume the
> same of any OS page cache. (2) Pillai et al. (OSDI 2014, ALICE) showed
> that many applications rely on undocumented file-system ordering and
> atomicity (e.g., rename atomicity without directory fsync, append ordering);
> test against the weakest POSIX-allowed behaviour, not your laptop's file
> system. (3) Studies of SSDs under power faults (Zheng et al., FAST 2013)
> found corruption and lost acknowledged writes on some devices; enterprise
> deployments require power-loss-protected devices and still keep checksums.

## 4. Crash-point enumeration

For a workload of N I/O operations, run N+1 experiments: crash before op k,
for k = 0..N. With "lost unsynced writes" the state space per crash point is
2^(writes since last sync); sample it randomly (and always include "none
persisted" and "all persisted"). Prioritise points adjacent to:
- log flush completions (commit boundary),
- the first write of a page after a checkpoint (FPI boundary),
- master-record update in checkpoint,
- segment switch and recycle,
- SMO (split/merge) records and their nested-top-action/system-txn end,
- each CLR during rollback and during restart undo,
- backup start/stop label writes.

## 5. In-engine assertions (cheap, always on in debug builds)

```
on page write-back:   assert(log.flushedLSN >= page.pageLSN)
on page update:       assert(new_lsn > page.pageLSN); assert(page latched X by me)
on dirtying:          assert(DPT[page] <= new_lsn)
on log append:        assert(rec.prevLSN == txn.lastLSN)
on CLR write:         assert(clr.undoNextLSN < undone_record.lsn)
on undo:              assert(record.type != CLR)          // CLRs never undone
on redo:              assert(no log records appended)
on commit ack:        assert(log.flushedLSN >= commit_lsn)
on truncation:        assert(trunc_lsn <= min(minRecLSN, oldestTxnFirstLSN, archiver, backups, replicas))
on page read:         verify checksum before reading pageLSN
```

Add a **shadow model** in debug builds: keep a copy of every page's expected
contents derived only from the log (apply each record to a shadow page at
append time); compare when the real page is written back. This catches
resource managers whose redo differs from their do.

## 6. Property tests for recovery primitives

- **Redo idempotence**: for random log prefix L and page image P0 drawn from
  any state reachable by write-back, `redo(redo(P0, L), L) == redo(P0, L)`.
- **Do/redo equivalence**: applying an operation at run time and replaying
  its log record onto the pre-image produce byte-identical pages (excluding
  documented non-deterministic fields).
- **Undo inverse**: for each logical operation op on state S,
  `undo(op)(op(S))` is logically equal to S, including after unrelated
  concurrent operations commuted between them (key migration via splits).
- **Rollback equivalence**: transaction that rolls back to a savepoint then
  commits has the same effect as one that never executed the rolled-back part.
- **Checkpoint neutrality**: inserting a checkpoint anywhere in a crash
  experiment does not change the post-restart logical state, only its cost.
- **Log reader robustness**: fuzz the log reader with truncated and corrupted
  segments; it must never crash, loop, or accept a record with bad CRC.

## 7. Distributed and replication scenarios

- Crash coordinator and participants at every 2PC state transition; check
  atomicity across sites and that locks are eventually released; check that
  in-doubt participants never decide unilaterally.
- Partition primary from backups during commit with 1-safe and 2-safe modes;
  verify the documented RPO exactly (count of acknowledged-but-lost
  transactions must be 0 under 2-safe).
- Kill a recovering replica mid state transfer; restart transfer; verify the
  cut set (every transaction exactly once).
- Failover with an in-flight COMMIT: client outcome inquiry returns the truth.
- Jepsen-style history checking for linearizable/serializable claims after
  failovers.

## 8. Backup and restore tests

- Online backup under write load, then PITR to random targets (LSN, time,
  xid); compare to oracle snapshots taken at those targets.
- Remove one archived segment: restore must fail loudly, naming the gap.
- Restore from the oldest generation every release cycle.
- Snapshot data and log volumes at *different* instants (deliberate misuse)
  to confirm the engine detects or at least the runbook forbids it.

## 9. Measuring recovery performance

Report: restart time vs. dirty pages, log since min recLSN, loser log volume;
redo throughput (MB/s log, pages/s); time-to-first-transaction vs.
time-to-full-recovery (for instant restart); throughput during replica
recovery (performability). Regressions here are product regressions: wire
them into the benchmark suite (see `tuning-and-benchmarking`).

## 10. Review checklist

- [ ] Fault-injection shim covers write, fsync, rename, directory sync.
- [ ] Oracle distinguishes acknowledged vs requested commits.
- [ ] Crash-during-recovery runs in CI, not only manually.
- [ ] Torn pages at sector granularity; torn log tails with stale bytes.
- [ ] fsync-error path tested and fatal.
- [ ] Consistency checker runs after every restart in tests.
- [ ] Every new resource manager ships with do/redo equivalence and undo
      inverse property tests.

Sources: EDBS Crash Recovery p.660 (Gray quote; restart concurrency and
redo-only directions); Multilevel Recovery and the ARIES Algorithm p.2344
(testability, nested crashes); Checksum and Cyclic Redundancy Check
Mechanism p.423; Distributed Recovery p.1212; Online Recovery in Parallel
Database Systems p.2564. Testing methodology beyond these entries is
engineering practice and the cited papers.
