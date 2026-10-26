# GiST and the R-tree family

Read this when implementing or reviewing a balanced, data-partitioning
multidimensional index: a GiST operator class, an R-tree/R*-tree, a bulk
loader, a split heuristic, or concurrency/recovery for any of them.

---

## 1. GiST as the abstraction

A Generalized Search Tree (Hellerstein, Naughton, Pfeffer, VLDB 1995) is a
height-balanced, paged tree whose internal entries are `(predicate p, child)`
and whose leaf entries are `(predicate p, tid)`. The only structural rule is

> **Covering invariant.** For every internal entry `(p, child)`, every tuple
> reachable below `child` satisfies `p`.

Nothing requires predicates of siblings to be disjoint or ordered. A B+-tree
is the special case where `p` is a key range and siblings partition the
domain; an R-tree is the case where `p` is an MBR and siblings may overlap.

The engine owns paging, buffer management, search, insertion, splitting,
concurrency and WAL. The type author supplies a small key class:

| Method | Contract | What breaks if wrong |
|---|---|---|
| `Consistent(E, q)` | Return false **only** if no tuple under `E` can satisfy `q`. May return true spuriously (lossy). | False negative = silently missing rows. |
| `Union(P)` | Return a predicate implied by every predicate in `P` (e.g. MBR of MBRs). | Covering invariant violated after insert/split. |
| `Penalty(E, new)` | Cost of inserting `new` under `E` (e.g. area enlargement). | Only quality (clustering), never correctness. |
| `PickSplit(P)` | Partition an overflowing set into two groups, each ≥ minimum fill. | Quality; degenerate splits can cause unbounded split loops if one side is empty. |
| `Compress/Decompress` | Optional lossy/lossless key encoding for storage. | Lossy compression must still satisfy covering (decompressed key ⊇ original). |
| `Same(a, b)` (PostgreSQL) | Equality for keys, to skip no-op parent updates. | Missed early termination only. |
| `Distance(E, q)` (PostgreSQL ≥ 9.1) | Lower bound on distance from `q` to anything under `E`; exact at leaves unless recheck is flagged. | Wrong KNN order if not a lower bound. |

Correctness lives entirely in `Consistent`, `Union` and the lower-bound
property of `Distance`. `Penalty` and `PickSplit` are pure performance
knobs. That separation is the main engineering lesson of GiST: put the
property-based tests on the first group and the benchmarks on the second.

### Algorithms (engine side)

```
Search(node, q):
  for e in node.entries:
    if Consistent(e, q):
      if node.is_leaf: emit e.tid (recheck heap tuple if lossy)
      else: Search(child(e), q)

Insert(tuple t, level L):
  path = []
  n = root
  while n.level > L:                     # ChooseSubtree
    e = argmin_{e in n} Penalty(e, t)    # ties: implementation-defined
    path.push((n, e)); n = child(e)
  add t to n
  if overflow(n): (n1, n2) = PickSplit(n.entries); install n2 in parent (may cascade)
  AdjustKeys: walk path upward, replacing parent predicate by Union(child entries);
              stop when Same(old, new)
```

Deletion in the original paper does not merge; implementations either leave
underfull pages (PostgreSQL GiST does, and relies on VACUUM to reclaim
empty pages) or reinsert orphans as R-trees do.

### Extensions of the framework

- **Nearest-neighbour / ranked search** (Aoki ICDE 1998; PostgreSQL KNN-GiST):
  replace the DFS stack by a priority queue keyed on `Distance`. This turns
  any GiST into a best-first incremental ranker (see
  `spatial-join-and-nn-search.md`). PostgreSQL ≥ 9.5 lets `Distance` set a
  recheck flag; the executor then keeps a reorder queue and only emits a row
  once its exact distance is ≤ the lower bound at the queue head — the
  multi-step kNN algorithm of Seidl & Kriegel built into an index scan.
- **SP-GiST** (Aref & Ilyas, JIIS 2001): an extensibility framework for
  *space-partitioning, possibly unbalanced* trees — quadtrees, kd-trees,
  radix tries. Interface (PostgreSQL ≥ 9.2): `config`, `choose`,
  `picksplit`, `inner_consistent`, `leaf_consistent`. The hard systems
  problem it solves is clustering small, variable-depth nodes onto pages.
- **Theory of indexability** (Hellerstein, Koutsoupias, Miranker,
  Papadimitriou, Samoladas, JACM 2002): formal trade-off between redundancy
  (copies of a tuple) and access overhead (pages read beyond the output) for
  a workload of queries; explains why some workloads cannot be indexed well
  by any tree.
- **amdb** (Kornacker, Shah, Hellerstein, 2003): profiles a GiST instance by
  attributing wasted I/O to *excess coverage* (predicates looser than
  needed), *utilization* (underfull pages) and *clustering* (tuples that
  co-occur in results spread over many pages). Use the same decomposition
  when diagnosing a slow spatial index.
