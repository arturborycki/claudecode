# Array and multidimensional storage (MOLAP and array DBMSs)

"Multidimensional data" means two things in data management: (1) OLAP
aggregates over relational facts, and (2) arrays — sensor, image, simulation
and statistics grids. Both meet in the same physical problem: storing a
(possibly sparse) n-dimensional array so that range, slice and aggregation
queries touch as few storage units as possible. This file covers the array
model and language, chunked/tiled storage, sparse chunk encodings, array query
evaluation, tertiary storage, scientific file formats, and the MOLAP vs ROLAP
vs HOLAP physical trade-off.

## 1. Array model

An array is a function a: X → F where X ⊂ Z^d is a finite axis-parallel
hyper-rectangle (the domain, e.g. [0:4095] × [0:2047]) and F is the cell type
(scalar or record, e.g. RGB). Cells are (position, value) pairs. Arrays are
**type constructors** (parameterized by dimensionality, domain and cell type),
not types — the reason deep integration (parser, optimizer, executor) beats
bolting arrays on as an opaque object-relational type.

### 1.1 Core operators (Array Algebra; ISO SQL/MDA style)

| Operator | Meaning | Example (pseudo-syntax) |
|---|---|---|
| Constructor | build an array over a domain from a per-cell expression of a position variable, with no defined iteration order | `mdarray [i(0:4095), j(0:2047)] elements 0.5 * a[i,j]` |
| Trim | sub-box, same dimensionality | `a[i(10:99), j(0:511)]` |
| Slice | fix a coordinate, dimensionality drops | `a[i(42), j(*)]` |
| Induced (lifted) ops | apply any cell operation element-wise; binary ops on equal domains | `a / 2`, `a.img - b.img`, `case when a > t2 then … end` |
| Condenser (aggregate) | combine cells over a domain with a commutative, associative operator | `aggregate max over [i(0:4095), j(0:2047)] using a[i,j]`; shorthands count_cells, add_cells, min, max, quantifiers |
| Combination | constructor whose cell expression contains condensers | histogram: `mdarray [b(0:255)] elements add_cells(a = b)` |
| Encode/decode | convert to/from external formats (TIFF, JPEG, NetCDF) | `encode(a[...], "image/tiff")` |
| Nest/unnest | array ↔ table (dimensions become columns and back) | bridge to relational processing |

Declarative = no explicit iteration order; that keeps queries safe (finite
evaluation) and gives the optimizer freedom to reorder, parallelize and
stream. Such array languages have the expressive power of relational
languages with ranking (Libkin, Machlin, Wong, SIGMOD 1996).

Standards: OGC Web Coverage Processing Service (WCPS, 2010) for geo
coverages; ISO SQL/MDA (ISO/IEC 9075-15) adds n-D arrays and the operators
above to SQL (being finalized when EDBS was written).

### 1.2 Integrating arrays with relations

| Approach | Description | Systems | Trade-off |
|---|---|---|---|
| Array-as-attribute | an array is a column value; set operations stay relational, array subexpressions in SELECT/WHERE | rasdaman, PostGIS Raster, Oracle GeoRaster, Teradata ARRAY/VARRAY, SQL ARRAY | scales to millions of arrays (one table); schema stays stable |
| Array-as-table | an array is a table-like object whose dimensions are index columns | SciQL, SciDB | relational-looking syntax; one catalog object per array → catalog bloat and schema changes on ingest |

Limits in practice: PostGIS Raster and Oracle GeoRaster are 2-D with fixed
cell types; Teradata arrays were limited to under 64 KB (as of the EDBS
entry); SciDB is a free-standing array DBMS relying heavily on UDFs.

## 2. Why neither plain tables nor BLOBs work

- Table R(x, y, v): tuple overhead per cell, and linearization destroys
  n-D proximity — a cut along x reads contiguous tuples, a cut along y reads
  scattered ones. Only very sparse data (statistics cubes) is well served by
  enumerating non-empty cells with coordinates — which is exactly why ROLAP
  works for OLAP facts.
- BLOB: the DBMS cannot address cells; compressing the BLOB forces whole-array
  decompression to read any element.
- SS-DB benchmark results reported array engines up to ~200x faster than
  relational technology on science workloads (handpicked queries; systematic
  benchmarks were still in progress).

## 3. Tiling / chunking

Partition the array into n-D sub-arrays — **tiles** (rasdaman) or **chunks**
(Sarawagi & Stonebraker, ICDE 1994) — that are the unit of storage access,
compression, caching and parallelism.

### 3.1 Tiling strategies

