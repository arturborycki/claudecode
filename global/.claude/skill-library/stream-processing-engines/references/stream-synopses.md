# Synopses on streams: sampling, heavy hitters, quantiles, histograms, wavelets, sketches, distributed monitoring

Read this when an operator must answer a holistic aggregate (median,
percentile, top-k, count-distinct, frequency) over an unbounded or windowed
stream in bounded memory, when you need mergeable partial state for
distributed or sliced aggregation, or when you are choosing a summary that
survives deletes (turnstile streams). For optimizer statistics built from
these structures, see `cardinality-and-statistics`. This file is about the
in-engine, continuous-query use.

---

## 1. The one-pass model and its limits

A one-pass (streaming) algorithm reads `x1, x2, …` once, left to right,
maintaining a data structure. Its two costs are **space** and **per-item
time**, both as functions of stream length N (or of the bits needed to store
the input). Target: sublinear, ideally polylogarithmic, in N. A DFA is the
trivial O(1) example. Multi-pass algorithms (P passes) trade passes for space.

Lower bounds come from communication complexity. Many exact problems need
Ω(N) (or Ω(domain)) space deterministically:
- exact median in p passes needs Ω(N^{1/p}) memory (Munro–Paterson 1980);
- exact frequent items in one pass need Θ(min(|A|, N)) space;
- exact or deterministic-approximate frequency moments `F_k` (k ≠ 1) need Ω(m).

So the engine's toolkit is **approximation (ε)** plus **randomization (δ)**.
Two families are typical. *Sampling* keeps representative items.
*Sketching* keeps random projections (linear maps) of the frequency vector.

Selection axes for any synopsis:

| Axis | Question |
|---|---|
| Update model | cash register only, or turnstile (deletes / negative weights)? (`stream-semantics-and-cql.md` §1.1) |
| Error type | additive εN, additive ε‖f‖₂, relative (1±ε), rank error εn |
| Deterministic vs randomized | randomized needs seeds checkpointed for replay |
| Mergeable | can two summaries of disjoint inputs combine with no loss in guarantee? (needed for partitions, slices, distributed sites) |
| Order sensitivity | deterministic counter/quantile schemes vary with input order; linear sketches do not |
| Window support | whole stream, sliding window (count/time), exponential decay |

---

## 2. Sampling

### 2.1 Reservoir sampling (Vitter, TOMS 1985)

Uniform sample of size n without replacement, N unknown:
```
for t = 1..n:   R[t] = a_t
for t > n:      with prob n/t: R[rand(1..n)] = a_t
```
Invariant: after t items, R is a uniform n-subset of `a_1..a_t`. With
replacement, run n independent size-1 reservoirs. Optimization: draw the
*skip length* to the next accepted item directly from its distribution, so
per-item cost is paid only for accepted items. That is O(n(1 + log(N/n)))
expected work overall.

Uses: selectivity estimation (`|A ∩ R|·N/|R|` estimates |A|), quantiles
(sample size Θ(ε⁻² log δ⁻¹) for εN rank error), frequent elements. The
sample is query-agnostic, so the predicate can arrive after the stream.

### 2.2 Sample-and-count (AMS)

For frequency moment `F_k = Σ_j f_j^k`: pick a uniformly random position p
(reservoir), count `X = |{q ≥ p : a_q = a_p}|`. Then `Y = N·(X^k − (X−1)^k)` is
unbiased for F_k with bounded variance. Average and median independent copies
for (ε, δ). The same technique gives near-optimal space for empirical
**entropy** `−Σ (f_j/N) log(f_j/N)` (Chakrabarti, Cormode, McGregor 2007).

### 2.3 Distinct sampling (Gibbons, VLDB 2001; Gibbons–Tirthapura)

Uniform samples miss rare values (one dominant id hides 999 singletons).
Sample *values*, not occurrences, with a hash fixed in advance:
```
level ℓ = 0; D = {}
on x: if h(x) < 2^-ℓ: D.add(x) (with any per-value aggregate)
      while |D| > n: ℓ++; evict x ∈ D with h(x) ≥ 2^-ℓ
distinct-count estimate = |D| · 2^ℓ
```
Each distinct value is in D with probability 2^-ℓ, independent of its
multiplicity. Limited-independence hashes suffice in practice. The weighted
generalization (range sampling; Pavan–Tirthapura) reduces weighted to
unweighted sampling. Distinct samples over a hash are **mergeable**: union,
then raise the level.

