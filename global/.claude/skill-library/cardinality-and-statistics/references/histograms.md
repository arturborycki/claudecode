# Histograms and related value-distribution synopses

Histograms are the workhorse statistic of every cost-based optimizer: compact,
cheap to probe, and good at range predicates. This file defines them precisely,
gives the construction algorithm and cost for each major class, the
within-bucket assumptions, estimation procedures, maintenance, the
multi-dimensional and spatial variants, wavelet synopses as the
"multi-resolution histogram", and hierarchical summaries.

## 1. Definitions

For attribute X of relation R, let the distinct values present be
v_1 < v_2 < ... < v_n with frequencies f_1..f_n. The set T = {(v_i, f_i)} is the
**data distribution**. Derived quantities used by histogram classes:

- spread s_i = v_(i+1) - v_i (last spread conventionally 1)
- area a_i = f_i * s_i
- cumulative frequency c_i = f_1 + ... + f_i

A histogram is (1) a partition of T into beta buckets plus (2) a rule for
approximating values and frequencies inside each bucket. Each bucket stores at
least its boundaries, total frequency and number of distinct values.

Poosala, Ioannidis, Haas & Shekita (SIGMOD 1996) organize all classes along:

| Dimension | Choices |
|---|---|
| Partition class | serial (buckets are contiguous in the sort parameter), end-biased, arbitrary |
| Sort parameter | value V, frequency F, area A |
| Source parameter (what the constraint looks at) | spread S, frequency F, area A, cumulative C |
| Partition constraint | equi-sum, V-optimal, MaxDiff, compressed |
| Value approximation in bucket | continuous values, uniform spread, point value |
| Frequency approximation in bucket | uniform (average frequency) |

A class is named constraint(sort, source): equi-width = equi-sum(V, S),
equi-depth = equi-sum(V, F), V-optimal(V, F), MaxDiff(V, A), Compressed(V, F), etc.

## 2. The main classes

### Equi-width — equi-sum(V, S)
Equal-length value ranges. One pass with known min/max; trivially maintainable.
Poor on skew: one popular value inflates the estimate for every other value in
its bucket.

### Equi-depth (equi-height) — equi-sum(V, F)
Each bucket holds about |R|/beta rows; boundaries are the quantiles.
Introduced for selectivity estimation by Piatetsky-Shapiro & Connell (SIGMOD
1984). Construction: sort, or a quantile sketch, or a sample. Error on any
range is bounded by about two bucket depths (the two partial end buckets) under
the uniform assumption. Weakness: a value whose frequency exceeds the depth
spans several buckets; equality estimates for it are poor unless such values are
pulled out (compressed).

### Compressed — compressed(V, F)
The values with the highest frequencies get singleton buckets (exact counts);
the rest form an equi-depth histogram. This is the shape most engines ship:
MCV/frequent-value list + quantile histogram over the remainder.

### End-biased
The beta1 highest and beta2 lowest frequencies are kept exactly; all other
values share one bucket with their average frequency (Ioannidis & Poosala,
SIGMOD 1995). Serial in frequency, cheap to build (a top-k / bottom-k problem),
and the optimal end-biased histogram is efficiently computable; aimed at
join/self-join size estimation, where large frequencies dominate the error.

### V-optimal — V-optimal(V, F) or (F, F)
Choose boundaries minimizing the total within-bucket frequency variance:

```
minimize  sum_b  sum_{i in b} (f_i - avg_b)^2
```

Ioannidis & Christodoulakis (TODS 1993) showed serial histograms (buckets group
values with similar frequencies) optimal for bounding worst-case error in join
results; V-optimal is the variance-minimizing member of that family.
For the value-ordered variant, Jagadish et al. (VLDB 1998) give the DP

```
prefix sums P[i] = sum f_1..f_i,  Q[i] = sum f_1^2..f_i^2
SSE(a..b) = (Q[b] - Q[a-1]) - (P[b] - P[a-1])^2 / (b - a + 1)
E[i][k]   = min_{k-1 <= j < i}  E[j][k-1] + SSE(j+1..i),   E[i][1] = SSE(1..i)
time O(n^2 * beta), space O(n * beta)   (back-pointers recover boundaries)
```

Quadratic in the number of distinct values: fine for thousands, infeasible for
millions without pre-aggregation into micro-buckets or approximation (Guha,
Koudas & Shim give (1+eps)-approximate near-linear algorithms, including
streaming versions).

### MaxDiff — MaxDiff(V, A)
Put the beta-1 boundaries between adjacent values whose source parameter (area)
differs the most. O(n log n) with a sort, or O(n log beta) with a bounded heap,
after one pass to compute per-value frequencies. In Poosala et al.'s experiments
MaxDiff(V, A) and V-optimal(V, A) were the most accurate classes for range
predicates, with MaxDiff far cheaper to construct. EDBS's summary: MaxDiff and
V-optimal beat equi-width and equi-sum in most settings; V-optimal is usually
more accurate but its construction cost limits adoption.

