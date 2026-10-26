---
name: query-execution-advanced
description: "Use when implementing or reviewing execution-engine internals beyond the basic join catalogue: the iterator (Volcano) open/next/close contract, pipelining vs blocking (stop-&-go) operators, memory budgets and spilling, access path selection, external sort, hash/sort aggregation, DISTINCT and set operations, index nested loops, semijoin/Bloom reducers, window functions, top-k and rank joins, skyline/preference queries, approximate and adaptive processing, cache-conscious operators. Triggers on iterator model, open/next/close, pipeline breaker, spill, memory grant, external merge sort, replacement selection, hybrid hash, hash aggregation, INTERSECT/EXCEPT, window frame, ROWS vs RANGE, segment tree, ORDER BY LIMIT, threshold algorithm, HRJN, skyline, eddies, progressive optimization, online aggregation, TABLESAMPLE, vectorized execution, morsel-driven. Apply even when phrased as 'slow only at scale', 'running total wrong with ties' or 'operator OOMs'."
---

# Advanced Query Execution

Owns the runtime half of the engine: how physical operators exchange data,
when they block, how much memory they get and what they do when it runs out,
and the specialised operators (sort, aggregation, set ops, windows, top-k,
skyline, sampling) that sit outside the join catalogue. The single most
important idea: **every operator is defined by its contract (state machine,
output lifetime, blocking behaviour, memory grant, spill path) as much as by
its algorithm** — most production bugs are contract violations, not wrong
algorithms.

## Mental model

- A plan is a dataflow graph of physical operators behind one uniform
  interface (`open/next/close`, plus `rescan`). Access methods are operators
  too; parallelism hides in exchange operators.
- **Pipeline breakers** cut the plan into pipelines. Know *which input*
  blocks: hash join blocks on build only; sort blocks on input but streams
  output; hash DISTINCT never blocks; window blocks per partition.
- Memory decides algorithm class: **one-pass** if the blocking state fits,
  **two-pass** up to ~M² pages, **multi-pass** beyond. The grant is an
  estimate; the spill path is what makes the operator correct.
- Hash and sort are duals (both co-locate equal keys: hash by value
  top-down, sort by range bottom-up); in-memory both are cache/TLB-miss bound.
- **Rank-awareness** replaces materialise-then-sort with early termination
  backed by a monotone bound on unseen results (TA, rank join, SFS, BBS).
- **Adaptivity** places decision points where execution materialises anyway;
  **approximation** trades exactness for a reported confidence interval.

## Core invariants

1. Operator state machine: `open (next)* close`, `rescan` only while open;
   EOF is sticky; `close` runs exactly once on success, early stop
   (LIMIT/EXISTS/semijoin/cancel) and error.
2. A returned tuple/batch is valid only until the next call on that operator;
   consumers that retain rows copy or reference-count them.
3. `rescan(p)` yields exactly what a fresh `open(p)` would.
4. One engine-wide convention for empty non-EOF batches (forbidden, or every
   consumer loops).
5. Every spilling operator produces results identical to its unlimited-memory
   execution for any grant ≥ its documented minimum, and never OOMs above it.
6. The sum of memory grants of simultaneously active breakers (e.g., all
   build tables of a right-deep hash-join chain) never exceeds the query's
   budget.
7. Recursive partitioning makes progress or falls back: a partition that does
   not shrink (single heavy key) switches to block NLJ / sort.
8. Grouping, DISTINCT and set operations treat NULLs as equal; equi-joins do
   not. Rewrites of INTERSECT/EXCEPT to semi/anti-joins use null-safe
   equality; NOT IN is a null-aware anti-join.
9. Semijoin emits each qualifying left row once regardless of partner count;
   unnesting EXISTS into an inner join requires at-most-one inner match.
10. Pre-/partial aggregation and spilling of partial states only for
    distributive/algebraic aggregates; AVG ships (sum, count).
11. Window default frame with ORDER BY is RANGE UNBOUNDED PRECEDING..CURRENT
    ROW (peers included); ranking and LEAD/LAG ignore the frame;
    FIRST/LAST/NTH_VALUE respect it.
12. Rank-aware early termination is valid only for monotone scoring
    functions; a result is emitted only when its score ≥ the current bound on
    every unseen result.
13. Skyline/winnow algorithms (BNL, SFS) assume a strict partial order
    (irreflexive, transitive) preference.
14. Adaptive plan switches preserve exactly-once output; AQP reports an
    interval whose empirical coverage matches its nominal level, and flags
    groups it never observed.