- **RD-tree** (Hellerstein & Pfeffer 1994): sets as keys; the union is the
  superset; used for set containment and the ancestor of signature-based
  text GiST classes.

### Concurrency and recovery (Kornacker, Mohan, Hellerstein, SIGMOD 1997)

B-link right-links alone are insufficient because keys are unordered: after
a concurrent split, a searcher cannot tell from a key whether it must move
right. GiST fixes this with a **node sequence number (NSN)**:

1. A global counter (PostgreSQL uses the WAL LSN) is read when a searcher
   reads a parent and records the child pointer.
2. A split assigns the **original (left) node** the new counter value as its
   NSN; the new right sibling inherits the original's *old* NSN and old
   right-link, and the left node's right-link now points to it.
3. On reaching the child, if `child.NSN > remembered_counter`, the child was
   split after the parent was read; also search its right sibling (with the
   same remembered counter), repeating while the sibling's NSN is still
   greater — the first node with `NSN ≤ remembered_counter` is searched and
   ends the chain.

Phantom protection needs predicate-style locking because a range predicate
does not correspond to a key interval (the paper combines predicate locks on
search predicates with ordinary data locks). Under MVCC + SSI, PostgreSQL
takes SIREAD locks on visited GiST leaf pages.

Recovery: splits and key adjustments span several pages and must be atomic
w.r.t. crash; log them as a single nested top action / multi-page WAL
record, or mark incomplete splits (PostgreSQL: `F_FOLLOW_RIGHT` flag; an
incomplete split is completed by the next inserter that encounters it).

> **Beyond EDBS:** PostgreSQL 14 added *sorted* GiST builds when the opclass
> provides `sortsupport` (implemented for `point` via a Z-order key): pages
> are filled bottom-up from a sorted stream instead of by repeated inserts,
> which is much faster and gives tighter pages. PostGIS ships GiST
> (R-tree-like, 2D/ND boxes in float4), SP-GiST (quad/kd) and BRIN opclasses.

---

## 2. R-tree (Guttman, SIGMOD 1984)

### Structure and invariants

- Leaf entry `(MBR, oid)`; internal entry `(MBR, child)`; MBR is the
  tightest axis-aligned box over the child's entries.
- Every non-root node holds between `m` and `M` entries, `m ≤ M/2`; root has
  ≥ 2 children unless it is a leaf; all leaves at the same depth.
- Point data: leaves can hold ~2× more entries than rectangle data (store
  points, not degenerate boxes), so `M_leaf ≠ M_internal` in practice.

Testable invariants (write an `assert_valid()` that checks all of these
after every mutation in debug builds):

1. `node.mbr == union(child.mbr for child)` exactly (not just ⊇) — tight
   MBRs are a quality property; containment ⊇ is the correctness property.
2. Fill bounds and uniform leaf depth.
3. Every oid appears in exactly one leaf (R-tree, R*-tree, Hilbert R-tree);
   in R+-tree, an object may appear in several leaves and the union of its
   clipped pieces covers it.

### Insertion

```
ChooseLeaf(E):   # Guttman
  descend choosing the child whose MBR needs least area enlargement
  to include E; break ties by smallest area
Insert: put E in leaf; if overflow -> SplitNode; AdjustTree upward
        (recompute MBRs, install split halves, possibly grow a new root)
```

### Guttman's split policies (node with M+1 entries)

| Policy | Seeds | Distribution | Cost |
|---|---|---|---|
| Exhaustive | — | try all 2^(M+1) bipartitions, minimise total area | exponential; only for tiny M |
| Quadratic | pair maximising dead space `area(J) − area(E1) − area(E2)`, J = MBR of the pair | repeatedly pick the entry with the largest preference difference `|d1 − d2|` (enlargement for each group), assign to group needing less enlargement; force the rest when a group must take all remaining to reach `m` | O(M²) |
| Linear | along each axis, pair with greatest separation normalised by axis extent | assign remaining in arbitrary order by least enlargement | O(M) |

Guttman recommended quadratic as the compromise. Linear produces visibly
worse trees on skewed data.

### Deletion

`FindLeaf` (may need to search several subtrees because of overlap), remove,
then `CondenseTree`: walk up; remove each underfull node from its parent and
collect its entries; recompute MBRs; finally **reinsert** orphaned entries at
their original level (leaf entries at leaves, subtree entries at the
corresponding height). Reinsertion rather than sibling merging is preferred
because there is no natural "adjacent sibling" in 2-D and reinsertion
re-optimises placement.

---

## 3. R*-tree (Beckmann, Kriegel, Schneider, Seeger, SIGMOD 1990)

