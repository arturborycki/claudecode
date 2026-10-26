---
name: multidimensional-and-similarity-indexing
description: "Use when designing, implementing or reviewing multidimensional, spatial, temporal or similarity access methods and the operators on top of them: GiST/SP-GiST operator classes, R-tree/R*-tree/Hilbert R-tree, STR bulk loading, quadtrees, kd-trees, grid files, Z-order/Hilbert keys and data layout, spatial join, kNN and incremental NN, reverse NN, closest pairs, high-dimensional and metric indexing, MVBT/TSB-tree, TPR-tree, and vector ANN (HNSW, IVF-PQ, DiskANN/Vamana). Triggers on MBR, MINDIST, picksplit, penalty, consistent, plane sweep, PBSM, filter/refine, lower bound, VA-file, M-tree, triangle inequality, curse of dimensionality, Morton code, ZORDER BY, timeslice query, moving objects, recall@k, efSearch, nprobe, product quantization, filtered ANN, pgvector, Puffin. Apply even when phrased as 'make geo queries fast', 'nearest stores', 'similar items', 'AS OF query is slow' or 'add vector search to the engine'."
---

# Multidimensional and Similarity Indexing

This skill owns access methods whose keys have no useful total order —
points, boxes, intervals, trajectories, feature vectors, objects with only a
distance function — and the operators on them (window, kNN, join, closest
pair, reverse NN, timeslice, approximate top-k). The central idea: **every
one of these indexes is a conservative filter over cheap approximations
followed by exact refinement**, so correctness reduces to *covering* (a
parent key contains everything below it) and *lower bounding* (a distance
used to prune or order never exceeds the true distance). Everything else is
performance.

## Mental model

- **Approximate, then refine.** MBRs, z-cells, spheres, pivot distances,
  reduced dimensions and quantised codes are approximations; conservative
  ones give true drops, progressive ones true hits, refinement decides the
  rest. The index is only the first filter of a multi-step pipeline.
- **Data-driven vs space-driven.** R-, SS-, M-trees adapt overlapping
  regions to data; grid file, quadtree, kd-tree and space-filling curves cut
  the domain into disjoint cells and map onto 1-D structures (B+-tree, LSM,
  sorted files) whose concurrency, WAL and compression you already have.
- **Search is branch-and-bound.** Range prunes by intersection; kNN is a
  best-first queue keyed by a lower bound (an incremental ordered iterator);
  joins are synchronized traversals or partitioning with duplicate control.
- **Dimensionality changes the game.** Trees win below ~8 *intrinsic*
  dimensions; beyond ~10–15 distances concentrate and optimised scans
  (VA-file, SIMD brute force) or approximate methods (graphs, IVF-PQ) win.
- **Time is special.** Transaction time only grows and only the current
  state changes (persistence: MVBT); valid time is interval management
  (RI-tree); moving objects are functions of time (TPR-tree, Bx-tree).
- **Approximate indexes change semantics.** ANN results depend on the plan;
  the engine must expose that and never substitute it for exact evaluation.

## Core invariants

1. **Covering**: `Consistent(entry, q) == false` ⇒ no tuple below satisfies
   q. Test: index scan == sequential scan on random and boundary-heavy queries.
2. **Outward keys**: stored bounds may be looser than exact (round min down,
   max up), never tighter. MINMAXDIST-style upper bounds require *tight* MBRs.
3. **Lower bounding + consistency**: every pruning/priority distance satisfies
   `LB(q, node) ≤ dist(q, o)` for all o below, and child key ≥ parent key, so
   best-first output is in non-decreasing distance.
4. **Contractive reduction**: an embedding used for exact search satisfies
   `d'(F(x),F(y)) ≤ d(x,y)` — no false dismissals.
5. **Metric pruning only with a metric**: triangle-inequality pruning only
   for true metrics (L2 yes; squared L2, cosine similarity, DTW no).
6. **Balance and fill**: non-root nodes hold m..M entries (R-family, M-tree,
   MVBT pages), equal leaf depth; space-driven structures cap depth.
7. **Exactly-once output**: replicating methods (R+-tree, PBSM, SETI,
   z-cell and cell-id joins) report each result once — multiset equality
   with a brute-force join.
8. **Multi-step stopping**: kNN with refinement stops only when the next
   candidate's lower bound ≥ the current k-th exact distance.
