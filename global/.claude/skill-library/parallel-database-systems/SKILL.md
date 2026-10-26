---
name: parallel-database-systems
description: "Use when designing, implementing or reviewing a parallel/MPP database engine: shared-nothing vs shared-disk vs shared-memory, data placement and declustering, speedup/scaleup limits, inter-/intra-operator parallelism, broadcast vs repartition vs co-located joins, local/global aggregation, parallel optimization and DOP, skew handling and load balancing, database clusters, elasticity, MapReduce and SQL-on-Hadoop lineage. Triggers on MPP, shared-nothing, declustering, distribution key, hash map, AMP, virtual processor, range partitioning, chained declustering, speedup, scaleup, data skew, redistribution skew, join product skew, broadcast join, repartition join, co-located join, PRPD, two-phase aggregation, degree of parallelism, exchange operator, bushy plan, work stealing, virtual partitioning, Hive, Impala, Spark SQL. Apply even when phrased as 'adding nodes does not help', 'one worker is always last', or 'how should we distribute this table'."
---

# Parallel Database Systems

This skill owns the *MPP engineering* layer: how data is declustered across
nodes, which parallel algorithm runs each operator, how the optimizer picks
partitionings and degrees of parallelism, and how the system stays balanced,
elastic and available. The single most important idea: **elapsed time is the
maximum over instances, not the average** — placement, data movement and
balance are one problem, and skew is the default, not the exception.

## Mental model

- Parallel plan = serial operators + partitioning + pipelining, glued by the
  exchange operator. Correctness lives in the partitioning rule; performance
  in the slowest instance.
- Levers by leverage: **placement** (what is already co-located), **movement**
  (what each exchange ships), **balance** (how evenly work lands).
- Speedup barriers: startup, interference, skew. Parallelism buys response
  time with extra total work.
- Two levels: morsel/work-stealing inside a node (DuckDB, HyPer), exchange
  across nodes.

## Core invariants

1. **Meet exactly once.** For every binary matching operator, each pair of
   rows that can contribute to a result meets at exactly one site, and each
   result row is emitted exactly once. Test: multiset(parallel) ==
   multiset(serial) for DOP ∈ {1, 2, 3, 7, 64} and every distribution strategy.
2. **Canonical hashing.** Equal SQL values map to the same bucket in loader,
   storage and executor (integer widths, DECIMAL scale, collation, padding,
   `-0.0`, NULL policy). Test: cross-type equal-value pairs co-locate.
3. **Location independence.** Plans reference logical buckets/partitions,
   never node ids; the bucket→node map is versioned and a producer/consumer
   version mismatch fails loudly.
4. **Stream completion.** A consumer finishes only after EOS from every
   producer, including zero-row producers; cancellation reaches all instances.
5. **Broadcast safety.** Only the non-preserved operand of an outer, semi or
   anti join may be replicated; FULL OUTER needs repartitioning.
6. **Partial-state algebra.** Every partial aggregate has a merge that is
   associative and commutative; final(merge(partials)) == serial aggregate
   (float within tolerance, integer overflow semantics identical).
7. **Property satisfaction.** Each input satisfies its required distribution
   (hash on a non-empty subset of join/group keys with the same function and
   bucket count, or replicated/singleton); asserted in plan validation.
8. **No exchange deadlock.** Order-preserving (merging) exchanges with bounded
   buffers either send punctuation to all consumers or spill.
9. **Agreed decisions.** Choices other operators' scheduling depends on (sort
   phase separation, in-memory vs Grace/hybrid) are identical on all instances.
10. **Independent hash levels.** Partition hash, spill-partition hash and
    hash-table slot hash use different seeds/bits.
11. **Bounded failover load.** After one node failure the max per-node load
    factor matches the design (mirroring 2×; chained `1 + 1/(n−1)`).

## Design space & trade-offs

