# Index taxonomy and access paths

Precise vocabulary for index kinds, what each implies for the physical
design, and how an optimizer turns them into access paths with costs. The
cost-based search itself is `query-optimizer`; selectivity estimation is
`cardinality-and-statistics`; index advisors are `tuning-and-benchmarking`.

## 1. Definitions (made precise)

| Term | Definition | Consequence |
|---|---|---|
| Ordered file | records stored in pages in the order of some attribute(s) | a file has at most one physical order |
| Heap | file with no order | only secondary indexes possible |
| Primary (clustering) index | ordered index whose search key is the file's ordering attribute | at most one per file; need not be on the primary key |
| Secondary (non-clustering) index | ordered index on a non-ordering attribute | leaf entries point into arbitrary pages; one extra indirection per match |
| Dense index | every search-key value in the file has an index entry | required for secondary indexes; larger; maintained on every relevant update |
| Sparse (non-dense) index | entries for only some values, typically one anchor per data page | requires the file to be ordered on the key; tiny; the classic ISAM/primary form |
| Unique index | at most one entry per key value (modulo NULL semantics) | doubles as constraint enforcement |
| Composite index | key is a list of columns, ordered lexicographically | usable for predicates on a leading prefix |
| Covering index (for a query) | contains every column the query references | index-only plan; base table never touched |
| Partial / filtered index | only rows satisfying a predicate are indexed | small; usable only when the query predicate implies the index predicate |
| Expression / functional index | key is an expression over columns | query must use the same (normalised) expression |
| Index-organized table / clustered index (alternative 1) | the index leaves are the rows | table and primary index are one structure |

Entry alternatives (Ramakrishnan & Gehrke naming): (1) the data record
itself; (2) (key, RID); (3) (key, RID-list). Alternative 1 is always
clustered; 2 and 3 are clustered only if the file happens to be ordered on
the key.

Relationships worth asserting in a catalog validator:
* clustered + ordered file on key => a sparse index is sufficient;
* secondary => dense (a sparse index over an unordered file cannot find
  unindexed values);
* B+-tree interior levels are sparse indexes over the level below; with
  alternative 2/3 the leaf level is a dense index over the table.

## 2. Row locators: physical vs logical

| Locator | Example | Pros | Cons |
|---|---|---|---|
| Physical RID (page, slot) | PostgreSQL heap TID, Oracle ROWID | one hop to the row | row movement (update to a larger size, reorganisation, clustered-index page split) must update every secondary index or leave a forwarding stub |
| Logical key (primary/clustering key) | InnoDB secondary indexes store the PK | clustered-index splits never touch secondary indexes | every secondary lookup is two tree descents; wide PKs bloat every secondary index |
| Surrogate row id + mapping | column stores, some MPP engines | stable ids, compact | an extra mapping structure |

> **Beyond EDBS:** PostgreSQL's heap-only tuple (HOT) updates avoid creating
> new index entries when no indexed column changes and the new version fits
> on the same heap page: the index keeps pointing at the chain root. This is
> the main mitigation of physical-locator write amplification. PostgreSQL's
> index-only scans must still consult the visibility map, falling back to the
> heap for pages not marked all-visible, because index entries carry no MVCC
> visibility information.

## 3. ISAM (static multi-level sparse index)

Three areas: sorted data file, index file (multi-level sparse index, one
entry per page of the level below), overflow area. Search descends
O(log_B(n/B)) levels; range adds O(a/B) sequential pages; index space is
O(n/B^2) pages. Inserts land in overflow chains hanging off the target data
page; deletes leave holes; the index never changes until reorganisation.
Replaced by VSAM (splits) and then B+-trees. Details and the B+-tree
contrast: btree-engineering.md section 8.

## 4. Access paths

An access path is a way to produce the tuples of one relation that satisfy
the local predicates: a sequential scan, or an index scan whose index
"matches" some predicate (Selinger et al. 1979).

Matching rules for an ordered composite index on (a, b, c):
* sargable predicates of form `col op constant` (or a bound parameter);
* matching prefix: equalities on a, then a, b; at most one range predicate,
  on the first column after the equality prefix; predicates on later
  columns become index filters (evaluated on index entries, reduce heap
  fetches, do not narrow the scanned range);
