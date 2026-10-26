# Space-filling curves, grids, quadtrees and kd-trees

Read this when choosing a *space-partitioning* access method, mapping
multi-dimensional keys onto a B+-tree/LSM/sorted file, designing
clustering/data layout (Z-order, Hilbert) for a columnar or lakehouse table,
or implementing grid-file, quadtree or kd-tree variants.

---

## 1. Two families of partitioning

| | Data-driven (R-tree family, SS/M-tree) | Space-driven (grid file, quadtree, kd/K-D-B, z-order, Pyramid) |
|---|---|---|
| Region shape | adapts to data (MBRs, spheres) | fixed recursive decomposition of the domain |
| Overlap | allowed between siblings | regions disjoint (cells/quadrants) |
| Coverage | only populated space | whole domain, including empty space |
| Point query | may follow several paths | single path |
| Extended objects | stored once (MBR) | clipped/replicated, or stored at the smallest enclosing cell (MX-CIF) |
| Balance | height-balanced | often unbalanced (quadtree depth grows with point density) |
| Mapping to 1-D | Hilbert R-tree only | natural: cell codes = locational keys |

Space-driven schemes are attractive in engines because they **reuse existing
1-D machinery** — a B+-tree, an LSM tree, a sorted Parquet file, a hash
partitioner — with all its concurrency, recovery, compression and
statistics already solved.

---

## 2. Space-filling curves (SFCs)

A d-dimensional SFC over a grid of N cells per axis is a bijection between
the N^d cells and `[0, N^d)` visiting every cell once. Locality is the only
quality measure: cells near in space should be near on the curve, and a
query region should map to **few, long runs** of curve values.

### Curves

| Curve | Construction | Locality | Cost to compute |
|---|---|---|---|
| Row-major / scan | concatenate coordinates | terrible in all but the leading axis | trivial |
| Z-order (Morton, bit interleaving, N-order, quad code, locational code; EDBS calls it the "Peano SFC") | interleave the bits of the coordinates, MSB first | good but with large jumps at quadrant boundaries | bit shuffles (PDEP on x86 BMI2, or magic-number spreading) |
| Gray-code curve | interleave, then interpret as Gray code | fewer jumps than Z | cheap |
| Hilbert | recursive U-shape with rotations/reflections per quadrant | best clustering of the common curves: consecutive cells always adjacent | table-driven state machine, or Skilling's iterative transform; ~O(d·bits) |

Terminology warning: in most of the literature "Peano curve" means the
3×3-recursive curve; EDBS (Mokbel & Aref) uses "Peano SFC" for bit
interleaving. Say "Z-order/Morton" in code and docs.

**Z-order encoding (2-D, 32-bit coords → 64-bit key)**
```
spread(x): x = (x | x<<16) & 0x0000FFFF0000FFFF
           x = (x | x<<8)  & 0x00FF00FF00FF00FF
           x = (x | x<<4)  & 0x0F0F0F0F0F0F0F0F
           x = (x | x<<2)  & 0x3333333333333333
           x = (x | x<<1)  & 0x5555555555555555
z(x,y) = spread(x) | (spread(y) << 1)
```
Prefixes of a z-value of length 2k identify a quadtree cell at level k —
this is exactly the linear quadtree locational code.

### Quality measures

- **Clustering number**: number of maximal runs of consecutive curve values
  needed to cover a query region. Moon, Jagadish, Faloutsos, Saltz (TKDE
  2001) analysed Hilbert clustering and showed it grows with the query's
  surface area (not its volume), and that Hilbert beats Z-order.
- **Segment types** (Mokbel, Aref, Kamel 2003): count jumps (distance > 1
  in some dimension), contiguities, forward/reverse and still segments per
  dimension — a per-dimension fairness profile.
- **Irregularity** (Mokbel & Aref 2011): number of pairs visited in
  descending order of a coordinate; measures bias toward particular axes.
  A deliberately biased curve is useful when one dimension matters more
  (e.g. a deadline axis in an SFC-based disk scheduler).

### Range queries over an SFC-keyed B+-tree

Two strategies:

1. **Decompose the query box into curve intervals** — recursively split the
   box along the curve's quadrant structure, emitting maximal intervals;
   cap the number of intervals (merge small gaps) and post-filter. More
   intervals = fewer false positives but more seeks.
2. **Single scan with skipping** — scan from `z(lo)` to `z(hi)`; when the
   current key is outside the box, compute the next z-value inside the box
   (**BIGMIN**, Tropf & Herzog 1981; its dual LITMAX for descending scans)
   and seek there. This is how the UB-tree (Bayer; Ramsak et al., VLDB
   2000) answers range queries on a plain B+-tree of z-addresses.

Invariant to test: the union of decomposed intervals ⊇ the cells
intersecting the box, and post-filtering on the original coordinates yields
exactly the box contents.

kNN over an SFC: no direct algorithm with guarantees — common practice is to
use the curve to fetch a candidate neighbourhood, take the k-th distance as
radius, then run an exact range query of that radius (the same two-phase
pattern as multi-step kNN). Using several shifted curves reduces misses
(Liao, Lopez, Leutenegger, ICDE 2001).

