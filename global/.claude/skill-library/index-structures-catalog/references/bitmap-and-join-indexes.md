# Bitmap indexes, join indexes and star indexes

Bitmap representations of RID sets, the encoding design space, compressed
formats you can operate on without decompressing, and precomputed join
structures for warehouse schemas. Star-schema query planning and cube
machinery live in `olap-and-warehouse-engines`; join indexes as stored
materialized joins (Teradata sense) live in `materialized-views-ivm`.

## 1. Model

A bitmap index replaces each RID-list of a value index by a bit vector of
length N (rows), bit i set iff row i satisfies the property ("A = v",
"A <= v", "A in bin j").

Prerequisites that are easy to forget:

* **Dense row numbering.** Bit position must map to a row by arithmetic.
  Heap files with fixed max rows per page use `page * max_slots + slot`
  (wasting bits on short pages); column stores and append-only tables have
  natural ordinals. For index-organized/clustered tables, a mapping table from
  bit position to row locator is needed.
* **Existence bitmap** (or deleted-row bitmap): NOT and complement-based
  plans must be ANDed with it, otherwise deleted rows and never-used slots
  appear in results.
* **NULL bitmap**: `A <> 5` is not `NOT (A = 5)` under three-valued logic;
  it is `NOT(E5) AND NOT(Enull) AND Exists`.

Why bitmaps: AND/OR/XOR/NOT on machine words (64 rows per instruction, more
with SIMD), predictable sequential access, trivial parallelism (equal-length
vectors partition by row range), and COUNT via popcount without touching
rows.

Break-even versus RID lists (uncompressed, 32-bit RIDs): one value's bitmap
costs N bits, its RID list 32 x (sel x N) bits, so the bitmap is smaller when
selectivity > 1/32 (~3%). The whole equality-encoded index costs C x N bits
against 32 N for all RID lists, so it is smaller when column cardinality
C < 32. Compression moves both thresholds dramatically (section 5).

## 2. The design space (Chan & Ioannidis)

Two orthogonal choices: how a value is decomposed into digits, and how each
digit is encoded in bits.

**Decomposition.** Pick bases <b_n, ..., b_1> with product >= C; value v
becomes digits <v_n, ..., v_1> (mixed radix). One component per digit.
Base <C> is a single component (classic value-list index); base <2,2,...,2>
is the binary bit-sliced index.

**Encoding per component of base b:**

| Encoding | Bitmaps per component | Bit j of row is 1 iff | Point query | Range query |
|---|---|---|---|---|
| Equality (value-list, projection) | b | digit = j | 1 bitmap | OR of up to b/2 bitmaps (complement the smaller side) |
| Range | b - 1 (the all-ones one is implicit) | digit <= j | 2 (R_v AND NOT R_{v-1}) | 2 (R_hi AND NOT R_{lo-1}); one-sided: 1 |
| Interval (Chan & Ioannidis 1999) | ceil(b/2) | digit in [j, j + ceil(b/2) - 1] | <= 2 | <= 2 |

Interval encoding matches range encoding's worst case of two bitmap scans
with about half the bitmaps, which is why it dominates range encoding on the
space-time frontier for single-component indexes.

Single-attribute sizes for C = 1000:

| Index | Bitmaps | Worst-case bitmaps read, arbitrary range |
|---|---|---|
| Equality, base <1000> | 1000 | ~500 |
| Range, base <1000> | 999 | 2 |
| Interval, base <1000> | 500 | 2 |
| Range, base <10,10,10> | 27 | ~2 per component, combined across components |
| Binary bit-sliced, base <2^10> | 10 | all 10 (plus bookkeeping bitmaps) |

Other points in the space: K-of-N encoding (each value gets a distinct
N-bit code with exactly K ones; fewer bitmaps than equality, more reads per
point query); encoded bitmap index (Wu & Buchmann 1998: a lookup table maps
values to bit codes chosen so that frequent predicates reduce to few
bitmaps; binary BSI is the identity mapping); DB2's encoded vector index (the
same codes stored row-wise as one vector of short codes, scanned with
comparisons rather than bitmap ops); superimposed coding for set-valued
attributes (see bloom-filters.md, signature files).

