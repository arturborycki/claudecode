# System R / R* architecture and join-order enumeration

How a cost-based optimizer organizes its search: the System R blueprint (still
the skeleton of DB2, PostgreSQL and most bottom-up planners), its distributed
extension R*, the generalization of interesting orders into physical
properties, the exact DP algorithms over the query graph, top-down memo search,
non-inner joins, and what to do when the query is too large to enumerate.

## 1. The System R pipeline

Four phases per statement: parse -> optimize -> generate code -> execute.

- A statement is one or more **query blocks**. A block is a SELECT list, a FROM
  list and a WHERE tree (Boolean combination of simple predicates). Nested
  blocks appear where a predicate operand is itself a query.
- The optimizer resolves names and types against the catalog, performs the
  semantic checks, pulls statistics and the available access paths, and picks a
  minimum-cost plan. The plan was emitted in an access specification language
  (ASL) and compiled to machine code that calls the storage layer.
- Storage (RSS) exposes two scan types through the RSI tuple-at-a-time
  interface: **segment scans** (visit every non-empty page of the segment holding
  the relation) and **index scans** (B-tree, leaf chain read in key order, with
  optional start/stop keys). An index is **clustered** when physical tuple order
  follows key order, so each data page is touched once during a scan.
- **SARGs** (search arguments) are simple `column op value` predicates the RSS
  evaluates before returning a tuple across the RSI. They matter to the cost
  model: they cut CPU (RSI calls) but not page fetches.

Engine-builder takeaway: the boundary at which a predicate is evaluated
(storage-level pushdown vs operator-level filter) is a cost-model input, not just
an executor detail. Columnar engines have the same split (zone-map/page pruning
vs post-decode filter).

## 2. Single-relation access path selection

Cost of an access path:

```
COST = PAGE_FETCHES + W * RSI_CALLS
```

`PAGE_FETCHES` counts index plus data pages; `RSI_CALLS` (tuples crossing the
storage interface) proxies CPU because most CPU time was spent in the RSS. `W`
is a tunable I/O-vs-CPU weight. Statistics used: relation cardinality (NCARD),
pages occupied (TCARD), fraction of segment pages holding the relation (P),
per index the number of distinct keys (ICARD) and pages (NINDX).

Two derived counts:
- `QCARD` = product of FROM-list cardinalities x product of selectivity factors
  of all block predicates (the block's output).
- `RSICARD` = product of cardinalities x product of selectivity factors of the
  **sargable** predicates only (what crosses the interface).

Per-path formulas as reported in Selinger et al. 1979 (F = selectivity of the
predicates matched by the index):

| Situation | Cost |
|---|---|
| unique index, equality match | 1 + 1 + W |
| clustered index, matching predicates | F*(NINDX + TCARD) + W*RSICARD |
| non-clustered index, matching predicates | F*(NINDX + NCARD) + W*RSICARD |
| clustered index, no matching predicate | NINDX + TCARD + W*RSICARD |
| non-clustered index, no matching predicate | NINDX + NCARD + W*RSICARD |
| segment scan | TCARD/P + W*RSICARD |

The non-clustered formulas charge one page fetch per qualifying tuple (worst
case: no buffer reuse); the paper notes a cheaper variant when the relation fits
in the buffer. Modern equivalents replace this with a page-fetch model driven by
the physical correlation between index order and heap order (e.g., PostgreSQL's
`correlation` statistic interpolating between the clustered and random cases),
or with the Yao/Cardenas formula for distinct pages touched.

Ordering: for each relation keep the cheapest unordered path **and** the
cheapest path per interesting order. For a single-relation block with ORDER BY
or GROUP BY, compare `cheapest ordered path` against `cheapest unordered +
sort(QCARD)`.

## 3. Joins in System R

Two methods were judged sufficient: nested loops and merging scans.

```
C_nl(path1, path2)    = C_outer(path1) + N * C_inner(path2)
C_merge(path1, path2) = C_outer(path1) + N * C_inner(path2)      (+ sort costs)
C_inner(sorted temp)  = TEMPPAGES / N + W * RSICARD
```

`N` = product of the cardinalities of the relations joined so far times the
selectivities of the applicable predicates, i.e. the outer's output
cardinality. With a sorted temporary inner, the merge does not rescan; the inner
cost per outer tuple collapses to its share of the temp pages. Merge scans make
**join columns** interesting orders, in addition to ORDER BY and GROUP BY columns.
Columns related by equi-join predicates form an equivalence class, so an order
on any member serves the class.

Search: **linear (left-deep) trees** only; a composite (already-joined) outer is
extended by one base inner. DP over relation subsets organized by size:

```
for each relation R: best[{R}] = { cheapest path per interesting order, cheapest unordered }
for s in 2..n:
  for each S with |S| = s-1 that has an entry, for each R not in S:
    if no join predicate links R to S and some other R' does: skip   # defer cross products
    for each plan p in best[S], each method m, each access path a of R:
      q = join(m, p, a); keep q in best[S + R] unless dominated
answer = cheapest plan in best[All] with the order the query requires (or + sort)
```

This reduces the search from O(n!) orderings to O(n * 2^n) subset extensions;
banning cross products shrinks it further (polynomial for a chain query).

Worked interesting-order example: R1.x = R2.x and R2.x = R3.x. For {R1, R2} the
nested loop costs C1 < merge cost C2. Keeping only the NL plan would be wrong:
the merge plan's output is sorted on x (the equivalence class {R1.x, R2.x,
R3.x}), which can make the subsequent merge with R3 skip a sort. Both survive
because their order properties are incomparable.