The R*-tree changes only insertion heuristics; search is identical. It
optimises four criteria simultaneously: area, overlap between siblings,
margin (perimeter — favours square-ish boxes, which pack better at upper
levels), and storage utilisation.

**ChooseSubtree**
- If the children are leaves: choose the entry with least **overlap
  enlargement** (increase of Σ overlap with siblings); ties → least area
  enlargement → smallest area. (The paper also gives a cheaper approximation
  that only evaluates the ~32 entries with least area enlargement.)
- Otherwise: least area enlargement, ties → smallest area.

**Split** (node with M+1 entries, minimum fill m; m ≈ 40% of M worked best)
```
ChooseSplitAxis:
  for each axis a:
    for sort key in (lower bound, upper bound):
      sort entries; for k in 1..(M-2m+2):
        group1 = first (m-1+k) entries, group2 = rest
        S_a += margin(group1) + margin(group2)
  choose axis with minimum S_a
ChooseSplitIndex (on that axis, both sorts):
  choose distribution with minimum overlap(group1, group2);
  ties -> minimum total area
```
Complexity O(d · M log M) per split.

**Forced reinsert** — the key idea. On the *first* overflow at a given level
during one insertion (excluding the root): remove the `p` entries (p ≈ 30%
of M) whose centres are farthest from the node's MBR centre, shrink the MBR,
and reinsert them from the top ("close reinsert": nearest first performed
best). Only if the node overflows again at that level is it split. This
gives a dynamic tree some of the global reorganisation of a bulk load and
raises utilisation; the cost is more I/O per insert and a re-entrant insert
path that must be designed carefully (no latch held across the reinsertion;
see failure modes).

---

## 4. R+-tree (Sellis, Roussopoulos, Faloutsos, VLDB 1987)

- Internal entries at the same level are **disjoint**; objects straddling a
  partition are clipped and stored in every leaf they intersect.
- Point queries follow a single path; window queries may report duplicates
  → deduplicate (oid set, or reference-point rule as in PBSM).
- No minimum fill guarantee; splits can propagate **downward** (a split line
  through a parent region forces children it cuts to split) — the same
  cascade as the K-D-B-tree.
- Space grows with replication; large objects are pathological.
- Use when point-location dominates and objects are small relative to the
  partition size; otherwise the R*-tree wins.

---

## 5. Hilbert R-tree (Kamel & Faloutsos, VLDB 1994)

- Orders data rectangles by the Hilbert value of their centre; internal
  entries carry `(MBR, LHV, child)` where LHV is the largest Hilbert value
  in the subtree. Insertion descends like a B+-tree on Hilbert value (pick
  the first child with LHV ≥ h), so ChooseSubtree is O(log) comparisons
  rather than geometric optimisation.
- Overflow uses **deferred splitting**: with a cooperating set of `s`
  siblings, first redistribute among them; only when all `s` are full split
  `s` nodes into `s+1`. Larger `s` → higher utilisation, costlier inserts.
- Search still uses MBRs; the Hilbert order is only used for placement.
- Good clustering for small, square-ish objects; degrades for elongated or
  large rectangles whose centre is a poor proxy for extent.

---

## 6. Bulk loading (packing)

Bottom-up construction from a known set: nodes are filled to capacity (or a
target fill such as 70–90% if future inserts are expected), the tree is
minimal in height and node count, and there is no split overhead.

| Method | Leaf ordering | Notes |
|---|---|---|
| Packed R-tree (Roussopoulos & Leifker 1985) | sort by one coordinate (e.g. low-x) | creates long thin leaves; poor window queries |
| Hilbert pack (Kamel & Faloutsos, CIKM 1993) | sort by Hilbert value of centre | good general default; trivially parallel (global sort) |
| STR, Sort-Tile-Recursive (Leutenegger, Edgington, Lopez, ICDE 1997) | tile: slices on x, then y within slice | best or near-best on uniform & mildly skewed data |
| Top-down greedy split (TGS) | recursive binary partition minimising a cost | better on highly skewed data, more CPU |

**STR in 2-D**, n rectangles, capacity b:
```
P = ceil(n / b)                   # number of leaves
S = ceil(sqrt(P))                 # number of vertical slices
sort all rectangles by x-centre; cut into S slices of S*b rectangles
for each slice: sort by y-centre; emit runs of b as leaves
recurse on the leaf MBRs to build the next level until one node
```
In d dimensions: `S = ceil(P^(1/d))` slabs on the first axis, then recurse
on the remaining d−1 axes inside each slab. Cost: d sorts per level,
O(n log n).

> **Beyond EDBS:** the *Priority R-tree* (Arge, de Berg, Haverkort, Yi,
> SIGMOD 2004) is a bulk-loaded R-tree with worst-case optimal window query
> cost O((N/B)^(1−1/d) + T/B); packed Hilbert/STR trees have no such bound
> and can be forced to read Θ(N/B) leaves for an empty answer on adversarial
> data. Choose PR-tree when tail latency on adversarial or extremely skewed
> data matters.