## 3. Query evaluation

### Equality-encoded

* Conjunction of point predicates on different columns: AND their bitmaps.
* IN-list / range on one column: OR the member bitmaps; if the range covers
  more than half the domain, OR the complement set and NOT the result (then
  AND with existence).
* COUNT(*): popcount of the final bitmap; never fetch rows.

### Range-encoded comparison

```
A <= v  : R_v
A <  v  : R_{v-1}
A =  v  : R_v AND NOT R_{v-1}
A >  v  : NOT R_v           (AND exists AND NOT null)
lo <= A <= hi : R_hi AND NOT R_{lo-1}
```

Multi-component range-encoded indexes evaluate a comparison digit by digit
from the most significant component, combining "strictly less in a higher
digit" with "equal in higher digits and less-or-equal in this one"; Chan &
Ioannidis give the algorithms and their cost.

### Bit-sliced index (BSI) comparisons (O'Neil & Quass 1997)

Slices B_{k-1} .. B_0 hold the binary digits of each row's value. Compare
against constant c:

```
LT = 0; GT = 0; EQ = existence
for i = k-1 downto 0:
    if bit i of c == 1:
        LT = LT OR (EQ AND NOT B_i)
        EQ = EQ AND B_i
    else:
        GT = GT OR (EQ AND B_i)
        EQ = EQ AND NOT B_i
# A < c : LT ;  A <= c : LT OR EQ ;  A > c : GT ; A >= c : GT OR EQ
```

Cost: k slices read, ~4k word-parallel ops; independent of selectivity.

### BSI aggregation

* SUM(A) over found set F = sum_i 2^i x popcount(B_i AND F).
* MIN/MAX: walk slices from the top, keeping rows that have the bit when
  any such row exists in the candidate set.
* Median / quantiles: same walk with counts.
* Addition and subtraction of two BSIs slice by slice with a carry bitmap
  (Rinfret, O'Neil & O'Neil 2001) enable expressions like
  SUM(price x qty) for small domains and top-k by score.

## 4. High cardinality: binning and multi-resolution

* **Binning / range-based bitmaps:** one bitmap per value range, not per
  value. Lossy: rows in edge bins must be re-checked against the base data
  (candidate check). Bin boundaries tuned to data and query distributions
  minimise candidate checks (Koudas 2000; Rotem, Stockinger & Wu 2005).
  Order-preserving bin-based clustering (OrBiC; Wu, Stockinger & Shoshani
  2008) stores base data clustered by bin so that candidate checks read
  contiguous data.
* **Multi-resolution** (Sinha & Winslett 2007): a coarse binned level plus a
  fine per-value level; answer the interior of a range from coarse bitmaps
  and the edges from fine ones, avoiding candidate checks altogether.
* Compression (next section) is the other answer: WAH-compressed equality
  bitmaps were shown to stay efficient even for high-cardinality columns
  (Wu, Otoo & Shoshani 2004), because total compressed size is bounded by the
  number of set bits.

## 5. Compression you can compute on

Generic compressors (LZ-family) shrink bitmaps but force full decompression
before every logical operation. Run-length hybrids allow operations directly
on the compressed form.

### BBC (Byte-aligned Bitmap Code; Antoshenkov 1995, Oracle)

Byte-aligned runs: a header byte describes a fill (run of identical bytes of
0x00 or 0xFF, length in bytes) followed by a short tail of literal bytes;
several header forms (four run types) cover short/long fills and the
"single odd bit" case. Byte alignment means a literal byte is never split
during an operation.

### WAH (Word-Aligned Hybrid; Wu, Otoo & Shoshani 2006)

With word size w (32), the bit sequence is cut into groups of w - 1 = 31 bits.

```
literal word : MSB = 0, low 31 bits = one group verbatim
fill word    : MSB = 1, next bit = fill value, low 30 bits = number of
               consecutive all-0 or all-1 groups
```