## 4. R*: distributed extension

Unit of distribution is a relation stored at one site. Two new factors:
communication delay and the chance of concurrent work at several sites.

Decisions the R* optimizer adds to System R's (method, order, access path):
- **Join site** for each join.
- **Inner transfer strategy** when the inner is remote:
  - *ship whole*: send the inner relation once, store it as a temp at the join
    site (an index can be built on it — "dynamically created index").
  - *fetch matches*: for each outer tuple send its join value and receive the
    matching inner tuples. Message-heavy; wins for a tiny outer.
  - *semijoin*: project the outer on the join column, ship to the inner site,
    reduce the inner to matching tuples, ship those back, join.
  - *Bloom join*: ship a Bloom filter of the outer's join values instead of the
    values; false positives cost extra shipped tuples, never wrong results.
- Cost is a weighted sum of CPU instructions, I/Os, messages and bytes shipped
  (Lohman et al. 1985). Mackert & Lohman (VLDB 1986) validated the model on
  the running system and found Bloom joins generally beat semijoins.

## 5. Physical properties: generalizing interesting orders

A **physical property** affects the cost of later operators but not logical
equivalence: sort order, grouping (clustering by key without total order),
partitioning/distribution, uniqueness, materialized vs pipelined, memory
footprint. Properties define a partial order, and DP's principle of optimality
holds only within it:

```
p dominates q  iff  cost(p) <= cost(q)  and  props(p) >= props(q)
DP cell(S) = Pareto set of non-dominated plans
```

Order reasoning that pays off (Simmen, Shekita & Malkemus, SIGMOD 1996):
- Reduce an order using **constants** (`WHERE a = 5` makes `a` free in `ORDER BY a, b`),
  **equivalence classes** (`a = b` makes an order on a serve b) and **functional
  dependencies** (if key k -> c, then order (k, c) reduces to (k)).
- Compute interesting orders before enumeration so that only plans producing
  potentially useful orders are kept; otherwise the Pareto sets explode.
- Neumann & Moerkotte (VLDB 2004) encode orders and groupings in a precomputed
  finite-state machine so property tests are O(1) per plan.

In a Cascades-style optimizer the same idea appears as **required properties**
passed top-down plus **enforcers** (Sort, Exchange/Repartition) inserted when a
child cannot deliver the requirement.

## 6. Search-space sizes

Without a query graph:
- Tree shapes with n leaves: Catalan(n-1), growing roughly like 4^n / n^1.5.
- Labeled bushy trees: n! * Catalan(n-1). Left-deep trees: n!.

With a query graph and no cross products, the DP table holds one cell per
**connected subgraph (csg)**, and the work is the number of **csg-cmp pairs**
(S1 connected, S2 connected, disjoint, joined by at least one edge). Counts for
unordered pairs (Ono & Lohman VLDB 1990; Moerkotte & Neumann VLDB 2006):

| Graph | #csg (DP cells) | #csg-cmp pairs (join work) |
|---|---|---|
| chain | n(n+1)/2 | (n^3 - n)/6 |
| cycle | n^2 - n + 1 | (n^3 - 2n^2 + n)/2 |
| star | 2^(n-1) + n - 1 | (n-1) * 2^(n-2) |
| clique | 2^n - 1 | (3^n - 2^(n+1) + 1)/2 |

Use these as exact test oracles for an enumerator. Complexity: optimal join
ordering is NP-hard in general (Ibaraki & Kameda, TODS 1984, for nested-loop
costs; cross products make it hard even for simple cost functions), yet chains
are polynomial. Real queries sit between chain and clique, mostly closer to
chain/star (snowflakes), which is why connectivity-aware DP is practical.

