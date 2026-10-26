# Column-store engineering for warehouses

Storage layout, compression, compressed execution, materialization strategy
and update handling for column-oriented analytical engines. The in-memory
vector format (Arrow buffers, validity bitmaps) is covered by
`columnar-arrow-layout`; vectorized vs compiled execution substrates by
`query-execution-advanced`. This file owns the warehouse-specific layer
between disk segments and operators.

## 1. Lineage and what actually makes column stores fast

| Milestone | Contribution |
|---|---|
| Transposed files (1970s) | store a file attribute-by-attribute |
| DSM — Copeland, Khoshafian (SIGMOD 1985) | full decomposition into binary relations (surrogate, value); schema changes do not change storage structure |
| K/kdb (1990s), Sybase IQ (≈1995) | commercial column engines; Sybase IQ's projection and bit-sliced indexes |
| MonetDB (Boncz, Kersten) | BATs, column-at-a-time algebra with full materialization of intermediates |
| MonetDB/X100 — Boncz, Zukowski, Nes (CIDR 2005) | vectorized "hyper-pipelined" execution on cache-resident vectors → Vectorwise |
| C-Store — Stonebraker et al. (VLDB 2005) | projections with sort orders, read/write stores, compression-aware operators → Vertica (Lamb et al., PVLDB 2012) |
| SAP HANA, DB2 BLU (Raman et al. 2013), SQL Server columnstore, Oracle in-memory | columnar engines inside general-purpose DBMSs |
| RCFile (Hive) | row groups whose columns are stored and compressed separately — the hybrid that led to ORC and Parquet |

"Column family" NoSQL stores (Bigtable, HBase, Cassandra, Hypertable) group
columns into families stored per row key; they are not analytical column
stores and share few of the techniques below.

Abadi, Madden, Hachem (SIGMOD 2008) showed that emulating a column store in a
row engine (full vertical partitioning, index-only plans, materialized
projections) does **not** recover the performance. Removing optimizations one
at a time from a real column store showed the gains come from: (1)
compression with operators working on compressed data, (2) late
materialization, (3) block (vector) iteration, and (4) the invisible join for
star schemas. Reading fewer columns is necessary but nowhere near sufficient.
Halverson et al. (UW–Madison tech report, 2006) and Harizopoulos et al.
(VLDB 2006) compared C-Store-style and row storage in one
framework with similar conclusions: the win depends on workload — many
columns per row and point access favour rows.

## 2. Physical organization

### 2.1 Segments

Split each column into segments (row groups / micro-partitions / containers)
of a fixed row count (typically 64K–1M rows). Per segment keep:

- encoding id and parameters (bit width, frame base, dictionary reference),
- min, max, null count, (approximate) distinct count,
- optional Bloom filter or value set for point-lookup pruning,
- row-count and a row-id base, so position ↔ segment mapping is arithmetic.

All columns of a table (or projection) use identical segment boundaries so
positions align across columns (invariant 7 in SKILL.md).

### 2.2 C-Store projections

- A projection = a subset of a table's columns (optionally including columns
  of tables reachable through FKs: a pre-joined projection), stored sorted on
  one or more of its columns.
- Several overlapping projections with different sort orders serve different
  predicates; redundancy across nodes doubles as **K-safety** (survive K node
  failures).
- The read-optimized store (RS) is compressed and sorted; the writeable store
  (WS) absorbs inserts; a tuple mover merges WS into RS in batches.
- The original design reconstructed tuples across projections via join
  indexes; Vertica later abandoned join indexes and required a "super
  projection" containing all columns of each table, because join indexes were
  too costly to maintain (Lamb et al. 2012).

### 2.3 Sort order selection

Sort lexicographically on low-cardinality, frequently filtered columns first
(e.g. region, date, product category, then high-cardinality keys). The leading
column gets long runs (excellent RLE), each subsequent column gets runs
bounded by the previous columns' run boundaries. Sorting also narrows
min/max ranges per segment, making zone maps effective.

> **Beyond EDBS:** when several columns are filtered with similar frequency,
> interleaved orders (Z-order/Hilbert over a few keys) trade some RLE for
> balanced pruning on each key; Delta Lake's Z-ordering and Redshift's
> interleaved sort keys are production examples.

## 3. Lightweight encodings

| Encoding | Representation | Best for | Predicates/aggregates on encoded form |
|---|---|---|---|
| RLE | (value, start, length) triples | sorted or clustered low-cardinality columns | per run: filter cost ∝ #runs; SUM += v·len; COUNT per run |
| Dictionary | codes into a value dictionary | low/medium cardinality strings | evaluate predicate once on dictionary → code set; scan codes |
| Order-preserving dictionary | codes sorted like values | range predicates, MIN/MAX, ORDER BY on codes | ranges map to code ranges |
| Bit-packing | ⌈log2(range)⌉ bits per value | small-range integers, dictionary codes | SIMD compare on packed lanes |
| Frame of reference (FOR) | segment base + small offsets, bit-packed | clustered numeric values (dates, keys) | compare against (constant − base) |
| Delta | differences between consecutive values (then bit-packed) | sorted keys, timestamps, row ids | needs prefix sum to decode; range filters via running sum |
| PFOR / PDICT / PFOR-DELTA (Zukowski et al., ICDE 2006) | FOR/dictionary with out-of-range "exceptions" patched separately | skewed distributions with outliers | branch-free decode loops; high decode bandwidth |
| Bitmap (per value) | one bitmap per distinct value | very low cardinality | AND/OR/popcount directly |
| Null suppression / sparse | positions + values of non-default entries | mostly-NULL or mostly-zero columns | skip absent positions |
| Heavyweight (LZ4, Zstd, Snappy) | general-purpose on top of the above | cold data, I/O-bound storage | none — must decompress |

