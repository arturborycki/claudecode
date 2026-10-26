# Parallel operators: exchange, joins, aggregation, sort, utilities

Principle: parallel operators are the serial algorithms run in many threads or
nodes, glued together by a small number of parallelism mechanisms —
partitioning and pipelining — encapsulated in one operator (exchange). The
serial algorithm needs only minor changes; the correctness burden moves to the
partitioning rule ("every pair of rows that can contribute to a result meets
at exactly one site; every result row is produced exactly once") and to a few
coordination points.

---

## 1. The exchange operator

Names: Exchange (Volcano, Graefe 1990), Table Queue (DB2), River, shuffle
(MapReduce/Spark), RepartitionExec/ShuffleWriter+Reader (DataFusion/Ballista).
It is the only operator that moves data between processes; every other
operator works on local memory or local disk.

Responsibilities:
- spawn/initialize producer and consumer instances and their channels;
  tear them down (startup cost lives here);
- route each row by a partitioning function: hash, range, round-robin,
  broadcast, gather-to-one;
- **flow control** with bounded buffers;
- batch rows into packets/pages to amortize per-message cost;
- optionally preserve order (merging exchange);
- for parallel nested iteration, carry **bindings upstream** (consumer →
  producer: correlation values) as well as results downstream.

### Flow control and slack
Within a thread, iterators are demand-driven (pull) — a good fit for binary
operators. Between threads/nodes, data-driven (push) is usually better. With
flow control, the slower side dictates the rate anyway; what matters is slack:

```
smoothing interval ≈ buffer_bytes / bandwidth
```

i.e. how long the producer may run ahead (or the consumer fall behind) before
blocking. Size exchange buffers from this, not from a fixed row count. The
pipeline may carry records, value packets (runs of equal sort keys), pages,
or whole sorted runs (sort run-generation → merge), plus control records
(e.g. synthetic keys to advance a downstream merge).

### Merging (order-preserving) exchange deadlock
With bounded buffers, producers must send in production order while each
consumer must consume in key order across all producers. Example: producer 1
only has data for consumer 1, producer 2 only for consumer 2; consumer 1
blocks waiting for anything from producer 2 to advance its merge, producer 2
blocks because consumer 2's buffer is full and consumer 2 waits on producer 1
… a cycle.

- Avoidance: producers periodically send **punctuation/dummy records** (current
  low-water key) to *all* consumers so every merge can advance.
- Resolution: detect the stall and **spill** to disk, i.e. temporarily
  unbounded buffers.
- Alternative: avoid merging exchanges — range-partition then sort locally,
  so global order is the concatenation of partitions.

### Nested-iteration exchange
If the outer side runs in 3 threads and the inner subplan in 4 (four on-disk
partitions), naive composition creates 12 inner instances. Decide the inner
DOP explicitly, design the binding/result channels to avoid cycles, and send
**batches of outer correlation values** — cheaper messaging and it lets the
inner plan use set-oriented algorithms instead of per-row probes.

---

## 2. Join distribution strategies

Notation: |R| ≥ |S| bytes, p sites, both inputs partitioned somehow.

| Strategy | What moves | Network (bytes) | Per-site memory for build | Applicable to |
|---|---|---|---|---|
| Co-located (local) | nothing | 0 | |S|/p | equi-join where both sides are aligned on the join key |
| Directed (one-side repartition) | S repartitioned to R's existing partitioning | ≈ |S| (1−1/p) | |S|/p | R already partitioned on join key |
| Repartition both (shuffle hash) | both hashed on join key | ≈ (|R|+|S|)(1−1/p) | |S|/p | equi-joins |
| Broadcast (replicate small) | S to every site; R stays | ≈ (p−1)·|S| | **|S|** | almost all joins incl. non-equi; see outer-join rule |
| Fragment-and-replicate grid | R over rows, copied along row; S over columns, copied along column (r·c = p) | ≈ c·|R| + r·|S| | |S|/c | non-equi / theta joins, cross products |

First-order rule: broadcast beats repartition when `|R|/|S| > p` roughly
(compare the size ratio with the degree of parallelism). Refine with record
counts and widths, per-message and per-byte network cost, available memory per
thread, and whether the result benefits from R keeping its partitioning (a
later join or GROUP BY on R's key). For the grid, traffic is minimized at
`r = sqrt(p·|R|/|S|)`.

**Outer, semi and anti joins.** Broadcasting replicates rows; a replicated row
must not be the one whose *non-match* produces output. So only the
non-preserved operand may be broadcast:
- `R LEFT JOIN S`: broadcast S (each R partition sees all of S) — OK.
  Broadcasting R would emit R's unmatched rows once per site — wrong.
- `R SEMI/ANTI JOIN S`: broadcast S, not R.
- `FULL OUTER`: neither side can be broadcast without a second pass; use
  repartitioning (or broadcast plus a global "matched" bitmap merge, which is
  a distributed protocol, not a free choice).
- UNION ALL has no constraint; UNION/INTERSECT/EXCEPT need co-partitioning on
  all columns (they are duplicate-eliminating equi-matches).

**Cost metric.** Average per-site cost models throughput (multi-user); maximum
per-site cost models elapsed time (single user). An optimizer that uses the
average never sees skew.

> **Beyond EDBS:** Teradata's join geography vocabulary — *local* (same PI),
> *redistribute* by row hash (one or both sides), *duplicate on all AMPs*
> (broadcast), and PRPD (partial redistribution / partial duplication for
> skewed values; Xu et al., SIGMOD 2008, see the skew file). DataFusion
> `HashJoinExec` has `PartitionMode::CollectLeft` (build side collected and
> shared — broadcast) vs `Partitioned` (both sides hash-repartitioned); Spark
> picks broadcast below `spark.sql.autoBroadcastJoinThreshold` and, with AQE,
> can switch to broadcast at run time once actual sizes are known.
> Track join (Polychroniou, Sen, Ross, SIGMOD 2014) decides per key where to
> join, minimizing network traffic for each key individually.

---

## 3. Parallel hash join

```
parallel_hash_join(R build, S probe, key k, p sites):
  phase 1 (build, blocking):
    every R producer: route r to site bucket(h1(r.k))      # h1: partition hash
                      set bit h_bv(r.k) in local bit-vector
    every site i:     insert arriving r into hash table keyed by h2(r.k)  # h2 independent of h1
    OR bit-vectors from all sites -> global filter; ship to S producers
  barrier: all builds complete (and all sites agree on in-memory vs Grace/hybrid)
  phase 2 (probe, pipelined):
    every S producer: drop s if bit h_bv(s.k) unset        # before sending: saves network
                      route s to site bucket(h1(s.k))
    every site i:     probe, emit matches
```

- Measured on Gamma by Schneider & DeWitt (SIGMOD 1989: sort-merge, simple,
  Grace and hybrid hash; hybrid hash generally fastest, hash variants
  degrade under join-attribute skew).
- Overflow handling per site: **simple** hash (one pass, rescan on overflow),
  **Grace** (partition everything into spill buckets first, then join bucket
  by bucket; Kitsuregawa, Tanaka, Moto-oka 1983), **hybrid** (keep bucket 0 in
  memory during partitioning, join it immediately; DeWitt et al. 1984,
  Shapiro 1986). Cost per site for hybrid with memory M and build |S_i| ≈
  `(|R_i| + |S_i|)·(1 − q)·2` extra I/O, where q is the fraction of the build
  kept resident.
- **Coordination point**: sites may want different overflow strategies
  (different data volumes). If the surrounding schedule depends on the
  strategy (e.g. when a downstream operator can start, how much memory is
  released), all sites must agree — a brief decision round after the build.
- If network transfer is faster than local disk, overflow partitions can be
  shipped toward their final destination instead of spilled locally.
- Bit-vector (Bloom) filtering is most natural for hash join because build
  precedes probe. Keep min/max of the build keys too — they become range
  predicates that can prune the probe-side scan (zone maps, partitions).
- **Pipelined hash joins in right-deep trees**: all builds proceed
  (independently) then the probe stream flows through every hash table — high
  parallelism but every hash table resident at once. Left-deep trees keep only
  ~two tables resident but give little parallelism. See
  `parallel-optimization-and-scheduling.md` §4.

> **Beyond EDBS:** The symmetric (pipelining) hash join (Wilschut & Apers,
> 1991) builds tables on both inputs and probes the opposite one per arriving
> row, so neither input blocks — useful for streaming and for exchanges whose
> sizes are unknown, at double memory. Intra-node, radix-partitioned hash
> joins (Balkesen et al., ICDE 2013) partition into cache-sized pieces first;
> distributed engines often do node-level hash repartitioning followed by
> local radix partitioning, which is the same Grace idea one level down.

---

## 4. Parallel sort and sort-merge join

Parallel sort:
1. Choose p−1 **splitters** by sampling (quantiles; oversample by a factor
   like 10–100× p, or use per-producer histograms merged at a coordinator).
2. Range-repartition by splitters.
3. Sort locally; partitions are independent. Global order = concatenation.
Alternative: sort locally first, then a merging exchange (order-preserving
gather) — needs no splitters, but the final merge is serial and the
merging exchange can deadlock (§1).

**Halloween protection by phase separation.** If the optimizer relies on a
sort being a full materialization barrier (to stop an update from seeing its
own effects), *all* sort threads must finish consuming input before *any*
emits output — otherwise one thread's output could modify another thread's
still-pending input. Implement as a barrier across instances.

Parallel merge join: range-partition both inputs with the **same splitters**,
sort locally, merge locally; or hash-partition both and sort locally (order
then is per-partition only). Bit-vector filters help merge join when one
input's filter can be completed before the other input's stop-and-go step
(its sort), and pay most when the other input must also be sorted (expensive
work avoided for filtered rows).

---

## 5. Parallel (index) nested loops

- Naive parallel nested loops failed historically: brute force does not beat a
  well-chosen index, persistent (index NL) or temporary (hash table).
- **Parallel index NL**: route each outer row to the site that owns the
  matching index partition (when the index is partitioned on the join key),
  or broadcast outer rows to all index partitions (global index on another
  key). Batch outer bindings (§1).
- Non-equi conditions: fragment-and-replicate grid (§2) or broadcast the
  smaller side.

---

## 6. Parallel aggregation and duplicate elimination

### Strategies
| Strategy | Steps | Wins when | Risk |
|---|---|---|---|
| Repartition-only | hash-repartition rows on group key → aggregate locally | few rows per group (G ≈ N) | ships every row |
| Local/global (two-phase) | aggregate locally → repartition partial states on group key → final aggregate | average group size N/G > p | wasted CPU/memory if groups barely shrink |
| Centralized merge | local aggregate → gather all partials to one site | tiny G (scalar aggregates) | serial final step |
| Already partitioned on group key | aggregate locally only | input partitioning ⊇ group key | must prove the property (§ optimization) |

Why `N/G > p`: with rows spread randomly, each site's local aggregation
emits up to `min(N/p, G)` partials; total shipped ≈ `p·G` vs `N` for
repartition-only. Local aggregation reduces traffic iff `p·G < N`.

Local phase variants:
- **Opportunistic**: aggregate what fits in memory; when the table is full,
  flush partials downstream (or switch to pass-through). No spill.
- **Complete**: spill overflow partitions to local disk and finish locally;
  ships exactly one partial per (site, group).
- Sort-based analogues: opportunistic = run generation with early duplicate
  removal before shipping; complete = full local sort + aggregation.

> **Beyond EDBS:** Adaptive parallel aggregation (Shatdal & Naughton, SIGMOD
> 1995) monitors the local reduction ratio and switches between two-phase and
> repartition. Most modern engines implement "partial aggregation with
> pass-through": skip local aggregation when the observed reduction ratio
> falls below a threshold. DataFusion expresses this as
> `AggregateExec(Partial) → RepartitionExec(Hash) → AggregateExec(FinalPartitioned)`
> and DuckDB as per-thread local hash tables merged into radix-partitioned
> global state.

### Correctness of partial states
- Decomposable: SUM, COUNT, MIN, MAX; AVG via (sum, count); variance via
  (n, mean, M2) with Chan's merge.
- Not decomposable as values: MEDIAN/percentiles (ship sketches or values),
  COUNT(DISTINCT x) (repartition on (g, x) to deduplicate, then count by g;
  or HyperLogLog sketches), ordered-set and user-defined aggregates without a
  merge function.
- SUM over integers in parallel must use the same overflow semantics as
  serial; float SUM is order-dependent — tests must compare with tolerance or
  fix the combine order.
- NULL group keys form one group; must hash to one site.

### Top-N
Local top-N per site + global merge massively cuts traffic, but the final
selection is serial. Grouped top-N ("top 3 per region") parallelizes fully by
partitioning on the group.

### Window functions (not covered by EDBS; practical note)
`OVER (PARTITION BY k …)` → repartition on k then sort within partition; no
PARTITION BY → effectively serial, or range-partition on the ORDER BY key and
carry boundary state between neighbours.

---

## 7. Set operations, semijoin reduction, index operations

- Intersection/union/difference of RID lists (index ANDing/ORing for
  conjunctive/disjunctive predicates), index joins (join two indexes before
  fetching rows; or join several indexes of one table to cover a query), and
  star joins all are matching operations and parallelize like joins — locally
  if all indexes of a table are partitioned like the table.
- Semijoin reduction (ship join keys, ship back matches) or its cheap
  approximation, bit-vector filtering, applies to every join algorithm and
  every matching operation.

---

## 8. Parallelism beyond queries

- Large updates (bulk load/roll-in, bulk delete/roll-out) must run in parallel
  in shared-nothing systems because, like filters, they execute where the data
  lives.
- Parallelize by stored partition, by disjoint B-tree key ranges, or by index
  (index-by-index maintenance: sort the changes per index, then apply in key
  order with read-ahead).
- Constraint verification, materialized/indexed view maintenance, view
  creation and recomputation reuse query parallelism.
- **Index creation** is arguably the most important parallel operation for
  growing databases (scan, sort, build all parallelize), especially without
  online index build.
- Local concurrency inside an operator: async read-ahead/write-behind, and
  multi-threaded phases inside one sort (fill workspace, sort pointer arrays,
  write runs).

---

## 9. Implementation checklist for the exchange and operators

- Exchange buffers bounded in bytes; credit-based flow control; batching to
  ≥ tens of KB per message; separate control channel for EOS, punctuation,
  cancellation, and bit-vector broadcast.
- Partition function is a pure function of (canonical key bytes, seed, bucket
  map version); version mismatches between producer and consumer must fail
  loudly.
- End-of-stream: consumer completes only when *every* producer has sent EOS;
  count producers explicitly (a producer with no rows still sends EOS).
- Hash tables use a hash seed independent of the partition hash.
- Every operator instance reports rows/bytes in and out and busy time — the
  raw material for skew detection and DOP tuning.

---

Sources: Parallel Query Execution Algorithms (p.2668); Parallel Hash Join,
Parallel Merge Join, Parallel Nested Loops Join (p.2666); Parallel Query
Optimization (p.2674); Parallel Query Processing (p.2677); Operator-Level
Parallelism (p.2601); Intra-operator Parallelism (p.2030); Big Data
Platforms for Data Analytics (p.268); MapReduce (p.2206).
