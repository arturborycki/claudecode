---
name: concurrency-control-theory
description: "Use when designing, implementing, proving or reviewing concurrency control in a database engine at expert depth: serializability theory, lock managers, B-tree key locking, MVCC, snapshot isolation, SSI, OCC, isolation-level semantics and anomaly testing. Triggers on conflict serializability, view serializability, precedence graph, MVSG, recoverable/ACA/strict/rigorous, strict 2PL, conservative 2PL, wait-die, wound-wait, waits-for graph, intention locks, IS/IX/SIX, lock escalation, latch coupling, B-link tree, next-key locking, gap lock, ghost record, phantom, timestamp ordering, Thomas write rule, MVTO, write skew, SIREAD, dangerous structure, G0/G1c/G2/G-single, Berenson critique, escrow, commutativity, multilevel/open nested transaction, saga, transaction chopping, thrashing, hot spot. Apply even when phrased as 'two sessions corrupt a counter', 'why did this serialization failure happen', 'can we drop read locks', 'is REPEATABLE READ enough' or 'deadlocks under load'."
---

# Concurrency Control Theory and Mechanisms

This skill owns the isolation half of the transaction manager: correctness
criteria (serializability and recoverability classes, isolation levels as
dependency-graph phenomena) and the mechanisms that enforce them (2PL and the
lock manager, B-tree key-range locking, timestamp ordering, OCC, MVCC/SI/SSI,
semantic and extended models). The single most important idea: **every
mechanism keeps a dependency graph acyclic** (ww, wr, rw edges, plus
real-time edges if you promise strictness), and every isolation level states
which cycles you tolerate. Get the graph right, then pick the cheapest
enforcer.

## Mental model

- **Two layers, two tools.** Locks protect logical contents between
  transactions (modes, queues, deadlock detection, held to commit). Latches
  protect physical structures between threads (S/X, tens of instructions,
  deadlock avoided by ordering). Index operations are subtransactions:
  latches released per operation, key locks held to commit (multilevel
  transactions). Mixing the layers creates deadlocks no detector sees.
- **Edges.** `Ti -wr-> Tj` (Tj saw Ti), `Ti -ww-> Tj` (Tj overwrote Ti),
  `Ti -rw-> Tj` (Ti did not see Tj). Pessimistic schemes stop edges forming
  in the wrong direction; optimistic schemes let them form and abort at
  validation; MVCC folds ww/wr into version order, leaving rw edges as the
  hazard.
- **Serializability concerns the committed projection; recoverability
  concerns aborts.** Strictness (no read/overwrite of uncommitted writes)
  makes before-image undo correct, so dirty writes are banned at every level.
- **SI is not serializable.** Its cycles always contain two consecutive rw
  edges between concurrent transactions (write skew, read-only anomaly). SSI
  aborts the pivot of that structure.
- **Contention is quadratic.** Blocking probability grows with `M·k²/D`;
  long transactions dominate; thrashing is a data-contention collapse that
  can happen with idle CPUs.

## Core invariants

1. Every producible history's committed projection is in the claimed class
   (CSR/OCSR/COCSR/MVSR); at each isolation level, none of its forbidden Adya
   phenomena (G0, G1a, G1b, G1c, G-single, G2-item, G2) occurs.
2. No dirty write (P0) at any level: a write to `x` waits for or aborts
   against any uncommitted writer of `x`.
3. If `Tj` reads from `Ti`, `Ti` commits first (RC); default levels never
   read uncommitted data (ACA/ST).
4. 2PL: no acquire after the first release; SS2PL: release only at or after
   commit/abort.
5. Lock manager: granted requests on a resource are pairwise compatible; no
   request overtakes an earlier incompatible waiter except conversions; every
   waiter is eventually granted or aborted.
6. Every waits-for cycle is detected within a bound, or is impossible by
   construction (wait-die/wound-wait with retained timestamps, ordered
   acquisition).
7. MGL: a lock on a node implies the matching intention lock on every
   ancestor (X/IX/SIX need IX or SIX on all parents in a DAG); escalation
   drops child locks only after the covering parent lock is granted.