9. **Persistence**: transaction-time indexes never mutate past versions; any
   timeslice equals log replay to that time; MVBT pages satisfy the weak
   version condition over their lifespan.
10. **Time-parameterised containment**: a TPR-tree box contains all children
    for every t in [t_ref, t_ref + horizon].
11. **ANN honesty**: approximate indexes are used only under an explicit
    approximate contract, and never return rows invisible/deleted at the
    query snapshot.

## Design space & trade-offs

| Option | When it wins | Cost / risk |
|---|---|---|
| R*-tree (dynamic) | 2–8 d, extended objects, mixed updates | insert CPU (overlap tests, forced reinsert) |
| STR / Hilbert packed R-tree | static or batch-loaded, read-mostly | decays with later inserts; adversarial data → PR-tree |
| Hilbert R-tree | dynamic, small square-ish objects, high fill | elongated/large objects cluster badly |
| R+-tree / clipping | point location, small objects | replication, dedup, downward split cascades |
| Quadtree / kd-tree (SP-GiST) | in-memory points | unbalanced depth on clustered data |
| SFC key on B+-tree/LSM (Z, Hilbert, UB-tree, linear quadtree) | reuse 1-D machinery | range = many intervals + post-filter; locality falls with d |
| Z-order/Hilbert data layout | file/row-group skipping on 2–4 columns | recluster = rewrite; weak beyond ~4 columns |
| Grid file | uniform, uncorrelated, low d, exact match | directory blow-up on correlated data |
| VA-file / quantised scan | high d, exact, uniform-ish | full pass over approximations per query |
| Reduction + low-d index + refine | correlated data (PCA/CSVD) | SVD maintenance under updates |
| M-tree / pivot table | arbitrary metric, expensive distance | weak on concentrated distance distributions |
| MVBT / TSB-tree | key-range AS OF over long histories | complex splits; TSB duplicates live records |
| Overlapping (path-copy) trees | simple versioning, timeslices | O(n log n) space, poor time-range queries |
| RI-tree | interval stabbing with plain B+-trees in SQL | backbone-height factor |
| TPR / TPR*-tree | predictive queries on moving points | needs frequent updates to stay tight |
| Bx-tree | very high update rates | query enlargement by v_max |
| HNSW | in-RAM ANN, best recall/QPS | memory, deletes, build cost |
| Vamana/DiskANN | billion-scale on SSD/object store | build complexity; filters need variants |
| IVF-PQ | memory-bound, partitionable, distributed routing | recall ceiling without re-rank; retrain on drift |

## Algorithms that matter

- **GiST insert/search**: ChooseSubtree by min `Penalty`; overflow →
  `PickSplit`; propagate `Union` up until unchanged. Search descends every
  child with `Consistent` true.
- **R*-tree split**: axis with minimum Σ margins over all distributions,
  then min overlap, then min area; forced reinsert of ~30% farthest entries
  on first overflow per level. O(d·M log M).
- **STR bulk load**: P = ⌈n/b⌉ leaves, S = ⌈P^{1/d}⌉ slabs per axis; sort,
  slice, recurse; O(n log n).
- **Best-first kNN** (Hjaltason & Samet): heap of nodes/objects by
  MINDIST/exact distance; visits exactly the nodes meeting the k-NN ball;
  incremental; memory must be bounded. Depth-first: O(height) memory, more I/O.
- **Multi-step kNN** (Seidl & Kriegel): consume ranking by lower bound;
  refine until next LB ≥ k-th exact — optimal refinements.
- **Spatial join**: R-tree join = synchronized traversal with search-space
  restriction + plane sweep; PBSM = hashed grid tiles, replicate, sweep per
  partition, reference-point dedup; pick by index availability.
- **Z-order range**: ≤ K curve intervals or BIGMIN skip-scan; post-filter.
- **VA-file kNN**: scan approximations for [lb, ub]; keep lb ≤ k-th ub;
  refine in lb order until lb ≥ k-th exact.
- **M-tree**: skip entry if `|d(q,O_p) − d(O_r,O_p)| > r + r(O_r)` without
  computing a new distance.
- **MVBT**: version split copies alive entries, then key split or merge to
  meet the strong version condition; range-timeslice O(log_B n + s/B).
- **Vamana RobustPrune**: keep closest p*, drop v with α·d(p*,v) ≤ d(p,v),
  cap degree R; α > 1 keeps long edges → fewer hops.