### 2.4 Sliding windows, decay, deletions

- Sampling from a moving window (Babcock, Datar, Motwani, SODA 2002). Items
  expire, so a fixed reservoir drains. Keep candidate successors (chain
  sampling) or random priorities with dominance pruning (priority sampling),
  using expected logarithmic memory.
- Distinct sampling over windows: keep, at each sampling level, a fixed number
  of the most recent sampled values.
- **Any decay function reduces to sliding windows** (Cohen & Strauss, PODS
  2003). So window-capable samplers support polynomial and exponential decay.
- Turnstile streams empty samples through deletions. Use dynamic (inverse)
  sampling built on linear sketches (Ganguly 2007; Cormode, Muthukrishnan,
  Rozenbaum, VLDB 2005; Frahling, Indyk, Sohler 2005).

---

## 3. Frequent items (heavy hitters)

Problem: report items with `f_i > φN`. At most ⌊1/φ⌋ such items exist.
ε-deficient version (Manku & Motwani 2002): report every item with
`f_i > φN`, none with `f_i < (φ−ε)N`, with estimates within εN.

### 3.1 Counter-based (cash register; deterministic; fast)

**Misra–Gries / Frequent** (Misra & Gries 1982; rediscovered by Demaine et
al. 2002 and Karp et al. 2003), with k counters:
```
on x: if x in C: C[x]++
      elif |C| < k: C[x] = 1
      else: decrement every counter; drop zeros     # O(1) amortized with grouped structure
estimate f̂(x) = C.get(x, 0);   f(x) − N/(k+1) ≤ f̂(x) ≤ f(x)
```
Generalizes Boyer–Moore majority (one counter). It underestimates. Reporting
all k monitored items yields many false positives.

**Lossy Counting** (Manku & Motwani, VLDB 2002): buckets of width ⌈1/ε⌉.
Entry (item, f, Δ). A new item in bucket b gets `(x, 1, b−1)` (benefit of the
doubt). At bucket boundaries, delete entries with `f + Δ ≤ b`. The stored
f never overestimates and underestimates by ≤ εN (`f ≤ f_true ≤ f + Δ`);
report items with `f ≥ (φ−ε)N`. Space O((1/ε) log(εN)).
**Sticky Sampling** is the probabilistic variant with space
O((1/ε) log(1/(φδ))).

