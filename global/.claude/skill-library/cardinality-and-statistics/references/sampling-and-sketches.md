# Sampling and sketches

Two families of synopses complement histograms. **Samples** keep actual rows,
so any predicate can be evaluated on them, with error that shrinks as
1/sqrt(sample size). **Sketches** are small randomized linear (or max/OR)
projections of a frequency vector that answer one class of query with provable
error, can be maintained under inserts (often deletes), and merge across
partitions and nodes. This file covers both, plus the hardness of
distinct-value estimation, which decides how ANALYZE should compute NDV.

## 1. Synopsis structures: vocabulary and evaluation

A synopsis of data set S is any summary substantially smaller than S
(formally O(|S|^eps) for some eps < 1); the term (Gibbons & Matias) covers
samples, histograms, wavelets, sketches and top-k summaries. "Sketch" usually
means a random-projection synopsis. Judge a synopsis on:

1. **Coverage** — which queries it answers.
2. **Answer quality** — error and confidence (eps, delta).
3. **Space** — ideally polylogarithmic in |S|.
4. **Per-item update time** — the stream/ingest cost.
5. **Query time**.

Add two engine-specific criteria: **mergeability** (combine per-partition or
per-node synopses exactly) and **deletion support** (turnstile updates).

## 2. Sampling designs

| Design | Mechanism | Strength | Weakness |
|---|---|---|---|
| Simple random, with replacement (SRSWR) | n independent draws, prob 1/N each | simplest analysis | duplicates |
| Simple random, without replacement (SRSWOR) | n distinct rows | slightly better accuracy | analysis a bit harder; difference negligible when n << N |
| Bernoulli(p) | each row independently with prob p | trivially parallel, mergeable | sample size random |
| Reservoir (Vitter, TOMS 1985) | keep first n; row t enters with prob n/t, evicting a uniform victim | one pass, unknown N, uniform | sequential; use skip-based Algorithm Z for speed |
| Cluster (block/page) | sample whole pages/blocks | I/O-cheap | correlated with physical clustering; effective sample size much smaller |
| Stratified | partition into strata, sample each | guarantees small groups appear; lower variance under skew | strata must be chosen; reweighting needed |
| Two-stage | sample blocks, then rows within them | balances I/O and correlation | variance depends on intra-block homogeneity |

Engine notes:
- ANALYZE in most systems is two-stage: pick blocks, then reservoir-sample
  rows from them, giving a fixed-size sample independent of table size.
- Block sampling on a column correlated with physical order (load date,
  sequence ids) under-represents values and inflates NDV error; detect by
  comparing estimates from two independent block subsets and enlarging the
  sample when they disagree (Chaudhuri, Das & Srivastava, SIGMOD 2004), or use
  a bi-level Bernoulli scheme (Haas & Konig, SIGMOD 2004).
- Stratified samples are what approximate-query engines keep for GROUP BY
  workloads (small groups otherwise vanish); the optimizer can reuse them.
- Dynamic samples under updates need special maintenance (each update is a
  delete plus insert); a backing sample also feeds incremental histograms.

## 3. Estimators and their error

For a linear aggregate (COUNT, SUM, AVG) over a uniform sample of n rows, the
estimator is unbiased (scaled by N/n for COUNT/SUM) and, by the central limit
theorem, approximately normal with standard error proportional to
sigma/sqrt(n): halving error costs 4x the sample. For non-linear functions
(MAX, distinct counts) there is no general unbiased estimator; bound the tails
using E[X] and Var[X].

Tail bounds, weakest to strongest:

```
Markov     (X >= 0):           Pr[X >= a] <= E[X] / a
Chebyshev:                     Pr[|X - E X| >= a] <= Var[X] / a^2
Chernoff  (sum of independent 0/1 trials, mu = E X, 0 < d < 1):
                               Pr[|X - mu| >= d*mu] <= 2 * exp(-mu * d^2 / 3)
```

