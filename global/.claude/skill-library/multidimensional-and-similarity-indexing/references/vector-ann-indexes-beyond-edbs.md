# Vector ANN indexes (Beyond EDBS)

Read this when designing, implementing or reviewing approximate
nearest-neighbour (ANN) search over dense embeddings: HNSW, IVF/IVF-PQ,
product quantisation, DiskANN/Vamana, filtered ANN, recall/latency tuning,
an ANN index access method inside a SQL engine, or ANN indexes stored in a
lakehouse table format. None of this material is in EDBS (2018); everything
here is flagged **Beyond EDBS**. EDBS supplies the foundations it rests on:
curse of dimensionality, multi-step filter/refine, quantised scans (VA-file,
IQ-tree), clustering + branch-and-bound (CSVD), Voronoi/Delaunay structure.

---

## 1. Problem statement and why approximation

- Data: n vectors in R^d (d typically 64–4096), often n = 10⁶–10¹⁰.
- Distances: L2; inner product (maximum inner product search, MIPS); cosine
  (normalise at ingest → cosine ranking = IP ranking = L2 ranking). IP is
  not a metric; MIPS can be reduced to L2 NN by appending one coordinate
  `sqrt(Φ² − ‖x‖²)` with Φ = max norm (Bachrach et al., RecSys 2014).
- Exact kNN at this d is essentially a scan (high-dim file §1). ANN trades a
  bounded loss of **recall** for orders-of-magnitude speedups by exploiting
  low intrinsic dimension and by never computing most distances exactly.
- **recall@k** = |returned_k ∩ true_kNN_k| / k, averaged over queries; also
  report tail (p5/p1 recall), because averages hide queries that fail
  completely (common with filters or out-of-distribution queries).
- Throughput/latency are always quoted *at a recall target*; one number
  without a recall is meaningless. Compare methods by Pareto curves (QPS vs
  recall@k) — the methodology of ann-benchmarks (Aumüller, Bernhardsson,
  Faithfull, Information Systems 2020) and the NeurIPS'21 big-ann-benchmarks
  competition.

Four families: hashing (LSH), space partitioning / clustering (IVF),
compression (PQ, SQ, binary), proximity graphs (NSW/HNSW, NSG, Vamana).
Production systems combine them: IVF + PQ, graph + PQ, graph over IVF
centroids.

---

## 2. Locality-sensitive hashing (brief)

Indyk & Motwani (STOC 1998); E2LSH with p-stable projections (Datar,
Immorlica, Indyk, Mirrokni, SoCG 2004). L hash tables of K concatenated
hashes; collisions are candidates; refine exactly. Sub-linear query time
with provable guarantees for (c, r)-near neighbour, but in practice needs
many tables (memory) and loses to graphs and IVF-PQ at equal recall on real
embeddings. Still useful for streaming dedup and for sets (MinHash for
Jaccard).

---

## 3. IVF: clustering-based partitioning

- Train a **coarse quantiser** (k-means, `nlist` centroids) on a sample.
- Assign each vector to its nearest centroid; store per-centroid **inverted
  lists** (posting lists) of (id, payload).
- Query: find the `nprobe` nearest centroids, scan their lists, keep top-k.
- This is CSVD's cluster-level branch-and-bound with the exact stopping test
  replaced by a fixed probe count — vectors near Voronoi cell boundaries are
  the ones missed. Recall rises monotonically with nprobe; cost ≈ nprobe ·
  n / nlist distance computations + centroid search.
- Rules of thumb: nlist on the order of √n to a few·√n; train on ≥ 30–100
  points per centroid; balanced lists matter more than optimal k-means
  objective (skewed lists inflate tail latency).
- Variants: multiple assignment of boundary vectors to several lists
  (SPANN, Chen et al., NeurIPS 2021: centroids in memory, posting lists on
  SSD, boundary vectors duplicated); a graph index over the centroids when
  nlist is large.
- Strengths for engines: lists are append-friendly, map naturally onto
  partitions/files/segments, cheap to rebuild incrementally, and give a
  routing table for distributed search.

---

## 4. Quantisation

### Product quantisation (Jégou, Douze, Schmid, TPAMI 2011)

- Split x ∈ R^d into m sub-vectors of d/m dims; for each subspace train a
  codebook of k* centroids (usually 256 → 1 byte); code = m bytes.
- **ADC** (asymmetric distance computation): per query build m × k* tables
  `T[j][c] = ‖q_j − C_j[c]‖²`; distance to a code = Σ_j T[j][code_j] —
  m lookups + adds, no decompression. SDC (both quantised) is less accurate.