## Design space & trade-offs

### Execution model

| Option | When it wins | Cost / risk |
|---|---|---|
| Tuple-at-a-time pull iterator | OLTP, simple engines, easy LIMIT/EXISTS | Per-tuple virtual call + interpretation overhead |
| Vectorized pull/push (X100 style) | Analytics; memory-stall-heavy probes; easy profiling | Selection-vector plumbing; batch-size tuning |
| Data-centric compiled (HyPer) | Compute-heavy pipelines; tuples in registers | Compile latency; harder debugging; needs tiered fallback |
| Exchange-based parallelism | Distributed/shared-nothing, fixed DOP | Repartition costs; DOP fixed at plan time; skew |
| Morsel-driven parallelism | Multi-core/NUMA single node | Shared breaker state must be concurrent; scheduler complexity |

### Access paths (selectivity s)

| Option | When it wins | Cost / risk |
|---|---|---|
| Heap scan | s above a few percent; no covering index | Reads everything, but sequentially |
| Clustered index range | Range on the clustering key | Only one clustering per table |
| Unclustered fetch per entry | Very small s (≈ a few rows per page or less) | One random I/O per row; collapses at medium s |
| Sorted-RID (bitmap) fetch | Medium s; multi-index intersection | Loses index order; needs RID sort memory |
| Index-only | All columns in the index and visibility decidable | Wider indexes; MVCC visibility checks |

**Sort vs hash** (GROUP BY, DISTINCT, set ops): sort wins on pre-ordered
input, required output order, or holistic aggregates with giant groups; hash
wins when groups ≪ input and no order is needed. Top-N is always a bounded heap.

### Top-k, adaptive and approximate options

| Option | When it wins | Cost / risk |
|---|---|---|
| Full sort/aggregate + heap | No ranked access path; k large | Reads everything |
| Index on ORDER BY expr + pipelined plan | Single table or FK-preserving joins | Needs index; LIMIT pushdown legality |
| TA / NRA / CA | Ranked sources with sorted (+random) access | Monotone F; bookkeeping cost |
| Rank join (HRJN*, PBRJ) | Top-k join, ranked inputs, selective join | Depth explodes for unselective joins/scores |
| Filter/restart, STOP AFTER | Cutoff estimable from statistics | Restart on underestimate |
| In-operator (spill sizing, role reversal, adaptive join) | Always; cheapest | Local decisions only |
| CHECK/validity ranges (POP) at materialisation points | Large estimation errors in long queries | Late detection; reuse of intermediates needed |
| Eddies / tuple routing | Streams, unknown selectivities, federated sources | Per-tuple routing overhead; exactly-once complexity |
| Uniform / stratified samples | Exploratory aggregates, previews | Joins of samples, rare groups, MIN/MAX, NDV |
| Online aggregation / ripple join | Interactive analysis | Random-order access + non-blocking plan required |

## Algorithms that matter

```
memory class:   fits(state, M) → one-pass; else if B ≤ ~M² → two-pass; else recurse
external sort:  runs = ⌈B/M⌉ (≈B/2M with replacement selection on random input)
                passes = ⌈log_{M−1} runs⌉; pipeline the final merge into the parent
hybrid hash:    I/O ≈ (3 − 2q)(B(R)+B(S)), q = fraction of build kept resident
block NLJ:      B(R) + ⌈B(R)/(M−2)⌉·B(S)
Bloom filter:   FP ≈ (1 − e^(−kn/m))^k, k_opt = (m/n)·ln 2
TA:             sorted access round-robin; random-access new objects;
                τ = F(last_1..last_m); stop when k results ≥ τ
HRJN bound:     T = max(F(top1,last2), F(last1,top2)); emit PQ head while ≥ T;
                HRJN*: pull from the input whose 'last' sits in the max term
SFS:            sort by monotone score; window = skyline so far; survivor ⇒ final
sliding frame:  monotone [start,end): add entering, remove leaving (invertible aggs);
                MIN/MAX via monotonic deque; anything else via segment tree O(log n)
sample SUM:     N·mean(x·1[pred]) ± z·sqrt(N²·s²/n·(1−n/N))
expensive preds: order conjuncts by (selectivity − 1)/cost ascending
```

## Failure modes & classic bugs

- **Use-after-next:** parent keeps a pointer into a child's page/batch that is
  unpinned or reused on the next call. Detect by poisoning buffers in debug.
- **Leaks on early close:** LIMIT/EXISTS stops pulling; spill files, pins and
  hash tables survive. Assert the resource tracker is empty after `close`.