Left-deep vs bushy: left-deep keeps one pipelined probe path and a small
search space, but the optimum is frequently bushy (two dimension branches
filtered independently and then joined). Most modern optimizers enumerate bushy
trees; zig-zag trees (each join has at least one base input) are a middle ground.

## 7. Bottom-up DP variants

**DPsize** (System R generalized to bushy, as in the EDBS Query Optimization
entry): for s = 2..n, for every pair of solved sets (S1, S2) with |S1|+|S2| = s,
skip if they overlap or are not connected by an edge, else combine. Simple but
performs many failing overlap/connectivity tests; reasonable on chains and
cycles, poor on stars and cliques.

**DPsub**: iterate S over all subsets in increasing integer (bitset) order, so
every subset precedes its supersets; for each non-empty proper S1 of S, set S2 =
S \ S1 and test connectivity. Visits O(3^n) pairs regardless of graph shape:
good for cliques, wasteful for chains. Submask iteration:

```rust
let mut s1 = (s - 1) & s;          // all non-empty proper submasks, descending
while s1 != 0 { let s2 = s ^ s1; /* test, combine */ s1 = (s1 - 1) & s; }
```

**DPccp** (Moerkotte & Neumann 2006): enumerates exactly the csg-cmp pairs, so
its work matches the lower bound of any DP over this space. Number relations
v0..v(n-1) (e.g., by BFS from a root); let B_i = {v_j : j <= i}.

```
EnumerateCsg():
  for i = n-1 downto 0:
    emit {v_i}
    EnumerateCsgRec({v_i}, B_i)

EnumerateCsgRec(S, X):
  N = neighbours(S) \ X
  for each non-empty S' subset of N: emit S | S'
  for each non-empty S' subset of N: EnumerateCsgRec(S | S', X | N)

EnumerateCmp(S1):                       # complements for a given csg S1
  X = B_min(S1) | S1
  N = neighbours(S1) \ X
  for each v_i in N, by descending i:
    emit {v_i}
    EnumerateCsgRec({v_i}, X | (B_i & N))
```

For each csg S1 (in emission order) and each complement S2 from
EnumerateCmp(S1), build plans for S1|S2 from best[S1] and best[S2] in both
orientations (and every join method). The emission order guarantees both inputs
are complete before use. Neighbourhood computation is a few OR/AND-NOT
operations on precomputed per-relation neighbour masks.

**DPhyp** (Moerkotte & Neumann, SIGMOD 2008) generalizes DPccp to hypergraphs:
predicates spanning more than two relations (`a.x + b.y = c.z`) become
hyperedges, and reordering constraints of non-inner joins are encoded as
hyperedges too, so one enumerator handles outer, semi, anti and dependent joins.

> **Beyond EDBS:** DuckDB's join-order optimizer is DPhyp-based with a greedy
> fallback when the enumeration budget is exceeded; Neumann & Radke (SIGMOD
> 2018) give an adaptive scheme: exact DPhyp for small queries, linearized DP
> (fix an IKKBZ linear order, then run DP over contiguous subsequences, cubic
> time) for medium ones, and greedy plus iterative DP refinement for queries with
> hundreds or thousands of relations.

## 8. Top-down, memoized search (Volcano / Cascades)

- **Memo**: groups of logically equivalent expressions; each group carries
  logical properties (cardinality, schema, keys) computed once.
- **Rules**: transformation rules (logical -> logical, e.g. join commutativity
  and associativity) and implementation rules (logical -> physical).
- **Goal-driven**: optimize(group, required props, upper bound) recursively;
  enforcers satisfy properties; branch-and-bound prunes alternatives whose
  partial cost already exceeds the best known plan.
- Memoization makes top-down search equivalent in power to bottom-up DP (the
  MQO entry makes this point explicitly). The difference is engineering:
  extensibility and pruning versus duplicate generation. Naive application of
  commutativity plus associativity regenerates the same expression many times;
  rule-application flags (Pellenkoft et al., VLDB 1997) or graph-aware top-down
  partitioning (DeHaan & Tompa, SIGMOD 2007; Fender & Moerkotte, ICDE 2011)
  restore DPccp-like efficiency.
- Starburst sits between: bottom-up and constructive like System R, but
  rule-driven (grammar-like STARs over low-level operators, LOLEPOPs) over the
  Query Graph Model, and the ancestor of DB2's optimizer.

