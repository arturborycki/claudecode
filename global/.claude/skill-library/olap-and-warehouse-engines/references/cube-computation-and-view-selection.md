# Cube computation and view selection

How to execute CUBE/ROLLUP/GROUPING SETS, how to compute a full or partial
data cube efficiently, how to choose which aggregates to materialize, and how
to keep them current.

## 1. SQL semantics an implementation must reproduce

Gray et al. introduced CUBE and ROLLUP by adding a special ALL value; SQL:1999
standardised them as GROUPING SETS with NULL standing in for ALL.

| Construct | Expansion |
|---|---|
| `GROUPING SETS (s1,…,sk)` | UNION ALL of `GROUP BY si`; non-grouped columns NULL |
| `ROLLUP(a,b,c)` | `GROUPING SETS ((a,b,c),(a,b),(a),())` — n+1 sets |
| `CUBE(a,b,c)` | all 2^n subsets |
| `ROLLUP((a,b),c)` | composite column: (a,b) treated as one unit → ((a,b,c),(a,b),()) |
| `GROUP BY a, ROLLUP(b,c)` | concatenation = cross product: ((a,b,c),(a,b),(a)) |
| `GROUP BY CUBE(a,b), ROLLUP(c,d)` | product: 4 × 3 = 12 sets |
| `GROUPING(c)` | 1 if c is aggregated away in this row's set |
| `GROUPING_ID(c1..cn)` | bit vector of GROUPING values (c1 most significant) |

Edge cases (each needs a test):

- Duplicate sets are **not** removed (`GROUPING SETS ((a),(a))` doubles the
  rows) unless `GROUP BY DISTINCT` (SQL:2016-era; e.g. PostgreSQL 14+).
- The `()` set returns exactly one row even when the input is empty; other
  sets return zero rows on empty input.
- HAVING is evaluated per output row, after grouping; it may reference
  GROUPING().
- NULL in a grouping column is ambiguous with "ALL" — only GROUPING()
  disambiguates. Do not "fix" this by substituting sentinel values.
- Aggregates with DISTINCT or ORDER BY inside (`COUNT(DISTINCT x)`,
  `PERCENTILE_CONT`) are holistic: no reuse across sets.
- Window functions over grouping-set output see the NULL-ed columns.

The cube lattice: nodes are group-bys (subsets of the D dimensions); an edge
from q to q' when q' drops exactly one attribute of q. With hierarchies, the
lattice is the product of each dimension's hierarchy lattice (levels incl.
ALL), so its size is Π (levels_d + 1) rather than 2^D.

## 2. Execution strategies for grouping sets

### 2.1 Expand + single aggregation

```
for each input row r:
   for each set s (bitmask):
      emit (mask_cols(r, s), gid = s, measures(r))
HashAggregate(keys = grouping_cols ∪ {gid})
```

Simple and parallel-friendly (one shuffle on (keys, gid)), but multiplies
input volume by k. Fine for small k or when partial aggregation runs before
the expand; poor for CUBE over many columns.

### 2.2 Sort chains (ROLLUP for free)

Sorted on (a,b,c), one streaming pass produces (a,b,c), (a,b), (a), () by
closing groups at each prefix boundary — this is the "share-sorts" idea. A
set of grouping sets is covered by chains in the inclusion order; the minimum
number of sorts equals the size of the largest antichain (Dilworth). For a
full CUBE over n columns that is C(n, ⌊n/2⌋) (Sperner; a symmetric chain
decomposition achieves it): n=4 → 6 sorts instead of 16 group-bys.

### 2.3 Smallest parent / reuse of partial results

For distributive and algebraic aggregates, compute each node from its
smallest already-computed parent rather than from the base table. The
estimated output sizes (see `cardinality-and-statistics`) drive the choice.

> **Beyond EDBS:** PostgreSQL plans grouping sets as a mix of sorted chains
> and hash tables ("MixedAggregate") and Spark SQL uses an Expand operator
> feeding a hash aggregate; both are instances of 2.1/2.2.

## 3. The five sharing optimizations (Agarwal et al., VLDB 1996)