- **IVFADC / IVF-PQ**: quantise the **residual** x − c(x) w.r.t. the coarse
  centroid; per probed list rebuild tables for q − c_i (or use the
  decomposition trick to share terms).
- Accuracy knobs: m (bytes per vector), k*, training sample, **OPQ** (Ge
  et al., CVPR 2013: learned rotation before PQ balances variance across
  subspaces), anisotropic loss (ScaNN; Guo et al., ICML 2020, weights error
  parallel to x more for MIPS).
- **Fast-scan PQ**: 4-bit sub-quantisers so tables fit in SIMD registers and
  lookups become shuffles (André, Kermarrec, Le Scouarnec, PVLDB 2015) —
  large constant-factor gains on CPUs.
- PQ distances are **not lower bounds** of true distances. A re-ranking pass
  with full-precision vectors on the top k' = (2–10)·k candidates restores
  most recall, but unlike GEMINI there is no no-false-dismissal guarantee.

### Scalar and binary quantisation

- SQ8 / fp16 / bf16: per-dimension affine quantisation; 2–4× compression,
  small recall loss, trivially SIMD.
- Binary (1 bit/dim, Hamming via popcount): 32× compression; recall loss
  large for low d, acceptable for d ≥ ~512 with re-ranking. RaBitQ (Gao &
  Long, SIGMOD 2024) gives randomised binary codes with a theoretical error
  bound on the estimated distance, enabling principled re-rank cut-offs.
- Pattern: quantised vectors in RAM drive search; full-precision vectors on
  disk/object store used only for re-ranking — DiskANN, IVF-PQ+refine and
  pgvector's binary-quantise-then-rerank recipe all follow it.

---

## 5. Proximity-graph indexes

### Why graphs work

