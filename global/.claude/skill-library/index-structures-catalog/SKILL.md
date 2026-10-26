---
name: index-structures-catalog
description: "Use when choosing, implementing or reviewing one-dimensional and text index structures at implementation depth: index taxonomy (clustered vs secondary, dense vs sparse, covering, unique), ISAM, B+-tree engineering (bulk load, fill factor, key truncation, merge policy, B-link), external hashing (static, extendible, linear), bitmap indexes and their encodings and compression, join and star indexes, tries/ART, suffix trees/arrays, FM-index, inverted files, signature files, Bloom filters. Triggers on clustered index, covering index, index-only scan, fill factor, bulk load, online index build, suffix truncation, extendible hashing, linear hashing, split pointer, bit-sliced index, WAH, Roaring, bitmap join index, posting list, variable-byte, PForDelta, skip pointers, suffix array, BWT, Bloom filter false positive rate, bits per key. Apply even when phrased as 'which index should this column get', 'why is this lookup slow' or 'make the filter smaller'."
---

# Index Structures Catalog

This skill owns the access-method catalog below the optimizer: structures
that map a key, word, substring or predicate to row locators, and the
engineering that makes each fast, compact and correct. The governing idea:
**choose the structure by query class and update pattern, then make every
invariant machine-checkable** — ordered trees for ranges, hashing for
equality only, bitmaps for low-cardinality conjunctions, inverted files for
words, suffix structures for substrings, filters to skip work. Most real bugs
sit at boundaries: separator equality, split pointer, existence bitmap, hash
identity.

## Mental model

* Index = (key -> locator) organisation + maintenance policy, judged by three
  costs: query I/O, update I/O, space. Locators are physical (page, slot) or
  logical (clustering key); that choice decides who pays on row movement.
* Ordered (ISAM, B+-tree, trie/ART, learned) give ranges, prefixes and
  interesting orders; hashing gives one-probe equality and nothing else;
  bitmaps turn predicates into word-parallel boolean algebra over row
  positions; text indexes add tokenisation (inverted files) or substring
  semantics (suffix arrays, FM-index).
* Static structures (ISAM, static hashing, suffix arrays, SSTable block
  indexes) are rebuilt; dynamic ones (B+-tree, extendible/linear hashing)
  grow locally. Immutable runs (LSM, Parquet, search segments) have made
  static structures the default again.
* Filters (Bloom, signature files) prove absence. Their contract is "no false
  negatives"; a false negative is a correctness bug.

## Core invariants

1. **B+-tree order**: keys of subtree(P_i) lie in [K_i, K_{i+1}); one
   separator convention shared by search, split, merge and unique checks;
   in-node fence keys equal the parent's bracketing separators.
2. **Balance/occupancy**: all leaves at one depth; non-root nodes meet the
   declared minimum of the chosen merge policy; interior root has >= 2 children.
3. **Leaf chain / B-link**: links visit each leaf once in key order; a node's
   high key bounds its keys and its right link reaches the node whose low
   fence equals it.
4. **Splits**: leaf split copies up the first right key or a separator s with
   last_left < s <= first_right; interior split moves the middle key up.
5. **Sparse needs order**: anchor-per-page indexes are valid only on a file
   ordered by the key; secondary indexes are dense.
6. **Extendible hashing**: a bucket of local depth d' has exactly 2^(d-d')
   directory slots, all agreeing on d' hash bits.
7. **Linear hashing**: buckets = N0 x 2^i + p; addr(k) = h_{i+1}(k) iff
   h_i(k) < p else h_i(k); h_{i+1} sends h_i-bucket j to j or j + N0 x 2^i.
8. **Hash identity persists**: hash function, seed and key normalisation are
   stored and versioned with every hash index and filter.
9. **Bitmap safety**: every NOT is ANDed with existence and NULL bitmaps;
   decompress(op(c(a), c(b))) == op(a, b) for every codec and op.
10. **Postings**: doc ids strictly increase per list (or per equal-impact
    run); each skip entry's (doc id, offset) decodes to exactly that posting.
11. **Filters**: query(x) holds for every inserted x across serialisation,
    upgrade and concurrent insert, using the query-time key form.
