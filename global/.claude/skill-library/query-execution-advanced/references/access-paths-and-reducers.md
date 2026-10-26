# Access paths, index nested loops, semijoin reducers, filter/refine and object-relational execution

Scope: how a single relation is read (scan vs index vs index-only), how the
executor uses indexes inside joins, how semijoins and bit-vector filters
shrink inputs before expensive work, how multi-step (filter/refine)
processing handles costly predicates, and what object-relational features
(methods, UDFs, path expressions) do to execution.

---

## 1. Access path selection

An **access path** is the method used to fetch the qualifying tuples of one
relation: a sequential scan of the file (heap), or an index scan whose index
*matches* the selection condition, i.e., the index alone can locate every
tuple satisfying it. Every commercial system has heaps and B+-trees; most
also have hash indexes for equality.

Matching rules (state them in the planner and test them):

| Index | Matches | Does not match |
|---|---|---|
| B+-tree on (a, b, c) | equality on a prefix (a), (a,b), (a,b,c); equality prefix + one range on the next column (a = 1 AND b > 5); range on a | predicates on b or c without a (unless a skip-scan exists); range on a then predicate on b used as a seek key |
| Hash index on (a, b) | equality on *all* key columns | ranges, prefixes, IS NULL (unless NULLs are hashed) |
| Clustered (sorted file) on a | binary search/seek to first qualifying tuple, then scan until the predicate fails | |

Residual predicates that the index cannot use as seek keys are still
evaluated on the index entry (if the columns are present) before fetching the
base row — cheaper than evaluating after the fetch.

### Cost model (Selinger et al., SIGMOD 1979)

The optimizer enumerates matching access paths, estimates for each the number
of pages touched (EDBS calls this the access path's *selectivity*: index pages
plus data pages), and the cheapest is the *most selective* path. With h = index
height, s = predicate selectivity, B = data pages, T = tuples, L = leaf pages:

| Path | Page I/O (approx.) | Access pattern |
|---|---|---|
| Heap scan | B | sequential, prefetchable |
| Clustered index range | h + s·B | one seek then sequential |
| Unclustered index, fetch per entry | h + s·L + s·T (worst case one random page per tuple) | random |
| Unclustered index, RIDs sorted before fetch | h + s·L + Cardenas(B, s·T) | ascending page order, each page once |
| Index-only (covering) | h + s·L | sequential over leaves |
| RID intersection of several indexes | Σ index costs + Cardenas(B, s₁·s₂·…·T) | |

Cardenas' estimate of distinct pages touched when k tuples are drawn
uniformly from m pages: m·(1 − (1 − 1/m)^k); Yao (CACM 1977) gives the exact
form without replacement. Use them for the sorted-RID fetch; never assume
"one I/O per tuple" and "one I/O per page" interchangeably.

Engineering consequences:

- The **break-even selectivity** for an unclustered fetch-per-entry plan is
  tiny (on the order of B/T, i.e., a few rows per page); above it a scan wins
  because it is sequential. Sorting RIDs before fetching (PostgreSQL bitmap
  heap scan, DB2 list prefetch) moves the break-even far higher and should be
  the default for medium selectivities.
- On SSD/NVMe the random/sequential gap shrinks but does not vanish (request
  overheads, read amplification on 4–16 KB pages); recalibrate the constants
  instead of hard-coding disk ratios.
- **Index-only** needs every referenced column in the index *and* a way to
  decide visibility without the heap (e.g., PostgreSQL's visibility map; MVCC
  engines that store versions only in the heap otherwise must fetch).
- An index can serve **order** (interesting order) as well as selection: a
  scan of an index whose key prefix equals the ORDER BY / GROUP BY / merge-join
  key avoids a sort. Aggregation over a covering index whose key starts with
  the grouping columns becomes a streaming aggregate with no sort and far
  fewer pages than the base table.
- Membership (equality) queries are the degenerate range [x, x]; hash or
  B+-tree. Range queries need an order-preserving index; multidimensional
  ranges need R-tree-family or space-filling-curve indexes (see
  `multidimensional-and-similarity-indexing`).

---

## 2. Index nested-loop join (index join) beyond the basics

For each outer tuple, probe an index on the inner's join column instead of
scanning the inner. Applicable when a join column is the **leading** key of the
inner index; equality predicates do a lookup, range/band predicates do a seek
to the first match then a leaf scan.

Cost ≈ B(outer) + T(outer)·(probe cost + matches × fetch cost). INL wins when
T(outer) is small (after filters) or when the query has a small LIMIT, because
it is fully pipelined and returns first rows immediately. It loses when many
outer rows each fetch scattered inner pages — then block NLJ or hash join is
cheaper even though they read the whole inner.

Execution techniques that matter more than the textbook formula:

1. **Sort or batch the outer keys** before probing. Sorted probes sweep the
   index left to right, so upper levels and leaves are hit with locality and
   duplicates collapse; several commercial engines batch-sort outer rows for
   exactly this reason. Preserves correctness only if the plan does not rely
   on outer order above the join — or the operator restores it.