8. SERIALIZABLE range protection: every scanned range is covered by key and
   gap locks (including the gap past the last key, up to an end sentinel) or
   by predicate/SIREAD tracking; ghosts are purged only when no lock covers
   them.
9. No reader observes a half-split node; a pointer is followed only while its
   source is latched or version-validated (coupling, B-link move-right,
   optimistic lock coupling).
10. MVCC: a transaction sees exactly the versions committed before its
    snapshot plus its own writes; commit status is published atomically with
    the commit timestamp; no version visible to an active snapshot is reclaimed.
11. SI: two concurrent committed transactions never wrote the same item. SSI:
    no committed dangerous structure `T1 -rw-> T2 -rw-> T3` with `T3`
    committing first, unless proven cycle-free.
12. OCC: commit only if nothing read (including scanned ranges) was written
    by a transaction that committed during this one's lifetime; never act on
    inconsistent intermediate reads.
13. Semantic CC: operations are non-conflicting only if they commute (or are
    recoverable relative to each other with the commit order enforced), and
    each has a logical inverse used by undo.

## Design space & trade-offs

| Mechanism | When it wins | Cost / risk |
|---|---|---|
| SS2PL + MGL + key-range locks | general OLTP, predictable semantics | readers block writers; deadlocks; lock-manager CPU; escalation |
| Conservative / deterministic ordered locking | predeclared read/write sets; replication without 2PC (Calvin) | sets needed up front; batching latency |
| Basic TO / MVTO | no waiting; read-heavy (MVTO) | reads write `RTS`; late writers abort; timestamp counter bottleneck |
| OCC (backward/forward; Silo-style) | in-memory, low contention, short txns | aborts grow with `k²`; zombies; range validation |
| MV2PL / snapshot readers + 2PL | long readers in a locking engine | version storage; certify waits |
| SI | read-heavy, non-blocking reads | write skew, read-only anomaly; GC horizon |
| SSI | serializable at near-SI cost | false-positive aborts; SIREAD memory |
| Escrow / commutative operations | hot aggregates (stock, balances, counters) | ranged reads; special recovery |
| Chopping / sagas / open nesting | long or hot transactions | SC-cycle proof or compensation design |

Deadlock policies (WFG detection, timeout, wait-die, wound-wait, no-wait,
cautious waiting) are compared in `references/locking-and-btree-concurrency.md`.

## Algorithms that matter

- **CSR test**: `SG` over committed txns, cycle check `O(V+E)`. VSR and
  general MVSR testing are NP-complete: never build those schedulers.
- **SS2PL request**: hash -> latch bucket -> grant if compatible with group
  mode and no waiters (or a conversion); else enqueue, add WFG edges, unlatch,
  sleep. Commit releases all, waking compatible queue prefixes.
- **Next-key locking**: scan `[a,b]` S-locks each key and the first key `> b`;
  insert `k` takes instant X on the next key under the page latch, then X on
  `k`; delete X-locks `k` and the next key (or ghosts `k`).
- **B-link split**: half-split (right sibling, high key, right-link) under one
  latch; post separator later; readers move right when `key > highkey`.
- **Basic TO**: reject read if `ts < WTS`; reject write if `ts < RTS`; skip
  write if `ts < WTS` (Thomas rule: VSR only).
- **OCC**: abort if `WS(Ti) ∩ RS(Tj) ≠ ∅` for any `Ti` committed during `Tj`;
  Silo: lock sorted write set, fence, validate read-set TIDs and node set.
- **MVTO**: read largest `wts <= ts`; write aborts if that version's
  `rts > ts`; commit waits for writers of versions read.
- **SSI**: non-blocking SIREAD locks kept past commit; rw edges recorded on
  read (newer invisible version) and on write (SIREAD holders); abort a pivot
  with in and out edges, filtered by `T3`-commits-first and read-only rules.
- **Escrow**: keep `inf <= val <= sup`; admit a signed delta `d < 0` only if
  `inf + d >= Min` (`d > 0`: `sup + d <= Max`); commit/abort adjust bounds.
- **Chopping**: S/C graph of pieces; correct if rollback-safe and SC-acyclic.

## Failure modes & classic bugs

- Dirty writes at READ UNCOMMITTED: undo restores a before-image over another
  transaction's write.
