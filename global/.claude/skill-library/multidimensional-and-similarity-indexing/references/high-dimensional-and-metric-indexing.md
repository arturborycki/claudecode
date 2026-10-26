# High-dimensional and metric-space indexing

Read this when the data are feature vectors with more than ~10 dimensions,
when the only thing you have is a distance function (strings, sets, graphs,
images under a learned metric), or when deciding between an index, a
compressed scan and an approximate method.

---

## 1. Curse of dimensionality — what actually breaks

Bellman's original statement: sample complexity for estimating a function
grows exponentially with input dimension. For similarity search it shows up
as several concrete effects:

1. **Distance concentration** (Beyer, Goldstein, Ramakrishnan, Shaft, ICDT
   1999): under broad conditions (e.g. i.i.d. dimensions), the ratio
   `(Dmax − Dmin)/Dmin` between a query's farthest and nearest neighbour
   tends to 0 as d grows. The NN is then barely nearer than everything else;
   any index must look at most of the data and the query may be
   semantically meaningless.
2. **Boundary effect**: most of the volume of a hypercube lies near its
   surface; points cluster near the boundary; a query ball of useful radius
   pokes far outside the data space, so naive uniform cost models are wrong.
3. **Page regions become huge**: with fanout-limited splits, each
   directory rectangle is split in only a few of the d dimensions, so its
   extent in the remaining dimensions is the full domain; MINDIST to almost
   every page is ≈ 0 and nothing prunes.
4. **Overlap and low fanout**: entries are 2·d coordinates → fewer per page
   → taller trees, and directory splits cannot avoid overlap.
5. **Random I/O vs sequential**: a tree that reads 20% of the pages randomly
   is slower than a full sequential scan (EDBS cites up to ~20× cost ratio
   for random vs sequential reads).

Rules of thumb from the entries: R-tree-like trees lose to a scan beyond
roughly 10–15 dimensions on uniform data (Weber, Schek, Blott, VLDB 1998
made this quantitative); metric trees stay useful somewhat longer (EDBS
quotes ~20–25); all thresholds depend on **intrinsic** dimensionality, data
size and clustering, not the nominal d. Real data are usually correlated and
clustered, which is why high-d indexing works at all.

**Intrinsic dimensionality** estimators to compute before choosing a method:
- correlation fractal dimension (box counting on pair distances; used in
  the Böhm/Berchtold cost models);
- PCA spectrum: number of components to reach 90–95% variance;
- for metric spaces, Chávez et al.'s `ρ = μ² / (2σ²)` from the histogram of
  pairwise distances (mean μ, variance σ²): small variance (concentrated
  distances) ⇒ high ρ ⇒ hard to index. EDBS makes the same observation: a
  narrow spread of pairwise distances makes metric search costly.

---

## 2. The toolbox (Böhm & Plant's classification)

| Trick | Representatives |
|---|---|
| Dimensionality reduction | TV-tree, SDI-tree, CSVD/LDR, tree striping, Delta-tree |
| Data compression / quantisation | VA-file, IQ-tree, A-tree (relative approximation) |
| Optimised I/O schedules | page-size optimisation, fast index scan (FIS) |
| Hierarchy flattening | X-tree supernodes, IQ-tree one-level directory |
| Page region shape | SS-tree (spheres), SR-tree (sphere ∩ box), TV-tree (spheres in active dims) |
| Clustering / 1-D embedding | iDistance, Pyramid technique, CSVD, SUSHI, Delta⁺-tree |

### Tree structures

- **TV-tree** (Lin, Jagadish, Faloutsos, VLDBJ 1994): after a transform that
  concentrates variance (PCA/DFT), only a few *active dimensions* are used
  in upper levels; regions are spheres in those dimensions; deeper levels
  activate more dimensions. Wins only when the data are reducible.
- **SS-tree** (White & Jain, ICDE 1996): page region = sphere centred at the
  centroid with radius covering all entries; cheap, good for Euclidean
  NN; spheres are hard to split without overlap.
- **SR-tree** (Katayama & Satoh, SIGMOD 1997): region = intersection of
  bounding sphere and MBR; MINDIST = max of the two lower bounds.
- **X-tree** (Berchtold, Keim, Kriegel, VLDB 1996): R*-tree plus split
  history; when a directory split would create high overlap, create a
  **supernode** (multi-page node, scanned sequentially) instead. Degrades
  gracefully toward a linear scan as d grows — by design.