| Strategy | Description | Use |
|---|---|---|
| Regular (aligned) | equal-size, grid-aligned chunks | default; trivial addressing (chunk id = ⌊pos / extent⌋ per axis) |
| Arbitrary tiling (Furtado & Baumann, ICDE 1999) | tiles need not be aligned or equal | adapt to data and workload |
| Directional | specify ratios of edge extents rather than sizes | balance mixed workloads (spatial slices vs long time series) |
| Area-of-interest | declare hot regions; system derives tiling that isolates them | known hot spots |
| Two-level (SciDB) | small chunks grouped into containers | decouple I/O unit from processing unit |
| Overlapping chunks (ArrayStore, Soroush et al., SIGMOD 2011; SciDB) | chunks replicate a halo of neighbouring cells | stencil/convolution operations avoid reading neighbours |

### 3.2 Cost model for choosing chunk shape

For a query box with extents q_i and regular chunks with extents c_i, the
number of chunks touched is at most Π_i (⌈q_i / c_i⌉ + 1) (the +1 for
misalignment); bytes read ≈ chunks × chunk volume × cell size. Read
efficiency = query volume / volume read. Choose c to maximize expected
efficiency over the workload's query-shape distribution under a chunk-size
constraint (big enough to amortize per-access latency, small enough not to
over-read): disk-oriented tile sizes of roughly 64 KB–1 MB are typical (as
used in rasdaman); object storage favours several MB.

Worked example: x/y/t satellite data cube; ingestion arrives as t-thin x/y
slices; time-series queries ask for small x/y windows over long t. Chunks
1024×1024×1 make each time-series query touch one chunk per time step;
chunks 64×64×256 make it touch ⌈T/256⌉ chunks while slice extraction touches
(1024/64)² = 256 chunks per slice. Directional tiling picks ratios between
these; many systems ingest in slice-shaped chunks and **re-tile** in the
background.

### 3.3 Locating chunks

