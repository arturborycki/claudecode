---
name: parallel-distributed-execution
description: "Use when adding parallelism or distribution to query EXECUTION (not data replication): partitioning schemes, exchange/repartition (shuffle) operators, partition pruning, parallel and distributed joins/aggregates, query stages, streaming vs blocking operators, data locality, and serializing plans/data across nodes. Triggers on partitioning, repartition, exchange operator, shuffle, query stage, parallel join, distributed aggregate, two-phase aggregation, partition pruning, data parallelism. For replication/consistency and consensus use the distributed-* skills; this is about splitting query work across cores and nodes."
---

# Parallel and Distributed Query Execution

This is about splitting a query's *work* across cores and machines — a
different axis from replicating *data* (see `replication-and-consistency`).
The core mechanism is partitioning plus an exchange operator.

## Data parallelism via partitioning

Split each input into partitions that can be processed independently, then
combine. Partitioning schemes:
- **Hash partitioning** — `hash(key) mod n`; co-locates equal keys, enabling
  parallel joins/aggregates on that key.
- **Range partitioning** — contiguous key ranges; supports parallel sorts
  and range pruning, but risks skew.
- **Round-robin** — even load, but no key locality (only good for scans/
  filters).

**Partition pruning**: use query predicates to skip whole partitions
(e.g., a date filter skips partitions outside the range). Huge win when the
layout matches the query.

## The exchange / repartition operator

The key abstraction. An **exchange** (a.k.a. shuffle/repartition) operator
redistributes rows from M input partitions to N output partitions by some
partitioning function. It is the *only* operator that moves data between
partitions, and therefore it defines **stage boundaries**: the plan splits
into pipelines separated by exchanges.

- **Embarrassingly parallel** operators (scan, filter, project) run
  independently per partition — no exchange needed.
- Operators that combine across keys (join, aggregate, global sort) need an
  exchange to bring matching keys together first.

## Parallel/distributed aggregates and joins

- **Two-phase aggregation**: compute **partial aggregates** locally per
  partition (e.g., partial sums + counts for AVG), exchange by group key,
  then **final-aggregate**. This minimizes data shuffled. Make sure the
  aggregate is decomposable (SUM/COUNT/MIN/MAX trivially; AVG via sum+count;
  DISTINCT/MEDIAN need care).
- **Distributed hash join**: either **co-partition** both inputs on the
  join key (shuffle both, then local hash joins) or **broadcast** the small
  side to every node (no shuffle of the big side). Pick by relative sizes.
  Bloom filters cut shuffle volume (see `join-algorithms`).

## Streaming vs blocking operators

A **streaming** operator emits output as it consumes input (filter,
project, probe side of a hash join). A **blocking** operator must consume
*all* input before producing output (sort, aggregate, hash-join build).
Blocking operators force a materialization point and define stage
boundaries. Knowing which is which is essential for pipelining and for
placing exchanges.

## Distributed concerns

Producing a distributed plan = break the plan into **query stages** at
exchange boundaries, schedule stages across workers, and stream/serialize
intermediate data between them (Arrow IPC/Flight is a natural choice for
columnar data — zero-copy on both ends). Consider **data locality**
(schedule work where the data lives) and **fault tolerance** (re-run a
failed stage vs checkpoint).

## Language notes (C/C++/Rust)

- **Rust**: partitions map to async tasks/streams; an exchange is a set of
  channels (one per output partition) fed by partitioning each input batch.
  Use a work-stealing runtime (Tokio/Rayon) and bound channel capacity for
  back-pressure.
- **C++**: a thread pool with per-partition work items; lock-free queues for
  the exchange. Watch false sharing in per-partition accumulators (pad to
  cache lines).
- Serialize intermediate data with Arrow IPC to keep it zero-copy and
  language-portable across workers.

## Grounding
HQEW *Parallel Query Execution* and *Distributed Query Execution*
(partitioning, exchange, query stages, distributed aggregates/joins,
streaming vs blocking, locality, serialization). DBMS Ch 20 (parallel
algorithms on relations, map-reduce, distributed query processing).

## EDBS grounding & deeper skills
EDBS 2e entries (pull full text with `edbs-reference`: `python3 <edbs-reference>/scripts/edbs.py show "<Entry>"`):
*Parallel Query Processing* (p.2677); *Intra-operator Parallelism* (p.2030); *Data Partitioning* (p.802); *Parallel Hash Join, Parallel Merge Join, Parallel Nested Loops Join* (p.2666); *Execution Skew* (p.1412).
Go deeper with: `parallel-database-systems`, `distributed-dbms-design`.