### Refinements
- Curve-fitting / spline synopses inside or instead of buckets (Konig & Weikum,
  VLDB 1999 and SIGMOD 2000), optionally driven by query feedback.
- Intra-bucket index trees that store a few extra bits per bucket to improve
  partial-bucket range estimates (Buccafurri et al., ICDE 2002).

## 3. Approximation inside a bucket

| Assumption | Values in bucket | Frequency of each | Good for |
|---|---|---|---|
| Continuous values | uniformly spread over [lo, hi] as a continuum | f_b over the range length | real-valued domains |
| Uniform spread | d_b distinct values equally spaced from lo to hi | f_b / d_b each | discrete domains; range and equality |
| Point value | all values at one point | f_b | rarely appropriate |

Uniform spread (Poosala et al.) requires storing d_b; it fixes the classic
equality error of the continuous model on integer and date columns.

## 4. Estimation procedures

```
eq(c):     if c is a singleton bucket: its count
           else bucket b containing c: f_b / d_b      (uniform spread)
range(lo <= X <= hi):
           sum of fully covered buckets
         + for each partially covered bucket b:
             f_b * (#assumed values of b inside [lo,hi]) / d_b    (uniform spread)
             or f_b * overlap_len / bucket_len                    (continuous)
ndv in range: sum over buckets of d_b * covered fraction
join(R.a = S.b) via histograms:
           split both at the union of their boundaries; in each aligned piece
           apply |piece_R| * |piece_S| / max(d_R, d_S); sum the pieces
```

Worked example (own data). Values 1..8 with frequencies
`1:2  2:2  3:20  4:2  5:3  6:3  7:4  8:4` (40 rows), beta = 3.

- Equi-width [1-3][4-6][7-8]: counts 24, 8, 8. eq(1) estimate 8 (true 2);
  eq(3) estimate 8 (true 20).
- Equi-depth, about 13 rows per bucket: boundaries land inside value 3 and
  between 4 and 5, giving [1..3] (13 rows), [3..4] (13), [5..8] (14). Value 3
  straddles two buckets; summing its uniform-spread shares gives about
  13/3 + 13/2 = 10.8 (true 20). Equality for 3 stays wrong without singletons.
- Compressed with one singleton: {3: 20} exact; remaining 20 rows in two
  equi-depth buckets [1,2,4,5] (9 rows) and [6,7,8] (11 rows): eq(1) estimate
  2.25 (true 2), eq(3) exact.

The example shows why every production histogram pairs a frequent-value list
with a quantile histogram.

## 5. Construction cost and sampling

- Exact: sort the column (or hash-aggregate value -> frequency, then sort the
  distinct values) — O(N log N) or O(N + n log n). V-optimal adds O(n^2 beta).
- Quantile sketches give equi-depth boundaries in one pass (Greenwald-Khanna,
  SIGMOD 2001; KLL, Karnin, Lang & Liberty, FOCS 2016); KLL is fully mergeable
  across partitions/row groups (GK only in restricted one-way fashion) — the right tool for distributed and columnar engines
  where per-file statistics are combined at plan time.
- From a sample: Chaudhuri, Motwani & Narasayya (SIGMOD 1998) bound the sample
  size needed for an equi-depth histogram whose bucket sizes are within a
  relative error of the target; it grows with the number of buckets and only
  logarithmically with table size, so a fixed-size sample (tens of thousands of
  rows) serves tables of any size for equi-depth.
- Frequent values from a sample are reliable only above roughly 1/sample_size
  frequency; mid-frequency values look like singletons and get lost.
- Block (page) sampling is much cheaper but correlated with physical
  clustering; Chaudhuri, Das & Srivastava (SIGMOD 2004) adaptively increase the
  sample when cross-validation between halves of the sample disagrees.

> **Beyond EDBS:** Production defaults, for orientation. PostgreSQL samples
> 300 x `default_statistics_target` rows (100 by default, hence 30,000 rows),
> keeps up to `target` MCVs and an equi-depth histogram of up to `target + 1`
> bounds over the non-MCV values. DB2 RUNSTATS keeps frequent values plus
> quantiles (defaults `NUM_FREQVALUES = 10`, `NUM_QUANTILES = 20`). SQL Server
> histograms have at most 200 steps; each step stores the upper bound key,
> rows equal to it, rows strictly inside the step, distinct values inside the
> step, and average rows per distinct value. Oracle (12c onward) distinguishes
> frequency, top-frequency and hybrid histograms.

## 6. Maintenance