12. **Unique and online build**: check-and-insert is atomic per key and sees
    uncommitted inserters/deleters; an online build reflects each change
    exactly once relative to one cut and stays invisible to the planner
    until validated.

## Design space & trade-offs

| Need | Structure | Wins when | Cost / risk |
|---|---|---|---|
| equality + range + order | B+-tree | OLTP default, most secondaries | write amplification per index; root/right-edge hot spots |
| equality only, extreme probe rate | extendible / linear hashing | long keys, uncacheable interior levels | no order; skew -> chains or directory blow-up |
| read-only sorted run | ISAM-style sparse index, learned index | SSTables, segments, bulk files | rebuild on change |
| low-cardinality conjunctions, COUNT | compressed equality-encoded bitmaps | warehouses, read-mostly | update cost; locks cover many rows |
| ranges / aggregates on bitmap columns | range, interval, bit-sliced encodings | wide ranges, SUM over BSI | more bitmaps touched per insert |
| precomputed joins | join, star, bitmapped join index | star schemas, stable dimensions | maintenance = incremental join |
| words, phrases, ranking | inverted file | natural-language text | analyzer drift breaks recall |
| arbitrary substrings | suffix array; FM-index/CSA if space-bound | logs, DNA, code, CJK | compressed locate is slow |
| in-memory ordered, binary keys | ART, B+-tree with OLC | main-memory engines | needs memcmp-comparable keys |
| prove absence | blocked Bloom; cuckoo/xor/ribbon | LSM runs, remote joins, row groups | key/hash mismatch -> false negatives |

Bitmap encodings for cardinality C (single component):

| Encoding | Bitmaps | Point query | Range query |
|---|---|---|---|
| Equality | C | 1 | up to C/2 (use complement) |
| Range | C - 1 | 2 | 2 |
| Interval | ceil(C/2) | <= 2 | <= 2 |
| Binary bit-sliced | ceil(log2 C) | all slices | all slices |

B+-tree defaults: suffix-truncated interior separators, prefix truncation via
fences, key+RID uniqueness (or dedup posting lists for low-cardinality
secondaries), monotone-insert edge splits, free-at-empty or low-threshold
merges with ghost records, fill factor 100% only for read/append-only (random
inserts settle near 69%). Posting codecs: block bit-packing (PFor-style,
SIMD) with per-block skips, or Elias-Fano in memory; gamma/delta/Golomb only
where space dominates decode speed.

## Algorithms that matter

```
Bloom sizing:   m = ceil(n * log2(1/eps) / ln 2)    # 9.6 bits/key for 1%
                k = round((m/n) ln 2); FPR = (1 - e^(-kn/m))^k
                probe_i = (h1 + i*h2) mod m          # one 128-bit hash
Linear hashing: addr(k): a = h_i(k); if a < p: a = h_{i+1}(k)
                split: add bucket p + N0*2^i, rehash bucket p with h_{i+1}, p++,
                       if p == N0*2^i: i++, p = 0     # trigger on load > threshold
Extendible:     full bucket: if local == global double directory; split only that
                bucket; redirect half of its 2^(d-d') slots; local++ on both; retry
Bulk load:      external sort (key, locator) -> pack leaves at fill factor ->
                parents from truncated first keys, bottom-up; O(sort) + 1 seq write
BSI A < c:      MSB->LSB keep LT, GT, EQ; SUM = sum_i 2^i * popcount(B_i AND F)
Inversion:      (term, doc, tf[, pos]) -> sorted runs -> k-way merge -> gap-coded
                lists + lexicon offsets; distribute by document partitioning
FM count:       backward search, 2 rank_c queries per pattern symbol; locate by
                LF-walking to sampled SA positions
```

## Failure modes & classic bugs

* Separator `<`/`<=` mismatch: keys equal to a separator unreachable;
  duplicates straddling leaves found partially; unique check misses a sibling.
* Variable-length keys split by count: the target half cannot absorb the key.
* 100%-fill bulk load then random inserts: split storm and latency cliff.
* Root split racing readers that cached the root id.
* Duplicate-heavy keys in extendible hashing: unbounded directory doubling;
  linear hashing `a <= p`: the just-split bucket's keys misrouted.
* Library upgrade changes hash or seed: persisted hash indexes and filters
  silently wrong.