| Architecture | Wins when | Cost / risk |
|---|---|---|
| Shared-memory | one box, dynamic balancing, simple code | memory bandwidth, tens of cores, single failure domain |
| Shared-disk | easy migration, any node reads any page | cache coherence (DLM), shared storage bottleneck |
| Shared-nothing (MPP) | hundreds–thousands of nodes, cheap scale-out | placement-driven balance, reorganization on growth |
| Hierarchical / disaggregated storage | modern default | two-level balancing; cache affinity replaces ownership |

| Placement | Wins when | Cost / risk |
|---|---|---|
| Hash on key | exact-match routing, co-located joins/aggregates | duplicate-key skew; range queries hit all nodes |
| Range | range pruning, ordered output | TPS drift, needs quantiles, selectivity skew |
| Round-robin / random | scan-only tables, perfect balance | every query hits every node, no co-location |
| Replicate small table | dimensions, lookups | storage and write fan-out |
| Hashed small ranges / two-level | mix of small and large range queries | more metadata, planner must understand it |
| Virtual partitioning over replicas | black-box per-node DBMS, skew-resistant | P× storage, needs clustering on VP key |

| Join strategy | Wins when | Cost / risk |
|---|---|---|
| Co-located | aligned distribution on join key | requires design-time alignment |
| Directed (move one side) | one side already partitioned on key | — |
| Repartition both | large-large equi-join | ships ≈ both inputs; RS/JPS exposure |
| Broadcast small side | `|R|/|S| > p` (first approximation) | per-node memory = whole S; outer-join restriction |
| Grid fragment-replicate | non-equi joins | ships `c·|R| + r·|S|` |
| Skew-aware (PRPD, subset-replicate) | heavy keys known or detected | heavy-key detection, extra plan complexity |

| Exchange mode | Wins when | Cost / risk |
|---|---|---|
| Pipelined (push) | interactive latency | whole-query restart on failure; flow-control deadlocks |
| Materialized shuffle (pull) | stage retry, re-optimization, elasticity | latency and I/O on every run |

## Algorithms that matter

```
speedup S(p)=T(1,D)/T(p,D); scaleup U(p)=T(1,D)/T(p,p·D)
T(p) ≈ W/p + c·p  ->  p* = sqrt(W/c)          # startup-optimal DOP
heavy value with fraction f  ->  S(p) ≤ 1/f    # Zipf θ=1, D=1e6: f≈7%, cap ≈14x

join placement:
  if aligned(R,S,key): local
  elif partitioned_on(R,key): move S
  elif |R|/|S| > p and S not preserved side: broadcast S
  elif heavy_keys(R,S): PRPD / subset-replicate for heavy keys, hash the rest
  else: repartition both on key

parallel hash join: route build by h1 -> build local table with h2 -> OR bit-vectors
  -> ship filter to probe producers -> filter before sending -> route probe by h1 -> probe
two-phase aggregation: local agg (opportunistic or complete) -> hash on group key -> final
  beneficial iff N/G > p ; switch to pass-through when observed reduction is low
sampled range partitioning: sample -> equi-depth splitters -> range-route build and probe
virtual processors: k·p partitions -> greedy LPT to least-loaded processor
  makespan ≤ mean + largest partition (single heavy value still needs splitting)
```

## Failure modes & classic bugs

- **Non-canonical hashing** (INT vs BIGINT, collation): matching rows land on
  different nodes, join silently loses rows. Detect with cross-type
  co-location tests and a debug mode that re-checks probe misses globally.
- **Broadcasting the preserved side** of LEFT/SEMI/ANTI: duplicated output.
- **Averaging averages**; merging MEDIAN/COUNT DISTINCT as values.
- **Same hash bits for partitioning and hash table**: each node's table uses
  1/p of its slots — looks like skew, is a bug.
- **`hash mod n` placement**: adding one node moves almost all data.
- **Skew-blind costing**: mean partition size in the cost model; EXPLAIN
  totals look fine while one instance runs 10× longer.
- **Selectivity skew**: range-distributed by date, queries hit recent dates.
- **Join product skew**: balanced inputs, one site's output explodes.
- **Merging-exchange deadlock** with bounded buffers; appears only at some
  DOPs and distributions.