A spatial index over chunk boxes (R-tree; rasdaman's RC-tree) answers "which
chunks intersect the query box". Easier than general spatial indexing: chunks
are boxes partitioning a space of known extent, so nearly any spatial index
performs well; regular tiling needs only arithmetic. Within a chunk, the cell
linearization (row-major vs Z-order/Hilbert) determines locality for
sub-chunk accesses.

### 3.4 Compression

Compress per tile (so random access remains at tile granularity): run-length
for large constant regions and empty cells, delta/predictive coding for
smooth fields, general-purpose codecs on top. Dehmel (2002) studied a
compression engine for array DBMSs.

## 4. Sparse arrays and MOLAP chunk encodings

OLAP cubes are sparse, increasingly so with more dimensions and finer grains.
Chunk-based MOLAP (Zhao, Deshpande, Naughton 1997, "ArrayCube") stores:

- empty chunks: not stored;
- dense chunks: plain arrays (position encodes coordinates — no dimension
  values stored per cell, the MOLAP advantage);
- sparse chunks: **chunk-offset compression**: (offset-within-chunk, value)
  pairs.

Break-even density for a chunk of N cells with n non-empty, value size v and
offset size o: offset encoding is smaller when n/N < v/(o + v) (8-byte
values, 4-byte offsets → below ≈ 67% fill). A third option — values for
non-empty cells plus an N-bit occupancy bitmap — costs n·v + N/8 and wins in
the middle range; choose per chunk.

> **Beyond EDBS:** Essbase's block storage classifies dimensions as dense or
> sparse: combinations of dense dimension members form fixed-size blocks
> (arrays), and an index over sparse-dimension member combinations points to
> existing blocks only — a two-level chunking chosen by the cube designer.
> Microsoft Analysis Services exposes MOLAP, ROLAP and HOLAP as per-partition
> storage modes.

## 5. MOLAP vs ROLAP vs HOLAP (physical view)

| Criterion | MOLAP (chunked arrays) | ROLAP (star schema + aggregates) | HOLAP |
|---|---|---|---|
| Storage of coordinates | implicit (position) | explicit FK columns per row | detail explicit, aggregates implicit |
| Sparse data | needs chunking/compression; worst case blow-up | natural (store non-empty facts only) | detail sparse in ROLAP, aggregates dense enough for MOLAP |
| Aggregation / slicing speed | very fast (array arithmetic, MultiWay cubing) | depends on aggregates and indexes | fast for aggregated levels |
| Scale | limited by array sizes and rebuild time | scales with the RDBMS / MPP | detail scales, aggregates bounded |
| New dimension members | may force re-layout | insert rows | re-layout only for MOLAP part |
| Query language | MDX / proprietary | SQL (+ OLAP extensions) | both |
| Typical placement (EDBS) | data marts | enterprise warehouse | marts over EDW |

## 6. Array query evaluation

Rasdaman as a reference design:

- The relational "set tree" stays standard SQL; array subexpressions in
  SELECT/WHERE form separate **array subtrees**, which from the set tree's
  view are per-element expressions (like functions on any column type).
- Array subtrees evaluate by **tile streaming**: leaves read only tiles
  intersecting the requested domain and pass them upward; most array
  operators are non-blocking, so streaming reaches far up the tree.
- Blocking operators delimit subtrees that can be shipped to other cores,
  nodes or accelerators; array queries tend to be CPU-bound (unlike I/O-bound
  table scans), so **code shipping** and tile-parallel evaluation pay off.
- Algebraic rewriting (rasdaman applies on the order of 150 rules), e.g.
  `avg_cells(a + b) → avg_cells(a) + avg_cells(b)` for equal domains: two
  tile streams and scalar addition instead of materializing a + b; push
  trims/slices below induced operations; fold constants into lifted ops.
- Parallelism models: SciDB — coordinator with parallel UDFs over chunks
  distributed across instances; EXTASCID — dedicated parallel algorithms;
  rasdaman — peer federation without a single point of failure. In-situ
  processing over archive files avoids duplicating petabyte datasets.

Related algebras: gridfields for irregular/unstructured grids with algebraic
optimization (Howe & Maier, VLDB J 2005); map algebra for raster GIS;
Marathe & Salem (VLDB J 2002) on array query processing.

## 7. Tertiary storage and hierarchical storage management

Scientific arrays (climate simulations, satellite archives) reach hundreds of
TB to PB and live on tape robots behind an HSM. HEAVEN (Reiner, Hahn,
rasdaman) shows the key ideas:

| Problem | Technique |
|---|---|
| Tape positioning (≈20–180 s) ≫ disk (≈5–12 ms), but transfer rates comparable | maximize bytes per mount: transfer large units |
| Disk-optimal tiles (64 KB–1 MB) too small for tape | **super-tiles**: group tiles of one index subtree into one tape file; the access unit for import/export |
| Neighbourhood access patterns | intra-super-tile clustering (tiles of a subtree) and inter-super-tile clustering (write super-tiles in index order) |
| Repeated access | cache imported super-tiles in the DBMS (online area) with an LRU-variant eviction; HSM's own disk cache below |
| Data placement visibility | metadata records online (disk), nearline (robot tape) and offline (shelf) location; query execution imports transparently |

Query response then scales with the size of the query box rather than with
the size of the stored object. Earlier work: Sarawagi & Stonebraker (ICDE
1994) on chunking, reordering, redundancy and partitioning for tertiary
memory; Chen et al. (Inf Syst 1995) on organizing multidimensional datasets on
tertiary storage.

## 8. Self-describing scientific formats

HDF5 and NetCDF aim at random access to very large, heterogeneous,
self-describing, shareable, extensible, archivable data: hierarchies of
groups, n-D datasets with chunked storage and per-chunk compression, rich
attributes (metadata) and mixing of tables, images, instrument streams and
grids in one file. Challenges: concurrent random access to TB-scale files and
indexing beyond chunk boundaries (bitmap indexes such as FastBit and
multi-resolution bitmaps were developed for this).

> **Beyond EDBS:** NetCDF-4 is layered on HDF5. Zarr stores each chunk of an
> n-D array as a separate object in object storage with JSON metadata — the
> cloud analogue of HDF5 chunking. TileDB (Papadopoulos et al., PVLDB 2016)
> handles dense and sparse arrays with immutable write fragments consolidated
> later, the array counterpart of LSM/immutable-segment designs.

## 9. Future directions noted in EDBS

- Distributed and parallel array query processing as the top priority;
  adaptive re-partitioning and distribution.
- Linear/tensor algebra on massive arrays for statistics and ML.
- Safe iteration constructs with numerically defined termination — open
  research, unlike Datalog-style recursion with set semantics.
- Canonical benchmarks for array DBMSs.

## 10. Pitfalls

- Chunk shape fixed by ingest order while the query workload wants the
  orthogonal shape (no re-tiling path).
- Lifted binary operation on arrays with different domains or cell types
  without explicit alignment/resampling rules.
- Treating an overlapping chunk's halo as owned data (double counting in
  condensers).
- Whole-array decompression because compression was applied above tile
  granularity.
- MOLAP layouts that assume a fixed member list per dimension, breaking on
  new members (re-layout during business hours).

## 11. Tests

- Trim/slice/condense on random domains vs a naïve dense reference
  implementation; chunk-boundary-straddling queries; empty and single-cell
  domains.
- Tiling invariance: results identical across tiling strategies, chunk sizes
  and overlaps (halos excluded from aggregates).
- Rewrite equivalence for every algebraic rule (property tests over random
  arrays, including NaN and missing-value semantics).
- Sparse chunk encodings: round-trip and operator equivalence across density
  thresholds.
- Storage hierarchy: queries must return identical results whether data is
  online, nearline (forced import) or cached.

Sources: EDBS — Array Databases p.165; Storage of Large Scale Multidimensional
Data p.3746; Multidimensional Data Formats p.2327; Query Evaluation
Techniques for Multidimensional Data p.2986; Cube Implementations p.710;
Data Warehousing Systems: Foundations and Architectures p.916; Data Mart
p.793; Cube p.709.
