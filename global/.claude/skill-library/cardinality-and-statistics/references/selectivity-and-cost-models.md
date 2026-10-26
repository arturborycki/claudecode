# Selectivity estimation and cost models

The estimator turns catalog statistics into cardinalities for every logical
subexpression; the cost model turns cardinalities and physical properties into
a comparable scalar. This file gives the assumptions both rest on, the concrete
formulas, how the assumptions fail on real data, and what production engines and
research do about it.

## 1. What "cost" means and how it is layered

Optimization goals vary: total resource consumption, response time to the first
or the last row, throughput, and in constrained settings energy or connection
time. Whatever the goal, the cost model must be **analytical** (closed-form,
microseconds to evaluate) because the optimizer evaluates it for thousands to
millions of alternatives; simulation models are accurate but far too slow.

Three layers (Manegold's classification in EDBS):

| Layer | Inputs | Output | Example |
|---|---|---|---|
| Logical | data distribution, operator semantics | intermediate result sizes | card(sigma_p R) = sel(p) * card(R) |
| Algorithmic | logical sizes + algorithm complexity, block/page sizes | counts: I/Os, comparisons, memory needed | grace hash join reads and writes both inputs once more |
| Physical | algorithmic counts + hardware description | time | I/Os * (latency + block/bandwidth) + cycles / clock |

Engineering consequence: implement them as separate functions. Logical
estimates live on the memo group; algorithmic and physical costs live on the
physical plan node and are re-evaluated per implementation choice.

Cost factors:
- **Temporal** (convertible to time, additive, "stretchable"): disk I/O with
  sequential vs random distinction (seek charged once per run vs per access),
  memory accesses / cache misses scored by latency, CPU cycles, network latency
  plus bandwidth.
- **Spatial**: memory footprint. Not additive in time: two operators each
  needing 60% of memory cannot overlap at all; they serialize. Model memory as a
  feasibility constraint (memory grants, spill thresholds), not as a cost term.

Composition:
- Serial, side-effect-free operators: plan cost = sum of operator costs (each
  node's cost includes its inputs), as System R did.
- Concurrent operators on disjoint resources: response time = max over the
  concurrent branches.
- Concurrent operators sharing resources: needs an explicit contention model;
  the hard case for parallel and distributed plans.

> **Beyond EDBS:** PostgreSQL's planner is a concrete linear model with
> calibratable knobs: `seq_page_cost = 1.0`, `random_page_cost = 4.0`,
> `cpu_tuple_cost = 0.01`, `cpu_index_tuple_cost = 0.005`,
> `cpu_operator_cost = 0.0025` (defaults). Calibrate them per platform with
> microbenchmarks; on SSD or memory-resident data the random/sequential ratio
> should shrink toward 1.

## 2. The standard assumptions and how they break

| Assumption | Statement | Typical failure |
|---|---|---|
| Uniformity | values (or frequencies within a bucket) are spread evenly | Zipfian keys, popular products, NULL-heavy columns |
| Attribute value independence (AVI) | joint distribution = product of marginals | (city, state), (model, make), (order_date, ship_date) |
| Containment of value sets | for an equi-join, the column with fewer distinct values has all of them in the other | FK columns referencing a filtered or partially populated dimension; disjoint ranges |
| Preservation of value sets | a non-join column keeps its NDV through a join (capped by output card) | joins that filter (semijoin effect) |
| Predicate-join independence | a local filter does not change join selectivity | filter on dimension correlates with fact distribution (region = 'EU' and EU-heavy sales) |
| Stationarity | statistics still describe current data | bulk loads, ascending keys, deleted partitions |

Uniformity was the starting point of explicit cost estimation; non-uniform
distributions were addressed with histograms; **hidden correlation remains the
open problem** (EDBS Cost Estimation says as much). Multiplying independent
selectivities underestimates correlated conjunctions, and underestimates are the
dangerous direction: they select nested loops, small hash tables and serial plans.

## 3. Single-table predicate selectivity

With MCV list M (values with frequencies), histogram H over the remaining
values, null fraction z, NDV d:

```
eq(c):        if c in M: freq_M(c)
              else: (1 - z - sum(freq_M)) / max(d - |M|, 1)
neq(c):       1 - z - eq(c)
range(a<c):   sum of freq_M(v) for v < c  +  (1 - z - sum freq_M) * H.fraction_below(c)
between:      treat as one range, never as product of two half-ranges
is null:      z
in (c1..ck):  sum eq(ci) for distinct ci, capped at 1 - z
like 'abc%':  range [abc, abd) on the column; '%abc%': default or sample
col1 op col2 (same table):  default, or evaluate on a stored sample
f(col) op c:  default unless an expression statistic exists
```

Selinger's original defaults when no statistics exist: equality 1/10 (or
1/ICARD with an index), column = column 1/max(ICARD1, ICARD2), open range 1/3
(or linear interpolation over [low, high] for arithmetic types), BETWEEN 1/4,
IN-list = k x equality capped at 1/2, OR = s1 + s2 - s1*s2, AND = s1*s2, NOT = 1 - s.

> **Beyond EDBS:** PostgreSQL's fallbacks are `DEFAULT_EQ_SEL = 0.005`,
> `DEFAULT_INEQ_SEL = 1/3`, `DEFAULT_RANGE_INEQ_SEL = 0.005` and
> `DEFAULT_NUM_DISTINCT = 200`; it pairs `a > x AND a < y` on the same column into
> one range estimate instead of a product, and for out-of-histogram constants on
> indexed columns it probes the index for the actual current min/max.

Conjunction strategies (choose deliberately, test with correlated data):

| Strategy | Formula | Notes |
|---|---|---|
| Independence | product | default almost everywhere; underestimates |
| Exponential backoff | sorted ascending s(1) * s(2)^(1/2) * s(3)^(1/4) * s(4)^(1/8) | SQL Server's 2014+ estimator (four most selective); between independence and full correlation |
| Minimum | min(s_i) | assumes full correlation; overestimates for independent columns |
| Column-group stats | NDV of (a, b), multi-column MCV, functional-dependency degree | Oracle column groups, DB2 column-group stats, PostgreSQL `CREATE STATISTICS` (ndistinct, dependencies, mcv) |
| Evaluate on sample | count matches in a stored or on-the-fly sample | handles any predicate; zero hits for selective predicates -> fall back |
| Maximum entropy | combine overlapping multivariate knowledge consistently | Markl et al. (VLDB 2005): different combinations of partial stats otherwise give inconsistent answers for the same conjunction |

Detecting which column groups need statistics: CORDS (Ilyas et al., SIGMOD
2004) samples column pairs, tests for soft functional dependencies and
chi-square correlation, and recommends groups. A cheap engine-level proxy:
compare NDV(a, b) from a sample-based HLL with min(card, NDV(a) * NDV(b)).

## 4. Join selectivity

Equi-join R.a = S.b under containment:

```
|R join S| = |R| * |S| / max(V(R,a), V(S,b))
```

Exact size is the dot product of frequency vectors `sum_v f_R(v) * f_S(v)`.
By Cauchy-Schwarz it is at most `sqrt(F2(R.a) * F2(S.b))`, where F2 is the
self-join size (second frequency moment). When the heavy hitters coincide on both
sides the true size can exceed the uniform estimate by orders of magnitude;
when they are disjoint it can be far smaller. Better estimators in order of cost:

1. **MCV x MCV matching**: sum products of frequencies of values present in both
   MCV lists; treat unmatched MCVs and the remainders uniformly (PostgreSQL's
   `eqjoinsel` does this).
2. **Histogram alignment**: split both histograms at the union of boundaries,
   apply containment per aligned bucket pair, sum.
3. **Sketch dot product**: AMS or Count-Min sketches built with the same seeds on
   both columns estimate `f . g` directly (see `sampling-and-sketches.md`).
4. **Join sampling**: sample-based estimation, best with an index on the inner
   (see below).

FK -> PK equi-join (key known from constraints): output = |FK side| x
sel(filters on PK side) x (1 - null_frac(FK)). Prefer this over the generic
formula whenever the key is declared or inferred; it is exact under
referential integrity.

Distinct values after filtering. Selecting k of n rows from a column with d
equally frequent values leaves in expectation about

```
d_after = d * (1 - (1 - 1/d)^k)        (approx d * (1 - exp(-k/d)))
```

distinct values. Use this to propagate NDV of non-filtered columns; use the
filter itself for the filtered column (equality -> 1; range -> fraction of d).

NDV propagation through a join: join column -> min(V_R, V_S); other columns ->
min(V, output card). GROUP BY output on (g1..gk): column-group NDV if known,
else min(product of NDVs, input card), applying the after-filter formula when
the grouping input is filtered.

Composite join predicates between the same pair (`R.a = S.a AND R.b = S.b`):
the independence product of the two 1/max(V) terms underestimates when (a, b) is
a composite key; use column-group NDV of (a, b) on both sides.

Non-equi joins: band joins via histogram overlap; `<` joins default to 1/3;
theta joins with UDFs default or sample.

## 5. Error propagation

Ioannidis & Christodoulakis (SIGMOD 1991) showed estimation errors grow
**exponentially** with the number of joins: each join multiplies the error of its
inputs by the error of its own selectivity. Use the **q-error**

```
q(est, act) = max(est / act, act / est)     (with both clamped to >= 1)
```

because it is symmetric, multiplicative, and composes: if every selectivity on a
k-join path has q-error <= q, the result's q-error can reach q^k. Moerkotte,
Neumann & Steidl (VLDB 2009) relate plan-cost suboptimality to the maximum
q-error and argue for estimators that bound q-error rather than average error.

Ioannidis & Christodoulakis (TODS 1993) further showed that, for limiting
worst-case error propagation in join sizes, **serial** histograms (buckets group
values with contiguous frequencies) are optimal; this motivates frequency-sorted
histogram classes such as V-optimal and end-biased (see `histograms.md`).

## 6. Skew and its effects on estimates

Skew means non-uniform value frequencies, commonly modelled by Zipf: the i-th
most frequent value has frequency proportional to 1/i^z (z = 0 is uniform). Lynch
(VLDB 1988) supplied real-world Zipf parameters and selectivity techniques for
highly skewed columns.

Walton, Dale & Jenevein's taxonomy (VLDB 1991), framed for parallel joins:

| Skew | Origin | Estimator responsibility |
|---|---|---|
| Attribute value skew (AVS) | intrinsic to data | MCV / heavy-hitter stats on join and group keys |
| Tuple placement skew (TPS) | initial partitioning (e.g., range) | per-partition row counts |
| Selectivity skew (SS) | filters select different fractions per node | per-partition histograms or zone maps |
| Redistribution skew (RS) | repartitioning between operators | hash-bucket load from MCVs before choosing broadcast vs shuffle |
| Join product skew (JPS) | per-node join selectivity differs | per-node f.g, i.e. MCV matching per partition |

Mean-based estimates are fine for totals but useless for the max-loaded node,
which governs parallel response time. An MPP optimizer needs heavy-hitter
frequencies to cost a skewed shuffle and to pick skew-handling plans
(broadcast the small side, split heavy keys, partial pre-aggregation). Effects
on sketches go the other way: AMS self-join estimates get relatively more
accurate as skew increases, and Count-Min needs less space for Zipf z > 1.

## 7. Feedback, adaptivity and robustness

- **Query feedback**: Chen & Roussopoulos (SIGMOD 1994) fit a curve to observed
  selectivities; self-tuning histograms (Aboulnaga & Chaudhuri, SIGMOD 1999) and
  STHoles (Bruno, Chaudhuri & Gravano, SIGMOD 2001) refine buckets from results;
  DB2 LEO (Stillger et al., VLDB 2001) records est/actual per operator and applies
  adjustments to later estimates. Pitfall: overlapping feedback must be combined
  consistently (maximum entropy), and adjustments must expire as data changes.
- **Statistics on intermediate results**: SITs (Bruno & Chaudhuri, SIGMOD 2002)
  keep histograms on views/join results so join-filter correlation is captured.
- **Progressive / mid-query re-optimization**: Kabra & DeWitt (SIGMOD 1998);
  POP (Markl et al., SIGMOD 2004) attaches validity ranges to plan choices and
  re-optimizes at a materialization checkpoint when the observed cardinality
  leaves the range.
- **Robust choice**: least-expected-cost over a distribution of selectivities
  (Chu, Halpern & Seshadri, PODS 1999); robust cardinality from sample-based
  confidence (Babcock & Chaudhuri, SIGMOD 2005); parametric optimization
  precomputes plans per parameter region (Ioannidis et al., VLDB 1992).
- **Pessimistic estimation**: upper bounds from degree statistics instead of
  point estimates (Cai, Balazinska & Suciu, SIGMOD 2019, building on the AGM
  bound). Overestimates are safer than underestimates for plan robustness.
- Executor-side insurance belongs to `query-execution-advanced`: adaptive
  joins, hash tables that grow without rehash storms, runtime filter pushdown.

## 8. How good are optimizers, empirically

> **Beyond EDBS:** Leis, Gubichev, Mirchev, Boncz, Kemper & Neumann, "How good
> are query optimizers, really?" (PVLDB 9(3), 2015) introduced the Join Order
> Benchmark (JOB): 113 queries over the real, correlated IMDB data set, each with
> several joins (3-16). Findings an engine builder should internalize:
> - Every tested system (PostgreSQL, HyPer and three commercial systems)
>   produced estimates off by orders of magnitude for multi-join queries, and
>   **underestimation dominates and worsens with join count**. Base-table
>   estimates were comparatively good; sampling-based base estimates (HyPer)
>   helped there but not for joins.
> - TPC-H-style synthetic data (uniform, independent) hides these problems.
> - Injecting true cardinalities improved plans far more than refining the cost
>   model; with true cardinalities even a simple main-memory cost model
>   (roughly, counting tuples processed) chose plans comparable to tuned models.
> - Some of the worst runtime failures came from risky operator choices on
>   underestimates: nested-loop joins without an index, and hash tables sized
>   from the estimate. Disabling non-index NL joins and making hash tables
>   resize gracefully removed most catastrophic cases.
> - More indexes widen the plan space and therefore make bad estimates costlier.
> - Exhaustive DP (bushy) beat heuristic enumeration once estimates were sane.

## 9. Learned cardinality estimation

> **Beyond EDBS:** Two families exist.
> - *Query-driven*: learn a regression from query features to cardinality from
>   executed workload, e.g. MSCN (Kipf et al., CIDR 2019). Cheap inference;
>   degrades on workload shift and needs training queries.
> - *Data-driven*: learn the joint data distribution, e.g. Naru (Yang et al.,
>   PVLDB 2020, autoregressive models for single tables), NeuroCard (Yang et al.,
>   PVLDB 2021, joins via a learned model over a full-outer-join sample) and
>   DeepDB (Hilprecht et al., PVLDB 2020, relational sum-product networks).
>   Handle correlation well; training and update cost grows with schema size.
> - The benchmark study of Han et al. (PVLDB 2022) found data-driven methods
>   generally more accurate than query-driven ones, but end-to-end gains smaller
>   than q-error gains suggest, with practical problems in training time,
>   model update after data change, inference latency during enumeration, and
>   occasional violation of basic logical rules (monotonicity, consistency).
> - Practical integration guidance: keep the classical estimator as the
>   fallback; require the learned estimator to respect the invariants in
>   SKILL.md (bounds, monotonicity, order independence), or clamp it; cache per
>   memo group; and measure end-to-end runtime, not q-error alone. Steering
>   approaches that pick among the classical optimizer's hinted plans (Bao,
>   Marcus et al., SIGMOD 2021) avoid replacing the estimator altogether.