* `IN` lists on a leading column expand into multiple ranges (MDAM-style);
* an index also matches ORDER BY / GROUP BY / merge-join requirements on a
  key prefix (interesting order), even with no predicate.

A hash index matches only equality on all of its key columns.

> **Beyond EDBS:** Index skip scan (Oracle; MySQL 8.0; PostgreSQL 18 B-tree
> skip scan) uses a composite
> index when the leading column is unconstrained but has few distinct
> values, by iterating its distinct values and probing the rest of the key.

### Cost formulas (page I/O; P = table pages, N = rows, s = selectivity, h = index height, Lp = index leaf pages)

| Path | Cost | Notes |
|---|---|---|
| Full scan | P (sequential) | baseline; benefits from prefetch, zone maps, parallelism |
| Clustered index range | h + s Lp + s P | rows contiguous |
| Unclustered index, fetch per entry | h + s Lp + s N (random) | each match may be a separate random page read |
| Unclustered, RIDs sorted first (bitmap heap scan) | h + s Lp + P (1 - (1 - 1/P)^(sN)) | Cardenas' estimate of distinct pages touched; pages read in physical order |
| Index-only (covering) | h + s Lp | requires visibility handling under MVCC |
| Index intersection (AND of RID sets) | sum over indexes of (h + s_i Lp_i) + fetch(s_1 s_2 ... N) | RID-set AND via bitmaps or sort-merge |

EDBS measures an access path's "selectivity" as the count of index and data
pages it reads, so the "most selective" path is the one touching the fewest
pages: note the clash with predicate selectivity (fraction of rows).

Crossover intuition: an unclustered index with per-entry fetch beats a full
scan only while s N c < P, where c is the random/sequential cost ratio. With
100 rows per page and c = 10 the break-even selectivity is ~0.1%. Sorting
RIDs before fetching moves the break-even up by bounding the fetch cost at
P. This is why optimizers that misestimate s by 10x pick catastrophic index
plans (`cardinality-and-statistics`).

Example (secondary vs primary, from the entries): fetching 1,000 employees by
an ssn range through a secondary index can cost ~1,000 page reads; if the
file were ordered on ssn, the same 1,000 rows would occupy a handful of
pages.

## 5. Covering indexes and index-only plans

* A covering index lets the plan answer from index leaves alone. Benefits:
  fewer pages, sequential leaf scans, no heap random I/O.
* Cost: every extra column widens leaves (fewer entries per page, deeper
  tree), increases update cost, and duplicates storage. Very wide "cover
  everything" composite indexes can perform worse than a scan.
* Guidelines from the entry: build covering indexes for frequent queries
  only; extend an existing index (add columns) rather than creating an
  overlapping new one.
* Non-key included columns (SQL Server INCLUDE; PostgreSQL 11+ INCLUDE)
  store payload columns in leaves only: interior nodes stay small, and the
  included columns do not affect uniqueness or order.
* With logical locators (InnoDB), the PK columns are implicitly part of every
  secondary index, so "covering" includes them for free.
* Index intersection (SQL Server; also DB2 dynamic bitmaps, PostgreSQL
  BitmapAnd) builds a transient structure from several single-column indexes,
  which is sometimes loosely called a covering index: the optimizer combines
  RID sets or joins index entries on RID to supply all needed columns.

## 6. Unique indexes and constraint enforcement

* Check-and-insert must be atomic with respect to concurrent inserters of
  the same key: hold the leaf latch across "search for key" and "insert",
  plus a key lock (or wait on the in-progress inserter) for transactional
  isolation (`concurrency-control-theory`).
