# Sort, aggregation, duplicate elimination, set operations — and cache-conscious operator design

Scope: the non-join relational operators the executor spends most of its time
in, their external-memory variants, the sort/hash duality, hybrid hashing as
it applies beyond joins, and the hardware-conscious techniques (blocking,
partitioning, prefetching, buffering) that decide in-memory performance.
Join algorithms themselves are in `join-algorithms`; this file adds what that
catalogue omits.

---

## 1. Selection and projection

- **Selection:** scan + predicate, or an index path (see
  `access-paths-and-reducers.md`). Evaluate cheap, selective conjuncts first;
  in vectorized engines, evaluate conjuncts as successive refinements of a
  selection vector so later conjuncts touch only surviving rows.
- **Projection without dedup** is pipelined: drop columns, compute
  expressions on the fly. **Projection with dedup (SQL DISTINCT)** is
  duplicate elimination (section 4).

---

## 2. External merge sort

### Phase 1 — run generation

| Method | Run length | Notes |
|---|---|---|
| Load-sort-store (quicksort M pages) | M | Simple, cache-friendly if done on (key prefix, pointer) pairs |
| Replacement selection (heap of M pages) | ~2M on random input; one run on presorted input; M on reverse-sorted | Streams output while reading; worse cache behaviour (heap) |
| Cache-sized mini-runs then in-memory merge (AlphaSort) | M | Quicksort cache-sized blocks of (key-prefix, pointer), merge them; Nyberg et al., VLDB J 1995 |

### Phase 2 — merging

