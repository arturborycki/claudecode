---
name: olap-and-warehouse-engines
description: "Use when designing, implementing or reviewing an analytical/warehouse engine: star/snowflake schemas as the optimizer sees them, hierarchies, measures and summarizability, CUBE/ROLLUP/GROUPING SETS execution, cube computation and aggregate selection, star-join processing, bitmap/join indexes, column-store compression and late materialization, MPP warehouse partitioning, ETL/CDC and real-time loading, cloud/lakehouse warehouses, array/MOLAP storage. Triggers on OLAP, data warehouse, star schema, fact table, semi-additive, summarizability, GROUPING SETS, ROLLUP, CUBE, iceberg cube, BUC, PipeSort, HRU view selection, aggregate navigation, aggregate join index, bitmap join index, star transformation, invisible join, Bloom filter join, RLE, late materialization, zone map, MOLAP, SCD type 2, trickle feed, Parquet, Iceberg. Apply even when phrased as 'make dashboards faster', 'precompute rollups', 'why is this total wrong' or 'design the reporting schema'."
---

# OLAP and Warehouse Engines

This skill owns the parts of an engine that exist *because* the workload is
analytical: star-shaped schemas, aggregation along dimension hierarchies,
precomputed aggregates, star-join access paths, compressed column storage, and
bulk/trickle loading on MPP or cloud storage. The single most important idea:
**every warehouse speed-up (pre-aggregation, aggregate navigation, rollup
reuse, pruning) is only correct if the data is summarizable and the pruning is
conservative** — performance features are semantic contracts first.

## Mental model

- A fact table is a (sparse) function from the cross product of dimension
  leaf levels to measure values. Queries = select on dimension attributes,
  join fact to dimensions on surrogate keys, group by coarser hierarchy levels,
  aggregate measures. Every DW optimization exploits that fixed shape.
- Aggregates form a **lattice** (2^D group-bys, or the product of per-dimension
  hierarchy lattices). A materialized node can answer any query at or above it
  in the lattice — iff aggregation along the path is summarizable.
- Three physical families: **ROLAP** (relational star + materialized
  aggregates + bitmap/join indexes), **MOLAP** (chunked arrays, position
  encodes coordinates), **HOLAP** (detail in ROLAP, aggregates in MOLAP).
  Modern column stores collapse much of the distinction: a sorted, compressed
  fact projection scanned at memory bandwidth often beats a cube.
- Data arrives in batches (ETL/ELT, CDC micro-batches): append-mostly storage,
  partition attach/detach and delta-store-plus-merge are the norm.

## Core invariants

1. `GROUP BY GROUPING SETS (s1..sk)` returns exactly the UNION ALL of the k
   individual GROUP BYs, with columns absent from si set to NULL and
   `GROUPING(c)=1`; duplicate sets yield duplicate rows; the `()` set yields
   one row even on empty input.
2. A materialized aggregate V may answer query Q only if: Q's grouping is
   functionally determined by V's grouping; every rolled-up hierarchy step is
   strict, covering and onto (or V stores the bridge/weights to fix it); each
   aggregate is distributive, or algebraic with all components stored (AVG
   needs SUM and COUNT); Q's predicates reference only V's columns or columns
   derivable through FK-PK joins from them.
3. A semi-additive (stock) measure is never SUMmed along its non-additive
   dimension (usually time); a value-per-unit measure is never SUMmed at all.
   The aggregation rule belongs in catalog metadata, not in the client tool.
4. Every fact FK resolves to exactly one dimension row (an explicit
   "unknown/late-arriving" member counts); otherwise inner star joins drop
   facts silently and totals drift between grains.
5. Zone-map/partition/Bloom/bitmap pre-filters are **conservative**: false
   positives allowed, false negatives never (NULL, NaN, collation, casts).
6. Execution on compressed data (RLE runs, dictionary codes, bit-packed or
   delta values) yields results identical to decompress-then-execute.
7. Late materialization: position lists/bitmaps produced from different
   columns of one projection refer to the same row ordinal space; any
   reordering (sort, join) must carry positions or materialize first.
8. Iceberg-cube pruning is applied only to anti-monotone conditions
   (COUNT ≥ t, SUM ≥ t over non-negative values); AVG ≥ t needs a top-k
   bound, not direct pruning.
9. Incremental aggregate maintenance: refreshed view = recomputed view; groups
   whose COUNT(*) reaches 0 are deleted; MIN/MAX under deletion falls back to
   recomputing the affected groups.
