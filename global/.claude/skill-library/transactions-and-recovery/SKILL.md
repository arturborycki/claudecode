---
name: transactions-and-recovery
description: "Use when implementing or reviewing concurrency control and durability in a single-node database: locking (2PL, lock modes, intention locks, deadlocks), serializability theory, optimistic and multi-version concurrency control (MVCC, snapshot isolation), write-ahead logging (undo/redo/ARIES), checkpoints, and crash recovery. Triggers on transaction, ACID, serializability, 2PL, lock manager, latch, deadlock, isolation level, MVCC, snapshot isolation, WAL, write-ahead log, undo/redo, checkpoint, recovery. For distributed/multi-node transactions use distributed-transactions."
---

# Transactions and Recovery (single node)

Two guarantees, two mechanisms: **concurrency control** gives isolation
(transactions don't corrupt each other), and **logging/recovery** gives
atomicity + durability (crashes don't leave torn state). Keep them
conceptually separate even though they interact.

## Serializability — the correctness target

A schedule is **serializable** if its effect equals some serial order of
the transactions. The practical test is **conflict-serializability**: build
a precedence graph (edge A→B if A has an operation conflicting with and
ordered before B's on the same item); the schedule is conflict-serializable
iff the graph is **acyclic**. This is the yardstick every CC scheme is
measured against.

## Lock-based concurrency control

- **Two-phase locking (2PL)**: each transaction acquires all locks in a
  growing phase and releases in a shrinking phase (no acquire after the
  first release). 2PL guarantees serializability. **Strict 2PL** (hold all
  locks until commit/abort) additionally guarantees recoverability and
  avoids cascading aborts — it's the common choice.
- **Lock modes & compatibility** (the matrix to implement):

  |        | S    | X    |
  |--------|------|------|
  | **S**  | ✓    | ✗    |
  | **X**  | ✗    | ✗    |

  Shared (read) locks are mutually compatible; exclusive (write) locks
  conflict with everything.
- **Hierarchical / intention locks**: to lock at mixed granularity
  (table vs row) add **IS, IX, SIX**. Before locking a row X, take an IX on
  its table; this lets the manager detect coarse/fine conflicts without
  scanning every row lock.
- **Latches vs locks**: latches are short-duration physical mutexes
  protecting in-memory structures (a B-tree node, a buffer frame); locks are
  logical, transaction-duration, and tracked by the lock manager. Don't
  conflate them.

## Deadlocks

2PL can deadlock. Handle by **detection** (a waits-for graph; abort a
transaction in a cycle) or **prevention** (wait-die / wound-wait using
transaction timestamps), or timeouts as a crude fallback.

## Optimistic and multi-version CC

- **MVCC**: keep multiple versions of each item; readers see a consistent
  snapshot without blocking writers, and writers don't block readers. This
  is why **snapshot isolation** is the default in Postgres, Oracle, etc.
  Know its weakness — **write skew** — which serializable snapshot isolation
  (SSI) closes.
- **Optimistic CC**: run without locks, then validate at commit that no
  conflicting transaction committed in the interim; abort and retry if so.
  Wins under low contention.

## Logging and recovery (WAL)

The **write-ahead logging rule**: the log record describing a change must
reach durable storage *before* the corresponding data page is written.
Three disciplines:
- **Undo logging** — log old values; flush log then data, commit only after
  data is on disk. Recovery undoes uncommitted transactions.
- **Redo logging** — log new values; data pages may lag behind commit.
  Recovery redoes committed transactions whose pages weren't flushed.
- **Undo/redo logging** — log both old and new values; most flexible
  (allows steal + no-force buffer policies). This generalizes to
  **ARIES**: analysis pass → redo pass (repeat history) → undo pass (roll
  back losers), using LSNs and a dirty-page table.

**Checkpoints** bound recovery work by recording a consistent point so
recovery needn't scan the whole log. Fuzzy checkpoints avoid stalling
transactions during the checkpoint.

Protect against **media failure** (disk loss) separately with archiving +
log shipping; WAL alone only survives a crash, not a dead disk.

## Language notes (C/C++/Rust)

- **Rust**: the lock manager is a `HashMap<ResourceId, LockState>` behind a
  mutex/sharded mutexes; model lock modes as an enum with a compatibility
  function. MVCC version chains fit `Arc`-linked versions. Use the type
  system to make "holding a latch" a guard (`MutexGuard`) so it's released
  on scope exit.
- **C++**: RAII lock guards for latches; a sharded lock table to reduce
  contention. The log writer is a sequential append — batch and group-commit
  to amortize fsync.
- Group-commit (batch many transactions per fsync) is the highest-leverage
  durability optimization; build the log as an append-only sequential stream.

## Grounding
DBMS Ch 17 (undo/redo/undo-redo logging, media failure), Ch 18
(serializability, locking, lock modes, hierarchies, tree protocol), Ch 19
(recoverability, deadlocks). Petrov Ch 5 (buffer management, recovery,
concurrency control: optimistic, MVCC, timestamp ordering).

## EDBS grounding & deeper skills
EDBS 2e entries (pull full text with `edbs-reference`: `python3 <edbs-reference>/scripts/edbs.py show "<Entry>"`):
*ACID Properties* (p.23); *Two-Phase Locking* (p.4270); *Multiversion Serializability and Concurrency Control* (p.2454); *Snapshot Isolation* (p.3513); *Logging and Recovery* (p.2133); *Multilevel Recovery and the ARIES Algorithm* (p.2344).
Go deeper with: `concurrency-control-theory`, `recovery-and-durability`, `temporal-databases`.