## Failure modes & classic bugs

- Float boxes rounded inward on compression → edge rows vanish (test with
  boundary-aligned fixtures vs seq scan).
- Lossy keys without recheck (false positives); lossy distances without a
  reorder queue (wrong kNN order); MINMAXDIST on loose keys (missed NNs).
- AdjustTree skipped on an early-exit path → parent no longer covers child.
- Forced reinsert under held latches or re-triggered at the same level;
  PickSplit returning an empty group on identical keys.
- Replicating joins without dedup (duplicates) or with an uncosted sort.
- Unbounded best-first heap on large k or adversarial data → OOM.
- Z-ordering unnormalised columns → one column dominates the clustering.
- Triangle pruning on cosine similarity or squared L2 → silent misses.
- TPR velocity bounds without outward rounding → objects escape boxes later.
- ANN: post-filter underflow (< k rows under selective WHERE), MVCC-invisible
  entries consuming the budget, appended-but-unindexed files never searched,
  QPS quoted without recall or recall measured with a different metric.

## Implementation checklist (C/C++/Rust)

- Key-class trait: `consistent`, `union`, `penalty`, `pick_split`,
  `distance_lower_bound`, `recheck_needed`; R*-style defaults.
- MBRs as contiguous `[min..., max...]` per node (SoA) for SIMD intersection
  and MINDIST; squared distances internally; fixed-size entries for fixed d.
- Concurrency: right-links + NSN/LSN check (GiST, R-link tree); no latches
  across forced reinsert; predicate/page locks for phantoms.
- WAL multi-page splits atomically or flag incomplete splits for completion.
- Bounded priority queues with spill; process join node pairs in sweep order.
- Separate bulk-load path (STR/Hilbert sort, sorted GiST build), fill factor.
- SFC codecs: branch-free bit spreading/PDEP, order-preserving float→int,
  versioned domain scaling recorded in metadata.
- Temporal: symbolic UC/now; root* directory; reachability asserts before
  writing pages shared by older versions.
- Vectors: aligned storage, fp32/fp16/int8 kernels, per-query PQ tables in
  L1, per-node adjacency locks, tombstones + background consolidation.
- Rust: node arena indexed by `u32`, `const D: usize` geometry, explicit
  stacks/heaps instead of recursion.

## How to test it

- **Oracle**: brute force on every query in property tests (≤ ~10⁵ rows).
- **Validator** after each mutation (debug): covering, tightness, fill,
  leaf depth, object placement, MVBT version conditions.
- **Adversarial data**: duplicates, collinear points, zero-width and
  domain-spanning boxes, points on cell boundaries, NaN/inverted boxes,
  mixed long/short intervals, clustered + uniform mixes.
- **Metamorphic**: kNN(k) prefix of kNN(k+1) with fixed ties; incremental
  distances non-decreasing; join(R,S) = swap(join(S,R)); distributed join =
  local join as multisets; bulk-loaded vs insert-built trees agree.
- **Efficiency**: assert node-access and refinement counts against
  best-first/optimal multi-step on fixtures — lost pruning is invisible in
  result tests.
- **Temporal**: random change streams; timeslices at split times vs replay.
- **ANN**: recall@k thresholds vs stored ground truth over parameter sweeps,
  tail recall, filter selectivities 1…0.001, deletes + reachability check,
  appended-but-unindexed rows still returned.

## Expert review questions

1. What exactly does `Consistent` guarantee, and which test proves no false
   negatives on boundary data after float compression?
2. Is every pruning distance a lower bound; is MINMAXDIST used on loose keys?
3. Why this split heuristic and fill factor — measured overlap per level
   and utilisation after a realistic insert/delete mix?
4. What is the intrinsic dimensionality, and how does the index compare with
   a parallel SIMD brute-force scan?
5. Is the plan alternative for a non-indexed join input (after a selection)
   costed?
6. Where can duplicates arise, and how are they removed without a blocking sort?
7. What bounds the best-first queue's memory, and what happens at the bound?
8. For SFC keys: intervals per query, post-filter cost, column normalisation?
9. Is the distance a metric wherever triangle pruning is applied?
10. Cost of a key-range AS OF query at history depth n; space under
    scattered updates?
11. What update rate keeps TPR boxes useful; how is v_max enforced?
12. ANN: what recall at what latency on which query distribution; effect of
    selective filters, deletes and MVCC visibility on returned rows?
