# Adaptive query processing and approximate query processing

Scope: (A) techniques that use runtime feedback to change *how* a query runs —
tuple routing (eddies), symmetric/pipelining joins, mid-query
re-optimization, progressive optimization with validity ranges, runtime plan
binding, in-operator adaptivity; and (B) techniques that change *what* is
computed — approximate answers from samples or synopses, online aggregation
with confidence intervals, ripple joins, join synopses.

---

# Part A — Adaptive query processing

## A1. Why and what

Optimize-then-execute fails when statistics are missing or stale, predicates
are correlated, parameters are unknown at compile time, data arrives from
remote/streaming sources at unpredictable rates, or resources change while a
long query runs. Adaptive processing adds a **monitor → analyse → act**
control loop to execution; the loop itself costs CPU and memory, so the win
must exceed that overhead.

Two orthogonal axes: scope (within one query vs across many queries) and
target (the plan itself vs only the scheduling of operators inside a plan).
The degree of interleaving ranges from a few re-optimization points to a
continuum where planning and execution are indistinguishable.

## A2. Taxonomy (fundamental techniques)

| Technique | Mechanism | Example systems/papers |
|---|---|---|
| Horizontal partitioning | Different plans for different subsets of the data, explicit or implicit inside an operator | Partition-wise plan selection; per-partition join method choice |
| Tuple routing | Execution = routing tuples through operators; change the route to adapt | Eddies (Avnur & Hellerstein, SIGMOD 2000) |
| Plan partitioning | Execute in stages; re-optimize at well-defined points between stages | Mid-query re-optimization (Kabra & DeWitt, SIGMOD 1998); POP (Markl et al., SIGMOD 2004) |
| Runtime binding | Defer some choices; pick among alternatives at start-up or runtime, possibly re-invoking the optimizer | Dynamic plans with choose-plan operators (Graefe & Ward, SIGMOD 1989; Cole & Graefe, SIGMOD 1994); parametric query optimization |
| In-operator adaptivity | The operator itself decides (spill, switch algorithm, change build side, change aggregation strategy) | Hybrid hash role reversal, adaptive aggregation, adaptive joins |

Surveys: Deshpande, Ives & Raman (Foundations and Trends in Databases, 2007);
Babu & Bizarro (CIDR 2005).

## A3. Pipelining joins: the substrate for adaptivity

**Symmetric hash join** (Wilschut & Apers, 1991): a hash table per input;
each arriving tuple is inserted into its own table and probes the opposite
one, so output is produced incrementally from whichever input has data. It
is non-blocking on both sides and has frequent **moments of symmetry** —
points (e.g., between tuples) where the join order or routing can change
without losing work or breaking correctness. Costs: two hash tables in memory.
XJoin (Urhan & Franklin, 2000) spills partitions and uses source stalls to
join spilled data. Ripple joins (Part B) generalise the idea for sampling.

Blocking operators (sort-merge, the build phase of a hash join) give an
adaptive engine few decision points: they produce nothing until their input
is consumed, so most adaptive designs favour pipelined operators.

## A4. Eddies

An eddy is an n-ary routing operator connected to a set of commutative
operators (selections, joins implemented over state modules).

- Each tuple carries a **ready/done bitmap**: which operators it still must
  visit and which it has passed. The eddy sends a tuple to an eligible
  operator; when the tuple returns, the eddy updates its bits; when all bits
  are done it is output.
- **Routing policy** learns selectivities and costs online. The original
  paper used back-pressure (slow operators accept fewer tuples) plus lottery
  scheduling (an operator gains tickets for tuples it consumes and loses them
  for tuples it returns, so selective operators earn more traffic).
- **Joins inside eddies** are built from *state modules* (SteMs: Raman,
  Deshpande & Hellerstein, ICDE 2003) — per-relation dictionaries that tuples
  are inserted into and probe, decoupling join state from join order.