- **SDI-tree** (Thomasian & Zhang 2006): PCA-transformed vectors; level ℓ
  uses the first n_ℓ dimensions, chosen so cumulative variance grows by a
  fixed fraction p per level; nodes are hyperspheres in n_ℓ dims; fanout
  per level depends on n_ℓ.
- **OP-tree**: equipartitions round-robin one dimension at a time; can be
  serialised into one contiguous file and loaded with a single transfer.

### Cost-model-driven tuning (Berchtold, Böhm, Keim, Kriegel; Böhm TODS 2000)

Probability a page is accessed ≈ volume of the Minkowski sum of the page
region and the query region, corrected for the boundary effect and the
fractal dimension. Use it to choose:
- **Data page size** — large pages for high intrinsic dimension (you will
  read many pages anyway, so make them sequential), small pages for low.
  Can be adapted dynamically and differ per subtree.
- **Tree striping** — split vectors into sub-vectors indexed in separate
  trees; optimal stripe count balances per-tree selectivity against the cost
  of merging results.

### Scan-based and quantised approaches

**VA-file** (Weber, Schek, Blott, VLDB 1998). Quantise each dimension into
2^{b_i} quantile-based intervals; store a b-bit cell code per vector in a
compact approximation file; keep exact vectors elsewhere.
```
Phase 1 (scan approximations, sequential):
  for each vector i: lb_i, ub_i = bounds from q to cell(i)
  maintain kth smallest ub so far = δ; keep i as candidate iff lb_i ≤ δ
Phase 2 (refine, random I/O):
  visit candidates in ascending lb; compute exact distance;
  stop when next lb ≥ current kth exact distance
```
Exact (no false dismissals), I/O mostly sequential; global quantiles suit
uniform data; clustered data favour hierarchical methods.

**IQ-tree** (Berchtold et al., ICDE 2000): one-level directory of MBRs →
per-page *independently* quantised data pages (regular grid inside the
page MBR; resolution chosen by cost model) → exact data level. Two lower
bounds: distance to the page MBR, distance to the grid cell. **Fast index
scan**: from the directory, classify pages as certainly needed / excluded /
probably needed, then read runs of adjacent needed pages in one I/O.

**A-tree** (Sakurai et al., VLDB 2000): child MBRs stored as quantised
*relative* approximations of the parent MBR — more entries per node.

### One-dimensional embeddings

- **Pyramid technique** (Berchtold, Böhm, Kriegel, SIGMOD 1998): 2d pyramids
  around the centre; key `(pyramid_id, height)` in a B+-tree; window query →
  ≤ 2d intervals. Ideal for L∞-style hypercube queries; NN via repeated
  range queries; inspired onion technique and concentric hyperspaces.
- **iDistance** (Yu, Ooi, Tan, Jagadish, VLDB 2001): partition (clustering),
  reference point O_i per partition, key = i·c + d(p, O_i); kNN search grows
  a radius r and scans the annulus `[d(q,O_i) − r, d(q,O_i) + r]` in each
  partition whose sphere intersects the query ball; partition max radius
  prunes. Quality depends on partitioning and reference choice (centroid vs
  edge point); subspace clustering first (Jin et al. ICDE 2003) helps when
  correlations are local.

### Main-memory, multicore, distributed

- A 64-d float vector is 256 bytes — several cache lines; distance
  computations, not node visits, dominate. Delta-tree (Cui et al., TKDE
  2005): PCA so upper levels fit in cache lines, more dimensions deeper;
  Delta⁺-tree clusters globally first. SUSHI (Günnemann et al., EDBT 2011):
  subspace-clustering hierarchy, intentionally unbalanced (fine in RAM).
- GPU/SIMD batching, MapReduce index builds (Moise et al. 2013, 100M
  images), RT-CAN (Wang et al., SIGMOD 2010: local R-trees with selected
  nodes promoted into a CAN overlay).

---

## 3. Dimensionality reduction with guarantees

### Lower-bounding lemma (GEMINI; Agrawal, Faloutsos, Swami, FODO 1993;
Faloutsos et al., SIGMOD 1994)

If a feature map F satisfies `d_F(F(x), F(y)) ≤ d(x, y)` for all x, y
(contractive), then an ε-range query in feature space returns a superset of
the true answer: **no false dismissals**. False alarms are removed by
refinement against the original objects. kNN uses the multi-step algorithm
(spatial-join-and-nn file §1).