2. **Buffer probes level by level** (Zhou & Ross, VLDB 2003): push a batch of
   probes through one tree level at a time so each node is brought into cache
   once per batch; turns cache misses per probe into amortised misses per
   node. Same idea as vectorized probing.
3. **Prefetch** the next probes' root-to-leaf paths while processing the
   current one (Chen, Gibbons & Mowry, SIGMOD 2001 for index prefetching).
4. **Cache inner results per distinct outer key** when the outer has repeated
   keys (correlated subqueries are the common case).
   > **Beyond EDBS:** PostgreSQL 14 added a `Memoize` node that caches inner
   > results of parameterised nested loops keyed by the parameter values,
   > with LRU eviction under a memory budget.
5. **Zig-zag / merge with the index:** if the outer is sorted on the key, a
   merge join *against the index leaves* avoids random probes entirely;
   retrieve remaining columns afterwards via the RIDs (EDBS sort-merge
   improvement).

NULL outer keys must never probe for equality (they cannot match); for
null-safe equality (`IS NOT DISTINCT FROM`, used in set operations and some
rewrites) the index must store and seek NULLs explicitly.

---

## 3. Semijoin and bit-vector reducers

Definition: R ⋉_{A=C} S = π_attr(R)(R ⋈_{A=C} S) — the R tuples that have at
least one partner. It is a **reducer** (result ⊆ R) and **asymmetric**
(R ⋉ S ≠ S ⋉ R). Equivalences used for planning:

```
R ⋈ S  =  (R ⋉ S) ⋈ S  =  R ⋈ (S ⋉ R)  =  (R ⋉ S) ⋈ (S ⋉ R)
```

### Distributed semijoin program (SDD-1, Bernstein et al.)

R at site 1, S at site 2:
1. Site 1 sends π_A(R) to site 2.
2. Site 2 computes S' = S ⋉_{C=A} π_A(R) (only S tuples that will join).
3. Site 2 ships S' to site 1.
4. Site 1 computes R ⋈ S'.

Transfer-only cost comparison against "ship whole" (send the smaller relation
S): semijoin wins iff size(π_A(R)) + size(S ⋉ R) < size(S); since the
semijoin keeps S's width, that means the semijoin must actually *reduce* S
(|S ⋉ R| < |S|) by more than the cost of shipping the key column. If nearly
every S tuple joins, ship-whole wins. Estimate the reduction from the
fraction of S's join-key domain present in R (e.g., |π_A(R)| / |distinct
values of C's domain| under containment assumptions). Distributed planning
detail lives in `distributed-dbms-design`.

### Bloom (hash-filter, bit-vector) join

Replace π_A(R) by a bit vector: set B[h(v)] for each key v of R, ship B, keep
S tuples whose B[h(t.C)] is set. False positives (hash collisions) send a few
useless S tuples back — correctness is preserved because the final join
rechecks the predicate; false negatives are impossible. With k hash functions
over m bits and n keys, false-positive rate ≈ (1 − e^(−kn/m))^k, minimised at
k = (m/n)·ln 2. Experimental work on R* (Mackert & Lohman) found the hash-filter
variant beating plain semijoin and ship-whole across most sizes; plain
semijoin only won when the inner fit in the buffer. Early proposals: Babb
(TODS 1979) for specialised hardware, Valduriez for database machines.

### Local (single-node) uses

- **Runtime join filters:** build a Bloom/min-max filter from the hash join
  build side and push it into the probe-side scan (or across an exchange)
  before rows are decoded, shuffled or joined. Big wins for selective
  dimension filters on star schemas.
  > **Beyond EDBS:** widely shipped as "runtime filters" / "dynamic partition
  > pruning" (Impala, Spark, Trino and others), including min/max ranges for
  > zone-map pruning of Parquet/ORC row groups.
- **Star joins via index semijoins:** semijoin each filtered dimension with a
  fact-table index to collect fact RIDs, intersect the RID sets (bitmaps),
  then fetch only qualifying fact rows (`olap-and-warehouse-engines`).
- **Sources with limited capabilities:** sending a set of bindings to a
  component source that only answers parameterised selections *is* a
  semijoin (data integration, foreign tables).
- **EXISTS / IN subqueries** are semijoins; NOT EXISTS is an anti-join; NOT IN
  is a *null-aware* anti-join (any NULL in the subquery result makes every
  comparison unknown → empty result unless the subquery is empty). Unnesting
  EXISTS into a plain inner join is valid only when the inner block returns
  at most one row per outer row (e.g., the inner join column is a key);
  otherwise it duplicates outer rows — use a semijoin or add DISTINCT on the
  outer key (EDBS object-relational entry's rewrite example rests on exactly
  this condition).

Invariant to test: semijoin output contains each qualifying left row once,
regardless of how many partners it has (hash semijoin must stop probing after
the first match; sort-merge semijoin must not emit per partner).

---

## 4. Multi-step (filter/refine) query processing

For predicates that are costly to evaluate exactly (polygon intersection,
edit distance, dynamic time warping, road-network shortest paths), run one or
more cheap **filter** steps over approximations, then a **refine** step with
the exact predicate on the remaining candidates.