10. SCD type 2: one current version per natural key, non-overlapping validity
    intervals, each fact references the version valid at event time.
11. Derived (reference) partitioning puts every fact row in exactly one
    fragment: dimension fragment predicates are complete and disjoint.

## Design space & trade-offs

| Option | When it wins | Cost / risk |
|---|---|---|
| Star (denormalized dims) | few joins, simple star detection, dims small | update anomalies in dims, wider dim rows |
| Snowflake (normalized dims) | huge/shared hierarchies, conformed levels | more joins; optimizer must flatten branches first |
| Full cube materialization | low D (≤ 6–8), static data, MOLAP marts | 2^D blow-up, long refresh, mostly redundant tuples |
| Partial materialization (HRU/greedy) | many dims, known workload | NP-hard selection, stale stats, rewrite complexity |
| No aggregates, fast column scans | in-memory/columnar, ad hoc, frequent loads | CPU per query; concurrency at scale |
| Bitmap / bitmap-join index | low–medium cardinality, ANDed predicates, read-mostly | update cost, lock granularity, high-cardinality size |
| Hash star join + Bloom/SIP | general case, columnar MPP | Bloom FP rate and build memory; probe order matters |
| Star transformation (semijoin bitmaps) | selective multi-dim filters, row store with FK bitmaps | extra join-back to dims for projected columns |
| Dimension Cartesian product + fact composite index | product of filtered dims tiny | explodes when filters are weak |
| MOLAP chunked arrays | dense sub-cubes, interactive slice/roll-up | sparsity, dimension changes force re-layout |
| Hash distribution on FK (MPP) | co-located fact–dim joins, even data | skew on hot keys; single co-location choice |
| Replicate small dims to all nodes | star joins without fact redistribution | storage × nodes, dimension update fan-out |
| Trickle feed into fact | freshness in seconds | contention with queries, index/MV maintenance |
| Delta store + periodic merge | columnar with continuous ingest | read path must merge delta; merge stalls |
| Storage/compute separation (cloud) | elastic, isolated workloads | remote-read latency, cache warm-up, metadata service as bottleneck |

## Algorithms that matter

- **GROUPING SETS**: (a) expand rows × sets with a grouping id, one hash
  aggregate; (b) sort chains — one sort emits all ROLLUP prefixes; a CUBE on
  n columns needs C(n, ⌊n/2⌋) chains; (c) smallest-parent reuse of partials.
- **PipeSort** (Agarwal et al. 1996): per lattice level, min-cost bipartite
  matching (one child per parent at scan cost, others at re-sort cost) →
  pipelines. **PipeHash**: smallest-parent tree, partition when tables spill.
- **MultiWay array cubing** (Zhao et al. 1997): one chunk scan updates all
  aggregates; memory = full extents of kept dims faster than the dropped
  one × chunk extents of slower kept dims → smallest dims vary fastest.
- **BUC** (Beyer, Ramakrishnan 1999): apex-down recursive counting-sort
  partitioning; recurse only where an anti-monotone threshold holds.
- **HRU greedy**: B(v|S) = Σ_{w ⪯ v} max(0, cost_S(w) − |v|); k picks give
  ≥ (1 − 1/e) of optimal benefit; O(k·n²).
- **Summary-delta** (Mumick et al. 1997): propagate signed aggregated deltas,
  refresh by merge (delete at COUNT 0); lower nodes from higher deltas.
- **Star joins**: dimension semijoins → key sets/bitmaps/Bloom → AND → fetch
  facts → join back only for projected attributes; columnar form: invisible
  join (dense surrogate keys as array offsets).
- **Eager aggregation** (Yan, Larson 1995): GROUP BY below FK joins when the
  pushed grouping includes the FK and aggregates decompose.
- **Encodings**: RLE (sorted leading columns), dictionary, FOR/bit-packing/
  PFOR, delta; predicates and aggregates evaluated on codes.

## Failure modes & classic bugs

- **Double counting via non-strict hierarchies** (product in two groups):
  child totals exceed the parent. Detect: per-level "parents per child ≤ 1";
  fix: weighted bridge tables, or refuse reuse of the lower aggregate.
- **Lost facts via ragged/non-covering hierarchies** (city → country, no
  state): state aggregates miss rows; country totals derived from them are low.