Fan-in F ≤ M − 1 (one output buffer), lower with double buffering or
forecasting. Number of merge passes = ⌈log_F(#runs)⌉; total I/O ≈
2·B·(1 + merge passes) if the final output is written, ≈ 2·B·(merge passes)
+ B if the final merge streams to the consumer. **Always pipeline the final
merge into the parent** — it saves a full write and read.

Variants and optimizations:

- **Sort-merge join fusion:** if #runs(R) + #runs(S) ≤ M − 1, merge R's runs,
  S's runs, and join in one pass (EDBS sort-merge join improvement), cost
  ≈ 3(B(R)+B(S)).
- **Graceful degradation:** an input slightly larger than M must not double
  the cost; spill only part of the data (hybrid approach: keep the last run
  in memory and merge it with spilled runs).
- **Key normalisation:** encode the composite sort key (with NULL ordering,
  ASC/DESC, collation) into a byte string that compares with `memcmp`;
  sort (normalised prefix, row pointer) pairs and break ties on the full key
  only when prefixes collide. Graefe's survey "Implementing sorting in
  database systems" (ACM CSUR 2006) is the reference for these techniques.
- **Early aggregation / dedup in run generation:** when sorting for GROUP BY
  or DISTINCT, collapse equal keys while forming runs and while merging; runs
  shrink toward the number of groups (Bitton & DeWitt, TODS 1983).
- **Top-N sort:** ORDER BY … LIMIT N uses a bounded heap of N entries
  (O(n log N), memory O(N)) or, for large N, run generation that discards
  rows below the current Nth key. Push LIMIT into the sort, never sort fully
  then cut.
- **Offset-value coding / prefix truncation** cut comparison cost in merges
  of long keys (also from Graefe's work).

Invariants: output is a permutation of input (multiset equality — test with
a hash-based checksum independent of order); stability if the operator
promises it (needed when a later sort on a subset of keys must preserve a
previous order); NULLS FIRST/LAST respected per key; collation-aware string
comparison identical between run generation and merge.

---

## 3. Aggregation (GROUP BY)

### Aggregate function classes (decide algorithm legality)

| Class | Examples | Partial state | Combine | Parallel/spill-friendly |
|---|---|---|---|---|
| Distributive | COUNT, SUM, MIN, MAX | same type as result | same function | yes |
| Algebraic | AVG (SUM, COUNT), VAR/STDDEV (count, sum, sum of squares or Welford state) | fixed-size tuple | combine tuples, finalise | yes |
| Holistic | MEDIAN, PERCENTILE, MODE, COUNT(DISTINCT), string_agg with ORDER BY | unbounded | — | needs all values per group (or approximate sketches) |

(Classification from Gray et al.'s data cube work.) Only distributive and
algebraic aggregates admit pre-aggregation below exchanges and partial
aggregation during spills. AVG must ship (sum, count) — never averages of
averages. VARIANCE via naive sum-of-squares loses precision; use Welford's
state and the pairwise-merge formula.

### Scalar aggregation

One state object, updated per input row: SUM keeps the running sum, AVG keeps
sum and count, COUNT a counter, MIN/MAX the extreme seen. Watch for overflow
(SUM of int64 into int128 or decimal), NULL skipping (aggregates ignore NULL
inputs; COUNT(*) counts rows; SUM of zero non-NULL rows is NULL, not 0).

### Sort-based grouping

Sort on grouping keys, then scan and emit a group at each key change. Free if
input is already ordered (clustered index, upstream merge join, index scan on
a covering index whose key starts with the grouping columns — EDBS notes this
avoids reading the base table entirely). Streaming (non-blocking across
groups), output sorted by group key (an interesting order for the parent).

### Hash-based grouping

Probe a hash table keyed by group, create state on first sight, update in
place. Output order arbitrary. When the table exceeds memory:

1. **Grace-style:** hash-partition input to disk on group key (every group
   lands wholly in one partition), then aggregate each partition in memory.
2. **Hybrid:** keep partition 0 (or as many as fit) resident and aggregated
   during partitioning; spill the others. Under memory pressure evict a
   resident partition by writing its *partial states* (not raw rows) to its
   spill file — legal only for distributive/algebraic aggregates.
3. **Recursive:** if a spilled partition is still too large, repartition with
   an independent hash function. If one *key* is larger than memory (possible
   only for holistic aggregates), recursion cannot help — fall back to
   sorting that partition.
4. **Pre-aggregation / partial aggregation:** a small cache-resident table
   absorbs high-locality groups and flushes partial states downstream;
   effective when there are few groups or strong locality, useless (pure
   overhead) for unique keys — measure the reduction ratio at runtime and
   switch it off adaptively (Cieslewicz & Ross, VLDB 2007 sample the stream
   to estimate group locality and pick the aggregation algorithm).

### Sort vs hash duality

Both partition the input so that equal keys meet; sort partitions by key
*range* recursively from the bottom (runs) up (merges), hash partitions by
key *hash* top-down. Hash wins when the output (number of groups) is much
smaller than the input and no order is needed; sort wins when the input is
already ordered, when sorted output is needed upstream, or under severe skew
on a holistic aggregate. Graefe's survey (CSUR 1993) and "sort vs hash
revisited" (Graefe, Linville & Shapiro, TKDE 1994) lay out the duality.

---

## 4. Duplicate elimination and DISTINCT

Duplicate elimination is grouping with no aggregates; output one row per
distinct key.

- **Hash DISTINCT is non-blocking:** emit a row the first time its key is
  inserted. Memory grows with the distinct count; on overflow, spill
  *unseen* rows by partition and dedup each partition later — keys already
  emitted must stay in the resident table or be carried into the partition's
  table so they are not emitted twice.
- **Sort DISTINCT** collapses duplicates during run generation and merging.
- **COUNT(DISTINCT x) GROUP BY g** = dedup on (g, x) then COUNT per g; with
  several DISTINCT aggregates on different columns, either one dedup per
  aggregate followed by a join on g, or an expand-then-aggregate plan (tag
  each row once per DISTINCT argument).
- DISTINCT treats NULLs as equal (one NULL group), unlike `=`; the hash and
  equality functions used for grouping must implement this.

---

## 5. Set operations

| Operation | Bag semantics (ALL) | Set semantics |
|---|---|---|
| UNION | concatenate (pipelined) | concatenate + dedup |
| INTERSECT | min(m, n) copies of a row with m and n occurrences | one copy if m, n ≥ 1 |
| EXCEPT | max(m − n, 0) copies | one copy if m ≥ 1 and n = 0 |

Implementations:

- **Sort-merge:** sort both inputs on all columns, merge with counters per
  side; one pass decides the multiplicity of each distinct row.
- **Hash:** build a table on one input storing a counter (or a pair of
  counters, one per side), stream the other. For EXCEPT build the right side
  (the subtrahend) and stream the left, or build both counters when bag
  semantics require exact multiplicities.
- **Via joins:** INTERSECT = semijoin + dedup; EXCEPT = anti-join + dedup —
  but only with **null-safe equality** (`IS NOT DISTINCT FROM`) on every
  column, because set operations treat two NULLs as duplicates while joins do
  not. This is the single most common set-operation bug when rewriting to
  joins.
- Memory: one-pass if the smaller (build) side fits; otherwise hash-partition
  both inputs on all columns (Grace/hybrid) or sort both.

---

## 6. Hash join variants as they matter to the executor

The algorithms are in `join-algorithms`; execution-level points from EDBS and
practice:

- **Grace hash join** (Kitsuregawa, Tanaka & Moto-oka, 1983): partition both
  inputs with h1 into k partitions, then build/probe partition pairs with an
  independent h2; recursive repartitioning with a fresh hash function when a
  partition overflows (e.g., skew). If a partition overflows because of one
  dominant key, recursion never terminates usefully — detect "no progress"
  (partition size not shrinking) and fall back to block NLJ for that pair.
- **Hybrid hash join** (DeWitt et al., SIGMOD 1984): partition 0 of the build
  stays in memory as a hash table during partitioning; probe tuples of
  partition 0 are joined immediately instead of being written. Saves the
  write and re-read of that fraction q of both inputs: cost ≈ (3 − 2q)·
  (B(R) + B(S)). Choose k so the spilled partitions each fit later, and use
  the remaining memory for partition 0.
- **Role reversal:** after partitioning, the build side of each partition
  pair can be whichever is smaller *for that pair* (decide from actual
  partition sizes, not estimates).
- **Symmetric (pipelining) hash join:** hash tables on both inputs; each
  arriving tuple is inserted into its side's table and probes the other.
  Non-blocking on both sides; the building block of adaptive processing.

---

## 7. Cache-conscious operator design

Since memory latency is hundreds of cycles, in-memory operators are bound by
cache and TLB misses, not instructions. The general strategies (Ross's EDBS
entry) and their canonical instances:

| Strategy | Instance | What to implement |
|---|---|---|
| Spatial locality | Column-wise layout (MonetDB, C-Store, Sybase IQ); PAX pages (Ailamaki et al., VLDB 2001) | Scan only needed columns; within a page group values by column |
| Cache-line-sized index nodes | CSS-trees, CSB+-trees (Rao & Ross, VLDB 1999 / SIGMOD 2000) | Pointer-free or one-pointer nodes, children contiguous, nodes aligned to lines |
| Temporal locality by blocking | AlphaSort; block-oriented operator interfaces (Padmanabhan et al., ICDE 2001) | Process cache-sized units, combine later |
| Buffering | Batched B-tree probes (Zhou & Ross, VLDB 2003); instruction-cache buffering between operators (Zhou & Ross, SIGMOD 2004) | Buffer tuples so each node / each operator's code footprint is reused across many tuples |
| Partitioning into cache-sized pieces | Partitioned hash join (Shatdal, Kant & Naughton, VLDB 1994); radix join (Boncz, Manegold & Kersten, VLDB 1999) | Partition until each build partition's hash table fits in cache, then join partitions |
| Hide latency | Group/software-pipelined prefetching for hash joins (Chen et al., ICDE 2004); prefetching wider B+-tree nodes (Chen et al., SIGMOD 2001); helper-thread work-ahead sets on SMT (Zhou et al., VLDB 2005) | Split per-tuple work into stages separated by memory accesses; issue prefetches for a group of tuples, then do work |
| Avoid pollution / TLB thrash | Software write-combining buffers for partitioning (Wassenberg & Sanders, Euro-Par 2011); non-temporal stores | Partition into a cache-resident buffer per partition, flush whole lines; limit fan-out per pass to the TLB reach and use multiple radix passes |
| Choose by sampling | Inspector joins (Chen et al., VLDB 2005); adaptive aggregation (Cieslewicz & Ross, VLDB 2007) | Inspect data during an early pass and pick the algorithm for the rest |
| Calibrate | Manegold et al. (VLDB 2000) calibration of cache/TLB parameters | Measure, do not hard-code, cache sizes and latencies |

Further points:

- **Software has only indirect control of CPU caches.** Unlike the buffer pool
  (which a DBMS manages itself instead of trusting OS virtual memory), cache
  contents are decided by hardware replacement (LRU variants); the levers are
  data layout, access order, prefetch instructions and non-temporal stores.
- **Radix partitioning fan-out** per pass is bounded by TLB entries and cache
  lines (too many output partitions → one TLB miss per tuple). Use 2+ passes
  of moderate fan-out instead of one huge fan-out.
- **Cache-oblivious** (recursive divide and conquer; Frigo et al., FOCS 1999)
  algorithms get locality at every level without parameters; **cache-adaptive**
  ones stay efficient as the available cache changes mid-computation (Bender
  et al., SODA 2014) — relevant under co-scheduled queries.
- **Shared caches:** individually cache-conscious threads can still thrash a
  shared L3. Prefer cooperative multi-threaded operators over one shared
  structure, but watch for contention hot spots on shared hash tables
  (locality helps caching but concentrates contention).
- **NUMA:** remote memory and remote caches are slower; partition data and
  pin workers so each thread mostly touches local memory (morsel-driven
  dispatch, see `iterator-pipelining-and-memory.md`).

> **Beyond EDBS:** in-memory hash join studies after 2011 (e.g., Balkesen et
> al., ICDE 2013) showed that a well-tuned radix-partitioned join and a
> well-tuned non-partitioned shared-table join are close on modern hardware,
> with the winner depending on build size relative to cache, skew and thread
> count; engines often implement both or a partitioned join with adaptive
> fan-out.

---

## 8. Tests

- Oracle: compare every sort/aggregate/set-op result against a trivially
  correct in-memory implementation (multiset equality) on random inputs with
  heavy duplicates, NULLs in every key column, and Unicode strings under
  non-binary collations.
- Spill matrix: memory grants forcing 0, 1, 2 and recursive spill levels;
  one key holding > 50% of rows; all rows in one group; all rows distinct.
- Aggregate edge cases: SUM overflow boundaries, SUM/AVG over empty input
  (NULL), COUNT(*) vs COUNT(col), DISTINCT aggregates with NULLs, float
  aggregation order sensitivity (tolerance, or exact decimal paths).
- Set ops: ALL vs set semantics multiplicities (m, n ∈ {0,1,2,5}), NULL rows
  on both sides, EXCEPT where the right side is empty or all-NULL.
- Performance regression: hardware counters (LLC misses, dTLB misses per
  tuple) on partitioning and probing microbenchmarks, not just wall time.

Sources: EDBS entries Evaluation of Relational Operators (p.1348), Hash Join
(p.1682), Sort-Merge Join (p.3546), Nested Loop Join (p.2485), Cache-Conscious
Query Processing (p.389).