### SFCs in query processing

- **Spatial join on z-values** (Orenstein SIGMOD 1986): approximate each
  object by the z-cells covering its MBR, sort both inputs by z-value and
  merge, treating a z-prefix as containing all its extensions; then refine.
  Grid granularity trades replication against approximation quality.
- **Bulk loading**: Hilbert-packed R-trees; PostgreSQL sorted GiST builds.
- **Moving objects**: Bx-tree and B^dual-tree linearise positions/velocities
  with an SFC into B+-tree keys (temporal file).
- **Scheduling**: map request attributes (cylinder, deadline, priority) into
  a multi-D space and serve requests in curve order (multimedia disk/NASD
  schedulers in the EDBS entry).

> **Beyond EDBS — data layout in columnar/lakehouse engines.** The most
> common use of SFCs today is clustering rows across files and row groups
> so that per-file min/max statistics skip data on predicates over several
> columns. Delta Lake (`OPTIMIZE … ZORDER BY`), Apache Iceberg
> (`rewrite_data_files` with a z-order sort strategy), Apache Hudi
> (z-order and Hilbert layout optimisation) and Amazon Redshift interleaved
> sort keys all apply this idea. Practical rules: (i) normalise or
> rank-transform each column before interleaving — interleaving raw values
> of very different domains lets the widest column dominate; (ii)
> effectiveness drops quickly beyond ~3–4 columns because each column gets
> only 1/d of the key's bits of resolution per level; (iii) Hilbert gives
> better file-level skipping than Z for the same file count but is costlier
> to compute; (iv) re-clustering is a rewrite — incremental schemes cluster
> only new data. Geospatial systems use the same idea at planetary scale:
> Geohash is Z-order on interleaved lat/long bits, Google S2 numbers cells
> along a Hilbert curve on the faces of a cube, and Uber H3 uses a
> hierarchical hexagonal grid; all three turn spatial predicates into
> covering sets of cell ids and an equi-join/prefix scan followed by exact
> refinement.

> **Beyond EDBS — learned and workload-aware layouts.** Flood (Nathan et
> al., SIGMOD 2020) learns a grid layout per workload; Qd-tree (Yang et
> al., SIGMOD 2020) learns a partitioning tree over predicates to maximise
> block skipping. Both beat fixed curves when the workload is stable; both
> need re-optimisation when it drifts.

---

## 3. Grid file (Nievergelt, Hinterberger, Sevcik, TODS 1984)

Multidimensional generalisation of extendible hashing, symmetric across
attributes.

- **Linear scales**: one sorted array of split points per dimension (small,
  kept in memory).
- **Directory**: d-dimensional array of cell → data-page pointers; several
  adjacent cells may share one page as long as the union of shared cells is
  a box (a *bucket region*).
- **Exact match**: scales locate the cell in memory → one directory page
  read → one data page read: **two disk accesses** worst case.
- **Range / partial match**: intervals on each scale select a sub-array of
  the directory; visit the distinct pages it references; filter records.

Insertion overflow:
```
if page shared by >1 cell: split the bucket region along an existing
    scale boundary; redistribute records between old and new page
else: add a new split point on one scale (round-robin or by data),
      which inserts a whole hyperplane of cells into the directory
      (all pointing to their previous pages), then split as above
```
Deletion: merge underfull buddy pages (buddy system keeps regions boxes);
remove scale entries when a hyperplane becomes redundant.

Weaknesses that matter to an engine builder:
- Directory size can grow **superlinearly** in the number of records for
  correlated or clustered data (each new split point creates a full
  hyperplane of cells); in high d the directory explodes.
- Splits touch many directory entries (update amplification).
- Correlated attributes leave most cells empty → poor utilisation.

Variants: BANG file (Freeston 1987, tree-structured directory over nested
regions), twin grid file (better utilisation), multilevel grid file,
parallel grid files with declustered pages across disks. The EDBS entry
notes the grid file was influential in research but not adopted
commercially; in practice its role is played by multi-level hash
partitioning and by SFC keys over B-trees.

---

## 4. kd-tree family

- **kd-tree** (Bentley, CACM 1975): binary search tree; level i splits on
  dimension `i mod d` at a data point. Main-memory structure; balance
  depends on insertion order.
- **Adaptive kd-tree**: split at the median along the dimension of greatest
  spread, data only in leaf buckets; static, built in O(n log n).
- **K-D-B-tree** (Robinson, SIGMOD 1981): paged kd-tree with region pages
  and point pages; height-balanced, but a split of an upper region page can
  force splits of children cut by the split plane (**downward cascade**),
  so no minimum utilisation guarantee.
- **hB-tree** (Lomet & Salzberg, TODS 1990): each index node holds a small
  kd-tree describing "holey bricks"; a split extracts a brick (possibly
  with holes) so that it never cascades downward and guarantees a 1/3–2/3
  balance; consequence: a node may have multiple parents (fixed by hB^Π).
- **LSD-tree** (Henrich, Six, Widmayer, VLDB 1989): kd-structured directory
  with local split decisions; the top of the directory is memory-resident
  and lower subtrees are paged out to keep it balanced.