Only two word types, all decisions on whole words. Two compressed operands
are combined by a merge that consumes runs: fill x fill yields a fill of
min length; fill x literal yields literals (or a fill when the fill is the
absorbing value, e.g. 0-fill AND anything); literal x literal is one word op.
Time is O(|A| + |B|) in compressed words. Rule of thumb from the
literature: WAH operations are faster, BBC compresses tighter.

### Reordering

RLE compresses runs, so row order matters. Sorting rows lexicographically
on the indexed columns, or using Gray-code ordering (Pinar, Tao &
Ferhatosmanoglu 2005), greatly shortens bitmaps; optimal ordering is
NP-hard (TSP-like heuristics are used for general Boolean matrices). Encoded
indexes (range, interval, BSI) have high bit density and compress poorly;
compression favours equality encoding.

### Hybrid segment formats

Model 204's original bitmaps already mixed representations per fixed-size
segment: dense segments as verbatim bits, sparse ones as RID lists.

> **Beyond EDBS: Roaring bitmaps** (Chambi, Lemire, Kaser & Godin, 2016;
> run containers added by Lemire, Ssi-Yan-Kai & Kaser, SPE 2016; library
> paper Lemire et al. 2018). The 32-bit row space is split
> by the high 16 bits into chunks of 65,536 rows. Each non-empty chunk
> stores one container: an **array** container (sorted uint16 values, used
> while cardinality <= 4096, i.e. <= 8 KiB), a **bitmap** container (8 KiB,
> 65,536 bits), or a **run** container (sorted (start, length) pairs). The
> 4096 threshold is exactly where the array stops being smaller than the
> bitmap. Operations dispatch on the container pair (array x array via merge
> or galloping intersection, bitmap x bitmap via word ops with SIMD, etc.).
> Advantages over WAH/EWAH/Concise: random access and membership in O(log)
> of chunk count, fast intersections of sparse sets, no pathological slowness
> for scattered bits. RLE formats can still win on very long runs of sorted
> data. Roaring is the de facto format in Lucene, Druid, Spark, ClickHouse and
> many others, with 64-bit variants for larger row spaces. Default choice for
> a new engine.

> **Beyond EDBS:** EWAH (Lemire, Kaser & Aouiche 2010) is a WAH variant that
> stores a run header followed by a counted block of literal words, enabling
> skipping; the same paper shows that sorting rows improves word-aligned
> bitmap compression substantially.

## 6. Updates and concurrency

* Each inserted row touches one bitmap per indexed column (equality
  encoding) but up to b - 1 bitmaps in range encoding: encodings that make
  reads cheap make writes expensive.
* Compressed bitmaps cannot be patched in place cheaply; appending at the
  end is cheap, changing the middle forces re-encoding of a segment.
* Common practice in warehouses: drop, bulk load, rebuild. Alternatives:
  append-only delta bitmaps plus a deleted-row bitmap merged periodically
  (LSM-like); "update-conscious" padding words that pre-encode future rows
  as zeros so an append touches only the target bitmap (Canahuate, Gibas &
  Ferhatosmanoglu 2007).
* Concurrency trap: one compressed bitmap entry covers many rows, so a lock
  on that entry blocks unrelated writers. Oracle documents bitmap indexes as
  unsuitable for high-concurrency DML for this reason. Key-range locking over
  bitmap segments is the theoretical fix (`concurrency-control-theory`).

## 7. Bitmaps built at query time

Systems without persistent bitmap indexes still use bitmaps as an execution
device:

* PostgreSQL (since 8.1) bitmap index scan: each index condition produces a
  TID bitmap; bitmaps are ANDed/ORed; the heap is then visited in physical
  order. When the bitmap exceeds working memory it degrades to page-level
  ("lossy") bits, which forces re-checking the predicate on every tuple of
  those pages.
* DB2 builds dynamic bitmaps from B-tree RID lists to AND index results and
  for star joins; SQL Server's index intersection builds a hash structure from
  several single-column indexes, effectively a transient covering index.
