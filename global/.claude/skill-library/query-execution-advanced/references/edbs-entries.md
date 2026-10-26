# EDBS entries behind `query-execution-advanced`

All 31 entries of the source bundle. Pull the full text with the
`edbs-reference` skill: `python3 <edbs-reference>/scripts/edbs.py show "<Entry>"`.
Printed page = page number printed in the book (2nd ed., 2018).

| Entry | Printed page | What it gives an engine builder |
|---|---|---|
| Access Path | p.22 | Definition of access path (heap scan vs matching index scan); "matching index" notion; choosing the path that touches the fewest index+data pages; Selinger 1979 as the root reference |
| Adaptive Query Processing | p.61 | Taxonomy of adaptivity (horizontal partitioning, tuple routing, plan partitioning, runtime binding, in-operator logic); symmetric hash join and moments of symmetry; eddies; survey pointers |
| Approximate Query Processing | p.139 | Relative-error metric; precomputed synopses vs online processing; sampling families (uniform, biased, icicles, outlier indexing, congressional, stratified); join-of-samples pitfall; histograms (continuous vs uniform spread), wavelets; AQUA and online aggregation pointers |
| Cache-Conscious Query Processing | p.389 | Catalogue of hardware-conscious strategies: spatial/temporal locality, blocking, buffering, partitioning (radix join), prefetching, avoiding pollution and TLB thrash, sampling to pick algorithms, cache-oblivious/adaptive algorithms, shared-cache interference |
| Evaluation of Relational Operators | p.1348 | Open/next/close demand-pull execution; selection by scan, clustered and secondary index, index-only; projection; nested loops (block, index), sort-merge (with run-merge fusion and index merge), Grace and hybrid hash join; scalar, sort- and hash-based aggregation; aggregation over covering indexes |
| Hash Join | p.1682 | Build/probe; Grace partitioning with recursive repartitioning on skew; hybrid hash keeping the first partition resident (overlaps `join-algorithms`) |
| Index Join | p.1845 | Index nested-loop join applicability (join column must lead the index), lookup for equality and seek-then-scan for ranges (entry text truncated in extraction) |
| Iterator | p.2042 | Uniform open/next/close interface; plans as dataflow graphs; iterators also wrap access methods; exchange iterators encapsulate parallelism and networking |
| Membership Query | p.2222 | Equality selection as a degenerate range; hash vs B+-tree implementation |
| Multi-step Query Processing | p.2435 | Filter/refine paradigm; conservative (lower-bounding) vs progressive (upper-bounding) approximations; true hits/drops; multi-step range and optimal multi-step kNN; applications in time series, road networks, point-in-polygon |
| Nested Loop Join | p.2485 | Tuple and block nested loops with B−2 outer buffer pages; handles arbitrary predicates (overlaps `join-algorithms`) |
| One-Pass Algorithm | p.2556 | Streaming-algorithm model: single left-to-right pass, sublinear memory and per-item time; lower bounds via communication complexity; randomized sketches/sampling; multi-pass trade-offs; use for maintaining optimizer statistics |
| Pipeline | p.2767 | General pipeline performance model: latency vs occupancy, balanced vs unbalanced stages, per-stage overhead limiting useful depth |
| Pipelining | p.2768 | Materialization vs pipelining; demand-driven (pull) vs producer-driven (push) pipelines; why merge join with unsorted inputs cannot pipeline |
| Preference Queries | p.2784 | Winnow/BMO operator and its algebraic laws (conditional commutation with selection), semantic optimization with constraints, BNL/SFS applicability to strict partial orders, Preference SQL, PrefDB, regret-minimizing sets |
| Query Plan | p.3020 | Plan as operator tree (or DAG with common subexpressions); left-deep, right-deep, bushy shapes |
| Query Processing | p.3026 | Phases: parse/validate/authorize, rewrite, optimize, code generation, iterator-based execution |
| Query Processing (in Relational Databases) | p.3027 | History and architecture of query compilation; System R bottom-up DP vs Volcano/Cascades top-down; interesting orders; estimation assumptions (currency, uniformity, independence, inclusion) and their failure modes; interpreted vs generated execution; feedback loops |
| Query Processing and Optimization in Object Relational Databases | p.3032 | Four-phase processing; constraint-based rewrite (EXISTS to join only if inner returns at most one row); optimizer as search strategy + cost functions + plan generation; OR features (objects, path expressions, inheritance, methods) that complicate optimization; call for intertwined optimize/execute |
| Range Query | p.3079 | One-dimensional ranges via B+-tree leaf scans; multidimensional ranges via R-trees |
| Rank-Aware Query Processing | p.3080 | Making the engine rank-aware: rank-relational algebra (rank operator, upper-bound scoring of partially evaluated tuples, splitting and interleaving laws), RankSQL optimizer, pipelined rank-join operators |
| Rank-Join | p.3093 | J* (A*-based), HRJN with corner-bound threshold, HRJN* adaptive pulling, PBRJ template, sumDepths cost metric and instance optimality |
| Rank-Join Indices | p.3096 | Precomputed index for top-k joins under query-time linear scoring: dominating set D_K, separating vectors, angular sweep into a B-tree, construction/space/query bounds |
| Score Aggregation | p.3324 | Monotone aggregation functions over per-attribute grades (min, averages); TA as the optimally efficient algorithm under sorted/random access |
| Semijoin | p.3436 | Semijoin definition and reducer equivalences; distributed semijoin program and transfer-cost criterion; bit-vector (Bloom) join with multiple hash functions; heterogeneous sources; star-join RID intersection; R* experimental results |
| Similarity and Ranking Operations | p.3495 | IR similarity measures (Jaccard, cosine, Dice, overlap, binary and weighted) and probabilistic relevance ranking — the score sources that top-k operators combine |
| Skyline Queries and Pareto Optimality | p.3508 | Dominance and skyline definitions; BNL, divide and conquer, SFS (progressive), bitmap/index/NN, BBS (progressive, I/O-optimal); categorical dimensions; k-representative skylines |
| Sort-Merge Join | p.3546 | Sort and merge phases with duplicate-group handling; merging runs of both inputs during the join (overlaps `join-algorithms`) |
| Stop-&-Go Operator | p.3720 | Non-pipelineable operators (sort, hash join build, sort-merge sort phase) cap operator-level parallelism; optimizers may trade them for costlier pipelineable operators |
| Top-k Queries | p.4168 | Formal top-k definition; top-k join and top-k aggregate SQL templates (entry body truncated in the bundle) |
| Window Operator in RDBMS | p.4693 | Window function semantics (partition, order, frame, function); Oracle's sort sharing, rank-predicate pushdown and parallelization; segment trees (Leis et al.); multi-window optimization (Cao et al.); window functions for subquery elimination |