- Lost update under RC read-modify-write, or in "REPEATABLE READ" engines that
  are not SI (locking reads see latest, plain reads see snapshot).
- Phantoms: row locks only; no end-of-range sentinel; ghost purged under a
  range lock; OCC validating items but not ranges.
- Latch held while waiting for a lock (latch/lock deadlock). Request
  conditionally under the latch; else unlatch, wait, re-latch, recheck LSN.
- S->X upgrade deadlocks without U mode; escalation-induced deadlocks.
- Wait-die/wound-wait restarting with a new timestamp (starvation); basic TO
  without commit buffering (unrecoverable reads).
- OCC zombies on inconsistent reads; optimistic index readers without epoch
  reclamation (use-after-free).
- SSI: SIREAD dropped at reader commit; predicate reads without index-range
  SIREAD; serializable reads on replicas.
- MVCC: commit timestamp visible before commit status; GC reclaiming a version
  an old snapshot needs; bloat from idle-in-transaction sessions.
- Raising MPL "to use idle CPU" past the conflict-ratio knee: thrashing.
Detect with the anomaly suite below, invariant workloads, lock-wait and
abort-reason telemetry, and Elle-style DSG checking of randomized histories.

## Implementation checklist (C/C++/Rust)

- Lock table: sharded hash of lock heads (granted list, wait queue,
  conversion queue, group mode); per-txn intrusive request list for
  `O(locks)` release; sleep on a per-txn futex/condvar, never under a bucket
  latch.
- Logical lock names (table id + key bytes/hash), never `(page, slot)`; modes
  as an enum with constant compatibility and supremum tables, tested exhaustively.
- WFG maintained incrementally; detection from the new edge or a background
  pass; victim policy with anti-starvation counter.
- Latches: RW latch or optimistic version word in node headers; try-latch for
  sibling moves; epoch reclamation or hazard pointers for optimistic readers.
- MVCC header: begin/end ts or `xmin/xmax`, version pointer, lock/TID word;
  release-ordered commit publication; snapshot = `ts` or `(xmin,xmax,active)`.
- SSI: per-txn in/out conflict lists; SIREAD table with granularity promotion,
  memory bound, and a tested summarisation path.
- OCC: read set (ptr, observed version), write set sorted globally before
  locking, node set for phantoms; acquire loads during validation.
- Escrow/commutative ops: dedicated operator and log record types with logical
  redo/undo, excluded from before-image undo.
- Metrics: lock waits per resource, deadlocks, timeouts, escalations, conflict
  ratio, serialization/validation failures, oldest snapshot age.

## How to test it

- **Anomaly suite** per isolation level (scripted 2–3 session interleavings):
  P0, P1, P4 lost update, A5A read skew, A5B write skew, predicate write skew
  (check-then-insert), A3 phantom, SI read-only anomaly; assert
  allowed/forbidden against your documented level table.
- **History oracle**: log operations with versions, build Adya's DSG, Tarjan
  SCC for cycles; for COCSR replay serially in commit order; list-append
  workloads make version orders recoverable (Elle).
- **Invariant workloads**: constant-sum transfers, on-call doctors, unique
  bookings; random interleavings plus crash and abort injection.
- **Deterministic simulation** of schedules around latch/lock boundaries.
- **Lock manager model test**: random request streams vs a reference model;
  assert compatibility on grant, FIFO fairness, no lost wakeups, bounded
  cycle detection.
- **B-tree stress**: concurrent insert/delete/bidirectional scans with
  structure verification (fence keys = parent separators, no lost keys).
- **Contention curves**: throughput vs MPL under Zipf skew, no collapse past
  the knee with admission control on.

## Expert review questions

1. Which class do you guarantee (CSR, OCSR, COCSR, MVSR, strict
   serializability), and which oracle checks it?
2. Where is a dirty write prevented at READ UNCOMMITTED?
3. Does "strict 2PL" mean write locks or all locks to commit? If read locks
   are released early, what defines the lock point?
4. How are phantoms prevented for range scans, `count(*)`, `NOT EXISTS` and
   unique checks, and what protects the gap past the last key?
5. Is any latch held while waiting for a lock? Deadlock policy, victim rule,
   starvation prevention?
6. When does escalation trigger, can it deadlock, and can the optimizer pick
   granularity up front?