- **Premature EOF** from an empty batch; **spill cliff / OOM** just below the
  grant (hash overhead unaccounted, budget per operator rather than per active
  set of breakers); infinite recursive partitioning on one dominant key.
- **NULL drift:** set ops/DISTINCT rewritten to joins with `=`; NOT IN as a
  plain anti-join; EXISTS→inner join duplicating rows when the inner is not unique.
- **Averages of averages** in partial aggregation; float SUM drift in sliding
  windows after removals.
- **Window default frame implemented as ROWS:** running totals wrong at ties;
  LAST_VALUE returns the current peer, not the partition's last row; ranks off
  by the boundary count under parallel range splits.
- **LIMIT pushed through an inner join or filter;** non-monotone score fed to
  TA/rank join; unclustered per-row fetch at medium selectivity.
- **Adaptive switch re-emits rows** already returned; **CI under-coverage**
  from block sampling or joins of independent samples.

## Implementation checklist (C/C++/Rust)

- Operator API `open(ctx, params)`, `next(&mut out) -> Status`, `rescan(params)`,
  `close()`; Rust `Drop` / C++ destructor calls an idempotent `close`; a debug
  decorator checks the state machine and sticky EOF and poisons old buffers.
- Per-query memory tracker with per-operator reservations; `try_reserve`
  returns "spill" instead of aborting; count bucket arrays and arenas.
- Spill files owned by the query context (cleanup on cancel); open-addressing
  hash tables, stored hash codes, fresh hash seed per recursion level.
- Sort on normalised binary keys (NULL order, ASC/DESC, collation) + row
  pointers; cache-sized runs; loser tree merge; final merge pipelined.
- Aggregate objects `init/update/merge/finalize` (+ `remove` for windows) with
  a declared class (distributive/algebraic/holistic) the planner can read.
- Window: spillable random-access partition buffer, peer-boundary array,
  frame-bound calculators per unit, segment tree with configurable fan-out.
- Top-k: bounded heap with an explicit ties policy; rank join = two hash
  tables + priority queue + bound; skyline window as flat SIMD-friendly arrays.
- Vectorized primitives as monomorphised generics/templates over column +
  selection vectors; thread-local pre-aggregation merged at the breaker.
- Adaptivity: per-operator runtime stats (rows, bytes, NDV sketch) exposed to
  a controller; every adaptive decision logged with its trigger.

## How to test it

- **Differential oracles:** naive implementations of every operator; compare
  multisets (score multisets under ties).
- **Memory sweeps:** grants just above/at/below one-pass need, ~sqrt(B), below;
  identical results required.
- **Adversarial data:** all-equal keys, all-distinct, one key with 90% of rows,
  NULLs in every key, anti-correlated skyline data, one giant window partition,
  empty inputs on either side.
- **Contract fuzzing:** random LIMITs/cancels; zero leaked bytes, files, pins.
  **Plan assertions:** LIMIT pushed only where legal; ROW_NUMBER filter becomes
  per-partition top-k; partition-key filters below windows; streaming
  aggregate over a covering index.
- **AQP statistics:** bias ≈ 0 and CI coverage ≈ nominal over many seeds;
  **performance invariants:** LLC/dTLB misses per tuple on partition/probe
  microbenchmarks; early-termination operators read less than their input.

## Expert review questions

1. Which inputs block; what is peak memory of all concurrently active breakers?
2. What happens at grant − 1 byte? Show the spill path and its cost curve.
3. How does recursive partitioning terminate on a single heavy key?
4. Who owns a returned batch, and until when?
5. Is `close` guaranteed on LIMIT, EXISTS, error and cancel — and tested?
6. Which NULL semantics does each equality here use, and why?
7. Is the aggregate splittable, and what crosses the exchange?
8. What is the frame of a row with tied ORDER BY keys, or a NULL key?
9. How many sorts do these k window specs cost; can one sort serve several?
10. Is the score monotone, and what bound certifies the k-th result?
11. Where does the unclustered path lose to a scan, measured on our storage?
12. Where can the plan change mid-flight, and how is exactly-once preserved?
13. Does the sample support this join/grouping; what is measured CI coverage?
14. Is this operator instruction-bound or stall-bound — vectorize or compile?

## Go deeper

