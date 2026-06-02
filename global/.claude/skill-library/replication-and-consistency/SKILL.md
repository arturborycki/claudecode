---
name: replication-and-consistency
description: "Use when designing replication and consistency for a distributed data store: CAP tradeoffs, consistency models (linearizability, sequential, causal, eventual), session guarantees (read-your-writes, monotonic reads), quorums (R + W > N), tunable consistency, anti-entropy (read repair, hinted handoff, Merkle trees), gossip dissemination, and CRDTs. Triggers on replication, consistency model, linearizability, eventual consistency, CAP, quorum, read repair, hinted handoff, Merkle tree, gossip, CRDT, conflict resolution, last-write-wins. Reach for this whenever copies of data must agree; for agreeing on a single value/log use distributed-consensus."
---

# Replication and Consistency

Replicate data for availability and read scaling — but replicas diverge,
and the consistency model is the contract for how much they may diverge and
what clients observe. This is a spectrum of tradeoffs, not a single right
answer.

## CAP, honestly

Under a network **partition** you must choose between **consistency**
(reject/queue operations to avoid divergence) and **availability** (keep
serving, accept divergence). CAP is about the partition case only; in the
common no-partition case you also trade latency vs consistency (PACELC).
Don't overstate CAP — it's a coarse guide, not a law that forbids strong
consistency.

## Consistency models (strongest to weakest)

- **Linearizability** — operations appear to take effect atomically at some
  point between invocation and response; there is a single, real-time-
  respecting global order. The gold standard; expensive.
- **Sequential consistency** — a single global order consistent with each
  client's program order, but not necessarily real time.
- **Causal consistency** — operations that are causally related are seen in
  order by everyone; concurrent ops may be seen in different orders. Often
  the sweet spot: meaningful guarantees without coordination on every write.
- **Eventual consistency** — replicas converge *if writes stop*; no ordering
  guarantee in the meantime.

## Session (client-centric) guarantees

Even on a weakly consistent store, give a single client sane behavior:
**read-your-writes**, **monotonic reads** (never go backward in time),
**monotonic writes**, **writes-follow-reads**. These are cheaper than global
strong consistency and fix the most jarring anomalies.

## Quorums and tunable consistency

With N replicas, require W replicas to ack a write and R replicas for a
read. **R + W > N** guarantees a read overlaps the latest write (strong-ish
reads). Tuning (R, W) trades read vs write latency vs consistency — e.g.,
W=N read-one is read-optimized; W=1 read-N is write-optimized. **Witness
replicas** participate in quorums without storing full data, cutting cost.

## Anti-entropy — repairing divergence

Replicas drift; reconcile them:
- **Read repair** — on a read, detect stale replicas and push the latest
  value to them.
- **Hinted handoff** — if a replica is down, a coordinator stores a "hint"
  and replays the write when it returns.
- **Merkle trees** — hash trees over key ranges so two replicas can find
  *which* ranges differ with logarithmic comparison instead of shipping all
  data. The backbone of background repair.
- **Gossip** — nodes periodically exchange state with random peers;
  information disseminates epidemically with no central coordinator.

## Conflict resolution and CRDTs

Concurrent writes conflict. Resolution options: **last-write-wins** (simple,
loses data; needs synchronized-ish clocks or version stamps), **version
vectors** (detect concurrency, surface conflicts to the app), or **CRDTs**
(Conflict-free Replicated Data Types) — types (counters, sets, maps)
designed so concurrent updates **merge deterministically** without
coordination, giving **strong eventual consistency**.

## Language notes (C/C++/Rust)

- Use **version vectors / dotted version vectors** to detect concurrent
  updates; represent them compactly and prune retired entries.
- CRDTs need an associative, commutative, idempotent merge — encode that in
  the type's API and property-test the merge laws (Rust: `proptest`).
- Clocks lie: prefer logical clocks / version stamps over wall-clock for
  ordering unless you have bounded-uncertainty time (see Spanner in
  `distributed-transactions`).

## Grounding
Petrov Ch 11 (availability, CAP, ordering, consistency models, session
models, eventual/tunable consistency, witness replicas, CRDTs), Ch 12
(read repair, digest reads, hinted handoff, Merkle trees, bitmap version
vectors, gossip dissemination).