| Optimization | Meaning |
|---|---|
| Smallest-parent | compute a group-by from the smallest previously computed ancestor |
| Cache-results | keep a computed result in memory to compute its children without I/O |
| Amortize-scans | compute as many group-bys as possible in one scan of a parent |
| Share-sorts | (sort-based) one sort serves all prefix group-bys; reuse partial sort orders |
| Share-partitions | (hash-based) partition once on an attribute, compute many group-bys per partition |

They conflict: smallest-parent may pick a parent whose sort order is useless
for its child; PipeSort and PipeHash are two ways to resolve the conflict.

## 4. PipeSort

Input: lattice with estimated sizes; costs A(i,j) (compute j from i when i is
already sorted with j as a prefix: scan cost) and S(i,j) (re-sort i first).

```
for level k = 0 .. D-1 (from coarse to fine is equivalent; paper goes top-down by k):
   build bipartite graph: left = nodes at level k+1, right = nodes at level k
   make k+1 copies of each left node i:
       copy 0 has edge cost A(i,j) to each child j   (child inherits i's order)
       copies 1..k have edge cost S(i,j)             (child needs a re-sort)
   solve min-cost bipartite matching covering all right nodes
   result: each parent passes its order to at most one child "for free"
connect the A-edges into pipelines; each pipeline = one sort + one scan
```

Complexity is dominated by the per-level weighted matchings (polynomial).
Output: a set of pipelines, each starting with one sort, so total cost ≈
Σ sorts + Σ scans. Works well when the cube is dense enough that sorting is
the cost; for very sparse cubes, Overlap-style partitioned sorting (Deshpande
et al.) reduces I/O.

## 5. PipeHash

```
T = minimum spanning tree of the lattice using smallest-parent edges
while T not empty:
   pick subtree rooted at r that fits in memory as hash tables, else
      partition r's input on an attribute a common to the subtree, recurse per partition
   scan r once, update all hash tables of the subtree (amortize-scans)
   write results, remove subtree
```

Hashing excels for dense low-cardinality cubes and when memory holds many
hash tables at once.

## 6. MOLAP: MultiWay array cubing (Zhao, Deshpande, Naughton, SIGMOD 1997)

Store the base cube as a chunked array (chunks are dense sub-arrays; sparse
chunks compressed as (offset-in-chunk, value) pairs). Read chunks in a fixed
dimension order and update every aggregate array simultaneously, flushing an
aggregate chunk as soon as all base chunks contributing to it were read.

Memory rule (dimensions A varying fastest, then B, then C slowest; chunk
extents c_A, c_B, c_C):

| Aggregate | Aggregates away | Memory needed |
|---|---|---|
| BC | A (fastest) | one chunk face: c_B · c_C |
| AC | B | a full row along A: \|A\| · c_C |
| AB | C (slowest) | a full plane: \|A\| · \|B\| |

Worked example: |A|=40, |B|=400, |C|=4000, chunks 10, 100, 1000 → 16,000 +
40,000 + 100,000 = 156,000 cells. Reversing the order (largest varying
fastest) needs |C|·|B| = 1,600,000 for the plane alone. Rule: **order
dimensions so the smallest vary fastest**; then compute coarser aggregates
from the 2-D results via a minimum memory spanning tree.

Pros: no sorting/hashing; position encodes coordinates. Cons: needs a dense
enough base array; dimension-value additions force re-layout. MM-Cubing
(Shao, Han, Xin 2004) applies array techniques only to dense subspaces.

## 7. Iceberg cubes and BUC (Beyer, Ramakrishnan, SIGMOD 1999)

An iceberg cube stores only cells whose aggregate satisfies a threshold
(e.g. COUNT(*) ≥ minsup) — essentially frequent-itemset counting over group-bys.

```
BUC(input, dim_start, prefix):
   write cell(prefix, aggregate(input))          -- only reached if threshold held
   for d in dim_start .. D-1:
      partitions = counting_sort(input, on d)     -- O(n) per dimension
      for each partition p with value v:
         if threshold(p) holds:                   -- anti-monotone: safe to prune
            BUC(p, d + 1, prefix ∪ {d = v})
```

- Computes from the apex (ALL) toward the base: coarse cells first, fine cells
  only inside qualifying partitions.
- **Anti-monotonicity** is the correctness condition: if a cell fails, all its
  descendants (finer cells) fail. COUNT ≥ t and SUM ≥ t over non-negative
  values qualify; AVG ≥ t does not — use a top-k average bound (Han et al.,
  SIGMOD 2001) that is anti-monotone and filter the true condition afterward.