Choosing per segment: compute run count, distinct count, value range and
sortedness during segment build; pick the encoding minimizing
(size × expected scan frequency + decode cost). Re-evaluate at merge time.

Dictionary scope: per-segment dictionaries compress better and need no global
coordination; a global (per-column) dictionary makes codes comparable across
segments, enabling joins and GROUP BY directly on codes. Many engines use a
global dictionary for hot low-cardinality columns and local dictionaries
elsewhere.

> **Beyond EDBS:** DB2 BLU uses frequency-based encoding (more frequent values
> get shorter codes, column values partitioned by code length) and evaluates
> many predicates without decoding; SAP HANA's main store uses a sorted
> dictionary while its delta store uses an unsorted, append-only dictionary,
> reconciled at delta merge.

## 4. Operating on compressed data (Abadi, Madden, Ferreira, SIGMOD 2006)

Design the operator interface around **compressed blocks** with properties
instead of decompressed tuples:

| Block property | Lets operators… |
|---|---|
| isOneValue (whole block one value, e.g. RLE run) | evaluate predicate once; aggregate value × count |
| isValueSorted | binary search for range predicates; merge-join without sort |
| isPosContiguous | represent result positions as a range instead of a list |
| encoding exposes codes | compare codes, group on codes, hash codes |

Rules of thumb:

- Selection on RLE: output position *ranges*; on dictionary: translate the
  predicate into a code set (or code range if order-preserving) first, then
  SIMD-scan the code vector; on bit-packed: compare in packed form.
- Aggregation: dense dictionary code space → array-indexed aggregation table
  (no hashing); RLE → multiply.
- Join/GROUP BY on codes only when both sides share the dictionary;
  otherwise decode one side (usually the smaller).
- Decompress as late as possible, but not later than the first operator that
  cannot handle the encoding; keep a "decompress" operator explicit in plans.
- Correctness requirement: compressed execution ≡ decompress-then-execute,
  including NULL semantics (NULL is not a dictionary code unless explicitly
  reserved) and collations (code order must match the comparison collation).

> **Beyond EDBS:** BitWeaving (Li, Patel, SIGMOD 2013) lays out bit-packed
> codes vertically or horizontally so that predicates evaluate many codes per
> machine word — scans at a fraction of a CPU cycle per value.

## 5. Materialization strategy

Abadi, Myers, DeWitt, Madden (ICDE 2007) compare tuple construction points:

| Strategy | Mechanism | Wins when | Loses when |
|---|---|---|---|
| Early materialization (EM) | stitch the needed columns into tuples at (or right after) the scan | low selectivity (most rows survive); many columns used after filtering; downstream operators are row-oriented | data compressed (decompression early), selective predicates |
| Late materialization (LM) | each predicate yields positions (lists/bitmaps/ranges); intersect; fetch remaining columns only for survivors | selective predicates; compressed columns; few output columns | positions become unordered (after joins) → random access to other columns |

Position representations: ranges (contiguous runs, from RLE or sorted
predicates), bitmaps (density above ≈1/32 of rows in the segment), sorted
lists (sparse). Intersect in the cheapest pairwise form.

Joins under LM: the probe (outer) side keeps its position order; the build
(inner) side's matching positions are out of order. Either sort the inner
positions before fetching (as in Jive join) or materialize the inner columns
needed above the join early. A hybrid — late for the probe side, early for
the build side — is a common engine default.

> **Beyond EDBS:** most modern vectorized engines materialize per vector
> (≈1–2K rows) with selection vectors, which keeps LM's benefit within a
> vector while avoiding random cross-segment fetches.

## 6. The invisible join (Abadi, Madden, Hachem 2008)

Star join over a column store in three phases:

1. **Dimension predicates → key sets.** Evaluate each dimension's predicates;
   build a hash set of qualifying surrogate keys. If the qualifying keys form a
   contiguous range (keys assigned in hierarchy order), rewrite into a
   `BETWEEN lo AND hi` predicate on the fact FK column instead — no hashing.
2. **Probe FK columns → position bitmaps.** Scan each fact FK column, test
   membership (or range), produce a bitmap per dimension, AND them (process
   most selective first; skip blocks once the running bitmap is empty).
3. **Fetch.** For surviving positions, fetch FK values and use them as
   positional offsets into the dimension column (dense surrogate keys
   0..n−1 mean the dimension column *is* the lookup table); fetch measure
   columns at the same fact positions.

