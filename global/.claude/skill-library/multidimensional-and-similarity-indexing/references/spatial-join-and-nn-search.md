# Filter/refine, spatial join, nearest-neighbour family, Voronoi, uncertainty

Read this when implementing a spatial or similarity *operator* on top of an
index: the filter/refine pipeline, an intersection or distance join, kNN
(depth-first, best-first, incremental), closest pairs, reverse NN, Voronoi
methods, or probabilistic queries over uncertain objects.

---

## 1. Multi-step (filter/refine) query processing

Every operator here is an instance of one pattern. Exact objects (polygons,
time series, images, uncertain pdfs) are expensive to test; cheap
approximations decide most candidates.

```
DB ──filter_1──► candidates ──filter_2──► … ──refine (exact predicate)──► result
        │  true drops                │ true hits (report early)
```

- **Conservative approximation** (contains the object: MBR, convex hull,
  rotated MBR, minimum bounding m-corner, bounding sphere) or a
  **lower-bounding distance** `LB(q,o) ≤ dist(q,o)` → identifies **true
  drops** with no false dismissals.
- **Progressive approximation** (contained in the object: maximum enclosed
  rectangle/circle) or an **upper-bounding distance** `UB ≥ dist` →
  identifies **true hits** without refinement.
- A filter that is neither conservative nor progressive cannot prune
  correctly; using one is a correctness bug, not a tuning choice.
- Order filters by (cost, selectivity): cheapest high-pruning first. The
  index itself can only be the *first* filter (it organises the whole
  database); later filters run on candidate streams.

### Distance range (ε) query

Known threshold → each filter step classifies independently:
`LB(q,o) > ε ⇒ drop`, `UB(q,o) ≤ ε ⇒ hit`, else pass on.

### kNN with expensive distance (the hard case)

The threshold `d_k` (k-th NN distance) is unknown until k objects are
refined.

1. **Korn et al. 1996**: kNN on the filter distance → refine those k → take
   max exact distance `d'` → ε-range on the filter with radius `d'` →
   refine all → take top k. Correct, but refines more than needed.
2. **Seidl & Kriegel, SIGMOD 1998 (optimal)**: consume an *incremental
   ranking* by filter distance; keep a max-heap of the best k exact
   distances; for each next candidate, if `LB(next) ≥ current d_k` stop,
   else refine and update. Optimal in the number of refinements among
   algorithms using that lower-bounding filter.
3. **With an additional progressive (upper-bound) filter** (Kriegel/Kröger/
   Renz line of work): `d_k` can be bounded from UB values before any
   refinement, reducing refinements further; again optimal for that filter
   pair.

```
MultiStepKNN(q, k, ranking_by_LB):
  R = max-heap (capacity k) of (exact_dist, obj)
  for (lb, o) in ranking_by_LB:            # ascending lb
    if |R| == k and lb >= R.max(): break
    d = exact(q, o)
    if |R| < k or d < R.max(): R.push((d,o)); trim to k
  return sorted(R)
```
This is exactly what PostgreSQL's index scan does for lossy KNN-GiST
distances (reorder queue, ≥ 9.5) and what an ANN re-ranking stage does —
except that quantised ANN distances are *not* lower bounds, so the
`break` there is heuristic.

Applications called out by EDBS: time series (dimensionality-reduced filter,
raw-series refine), road networks (Euclidean distance or landmark-based
bounds as filters for shortest-path distance), point-in-polygon (MBR
conservative, inscribed shapes progressive).

---

## 2. Spatial join

