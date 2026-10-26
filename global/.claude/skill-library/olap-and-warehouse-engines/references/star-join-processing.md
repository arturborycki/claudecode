# Star-join processing and warehouse indexing

How an engine evaluates the canonical warehouse query — filter several small
dimensions, join them to a huge fact table on surrogate keys, group, aggregate
— and the index structures built specifically for it.

```
SELECT d.year, s.region, SUM(f.amount)
FROM   sales f
JOIN   date d    ON f.date_sk  = d.sk
JOIN   store s   ON f.store_sk = s.sk
JOIN   product p ON f.prod_sk  = p.sk
WHERE  d.year IN (2024, 2025) AND s.country = 'PL' AND p.category = 'Audio'
GROUP  BY d.year, s.region;
```

Characteristics the engine exploits: the fact participates in every join;
each individual dimension predicate may be weak (1/100) while their
conjunction is strong (1/10^4–1/10^6); output is tiny compared to input;
joins are FK→PK so they neither multiply nor (with enforced FKs) drop facts.

## 1. Strategy catalogue

| Strategy | Mechanism | Wins when | Fails when |
|---|---|---|---|
| Left-deep hash pipeline | build hash tables on filtered dims; fact streams through probes | general default; dims fit in memory | no early filtering — every fact row decoded and probed |
| Bloom / sideways information passing | each dim build publishes a key filter applied in the fact scan | columnar scans; selective combined filters | filters useless (non-selective) yet still cost CPU; builds not finished before scan |
| Star transformation (semijoin bitmaps) | per dim: keys → OR of FK bitmaps; AND across dims; fetch facts; join back | row store with bitmap indexes on FKs, very selective conjunctions | low selectivity — random fetches beat by a scan |
| Dimension Cartesian product + composite fact index | product of filtered dims, then index lookups on fact (dim-key,...) | product is small, index leading columns match | product explodes (weak filters, many dims) |
| Invisible join (column store) | predicates → key sets/ranges; probe FK columns → position bitmaps; AND; fetch dim values by position | sorted/dense surrogate keys, column store | non-dense keys, need for hash lookups everywhere |
| Pre-joined structures | bitmap join index, join index, derived partitioning, aggregate join index | stable predicates on dimension attributes | many distinct predicate attributes; maintenance |

### 1.1 Probe ordering in the hash pipeline

With per-dimension pass rates p_i (fraction of fact rows surviving the join
with dimension i) and probe cost c_i, the expected per-row cost of order
(1..d) is c_1 + p_1 c_2 + p_1 p_2 c_3 + … . Ordering by increasing
c_i / (1 − p_i) minimizes it (classic predicate ordering, assuming
independence). Estimates are often wrong; **adaptive ordering** at run time
(sample pass rates per batch, re-sort probes) is cheap and robust.

> **Beyond EDBS:** Lookahead Information Passing (Zhu, Potti, Saurabh, Patel,
> PVLDB 2017) pushes all dimension Bloom filters into the fact scan and orders
> them adaptively, making star-join performance largely insensitive to join
> order choice — a strong argument for SIP over clever join enumeration.

### 1.2 Bloom filters for star joins

- False-positive rate with m bits, n keys, k hash functions ≈
  (1 − e^{−kn/m})^k; optimal k = (m/n)·ln 2; ≈ 10 bits/key gives ≈ 1%.
- With several dimension filters, false positives are independent and are
  removed by the real join later — correctness only requires no false
  negatives (invariant 5 in SKILL.md).
- Blocked/register-blocked Bloom filters (one cache line per key) cut probe
  cost; for very small key sets an exact hash set or bitmap over dense keys
  is better.
- **Range filters**: if the qualifying surrogate keys form a contiguous range
  (date keys assigned in calendar order, product keys assigned in hierarchy
  order), publish [min,max] instead — exact for that dimension and usable for
  zone-map and partition pruning. Assign surrogates in hierarchy order at load
  time to make this common.
- Filter legality: do not push a filter from the preserved side of an outer
  join, across expressions that change key values (casts, COALESCE), or
  before the build input is complete (pipeline breaker on the build).

> **Beyond EDBS:** Spark 3 "dynamic partition pruning", Oracle join-filter
> pruning and Teradata dynamic partition elimination all turn a dimension
> filter evaluated at run time into partition pruning on the fact — the
> partition-level analogue of a Bloom filter.

### 1.3 Star transformation (semijoin + bitmaps)

