---
name: cardinality-and-statistics
description: "Use when designing, implementing or reviewing the optimizer's estimation and search machinery: statistics collection, histograms, sampling, sketches, selectivity and join-size estimation, cost models, join-order enumeration, and estimate-sensitive rewrites. Triggers on cardinality estimate, selectivity, NDV, n_distinct, histogram, equi-depth, V-optimal, MaxDiff, MCV list, ANALYZE, COLLECT STATISTICS, sampling rate, HyperLogLog, Count-Min, AMS sketch, correlated predicates, independence assumption, join selectivity, q-error, System R, interesting orders, DPccp, DPhyp, bushy vs left-deep, GEQO, cost model calibration, subquery unnesting, magic sets, multi-query optimization. Apply even when phrased as 'the planner picked a nested loop over millions of rows', 'estimates are off by 1000x', 'stats are stale', or 'the query got slow after the data grew'."
---

# Cardinality, Statistics and Plan Search

This skill owns the optimizer's numbers and its search: which statistics the
catalog keeps, how they become row-count estimates for every subplan, how a cost
model turns estimates into a scalar, and how the enumerator explores join orders
with them. The governing fact: **cardinality error, not cost-model fidelity or
search completeness, dominates plan quality**, and it compounds multiplicatively
up the join tree. Build estimators whose error is bounded and observable, and a
search plus executor that degrade gracefully when the estimates are wrong.

## Mental model

```
catalog stats ── row count, pages, null frac, NDV, min/max, MCV + histogram,
   │             column-group stats, sketches (HLL/KLL/CM), stored samples
   │  ANALYZE (sampled) / incremental merge / query feedback
   ▼
selectivity estimator: per predicate -> combine AND/OR/NOT -> per join edge
   ▼
cardinality + NDV per output column for every *logical* subexpression (memo group)
   ▼
cost model: op cost = f(input cards, physical props, hw params)
            plan cost = sum (serial) | critical path + contention (parallel)
   ▼
enumerator: DP over connected subsets (bottom-up) or memoized top-down;
            keeps a Pareto set per (relation set, physical property)
```

- Cardinality is a **logical** property of (relation set, applied predicates);
  it must be identical for every plan in a memo group. Cost is **physical**.
- Cost layers: logical volumes -> algorithmic counts -> physical time; keep them
  separable. System R's `page_fetches + W * RSI_calls` begat every I/O + CPU model.
- Estimates enter in four places: base-predicate selectivity, join selectivity,
  grouping/distinct output (NDV of column combinations), and physical
  parameters (pages touched, clustering). The third is the most neglected.

## Core invariants

1. **Order independence**: card(S) for relation set S with predicate set P is the
   same whichever join order derived it. Compute it once per memo group.
2. **Bounds**: 0 <= sel <= 1; card(sigma R) <= card(R); card(R join S) <= card(R)*card(S);
   semi/anti join <= outer card; left outer join >= outer card; GROUP BY output
   <= min(input card, product of key NDVs); NDV(col) <= card at every node.
3. **FK -> PK**: card = card(FK side, non-NULL FKs) x sel(PK-side filters).
4. **Monotonicity**: an extra conjunct never raises an estimate; a wider range or
   longer IN-list never lowers it.
5. **Optimality is per property**: DP may discard plan p for set S only if some
   q for S has cost(q) <= cost(p) and q's physical properties (order,
   partitioning, uniqueness) dominate p's. Pruning across incomparable
   properties silently loses merge-join and pre-partitioned plans.
6. **Exactly-once enumeration**: in the chosen space (e.g., bushy, no cross
   products) every connected-subgraph/connected-complement pair is emitted once.
   Countable against closed forms (see references).
7. **No double-counted predicates**: each predicate (or equivalence-class
   member implied by transitivity) contributes its selectivity once per subset.
8. **Mass conservation**: histogram bucket counts + MCV counts + null count =
   row count at collection; full-range selectivity = 1 - null_frac.
9. **Sketch merge**: for linear sketches (CM, AMS) and max/OR sketches (HLL, FM),
   merge(sk(A), sk(B)) equals sk(A multiset-union B) exactly, given identical
   hash seeds and parameters.
10. **Determinism**: same stats snapshot + same query -> same plan; any
    randomized enumeration uses a fixed seed derived from the query.