Binary spatial join `R ⋈_θ S` with θ = intersects (most common), contains,
within distance ε, or a directional relation. Almost all algorithms
implement the **filter step on MBRs**; refinement runs afterwards on the
surviving pairs (and dominates CPU for complex polygons — batch it, sort
candidate pairs by one input's page to get locality).

### Classification by index availability

| Inputs indexed | Algorithms |
|---|---|
| Both | R-tree join / synchronized traversal (RJ); z-value sort-merge over B-trees |
| One | indexed nested loops; seeded tree join; build-and-match; sort-and-match; slot index spatial join (SISJ) |
| Neither | spatial hash join (HJ); partition-based spatial merge (PBSM); size separation (S³J); scalable sweeping-based (SSSJ) |

Plans often have non-indexed inputs because a selection or another join runs
first — the optimizer must cost all three columns, not just RJ.

**Refinement predicates.** Exact topological tests are defined by
intersection matrices over interior, boundary (and exterior) of the two
geometries: the 4-intersection model (2×2), the 9-intersection model (3×3,
512 empty/non-empty patterns in theory, 68 realisable between simple
regions, lines and points), and dimension-extended variants that record the
dimension of each intersection (DE-9IM, the basis of OGC/SQL-MM `ST_Relate`
and of named predicates such as touches, crosses, overlaps). The MBR filter
must be valid for the predicate: `intersects`/`touches`/`overlaps` need MBR
intersection, `contains` needs MBR containment, `disjoint` cannot be
filtered by an index at all (it is the complement — plan it as an anti-join).

### R-tree join (Brinkhoff, Kriegel, Seeger, SIGMOD 1993)

```
RJ(nR, nS):
  # search-space restriction
  ER = { e ∈ nR : e.mbr ∩ nS.mbr ≠ ∅ };  ES = { e ∈ nS : e.mbr ∩ nR.mbr ≠ ∅ }
  # plane sweep over ER ∪ ES sorted by x_low
  for (eR, eS) in plane_sweep_pairs(ER, ES):
    if leaves: emit (eR.oid, eS.oid)
    else: RJ(child(eR), child(eS))   # schedule by locality / pin pages
```
Unequal heights: when the shallower tree reaches leaves, issue window queries
into the deeper subtree. I/O optimisations: read schedule ordered by
plane-sweep position so consecutive pairs share pages; pin the page shared
by the most pending pairs. Correctness hinge: non-intersecting parent MBRs
imply no intersecting descendant pairs (covering invariant).

### Plane sweep (used everywhere)

Sort both rectangle sets by lower x; sweep; for the next rectangle r
(from either set), scan forward in the *other* set while `x_low ≤ r.x_high`
and test y-overlap. Cost O((n+m) log(n+m) + k') with k' the number of
x-overlapping pairs. Choose the sweep axis with smaller expected overlap
(Shin, Moon, Lee 2000 use this for distance joins).

### Hash/partition-based joins (no indexes)

- **Spatial hash join** (Lo & Ravishankar, SIGMOD 1996): sample R to seed K
  bucket extents; insert each R object into the bucket needing least
  enlargement (no replication, buckets overlap); insert each S object into
  **every** bucket it intersects (replication on S, objects intersecting no
  bucket are filtered). Join matching bucket pairs in memory (or build a
  small R-tree when neither fits).
- **PBSM** (Patel & DeWitt, SIGMOD 1996): regular grid of tiles mapped to P
  partitions by a round-robin/hash tile→partition function (de-skews hot
  regions); replicate both inputs into all intersecting partitions;
  plane-sweep each partition; recursively repartition overflowing ones.
  Requires **duplicate elimination**.
- **S³J** (Koudas & Sevcik, SIGMOD 1997): hierarchical grid layers
  (level l has 4^l cells); each rectangle goes to the finest level where no
  grid line cuts it → no replication; sort each level by Hilbert value;
  synchronized scan joins a cell with all overlapping cells at coarser
  levels. A level-wise bitmap of non-empty cells filters the second input.
- **SSSJ** (Arge et al., VLDB 1998): external sort on x then plane sweep;
  relies on the expectation that the sweep line intersects ~√n rectangles;
  on memory overflow, partition into vertical strips and recurse.

**Duplicate avoidance without a sort — reference point method** (Dittrich &
Seeger, ICDE 2000): report a pair only in the partition that contains a
canonical point of the pair's intersection (e.g. the lower-left corner of
`r.mbr ∩ s.mbr`). Every intersecting pair has exactly one such partition, so
output needs no dedup and the join stays pipelined and parallel. Use this
in any replicating partitioned join (PBSM, distributed grids, cell-id joins).

### Single-index methods

- **Indexed nested loops**: window query per probe; only for small probe side.
- **Seeded tree join**: copy the top k levels of R's tree as "seeds", grow a
  tree for S under them, then RJ — produces a tree shaped for the join.
- **Build-and-match**: STR/Hilbert bulk-load an R-tree on S, then RJ.
- **Sort-and-match**: produce S's packed leaves on the fly (STR order) and
  probe each with a window query on R's tree; no full build.
- **SISJ** (Mamoulis & Papadias, TKDE 2003): pick the highest level of R's
  tree with ≥ K entries, group entries into K slots (R*-tree insertion
  heuristics), hash S into slot extents (replicate/filter), then join each
  slot's subtree data with its bucket.

Empirical summary from the entry: two-index RJ > single-index (SISJ, SaM
best) > no-index; among no-index methods results depend on object size and
replication — S³J wins for large rectangles, hashing usually beats sorting,
and PBSM's fixed partitions parallelise best.

### Distance joins and their relatives

- **ε-distance (similarity) join**: pairs within ε; expand one side's MBRs
  by ε and run an intersection join, then refine distance. In high-d
  feature spaces use dedicated similarity-join algorithms (ε-grid order,
  multidimensional spatial join of Koudas & Sevcik 2000).
- **kNN join**: for each r, its k nearest s (Böhm & Krebs 2004) — common
  in ML pipelines; implement as batched kNN with shared traversal.
- **Closest pairs / k-distance join** (section 4).
- **Buffer query, iceberg distance join, multi-way distance join,
  constrained CPQ** are variants named in EDBS.

> **Beyond EDBS:** distributed engines (e.g. Apache Sedona) partition both
> inputs spatially (KDB-tree/quadtree/grid from a sample), replicate across
> boundaries, build local indexes per partition, and deduplicate with a
> reference-point rule — PBSM generalised to a cluster. Cell-id joins over
> S2/H3 coverings are Orenstein's z-value join with a modern cell hierarchy.

---

## 3. k-nearest-neighbour search on a tree

kNN(q): the k objects with smallest dist(q,·), ties broken arbitrarily but
deterministically (tests need a tie rule).

### Distance bounds between a point q and an MBR R = [s, t]

```
MINDIST(q,R)^2 = Σ_i  (s_i − q_i)^2  if q_i < s_i
                      (q_i − t_i)^2  if q_i > t_i
                      0              otherwise
MAXDIST(q,R)^2 = Σ_i max((q_i − s_i)^2, (q_i − t_i)^2)
MINMAXDIST(q,R)^2 = min_k [ (q_k − rm_k)^2 + Σ_{i≠k} (q_i − rM_i)^2 ]
   rm_k = s_k if q_k ≤ (s_k+t_k)/2 else t_k     # nearer face along k
   rM_i = s_i if q_i ≥ (s_i+t_i)/2 else t_i     # farther face along i
```
- MINDIST lower-bounds the distance to every object in R.
- MINMAXDIST upper-bounds the distance to the *nearest* object in R; it is
  valid only because MBRs are **tight** (every face touches some object).
  A lossy/loose key (compressed floats rounded outward, GiST unions that
  are not minimal) invalidates MINMAXDIST — never use it with loose keys.
- MAXDIST upper-bounds the distance to every object in R.
- Work in squared distances; take square roots only for output.

### Depth-first branch-and-bound (Roussopoulos, Kelley, Vincent, SIGMOD 1995)

Visit children in ascending MINDIST (or MINMAXDIST) order; maintain the
current k-th best distance `d_k`. Pruning rules:
1. drop child M if `MINDIST(q,M) > MINMAXDIST(q,M')` for some sibling M'
   (k = 1 only);
2. drop object o if `dist(q,o) > MINMAXDIST(q,M)` for some M (k = 1);
3. drop child M if `MINDIST(q,M) > d_k`.

Cheung & Fu (SIGMOD Record 1998) showed rules 1–2 never save page accesses
once rule 3 is applied with MINDIST ordering — implement rule 3 only. DF uses
O(height) memory and is LRU-friendly but **suboptimal**: the first leaf it
reaches yields only a provisional best distance, so it can read leaves that
lie outside the true NN ball before backtracking finds the real NN elsewhere.
For k > 1 keep a sorted list (or max-heap) of the k best `(obj, dist)` pairs;
`d_k` is its last element; prune entries with MINDIST ≥ d_k on backtrack.
The benchmark for any algorithm: an **optimal** search reads exactly the
nodes whose regions intersect the ball centred at q with radius d_k — the
set best-first achieves.

### Best-first / incremental (Hjaltason & Samet, TODS 1999; Henrich 1994)

```
BF_kNN(q):
  PQ = min-heap keyed by distance; push (MINDIST(q,root), root)
  while PQ not empty:
    (d, e) = PQ.pop()
    if e is object (exact): yield e         # next NN, in order
    elif e is object approximation: PQ.push((exact_dist(q,e), exact(e)))
    else: for c in children(e): PQ.push((MINDIST(q,c.mbr), c))
```
- **I/O-optimal**: visits exactly the nodes whose MINDIST is < d_k (the
  nodes intersecting the k-NN ball), assuming distinct distances.
- **Incremental / distance browsing**: k need not be known; the consumer
  (e.g. `ORDER BY dist LIMIT` with a later filter) pulls until satisfied.
  This is the right executor abstraction: an ordered iterator.
- Correctness requires a **consistent** key: a child's key ≥ its parent's
  key and an object's key ≥ its container's key. MINDIST satisfies this
  because child MBR ⊆ parent MBR.
- Risks: priority queue growth (worst case all entries) — bound memory,
  spill or switch to DF; poor buffer locality.

### NN variants

| Query | Definition | Technique |
|---|---|---|
| Aggregate NN (Papadias et al., TODS 2005) | p minimising f(dist(p,q1..qn)), f = sum/max/min | BF with aggregate MINDIST bound over the query set |
| Constrained NN | NN within a region | intersect MBRs with constraint; MINDIST to clipped region |
| Continuous / moving NN | NN over a time interval or as q moves | split points along trajectory; validity regions (Voronoi cell of the NN) |
| kNN in road networks | network distance | Euclidean LB filter + Dijkstra/landmark refine; Voronoi-based network NN (VN³) |

---

## 4. Closest-pair queries (k-CPQ)

k pairs (p,q) ∈ P×Q with smallest distances; both sets indexed by R-trees.

MBR-pair bounds (M1, M2):
- `MINMINDIST(M1,M2)`: per dimension the gap between the intervals (0 if
  they overlap), combined in L2 — lower bound for all pairs under (M1,M2).
- `MAXMAXDIST`: farthest corners — upper bound for all pairs.
- `MINMAXDIST(M1,M2)`: upper bound on the closest pair under (M1,M2), using
  the face-touching property of tight MBRs.

Pruning: discard pair (M1,M2) if `MINMINDIST > z`, where z is the k-th best
pair distance found so far (or the k-th smallest MAXMAXDIST before k real
pairs exist).

Algorithms (Hjaltason & Samet SIGMOD 1998; Corral et al. SIGMOD 2000, DKE
2004):
- **BF (incremental distance join)**: heap of node pairs keyed by
  MINMINDIST plus a k-max-heap of results; near-optimal node pair accesses;
  heap can explode → spill.
- **DF (recursive)**: memory O(height), more node accesses.
- Expand node pairs with **plane sweep** along a chosen axis, keeping only
  pairs whose MINMINDIST along the sweep axis ≤ z — avoids the |n1|·|n2|
  Cartesian product.
- Different tree heights: fix the leaf of the shallower tree and keep
  expanding the other.
- High overlap between P and Q hurts; the b-Rdnn tree stores per-entry NN
  distances to the other set to prune better in that case.

---

## 5. Reverse nearest neighbours (RNN / RkNN)

`RNN(q) = { p ∈ P : no p' ∈ P with dist(p,p') < dist(p,q) }` (influence
set). NN is not symmetric: `p ∈ kNN(q)` neither implies nor is implied by
`p ∈ RkNN(q)`. Monochromatic (one set) vs bichromatic (sites vs customers).

| Method | Idea | Updates | Any d | Exact | Any k |
|---|---|---|---|---|---|
| KM (Korn & Muthukrishnan, SIGMOD 2000) | precompute each p's NN circle; RNN-tree of circles; RNN(q) = circles containing q | no | yes | yes | fixed k |
| YL RdNN-tree (Yang & Lin, ICDE 2001) | R-tree whose leaves store NN circles and inner nodes store max NN distance | no | yes | yes | fixed k |
| SAA (Stanoi et al. 2000) | 6 cones of 60° around q in 2-D: the NN of q in each cone is the only candidate there | yes | no (cones grow exponentially with d) | yes | extendable |
| SFT (Singh et al. 2003) | take K NNs of q as candidates; drop those closer to another candidate; verify with Boolean range queries | yes | yes | **no** (false misses) | yes |
| TPL (Tao, Papadias, Lian, VLDB 2004) | single BF traversal; each candidate p prunes the half-space beyond the perpendicular bisector of (p,q); a node is pruned if inside the union of such half-spaces; refinement removes false hits | yes | yes | yes | yes |

Boolean range query: stop at the first witness, or when an MBR side lies
fully inside the circle (guarantees a point inside) — a cheap existence
test worth having as a generic operator.

---

## 6. Voronoi-based methods

Voronoi cell V(p) = points closer to p than to any other site (for a chosen
metric). In 2-D Euclidean: cells are convex polygons bounded by bisector
segments; the diagram is unique; the NN of a site is among its Voronoi
neighbours; the average number of Voronoi neighbours is ≤ 6.

Uses in query processing:
- **NN as point location**: NN(q) = generator of the cell containing q.
  Index cells (D-tree, os-tree, Hagedoorn's DAG for general distance
  functions).
- **Incremental kNN**: the (i+1)-th NN is a Voronoi neighbour of one of the
  first i NNs → expand only along Voronoi adjacency (VoR-tree:
  R-tree whose leaves store each point's Voronoi neighbours, Sharifzadeh &
  Shahabi, PVLDB 2010).
- **RNN / influence sets**: candidates come from Voronoi neighbours.
- **Validity regions** for moving queries: the result stays valid while q
  stays inside the NN's cell.
- **Road networks**: network Voronoi cells precomputed per site for exact
  network kNN (Kolahdouzan & Shahabi, VLDB 2004).
- Distributed kNN over MapReduce by partitioning Voronoi cells.

Weighted (additive/multiplicative) and order-k diagrams exist; building
them in high d is infeasible (complexity grows as n^⌈d/2⌉) — which is why
high-dimensional similarity search uses graphs approximating the Delaunay
graph instead (vector ANN file).

---

## 7. Indexing uncertain data

Model: each object has an uncertainty region with a pdf (Gaussian around a
reported GPS fix bounded by a distance threshold; arbitrary histogram for
sensors); existential uncertainty adds a probability that the object exists.

Two-phase evaluation: index-level **probabilistic pruning**, then exact
probability computation (numerical integration) for survivors.

- **Probabilistic threshold range query** (PTRQ): return o with
  `P(o ∈ R) > τ`.
  - **PTI** (Cheng et al., VLDB 2004): R-tree whose entries additionally
    store *x-bounds*: the left-x-bound is the rightmost line such that no
    object in the subtree has probability > x of lying left of it
    (symmetric for right). A query with threshold τ that does not cross the
    appropriate τ-bound prunes the subtree even if it overlaps the MBR.
  - **U-tree** (Tao et al., VLDB 2005): stores compact approximations of
    the x-bounds (probabilistically constrained regions) so the idea scales
    to several dimensions; APLA approximates cdfs piecewise-linearly to
    avoid integration.
- **Probabilistic NN** (PNNQ): probability that each object is the NN. Prune
  every object whose minimum distance to q exceeds the smallest maximum
  distance over all objects (it has zero probability). UV-diagram /
  UV-index (Cheng et al. ICDE 2010; Xie et al. VLDBJ 2013): generalise
  Voronoi cells to uncertainty regions; precompute for each object the
  region where it can be the NN; store UV-cells in an adaptive grid; point
  queries return the candidate set. Exact UV-partitions are exponential in
  size, so UV-cells are represented by the sets of objects bounding them.
- Join processing over uncertain spatial data reuses x-bounds.

---

## 8. Testing oracles for this whole file

- Brute force is the oracle for everything (scan + exact predicate); keep
  datasets small enough (≤ 10⁵) to run it in CI.
- Adversarial fixtures: duplicate points, collinear points, objects on cell
  boundaries, zero-area and zero-width MBRs, huge objects spanning the
  domain, equal distances (ties), q exactly on an MBR face.
- Metamorphic: kNN(k) is a prefix of kNN(k+1) (with deterministic ties);
  join(R,S) = join(S,R) swapped; partitioned join output = single-node join
  output as a multiset (catches dedup bugs); incremental NN distances are
  non-decreasing.
- Count refinements / node accesses and assert against the optimal
  algorithm's count on fixtures (catches lost pruning, which is invisible
  in result tests).

Sources: EDBS *Multi step Query Processing* (p.2435), *Spatial Join*
(p.3598), *Nearest Neighbor Query* (p.2478, incl. recovered tail with the
DF/BF walk-through from *Nearest Neighbor Query in Spatiotemporal
Databases*), *Dimension-Extended Topological Relationships* (fragment
adjoining p.1108), *Closest-Pair Query* (p.469),
*Reverse Nearest Neighbor Query* (p.3234), *Voronoi Diagrams* (p.4580),
*Indexing Uncertain Data* (p.1900), *Indexing and Similarity Search*
(p.1857), *Range Query* (p.3079), *R-Tree (and Family)* (p.3258).