```
for each dimension Di with predicate Pi:
    K_i   = π_sk σ_Pi (Di)                            -- small key set
    B_i   = OR_{k ∈ K_i} bitmap_index(F.fk_i)[k]      -- RIDs of qualifying facts
B = AND_i B_i                                         -- strong combined filter
rows = fetch F by B                                   -- sorted RID order
result = join rows back to only the dims referenced in SELECT/GROUP BY
```

The rewrite is `F.fk_i IN (SELECT sk FROM Di WHERE Pi)` per dimension; the
optimizer must recognise that the join-back is still required for projected
dimension attributes, and may skip it otherwise (join elimination).

### 1.4 Dimension Cartesian product (Red Brick STARjoin style)

Compute σ(D1) × σ(D2) × … (size Π|σ(Di)|), then probe a composite (or star)
index on the fact. Cost ≈ Π|σ(Di)| index probes + matching facts. Use it only
when the product is well below the number of qualifying fact pages; guard
with a hard cap since one weak filter turns it into a disaster.

> **Beyond EDBS (Teradata):** Teradata's optimizer documents
> large-table/small-table (LT/ST) planning for star joins, where small
> (filtered) tables may be product-joined first and the result joined to the
> large table, often via its primary index — the same trade-off as above.

### 1.5 Snowflakes

Evaluate each snowflake branch to a key set at the level referenced by the
fact (predicate on `category` → set of `product.sk`), then treat it as a
star dimension. Tao et al. (CASCON 2003) give heuristic rewrites for large
star queries with snowflakes; the essential step is flattening branches
before fact-level join enumeration.

## 2. Join indexes and star indexes

- **Join index** (Valduriez, TODS 1987): the set of RID pairs {(r, s)} for
  R ⋈_p S, i.e. π_{R.rid, S.rid}(R ⋈_p S). Viewed from R it is an index on
  the "virtual attribute" S.rid. Store clustered on R or S, or for an
  equijoin as value → (R-RIDs, S-RIDs). A join becomes a scan of the join
  index plus RID fetches; Li and Ross (VLDB J 1999) give I/O-efficient
  algorithms (Jive/Slam join) for fetching both sides.
- **Star index**: one join index per FK join of a star or snowflake —
  semantically what an FK column plus a dense dimension array already gives a
  column store.