Greedy routing on the Delaunay graph (dual of the Voronoi diagram, EDBS
*Voronoi Diagrams*) always reaches the exact NN, but the Delaunay graph of
high-d data is nearly complete. Graph ANN indexes keep a sparse subgraph
that still makes greedy/beam search succeed with high probability, with
some long edges to shorten paths (navigability). The key pruning rule is the
**relative-neighbourhood-graph (RNG) rule**: drop edge (p, p') if some
already-kept neighbour p* is closer to p' than p is — the occluded
direction is reachable via p*.

### Beam (best-first) search on a graph

```
GreedySearch(entry s, query q, beam L):
  cand = {s}  (min-heap by distance, capped at L);  visited = ∅
  while exists unvisited p in cand:
    p* = closest unvisited in cand; visited += p*
    for nb in N_out(p*): if nb not seen: cand.insert(nb, d(q, nb))
    truncate cand to L closest
  return k closest of cand, visited
```
It is best-first NN search (spatial-join-and-nn file §3) on a graph instead
of a tree, with a bounded queue — the bound L (ef, search_list) is what makes
it approximate. Larger L → higher recall, linearly more distance computations.

### HNSW (Malkov & Yashunin, TPAMI 2020; arXiv 2016)

- Multi-layer graph: each node gets a top level
  `l = floor(−ln(U(0,1)) · mL)`, mL = 1/ln(M) — exponentially fewer nodes per
  layer, like a skip list; layer 0 contains all nodes.
- Parameters: **M** (max neighbours per node on upper layers; 2M on layer
  0), **efConstruction** (beam during build), **efSearch** (beam at query).
- Insert: greedy descent with beam 1 from the global entry point to layer
  l+1; for each layer ≤ l run beam search with efConstruction, choose
  neighbours with the **heuristic** (RNG-style diversity: accept candidate e
  only if it is closer to the new node than to every neighbour already
  accepted), add bidirectional edges, and re-prune neighbours that exceed
  their degree cap.
- Query: greedy descent through upper layers, beam search with efSearch on
  layer 0, return top k.
- Properties: excellent recall/QPS in RAM; memory = vectors +
  ~(2M)·4 bytes of ids per node on layer 0 plus upper layers; build cost
  high (each insert is a search); **deletes are hard** — practice is
  tombstones plus repair or periodic rebuild; incremental inserts are
  natural; concurrency via per-node locks on adjacency lists.

### NSG and Vamana

- **NSG** (Fu, Xiang, Wang, Cai, PVLDB 2019): approximates a monotonic RNG
  from a kNN-graph, single navigating node, spanning-tree repair for
  connectivity.
- **Vamana / DiskANN** (Subramanya, Devvrit, Kadekodi, Krishnaswamy,
  Simhadri, NeurIPS 2019): flat (single-layer) graph with degree bound R,
  built for SSD-resident search.

**RobustPrune(p, V, α, R)** — the core of Vamana:
```
V = (V ∪ N_out(p)) \ {p};  N_out(p) = ∅
while V ≠ ∅:
  p* = argmin_{v∈V} d(p, v)
  N_out(p) += p*;  if |N_out(p)| == R: break
  for v in V: if α · d(p*, v) ≤ d(p, v): V -= v     # v is "covered" by p*
```
α = 1 is the RNG rule; **α > 1 (e.g. 1.2)** prunes less aggressively,
keeping longer edges so each greedy step makes geometric progress toward the
query (fewer hops — crucial when every hop is an SSD read).

**Vamana build**
```
start from a random R-regular directed graph; s = medoid
for pass in (α=1, α=user value):
  for p in random permutation:
    (_, visited) = GreedySearch(s, x_p, L)
    RobustPrune(p, visited, α, R)
    for j in N_out(p):                       # add back-edges
      if |N_out(j) ∪ {p}| > R: RobustPrune(j, N_out(j) ∪ {p}, α, R)
      else: N_out(j) += p
```
**Billion-scale build in limited RAM**: k-means into k shards, assign each
point to its ℓ (=2) nearest shard centroids, build Vamana per shard in
memory, merge by taking the union of edges (overlap via ℓ keeps the merged
graph navigable).

**DiskANN on-SSD layout and search**
- On SSD, per node, one fixed-size, sector-aligned record: full-precision
  vector + up to R neighbour ids. In RAM: PQ codes of all vectors (and
  optionally a cache of nodes within a few hops of the medoid).
- **Beam search with width W**: each round, issue W parallel reads for the
  W closest unvisited candidates (by PQ distance); one round trip fetches
  both adjacency lists and full vectors.
- **Implicit re-ranking**: full-precision vectors arrive with the adjacency
  reads, so exact distances for visited nodes are free; final top-k is
  ranked by exact distance.
- Cost model: latency ≈ hops × SSD round trip; α and R reduce hops, W trades
  IOPS for rounds, PQ size trades RAM for routing accuracy.

**Updates (FreshDiskANN; Singh, Subramanya, Krishnaswamy, Simhadri, 2021)**
- Inserts go to an in-memory Vamana index (search both, merge results).
- Deletes are added to a tombstone set (filtered from results); a
  consolidation pass rewires each node that points to deleted nodes:
  candidates = its live neighbours ∪ the out-neighbours of its deleted
  neighbours, then RobustPrune.
- A background **streaming merge** folds the in-memory index and deletes
  into the SSD index without a full rebuild.

### Graph vs IVF-PQ summary

| | HNSW | Vamana/DiskANN | IVF-PQ |
|---|---|---|---|
| Memory | vectors + graph in RAM | PQ codes in RAM, rest on SSD | codes + ids in RAM (or lists on disk) |
| Recall at low latency | best in RAM | best on SSD | good with refine, needs large nprobe for >95% |
| Build | slow (search per insert) | slow-ish, 2 passes; shardable | fast (k-means + assign), easily parallel |
| Inserts | incremental | in-memory delta + merge | append to lists (drift → retrain) |
| Deletes | tombstone + repair | tombstone + consolidation | remove from list — easy |
| Distribution | per-shard graphs, fan-out all | per-shard graphs | centroid routing → partition pruning |
| Filters | degrades at low selectivity | Filtered-DiskANN variants | natural with per-list bitmaps |

---

## 6. Filtered ANN (vector + predicate)

`ORDER BY dist(v, q) LIMIT k WHERE <predicate>` is the dominant real query.
Strategies:

| Strategy | How | Fails when |
|---|---|---|
| Pre-filter + brute force | evaluate predicate (bitmap / B-tree), exact distances on survivors | survivors too many (selectivity s high) |
| Post-filter | ANN top k' (k' ≈ k/s), then apply predicate | s small → k' explodes or underflow returns < k rows |
| In-filter traversal | beam search visits all nodes but only qualifying ones enter the result | low s: graph restricted to qualifying nodes disconnects; search wanders |
| Iterative / resumable scan | keep pulling from the ANN iterator until k qualifying rows or a budget | budget exhaustion; ordering only approximate |
| Filter-aware index | partition by filter value; Filtered-DiskANN (Gollapudi et al., WWW 2023: label-aware start points and a prune rule that preserves edges needed for shared labels; FilteredVamana and StitchedVamana); ACORN (Patel et al., SIGMOD 2024: denser predicate-agnostic HNSW, search expands two-hop neighbourhoods of failing nodes) | arbitrary predicates (filter-aware graphs target label equality) |