11. **Rewrite soundness**: every rewrite preserves bag semantics including NULLs,
    duplicates and empty-group behaviour (the COUNT bug).
12. **Staleness is visible**: each stat stores the row count and modification
    counter at collection so the estimator can rescale or flag it.

## Design space & trade-offs

| Column statistic | Wins when | Cost / risk |
|---|---|---|
| min/max + NDV, uniformity | surrogate keys, uniform data | collapses on skew |
| MCV list + equi-depth on the remainder (compressed-style) | general default (PostgreSQL, DB2 style) | MCV threshold and bucket count tuning |
| V-optimal / MaxDiff | static data, accuracy-critical | V-opt DP O(n^2 B); MaxDiff needs every value's frequency |
| Wavelet synopsis | range sums, multi-dim, approximate answers | L2-optimal thresholding gives no per-value error bound |
| Sketches (HLL for NDV, KLL quantiles, CM frequencies) | incremental, per-partition merge, streams | error is relative to total mass; rare values invisible |
| Stored sample | arbitrary predicates, UDFs, LIKE, correlated conjuncts | optimize-time cost; zero-hit result for selective predicates |

| Correlation handling | Wins when | Cost / risk |
|---|---|---|
| Independence (product) | genuinely unrelated columns | orders-of-magnitude underestimates on correlated conjuncts |
| Exponential backoff s1*s2^(1/2)*s3^(1/4)... | unknown correlation | heuristic middle ground, no guarantee |
| Column-group NDV / FD degree / multi-col MCV | known correlated groups (city, zip) | which groups? needs detection (CORDS-style) |
| Multi-dimensional histogram | 2-3 correlated range columns | dimensionality curse, build cost |
| Evaluate conjunction on sample | single-table arbitrary predicates | sampling cost, zero hits |
| Query feedback (LEO, self-tuning histograms) | repetitive workloads | consistency across overlapping feedback; drift |

| Join-order search | Wins when | Cost / risk |
|---|---|---|
| Bushy DP (DPccp, DPhyp) | small/medium queries; chains and cycles to ~20+ relations | exponential for stars/cliques |
| Left-deep DP (System R) | pipelined index NL joins | misses bushy optima common in snowflakes |
| Top-down memo (Volcano/Cascades) | extensible rules, branch-and-bound, enforcers | memo bloat, rule-interaction bugs |
| IKKBZ / linearized DP | acyclic or large queries, poly time | ASI cost assumption, linear trees only |
| Greedy (GOO, min-selectivity) | hundreds of relations | arbitrarily bad on adversarial shapes |
| Randomized (II, SA, 2PO, genetic) | very large, anytime | non-reproducible, parameter tuning |

Cost models range from I/O counts (obsolete for memory-resident data) through
I/O + w*CPU (System R; w must be calibrated) to per-device sequential/random
I/O + CPU + cache misses + network, and response-time models for parallel plans
that need resource-contention modelling (details in the cost-model reference).

## Algorithms that matter

```
DPccp (bushy, no cross products), relations as bitsets:
  for each single relation R: best[{R}] = best access paths (one per interesting property)
  for each connected subgraph S1 (EnumerateCsg order: subsets before supersets):
    for each connected complement S2 of S1 (EnumerateCmp: disjoint, adjacent,
        restricted to higher-numbered relations so each pair appears once):
      for p1 in best[S1], p2 in best[S2], each method m, both orientations:
        add_if_not_dominated(best[S1|S2], join(m, p1, p2))
  work = #csg-cmp pairs (optimal); DPsize/DPsub waste failing tests on sparse graphs
```

Selinger defaults when nothing better is known: `col = const` 1/NDV (1/10
without index stats); `col1 = col2` 1/max(NDV1, NDV2); numeric range by
interpolation over [lo, hi], else 1/3; BETWEEN 1/4; IN-list k x equality,
capped; AND product; OR s1 + s2 - s1*s2; NOT 1 - s.

Join size under containment: `|R join_a S| = |R| * |S| / max(V(R,a), V(S,a))`;
the exact size is the frequency-vector dot product `sum_v f_R(v) * f_S(v)`,
which aligned skew pushes far above the uniform formula. MCV matching,
histogram alignment and AMS/CM sketches estimate it better. HyperLogLog
(NDV, ~1.04/sqrt(m) error, register-max merge) and Count-Min (frequencies,
eps*||a||_1 one-sided error) are specified in `references/sampling-and-sketches.md`.