- **Bitmapped join index** (O'Neil, Graefe, SIGMOD Rec 1995): a join index
  whose RID lists are bitmaps; generalised as a **bitmap join index** — a
  bitmap index on the fact keyed by a *dimension attribute* (e.g. bitmap per
  `store.region` over fact rows). Eliminates the dimension join for that
  predicate entirely. Implemented in Red Brick and Oracle.
- Derived horizontal partitioning (§5) achieves the same at partition grain.

## 3. Bitmap indexes: design space (Chan, Ioannidis)

Two orthogonal parameters for an attribute of cardinality C:

1. **Value decomposition** into n digits with bases ⟨b_n, …, b_1⟩,
   Π b_i ≥ C (base-C = single component; base-2 = bit-sliced).
2. **Per-component encoding**:

| Encoding | Bitmaps per component (base b) | Bitmap E/R/I set when | Equality cost | Range cost (one component) |
|---|---|---|---|---|
| Equality (value-list) | b | digit = j | 1 scan | up to b/2 scans (or complement) |
| Range | b − 1 (top is all ones) | digit ≤ j | 2 scans (R^v ∧ ¬R^{v−1}) | ≤ 2 scans (R^{v2} ∧ ¬R^{v1−1}) |
| Interval | ⌈b/2⌉ | digit ∈ [j, j + ⌈b/2⌉ − 1] | ≤ 2 scans | ≤ 2 scans |

Interval encoding matches range encoding's worst case with about half the
space. More components → less space, more scans per query.

Named designs:

| Index | Description | Systems |
|---|---|---|
| Value-List | equality-encoded, base-C | most RDBMSs |
| Bit-Sliced Index (BSI) | range-encoded multi-component; binary BSI has ⌈log2 C⌉ slices | Model 204, Sybase IQ (base-10) |
| Encoded Bitmap Index (Wu, Buchmann 1998) | lookup table maps values to ⌈log2 C⌉-bit codes chosen to minimise scans for the workload | research |
| Encoded Vector Index | one vector of short codes per row (no bitmaps); IN-list evaluation by code comparison | IBM DB2 |
| Projection index (O'Neil, Quass 1997) | the column's values stored densely in RID order | Sybase IQ — i.e. a column store column |
| Range-based / binned bitmaps | one bitmap per value range; lossy, needs a candidate check | scientific DBs (FastBit lineage) |
| Multi-resolution (Sinha, Winslett 2007) | binned level + exact level to avoid candidate checks | scientific DBs |

### 3.1 Space and I/O break-even (uncompressed)

With 32-bit RIDs, a value-list index is smaller than RID lists when C < 32
on average, and reading one bitmap (N bits) beats reading a RID list when the
predicate selects more than 1/32 ≈ 3.1% of rows. Compression moves both
break-evens (sparse bitmaps compress), which is why compressed bitmaps work
for high-cardinality columns too.

### 3.2 Aggregation directly on bitmaps (O'Neil, Quass 1997)

With a binary bit-sliced index over measure M (slices S_0..S_{k−1}) and a
found-set bitmap F:

```
SUM(M | F) = Σ_i 2^i · popcount(S_i AND F)
COUNT(F)   = popcount(F)
```

k popcount passes instead of fetching rows; MIN/MAX and even MEDIAN can be
computed slice by slice from the most significant slice down. BSI arithmetic
(Rinfret, O'Neil, O'Neil, SIGMOD 2001) adds/subtracts bit-sliced vectors to
evaluate expressions and top-k without materializing values.

### 3.3 Compression

| Scheme | Unit | Operates compressed? | Notes |
|---|---|---|---|
| Generic (LZ77 etc.) | byte stream | no — decompress first | good I/O savings, CPU kills it |
| Model 204 hybrid | fixed segments: dense = verbatim bitmap, sparse = RID list | yes | ancestor of container-based designs |
| BBC (Antoshenkov) | byte-aligned fill/literal codes | yes | Oracle; compact, byte-level branching |
| WAH (Wu, Otoo, Shoshani) | word-aligned: 31-bit literal words or fill words (run of 0s/1s) | yes, word-at-a-time | faster than BBC, somewhat larger |
| PLWAH (Deliège, Pedersen 2010) | WAH fill words also carry a position for a nearly-identical next literal | yes | smaller than WAH for sparse bitmaps |
| Roaring (Chambi, Lemire et al. 2016) | split by high 16 bits; container = sorted array (≤ 4096), 2^16-bit bitmap, or runs | yes, per-container algorithms | random access; the common default today |

Evaluating a complex Boolean predicate is itself an optimization problem
(which bitmaps, which order, when to complement); Amer-Yahia and Johnson
(VLDB 2000) give a linear-time dynamic program for the optimal plan over
compressed bitmaps.

### 3.4 Hybrid B-tree/bitmap

For a non-unique B-tree, store each key's RID set as a compressed bitmap
(Oracle does this with BBC). One structure serves both high-cardinality point
lookups and low-cardinality AND/OR plans.

### 3.5 Bitmap index operational costs

- Updates: changing one row touches one bitmap per encoded component; with
  compressed bitmaps an insert in the middle may re-encode a run. Use
  append-only RID assignment and batch maintenance at load.
- Concurrency: one compressed bitmap covers many rows → coarse locking; keep
  bitmap indexes on read-mostly fact partitions and rebuild per partition.
- Deleted rows: keep an existence (tombstone) bitmap ANDed into every plan
  rather than rewriting each value bitmap.

## 4. Aggregate-storing and summary indexes

- **Aggregate B-tree**: each entry also stores the aggregate of its subtree;
  a range aggregate costs two root-to-leaf walks (O(log n)) instead of a leaf
  scan. Extended to multiple dimensions (cube forests, Johnson & Shasha 1997;
  Cubetrees — packed R-trees holding ROLAP views, Kotidis & Roussopoulos 1998)
  and to temporal intervals (Kline & Snodgrass 1995).
- **Small Materialized Aggregates** (Moerkotte, VLDB 1998): per storage bucket
  keep min, max, count, sum of selected columns. A bucket whose min/max
  excludes the predicate is skipped; a bucket fully inside the predicate
  contributes its stored sum/count without being read. This is the origin of
  the **zone map** (min/max pruning) used by essentially every analytical
  engine.
- **Coarse / summary indexes** (Johnson 1998): per partition, record which
  values occur (e.g. which customer ids) or the inverse map value → partitions;
  minimizes partitions touched for point predicates on non-partitioning keys.

> **Beyond EDBS:** zone-map effectiveness depends entirely on physical order.
> Sorting or clustering (by date, then by a frequently filtered dimension key;
> or Z-order/Hilbert interleaving over several keys) makes min/max ranges
> narrow. Netezza zone maps, Oracle zone maps, Snowflake micro-partition
> metadata, Parquet/ORC statistics and Iceberg manifest column bounds are all
> the SMA idea at different granularities.

## 5. Partitioning for star queries

- Range/list/hash partitioning (and composites) of the fact; time is the
  primary partitioning key almost universally (rolling window: attach new
  partition, detach oldest).
- **Derived (referential) horizontal partitioning**: partition dimensions by
  predicates (primary partitioning), then partition the fact by semijoin with
  dimension fragments: F_{j,k,…} = F ⋉ D1_j ⋉ D2_k ⋉ …. Fragment count = Π m_i,
  so the designer caps it (threshold W). Benefits: the fact–dimension join is
  pre-computed at fragment level and dimension predicates prune fact
  fragments. Oracle 11g exposes it as reference partitioning. The selection
  problem is NP-hard (Bellatreche et al.); heuristics: hill climbing, genetic,
  simulated annealing.
- **Multidimensional clustering**: store facts in blocks clustered by
  combinations of several dimension values with per-dimension block indexes
  (DB2 MDC, Padmanabhan et al., SIGMOD 2003) — partition pruning on several
  dimensions at once without Π m_i explosion of partitions.

## 6. Group-by placement: eager and lazy aggregation (Yan, Larson, VLDB 1995)

For Q = γ_{G; agg(F.m)}(F ⋈_{F.fk = D.sk} D):

```
eager:  γ_{G; agg_final}( γ_{G_F ∪ {F.fk}; agg_partial(F.m)}(F) ⋈ D )
        where G_F = G ∩ attrs(F)
```

- Valid when the aggregate is decomposable (partial/final pair) and the join
  is on the pushed grouping's FK. If aggregates also reference D's columns, or
  the join can match several D rows, partial results need a count multiplier
  (eager count / double eager variants).
- Pays off when distinct (G_F, fk) combinations ≪ |F| — e.g. aggregating
  daily facts to (store, product) before joining. It is a cost decision:
  partial aggregation that barely reduces cardinality costs a full extra pass.
- Lazy aggregation is the inverse rewrite (pull GROUP BY above a join) when
  the join is very selective.
- In MPP engines the same rewrite becomes local pre-aggregation before the
  shuffle; make it adaptive (bypass when the observed reduction ratio is low).

## 7. Optimizer integration checklist

- Detect stars/snowflakes from declared (or RELY) FKs; restrict enumeration:
  dimensions join only through the fact; bushy plans only for snowflake
  branches and multi-fact queries.
- Choose among strategies by estimated combined selectivity, not per-dimension
  selectivity; correlation between dimension predicates (country and currency)
  makes independence estimates optimistic.
- Prefer robust plans: SIP/Bloom + hash pipeline degrades gracefully; index
  nested-loop / Cartesian strategies have cliffs. OLAP optimizers target a
  good-and-robust plan, not the cheapest on paper.
- Join elimination: drop a dimension whose only use is the join key (needs
  trusted FK and uniqueness of the PK).
- Aggregate navigation before star planning: if an aggregate answers the
  query, plan the star join over the aggregate instead (smaller fact).

## 8. Tests

- Equivalence: every strategy (hash pipeline, Bloom on/off, star
  transformation, Cartesian, bitmap join index, MV rewrite) returns identical
  multisets; adversarial NULL FKs, unknown members, outer joins.
- Bloom filters: assert zero false negatives via shadow exact sets in debug
  builds; measure realized FP rate vs configured.
- Bitmap structures: random Boolean expression trees evaluated on compressed
  vs uncompressed bitmaps; random run-length distributions; container
  boundary values (Roaring 4096-element threshold, 2^16 boundaries).
- Probe-order adaptivity: synthetic data with selectivities that change over
  the fact scan (sorted by date) — the adaptive order must switch.

Sources: EDBS — Bitmap Index p.311; Indexing of Data Warehouses p.1880; Join
Index p.2051; Star Index p.3703; Star Schema p.3703; Snowflake Schema
p.3520; Query Processing in Data Warehouses p.3039; Optimization and Tuning
in Data Warehouses p.2619; Parallel and Distributed Data Warehouses p.2644.