- **Conservative approximation** (contains the object, e.g., MBR) gives a
  **lower-bounding** distance LB(x,y) ≤ dist(x,y): any object with LB > ε is
  a **true drop** (safe to prune).
- **Progressive approximation** (contained in the object, e.g., inscribed
  circle) gives an **upper-bounding** distance UB(x,y) ≥ dist(x,y): any
  object with UB ≤ ε is a **true hit** (report without refinement).
- Correctness requires *no false drops and no false hits*; a filter that is
  neither lower- nor upper-bounding cannot be used to prune.
- Order filters by cost and selectivity (fraction decided as hit or drop) —
  the same ranking problem as ordering expensive predicates (section 5).
- Only the first filter can be an index (indexes organise the whole
  database, not an arbitrary candidate set); later filters are sequential
  tests over candidates.
- Reporting true hits from filters early improves time-to-first-result.

### Multi-step kNN

ε is not known in advance for kNN, so the circular dependency (need d(q,k) to
filter, need refinements to know d(q,k)) is broken by:

1. Korn et al. (VLDB 1996): refine any k candidates, take the max exact
   distance d' ≥ d(q,k), then run a multi-step range query with ε = d'; sort
   refined results and keep the k best.
2. Seidl & Kriegel (SIGMOD 1998): consume a *ranking* of objects by filter
   distance (incremental NN over the index); keep the current k best exact
   distances; refine the next candidate only while its filter distance ≤
   current kth exact distance; stop at the first candidate whose filter
   distance exceeds it. With a single conservative (lower-bounding) filter
   this is optimal in the number of refinements.
3. Using both a lower- and an upper-bounding filter (Kriegel, Kröger and
   colleagues) lets d(q,k) be bounded from the progressive filter before
   refinement, reducing refinements further.

The lower-bounding lemma is also the basis of dimensionality-reduced
time-series search (GEMINI, Faloutsos et al., SIGMOD 1994): index reduced
features with a distance that lower-bounds the true one.

---

## 5. Object-relational execution

Object-relational SQL (SQL:1999 onward) adds user-defined types, methods,
inheritance (typed tables), references/path expressions, and polymorphism.
The processing pipeline stays parse → semantic check → rewrite (using keys,
uniqueness, foreign keys, integrity constraints) → physical optimization
(access path per relation, join order, join method) → execution, but the
executor must handle:

| Feature | Execution concern | Technique |
|---|---|---|
| Methods / UDFs in predicates | Per-tuple cost may dwarf I/O; cost and selectivity unknown | Order conjuncts by rank = (selectivity − 1) / per-tuple cost (ascending); migrate expensive predicates above joins when that reduces invocations (Hellerstein & Stonebraker, SIGMOD 1993; Hellerstein, TODS 1998) |
| Deterministic UDFs with repeated arguments | Redundant invocations | Memoise results keyed by argument values within a query |
| Path expressions (`e.dept.manager.name`) | Pointer chasing → random I/O per step | Treat dereference as a join on OID; batch/sort OIDs before fetching (same as sorted RID fetch); consider value-based join plans |
| Inheritance / typed tables | A query over a supertype scans all subtypes | Plan as UNION ALL over subtables; push predicates into each branch; prune branches by type predicates |
| Polymorphic (late-bound) methods | Implementation chosen per object | Group rows by dynamic type before invoking, or dispatch per batch |
| Large objects / complex values | Expensive to materialise and copy | Pass handles/references through the pipeline; fetch lazily at the consumer |
| Costly spatial/similarity predicates | Exact evaluation dominates | Filter/refine (section 4) |

Invariants: the planner must never reorder a non-deterministic or
side-effecting UDF across operators that change how many times it is invoked
unless the function is declared safe for that; volatility classes
(immutable/stable/volatile) are part of the operator contract.

---

## 6. Test checklist

- Access path choice vs selectivity sweep: plot measured time of scan,
  unclustered fetch, sorted-RID fetch and index-only across s ∈ [1e-6, 1];
  the optimizer's crossover must land near the measured one.
- Matching-rule unit tests: every predicate shape against every index shape,
  including NULL predicates, IN-lists (multiple seeks), and descending keys.
- INL with duplicate outer keys, NULL outer keys, range predicates with
  inclusive/exclusive bounds, outer joins (unmatched outer rows preserved).
- Semijoin/anti-join with: many partners per row (no duplication), NULL keys
  on each side, empty inner (anti-join returns all; NOT IN with empty
  subquery returns all, with a NULL in the subquery returns none).
- Bloom filter: force tiny filters (high FP rate) and confirm identical
  results; confirm filters never drop a true match (no false negatives) under
  hash-seed changes.
- Filter/refine: property test that filter-refine output equals brute-force
  exact evaluation on random polygons/sequences; assert LB ≤ dist ≤ UB on
  random pairs.

Sources: EDBS entries Access Path (p.22), Evaluation of Relational Operators
(p.1348), Index Join (p.1845), Nested Loop Join (p.2485), Membership Query
(p.2222), Range Query (p.3079), Semijoin (p.3436), Multi-step Query Processing
(p.2435), Query Processing and Optimization in Object Relational Databases
(p.3032), Cache-Conscious Query Processing (p.389).
