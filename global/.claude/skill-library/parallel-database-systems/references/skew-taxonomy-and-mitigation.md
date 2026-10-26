# Skew: taxonomy, quantification and mitigation

A group of concurrent tasks finishes when its slowest member finishes. Skew is therefore not a tuning detail: it is the dominant reason
real parallel plans miss linear speedup, and it compounds as it flows up a
plan.

---

## 1. Vocabulary

- **Data skew**: non-uniform distribution of values in a dataset (Zipfian is
  the usual model; Gaussian, Poisson, self-similar also used). Real data is
  skewed (Lynch, VLDB 1988, measured it in bibliographic databases).
- **Execution skew**: concurrently running operator instances take very
  different times, leaving processors idle. Causes: data skew, *or*
  resources temporarily unavailable to one instance (a slow disk, a
  co-tenant, GC, a throttled VM, a hot NIC). Appears in both intra-operator
  parallelism (instances of one operator) and operator-level parallelism
  (stages of a pipeline).
- **Processing skew** (warehouse literature): uneven work despite even data —
  predicate cost, UDF cost, decompression variance — often seeded by data
  skew at the leaves.

---

## 2. Walton–Dale–Jenevin taxonomy (VLDB 1991)

Intrinsic skew lives in the data; partition skew is created by the parallel
implementation even when the data is uniform.

| Type | Kind | Where it arises | Typical signal | Primary mitigations |
|---|---|---|---|---|
| **AVS** attribute-value skew | intrinsic | some values far more frequent (more citizens in Paris than in Waterloo) | high top-k frequency in column stats | everything below; choose partition keys with high distinct count |
| **TPS** tuple-placement skew | partition | initial declustering (range boundaries off, time-ordered inserts, heavy hash key) | uneven base-partition sizes | more buckets, rebalancing, split oversized partitions, round-robin for scan-only tables |
| **SS** selectivity skew | partition | a selection keeps different fractions per site (filter correlated with placement key) | even input, uneven output per scan instance | re-shuffle (round-robin) after filtering before expensive work; partition on a key uncorrelated with common filters |
| **RS** redistribution skew | partition | an exchange sends uneven volumes to consumers (bad hash/range split, heavy key) | uneven rows received per consumer | sampling-based range splitters, virtual processors, heavy-key special handling |
| **JPS** join-product skew | partition | join output per site differs (matching heavy keys meet on one site) | even inputs per site, wildly uneven outputs | split the heavy key across sites while replicating its partner rows; skew-aware join algorithms |

### Propagation: skew compounds up the plan
Consider `σ(R) ⋈ S ⋈ T` with DOPs 2, 3, 2, run as one pipeline:

```
          ⋈T  inst1 ████████████          <- uneven left input (inherited)
              inst2 ███
           ^
          ⋈S  inst1 ██████   inst2 ████████████   inst3 ██    <- RS + SS in, AVS/TPS of S, JPS out
           ^
          σR  inst1 ████████  inst2 ███                      <- AVS/TPS of R
```

Even if T is perfectly partitioned, the T-join instances inherit the uneven
output of the S-join. Static (compile-time) balancing cannot anticipate the
combined effect; it takes run-time measurement.

---

## 3. Quantifying skew

- Skew factor of an operator: `σ = max_i(t_i) / mean_i(t_i)`; efficiency
  `= 1/σ`. Measure on rows, bytes and busy time separately — they diverge
  (wide rows, expensive predicates).
- Ceiling from a single heavy value with fraction `f` of the rows when
  partitioning *by that value*: speedup ≤ `1/f` for any p.
- Zipf worked example: D distinct values, exponent θ = 1. Top value frequency
  `f₁ = 1/H_D` with `H_D ≈ ln D + 0.577`. For D = 10⁶: `H ≈ 14.4`, so
  `f₁ ≈ 7%`. Hash-partitioning on this column caps speedup near **14×**, no
  matter how many nodes. With θ < 1 the cap rises quickly; with θ > 1 it falls.