## Weak or largely duplicated entries

- Hash Join, Nested Loop Join, Sort-Merge Join, Index Join: restate the join
  catalogue already in `join-algorithms`; used here only for execution-level
  details (recursive repartitioning, run-merge fusion, index merge).
- Membership Query, Range Query, Query Plan, Query Processing: short
  definitional entries.
- Top-k Queries and Index Join: truncated in the PDF extraction of the bundle;
  the algorithms come from Score Aggregation, Rank-Join and Rank-Aware Query
  Processing instead. The recovered-tail supplement did not restore Index
  Join's remaining text (its "tail" is the neighbouring entry Index Structures
  for Biological Sequences); likewise the Query Plan and Membership Query
  tails are neighbouring entries (Query Point Movement Techniques for CBIR;
  Memory Hierarchy), and the Query Processing / Query Processing (in
  Relational Databases) tails repeat text already in the bundle (System R vs
  Volcano search, EXISTS-to-join rewrite condition). Only the Memory Hierarchy
  text added a caveat (hardware-managed caches, see
  `sort-aggregate-setops.md` section 7).
- Similarity and Ranking Operations: information-retrieval focused; used only
  as the source of monotone scoring functions.
- Query Processing (in Relational Databases): mostly optimizer and
  cardinality-estimation material, owned by `query-optimizer` and
  `cardinality-and-statistics`.
- Pipeline: generic (hardware) pipeline theory; used for the throughput
  model only.

Related entries outside this bundle worth pulling: "Top-K Selection Queries
on Multimedia Datasets" (TA/NRA/Upper/MPro detail), "Adaptive Stream
Processing", "Data Sketch/Synopsis", "Histogram", "Parallel Query Execution
Algorithms", "Window-Based Query Processing" (stream windows).
