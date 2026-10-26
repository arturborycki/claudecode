# Checkpointing and main-memory recovery

Checkpoints exist to make restart cost independent of the time since the last
failure. Without them, a no-force engine's hot pages (never evicted because
they are always referenced) accumulate the updates of countless committed
transactions, and redo would have to start arbitrarily far back in the log
(Härder, Crash Recovery entry). For main-memory engines the checkpoint *is*
the on-disk database; the log is only the delta since it.

## 1. Checkpoint kinds (Härder–Reuter terminology)

| Kind | What happens | DB state on disk at checkpoint | Pause | Redo starts at |
|---|---|---|---|---|
| Transaction-oriented (TOC) | every commit forces its pages (= FORCE policy) | each txn's pages | none extra, but every commit pays | nothing to redo |
| Transaction-consistent (TCC) | stop admitting txns, drain, flush all dirty pages, log CKPT | transaction consistent | until longest txn ends + full flush | checkpoint |
| Action-consistent (ACC) | stop operations (not txns) at operation boundaries, flush all dirty pages | operation consistent (losers' completed ops present) | full buffer flush | checkpoint; undo still needed |
| Fuzzy | log TT + DPT only; pages flushed asynchronously | arbitrary page mix | latch on TT/DPT copy | min recLSN (may precede checkpoint) |

"Direct" checkpoints (TCC, ACC) write the buffer synchronously; with
multi-GB buffers that stall is unacceptable, so industrial engines use
fuzzy ("indirect") checkpoints with a background writer. ACC/TCC remain
useful where an operation-consistent image is required, e.g. to enable
logical (operation) logging, and they are what main-memory snapshots emulate
cheaply with copy-on-write.

## 2. Restart time model

```
T_restart ≈ T_analysis + T_redo + T_undo
T_analysis ≈ bytes(log from BEGIN_CKPT to end) / seq_read_bw
T_redo     ≈ bytes(log from min recLSN) / seq_read_bw          (log read)
           + |DPT pages needing I/O| × read_latency / io_parallelism
           + apply CPU
T_undo     ≈ Σ_losers records × (random log read if not cached + apply)
```

Levers:
- **Shorter checkpoint interval** bounds analysis; it does *not* bound redo
  unless dirty pages are also written.
- **Age-ordered write-back**: flush pages in order of oldest recLSN (a
  "checkpoint queue" ordered by first-dirty LSN), so min recLSN advances
  smoothly. LRU-only eviction leaves hot pages dirty indefinitely.
- **Cap dirty pages** or bytes of log since min recLSN; translate a recovery
  time objective into that cap using measured log replay rate.
- **Undo cost** is bounded only by transaction size: cap or split large
  transactions, or use version-store-based logical revert.
- **Prefetch** DPT pages in recLSN order during redo; parallelise apply by page.

> **Beyond EDBS:** SQL Server "indirect checkpoints" take a target recovery
> time and drive background writes to meet it; PostgreSQL spreads
> checkpoint writes over `checkpoint_completion_target` of the interval and
> triggers checkpoints by `checkpoint_timeout` or WAL volume (`max_wal_size`).
> Both are fuzzy checkpoints with age-aware write-back in spirit. A longer
> PostgreSQL checkpoint interval also reduces full-page-image volume, which
> is the usual tension: fewer FPIs vs. longer redo.

Measure, don't guess: a recovery benchmark should report restart time vs.
(dirty pages, log since min recLSN, loser log volume) and the replay rate
(MB/s of log, pages/s).

## 3. Correctness obligations of a checkpoint

1. The END_CKPT record (TT + DPT) is durable before the master record points
   at its BEGIN_CKPT.
2. The DPT snapshot never omits a page that is dirty with a change older than
   the snapshot (recLSN may be conservative).
3. Transactions that begin or pages dirtied between BEGIN and END are found by
   analysis because it scans from BEGIN, not END.
4. Log truncation uses the checkpoint's min recLSN and oldest active
   transaction, recomputed, never only "the checkpoint LSN".
5. The checkpoint itself must not deadlock with the page writer or hold page
   latches while waiting for log flushes.

## 4. Main-memory DBMS durability

An MMDBMS keeps the primary copy in RAM and optimises for CPU and cache
(cache-line-sized index nodes, simple tuple layouts); I/O is off the critical
path except for the log. ACID durability is provided by (Boncz, Main Memory
DBMS entry): transaction logging to a journal plus checkpoints, non-volatile
RAM (battery-backed or EEPROM-class), and/or replication with failover to a
standby (ClustRa, MySQL Cluster). Recovery = load latest checkpoint image +
replay the log suffix.

Because nothing but the checkpoint and log reach disk, MMDBs can choose
**no-steal**: uncommitted data is never written. That makes the log
**redo-only**: undo information stays in memory for runtime aborts and is
never logged. Commit = force the transaction's redo (with group commit).

### 4.1 Checkpoint strategies for in-memory state

| Strategy | Image consistency | Normal-path cost | Notes |
|---|---|---|---|
| Fuzzy copy | none; may contain uncommitted and partially applied state | none | log must be replayable onto an arbitrary image: physical/idempotent records or per-record version stamps, and uncommitted data in the image needs undo or must be excluded |
| Quiesce + copy (TCC) | transaction consistent | stall proportional to DB size | only for small DBs |
| Copy-on-write snapshot (fork(), page-level COW) | transaction consistent at fork instant | memory for copied pages; fork latency on large page tables | HyPer used fork for OLAP snapshots (Kemper & Neumann, ICDE 2011); Redis background save works this way |
| MVCC snapshot read | transaction consistent at a timestamp | version retention while checkpoint scans | natural for MVCC engines; checkpoint = scan at snapshot ts |
| Ping-pong (two images, alternate) | consistent per image with dirty tracking | double space | always one complete image on disk while the other is written (Salem & Garcia-Molina, 1989 study of MMDB checkpointing) |
| Virtual point of consistency (CALC; Ren et al., SIGMOD 2016) | transaction consistent | keep a stable copy only for records modified during the checkpoint | avoids physical quiesce |

Record in the checkpoint metadata the exact log position (or commit
timestamp) it is consistent with; replay starts there. For a fuzzy image,
replay starts at the log position at the *start* of the copy.

### 4.2 What to log: value vs command logging

| | Value (physical/tuple) logging | Command (logical) logging |
|---|---|---|
| Log content | after-images of modified tuples (+ key) | stored-procedure id + parameters + order |
| Log volume | proportional to data changed | tiny, constant per txn |
| Requires | nothing special | deterministic execution and a single serial order (or deterministic scheduler), operation-consistent checkpoint |
| Replay | parallel by key/partition; order-insensitive if versions are stamped | re-executes transactions, serially or under the original deterministic schedule; CPU-bound, as slow as original execution |
| Failure risk | low | any non-determinism (wall clock, random, hash-iteration order, external calls, UDF behaviour change after upgrade) silently forks state |

Malviya, Weisberg, Madden & Stonebraker (ICDE 2014, "Rethinking main memory
OLTP recovery", VoltDB) found command logging raises normal throughput and
shrinks the log, at the price of slower recovery; deterministic systems such
as Calvin get it naturally. Use command logging only with enforced
determinism (seeded RNG in the log, timestamps assigned by the sequencer,
deterministic iteration).

### 4.3 Parallel logging and recovery in multicore MMDBs

- One log stream per core or per partition removes the global log-append
  bottleneck. Commit durability then needs a global "durable epoch" or
  "durable timestamp": a transaction is durable when every stream has
  flushed through its epoch.
- **Order-insensitive replay**: if each logged record carries the writing
  transaction's commit TID and replay keeps, per key, the version with the
  largest TID, the streams can be replayed concurrently in any order — replay
  is idempotent and commutative (SiloR; Zheng, Tu, Liskov & Madden, OSDI
  2014). Deletes need tombstones with TIDs.
- Do not replay a stream past the global durable epoch: records of an epoch
  that was not durable on *all* streams belong to transactions that were never
  acknowledged and must be discarded.

> **Beyond EDBS:** Hekaton (SQL Server In-Memory OLTP; Diaconu et al.,
> SIGMOD 2013) logs only committed transactions' row versions (redo only, no
> WAL-before-data ordering because nothing but the log and checkpoint files
> reach disk), does not log index operations at all (indexes are rebuilt at
> recovery), and checkpoints as append-only data/delta file pairs that are
> loaded in parallel at restart.

### 4.4 Replication as durability

"Commit when the redo is in the memory of k nodes with independent failure
modes" replaces the disk force by a network round trip (ClustRa telecom DB,
Hvasshovd et al., VLDB 1995; MySQL Cluster). HARBOR (Lau & Madden, VLDB 2006)
drops the recovery log entirely for an updatable warehouse and recovers a
crashed site by querying replicas for missed updates with historical
(time-travel) queries. Requirements: replicas must not share failure causes
(power, rack, software version where a bug can strike all), and a correlated
failure must be survivable — keep an asynchronous disk log or periodic
checkpoints as the floor.