Contractive transforms in practice:
- Orthonormal transforms (DFT by Parseval, DWT, PCA/KLT/SVD rotation)
  followed by **truncation**: dropping coordinates can only reduce L2.
- PAA / APCA (Keogh et al., SIGMOD 2001) for time series.
- MBR distances (MINDIST) as LB for object distances.

> **Beyond EDBS:** for dynamic time warping, LB_Keogh (Keogh 2002) gives an
> envelope-based lower bound used in exactly this filter/refine scheme;
> SAX symbolic representations also admit lower-bounding distances.

### PCA/SVD details that matter

- Given data matrix X (M×N), SVD `X = UΣVᵀ`; covariance `C = XᵀX/M = VΛVᵀ`
  with `λ_i = σ_i²/M`. Projection `Y = XV`; keeping the first n columns
  minimises normalised mean squared error
  `NMSE = Σ_{j>n} λ_j / Σ_j λ_j`.
- Cost: O(MN²) to form C, O(N³) eigendecomposition — expensive to maintain
  under updates (dynamic SVD is an open-ish problem per EDBS; Ravikanth et
  al. 1998 address incremental updates).
- **Clustered SVD** (CSVD; Castelli, Thomasian, Li, TKDE 2003): cluster
  first (e.g. LBG/k-means), rotate each cluster into its own principal axes,
  then globally drop the (cluster, dimension) pairs with smallest
  `λ_j^(h)·m_h` until the target NMSE / index-size / recall is met. Local
  correlation gives much larger reduction than global SVD. **LDR**
  (Chakrabarti & Mehrotra, VLDB 2000) similar, adds the reconstruction
  distance as an extra coordinate to keep the lower bound tight.
- **kNN across clusters**: sort clusters by `max(d(q, centroid) − radius, 0)`;
  search the primary cluster; continue to the next cluster only while its
  bound ≤ current k-th distance. This branch-and-bound over clusters is the
  exact counterpart of IVF's `nprobe` heuristic.
- **Exact kNN on reduced data** (Korn et al., VLDB 1996): kNN in subspace →
  compute exact distances of those k → range query with the max as radius →
  refine and rank. Too few retained dims → many false alarms; too many →
  expensive filter; there is a CPU-optimal NMSE in between.

---

## 4. Metric-space indexing

### Definitions

Metric space (D, d) with non-negativity, symmetry, reflexivity, positivity
(identity of indiscernibles) and the **triangle inequality**. Relaxations:
- pseudo-metric (distinct objects at distance 0): collapse equivalence
  classes;
- quasi-metric (asymmetric, e.g. one-way streets): symmetrise with
  `d_sym(x,y) = d(x,y) + d(y,x)` if a metric index is needed;
- ultra-metric (`d(x,z) ≤ max(d(x,y), d(y,z))`): every triangle isosceles;
  enables stronger pruning.

Examples: L_p norms (L1 Manhattan, L2 Euclidean, L∞ max), edit distance,
Jaccard distance on sets, Hausdorff distance, Earth Mover's Distance.
**Not metrics**: cosine *similarity*, inner product, DTW, squared L2 (fails
the triangle inequality — use L2, or angular distance arccos for cosine).

### Pruning lemmas (all metric indexes are built from these)

With pivot p and precomputed d(o, p):
```
d(q, o) ≥ |d(q, p) − d(o, p)|          # lower bound
d(q, o) ≤  d(q, p) + d(o, p)           # upper bound
```
- Range query (q, r): discard o if `|d(q,p) − d(o,p)| > r`; accept without
  computing d(q,o) if `d(q,p) + d(o,p) ≤ r`.
- Ball region (center c, radius R): skip the subtree if `d(q,c) > r + R`;
  everything inside qualifies if `d(q,c) + R ≤ r`.
- Generalised hyperplane (c1, c2), objects closer to c1 on side 1: skip side
  1 if `(d(q,c1) − d(q,c2)) / 2 > r`.
- With m pivots, the best lower bound is `max_i |d(q,p_i) − d(o,p_i)|`
  (L∞ in pivot space) — a contractive embedding into R^m, so any vector
  index over pivot coordinates becomes a metric filter.

### Partitioning principles and structures