- Join output under AVS on both sides: a key with `a` rows in R and `b` in S
  produces `a·b` rows on one site. Two heavy hitters can make one site's output
  exceed the whole rest of the join.

---

## 4. Mitigation catalogue

### 4.1 At placement time
- Hash on high-cardinality keys; reserve range partitioning for pruning
  *within* a node (two-level scheme) when filters correlate with the key.
- Many logical buckets per node so oversized buckets can be split or moved.
- Further fragment oversized range partitions.
- Round-robin/random placement for tables that are only scanned and
  repartitioned anyway (no TPS, no co-location benefit lost).

### 4.2 Sampling-based range partitioning (DeWitt, Naughton, Schneider, Seshadri, VLDB 1992)
For a parallel hash join under RS on the build relation:
1. **Sample** the build relation; build a histogram of join-key values.
2. Choose ranges with equal numbers of build tuples (equi-depth).
3. Redistribute the build relation by those ranges; each site builds a hash
   table.
4. Redistribute the probe relation with the *same* ranges; probe.

Sampling also picks the algorithm (normal vs skew-handling) and which relation
should build. The sample can be tiny relative to the data; its cost is a
startup term.

A single value heavier than `1/p` of the build cannot be balanced by ranges
alone (one value, one range). Handle it explicitly:

> **Beyond EDBS:** The same paper's family includes *weighted range
> partitioning* (a heavy value's range is split across several sites, with
> the matching rows of the other relation replicated to all of them — often
> called subset-replicate) and *virtual-processor partitioning* (§4.3). The
> general principle: for a heavy key, **partition one side's rows of that key
> across k sites and replicate the other side's rows of that key to those k
> sites**. Choose the side with more rows of that key to be partitioned.

### 4.3 Virtual processors / many small partitions
Partition into `k·p` partitions (k ≫ 1), measure their sizes, then assign
partitions to real processors with greedy LPT bin-packing (largest first to
least loaded). Max load ≤ mean + largest partition, so splitting finely
bounds imbalance — except for single heavy values.

- **Bucket spreading** (Kitsuregawa & Ogawa, VLDB 1990, Super Database
  Computer): during repartitioning each hash bucket is itself spread evenly
  over all processors; after sizes are known, buckets are gathered to
  processors so that per-processor load is balanced (bucket tuning).
- Teradata AMPs are virtual processors in exactly this sense: many AMPs per
  node, a node's resources pooled among its AMPs.

### 4.4 Adaptive run-time reallocation
- Detect oversized partitions and repartition them across processors already
  assigned to the operator.
- **Control operators** inserted into the plan compare estimated and actual
  intermediate sizes; past a threshold they trigger redistribution to
  pre-empt RS and JPS, and can change the operator's DOP (Brunie & Kosch,
  SIGMOD Record 1996).
- A **scheduling step** inside the join that redistributes load once
  partition sizes are known (Wolf, Dias, Yu, Turek, TKDE 1994).

### 4.5 Dynamic processing / work stealing (Bouganim, Florescu, Valduriez, VLDB 1996)
For hierarchical machines (shared-nothing of SMP nodes): decompose the query
into small self-contained units of sequential work ("activations") that any
processor can execute. Processors move **horizontally** (other instances of
the same operator — intra-operator balancing) and **vertically** (other
operators of the plan — inter-operator balancing). Steal inside the node
first (no communication), across nodes only when the node runs dry.

> **Beyond EDBS:** Morsel-driven scheduling (Leis et al., SIGMOD 2014) is the
> modern intra-node form of the same idea and is what DuckDB does. Across
> nodes, the remaining problem is inter-node RS/JPS, which work stealing
> cannot fix without moving data — hence the skew-aware joins below.