- **Correctness invariants:** each output tuple is produced exactly once
  (no duplicate results from different routes over symmetric state); every
  tuple visits every applicable operator exactly once before output; build
  and probe of SteMs must be ordered so that a pair of matching tuples is
  joined by exactly one of the two probes (typically via timestamps/sequence
  numbers).
- Overhead: per-tuple routing decisions; batching routing decisions
  (route a group of tuples together) recovers much of the cost.
- Freedom depends on operators: pipelined symmetric operators offer the most,
  blocking ones the least.

## A5. Plan-partitioning re-optimization

### Mid-query re-optimization (Kabra & DeWitt, SIGMOD 1998)

Insert **statistics collectors** into the plan (cardinality, histograms of
intermediate results). At materialisation points (where an intermediate is
fully computed anyway — hash build, sort, temp), compare observed with
estimated statistics; if divergence is large and remaining work is
substantial, re-invoke the optimizer for the rest of the query, treating the
materialised intermediate as a new base relation. Also re-allocates memory to
remaining operators based on actual sizes.

### Progressive optimization — POP (Markl, Raman, Simmen, Lohman, Pirahesh & Cilimdzic, SIGMOD 2004)

- At optimization time, compute for each plan edge a **validity range**: the
  cardinality interval within which the chosen subplan stays optimal (or near
  optimal).
- Place **CHECK operators** on edges; at runtime a CHECK compares the actual
  cardinality against the range and triggers re-optimization if violated.
- Re-optimization reuses completed intermediate results (treated as
  materialised views) so work is not lost.
- CHECK placement trade-off: lazy checks at existing materialisation points
  are free but late; eager checks inside pipelines catch errors early but risk
  having already returned rows to the client. Remedies: buffer output until
  the check passes, or compensate by excluding already-returned rows (an
  anti-join against them) in the new plan.

### Learning across queries