- Order dimensions by **decreasing cardinality** so partitions shrink fast and
  pruning starts early; skewed data weakens pruning.
- No sharing of sorts between siblings — BUC trades sharing for pruning.

## 8. Compressed full cubes: removing redundancy

Most cube tuples are redundant: a base tuple that is alone in its partition
reproduces itself in every coarser group-by.

| Method | Idea | Property |
|---|---|---|
| Condensed cube (Wang et al. 2002) | store single-tuple partitions once ("base single tuples") | fully materialized semantics, much smaller |
| Dwarf (Sismanis et al. 2002) | DAG eliminating **prefix** (shared leading values) and **suffix** (shared trailing sub-cubes + aggregates) redundancy | polynomial size in D for fully coalesced cubes (Sismanis, Roussopoulos 2004); doubles as an index for point/range queries |
| QC-trees (Lakshmanan, Pei, Zhao 2003) | quotient cube: classes of cells with the same aggregate and cover | preserves roll-up/drill-down semantics |
| CURE (Morfonios, Ioannidis 2006) | ROLAP-native, hierarchies, external partitioning, redundancy-free relational storage | integrates with an RDBMS; handles data far larger than memory |
| Approximate (histograms, wavelets) | lossy synopses of the cube (Poosala & Ganti; Vitter & Wang 1999) | bounded error, tiny footprint |

Counter-intuitive lesson from the literature: compressed cubes often answer
queries **faster** than uncompressed full cubes, because an uncompressed
2^D-table cube is hard to index well, while structures like Dwarf are their
own index.

## 9. Partitioning for out-of-memory cube computation

All serious algorithms first partition the fact table so that tuples that
aggregate together land in the same partition (partition on a grouping
attribute); each partition is then cubed in memory and results of group-bys
that include the partitioning attribute are final. Group-bys excluding it
need a second pass (or a recursive scheme as in CURE). External sort/hash
without this costs a factor 2–3 in I/O.

Parallel cubing: either array-based (Goil, Choudhary 1998) or relational
(cgmCUBE, Dehne, Eavis, Rau-Chaplin 2006; Jin et al. 2005 for
communication/memory-optimal construction). The MPP pattern is: local
partial cube per node → shuffle partial cells by group-by key → final merge;
only valid for mergeable aggregates.

## 10. Choosing what to materialize: the view selection problem

Selecting the optimal subset of cube nodes under a space (or maintenance)
budget is NP-complete (HRU) / NP-hard in general variants.

### 10.1 HRU greedy (Harinarayan, Rajaraman, Ullman, SIGMOD 1996)

Linear cost model: answering w costs the size of the smallest materialized
ancestor of w.

```
S = { top view (base group-by) }
repeat k times:
   for each candidate v ∉ S:
      B(v,S) = Σ_{w ⪯ v} max(0, cost_S(w) − |v|)      -- w ranges over v and its descendants
   S = S ∪ { argmax_v B(v,S) }
```

- Guarantee: greedy benefit ≥ 1 − ((k−1)/k)^k ≥ 1 − 1/e ≈ 63% of the optimal
  benefit for k views; cost O(k·n²) with n lattice nodes.
- Space-constrained variant: maximize benefit per unit space; the bound
  degrades when a single view is very large relative to the budget.
- Query frequencies weight the sum; hierarchies enlarge the lattice to the
  product of hierarchy lattices.

Small example (sizes in rows): base ABC = 100M; AB = 50M; AC = 20M; BC = 1M;
A = 10K; B = 500; C = 1K; ALL = 1. First pick: BC benefits {BC, B, C, ALL}
each by 99M → 396M; AC benefits {AC, A, C, ALL} each by 80M → 320M; BC wins.
Second round recomputes costs with BC materialized (B, C, ALL now cost 1M):
AC benefits only AC and A, by 80M each (its other descendants already cost
less than 20M) → 160M, beating A (≈ 101M) and AB (100M); AC is picked; and so on.

### 10.2 Extensions