- **Recompute** on a modification threshold (e.g., PostgreSQL autovacuum
  re-analyzes after 50 rows + 10% of the table changed by default). Simple but
  stale between runs; ascending keys are the classic casualty.
- **Incremental** (Gibbons, Matias & Poosala, VLDB 1997): maintain approximate
  equi-depth and compressed histograms under inserts/deletes. Keep a **backing
  sample** (a uniform sample maintained under updates). When a bucket's count
  exceeds a threshold, split it using the backing sample; merge adjacent
  buckets that became too small; recompute from the backing sample when
  splits/merges cannot restore balance. Cost per update is O(1) amortized plus
  occasional re-derivation.
- **Feedback-driven**: self-tuning histograms (ST-histograms, Aboulnaga &
  Chaudhuri 1999) adjust bucket frequencies from observed selectivities without
  scanning data; STHoles (Bruno, Chaudhuri & Gravano 2001) drills nested "holes"
  into buckets where queries reveal non-uniformity (a hierarchical histogram).
- **Partitions**: histograms do not merge exactly. Keep per-partition stats for
  pruned access and a global synopsis for unpruned plans; build the global one
  from mergeable sketches (HLL for NDV, KLL for quantiles, top-k for MCVs).

## 7. Multi-dimensional histograms

Marginal histograms plus independence fail on correlated columns. The joint
distribution is a d-dimensional frequency array; a multi-dimensional histogram
partitions it into hyper-rectangular buckets.

| Method | Idea |
|---|---|
| Equi-depth multi-dim (Muralikrishna & DeWitt, SIGMOD 1988) | split dimension 1 into equi-depth slabs, each slab on dimension 2, ... |
| MHIST (Poosala & Ioannidis, VLDB 1997) | greedily split the bucket/dimension with the largest MaxDiff; also an SVD-based variant |
| GENHIST (Gunopulos et al., VLDB 2000) | overlapping buckets of decreasing size capture dense regions |
| STHoles (Bruno et al., SIGMOD 2001) | workload-driven nested buckets refined from query results |
| Dependency-based (Deshpande, Garofalakis & Rastogi, SIGMOD 2001) | factor the joint into low-dimensional histograms along a learned dependency structure |
| Multi-dim wavelets (Vitter & Wang, SIGMOD 1999) | threshold coefficients of the d-dim Haar transform of the joint array |

All suffer the curse of dimensionality: bucket count needed for a fixed
accuracy grows exponentially in d. In practice: 2-3 dimensions on explicitly
chosen column groups, or column-group NDV/MCV statistics instead.

## 8. Spatial and spatio-temporal histograms

- Spatial bucket B stores the number of objects whose centroid falls in it and
  their average extent. A window query Q is estimated as
  `sum_B B.num * area(Q intersect B) / area(B)`, assuming uniformity inside B
  (with extents enlarging the effective query). Accuracy depends on how uniform
  each bucket is; Acharya, Poosala & Ramaswamy (SIGMOD 1999) construct buckets
  to be nearly uniform. Histograms give no worst-case guarantee; spatial
  sketches based on AGMS sketches over dyadic intervals do, with polylog space
  and 1/eps^2 dependence (Das, Gehrke & Riedewald, SIGMOD 2004).
- Moving objects with linear motion o(t) = o_s + o_v * t: build the histogram
  in 2d dimensions (reference-time position and velocity); each bucket keeps a
  count and min/max position and velocity per dimension; a predictive window
  query sums the fraction of each bucket expected to intersect the query over
  its time interval. Alternatives: a uniform sample maintained under updates
  (each update is a delete plus insert, needing dynamic sampling schemes), and
  Venn sampling when the query set is known in advance.
- Spatio-temporal distance joins: under the L-infinity norm the dimensions are
  independent and the join selectivity is the product of per-dimension
  selectivities computed from bucket projections; under L2 the estimate
  integrates the probability that a uniformly placed partner falls within the
  distance during the interval.

## 9. Wavelet synopses

Haar decomposition, own example: A = [6, 2, 3, 3, 5, 7, 1, 1].

```
level   averages            detail coefficients ((first - second) / 2)
  3     [6,2,3,3,5,7,1,1]
  2     [4, 3, 6, 1]        [2, 0, -1, 0]
  1     [3.5, 3.5]          [0.5, 2.5]
  0     [3.5]               [0]
W_A = [3.5, 0, 0.5, 2.5, 2, 0, -1, 0]   (overall average, then details coarse -> fine)
```