**SpaceSaving** (Metwally, Agrawal, El Abbadi, ICDT 2005), with m counters:
```
on x: if x monitored: count[x]++
      else: y = argmin count; replace y by x; err[x] = count[y]; count[x] = count[y] + 1
guarantee: f(x) ≤ count[x] ≤ f(x) + err[x],  err ≤ min ≤ N/m
```
The *stream-summary* structure (buckets of equal count in a doubly linked list,
items hanging off buckets) gives O(1) increment and O(1) find-min. The error
bound tightens with skew. Every item with `f > N/m` is monitored. In the
comparison studies reported by EDBS (Cormode & Hadjieleftheriou 2008/2010;
Metwally's experiments), SpaceSaving is the most accurate counter-based method
on insert-only streams. It is often 5–10× faster than the fastest sketch with
much less memory.

### 3.2 Sketch-based (turnstile; linear; mergeable)

**Count-Min** (Cormode & Muthukrishnan, LATIN 2004 / J. Alg 2005): a d × w
array with pairwise-independent hashes `h_1..h_d`.
```
update(x, c):  for j: CM[j][h_j(x)] += c
query(x):      min_j CM[j][h_j(x)]
w = ⌈e/ε⌉, d = ⌈ln(1/δ)⌉:  f(x) ≤ f̂(x) ≤ f(x) + ε‖f‖₁  w.p. ≥ 1 − δ   (non-negative frequencies)
```
For general turnstile, use the median instead of the min (with a larger error
term). Heavy hitters under deletions: keep CM sketches over a dyadic
hierarchy of the domain and descend only into heavy ranges. Count-Min also
gives quantiles (O((1/ε) log² n · log(log n/δ)) space) by dyadic range
counting, and it handles weighted updates and distribution for free: add
sketches cell-wise.

**Count sketch / "L2 count sketch"** (Charikar, Chen, Farach-Colton 2002):
±1 signs per row and a median estimator, with error ε‖f‖₂. That is tighter on
skewed data, where ‖f‖₂ ≪ ‖f‖₁. This is the structure the streaming histogram
algorithms use (§5).

**Group testing** (GroupTest; Cormode & Muthukrishnan, PODS 2003): per group,
⌈log|A|⌉ + 1 counters (total + one per id bit). A majority item's bits are
read off counters exceeding half the total. Hash items into O(1/φ) groups,
with repetitions. It handles weighted inserts and deletes and suppresses false
positives by cross-checking groups. It returns hot items, not frequencies.

**Multistage filters** (Estan & Varghese, TOCS 2003) and hCount (Jin et al.
2003): CM-like counters. An item whose minimum counter passes the threshold is
promoted to exact *flow memory*. Conservative update (increment only the
minimum counters) reduces overestimation but breaks deletions.

### 3.3 Variants

- *Sliding windows*: multi-level copies of Misra–Gries over dyadic
  sub-windows (Arasu & Manku, PODS 2004; space is 1/ε times a squared-log
  factor for fixed windows, more for variable windows that need mergeable
  copies), or counter schemes that expire occurrences directly (Lee & Ting,
  PODS 2006, O(1/ε) space; later O(1) update time using an expiry-ordered
  linked list).
- *Exponential decay*: scale-free implementation by inflating new weights by
  `e^{λt}` (Cormode, Korn, Tirthapura, ICDE 2008).
- *Distributed*: sketches add. Misra–Gries and SpaceSaving are made mergeable
  (Agarwal et al., PODS 2012, "Mergeable summaries"): add counters, then
  subtract the (k+1)-th largest from all and drop non-positive.
- *Hierarchical heavy hitters* over multi-dimensional prefixes (e.g., IP
  subnets): Cormode, Korn, Muthukrishnan, Srivastava (SIGMOD 2004).

---

## 4. Quantiles

The φ-quantile of n items is the element with rank ⌈φn⌉. An **ε-approximate
quantile summary** answers any φ with an element whose rank is within
[(φ−ε)n, (φ+ε)n]. Trivial lower bound Ω(1/ε). The best deterministic upper
bounds are O((1/ε) log(εn)) or O((1/ε) log U).

| Algorithm | Space | Model | Notes |
|---|---|---|---|
| Random sample | Θ(ε⁻² log δ⁻¹) | cash register | simplest; big |
| MRL (Manku, Rajagopalan, Lindsay 1998/99) | O((1/ε) log²(εn)) | cash register | first deterministic one-pass |
| Greenwald–Khanna (SIGMOD 2001) | O((1/ε) log(εn)) | cash register, comparison-based | best for large universe, moderate n |
| q-digest (Shrivastava et al. 2004) | O((1/ε) log U) | cash register over integer universe [0, U) | simple, mergeable; best for huge n, small U |
| Count-Min dyadic | O((1/ε) log² n · log(log n/δ)) | **turnstile** | supports deletes and updates |
| Biased quantiles (Cormode et al., PODS 2006) | O((1/ε) log U log(εn)) | cash register | relative rank error near tails (p99.9) |

**GK in brief.** Keep tuples `(v_i, g_i, Δ_i)` sorted by v, where
`g_i = rmin(v_i) − rmin(v_{i−1})` and `Δ_i = rmax(v_i) − rmin(v_i)`, so
`rmin(v_i) = Σ_{j≤i} g_j`. Invariant: `g_i + Δ_i ≤ ⌊2εn⌋`.
Insert v before the first larger element as `(v, 1, ⌊2εn⌋)` (or Δ=0 at the
ends). Periodically merge tuple i into i+1 when
`g_i + g_{i+1} + Δ_{i+1} ≤ ⌊2εn⌋` (a band structure decides which merges
preserve the space bound). To query rank r, return a v_i with
`r − εn ≤ rmin(v_i)` and `rmax(v_i) ≤ r + εn`.

**q-digest in brief.** A complete binary tree over [0, U). Nodes hold counts.
With compression parameter k, keep only nodes v with `count(v) ≤ ⌊n/k⌋`
(leaves exempt) and `count(v) + count(parent) + count(sibling) > ⌊n/k⌋` (root
exempt). Compress bottom-up by folding light sibling pairs into the parent.
Size ≤ 3k, rank error ≤ (log U / k)·n. Merge = add counts node-wise, then
compress. That is why q-digest is the natural choice for sensor and tree
aggregation.

Practical notes from the EDBS entry: Cormode et al. ("Holistic UDAFs at
streaming speeds", SIGMOD 2004) kept up with ~2 Gbit/s (~310k packets/s) on
2004 commodity hardware. On skewed value distributions, a small rank error can
still mean a large *value* error at the tails. Deterministic schemes vary
with input order, and sketches do not.

Extensions: distributed (q-digest merges with the same space; GK extension
grows to O((1/ε) log³ n)); sliding windows (Lin et al. ICDE 2004
O(1/ε² + (1/ε) log(ε²N)); Arasu–Manku O((1/ε) log(1/ε) log N)); duplicate-
insensitive quantiles for multipath aggregation (via sketches, §8).

> **Beyond EDBS:** KLL (Karnin, Lang, Liberty, FOCS 2016) is a randomized,
> fully mergeable compactor-based quantile sketch with O((1/ε)·log log(1/δ))
> space (O((1/ε)·sqrt(log(1/δ))) for the simple all-compactor variant),
> optimal for the comparison model. It is the default in Apache
> DataSketches and in several engines. t-digest (Dunning) gives good empirical
> tail accuracy with no worst-case guarantee. DDSketch (Masson et al., VLDB
> 2019) gives *relative value error*, which matches latency-SLO use. GK is
> not known to merge with its guarantee, so prefer KLL or q-digest when
> partials must combine (panes, partitions, sites).

---

## 5. Histograms on streams

A B-bucket histogram partitions [0, N) into intervals with one height each.
For sum-squared error the optimal height is the bucket mean. Equi-width
histograms are trivial to maintain. *V-optimal* (variable-boundary,
min-SSE) histograms are found offline by dynamic programming:
```
best[k][j] = min_{i<j} best[k−1][i] + SSE(i, j)     # SSE via prefix sums of A and A²
O(N² B) time, O(N B) space
```
Equi-depth histograms are quantile summaries (§4).

Streaming near-optimal histograms (Gilbert, Guha, Indyk, Kotidis,
Muthukrishnan, Strauss, STOC 2002; Guha, Koudas, Shim, TODS 2006): target
error `≤ (1+ε)·OPT`.
1. Track the top `B₁ = poly(B log N / ε)` Haar wavelet coefficients R of A
   (§6).
2. Greedily grow a *robust* representation H_rob ⊆ R by adding Θ(B log N)
   largest remaining terms while that significantly reduces `‖R − H_rob‖`.
3. Run the DP restricted to H_rob's boundaries to get H.

Correctness: either H_rob = R (wavelet energy decays fast and R ≈ A), or H_rob
cannot be improved much by any B−1 extra boundaries, so the optimal B-bucket
histogram is not much better. Space and per-item time are
poly(B log N/ε)·log(1/δ). In the time-series (ordered) model the wavelet
coefficients come from a log N-depth pairing tree in O(1) amortized time. In
the turnstile model, updates map to O(log N) coefficient updates fed into an L2
count sketch.

Uses: selectivity estimation for re-optimization of continuous queries,
approximate answers, visualization.

---

## 6. Wavelets on streams

Haar transform of a = [2,2,0,2,3,5,4,4]. Average pairs and keep half-differences
as detail coefficients, recursively. The result is
`w = [11/4, −5/4, 1/2, 0, 0, −1, −1, 0]` (overall average, then details from
coarse to fine). The *error tree* has coefficients as internal nodes and data
as leaves:
- reconstructing `a[i]` needs only the log N + 1 coefficients on its root path;
- updating `a[i]` changes only those log N + 1 coefficients;
- coefficient supports at level l are the 2^l dyadic ranges of length N/2^l.

With normalization (scale level-l coefficients by sqrt(N/2^l)) the basis is
orthonormal. Then energy is preserved (Parseval), and keeping the B largest
normalized coefficients is the optimal B-term approximation in L2. Extends to d
dimensions with dyadic hyper-rectangle supports.

Streaming results:
- **Ordered (time-series) model**: keep the B best completed coefficients plus
  log N + 1 *straddling* partial coefficients (one per level). As each item
  arrives, update the straddlers. When a straddler completes, compare it
  against the top-B set and start a new one. This maintains the top B
  **exactly** in O(B + log N) space and time per item (Gilbert, Kotidis,
  Muthukrishnan, Strauss, VLDB 2001 / TKDE 2003). Thresholding for non-L2
  error metrics is possible in this model (Guha & Harb 2005).
- **Turnstile model**: recovering the exact top B needs nearly linear space
  (lower bound). Approximate with AMS sketches. GKMS estimates every
  coefficient's inner product from one sketch: polylog space but query time
  superlinear in N (and exponential in d). The Group-Count Sketch (Cormode,
  Garofalakis, Sacharidis, EDBT 2006) sketches the *coefficient vector*
  directly (each data update becomes O(log N) coefficient updates). It
  hash-groups dyadic ranges, keeps an AMS counter per sub-bucket, and
  binary-searches down a hierarchy of groups toward high-energy coefficients.
  Space, update and query are all polylogarithmic, and it extends to d
  dimensions.

**AMS sketch** (Alon, Matias, Szegedy 1996; join-size tracking with Gibbons,
PODS 1999): an atomic sketch `Σ_i a[i]·ξ(i)` with four-wise independent ±1
variables ξ. The product of two atomic sketches is an unbiased estimate of
⟨a, b⟩. Median of O(log 1/δ) means of O(1/ε²) copies gives
`|Z − ⟨a,b⟩| ≤ ε‖a‖₂‖b‖₂`. Self-join (F₂) and join-size estimation over
streams for continuous query optimization follow directly.

---

## 7. Sliding-window counting and decay

> **Beyond EDBS detail (paper is in the bundle's reading lists):** *Exponential
> histograms* (Datar, Gionis, Indyk, Motwani, SODA 2002) count the 1s in the
> last N items within relative error ε using O((1/ε) log² N) bits. Buckets
> hold power-of-two counts with timestamps. At most about 1/(2ε) + 1 buckets of
> each size are kept, merging the two oldest of a size when exceeded. Only the
> oldest bucket is uncertain (half its count is assumed in-window). They
> generalize to sums of bounded integers and underpin windowed variance and
> k-median. Use them when an aggregate over a count/time window must be
> approximate in o(window) memory. With panes (`windows-and-punctuations.md`
> §2.1) you get exact answers at O(window/slide) partials instead.

---

## 8. Distributed streams and in-network aggregation

Setting: m remote sites each see a local stream. A coordinator (or a tree, or
a peer network) answers a query over the union. The cost is **communication**
(bandwidth, sensor battery) in addition to space and time. Centralizing all
data is not viable, so push work into the network.

Axes:
- **One-shot vs continuous** queries.
- **Algebraic (constant-size partial state: SUM, COUNT, AVG, MIN, MAX) vs
  holistic** (median, top-k, count-distinct need summaries).
- **Duplicate-sensitive vs duplicate-insensitive** (MIN, MAX, count-distinct
  are insensitive).
- **Topology**: single-level coordinator, multi-level tree, or fully
  distributed (gossip).

One-shot techniques:
- *Tree aggregation* (TAG/TinyDB; Madden et al., OSDI 2002): partial states
  are generated at leaves, fused up the tree, and evaluated at the root.
  Holistic aggregates use composable summaries (q-digest, sketches) as
  partial states.
- *Multipath robustness*: one lost message near the root destroys accuracy.
  Send partials along several paths. Multipath double-counts, which is
  harmless for **ODI** (order- and duplicate-insensitive) aggregates such as
  MIN/MAX. For SUM/COUNT, use duplicate-insensitive sketches (Flajolet–Martin
  based "synopsis diffusion", Nath et al. SenSys 2004). Hybrid: trees far
  from the root, multipath near it ("tributaries and deltas", Manjhi et al.,
  SIGMOD 2005).
- *Gossip*: ODI aggregates converge in O(log n) rounds. Push-sum (Kempe,
  Dobra, Gehrke, FOCS 2003) handles SUM/AVG by splitting mass and conserving
  it, so nothing is counted twice.

Continuous techniques: **local filters with slack allocation**. Each site
pushes only when its local value leaves a filter range. The filters are sized
so the global error bound holds (safe filters).
- Algebraic aggregates: split slack directly and adapt widths to violation
  rates (Olston et al. 2003; `scheduling-load-shedding-adaptivity.md` §5.3).
- Distributed top-k (Babcock & Olston, SIGMOD 2003): local constraints keep
  each site's local top-k aligned with the global one. The coordinator keeps
  reserve slack to resolve violations locally.
- Set-expression cardinalities (Das et al., VLDB 2004): charge updates
  according to set semantics.
- Prediction-based tracking (Cormode & Garofalakis, VLDB 2005): site and
  coordinator share a prediction model of the local sketch's evolution. The
  site reports only when the prediction drifts beyond tolerance.
- Threshold triggers ("fire when the global count exceeds T"): exploit the
  threshold for wider safe filters when far from it (Keralapura et al.,
  SIGMOD 2006). The *geometric method* (Sharfman, Schuster, Keren, SIGMOD
  2006) handles general non-linear threshold functions by local bounding
  spheres.

Systems context: simple in-network aggregation shipped widely (TinyDB). The
sophisticated approximate tracking schemes largely remained research.
Operator placement in a distributed dataflow can be optimized in a cost space
of bandwidth and latency (Pietzuch et al., ICDE 2006).

> **Beyond EDBS:** HyperLogLog (Flajolet et al. 2007; HLL++ by Heule et al.,
> EDBT 2013) is the default count-distinct sketch in production engines. It is
> mergeable by register-wise max, which makes it ODI and therefore safe for
> multipath and re-delivery. Theta sketches add set operations. Apache
> DataSketches packages HLL, Theta, KLL, frequent-items (SpaceSaving-style)
> and quantiles with serialization formats suitable for operator state.

---

## 9. Engine integration checklist

1. **Synopsis as operator state**: implement a common interface: `update(x,
   w)`, `merge(other)`, `query(...)`, `serialize()`, `error_bound()`. That lets
   the same synopsis serve sliced windows, partition merge, checkpointing and
   distributed partials.
2. **Seeds are state**: hash seeds and RNG state are part of the checkpoint.
   Otherwise replay produces different sketches, which is divergent recovery
   (`fault-tolerance-and-exactly-once.md` §4).
3. **Match the update model**: retractions (negative tuples) into a
   SpaceSaving or reservoir summary are a bug. Route them to a linear sketch,
   or reject the plan.
4. **Expose error in results**: return (estimate, ±bound, confidence) so
   consumers and the load shedder can reason about precision.
5. **Mergeability across slices**: for panes/pairs over holistic aggregates,
   the per-slice partial must be a mergeable summary. GK is not, while KLL,
   q-digest, MG/SpaceSaving (Agarwal merge), CM and HLL are.
6. **Hash quality**: CM/AMS guarantees assume pairwise or four-wise
   independence. Use tabulation or multiply-shift families with fresh seeds per
   row. Never use `std::hash` identity on integers.
7. **Memory layout**: CM rows as contiguous `u32`/`u64` arrays (one cache line
   per row probe). SpaceSaving as a stream-summary with intrusive lists and an
   open-addressing index. Avoid per-item heap allocation.

## 10. Testing synopses

- **Exact oracle on small domains**: compute exact frequencies/ranks
  alongside. Assert the per-query error ≤ bound for deterministic schemes, and
  for randomized ones assert a failure rate ≤ δ over many seeds (binomial test).
- **Adversarial orders**: sorted, reverse-sorted, alternating, and all-distinct
  inputs for GK/q-digest/MG (order-sensitive). Zipf with varying skew for
  SpaceSaving/CM.
- **Merge equivalence**: `summary(A ∪ B)` vs `merge(summary(A), summary(B))`.
  Both must satisfy the bound. With fixed seeds, linear sketches must be
  bit-identical.
- **Turnstile**: insert then delete everything. A linear sketch must return
  to all zeros.
- **Window**: compare windowed variants against exact recomputation on every
  slide for small windows.

Sources: EDBS "One-Pass Algorithm" (p.2556), "Stream Sampling" (p.3782),
"Frequent Items on Streams" (p.1524), "Quantiles on Streams" (p.2965),
"Histograms on Streams" (p.1715), "Wavelets on Streams" (p.4588), "Distributed
Data Streams" (p.1162), "Streaming Analytics" (p.3793), "Stream Models"
(p.3768).