- **Inventory summed over months** (semi-additive misuse, often a BI default).
- **NULL-as-ALL ambiguity** in ROLLUP output over nullable grouping columns.
- **Stale or unsound rewrite**: aggregate used after a load without refresh,
  or rewrite across an FK the loader does not enforce (RELY).
- **Zone-map false negatives**: collation mismatch, NaN/−0.0 ordering,
  truncated string max, pruning before an implicit cast.
- **Bloom filter misuse**: built from the preserved side of an outer join,
  before the build is complete, or pushed across key-changing expressions.
- **Misaligned positions** in late materialization after a join reorders rows.
- **MPP skew** on hot FKs (unknown member, NULL key); partial aggregation that
  does not reduce cardinality.
- **Trickle-feed contention**: row-at-a-time inserts maintaining bitmap
  indexes and MVs; "open-loop fetch" loads.
- **SCD2 fan-out**: facts joined to dimension on natural key, not version key.

## Implementation checklist (C/C++/Rust)

- Catalog: hierarchy/level objects with declared strict/covering/onto bits;
  measures with additivity class and per-dimension rule (SUM, LAST_NON_EMPTY,
  AVG, NONE); FK RELY flags.
- Grouping-set planner: canonicalize ROLLUP/CUBE/concatenation into `u64`
  bitmasks, dedupe only under `GROUP BY DISTINCT`, pick expand / sort-chain /
  smallest-parent.
- Aggregate states expose `update/merge/finalize`; holistic aggregates refuse
  partial mode or switch to mergeable sketches (HLL, KLL) marked approximate.
- Aggregate navigation: lattice index of materialized aggregates keyed by
  per-dimension level; smallest qualifying ancestor; per-view freshness (LSN).
- Star join: filtered-dimension hash tables (dense arrays for 0..n surrogate
  keys); Bloom/range filters published before the fact scan starts; probes
  re-ordered by observed pass rate.
- Column segments (64K–1M rows): encoding id, min/max, null count, NDV;
  SIMD-friendly bit-packed codes; order-preserving dictionaries for ranges.
- Positions: `u32` offsets per segment; bitmap form above ~1/32 density.
- Loader: bulk segment build without per-row logging; partition attach as a
  metadata swap; delta store with snapshot-consistent merge.
- MPP: distribution metadata (hash/replicated/round-robin), co-location
  checks, local pre-aggregation with adaptive bypass.

## How to test it

- **Grouping-set oracle**: UNION ALL of plain GROUP BYs vs the operator; empty
  input, NULL grouping values, duplicate sets, HAVING on GROUPING().
- **Lattice consistency**: for additive measures each materialized node equals
  the roll-up of each materialized descendant.
- **Summarizability fuzzer**: random non-strict/ragged/unbalanced hierarchies;
  the rewriter must refuse reuse (or weight) exactly when invariant 2 fails.
- **Rewrite equivalence**: aggregate navigation, MV rewrite, star
  transformation on/off give identical results.
- **Incremental maintenance**: random insert/delete batches; refresh equals
  recompute, incl. MIN/MAX deletes and groups reaching COUNT 0.
- **Pruning oracle**: zone maps, partition pruning, Bloom, bitmap indexes on
  vs off on NULL/NaN/±0.0/long-string/collation/DST data.
- **Compression**: round-trip and compressed-vs-decoded execution per
  (encoding, operator). Benchmarks: SSB, TPC-H, TPC-DS; assert plan shape.

## Expert review questions

1. Which hierarchies are declared strict/covering/onto, and what does the
   rewriter do when data violates the declaration?
2. Where is each measure's per-dimension aggregation rule stored, and does
   the engine or the BI tool enforce it?
3. How are grouping sets executed (expand, sort chains, partial reuse)? Memory
   bound for CUBE over 6 columns?
4. What is the freshness contract of materialized aggregates; how does the
   optimizer know a view is stale?
5. Are dimension filters turned into fact-scan filters (Bloom/range/partition)
   before the fact scan starts? Under outer joins, casts, NULL keys?
6. Which encodings can predicates run on directly; where does the engine
   materialize; is late materialization ever slower here?
7. How is the fact distributed and partitioned; what share of joins is
   co-located; how is hot-key skew handled?
8. How do continuous loads coexist with scans; worst-case merge stall?
9. How are SCD1/2 changes applied; can a historical report be reproduced
   after a type-1 overwrite?
10. Which pruning metadata is kept per segment/file, and is it maintained
    transactionally with the data?