- **Missing EOS from empty producers**: hangs on highly selective filters.
- **Over-parallelized small queries**: startup dominates; throughput collapses
  under concurrency. **Rounded DOPs** starve the bottleneck stage.
- **Right-deep plans over memory**: every hash table resident, mass spilling.
- **Failover hot spot**: mirrored backup doubles one node's load.

## Implementation checklist (C/C++/Rust)

- `Partitioning` enum (Hash{keys, n, seed, map_version} | Range{keys,
  splitters} | RoundRobin | Replicated | Singleton | Any) with
  `satisfies(required, eq_classes)` implementing the subset rule.
- One canonical key encoder shared by loader, storage and executor; hash
  normalized bytes with fixed seeds; explicit NULL policy.
- Logical buckets (≫ nodes) + versioned bucket→node map resolved at stage
  start.
- Exchange: per-destination batch builders (Arrow batches / column vectors),
  byte-bounded credit-based channels (Rust bounded `tokio::mpsc`/crossbeam;
  C++ lock-free MPSC rings), control channel for EOS, punctuation, bloom
  filters, cancel; producer count tracked per consumer.
- Vectorized partitioning: hash a batch, compute destinations, scatter via
  selection vectors; no per-row allocation.
- Per-instance metrics (rows/bytes in/out, busy/blocked, spill) and a
  Space-Saving heavy-hitter sketch in producers.
- Aggregates expose `update / merge / finalize` with serializable state, and a
  pass-through mode for low-reduction partial aggregation.
- Hash-join build takes a scheduler memory grant before choosing in-memory vs
  hybrid; coordinated decision when downstream scheduling depends on it;
  recursion guard and fallback for unsplittable heavy keys.
- Cache-line-padded per-thread accumulators; NUMA-local morsels in a node.

## How to test it

- **Differential oracle**: serial vs several DOPs and forced strategies
  (co-located / broadcast / repartition / skew-split); compare multisets.
- **Property tests**: random data, partitionings and plans; enforcer insertion
  must always produce a valid plan.
- **Adversarial data**: Zipf θ ∈ {0, 0.5, 1, 1.5}; single-value keys on build,
  probe, both; all-NULL keys; time-ordered inserts with range placement;
  filters correlated with the distribution key.
- **Faults**: kill a node mid-exchange, delay one producer, zero-row
  producers, cancellation storms — no hangs, identical results after retry.
- **Scaling**: speedup/scaleup curves to 64+ instances with per-instance skew
  factor; small queries must pick low DOP.
- **Rebalance**: add/remove a node between queries; only reassigned buckets
  move; cached plans still run.

## Expert review questions

1. Distribution key of each large table: distinct count, top-k frequency, and
   the speedup cap the top value implies?
2. Which top-workload joins are co-located, which shuffle every time?
3. How do loader, storage and executor prove they hash identically for every
   type?
4. What moves when a node is added or removed; do compiled plans survive?
5. Does the cost model use mean or max partition, and where do heavy-key
   statistics come from?
6. Which decisions switch at run time (broadcast vs shuffle, partial-agg
   pass-through, skew split), and on what trigger?
7. How is DOP chosen per pipeline; what stops a 10 ms query fanning out to 500
   instances?
8. Which exchanges preserve order, and how is deadlock avoided?
9. Who grants memory to concurrent hash tables in bushy/right-deep plans?
10. Pipelined or materialized shuffles — is the recovery unit query, stage or
    task?
11. Worst per-node load factor after a node failure?
12. Can EXPLAIN ANALYZE show per-instance min/median/max for every operator?

## Go deeper

- `references/architecture-and-scaling.md` — shared-* trade-offs, speedup and
  barriers, parallelism taxonomy, database clusters, elasticity, failover
  placement, online recovery.
- `references/placement-and-declustering.md` — partitioning strategies, hash
  engineering, hybrid/multi-attribute declustering, aligned and derived
  partitioning, warehouse design, virtual partitioning. Read before choosing
  distribution keys.