* Under MVCC the check must consider versions that are not yet committed or
  not yet garbage: a key deleted by an uncommitted transaction still blocks;
  a key inserted by an in-progress transaction forces a wait (PostgreSQL
  waits for the other transaction's outcome).
* NULLs: under the SQL standard, NULLs are distinct, so a unique index
  allows many NULL keys. SQL Server's unique index allows one NULL;
  PostgreSQL 15 added `NULLS NOT DISTINCT`. Pick one semantics and test it.
* Deferred uniqueness (checked at statement end or commit) is needed for
  updates like `SET k = k + 1`; implementing it means tolerating temporary
  duplicates in the index and re-checking later (`sql-semantics-and-active-rules`).
* Unique-by-construction keys (appending RID to non-unique keys) are an
  internal device; do not confuse them with declared uniqueness.

## 7. Index kinds by query class (catalog of this skill)

| Query class | Structures | Reference |
|---|---|---|
| Equality only | external hashing (static, extendible, linear) | hashing-schemes.md |
| Equality + range + order, 1-D | B+-tree, ISAM (static), learned index (read-mostly) | btree-engineering.md |
| Low-cardinality predicates, ad hoc conjunctions, warehouse | bitmap (equality/range/interval/bit-sliced), compressed | bitmap-and-join-indexes.md |
| Precomputed joins / star schemas | join index, star index, bitmapped join index | bitmap-and-join-indexes.md |
| Words, phrases, ranking | inverted file | text-and-string-indexes.md |
| Arbitrary substrings | suffix tree/array, FM-index | text-and-string-indexes.md |
| String keys, prefixes, in-memory ordered | trie, PATRICIA, ART | text-and-string-indexes.md |
| Probabilistic pre-filter | Bloom filter, signature file | bloom-filters.md |
| Multidimensional, spatial, similarity | R-tree, grid file, UB-tree, LSH, HNSW | `multidimensional-and-similarity-indexing` |

Three costs characterise every access method: query I/O, update I/O, space.
The B+-tree is logarithmic for the first two and linear in space; hashing
trades ordered access for expected O(1) probes; bitmaps trade update cost for
CPU-efficient conjunctive filtering.

> **Beyond EDBS: Teradata vocabulary.** In Teradata the Primary Index is the
> row-distribution key: the row hash of the PI columns selects the AMP, and
> rows within an AMP are kept in row-hash order (optionally partitioned, PPI),
> so a PI is a hash-distribution and access mechanism rather than an ordered
> clustered B+-tree. Unique secondary indexes (USI) are hash-distributed
> subtables (typically a two-AMP access); non-unique secondary indexes
> (NUSI) are AMP-local subtables (all-AMP probe unless combined with the PI).
> Join indexes and hash indexes are materialised structures maintained by the
> system (see bitmap-and-join-indexes.md section 9). Always restate which
> meaning of "primary index" a design uses.

## 8. Pitfalls

* Treating "primary index" as "index on the primary key": the defining
  property is file order (and in some systems, distribution).
* Sparse index on a file that later loses its order (heap inserts appended
  out of order): lookups silently miss rows. Assert file order or
  disallow.
* Index-only scans returning rows invisible to the snapshot (MVCC
  visibility not checked).
* Using an unclustered index for a 20% range with per-row fetches.
* Partial index chosen for a query whose predicate does not imply the
  index predicate: an implication-prover bug, or a generic cached plan for
  `status = $1` reusing an index defined `WHERE status = 'open'` for other
  parameter values.
* Expression index unused because the query expression differs in casts or
  collation.
* Unique index check racing with a concurrent insert of the same key in a
  sibling leaf (keys equal to a separator).

## 9. Tests

* Plan-choice tests: for synthetic tables with known clustering factor and
  selectivity, assert the chosen access path (scan vs index vs bitmap vs
  index-only) flips at the expected crossover (`query-engine-testing`).
* Result-equivalence: force each access path via hints/knobs and compare
  results with a full scan for random predicates, including NULLs and
  boundary values of ranges.
* MVCC: index-only scans under concurrent updates and deletes, compared with
  heap scans in the same snapshot.
* Unique: concurrent inserters of the same key (exactly one succeeds), NULL
  semantics, deferred checks.
* Catalog invariants of section 1 asserted on every DDL.

Sources: EDBS "Access Path" (p.22), "Primary Index" (p.2798), "Secondary
Index" (p.3337), "Dense Index" (p.1045), "Sparse Index" (p.3558), "Covering
Index" (p.659), "Tree-Based Indexing" (p.4217), "Hash-Based Indexing"
(p.1683), "Indexed Sequential Access Method" (p.1854).