## Failure modes & classic bugs

- **Correlated conjuncts multiplied** -> underestimate -> nested loop over a big
  outer. Detect with per-operator q-error in EXPLAIN ANALYZE.
- **Error compounding with join depth**; underestimation dominates in practice
  and grows with the number of joins (Ioannidis/Christodoulakis; Leis et al.).
- **Ascending-key problem**: predicates past histogram max (today's date) get
  near-zero selectivity. Extrapolate from modification counters or probe the
  index for the real max at plan time.
- **NDV from a sample** underestimates heavy-tailed columns; naive scale-up
  overestimates skewed ones. No sample-based estimator has a good worst-case
  ratio error; prefer full-scan HLL where affordable.
- **Transitive closure double counting**: a=b, b=c plus the derived a=c applied
  as three independent selectivities. Estimate per equivalence class.
- **Block sampling on a clustered column** yields correlated samples and biased
  histograms/NDV; sample rows within blocks or use two-stage designs.
- **GROUP BY estimate = product of NDVs** exceeding the input. Clamp.
- **Zero estimates**: clamping to 1 row hides that a sub-estimate was wrong;
  carry estimates as f64 and clamp only for presentation.
- **Hash tables sized from underestimates** -> repeated resizing or spill storms.
- **Parameter sniffing**: plan cached for an atypical bind value.
- **Disconnected query graph** with cross products banned -> no plan at all.
- **Illegal outer-join reassociation** (use EELS/TES-style conflict sets) and
  the **COUNT bug** in unnesting (empty groups vanish under an inner join).
- **Sketch seeds differ across nodes**, or **weak hashes** on sequential keys:
  merged or single synopses are garbage.

## Implementation checklist (C/C++/Rust)

- Relation sets as `u64` bitsets (`SmallBitVec`/`std::bitset<N>` beyond 64);
  DP table as a hash map keyed by bitset; precompute neighbour masks per relation.
- Memo group owns logical properties: card (f64), per-column NDV, null frac,
  equivalence classes, key/FD info. Computed once at group creation.
- `ColumnStats { rows_at_collect, mod_counter, null_frac, avg_width, ndv,
  ndv_is_ratio, mcv: Vec<(Datum, f64)>, hist_bounds: Vec<Datum>,
  physical_correlation, hll: Option<Hll> }` behind an immutable `Arc` snapshot;
  swap atomically; key plan-cache entries by stats version.
- Type-aware interpolation inside buckets: numeric linear; strings via a
  prefix-to-scalar map; timestamps as epochs; non-orderable types equality only.
- Collection: two-stage (block then row) reservoir sampling with a fixed sample
  size independent of table size; per-row-group HLL/KLL in columnar formats,
  merged at plan time (histograms are not exactly mergeable; sketches are).
- 64-bit seeded hash (xxh3, wyhash, murmur3) shared by every sketch producer.
- Enumeration budget (csg-cmp count); beyond it use linearized DP/greedy, logged.
- Estimator = pure function of (stats snapshot, expression); an oracle hook
  substitutes true counts for diagnosis.

## How to test it

- **q-error** = max(est/act, act/est) per operator; report median/p95/max bucketed
  by join count on JOB (IMDB), TPC-DS, and synthetic Zipf + correlated data.
  TPC-H alone is too uniform and independent to exercise estimators.
- **Property tests**: random predicates on random tables check bounds and
  monotonicity; exact COUNT(*) is the oracle for single-table selectivity.
- **Enumerator**: count csg-cmp pairs against closed forms for chain, cycle,
  star, clique; brute-force all bushy trees for n <= 7 and require equal optimal cost.
- **Order independence**: every expression in a memo group yields the same card.
- **Sketches**: error over many seeds within bounds; merge equivalence; deletes.
  **Histograms**: mass conservation, exact MCVs, boundaries, empty/all-NULL/
  single-value/string columns.
- **Robustness**: perturb every estimate by a random factor in [1/k, k] and
  measure cost regret; inject true cardinalities to separate estimation error
  from cost-model error. Keep golden plan shapes per stats version.

## Expert review questions

1. Is cardinality computed per memo group, and how is order independence asserted?
2. How do conjuncts on one table combine? What is the estimate for
   `city='SF' AND state='CA'`, and for `a > 5 AND a < 3`?
3. What happens for a predicate beyond the histogram's max value?
4. How is NDV estimated, from what sample, with what worst-case ratio error?
5. How do NDVs propagate through filters, joins and GROUP BY?
6. How are equivalence classes used so implied predicates are not counted twice?
7. Which enumeration algorithm, what is its cost on a 20-dimension star, and
   what is the fallback when the budget runs out?
8. Which physical properties participate in dominance pruning?
9. How are outer, semi, anti and dependent joins constrained during reordering?
10. How was the CPU/I-O weight calibrated; can you inject true or perturbed
    cardinalities; what runtime guard (adaptive join, re-optimization) exists?
11. When are stats refreshed, how are partitions merged, which plans invalidated?
12. Which rewrites are heuristic vs costed? How is COUNT-bug safety tested?
13. When is a shared CTE / common subexpression materialized rather than inlined?

## Go deeper

- `references/system-r-and-join-enumeration.md` — building/reviewing the
  enumerator: System R/R*, physical properties, DPsize/DPsub/DPccp/DPhyp,
  search-space counts, Cascades memo, non-inner joins, large-query tiers.
- `references/selectivity-and-cost-models.md` — writing the estimator or cost
  model: assumptions and failures, predicate/join/NDV formulas, correlation,
  error propagation, skew, feedback, Leis et al. findings, learned estimation.
- `references/histograms.md` — choosing/building/maintaining histograms:
  taxonomy, V-optimal/MaxDiff/compressed/end-biased, multi-dim, spatial, wavelets.
- `references/sampling-and-sketches.md` — ANALYZE, NDV, any sketch: sampling
  designs, tail bounds, distinct-value hardness, FM/HLL, AMS, Count-Min, stable.
- `references/query-rewrite-and-mqo.md` — rewrite phase and shared work: view
  merging, unnesting, predicate move-around, magic sets, MQO.
- `references/edbs-entries.md` — all source entries with printed pages (full
  text via the `edbs-reference` skill).

## Related skills

- `query-optimizer` — rule framework, basic rewrites; this skill is its deep
  estimation/enumeration layer. `join-algorithms` — operator algorithms and
  formulas the enumerator chooses among. `query-plan-design` — memo/plan IR.
- `query-engine-testing` — plan snapshots; `parallel-distributed-execution` — runtime skew.
- `query-execution-advanced` — adaptive/robust execution consuming estimates.
- `materialized-views-ivm` — view matching (answering queries using views), not
  view merging. `relational-theory` — equivalences and containment.
- `sql-semantics-and-active-rules` — NULL/duplicate semantics rewrites must keep.
- `parallel-database-systems` — partition skew, parallel optimization;
  `distributed-dbms-design` — distributed optimization, semijoin/Bloom programs.
- `olap-and-warehouse-engines` — star joins, AQP; `stream-processing-engines` —
  windowed sketches; `tuning-and-benchmarking` — JOB/TPC methodology, stats knobs.
- `index-structures-catalog`, `multidimensional-and-similarity-indexing` —
  index-derived estimates, LSH on stable distributions; `beyond-relational-engines`
  — probabilistic data (Karp-Luby); `dbms-architecture` — where the optimizer sits.

## Grounding

EDBS (full table in `references/edbs-entries.md`): System R (R*) Optimizer
p.3866; Query Optimization (in Relational Databases) p.3009; Cost Estimation
p.647; Histogram p.1714; Discrete Wavelet Transform and Wavelet Synopses p.1132;
Data Sampling p.840; FM Synopsis p.1487; AMS Sketch p.99; Count-Min Sketch p.653;
Frequency Moments p.1518; Data Skew p.849; Query Rewriting p.3060; Multi-query
Optimization p.2425. Papers: Selinger et al. SIGMOD 1979; Moerkotte & Neumann
VLDB 2006 / SIGMOD 2008; Ioannidis & Christodoulakis SIGMOD 1991; Poosala et al.
SIGMOD 1996; Flajolet et al. 2007 (HLL); Alon, Matias & Szegedy STOC 1996;
Charikar et al. PODS 2000; Roy et al. SIGMOD 2000; Leis et al. VLDB 2015.