| Structure | Principle | Notes |
|---|---|---|
| BK-tree (Burkhard–Keller 1973), FQ-tree/array | discrete distances; child per distance value from a pivot | edit-distance dictionaries |
| VP-tree (Yianilos 1993; Uhlmann's metric tree) | **ball partitioning** at median distance from a vantage point | balanced; query near the median boundary visits both sides; MVP-tree uses multiple vantage points |
| GH-tree, GNAT (Brin 1995) | **generalised hyperplane** between 2 (or m) centres | GNAT stores distance ranges from each centre to each sibling subset |
| AESA (Vidal 1986) | all n² distances precomputed | fewest distance computations; quadratic space — small sets only |
| LAESA | k fixed pivots, n·k table | linear space; scan table with lower bound, refine |
| **M-tree** (Ciaccia, Patella, Zezula, VLDB 1997) | balanced, paged, ball regions, bottom-up splits | the disk-based workhorse |
| Slim-tree (Traina et al., EDBT 2000) | M-tree + MST-based split + slim-down to reduce overlap | measures overlap via fat-factor |
| D-index (Dohnal et al. 2003) | multi-level hashing with ρ-split functions; exclusion zone keeps buckets separable | range query with r ≤ ρ touches ≤ 1 bucket per level |
| SAT, GNAT, hybrid trees | spatial approximation / mixed | see Chávez et al. survey |

**M-tree in detail**
- Routing entry: `(O_r, ptr, r(O_r) covering radius, d(O_r, parent(O_r)))`.
- Leaf entry: `(O_j, oid, d(O_j, parent(O_j)))`.
- Range search at node N with parent routing object O_p:
```
for each entry e in N:
  if |d(q, O_p) − d(e.O, O_p)| > r + e.radius: skip   # no distance computed
  dq = d(q, e.O)                                        # one distance
  if dq ≤ r + e.radius: (leaf: emit if dq ≤ r) (inner: recurse)
```
  The stored parent distances let the first test prune without any new
  distance computation — the main CPU win for expensive metrics.
- kNN: best-first on `d_min(e) = max(d(q, O_r) − r(O_r), 0)` with the same
  parent-distance pre-check.
- Insert: descend choosing a routing object whose ball already contains the
  new object (minimal distance among those); otherwise the one needing the
  smallest radius increase; enlarge radii on the way down.
- Split: **promote** two routing objects (policies: minimise the larger
  radius `mM_RAD`, minimise radius sum, random, sampling) and **partition**
  entries (generalised hyperplane, or balanced alternation). Radii of the new
  routing entries must cover their subtrees: at inner levels
  `r = max(d(O_new, child) + child.radius)`.
- Bulk loading exists and is preferable for static sets.

### Approximate and distributed metric search

Relaxing exactness (stop early, prune with shrunken radii, probabilistic
bounds) gives up to ~2 orders of magnitude speedup at small loss — EDBS
justifies it because similarity is subjective and search is iterative. P2P
structures (GHT*, VPT*, M-CAN, M-Chord; compared in Batko et al. 2006) keep
response time nearly constant as data grows by adding peers.

> **Beyond EDBS:** permutation-based indexing (represent each object by the
> order in which it sees a set of pivots; Chávez, Figueroa, Navarro 2008)
> and graph-based methods dominate approximate metric search today; the
> latter are the vector ANN methods in `vector-ann-indexes-beyond-edbs.md`.

---

## 5. Decision table

| Situation | Choose |
|---|---|
| d ≤ ~8, extended objects | R*-tree / packed R-tree (GiST) |
| d ≤ ~8, points, in memory | kd-tree / PR-quadtree / SP-GiST |
| 10–30 d, correlated or clustered, need exact | dimensionality reduction (PCA/CSVD) + low-d index + multi-step refine; or X-tree/SR-tree; measure against VA-file |
| 10–100+ d, uniform-ish, need exact | VA-file / compressed sequential scan, SIMD, partition-parallel |
| Arbitrary metric, expensive distance | M-tree / pivot table (LAESA); minimise distance computations |
| Discrete distances (edit distance on short strings) | BK-tree, or q-gram filter + verify |
| 100+ d, millions–billions, approximate acceptable | graph (HNSW/Vamana) or IVF-PQ (vector ANN file) |

Always benchmark against a well-optimised parallel brute-force scan; it is
the honest baseline in high dimensions.

Sources: EDBS *Curse of Dimensionality* (p.717), *High-Dimensional
Indexing* (p.1706), *Dimensionality Reduction Techniques for
Nearest-Neighbor Computations* (p.1108), *Indexing and Similarity Search*
(p.1857), *Indexing Metric Spaces* (p.1876), *Metric Space* (p.2253),
*Multi step Query Processing* (p.2435), *Nearest Neighbor Query* (p.2478).