13. How does an ANN index track snapshots, deletes, appended files and time
    travel; can EXPLAIN show approximation and can users force exact?

## Go deeper

- `references/gist-and-rtree-family.md` — GiST contract, concurrency/WAL,
  Guttman/R*/R+/Hilbert R-trees, STR and bulk loads, bug table.
- `references/space-filling-curves-and-grids.md` — Z/Hilbert curves, range
  decomposition/BIGMIN, lakehouse clustering, grid file, kd/K-D-B/hB/LSD,
  quadtrees, Pyramid/iDistance embeddings.
- `references/spatial-join-and-nn-search.md` — multi-step kNN, spatial join
  algorithms and dedup, MINDIST/MINMAXDIST, DF/BF/incremental kNN, closest
  pairs, reverse NN, Voronoi, uncertain data.
- `references/high-dimensional-and-metric-indexing.md` — curse of
  dimensionality, VA-file/IQ-tree, X/SS/SR/TV-trees, lower-bounding
  reduction and CSVD, metric postulates, VP/M-tree, pivot tables.
- `references/temporal-and-moving-object-indexes.md` — MVBT, TSB-tree,
  overlapping B-trees, RI-tree, bitemporal designs, trajectories, TPR/Bx-trees.
- `references/vector-ann-indexes-beyond-edbs.md` — LSH, IVF, PQ/SQ/binary,
  HNSW, Vamana/DiskANN/FreshDiskANN, filtered ANN, ANN as a SQL access
  method, ANN in Iceberg/Puffin-style lakehouse formats.
- `references/edbs-entries.md` — all 26 source entries with pages.

## Related skills

- `storage-and-indexing` (B+-tree, hash, bitmap, buffer pool) and
  `page-and-file-format` (node page layout) — the substrate used here.
- `index-structures-catalog` — 1-D/general index catalogue; this skill owns
  multi-D, temporal and similarity methods.
- `temporal-databases` — temporal model and SQL semantics; access methods here.
- `join-algorithms`, `query-execution-advanced` — general operators; spatial,
  distance and kNN operators live here.
- `cardinality-and-statistics`, `query-optimizer` — spatial selectivity,
  index-vs-scan costing, ANN pre/post-filter choice.
- `concurrency-control-theory`, `recovery-and-durability` — predicate locks,
  B-link protocols, WAL for multi-page splits.
- `parallel-database-systems`, `distributed-dbms-design` — spatial
  partitioning, declustering, distributed kNN/ANN fan-out.
- `olap-and-warehouse-engines`, `columnar-arrow-layout` — Z/Hilbert
  clustering for zone-map skipping; `stream-processing-engines` — continuous
  kNN/RNN; `beyond-relational-engines` — vector/GIS engines as systems;
  `tuning-and-benchmarking` — recall/QPS methodology; `edbs-reference` —
  full entries.

## Grounding

EDBS entries (printed page): Bitemporal Indexing 304; Closest-Pair Query
469; Curse of Dimensionality 717; Dimensionality Reduction Techniques for
Nearest-Neighbor Computations 1108; Generalized Search Tree 1581; Grid File
(and Family) 1671; High-Dimensional Indexing 1706; Indexing and Similarity
Search 1857; Indexing Historical Spatiotemporal Data 1868; Indexing Metric
Spaces 1876; Indexing of the Current and Near-Future Positions of Moving
Objects 1884; Indexing Uncertain Data 1900; Metric Space 2253; Multi step
Query Processing 2435; Nearest Neighbor Query 2478; Quadtrees (and Family)
2946; Range Query 3079; Reverse Nearest Neighbor Query 3234; R-Tree (and
Family) 3258; Space-Filling Curves 3547; Space-Filling Curves for Query
Processing 3548; Spatial Indexing Techniques 3592; Spatial Join 3598;
Transaction-Time Indexing 4211; Valid-Time Indexing 4360; Voronoi Diagrams 4580.

Seminal work (full citations in the references): Guttman 1984; R* 1990;
GiST 1995/1997; STR 1997; PBSM 1996; Hjaltason & Samet 1999; Seidl & Kriegel
1998; VA-file 1998; M-tree 1997; MVBT 1996; TPR 2000; PQ 2011; HNSW 2020;
DiskANN 2019. Systems: PostgreSQL GiST/SP-GiST, PostGIS, pgvector, Lucene, Iceberg.