### 4.5 Non-volatile memory

NVRAM / storage-class memory makes log writes near DRAM latency, so commit
becomes CPU-bound and group commit matters less; it also enables keeping data
structures persistent in place (Pelley, Wenisch, Gold & Bridge, PVLDB 2013).
Correctness then depends on cache-line flush and fence ordering rather than
fsync: a persisted pointer must never become durable before the data it points
to. Treat each persist barrier as you would a WAL flush, and test with
cache-line-granular crash injection.

## 5. Pitfalls

- fork-based snapshots: page-table copy time grows with memory size; COW can
  double RSS under write-heavy load; transparent huge pages amplify copies.
- Fuzzy MMDB checkpoints with logical log records: replaying "increment x"
  onto an image that already contains the increment double-applies it.
- Checkpoint metadata written before the image is fully synced: restart loads
  a partial image believing it complete. Write image, fsync, then the
  manifest, fsync the directory.
- Deleting old log segments before the new checkpoint's manifest is durable.
- Command logging after a code upgrade: replay executes new procedure code
  against old commands. Version procedures in the log or checkpoint before
  upgrade.

Sources: EDBS Crash Recovery p.660; Main Memory DBMS p.2164 (DeWitt et al.
1984; Bohannon et al., Dalí 1997; Hvasshovd et al., ClustRa 1995 in its
reading list); Distributed Recovery p.1212 (ClustRa redundant in-memory
logging; HARBOR); Logging and Recovery p.2133; Application Recovery p.123
(checkpoint plus replay of logged non-determinism). Beyond-EDBS items cite
their own papers.
