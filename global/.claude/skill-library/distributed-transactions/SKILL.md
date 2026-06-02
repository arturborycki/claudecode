---
name: distributed-transactions
description: "Use when implementing transactions that span multiple nodes/partitions: atomic commitment (two-phase commit 2PC, three-phase commit 3PC), and the modern designs — Calvin (deterministic), Spanner (TrueTime + 2PC over Paxos), Percolator (snapshot isolation via a timestamp oracle), database partitioning/sharding, and coordination avoidance. Triggers on distributed transaction, two-phase commit, 2PC, 3PC, atomic commit, coordinator, Calvin, Spanner, TrueTime, Percolator, sharding, cross-partition transaction, coordination avoidance. For single-node transactions use transactions-and-recovery; for the agreement primitive use distributed-consensus."
---

# Distributed Transactions

A transaction that touches multiple nodes must commit **atomically** —
all-or-nothing across partitions. This is harder than single-node because
any participant or the coordinator can fail mid-protocol.

## Two-phase commit (2PC)

The baseline atomic-commitment protocol:
1. **Prepare** — coordinator asks every participant to prepare; each
   durably logs and votes YES (promising it *can* commit) or NO.
2. **Commit/Abort** — if all voted YES, coordinator logs commit and tells
   everyone to commit; any NO → abort everywhere.

2PC is correct but **blocking**: if the coordinator crashes after
participants vote YES but before delivering the decision, participants are
stuck holding locks until it recovers. This is 2PC's defining weakness.

## Three-phase commit (3PC)

Adds a **pre-commit** phase so participants can reach a decision among
themselves if the coordinator dies, making it **non-blocking** under certain
failure assumptions. In practice 3PC is rarely used — it adds a round trip
and breaks under network partitions; most systems instead make the
**coordinator fault-tolerant** by replicating it via consensus (Raft/Paxos),
which is the modern answer to 2PC's blocking problem.

## Modern designs (know the tradeoffs)

- **Calvin** — *deterministic* transactions: agree on a global transaction
  *order* up front (via a sequencing layer over consensus), then every
  replica executes that order deterministically. Eliminates the commit
  protocol's coordination but requires knowing the read/write set in advance.
- **Spanner** — 2PC *over Paxos groups* (so each participant is itself
  fault-tolerant) plus **TrueTime**: an API that exposes clock uncertainty
  as an interval `[earliest, latest]`. By **waiting out the uncertainty**
  before committing, Spanner assigns globally meaningful timestamps and
  achieves **external consistency (linearizability)** across the planet.
  The insight: make time uncertainty explicit and bounded rather than
  pretending clocks are exact.
- **Percolator** — snapshot-isolation transactions on top of a key-value
  store using a **timestamp oracle** and a primary-lock mechanism; commit is
  a 2PC-like protocol recorded in the data itself. Powers incremental
  indexing at scale (and TiDB).
- **Coordination avoidance** — the cheapest coordination is none: if
  operations are commutative or invariant-preserving (see CRDTs in
  `replication-and-consistency`), you can avoid the commit protocol
  altogether. Reach for this before reaching for 2PC.

## Partitioning / sharding

Cross-partition transactions are the expensive case, so **partition to keep
transactions local** where possible (co-locate data accessed together).
Route by partition key; a transaction confined to one partition needs no
distributed commit at all.

## Decision guide

- Single partition → no distributed commit; use `transactions-and-recovery`.
- Must span partitions, need strong consistency → 2PC with a
  **consensus-replicated coordinator** (don't use bare 2PC in production).
- Globally distributed, need external consistency → Spanner-style
  (TrueTime + 2PC over Paxos).
- Known read/write sets, want to avoid commit coordination → Calvin-style
  deterministic ordering.
- Operations commute / tolerate weak consistency → avoid coordination
  entirely.

## Language notes (C/C++/Rust)

- Model each side as an explicit state machine (`Init → Prepared →
  Committed/Aborted`) and **persist state transitions durably before
  acking** — recovery correctness depends on it.
- Make the coordinator fault-tolerant via `distributed-consensus` rather
  than hoping it stays up; a single-process coordinator is a single point of
  blocking.
- Test with injected coordinator/participant crashes at *every* step
  boundary (deterministic simulation), and verify locks are eventually
  released on every failure path.

## Grounding
Petrov Ch 13 (making operations atomic, 2PC, 3PC, Calvin, Spanner, database
partitioning, Percolator, coordination avoidance). DBMS Ch 20 (distributed
commit, distributed locking).