- `references/parallel-operators-join-aggregate.md` — exchange semantics, join
  strategies with cost formulas, parallel hash/merge/NL joins, aggregation,
  sort, top-N, utilities. Read when implementing an operator.
- `references/skew-taxonomy-and-mitigation.md` — AVS/TPS/SS/RS/JPS, sampling,
  virtual processors, adaptive reallocation, work stealing, PRPD/AQE,
  stragglers. Read when one instance is always last.
- `references/parallel-optimization-and-scheduling.md` — partitioning
  property, one- vs two-phase optimization, tree shapes, costing, DOP,
  processor/memory allocation, adaptive re-optimization.
- `references/mapreduce-and-sql-on-big-data.md` — dataflow platforms,
  MapReduce internals, Hive/Impala/Big SQL/Spark SQL, lessons for a modern
  engine.
- `references/edbs-entries.md` — all cluster entries with printed pages.

## Related skills

- `parallel-distributed-execution` — exchange/stage basics; this skill adds MPP placement, skew, optimization depth.
- `join-algorithms` — serial join internals; here their partitioned/broadcast forms.
- `query-optimizer`, `query-plan-design` — serial optimization; here the partitioning property and DOP.
- `replication-and-consistency`, `distributed-transactions`, `distributed-consensus` — protocols; here only replica placement.
- `columnar-arrow-layout`, `query-engine-testing` — exchange payload formats; test harness patterns.
- `dbms-architecture` — single-node process/thread model.
- `query-execution-advanced` — vectorized/compiled execution and morsel scheduling inside a node.
- `cardinality-and-statistics` — histograms, MCVs and sketches that feed skew-aware costing.
- `distributed-dbms-design` — geo-distributed fragmentation/allocation and semijoin strategies (not MPP).
- `replication-protocols` — eager/lazy and middleware replication behind clusters and online recovery.
- `olap-and-warehouse-engines` — star joins, cubes, columnar warehouses built on this layer.
- `stream-processing-engines` — continuous dataflow, partitioned state, backpressure.
- `tuning-and-benchmarking` — speedup/scaleup methodology, TPC-H/SSB.
- `recovery-and-durability`, `concurrency-control-theory` — per-node recovery, isolation under inter-query parallelism.
- `storage-devices-and-io` — device-level declustering (RAID), I/O bandwidth.
- `edbs-reference` — pull full EDBS entries.

## Grounding

EDBS (printed pages): Big Data Platforms for Data Analytics 268; Data
Partitioning 802; Data Skew 849; Database Clusters 940; Database Machine 956;
Elasticity 1269; Execution Skew 1412; Inter-operator Parallelism 2028;
Inter-query Parallelism 2029; Intra-operator Parallelism 2030; Intra-query
Parallelism 2030; MapReduce 2206; Online Recovery in Parallel Database
Systems 2564; Operator-Level Parallelism 2601; Parallel and Distributed Data
Warehouses 2644; Parallel Data Placement 2661; Parallel Database Management
2663; Parallel Hash Join, Parallel Merge Join, Parallel Nested Loops Join
2666; Parallel Query Execution Algorithms 2668; Parallel Query Optimization
2674; Parallel Query Processing 2677; Query Load Balancing in Parallel
Database Systems 3004; Shared-Disk 3484; Shared-Memory 3485; Shared-Nothing
3486; SQL Analytics on Big Data 3675; Virtual Partitioning 4462.

Seminal: DeWitt & Gray CACM 1992; Gamma; GRACE; Teradata (Neches 1985,
Ballinger & Fryer 1997); Bubba placement (Copeland et al. 1988); Volcano
exchange (Graefe 1990); Graefe survey (1993); Walton–Dale–Jenevin (1991);
DeWitt et al. practical skew handling (1992); Kitsuregawa & Ogawa (1990);
Mehta & DeWitt (1995, 1997); Bouganim et al. (1996); MapReduce (2004); Pavlo
et al. (2009). Beyond EDBS (flagged in references): morsel-driven
parallelism (Leis et al. 2014), PRPD (Xu et al. 2008), Flow-Join (2016),
Spark AQE, DataFusion distribution enforcement.