7. MVCC: snapshot format, commit-status publication order, GC horizon bound?
8. Is SERIALIZABLE actually SI? If SSI, what false-positive rate on your
   workload, and which promotions cause it?
9. OCC: how are ranges validated, and what stops zombies?
10. Which operations are declared commutative, and what is their logical undo?
11. Which transactions dominate `k²`-weighted contention; can they be chopped
    (show the SC-graph) or made escrow/commutative?
12. Does admission control use CPU, or blocked fraction / conflict ratio?
13. How do replicas and mixed isolation levels affect the serializability claim?

## Go deeper

- `references/serializability-theory.md` — class hierarchy, recoverability, SGT, TO, OCC (Silo, TicToc); for proofs.
- `references/locking-and-btree-concurrency.md` — 2PL variants, lock manager, deadlocks, MGL, latching, B-link, next-key/ghosts.
- `references/mvcc-si-ssi.md` — MVSG, MVTO, MV2PL, SI anomalies, SDG analysis, SSI/PostgreSQL, Hekaton/HyPer/Cicada.
- `references/isolation-levels-and-anomalies.md` — ANSI, Berenson table, Adya phenomena, product mapping, repro scripts, Elle.
- `references/semantic-and-extended-transaction-models.md` — commutativity, escrow, multilevel/nested, sagas, ACTA, STM, real-time.
- `references/cc-performance-and-tuning.md` — contention models, thrashing, RP/WDL, hot spots, chopping, Calvin/H-Store.
- `references/edbs-entries.md` — all 33 source entries with printed pages (full text via `edbs-reference`).

## Related skills

- `transactions-and-recovery` (existing overview; this is the deep layer
  beneath it) and `recovery-and-durability` (WAL/ARIES, CLRs, logical undo for
  multilevel transactions, early lock release, ghost-cleanup logging).
- `distributed-transactions` (2PC, Spanner, Percolator, Calvin as a
  distributed system), `distributed-dbms-design` (global serializability,
  QSR/2LSR, multidatabases), `replication-protocols` and
  `replication-and-consistency` (1SR, replica control, replicated SI).
- `index-structures-catalog`, `storage-and-indexing`, `lsm-storage` (structures
  themselves; this skill owns their concurrency protocols and MVCC rules).
- `dbms-architecture` (placement of lock/transaction managers),
  `parallel-database-systems` (intra-transaction parallelism sharing locks),
  `tuning-and-benchmarking` (general tuning; CC tuning lives here).
- `materialized-views-ivm` (increment locks, escrow for summaries),
  `sql-semantics-and-active-rules` (statement semantics, detached triggers),
  `temporal-databases` (time-travel versions vs MVCC versions),
  `database-security-internals` (CC covert channels), `beyond-relational-engines`
  (STM, object stores), `query-engine-testing` (anomaly/history oracles).

## Grounding

EDBS (Liu and Özsu, 2nd ed., 2018), core entries: Transaction Models: The
Read/Write Approach p.4194; Two-Phase Locking p.4270; Concurrency Control:
Traditional Approaches p.575; Locking Granularity and Lock Types p.2131;
B-Tree Locking p.345; Multiversion Serializability and Concurrency Control
p.2454; Snapshot Isolation p.3513; Serializable Snapshot Isolation p.3476;
SQL Isolation Levels p.3681; Multilevel Transactions and Object-Model
Transactions p.2353; Escrow Transactions p.1332; Transaction Chopping
p.4187; Performance Analysis of Transaction Processing Systems p.2732;
Tuning Concurrency Control p.4252. All 33 entries: `references/edbs-entries.md`.

Seminal: Eswaran et al. 1976; Gray et al. 1975; Papadimitriou 1979; BHG 1987;
Weikum and Vossen 2002; Kung and Robinson 1981; Lehman and Yao 1981; Mohan
1990; Berenson et al. 1995; Adya 1999; Fekete et al. 2005; Cahill et al. 2009;
Ports and Grittner 2012; O'Neil 1986; Weikum 1991; Shasha et al. 1995.
Systems: PostgreSQL SSI, InnoDB, SQL Server, Silo, Hekaton, HyPer, Calvin, Elle.