Engine rule: **cost-based switching on estimated selectivity** — brute
force below a threshold of qualifying rows, ANN with in-filter or iterative
scan above it. Lucene's kNN query falls back to exact search when the filter
is restrictive; pgvector ≥ 0.8 offers iterative index scans
(`hnsw.iterative_scan`, `ivfflat.iterative_scan`) to fix post-filter
underflow. Selectivity estimation for the predicate (cardinality skill)
therefore directly controls ANN recall and latency.

---

## 7. ANN inside a SQL engine (index access method design)

### Semantics

- An ANN index changes results: the same SQL can return different rows
  depending on the plan. Make this explicit — a distinct operator
  ("approximate top-k"), session knobs (ef, nprobe, recall target), EXPLAIN
  output naming the ANN index and its parameters, and the ability to force
  exact evaluation. Oracle's `FETCH APPROX FIRST k ROWS ONLY … WITH TARGET
  ACCURACY` is an example of putting approximation in the syntax.
- The planner must never use an ANN index to answer an exact predicate
  (e.g. `WHERE dist < r` without a LIMIT/ordering contract) unless the
  user opted into approximation.

### Plan shape

- Ordered index scan exposing an ordering operator (PostgreSQL:
  `amcanorderbyop`, as used by KNN-GiST and pgvector), consumed by Limit.
  The scan is an **incremental iterator**: Limit stops it; a filter above it
  pulls more (iterative scan) — the distance-browsing abstraction of
  Hjaltason & Samet.
- Re-ranking/recheck: if the index returns quantised distances, flag recheck
  and re-sort with exact distances (PostgreSQL's reorder queue mechanism
  generalises).
- Costing inputs: n, d, index parameters, k, predicate selectivity, whether
  vectors must be fetched for re-ranking (random I/O on heap/object store).

### Storage, MVCC, recovery

- Index entries for tuples invisible to the snapshot are filtered after the
  ANN step → effective k shrinks → need iterative scan or overfetch.
- Deletes/updates: tombstones + background repair (pgvector's HNSW vacuum
  repairs neighbour lists of removed nodes; FreshDiskANN consolidation).
- Graph pages must be WAL-logged or the index rebuilt after crash; many
  extensions use generic full-page WAL records — simple but write-heavy.
- Build: memory-bound (graph build wants everything in RAM); parallel build;
  bulk-load from a sorted/clustered stream where possible.

### Examples (as of 2025–2026)

- **pgvector** (PostgreSQL): types `vector`, `halfvec`, `sparsevec`, `bit`;
  access methods `hnsw` (options m, ef_construction; GUC hnsw.ef_search) and
  `ivfflat` (lists; GUC ivfflat.probes); operators `<->` L2, `<#>` negative
  inner product, `<=>` cosine distance; quantise-and-rerank via expression
  indexes. pgvectorscale adds a StreamingDiskANN index.
- **Oracle Database 23ai** (rebranded Oracle AI Database 26ai in late 2025):
  `VECTOR` type; in-memory neighbour-graph (HNSW) and disk-based
  neighbour-partition (IVF) vector indexes; approximate fetch syntax with a
  target accuracy.
- **SQL Server 2025 / Azure SQL**: `VECTOR` type, `VECTOR_DISTANCE`, and a
  DiskANN-based approximate vector index (`CREATE VECTOR INDEX … TYPE =
  'diskann'`, queried via `VECTOR_SEARCH` with `TOP (n) WITH APPROXIMATE`;
  preview in SQL Server 2025, GA in Azure SQL; early versions made the table
  read-only — check current docs for DML support).
- **Lucene/Elasticsearch/OpenSearch**: one HNSW graph per immutable segment
  (searched per segment, results merged), quantisation options; segment
  merges rebuild graphs, which dominates indexing cost.
- **Milvus**: index per sealed segment (IVF, HNSW, DiskANN), brute force on
  growing segments; **LanceDB/Lance**: IVF-PQ / IVF-HNSW indexes versioned
  with the dataset, unindexed fragments searched exhaustively and merged.
- **DuckDB (vss extension), ClickHouse**: HNSW via the usearch library as an
  index/skip-index.
- On Teradata Vantage, check the ClearScape Analytics vector functions
  (e.g. TD_VectorDistance) before writing custom distance code.