Net effect: no hash join with the fact at all; each dimension is touched
twice (predicates, then value extraction) through array indexing. Correctness
depends on keys being dense and stable — reorganizing a dimension's key space
requires rewriting fact FK columns.

## 7. Vectorized (block) iteration

- Operators exchange vectors of 1K–2K values per column plus a selection
  vector, sized to fit the L1/L2 cache with all columns of a pipeline.
- Primitives are tight loops per (operator, type, encoding) combination,
  generated from templates; no per-tuple interpretation or virtual calls.
- Predicates produce selection vectors; subsequent primitives process only
  selected positions (or all positions with a mask when selectivity is high
  and branch-free code is faster).
- Compiled (data-centric, HyPer-style) execution is the main alternative; see
  `query-execution-advanced`. Either way the warehouse-specific layer above
  (encodings, positions, zone maps) is the same.

## 8. Updates and loading

Column stores are read-optimized; in-place updates of compressed sorted
segments are expensive. Production designs:

| Design | Mechanism | Read-path cost |
|---|---|---|
| Write store / read store (C-Store WS/RS) | inserts into an uncompressed write store; tuple mover merges into the sorted compressed store | queries union WS and RS |
| Delta store + merge (HANA L1/L2/main) | row-format L1 delta → columnar L2 delta (unsorted dictionary) → main (sorted dictionary) via periodic merge | merge-on-read of delta and main |
| Positional delta trees (Héman et al., SIGMOD 2010; Vectorwise) | differences indexed by position, merged during scans | cheap positional merge |
| Bulk segments + delete bitmaps | loads create new immutable segments; deletes mark a bitmap; compaction rewrites | AND with delete bitmap; compaction cost |
| Incremental RLE maintenance (Mohapatra, Genesereth 2012) | update run-length encoded columns in place where possible | specialized |

Invariants: a scan sees a consistent snapshot across all columns of the
projection and across delta + main; the merge is atomic per segment set; row
ids used by delete bitmaps are stable until compaction (or remapped
atomically with it). See `lsm-storage` for the merge-policy side.

> **Beyond EDBS (Teradata):** Teradata Columnar stores column partitions in
> containers with automatic per-container compression and allows mixing
> column and row partitions (and row partitioning by e.g. date) in one table;
> column-partitioned tables were originally NoPI-only (later releases also
> allow a PI or primary AMP index — verify against current docs) and suit
> append-heavy loads, consistent with the read-optimized trade-off above.

## 9. Adaptive layouts: database cracking

- **Cracking** (Idreos, Kersten, Manegold, CIDR 2007): keep a copy of a column
  (cracker column); each range query physically partitions the relevant piece
  around its bounds (quicksort-like partition step), recording piece
  boundaries in a cracker index. The column converges toward sorted order
  where queries concentrate; no up-front index build.
- **Sideways cracking** (SIGMOD 2009) keeps cracker maps of column pairs
  aligned so multi-attribute queries reconstruct tuples without random
  access — self-organizing tuple reconstruction.
- Schuhknecht, Jindal, Dittrich (VLDB J 2016) evaluated many cracking
  variants: convergence speed and robustness to skewed/sequential workloads
  vary widely; stochastic cracking helps adversarial patterns.
- Cracking is an instance of adaptive physical design; the same idea is being
  applied to partitioning and materialized views.

## 10. Other uses of column organization

- RDF: vertical partitioning by property into (subject, object) tables stored
  in a column store (Abadi et al., VLDB 2007); scalability concerns with many
  properties and skewed property sizes (Sidirourgos et al., PVLDB 2008).
- Search engines and column stores converge (posting lists ≈ compressed
  position lists; Bjørklund et al. 2009).

## 11. Pitfalls

- Mis-aligned segment boundaries across columns after a partial rewrite.
- Order-preserving dictionary assumed but not built (range predicate on codes
  returns wrong rows), or built with a collation different from the query's.
- Max value truncated for long strings in segment stats (must round **up** the
  stored max, or mark it inexact).
- Float statistics with NaN/−0.0 ordering inconsistent with comparison
  semantics.
- Decoding inside the innermost loop per value (virtual dispatch per value)
  — destroys the benefit; dispatch per vector.
- Late materialization across a join without re-sorting positions → random
  I/O storm on the inner side.
- Delta store growing unbounded under steady trickle load because merges are
  starved by long-running queries holding old snapshots.

## 12. Tests

- Round-trip per encoding with random data, extreme bit widths (0, 1, 63, 64),
  all-NULL and no-NULL segments, single-value segments.
- Compressed execution vs decompressed oracle for every (operator, encoding)
  pair, including NULL handling and collation-sensitive comparisons.
- Zone-map pruning on/off equivalence with adversarial min/max edge cases.
- Snapshot consistency: concurrent loads/merges with scans; scans must never
  see a row in both delta and main or in neither.
- Performance regression guards on bytes read per query and on
  encoded-vs-decoded operator paths (assert the encoded path was taken).

Sources: EDBS — Column Stores p.518; Query Processing in Data Warehouses
p.3039; Optimization and Tuning in Data Warehouses p.2619; Indexing of Data
Warehouses p.1880; Data Warehousing in Cloud Environments p.908; Bitmap Index
p.311.