- **Buddy tree, BV-tree** (Freeston 1995): balanced space-partitioning
  trees; the BV-tree promotes "guard" regions to restore B-tree-like
  guarantees for n-dimensional data.

Use: kd-trees dominate in-memory point workloads (KNN in ML libraries,
geometry kernels); K-D-B/hB-style trees are disk point access methods with
good worst-case behaviour.

---

## 5. Quadtree family

General principle: recursively split a region into 2^d equal sub-blocks
until a block satisfies a stopping criterion (uniform colour, ≤ C points,
≤ C segments).

| Variant | Data | Split rule | Notes |
|---|---|---|---|
| Point quadtree (Finkel & Bentley 1974) | points | at an inserted point (data-driven position, always 4-way) | shape depends on insertion order |
| Region quadtree (Klinger & Dyer) | binary rasters | equal quadrants until uniform | 2^n × 2^n images; set ops, connected components |
| MX quadtree | points on a discrete grid | as region quadtree with points as black pixels | depth = grid resolution |
| PR quadtree | points in continuous space | equal quadrants until ≤ 1 (bucket: ≤ C) point | shape independent of order; depth depends on closest pair → use buckets |
| MX-CIF | small rectangles | store each rectangle at the smallest block containing it | no replication; big rectangles stuck near root |
| PMR quadtree | line segments | bucket splits once when it overflows, overflow buckets otherwise | used for road networks |
| XBR tree | points / segments | quadtree decomposition with variable-length addresses in paged, balanced nodes | external-memory, compact |
| Skip quadtree | points | region quadtree levels + skip-list | approximate range/NN in O(log n) expected |

**Linear quadtree** (Gargantini, CACM 1982): store only leaf (black) blocks,
each as a locational code (path of quadrant digits plus depth, or a
fixed-length code with "don't care" digits) in a B+-tree. Point location =
predecessor search on the code. This is precisely the Z-order key with a
level suffix; containment of block A in block B ⇔ B's code is a prefix of
A's.

Temporal extensions for evolving rasters — overlapping linear quadtrees,
multiversion linear quadtree, time-split linear quadtree — share unchanged
subtrees between consecutive images (see temporal file); benchmarks favour
overlapping linear quadtrees.

> **Beyond EDBS:** Oracle Spatial offered both quadtree and R-tree indexes
> (Kothuri, Ravada, Abugov, SIGMOD 2002 compared them) and later releases
> deprecated quadtree indexes in favour of R-trees. Kim & Patel (CIDR 2007)
> argued the PR-quadtree is competitive for in-memory point workloads. In
> PostgreSQL the quadtree and kd-tree are SP-GiST opclasses for `point`.

---

## 6. One-dimensional embeddings beyond SFCs

These map a d-dimensional point to a scalar key for a B+-tree and translate
a query into a set of 1-D intervals; they appear again in the
high-dimensional file.

- **Pyramid technique** (Berchtold, Böhm, Kriegel, SIGMOD 1998): split the
  data space into 2d pyramids sharing the centre as apex; key = pyramid
  number + height (L∞ distance from centre along the pyramid's axis). A
  window query becomes ≤ 2d key intervals. Works best for L∞-shaped
  queries and hypercube-ish data.
- **iDistance** (Yu, Ooi, Tan, Jagadish, VLDB 2001): partition data,
  pick a reference point per partition, key = partition_id·c + distance to
  reference point; NN search by expanding annuli.
- **Interval mapping** (valid-time file): `(start, end)` as a 2-D point, or
  MAP21-style concatenation `start·10^s + end`.

---

## 7. Implementation checklist

- Fix the grid: choose bits per dimension and the domain → integer mapping
  (affine scaling, or quantile/rank transform for skewed columns). Record
  the mapping in metadata; changing it invalidates every key.
- Handle negative and floating-point coordinates explicitly (flip sign bit
  for order-preserving integer encoding of IEEE floats).
- Key width: d · bits ≤ 64 or 128; beyond that use a byte-string key with
  memcmp order.
- Range decomposition: bound the number of intervals per query (e.g. 16–256)
  and always post-filter on true coordinates.
- Quadtree depth: cap depth and use bucket capacity C to avoid pathological
  depth from near-duplicate points; treat exact duplicates as a list.
- Grid file: keep scales in memory; size the directory page so the common
  partial-match query touches few directory pages.
- Testing: property test `decode(encode(p)) == p`; monotonicity of Z-order
  within each quadrant; BIGMIN result is the minimal in-box key > current;
  range results equal brute force for random boxes including degenerate
  (zero-width) and full-domain boxes.

Sources: EDBS *Space-Filling Curves* (p.3547), *Space-Filling Curves for
Query Processing* (p.3548), *Grid File (and Family)* (p.1671), *Quadtrees
(and Family)* (p.2946), *Spatial Indexing Techniques* (p.3592),
*High-Dimensional Indexing* (p.1706), *Spatial Join* (p.3598), *Indexing of
the Current and Near-Future Positions of Moving Objects* (p.1884).