### 4.6 Skew-aware join algorithms (Beyond EDBS)
> - **PRPD** — partial redistribution, partial duplication (Xu, Kostamaa,
>   Zhou, Chen, SIGMOD 2008; Teradata): rows of R with known heavy keys stay
>   where they are (not redistributed); matching S rows for those keys are
>   *duplicated* to all sites; all other rows are hash-redistributed
>   normally. Heavy keys come from statistics or are detected at run time.
> - **Flow-Join** (Rödiger et al., ICDE 2016): detects heavy hitters with a
>   sketch during the initial part of the shuffle and switches those keys to
>   a selective broadcast on the fly.
> - **Spark AQE skew join** (Spark 3.0+): after the shuffle map stage, splits
>   oversized reducer partitions into sub-partitions and replicates the
>   matching partition of the other side to each — the subset-replicate idea
>   driven by actual shuffle statistics.
> - Build-side heavy keys also hurt the *local* hash table (long chains, one
>   giant bucket that cannot be split by recursive partitioning). Prefer the
>   heavy side as probe; for recursive Grace partitioning, detect a partition
>   that does not shrink after re-hashing and fall back to nested-loops or
>   sort for that key.

### 4.7 Selectivity skew specifically
When placement is by date and the query filters the last day, one node does
all the work. Options: two-level placement (hash across nodes, range within
node), or insert a round-robin exchange right after the selective scan so the
expensive downstream operators are balanced (pays one shuffle of the
*filtered* data).

### 4.8 Resource-induced execution skew (stragglers)
- **Backup / speculative tasks**: run a second copy of a slow task, take
  whichever finishes first (MapReduce, Spark) — needs deterministic,
  side-effect-free tasks and materialized or replayable inputs.
- **Partial results**: Dremel can return an answer once most of the tree has
  reported, bounding tail latency for approximate-tolerant queries.
- **Re-split remaining work** of a straggler (SkewTune, Kwon et al., SIGMOD
  2012 — Beyond EDBS).
- In pipelines: give the slowest stage more intra-operator parallelism so
  stage rates match (see rate matching in `parallel-optimization-and-scheduling.md`).

---

## 5. Instrumentation and detection

- Every exchange consumer counts rows and bytes received per producer; every
  operator instance records busy vs blocked time. Skew alarms on
  `max/mean > threshold` per operator.
- Collect **heavy hitters** cheaply in the exchange producers (Space-Saving or
  Misra–Gries with k counters; Count-Min for frequency estimates) — this
  feeds run-time PRPD/Flow-Join-style switching.
- Optimizer statistics: most-common-value lists and equi-depth histograms on
  distribution and join keys; join-key MCV lists on *both* sides predict JPS
  (product of matching frequencies).
- EXPLAIN ANALYZE output must show per-instance min/median/max, not only
  totals — totals hide skew by construction.

---

## 6. Test data and adversarial cases

- Zipf generators with θ ∈ {0, 0.5, 1, 1.5} (Gray's DBGen-style synthetic
  generators support Zipf, Poisson, Gaussian).
- Single-value join key (all rows equal) on build, on probe, on both (JPS
  worst case: |R|·|S| output on one site).
- All-NULL keys (must not all land on one site *and* must still be grouped
  correctly for GROUP BY / outer join).
- Time-ordered inserts with range placement (TPS drift).
- Filter correlated with the partition key (SS).
- One slow node (inject latency/CPU throttling) to test straggler handling
  separately from data skew.
- Oracle: results must be identical to serial execution for every skew
  scenario; performance assertion: max/mean per operator below a bound for
  skew-handling plans.

---

Sources: Data Skew (p.849); Execution Skew (p.1412); Query Load Balancing in
Parallel Database Systems (p.3004); Operator-Level Parallelism (p.2601);
Parallel and Distributed Data Warehouses (p.2644); Parallel Data Placement
(p.2661); Parallel Query Execution Algorithms (p.2668); Big Data Platforms
for Data Analytics (p.268); MapReduce (p.2206).