Illustration: each of N rows is kept with probability 1/2, X = sample size,
E[X] = N/2. Bound on Pr[X >= 3N/4]: Markov gives 2/3; Chebyshev gives 4/N;
Chernoff gives 2*exp(-N/24) — exponentially small. Use Chernoff-style bounds to
size samples when a guarantee is needed.

Selectivity from a sample: sel_hat = k/n for k matches among n sampled rows;
relative standard error is about sqrt((1 - sel)/(n * sel)), which explodes for
small sel. A predicate with selectivity below about 1/n usually yields k = 0;
report "less than 1/n" and fall back, never 0.

The median-of-means trick, used throughout the sketch literature: average m
independent copies of an unbiased estimator to cut variance by m (Chebyshev
then bounds error eps with constant probability), and take the median of
O(log 1/delta) such averages to drive the failure probability to delta.

## 4. Distinct values: why sampling fails

NDV is the most important and the hardest statistic. Example of the
difficulty (adapted from Gibbons's FM entry): a 33% sample containing 6 distinct
values is equally consistent with a population of 6 distinct values (each
repeated) and one of about 18 (each sampled value representing several unseen
ones). No estimator can tell them apart.

Charikar, Chaudhuri, Motwani & Narasayya (PODS 2000) made this precise: any
estimator that examines r of n rows must, on some input, have ratio error at
least on the order of sqrt(n/r) with non-trivial probability. Their GEE
estimator matches the bound:

```
D_GEE = sqrt(n/r) * f1 + sum_{j >= 2} f_j        f_j = number of values seen exactly j times
```

Other practical estimators: Haas & Stokes's Duj1 (smoothed jackknife),
`D = n_s * d / (n_s - f1 + f1 * n_s / N)` where d = distinct in sample, n_s =
sample size, N = table rows; and hybrids that switch estimators based on
observed skew (Haas, Naughton, Seshadri & Stokes, VLDB 1995).

> **Beyond EDBS:** PostgreSQL's ANALYZE uses the Haas-Stokes Duj1 estimator on
> its 300 x statistics-target row sample and stores the result either as an
> absolute count or, when it appears to scale with the table, as a negative
> fraction of the row count.

Engineering rule: if NDV matters (join and GROUP BY estimates), compute it with
a **full-scan streaming sketch** (HLL) during ANALYZE or at ingest/compaction
time, and use samples only for MCVs and histograms. Columnar formats make this
cheap: keep an HLL per column per row group/file and merge.

## 5. Flajolet-Martin and its descendants (distinct counting)

### FM / probabilistic counting (Flajolet & Martin, JCSS 1985)
Hash each value to a bit position with a geometric distribution (position i
with probability 2^-(i+1)); set that bit in an m-bit vector M,
m about log2 |D|. Duplicates set the same bit, so M is insensitive to repetition.
Let Z be the index of the lowest unset bit; E[Z] is about log2(0.77351 * F0), so

```
F0_hat = 2^Z / 0.77351
```

Averaging Z over k independent hash functions gives standard error O(1/sqrt k)
with k*m bits; O(k) work per item.

Space optimization: the k bit vectors share a prefix of 1s and a suffix of 0s
around log2 F0; interleave their bits and store only the mixed "fringe" plus
the length of the all-ones run — expected log2 m + O(k log k) bits.

### PCSA (stochastic averaging)
One hash function; its low log2 k bits choose one of k bit vectors, the rest
choose the geometric position. Estimate `k * 2^(mean Z) / 0.77351`. O(1) work
per item, standard error about 0.78/sqrt(k).

### Variants
- Alon-Matias-Szegedy: pairwise-independent linear hashes `(a*v + b) mod p`,
  track only the maximum set position R, estimate 2^R; provable without
  idealized hashing (constant-factor accuracy).
- LogLog (Durand & Flajolet, ESA 2003): each of k buckets stores only the max
  position (log log bits), standard error about 1.30/sqrt(k) (about
  1.05/sqrt(k) with the truncation rule of SuperLogLog).
- Deletions: replace bits by counters (log-factor space).
- Sliding windows: store, per bit, the sequence number of the latest item that
  set it; a bit counts as set if that number is inside the window.
- Distribution: identical hash functions at every observer; bitwise OR of the
  vectors equals the vector of the combined stream, so the union estimate has
  the same guarantee. This is exactly what a parallel ANALYZE or a distributed
  COUNT(DISTINCT) needs.
- Duplicate-insensitive counting generalizes: count items by hashing their
  unique ids; supports robust multi-path aggregation in sensor networks.

Empirically under 15% error at k = 20 and under 10% at k = 64; error falls only
as 1/sqrt(k), so 1% needs about 100x the space of 10%.

> **Beyond EDBS — HyperLogLog** (Flajolet, Fusy, Gandouet & Meunier, AofA
> 2007): m = 2^p registers; for hash h(x), the first p bits select register j,
> and register j keeps the maximum of rho(rest) = position of the leftmost 1.
> Estimate with a bias-corrected *harmonic* mean,
> `E = alpha_m * m^2 / sum_j 2^(-M[j])`, standard error about 1.04/sqrt(m)
> (p = 14 -> 16384 registers, about 0.8%, 12 KB at 6 bits/register). Use linear
> counting `m * ln(m / V)` (V = empty registers) when E is small. HLL++ (Heule,
> Nunkesser & Hall, EDBT 2013) adds a 64-bit hash (no large-range correction),
> empirical bias correction in the small/medium range, and a sparse encoding for
> low cardinalities. Merge = register-wise max; union is exact, intersection via
> inclusion-exclusion is noisy (use KMV/theta sketches when intersections
> matter). HLL is the standard NDV synopsis in analytical engines.

```rust
struct Hll { p: u8, regs: Vec<u8> }            // 2^p registers
fn add(&mut self, h: u64) {
    let j = (h >> (64 - self.p)) as usize;
    let w = (h << self.p) | (1u64 << (self.p - 1)); // guard bit bounds rho
    let rho = w.leading_zeros() as u8 + 1;
    self.regs[j] = self.regs[j].max(rho);
}
```

## 6. Frequency moments

Stream of items from [m] with frequencies f_i. The k-th frequency moment is
`F_k = sum_i f_i^k`: F0 = number of distinct values, F1 = stream length, F2 =
self-join size (repeat rate, Gini's homogeneity index), F_inf = max f_i.
Database uses: F0 for NDV without sorting, F2 for self-join size and for the
error terms of join-size estimates, F_k (k >= 2) as skew indicators that guide
partitioning choices.

Space for (eps, delta)-approximation in one pass (Alon, Matias & Szegedy,
STOC 1996, and successors): F2 needs about O(log(1/delta)/eps^2) words (times
log n + log m bits), with a nearly matching lower bound; F_k for k > 2 needs
about m^(1 - 2/k) (polylog factors aside), polynomial in m; F_inf needs
Theta(m). Lower bounds come from communication complexity. So moments up to 2
are cheap to sketch; higher moments and exact maxima are not.

## 7. AMS ("tug-of-war") sketch: join and self-join size

Join size of F and G on attribute a is the dot product of frequency vectors,
`|F join G| = f . g`. Pick a random vector xi of +-1 entries with E[xi_i] = 0,
4-wise independent (generated on the fly from a small seed by a suitable hash,
so nothing of size m is stored). Elementary sketches:

```
X_F = sum over tuples t in F of xi(t.a)     (= f . xi)
X_G = sum over tuples t in G of xi(t.a)     (= g . xi)
X   = X_F * X_G
E[X] = f . g                                 (pairwise independence suffices)
Var[X] <= 2 * F2(F) * F2(G)                 (needs 4-wise independence)
```

One counter per relation per copy; each arriving tuple adds xi(value) — an O(1)
update in any order, inserts and deletes alike, so sketches of distributed
pieces add. Accuracy: average about 8 Var[X] / (eps^2 E[X]^2) independent
copies to get relative error eps with constant probability, then take the
median of about 2 log(1/delta) such averages. Self-join size is the special
case F = G.

Implication: space depends on F2(F) F2(G) / (f.g)^2 — joins much smaller than
the self-join sizes of their inputs (low-selectivity joins, skew on different
keys) need large sketches. Experiments in the EDBS entry (Zipf data, 100k
tuples, domain 16k) show acceptable self-join error at around 2000 words, with
error decreasing as skew increases. Pseudo-random generator choice matters in
practice (Rusu & Dobra, TODS 2007).

## 8. Count-Min sketch: frequencies, ranges, quantiles, heavy hitters

d x w counter array, d pairwise-independent hashes h_j: [n] -> [w].

```
w = ceil(e / eps),  d = ceil(ln(1/delta))
update(i, c):  for j in 1..d: CM[j][h_j(i)] += c            # O(d)
point(i):      min_j CM[j][h_j(i)]
guarantee (non-negative counts): a_i <= est_i, and with prob >= 1 - delta,
               est_i <= a_i + eps * ||a||_1
```

Proof sketch: each row overestimates by expected ||a||_1 / w; Markov gives
probability <= 1/e of exceeding eps ||a||_1 per row; the minimum fails only if
all d rows fail, e^-d <= delta. For Zipf skew z > 1 the space needed for the
same guarantee drops to about O(eps^(-1/z) ln(1/delta)), and that is optimal.

Derived queries:
- **Range sums**: keep log n sketches over dyadic ranges (level k aggregates
  blocks of 2^k values); any range decomposes into at most 2 log n dyadic
  ranges; space O((log^2 n / eps) log(1/delta)) for error eps ||a||_1.
- **Quantiles**: binary search over dyadic range sums (with error budget split
  across the queries).
- **Heavy hitters** (a_i >= phi ||a||_1): descend the dyadic hierarchy, expanding
  only heavy ranges; reports every item above (phi + eps) and, w.h.p., none below phi.
- **Inner product / join size**: min over rows of the row-wise dot product of
  two sketches with the same hashes; additive error eps ||a||_1 ||b||_1, versus
  AMS's eps ||a||_2 ||b||_2 at 1/eps^2 space. CM is often much better than its
  worst-case bound in practice (Rusu & Dobra 2007).
- **Linearity**: sketch(a + b) = sketch(a) + sketch(b), sketch(lambda a) =
  lambda sketch(a); ship sketches instead of data between nodes.
- **Conservative update** (Estan & Varghese): on insert, raise each of the d
  counters only up to est + c; tighter estimates, but no deletions and more
  update work.
- Replace counters by FM/HLL synopses to count distinct items per key.

Typical parameters: d = 5, w in the hundreds to thousands; millions of updates
per second on commodity CPUs. Engine uses: MCV/heavy-hitter detection for skew
handling, join-size estimation between columns sketched with shared seeds,
frequency estimates for values outside the MCV list.

> **Beyond EDBS:** for top-k with counts, deterministic counter-based summaries
> (Misra-Gries; SpaceSaving, Metwally, Agrawal & El Abbadi, ICDT 2005) are
> simpler and mergeable; for quantiles, KLL is the space-optimal mergeable
> sketch and the practical choice for distributed equi-depth boundaries.

## 9. Stable distributions and random projections

A symmetric alpha-stable variable (0 < alpha <= 2) satisfies: for i.i.d. copies
Z_1, Z_2, `c1 Z1 + c2 Z2` is distributed as `(|c1|^alpha + |c2|^alpha)^(1/alpha) Z`.
alpha = 2 is Gaussian, alpha = 1 Cauchy. Consequence: projecting a vector u
onto k random vectors with i.i.d. S(alpha, 1) entries produces k samples from
S(alpha, ||u||_alpha^alpha); estimating the scale recovers the l_alpha norm
(the alpha-th frequency moment) or, by linearity, the l_alpha distance between
two streams (Indyk, JACM 2006).

- Streaming (turnstile model): keep x_j += r_ij * delta for each update (i, delta);
  maintainable with deletions; pseudo-random generation of r_ij from a seed.
- Scale estimators: arithmetic mean of squares (alpha = 2 only), sample median,
  geometric mean, harmonic mean (small alpha) — geometric mean has good
  variance and k = O(log n / eps^2) suffices for pairwise distances of n points,
  matching Johnson-Lindenstrauss for alpha = 2 (Li, SODA 2008).
- As alpha -> 0, the alpha-th moment approaches the Hamming norm, i.e. the number
  of non-zero entries: distinct counting under deletions (Cormode, Datar, Indyk
  & Muthukrishnan, VLDB 2002).
- Sampling stable variates exactly needs a trigonometric transform of a uniform
  and an exponential variable (Chambers-Mallows-Stuck); very sparse projections
  replace them with a mixture of a point mass at 0 and a Pareto tail (Li, KDD 2007).
- LSH for l_alpha (Datar, Immorlica, Indyk & Mirrokni, SoCG 2004) is built on
  the same property — relevant to vector search, see the similarity-indexing skill.

## 10. Karp-Luby sampling (probabilistic data)

Estimating the probability that a DNF formula over independent Boolean
variables is true (lineage of a probabilistic query answer) is #P-hard.
Naive Monte Carlo needs O(log(1/delta) / (p eps^2)) samples, exponential when p
is tiny. Karp-Luby samples only from (assignment, satisfied clause) pairs:
pick clause C_i with probability P(C_i)/sum_j P(C_j), force its literals true,
draw the other variables from their marginals, and count the sample as a hit if
C_i is the lowest-numbered clause satisfied. The hit rate times sum_j P(C_j)
estimates the probability, with n = ceil(3 m log(2/delta) / eps^2) samples for m
clauses — polynomial. Relevant to estimation in probabilistic databases.

## 11. Choosing a synopsis for an optimizer

| Need | Synopsis | Why |
|---|---|---|
| NDV per column / column group | HLL (full scan) | mergeable, 1% error in KBs, insensitive to duplicates |
| Equality on frequent values | MCV list from sample, or SpaceSaving/CM | exact-ish on heavy hitters |
| Range selectivity | equi-depth from KLL or sample, plus MCVs | bounded per-bucket error |
| Arbitrary or correlated single-table predicates | stored row sample | evaluates any expression |
| Join size between two columns | MCV matching; AMS/CM with shared seeds | captures skew alignment |
| Per-partition stats merged at plan time | HLL + KLL + top-k | all mergeable (HLL exactly; KLL/Misra-Gries keep their error bounds) |
| Streaming / continuously updated tables | CM, AMS, HLL (inserts), stable projections (deletes) | O(1) updates |

## 12. Pitfalls

- Different hash seeds or functions on different nodes or file writers: merges
  are meaningless. Version the seed with the format.
- Weak hashes on sequential integers: FM/HLL position distribution collapses.
- 32-bit hashes for HLL beyond about 10^8 distinct values: collisions bias low.
- Scaling sample NDV linearly by N/n: overestimates when values repeat.
- Treating CM point estimates as unbiased: they are one-sided overestimates;
  subtract nothing unless using a debiased variant.
- AMS with fewer copies than Var/E^2 demands: estimates can be negative.
- Reservoir sampling with a poor RNG or modulo bias: non-uniform samples.
- Zero matches in a sample reported as selectivity 0.

Sources: Data Sampling p.840; Sampling Techniques for Statistical Databases
p.3274; Synopsis Structure p.3864; Data Sketch/Synopsis p.848; FM Synopsis
p.1487; Frequency Moments p.1518; AMS Sketch p.99; Count-Min Sketch p.653;
Stable Distribution p.3690; Karp-Luby Sampling p.2054; Data Reduction p.827.