* Sorting RIDs before fetching (the main benefit) turns random heap I/O into
  a sequential sweep; see index-taxonomy-and-access-paths.md for the cost
  formula.

## 8. Join indexes (Valduriez 1987)

A join index for R join_p S is the set of RID pairs {(r, s)} whose records
satisfy p. It is a precomputed projection of the join onto row identifiers.

Organisations:

| Layout | Supports | Notes |
|---|---|---|
| Pair list clustered on r | R-driven joins, semijoin R |x S | B+-tree keyed by r |
| Pair list clustered on s | S-driven joins | often both copies are kept |
| Value-based (equijoin): join value -> (R RIDs, S RIDs) | both directions | one entry per distinct join value |
| Bitmapped join index (O'Neil & Graefe 1995) | star joins | for each s (or each dimension attribute value), a bitmap over R's rows |

Using it: scan the join index (small, sequential), then fetch the needed
columns from R and S. The fetch is the expensive part; Li & Ross (1999)
give Jive-join and Slam-join, which partition and sort the RID pairs so each
base table is read in one (or few) sequential passes.

Maintenance: every insert/delete in R or S must find its join partners
(itself a join probe) and update the pairs; cost is that of incremental view
maintenance of a two-table join (`materialized-views-ivm`).

## 9. Star index and bitmapped star joins

A star index is the collection of join indexes for every foreign-key join of
a star (or snowflake) schema: fact table F, dimensions D_1..D_n. With bitmap
join indexes:

```
for each dimension D_j with a predicate:
    S_j = OR over qualifying dimension keys d of Bitmap_Fk_j[d]     # or a bitmap join index on D_j.attr directly
F_rows = AND_j S_j  (AND existence)
fetch facts in RID order; join back to dimensions only for projected columns
```

This is the "star transformation": the fact table is never scanned in full,
and per-dimension work is proportional to the qualifying dimension keys.
Oracle exposes bitmap join indexes defined over fact x dimension so the
dimension attribute (e.g. `region = 'West'`) maps directly to a fact-row
bitmap, skipping the dimension lookup. Snowflake schemas chain the same idea
through outrigger tables. Red Brick Warehouse shipped star indexes in the
1990s.

> **Beyond EDBS:** Vocabulary clash. In Teradata, a "join index" is a
> persistent, optionally aggregated, optionally sparse (filtered) materialized
> result of a multi-table join (or a single-table projection), maintained
> automatically and chosen by the optimizer. It is a materialized view, not a
> Valduriez RID-pair structure. Review designs with the definition stated.

## 10. Pitfalls

* NOT without AND existence: deleted rows reappear.
* NULLs folded into the zero value of a BSI: `SUM` correct, `A < 1` wrong.
* Comparing bitmaps with different lengths (rows appended after one bitmap
  was materialised): define the implicit tail as zeros and make every
  operation length-aware.
* Using range encoding on a write-heavy column: every insert updates half
  the bitmaps on average.
* Bitmap index on a high-cardinality, frequently updated OLTP column:
  lock contention and rebuild cost dominate.
* Bitmapped join index silently stale after dimension key update: dimension
  keys must be immutable surrogates or maintenance must cover updates.

## 11. Testing

* Oracle: brute-force predicate evaluation over the base rows for random
  predicates (point, range, IN, NOT, IS NULL, combinations) and every
  encoding; compare bitmaps bit for bit.
* Compressed ops: property test `decompress(op(compress(a), compress(b))) ==
  op(a, b)` over random, all-zero, all-one, alternating, long-run and
  single-bit inputs, with lengths not divisible by 31/32/64/65536.
* Aggregates on BSI versus SUM/MIN/MAX on base data, including negative
  values (offset or two's-complement slice handling) and NULLs.
* Star join via bitmaps versus hash join plan on the same data.

Sources: EDBS "Bitmap Index" (p.311), "Bitmap-Based Index Structures" (p.316),
"Join Index" (p.2051), "Star Index" (p.3703), "Covering Index" (p.659, index
intersection).