Feedback loops store observed cardinalities and adjust future estimates
(DB2's LEO, Stillger, Lohman, Markl & Kandil, VLDB 2001). This is
cross-query adaptivity; the statistics side belongs to
`cardinality-and-statistics`.

## A6. Runtime binding and competition

- **Choose-plan operators** embed alternative subplans; the choice is made at
  start-up when parameter values (or available memory) are known.
- **Parametric optimization** precomputes the optimal plan per region of the
  parameter space.
- **Competition:** run alternative access strategies concurrently for a short
  time and keep the winner (Antoshenkov's work on Rdb/VMS, ICDE 1993).

> **Beyond EDBS:** production adaptivity is mostly in-operator or
> stage-boundary: SQL Server adaptive joins (choose hash vs nested loop after
> seeing the build-side row count) and memory grant feedback; Oracle adaptive
> plans (a statistics collector decides between NL and hash join at runtime);
> Spark Adaptive Query Execution re-optimizes at shuffle boundaries using
> actual partition statistics (coalesce small partitions, switch sort-merge
> to broadcast join, split skewed partitions). All of them place decision
> points where the plan materialises anyway — the lesson of POP.

## A7. In-operator adaptivity checklist

- Hash join: decide spill partitions from actual build size; per-partition
  role reversal; detect skewed/heavy keys and handle them separately;
  short-circuit when the build is empty (inner/semi joins return nothing —
  stop reading the probe side).
- Aggregation: monitor reduction ratio of partial aggregation and disable it
  when it does not reduce; switch to sort-based handling for a partition with
  an oversized holistic group.
- Sorting: switch between in-memory and external modes at the actual size;
  detect presorted input (replacement selection gives one run).
- Filters: reorder conjuncts by observed selectivity/cost per batch (cheap,
  safe because conjunct order does not change semantics — except for
  short-circuit-sensitive expressions with side effects or errors, which
  must keep a guarded order).
- Runtime join filters: drop a Bloom filter whose observed pass rate is near
  100% (pure overhead).

## A8. Correctness invariants for any adaptive scheme

1. **Exactly-once output** across plan switches (no lost, no duplicated
   rows) — the hardest invariant; design around materialisation points or
   explicit compensation.
2. **Semantics independence:** any route or plan chosen produces the same
   multiset (and order, if promised) as the static plan.
3. **Bounded overhead:** monitoring cost stays a small fraction; decision
   frequency is rate-limited to avoid thrashing between plans.
4. **Determinism for debugging:** log every adaptive decision with the
   statistics that triggered it; provide a switch to disable adaptivity and
   reproduce the static plan.

---

# Part B — Approximate query processing (AQP)

## B1. Goal and error metric

Answer aggregate queries (COUNT, SUM, AVG, also GROUP BY variants) orders of
magnitude faster with acceptable accuracy, reporting the error. Relative
error of an answer y′ to exact y: |y − y′| / |y|. Motivations: exploratory
decision support where precision to the last digit is unnecessary, query
previews (estimated hit counts before running the real query — EDBS cites
NASA EOSDIS), and degraded operation when base data is unavailable.

Two approaches: **precomputed synopses** (built before queries) and **online
processing** (progressive refinement at query time).

## B2. Sampling-based estimation

Uniform random sample of n rows out of N, sampling fraction f = n/N.

| Aggregate | Estimator | Variance / CI (CLT, large n) |
|---|---|---|
| COUNT(*) WHERE pred | N·p̂ where p̂ = qualifying fraction | Var(p̂) ≈ p̂(1−p̂)/n·(1−f) |
| SUM(x) WHERE pred | N · mean of (x·1[pred]) over the sample | Var ≈ N²·s²/n·(1−f), s² = sample variance of x·1[pred] |
| AVG(x) WHERE pred | ratio estimator: Σx·1[pred] / Σ1[pred] | via delta method; driven by the number of qualifying sample rows |
| Non-uniform (weighted) samples | Horvitz–Thompson: Σ xᵢ/πᵢ, πᵢ = inclusion probability | |

CI: estimate ± z_{α/2}·sqrt(Var). Large-sample (CLT) intervals are
tight but asymptotic; Hoeffding-style intervals are conservative but valid
for any n given value bounds. Online aggregation offers both.

Hard limits — never pretend otherwise:
- MIN/MAX, rare groups, and selective predicates with few qualifying sample
  rows are poorly estimated; missing groups in GROUP BY cannot be produced at
  all.
- COUNT(DISTINCT) from a sample has no good general estimator (strong
  negative results; Charikar et al., PODS 2000) — use sketches instead.
- **Joins of samples:** sample(R) ⋈ sample(S) is not a uniform sample of
  R ⋈ S; its expected size shrinks by f_R·f_S and the output is correlated,
  inflating variance (Chaudhuri, Motwani & Narasayya, SIGMOD 1999). For
  foreign-key joins, a sample of the fact table joined with the *full*
  dimension tables *is* a uniform sample of the join — the basis of **join
  synopses** (Acharya, Gibbons, Poosala & Ramaswamy, SIGMOD 1999, AQUA
  system, Bell Labs).
- **Block (page) sampling** is cheaper than row sampling but correlated with
  physical clustering; variance can be much higher than the row-sample
  formula claims. SQL's `TABLESAMPLE SYSTEM` is block-level, `BERNOULLI` is
  row-level.

### Biased and stratified samples

| Scheme | Idea | Reference |
|---|---|---|
| Uniform | each row equally likely | |
| Biased | over-sample "important" regions | |
| Icicles | bias toward rows touched by the workload | Ganti, Lee & Ramakrishnan, VLDB 2000 |
| Outlier indexing | keep outliers exactly, sample the rest | Chaudhuri et al., ICDE 2001 |
| Congressional sampling | allocate sample per group so small groups are represented (a mix of uniform and per-group equal allocation) | Acharya, Gibbons & Poosala, SIGMOD 2000 |
| Stratified (workload-optimised) | strata chosen to minimise error for a workload; generalises the above | Chaudhuri, Das & Narasayya, SIGMOD 2001 |

Sampling's strengths: robust to correlation and skew in the data, and its
error is both measurable and controllable (bigger sample → smaller CI).
Weaknesses: optimizer/rewriter overhead to route queries to samples, and the
join problem above.

> **Beyond EDBS:** BlinkDB (Agarwal et al., EuroSys 2013) maintains multiple
> stratified samples over column sets chosen from the workload and picks a
> sample per query to meet a user error or time bound. Reservoir sampling
> (Vitter, TOMS 1985) maintains a uniform sample of fixed size over a stream
> or an append-only table in one pass.

## B3. Other synopses (brief; details in `cardinality-and-statistics`)

- **Histograms:** bucketise a value domain; within a bucket use the
  continuous-value assumption (only min/max) or the uniform-spread assumption
  (count of distinct values placed evenly). Low runtime overhead, widely used
  for estimation, but no theoretical error bound and poor scaling to many
  dimensions (bucket count explodes).
- **Wavelets:** Haar decomposition by recursive pairwise averaging and
  differencing; keep the largest coefficients as the synopsis (Matias, Vitter
  & Wang, SIGMOD 1998 for selectivity; extended to general approximate query
  answering over multidimensional/OLAP data, e.g., Chakrabarti et al., VLDB
  2000).
- **Sketches/random projections:** one-pass, mergeable, with probabilistic
  guarantees (AMS for join sizes; Das, Gehrke & Riedewald, SIGMOD 2004 for
  spatial result-size estimates).
- Synopsis maintenance: incrementally update while the distribution is stable,
  rebuild when it drifts.

## B4. Online aggregation (Hellerstein, Haas & Wang, SIGMOD 1997)

Instead of a single final answer, continuously display a running estimate
with a confidence interval that shrinks as more data is processed; the user
can stop when satisfied. It balances two goals: minimise dead time between
updates, and maximise the rate at which the estimate converges.

Engine requirements:
- **Random-order access:** the scan must deliver rows in random order (scan a
  pre-shuffled copy, or sample blocks/rows in random order). A clustered scan
  in key order gives biased running estimates.
- **Non-blocking operators** throughout the pipeline (no sort, no hash build
  that waits for all input before producing estimates).
- **Fair progress across groups:** for GROUP BY, small groups would get no
  samples for a long time; *index striding* reads round-robin across groups
  via an index so every group's estimate improves.
- **Running CI computation:** maintain count, sum, sum of squares per group
  (O(1) update per row).

**Ripple joins** (Haas & Hellerstein, SIGMOD 1999): read random samples from
both inputs incrementally; at each step join the new tuples of one input with
all tuples seen so far of the other (a generalisation of nested loops and
symmetric hash join), producing a growing uniform-ish sample of the join's
cross product restricted to the join predicate, with CIs; the aspect ratio
(how fast each input is read) adapts to minimise CI width.

Practical obstacle noted by EDBS: online processing requires substantial
changes to a conventional query processor (random-order access methods,
non-blocking operators, UI protocol for progressive results), which limited
commercial adoption.

## B5. AQP invariants and tests

1. Unbiasedness: over many seeds, the mean estimate converges to the exact
   answer (test with a fixed dataset and 1,000 sample seeds).
2. Coverage: the reported 95% CI contains the exact answer in ≈95% of
   trials (too high → intervals too wide; too low → wrong variance formula,
   often from block sampling or joins of samples).
3. Monotone convergence (online): CI width shrinks roughly as 1/sqrt(rows
   processed) under random order.
4. Group completeness: AQP must flag groups it could not observe; never
   silently drop them.
5. Scale-up correctness: SUM/COUNT scaled by inverse inclusion probability;
   AVG not scaled.

Sources: EDBS entries Adaptive Query Processing (p.61), Approximate Query
Processing (p.139), One-Pass Algorithm (p.2556), Query Processing (in
Relational Databases) (p.3027), Query Processing and Optimization in Object
Relational Databases (p.3032).