- `references/iterator-pipelining-and-memory.md` — operator contract, pipelines and stop-&-go, memory grants and pass counts, exchange, vectorized/compiled/morsel execution.
- `references/access-paths-and-reducers.md` — scan vs index vs index-only costing, INL tricks, semijoin/Bloom and runtime filters, filter/refine, object-relational execution.
- `references/sort-aggregate-setops.md` — external sort, hash/sort aggregation and spills, DISTINCT, set ops, Grace/hybrid details, cache-conscious partitioning and prefetching.
- `references/window-operators.md` — window semantics, frame algorithms, sort sharing, parallel windows, window-based rewrites.
- `references/topk-rank-join-and-skyline.md` — TA/NRA/CA, rank joins and bounds, RankSQL algebra, rank-join indices, LIMIT pushdown, winnow, skyline algorithms.
- `references/adaptive-and-approximate-processing.md` — eddies, symmetric joins, re-optimization and POP, runtime binding, sampling estimators, online aggregation, ripple joins.
- `references/edbs-entries.md` — all 31 source entries with printed pages (pull full text via `edbs-reference`).

## Related skills

- `join-algorithms` — the join catalogue; here: execution context, INL batching, symmetric and rank joins.
- `query-plan-design` — plan node shapes and interfaces; here: their runtime semantics.
- `columnar-arrow-layout` — batch memory format; here: how batches flow and when operators block.
- `query-optimizer` — plan choice; adaptive re-optimization and rank-aware planning straddle the boundary.
- `cardinality-and-statistics` — histograms, sketches, estimation (AQP synopses only summarised here).
- `parallel-database-systems`, `parallel-distributed-execution` — partitioned parallelism, exchange, skew.
- `distributed-dbms-design` — semijoin programs and distributed optimization in depth.
- `olap-and-warehouse-engines` — star joins, bitmaps, cubes, grouping sets built on these operators.
- `stream-processing-engines` — unbounded-stream windows, load shedding, adaptive stream processing.
- `multidimensional-and-similarity-indexing`, `index-structures-catalog` — R-trees/kNN (BBS, filter/refine), B+-tree/hash/CSB+ behind access paths.
- `sql-semantics-and-active-rules` — NULL, bag and set semantics the operators must reproduce.
- `materialized-views-ivm` — add/remove incremental machinery shared with sliding windows.
- `tuning-and-benchmarking`, `query-engine-testing` — calibration, measurement, test harnesses.
- `storage-devices-and-io`, `dbms-architecture` — I/O constants behind access/spill choices; where the executor sits.

## Grounding

EDBS (Liu & Özsu, 2nd ed., 2018): Iterator (p.2042), Pipelining (p.2768),
Pipeline (p.2767), Stop-&-Go Operator (p.3720), One-Pass Algorithm (p.2556),
Evaluation of Relational Operators (p.1348), Access Path (p.22), Index Join
(p.1845), Nested Loop Join (p.2485), Hash Join (p.1682), Sort-Merge Join
(p.3546), Semijoin (p.3436), Multi-step Query Processing (p.2435), Membership
Query (p.2222), Range Query (p.3079), Cache-Conscious Query Processing (p.389),
Window Operator in RDBMS (p.4693), Top-k Queries (p.4168), Score Aggregation
(p.3324), Rank-Aware Query Processing (p.3080), Rank-Join (p.3093), Rank-Join
Indices (p.3096), Preference Queries (p.2784), Skyline Queries and Pareto
Optimality (p.3508), Similarity and Ranking Operations (p.3495), Adaptive Query
Processing (p.61), Approximate Query Processing (p.139), Query Plan (p.3020),
Query Processing (p.3026), Query Processing (in Relational Databases) (p.3027),
Query Processing and Optimization in Object Relational Databases (p.3032).

Seminal work: Graefe, query evaluation survey (CSUR 1993), Volcano (TKDE 1994),
exchange (SIGMOD 1990); Selinger et al. (SIGMOD 1979); DeWitt et al., hybrid
hash (SIGMOD 1984); AlphaSort (VLDB J 1995); radix join (VLDB 1999); Fagin,
Lotem & Naor, TA/NRA (PODS 2001); HRJN (VLDB 2003); skyline operator (ICDE
2001), SFS (ICDE 2003), BBS (SIGMOD 2003); Leis et al., window functions (VLDB
2015); eddies (SIGMOD 2000); POP (SIGMOD 2004); online aggregation (SIGMOD
1997). Beyond EDBS: MonetDB/X100 (CIDR 2005); Neumann, compiled plans (VLDB
2011); morsel-driven parallelism (SIGMOD 2014); compiled vs vectorized (VLDB 2018).