Constructive vs transformative (Neumann's framing): transformative optimizers
apply equivalences to whole expressions — easy to extend, hard to explore
efficiently, usually heuristic; constructive optimizers build larger plans from
optimal smaller ones — efficient, but complex equivalences are awkward, so they
add transformative rewrite passes before and after enumeration.

## 9. Beyond inner joins

- Inner joins reorder freely subject to predicate availability. Outer joins,
  aggregation and dependent subqueries do not.
- Crude approach: cut the query into freely reorderable blocks at each outer
  join and optimize each separately. Too restrictive: many outer-join
  reorderings are valid (e.g., `(A LOJ B) LOJ C = A LOJ (B LOJ C)` when the
  B-C predicate rejects NULLs on B).
- **Dependency/conflict sets**: for each non-inner operator compute the set of
  relations that must be present below it (EELS, Rao et al. ICDE 2001;
  Galindo-Legaria & Rosenthal, TODS 1997; the SES/TES conflict detectors of
  Moerkotte, Fender & Eich, SIGMOD 2013). The enumerator then only checks
  `TES(op) is subset of S1 | S2` with the correct side split before placing op.
- **Aggregation placement**: grouping can be pushed below a join when the join
  cannot change the groups (e.g., it behaves like a filter on the grouping key);
  more general eager/lazy aggregation needs compensation (re-aggregation, count
  multiplication). Usually done as a heuristic rewrite, sometimes costed
  (Yan & Larson, ICDE 1994 / VLDB 1995; Chaudhuri & Shim, VLDB 1994).
- Selections are placed greedily as low as possible and projections where a
  pipeline breaks; expensive predicates (UDFs) are the exception and need
  rank-based placement (cost per tuple vs selectivity).

## 10. Large queries

| Method | Idea | Guarantee |
|---|---|---|
| IKKBZ (Ibaraki & Kameda 1984; Krishnamurthy, Boral & Zaniolo VLDB 1986) | acyclic graph, ASI cost (e.g., C_out, NL): root the graph at each relation, order subtrees by rank (T-1)/C, merge chains | optimal left-deep without cross products, O(n^2) |
| GOO, greedy operator ordering (Fegaras 1998) | repeatedly join the pair with the smallest result | none; bushy; fast |
| Iterative DP (Kossmann & Stocker, TODS 2000) | DP to block size k, commit best k-block, collapse, repeat | quality vs time knob |
| Randomized: iterative improvement, simulated annealing, two-phase (Swami & Gupta SIGMOD 1988; Ioannidis & Kang SIGMOD 1990) | local moves (swap, 3-cycle, associativity) on complete plans | none; anytime |
| Genetic (PostgreSQL GEQO, used at >= 12 FROM items by default) | crossover of join sequences | none; seed-dependent |
| QuickPick (Waas & Pellenkoft 2000) | random edge picking, keep best | probabilistic |

Steinbrunn, Moerkotte & Kemper (VLDBJ 1997) compared these systematically;
combinations that seed randomized search with a good heuristic plan do best.
The cost function used in such studies is usually `C_out` (sum of intermediate
result cardinalities), which isolates join order from operator implementation.

Practical policy: exact bushy DP while the csg-cmp count is within budget
(compute it incrementally; it is cheap to count before building plans), else
linearized DP or greedy + local DP, logging which tier was used.

> **Beyond EDBS:** Leis et al. ("How good are query optimizers, really?",
> VLDB 2015) found that with realistic cardinality estimates exhaustive bushy
> DP produced clearly better plans than greedy or randomized heuristics, and
> that restricting to left-deep trees cost moderately; but all of that mattered
> less than cardinality errors. Invest in estimation first, then exact search.

## 11. Pitfalls

- Pruning per relation set while ignoring physical properties (loses
  merge-join chains and pre-partitioned plans in MPP engines).
- Cross-product ban with a disconnected query graph: no plan at all; connect
  components with synthetic cross-product edges, placed last.
- Enumerating both (S1, S2) and (S2, S1) as separate pairs and also trying both
  orientations inside: 2x work; harmless but wasteful. Missing a pair is fatal.
- Computing a join cell's cardinality from the specific (S1, S2) split with
  per-edge selectivities that are not order-independent (multiple predicates
  between the same pair, transitive equalities). Compute per cell.
- Hash-join build side chosen from an underestimated input: also an enumeration
  issue, since orientation is a plan choice.
- Bitset width: 64-relation limit silently overflowing in generated SQL (ORMs,
  BI tools emit 100+ table joins); fall back to the large-query tier.

Sources: System R (R*) Optimizer p.3866; Query Optimization (in Relational
Databases) p.3009; Query Optimization p.3008; Join Order p.2051; Multi-query
Optimization p.2425 (memo equivalence to DP); Cost Estimation p.647.