* Bitmap NOT without existence AND (deleted rows reappear); NULLs matching
  `<>`; codec edge cases at lengths not divisible by 31/32/64/65536.
* Range-encoded bitmaps on write-hot columns; bitmap locks blocking OLTP.
* Analyzer drift; unpadded positions between fields create false phrases;
  skip offsets off by one.
* Bloom built over internal keys (sequence number, other prefix) but probed
  with user keys; filter sized for n holding 2n (1% becomes ~14%).
* Unclustered per-row fetch for a 20% range; index-only scan ignoring MVCC.
* Online build resurrecting keys deleted after the cut, or marked valid
  before uniqueness is proven.

## Implementation checklist (C/C++/Rust)

* One order-preserving memcmp-comparable key encoding (sign-flipped
  big-endian ints, NULL byte, escaped strings, collation keys); it enables
  truncation, inline key prefixes in slot arrays and ART.
* Nodes over `&[u8]` / `std::span<std::byte>` with explicit offsets and
  in-node fence keys; layout per `page-and-file-format`. Rust: arena/frame
  indices, not `Rc<RefCell>` parents. C++: RAII pin/latch guards; never keep
  a node pointer across latch release.
* Latching and SMO logging are delegated: `concurrency-control-theory`
  (coupling, B-link, OLC) and `recovery-and-durability` (system transactions).
* Hash entries carry the full 64-bit hash; buckets carry a split generation
  for stale-address detection; directory under a shared/exclusive latch.
* Bitmaps: Roaring (array/bitmap/run containers), 64-bit variant past 2^32
  rows, existence + NULL bitmaps, SIMD popcount, length-aware ops.
* Postings: separate doc/tf/position streams; per-block max doc id, offset
  and max score.
* Filters: blocked layout on disk, atomic fetch-or for concurrent builds,
  checksummed serialisation.
* Catalog records fill factor, codec, hash id/seed, analyzer version,
  NULL/unique semantics and build state (building, ready, valid).
* A `verify()` per structure, run after each SMO in debug builds and exposed
  as a CHECK INDEX utility.

## How to test it

* Model-based random operation streams against `BTreeMap` / `std::map` /
  hash sets, with `verify()` after every SMO; bulk-load vs incremental-build
  equivalence.
* Adversarial keys: all-equal, monotone up/down, insert/delete oscillation at
  a page boundary, maximal length, long shared prefixes, last-byte
  differences, keys equal modulo 2^j.
* Oracles: per-row predicate evaluation for bitmaps (every encoding),
  codec round-trip/op-equivalence properties, naive substring counting for
  suffix arrays and FM-index, document scans for inverted-file queries.
* Filters: zero-false-negative property; empirical FPR within tolerance of
  the formula, including sequential-integer keys.
* Crash injection at each split/merge/directory-doubling step; online build
  under concurrent writers vs snapshot scan; files from the previous release.

## Expert review questions

1. Which query classes must this index serve, and why is this structure the cheapest for them?
2. Physical or logical locators — who pays on row movement, and how much?
3. Where is the separator convention asserted in search, split, merge and unique checks?
4. What is the underflow policy, and does `verify()` encode it?
5. How are monotone inserts detected and split; what fill factor do bulk loads use?
6. Which key compression (prefix, suffix, dedup), and how does it interact with in-place updates and key-range locks?
7. Hashing: what happens with 10,000 duplicates of one key; where are hash id and seed persisted?
8. Bitmaps: which encoding and codec, how are deletes/NULLs handled, what does one insert cost in bitmaps and locks?
9. Text: analyzer version, posting codec, skip interval, TAAT or DAAT, delete handling?
10. Filters: which key form is hashed, bits/key and k, layout, observed vs predicted FPR?
11. Online build: what is the cut, how are racing deletes handled, how is uniqueness proven before validity?
12. Which statistics (clustering factor, distinct counts) does the optimizer get, and who maintains them?
13. How is the structure verified in production, and how long does a rebuild take at target size?

## Go deeper

* `references/index-taxonomy-and-access-paths.md` — index kinds, locators,
  covering/partial/unique semantics, ISAM, matching rules, access-path cost
  formulas, Teradata vocabulary.