Common pattern worth copying: **immutable indexed segments + a small mutable
segment searched by brute force + result merge**, with background
compaction re-indexing. It sidesteps graph deletes and fits LSM, MVCC and
lakehouse storage alike.

---

## 8. ANN in lakehouse table formats

Context: Apache Iceberg tables are immutable data files tracked by
snapshots; side data can live in **Puffin** files (a container of typed
blobs with a JSON footer listing each blob's type, source field ids,
snapshot id, sequence number, offset, length and compression; table
metadata references statistics files per snapshot). The spec currently
defines blob types such as `apache-datasketches-theta-v1` (NDV sketches) and,
in format v3, `deletion-vector-v1`. Iceberg v3 also adds row lineage (stable
`_row_id`). Community proposals have explored ANN index blobs in Puffin;
check the current spec before relying on any blob type name.

Design decisions an engine/format designer must make:

| Decision | Options | Consequence |
|---|---|---|
| Index granularity | per data file / per partition / global | per-file: rebuilt with compaction, many small graphs to search (fan-out); global: best latency, invalidated by any write → needs delta handling |
| Row addressing | (file path, position) / row lineage id | positions break on compaction rewrite; lineage ids survive but need an id→location lookup |
| Snapshot binding | index records the snapshot / sequence number it covers | query at a later snapshot = index results − deleted rows (apply delete files / deletion vectors) ∪ brute force over data files added after the indexed snapshot |
| Routing | IVF centroids as a small routing blob → choose partitions/shards | enables partition pruning and distributed fan-out to top-p shards |
| Graph layout | Vamana records sized to object-store range reads; hot upper hops cached | object-store GETs have high latency → minimise hops (α > 1, larger R), batch range reads (beam width), cache medoid neighbourhood |
| Re-rank source | full vectors from Parquet column chunks vs vectors embedded in graph records | Parquet: no duplication but random page reads; embedded: DiskANN-style implicit re-rank, 2× storage |
| Maintenance | rebuild on compaction / incremental merge (FreshDiskANN-style) | write amplification vs freshness |

Correctness invariants for a lakehouse ANN index:
1. Results never include rows deleted at the query snapshot (apply deletes
   after ANN, before top-k truncation, and overfetch to compensate).
2. Rows in data files not covered by the index are still searchable (brute
   force or delta index) — otherwise recall silently collapses after
   appends.
3. An index blob is used only with the snapshot lineage it was built for;
   time travel to a snapshot older than the index falls back to exact or to
   an older index.
4. Rebuilds are atomic with the snapshot commit that references them
   (optimistic concurrency like any Iceberg metadata change).

Distributed query plan: coordinator scores centroids → selects shards/
partitions → workers run graph/IVF search with local PQ codes → return
top-k' with ids and approximate distances → re-rank with exact vectors
(worker-local if vectors co-located) → coordinator merges top-k. Merge of
per-shard top-k is exact for whatever each shard returned; recall loss
comes only from routing (unprobed shards) and per-shard approximation.

---

## 9. Tuning and testing

- Ground truth: exact kNN by brute force with the **same** metric and the
  same normalisation; store it; recompute after data changes.
- Sweep parameters (efSearch/L, nprobe, W, re-rank k') and record full
  recall/QPS/latency curves; pick an operating point per SLA.
- Watch distribution shift: queries unlike the indexed data (e.g. text query
  embeddings vs document embeddings) get worse recall than self-queries;
  evaluate with real query logs.
- Degree and connectivity checks on graphs: every node reachable from the
  entry point; in-degree histogram (hubs and orphans); after deletes, count
  nodes whose all out-neighbours are dead.
- Filter tests at selectivities 1, 0.1, 0.01, 0.001 and for correlated vs
  anti-correlated predicates (qualifying rows far from the query region).
- Determinism: fix seeds for k-means, level sampling and insertion order in
  tests; production builds are nondeterministic, so CI asserts recall
  thresholds, not exact result sets.
- Memory accounting: bytes/vector for codes, ids, graph; page-cache residency
  for SSD layouts; object-store request counts for lakehouse layouts.

Sources: no EDBS entry covers this material (Beyond EDBS). Foundations it
builds on: EDBS *High-Dimensional Indexing* (p.1706), *Curse of
Dimensionality* (p.717), *Multi step Query Processing* (p.2435), *Voronoi
Diagrams* (p.4580), *Dimensionality Reduction Techniques for
Nearest-Neighbor Computations* (p.1108), *Indexing Metric Spaces* (p.1876).