**Error tree**: internal node c_j holds a coefficient, leaves hold data values.
- A data value is the overall average plus a signed sum of the coefficients on
  its root path (+ if the leaf lies in the coefficient's left half, - if right):
  at most log N + 1 terms. Check d_2 = 3.5 + 0 - 0.5 + 0 = 3.
- A range sum d(l:h) only involves coefficients on the paths to d_l and d_h:
  at most 2 log N + 1 terms; a coefficient contributes
  `(|left leaves in range| - |right leaves in range|) * c_j`, so subtrees fully
  inside the range contribute zero.
- The transform and its inverse are O(N).

**Synopsis = thresholding**: keep B << N coefficients, zero the rest. Range
selectivity from the synopsis touches at most min(B, 2 log N + 1) retained
coefficients; a B-coefficient synopsis expands to an O(B)-bucket histogram in
O(B) time. Matias, Vitter & Wang (SIGMOD 1998) introduced wavelet-based
histograms for selectivity estimation; Vitter & Wang (SIGMOD 1999) handled
sparse multi-dimensional data; Chakrabarti et al. (VLDB 2000/VLDBJ 2001) ran an
approximate relational algebra (select, project, join, aggregates) directly on
coefficient synopses, expanding to tuples only at the end.

| Thresholding | Optimizes | Notes |
|---|---|---|
| Keep B largest of abs(c_j) / sqrt(2^level) | overall L2 (RMS) error, provably optimal | per-value and per-range errors can be large and biased: some regions exact, others flattened to their mean |
| Probabilistic (Garofalakis & Gibbons, TODS 2004) | expected max normalized error / bias via randomized rounding, DP over the tree | randomness means per-instance variance |
| Deterministic DP (Garofalakis & Kumar, TODS 2005) | max or mean (weighted) relative error with sanity bound s, i.e. max_i abs(d_hat_i - d_i) / max(abs(d_i), s) | DP over error-tree nodes indexed by the error entering from ancestors; feasible because tree depth is O(log N) |
| Unrestricted (Guha & Harb, KDD 2005) | weighted Lp error, coefficient values chosen freely | restricting to Haar values is suboptimal for non-L2 metrics |
| Extended wavelets (Deligiannakis et al., TODS 2007) | weighted sum of L2 errors across several measures | shared storage for multi-measure coefficients |
| Streaming (Gilbert et al., TKDE 2003; Cormode, Garofalakis & Sacharidis, EDBT 2006) | top coefficients from AMS sketches of the stream | handles turnstile updates |

Multi-dimensional Haar: *standard* (full 1-d transform per dimension in turn)
vs *nonstandard* (alternate one level per dimension); each d-dim coefficient
has a rectangular support with sign quadrants; error trees become
quadtree-like with up to 2^d - 1 coefficients per node.

Engine use: wavelets fit range-sum-heavy, multi-dimensional, or approximate
query workloads; for plain one-column selectivity, compressed histograms are
simpler and as good. If you use them for estimation, choose a relative-error
thresholding, otherwise small-count regions (the selective predicates that
matter most for plan choice) receive the worst estimates.

## 10. Hierarchical summaries and data reduction context

- B+-trees with a subtree count per child pointer answer range counts in
  O(log n) (ranked trees, Knuth); maintenance touches every ancestor per update.
  Tolerating bounded count error cuts maintenance (an approach used in DEC
  Rdb's estimation, per Antoshenkov). Upper levels of any B+-tree already give a
  coarse equi-depth-like summary for free — an index "dive" estimate.
- Quadtrees, k-d trees and R-trees likewise act as hierarchical spatial
  summaries for selectivity estimation and aggregate queries.
- Hierarchical histograms for hierarchical identifiers (Reiss, Garofalakis &
  Hellerstein, VLDB 2006) and STHoles' nested buckets.
- Data reduction framing (New Jersey data reduction report, Barbara et al.
  1997): **nonparametric** techniques (histograms, clustering, indexes) assume no
  model and adapt to any distribution; **parametric** ones (regression, SVD, DWT)
  fit a model and compress far better when the model fits, badly when it does
  not. Histograms are the default precisely because they degrade gracefully.

## 11. Pitfalls

- Frequent values not separated: equality estimates on the hottest keys wrong.
- Using continuous-value interpolation on integer or date columns (off-by-one
  boundary errors, `<` vs `<=` asymmetry).
- Histogram bounds stored as truncated strings: prefix collisions make buckets
  zero-width; interpolation divides by zero.
- Ignoring NULLs and empty-string conventions in counts.
- Building histograms from a block sample on a clustered column.
- Treating stale histograms as current; record rows-at-collection and scale.
- Merging per-partition histograms by concatenating bounds (wrong quantiles).
- Out-of-range constants returning 0 instead of an extrapolated estimate.

Sources: Histogram p.1714; Data Reduction p.827; Nonparametric Data Reduction
Techniques p.2503; Parametric Data Reduction Techniques p.2684; Discrete
Wavelet Transform and Wavelet Synopses p.1132; Hierarchical Data Summarization
p.1695; Spatiotemporal Selectivity Estimation p.3650; Cost Estimation p.647;
Selectivity Estimation p.3371.