| Work | Adds |
|---|---|
| Gupta (ICDT 1997) | AND/OR view graphs (multiple plans per view), indexes selected together with views; greedy with performance guarantees for restricted graph classes |
| Gupta, Mumick (ICDT 1999) | maintenance-cost constraint; benefit no longer monotone, simple greedy can be arbitrarily bad; inverted-tree greedy and A*-style search |
| Yang, Karlapalem, Li (VLDB 1997) | multiple-view processing plans merged across the workload |
| Kotidis, Roussopoulos — DynaMat (SIGMOD 1999) | dynamic materialization of query fragments in a pool with admission/replacement |
| Survey: Mami, Bellahsene (SIGMOD Rec 2012) | deterministic, randomized, evolutionary and hybrid algorithm classes |

Engine guidance: the view-selection algorithm is only as good as the size
estimates. Cuboid size estimation needs distinct-value estimates of attribute
combinations — use sketches (HLL per candidate combination computed in one
pass) rather than independence assumptions, which overestimate badly for
correlated hierarchical attributes (city → state).

## 11. Answering queries from materialized cube nodes

- Pick the smallest materialized ancestor in the lattice that passes the
  summarizability guard (see `dimensional-semantics-and-summarizability.md`).
- If predicates reference a dimension attribute not in the view, but the
  view keeps the dimension key at a finer level, join the view to the
  dimension and filter — still cheaper than the base fact.
- Union of views: a query may be answered by combining partitions of
  different views (e.g. recent months from base data, older months from a
  monthly aggregate) — requires the partitioning predicates to be disjoint and
  complete.

> **Beyond EDBS (Teradata):** an aggregate join index is a persistent
> aggregate (optionally pre-joined) that the optimizer uses transparently
> when its grouping covers the query and its definition subsumes the query
> predicates, and is maintained automatically on base-table changes — a
> production instance of §11 plus §12.

## 12. Incremental maintenance of cubes and summary tables

Two-phase scheme used by most algorithms (Mumick, Quass, Mumick, SIGMOD 1997):

1. **Propagate**: from the change set ΔF (inserts +, deletes −) compute the
   *summary-delta* — aggregate ΔF to the view's grouping, with signed SUM and
   COUNT. Done outside the batch window, without touching the views.
2. **Refresh**: merge summary-delta into each view: matching group → add
   deltas; new group → insert; COUNT(*) reaching 0 → delete the group.

Rules:

- Every maintainable aggregate view must carry COUNT(*) (to detect empty
  groups) and COUNT(x) for nullable measured columns (to know when SUM(x)
  becomes NULL).
- MIN/MAX are self-maintainable under insert but not delete: if the deleted
  value equals the stored extreme, recompute that group from base data.
- Lower lattice nodes' deltas are computed from higher nodes' deltas
  (smallest-parent applies to deltas too); Lee and Kim (VLDB 2006) optimize
  the propagation phase by choosing which delta-cube nodes to build.
- Updates to dimension attributes (SCD type 1) move facts between groups of
  every view grouped by that attribute: treat as delete-old + insert-new for
  all affected facts; this is why type-1 changes on a hierarchy level are
  expensive.
- Refresh must be atomic per view (or per consistent set of views) so that
  queries rewritten to different views see the same snapshot.

## 13. Cube maintenance and storage format interplay

| Format | Refresh cost driver |
|---|---|
| ROLAP summary tables | index maintenance on the summary tables; batch MERGE |
| MOLAP chunked arrays | chunk rewrite; new dimension members may require re-chunking |
| Dwarf/condensed | structural merge; Dwarf supports bulk incremental updates but with structure-specific algorithms |
| Column store projections | append to delta store; aggregates recomputed per partition |

## 14. Test plan

- Grouping-set oracle (union of GROUP BYs) on random schemas, with duplicates,
  NULLs and empty input.
- For each cube algorithm: output equals naïve per-group-by computation;
  property tests with random dimension cardinalities and skew.
- Iceberg: compare with full cube filtered by the threshold; include an AVG
  threshold to make sure no direct pruning happens.
- View selection: on small lattices compare greedy with exhaustive optimum and
  assert the 63% bound empirically.
- Maintenance: random insert/delete/update streams; after each refresh views
  equal recomputation; target MIN/MAX deletions and groups becoming empty.

Sources: EDBS — Cube Implementations p.710; Cube p.709; Online Analytical
Processing p.2558; Optimization and Tuning in Data Warehouses p.2619;
Parallel and Distributed Data Warehouses p.2644; Query Processing in Data
Warehouses p.3039; Measure p.2217.