## 10. Sampling-based estimation at optimize time

- Single table: evaluate the full conjunction on a stored or block sample;
  estimate = matches / sample size x card. Exact under correlation; fails with
  zero matches (fall back to classical estimate, or report an upper bound such as
  "fewer than card/sample_size").
- Joins: the join of independent uniform samples is not a uniform sample of the
  join and is tiny (fraction p^2) and biased toward heavy keys (Chaudhuri,
  Motwani & Narasayya, SIGMOD 1999). Workable designs: sample one side and probe
  the full other side through an index (index-based join sampling, Leis et al.,
  CIDR 2017), correlated sampling with a shared hash on the join key, join
  synopses precomputed along FK paths (Acharya et al., SIGMOD 1999), or random
  walks over indexes (wander join, Li et al., SIGMOD 2016). Haas, Naughton,
  Seshadri & Swami (JCSS 1996) analysed join selectivity from samples.

## 11. Pitfalls checklist

- Estimating the same subset differently under different splits (compute per
  memo group).
- Multiplying the selectivity of an equivalence class's implied predicates.
- Treating `a > x AND a < y` as two independent predicates.
- GROUP BY above a join using base-table NDVs not reduced by the join.
- Using NDV of the whole table after a selective filter on another column.
- Forgetting NULLs in join columns (they never match) and in IS NOT NULL.
- Integer cardinalities truncating to 0 mid-plan; carry f64.
- Defaults that differ by operator (`<` vs `<=`) producing non-monotone estimates.
- Cost-model parameters tuned on one storage medium and shipped to another.

Sources: Cost Estimation p.647; Selectivity Estimation p.3371; System R (R*)
Optimizer p.3866; Query Optimization (in Relational Databases) p.3009; Data
Skew p.849; AMS Sketch p.99; Count-Min Sketch p.653; Frequency Moments p.1518;
Data Sampling p.840.