Bulk *insertion* into an existing tree: small-tree-large-tree (Chen et al.
1998) builds a tree over the batch and grafts it at the right height; GBI
generalises it by clustering the batch first. For LSM-style engines the
equivalent is "build a packed R-tree per immutable run and merge by
rebuild".

---

## 7. Variants worth knowing by name

| Variant | Idea | Use |
|---|---|---|
| X-tree (Berchtold, Keim, Kriegel, VLDB 1996) | supernodes instead of overlap-producing directory splits; split history | moderately high dimensions (see high-dim file) |
| SS-tree / SR-tree | spheres / sphere ∩ rectangle regions | Euclidean NN in feature spaces |
| TPR / TPR*-tree | time-parameterised MBRs with velocity bounds | moving objects (temporal file) |
| RT-, 3D R-, HR-, MV3R-tree | time as dimension / persistence | historical spatio-temporal |
| PTI / U-tree | probability-threshold x-bounds per entry | uncertain data |
| RdNN-tree | each entry also stores max NN distance of subtree | reverse NN |
| R-link tree (Kornacker & Banks, VLDB 1995) | right-links + LSN per node for high-concurrency R-trees | concurrent updates |
| SD-Rtree (du Mouza, Litwin, Rigaux, ICDE 2007) | scalable distributed R-tree over servers | distributed |

---

## 8. Cost intuition

- Window query I/O ≈ number of nodes whose MBR intersects the query. For
  uniform data and a query of side q in a unit square, a node of side s is
  hit with probability ≈ (s+q)² (Minkowski sum) — hence the drive to small
  margin *and* small area. The same Minkowski-sum reasoning underlies the
  high-dimensional cost models of Berchtold/Böhm.
- Overlap at upper levels multiplies paths; a 10% overlap at the root level
  costs more than 10% at leaves. Measure overlap per level, not globally.
- Point data indexed as zero-area rectangles waste half the leaf payload;
  store points natively.

---

## 9. Failure modes and classic bugs

| Bug | Symptom | Detection |
|---|---|---|
| Floating-point MBR rounding inward when converting double→float | rows near box edges missing from results | compare index scan vs seq scan on edge-heavy fixtures; always round **outward** (min down, max up) when compressing |
| Parent MBR not enlarged on insert path (AdjustTree skipped on early exit) | intermittent false negatives after inserts | `assert_valid()` recomputing unions |
| Forced reinsert while holding latches on the path | deadlock or latch-order violation | reinsert after releasing the path; or queue reinsertions |
| Reinsert recursion re-triggering forced reinsert at the same level | infinite loop / stack growth | per-insertion bitmask of levels already reinserted |
| PickSplit returning an empty group (all-identical keys) | infinite split loop | fall back to an arbitrary half split when the heuristic degenerates |
| Deletion searching only one path | "key not found" though present | FindLeaf must explore all consistent subtrees |
| R+/clipping without dedup | duplicate result rows | oid-dedup or reference-point rule |
| NaN or inverted (min > max) boxes from bad input | Consistent returns garbage, tree corruption | validate on insert; reject or normalise |
| Empty geometry / NULL key | crash or misplaced entries | treat as special "empty" key class excluded from all spatial predicates |
| Lossy GiST key without recheck | false positives returned to user | `recheck` flag must propagate to executor |

---

## 10. Implementation notes (C/C++/Rust)

- Store MBRs as `[min_0..min_{d-1}, max_0..max_{d-1}]` contiguous arrays
  (SoA within a node page when d is fixed) so intersection tests vectorise;
  `intersects = all(min_a <= max_b) && all(min_b <= max_a)`.
- Keep page-resident entries fixed-size for a given d to allow binary
  layout without slot indirection; variable-size keys (GiST generic) need a
  slotted page (see `page-and-file-format`).
- Split scratch space: allocate `M+1` entries on the stack or a per-thread
  arena; never allocate per split in the hot path.
- Rust: an arena of nodes indexed by `u32` page ids; MBR as `[f64; 2*D]`
  with `const D: usize` generics; search as an explicit stack/heap to avoid
  recursion limits in deep or skewed trees.
- Expose `Penalty`/`PickSplit` as trait methods with default R*-style
  implementations so new key types get good behaviour for free.

Sources: EDBS *Generalized Search Tree* (p.1581), *R-Tree (and Family)*
(p.3258), *Spatial Indexing Techniques* (p.3592), *Multi-step Query
Processing* (p.2435), *Indexing Uncertain Data* (p.1900), *Reverse Nearest
Neighbor Query* (p.3234).