* `references/btree-engineering.md` — invariants, node search, splits, merge
  policy, truncation, fill factor, B-link structure, bulk load, online build,
  Bw-tree and learned indexes.
* `references/hashing-schemes.md` — static, extendible, linear hashing; load
  control; pathologies; comparison with B+-trees.
* `references/bitmap-and-join-indexes.md` — encodings, BSI algorithms,
  binning, BBC/WAH/Roaring, updates and locking, join and star indexes.
* `references/text-and-string-indexes.md` — tries, PATRICIA, ART, suffix
  trees/arrays, BWT/FM-index/CSA, inverted files, posting compression.
* `references/bloom-filters.md` — Bloom math, layouts, variants, Bloomjoin,
  runtime and LSM filters, signature files.
* `references/edbs-entries.md` — the 25 EDBS entries with printed pages.

## Related skills

* `storage-and-indexing` — buffer pool and B-tree basics; this is the deeper catalog.
* `page-and-file-format` — node byte layout, slotted pages, checksums.
* `lsm-storage` — consumes per-run Bloom filters and sparse block indexes.
* `concurrency-control-theory` — latch coupling, B-link protocols, key-range locking, ghosts.
* `recovery-and-durability` — logging/recovery of SMOs and index builds.
* `multidimensional-and-similarity-indexing` — R-trees, grid files, UB-trees, LSH, HNSW/DiskANN.
* `query-optimizer`, `cardinality-and-statistics` — access-path choice and selectivity.
* `query-execution-advanced`, `join-algorithms` — index nested loops, bitmap heap scans, runtime join filters, external sort.
* `olap-and-warehouse-engines` — star transformation using bitmap/star indexes.
* `materialized-views-ivm` — join indexes as stored joins (Teradata sense).
* `beyond-relational-engines` — full-text engines, XML and graph indexes.
* `temporal-databases` — multiversion and time-split B-trees.
* `columnar-arrow-layout` — bit-packing/FOR encodings shared with posting codecs; zone maps.
* `parallel-database-systems`, `distributed-dbms-design` — local vs global indexes, distributed inverted files, LH*.
* `tuning-and-benchmarking` — index advisors, fill-factor and filter tuning.
* `storage-devices-and-io` — page size and flash effects on nodes and filters.
* `sql-semantics-and-active-rules` — deferred unique constraints, NULL semantics.
* `dbms-architecture` — where the access-method interface sits.

## Grounding

EDBS (Liu & Özsu, 2nd ed., 2018): Access Path p.22; B+-Tree p.247; Bitmap
Index p.311; Bitmap-Based Index Structures p.316; Bloom Filters p.320; B-Tree
Locking p.345; Covering Index p.659; Dense Index p.1045; Extendible Hashing
p.1429; Hash-Based Indexing p.1683; Index Creation and File Structures
p.1842; Indexed Sequential Access Method p.1854; Indexing Compressed Text
p.1861; Inverted Files p.2037; Join Index p.2051; Linear Hashing p.2093;
Primary Index p.2798; Secondary Index p.3337; Signature Files p.3491; Sparse
Index p.3558; Star Index p.3703; Suffix Tree p.3839; Text Index Compression
p.4075; Tree-Based Indexing p.4217; Trie p.4225.

Seminal: Bayer & McCreight 1972; Comer 1979; Bayer & Unterauer 1977 (prefix
B-trees); Lehman & Yao 1981 (B-link); Fagin et al. 1979 (extendible); Litwin
1980 (linear hashing); Valduriez 1987 (join indices); O'Neil & Quass 1997;
Chan & Ioannidis 1998/1999; Antoshenkov 1995 (BBC); Wu, Otoo & Shoshani 2006
(WAH); Bloom 1970; Morrison 1968 (PATRICIA); McCreight 1976; Ukkonen 1995;
Manber & Myers 1993; Ferragina & Manzini 2005; Grossi & Vitter 2005; Witten,
Moffat & Bell 1999; Zobel & Moffat 2006; Mohan & Narang 1992 (online build).
Beyond EDBS: Roaring (Chambi et al. 2016), ART (Leis et al. 2013), Bw-tree
(Levandoski et al. 2013), learned indexes (Kraska et al. 2018), Monkey (Dayan
et al. 2017), Elias-Fano (Vigna 2013).