11. Cloud: what is the unit of caching and pruning; how does metadata scale
    independently of compute?
12. Are holistic aggregates pre-aggregated via sketches, and is the
    approximation surfaced?

## Go deeper

- `references/dimensional-semantics-and-summarizability.md` — catalog model of
  measures/hierarchies, rewrite guards, irregular hierarchies, SCDs, OLAP
  algebra, MDX, what-if.
- `references/cube-computation-and-view-selection.md` — GROUPING SETS
  execution, PipeSort/PipeHash, MultiWay, BUC/iceberg, Dwarf/CURE, HRU, maintenance.
- `references/star-join-processing.md` — star-join strategies, Bloom/SIP,
  bitmap/join indexes, SMA/zone maps, derived partitioning, eager aggregation.
- `references/column-store-engineering.md` — encodings, compressed execution,
  late materialization, invisible join, update handling, cracking.
- `references/warehouse-architecture-etl-and-cloud.md` — architectures, ETL/CDC,
  real-time DW, physical design/tuning, MPP (Teradata), cloud and lakehouse.
- `references/array-and-multidimensional-storage.md` — array algebra,
  chunking/tiling, sparse chunks, MOLAP vs ROLAP, tertiary storage, HDF5.
- `references/edbs-entries.md` — all cluster entries with pages (use the
  `edbs-reference` skill for full text).

## Related skills

- `columnar-arrow-layout` (in-memory vectors; here: on-disk segments,
  encodings, materialization) · `query-optimizer` (generic rewrites; here:
  star detection, aggregate navigation, grouping sets) ·
  `parallel-distributed-execution` (exchange mechanics; here: distribution and
  co-location design) · `join-algorithms` (hash/Bloom joins in general).
- `materialized-views-ivm` (general view matching/IVM; here the aggregate
  lattice) · `cardinality-and-statistics` (cuboid sizes, star selectivity) ·
  `tuning-and-benchmarking` (advisors, TPC-H/DS, SSB) ·
  `index-structures-catalog` · `multidimensional-and-similarity-indexing`
  (R-/UB-trees over tiles) · `query-execution-advanced` (vectorized/compiled).
- `parallel-database-systems`, `distributed-dbms-design` (general
  architectures, fragmentation/allocation theory) · `stream-processing-engines`
  (CDC, continuous aggregation) · `temporal-databases` (periods vs SCD) ·
  `sql-semantics-and-active-rules` (rules behind active DW) ·
  `beyond-relational-engines` (science/array systems) · `storage-devices-and-io`
  (tertiary/HSM) · `concurrency-control-theory` (HTAP snapshots) ·
  `dbms-architecture`, `relational-theory`, `recovery-and-durability`,
  `replication-protocols`, `database-security-internals`.
- Existing: `storage-and-indexing`, `page-and-file-format`, `lsm-storage`
  (delta stores), `query-plan-design`, `query-engine-testing`.

## Grounding

EDBS 2nd ed. — all 29 entries with pages and relevance are listed in
`references/edbs-entries.md`; core ones: Cube Implementations p.710,
Summarizability p.3843, Multidimensional Modeling p.2328, Measure p.2217,
Hierarchy p.1705, Bitmap Index p.311, Indexing of Data Warehouses p.1880,
Query Processing in Data Warehouses p.3039, Optimization and Tuning in Data
Warehouses p.2619, Column Stores p.518, Parallel and Distributed Data
Warehouses p.2644, Data Warehousing in Cloud Environments p.908, Extraction,
Transformation, and Loading p.1432, Array Databases p.165.

Seminal work: Gray et al. data cube (ICDE 1996); Harinarayan, Rajaraman,
Ullman (SIGMOD 1996); Agarwal et al. (VLDB 1996); Zhao, Deshpande, Naughton
(SIGMOD 1997); Beyer, Ramakrishnan (SIGMOD 1999); Lenz, Shoshani (SSDBM
1997); Pedersen, Jensen, Dyreson (VLDB 1999); O'Neil, Quass (SIGMOD 1997);
Chan, Ioannidis (SIGMOD 1998); Valduriez (TODS 1987); Stonebraker et al.
C-Store (VLDB 2005); Abadi et al. (SIGMOD 2006, 2008); Mumick, Quass, Mumick
(SIGMOD 1997); Yan, Larson (VLDB 1995); Dageville et al. (SIGMOD 2016).
