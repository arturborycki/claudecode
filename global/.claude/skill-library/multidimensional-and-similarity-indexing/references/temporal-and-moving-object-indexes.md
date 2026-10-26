# Temporal, spatio-temporal and moving-object access methods

Read this when building an index over versioned data (transaction time),
interval data (valid time), both (bitemporal), trajectories, or current and
predicted positions of moving objects. For temporal *semantics* (SQL:2011
periods, sequenced semantics, coalescing) see the `temporal-databases`
skill; this file covers access methods only.

Common cost triple used throughout: **space** (pages), **update** (pages
touched per change), **query** (pages read). n = total number of changes in
the history, m = size of the current state, s = output size, B = records
per page.

---

## 1. Transaction-time indexing

### Model

An evolving set; time increases monotonically (commit order); changes are
applied **only to the current state**; past states are immutable. A record
carries `[t_start, t_end)` with `t_end = UC` (until changed) while alive; a
deletion closes the interval (logical delete); an update = delete + insert
at the same instant. Query of interest: **range-timeslice** — keys in
[k1,k2] alive at time t. (Pure timeslice: all alive at t; key-history: all
versions of key k.)

### Baselines and bound

| Approach | Space | Update | Query |
|---|---|---|---|
| Copy (materialise each state) | O(n²/B) worst | O(n/B) | O(log + s/B) |
| Log (append changes) | O(n/B) | O(1) | O(n/B) — replay |
| Lower bound for linear-space methods | O(n/B) | — | Ω(log_B n + s/B) |

Salzberg & Tsotras (ACM CSUR 1999) compare the methods worst-case.

Two design methodologies beat both baselines:

### (a) Partial persistence — Multiversion B-tree (MVBT)

Becker, Gschwind, Ohler, Seeger, Widmayer (VLDBJ 1996). Partial persistence
(Driscoll, Sarnak, Sleator, Tarjan 1989): every update creates a new version,
old versions remain readable, only the newest is modifiable — exactly the
transaction-time contract.

Structure: a DAG of pages embedding one B+-tree per version; each entry
(leaf and index) carries `[insert_time, delete_time)`. A **root\*** directory
maps time ranges to the root alive then (small, often memory-resident;
B-tree over it if large).

Invariants:
1. **Weak version condition**: for every time t in a page's lifespan, the
   page (non-root) contains ≥ d entries alive at t. This guarantees each
   page touched by a timeslice query contributes Ω(B) results → optimal
   query I/O.
2. Page capacity b = k·d. After a structural change, a newly created page
   must satisfy a **strong version condition**: its alive count lies
   strictly inside [(1+ε)d, (k−ε)d], so it can absorb ε·d further changes
   before the next restructuring (amortisation).
3. Only the current version is mutated; nothing with `delete_time ≤ now` is
   ever changed except by being copied.

Structural changes:
```
on overflow or weak-version underflow of page x at time t:
  version split: copy entries alive at t into new page y; mark x dead at t
                 (close x's parent entry, insert entry for y)
  if |alive(y)| > (k-ε)d : key split y into two pages
  if |alive(y)| < (1+ε)d : merge with a version-split copy of a sibling
                            (then key split if the result is too big)
```
Results: range-timeslice O(log_B n + s/B) I/Os; space O(n/B); update
amortised O(log_B m). Optimal.

Lineage: **WOBT** (Easton 1986) introduced time-splits for write-once
optical disks; **TSB-tree** (Lomet & Salzberg, SIGMOD 1989) for read-write
media; MVBT dropped deletion markers and added consolidation (merges), which
the WOBT/TSB lack. Snapshot index (Tsotras & Kangelaris 1995) and the
multiversion access structure (Varman & Verma 1997) are other
I/O-optimal persistent methods.

### TSB-tree specifics (Lomet & Salzberg)

- Nodes are split either by **time** (records alive at the split time are
  copied to the new current node; the historical node becomes immutable —
  originally migrated to WORM storage, the current node stays on magnetic
  disk) or by **key** (as in a B+-tree, only for the current node).
- Policy choice: time-split at the current time vs at the time of the last
  update; key-split when the fraction of current records exceeds a
  threshold, else time-split. Trade-off: more time splits → more redundancy
  (records alive across the split are duplicated) but better current-version
  clustering.
- Index nodes are time/key split too; an index entry for a historical node
  stays in historical index nodes.
- Deletions leave markers; no merging of sparse current nodes.

> **Beyond EDBS:** Lomet et al.'s *Immortal DB* prototype integrated a
> TSB-tree style time-split index into Microsoft SQL Server for
> transaction-time tables. Production systems mostly take simpler routes:
> SQL Server system-versioned temporal tables move closed versions into a
> separate history table (by default clustered on the period columns, end
> then start), PostgreSQL MVCC keeps versions in the heap without a
> historical index, and lakehouse formats (Iceberg/Delta) provide
> table-granularity time travel through immutable snapshots of file lists —
> a coarse "copy-on-write of metadata" persistence with no per-key version
> index. If an engine needs efficient key-range AS OF queries over long
> histories, MVBT/TSB ideas are the reference designs.

### (b) Overlapping trees

Overlapping B-tree (Burton et al. 1985; Tzouramanis et al. 1999), also the
EXODUS approach: each version gets a new root; unchanged subtrees are
**shared** by pointer; an update copies the leaf and the root-to-leaf path
(path copying). No timestamps inside nodes (only roots are stamped).
- Space O(n log_B n) worst case (a path per update); update O(log_B m);
  timeslice query = find root via a B-tree on root timestamps, then a normal
  search.
- Much simpler to implement and to make crash-safe (copy-on-write B-tree,
  cf. LMDB); bad for time-range queries (each version traversed
  separately) and space-hungry under scattered updates.

---

## 2. Valid-time indexing

### Model

A single current collection of **interval objects** (validity periods);
insert/delete/modify anywhere on the time axis (corrections of the past and
future allowed); no history of corrections kept. Index problem = dynamic
interval management. Basic query: **stabbing** (intervals containing v);
also interval intersection, plus non-temporal key predicates.

### Options

| Method | Idea | Space | Stabbing query | Notes |
|---|---|---|---|---|
| Interval tree / segment tree / priority search tree | classic main-memory structures | O(n) / O(n log n) / O(n) | O(log n + s) | external versions (Arge & Vitter 1996 external interval tree, metablock tree, path caching) are mostly of theoretical interest |
| **RI-tree** (Kriegel, Pötke, Seidl, VLDB 2000) | virtual interval-tree backbone computed arithmetically; interval stored at its fork node; two B+-trees: (fork, lower) and (fork, upper) | O(n/B) | O(h·log_B n + s/B) | runs inside any RDBMS with plain B+-trees and SQL — easiest to deploy |
| R-tree on intervals as 1-D boxes (plus key dims) | generic | O(n/B) | no guarantee | long intervals inflate MBRs; mixed long/short lengths → heavy overlap |
| Interval → 2-D point (start, end) + point access method | stabbing v ⇔ start ≤ v ≤ end ⇔ point in a quadrant above the diagonal | O(n/B) | no worst-case guarantee | long intervals cluster with long ones; no overlap problem |
| MAP21 | key = start·10^s + end in a B+-tree | O(n/B) | scan back from v bounded by max interval length | cheap; needs a known maximum length |
| Segment R-tree / Skeleton SR-tree (Kolovson & Stonebraker 1991) | long intervals stored in internal nodes that they span; remnants fragmented to children | up to O(n log_B n) | average logarithmic | larger upper nodes (multi-page) to keep fanout |

**RI-tree mechanics (sketch).** The backbone is a virtual balanced binary
tree over the integer time domain [1, 2^h−1]; the fork node of [l, r] is the
first backbone node w with l ≤ w ≤ r found by descending from the root —
computable with bit arithmetic, no stored nodes. Stabbing at v: walk the
root-to-v path; at nodes w > v report intervals with lower ≤ v from the
lowerIndex; at nodes w < v report intervals with upper ≥ v from the
upperIndex; at w = v report all. Each step is a B+-tree range scan; all
steps can be expressed as one SQL query over two indexed tables.

**Now-relative data**: valid-time intervals ending at the moving `now`
(and transaction-time `UC`) make MBRs that grow with time. Storing them as
"max timestamp" overstretches boxes; the **GR-tree** (Bliujute, Jensen,
Šaltenis, Slivinskas, VLDB 1998) represents growing rectangles and stair
shapes explicitly in leaves and uses bounding rectangles or regions that
grow with time in inner nodes.

> **Beyond EDBS:** PostgreSQL range types (`tstzrange` etc.) with GiST or
> SP-GiST opclasses implement valid-time indexing directly; exclusion
> constraints (`EXCLUDE USING gist (k WITH =, period WITH &&)`, with
> btree_gist for scalar keys) enforce non-overlapping periods per key, and
> PostgreSQL 18 added SQL-standard-style `WITHOUT OVERLAPS` keys on the
> same machinery. SQL:2011 application-time periods are the standard
> surface syntax for valid time.

---

## 3. Bitemporal indexing

Abstraction: a sequence of valid-time collections C(t) indexed by
transaction time; each record = surrogate + valid interval + transaction
interval `[t, UC)`. Query: e.g. which valid intervals contained v as known
at transaction time t.

| Approach | Description | Trade-off |
|---|---|---|
| One R-tree on (tt × vt) rectangles | simple; UC ≈ max time | all alive records share the UC edge and are long in tt → massive overlap |
| Two R-trees (Kumar, Tsotras, Faloutsos, TKDE 1998) | **front** tree: alive records as vertical vt-segments at their insertion tt; **back** tree: closed records as full rectangles. Query = point-enclosure on back + segment intersection with a horizontal probe on front | removes UC overlap; deletes move a record from front to back |
| GR-tree | exact growing regions for both now and UC | more complex geometry |
| Partial persistence of a valid-time index | make an R-tree (or quadtree) partially persistent: bitemporal R-tree | linear space; valid-time queries on any C(t) via the persistent structure |
| Overlapping valid-time index | overlapping R-trees (historical R-tree) or overlapping linear quadtrees | simpler to implement; possibly O(log) extra space |

The persistence/overlap approaches decouple the two axes: transaction time
comes from persistence, valid time from the underlying interval index, and
UC never has to be represented explicitly.

---

## 4. Historical spatio-temporal (trajectory) indexing

Data: sampled positions linearly interpolated into segments per object; the
history grows without bound (sample, or report only on change of speed or
direction to limit volume). Queries: timeslice, time-window, trajectory
(e.g. "where was object o during [t1,t2]", "who passed near X").

| Category | Methods | Strength | Weakness |
|---|---|---|---|
| 3-D structures (time as a dimension) | RT-tree (R-tree + TSB-style time attributes), **3D R-tree**, STR-tree (keeps a trajectory's segments together for p levels) | uniform handling | timeslice cost depends on total history size, not on the number alive at t |
| Overlapping/multiversion 2-D structures | MR-tree, **HR-tree** (overlapping R-trees), HR+-tree (nodes shared across timestamps to cut replication), **MV3R-tree** (MVR-tree for timestamp queries + small 3D R-tree for long interval queries, chosen by threshold) | fast timeslice | interval queries traverse many versions; replication |
| Trajectory-oriented | **TB-tree** (leaf holds segments of one trajectory only; leaves chained per trajectory; grows left to right), SETI (static spatial partitions, temporal index per partition; clipped segments duplicated), SEB-tree (zones + start/end time B-tree) | trajectory retrieval | weaker pure spatial queries |

Engineering note: SETI's insight — space changes little, time grows forever
— maps well onto partitioned storage: static spatial partitions × append-
only time-ordered runs inside each (exactly how a lakehouse table
partitioned by cell id and sorted by time behaves).

---

## 5. Current and near-future positions of moving objects

Positions as linear functions `x(t) = x(t_ref) + v·(t − t_ref)` with one
global reference time; an update = delete old function + insert new one;
update rates are very high. Queries over [now, now + H]:
- **timeslice** `(R, t)`: inside rectangle R at time t;
- **window** `(R, t1, t2)`: inside R at some time in [t1, t2];
- **moving** `(R1, R2, t1, t2)`: inside the trapezoid sweeping R1@t1 to R2@t2;
- plus kNN, RNN, continuous variants.

Four indexing approaches:

1. **Trajectories as lines in (d+1)-D** (e.g. PMR-quadtree over (x,t)) —
   hard beyond 1-D, needs periodic rebuild.
2. **Dual transformation** (Kollios, Gunopulos, Tsotras, PODS 1999): line
   ↦ point `(x(t_ref), v)` in 2d dimensions; queries become polygons in dual
   space. STRIPES (Patel et al., SIGMOD 2004) indexes dual points with PR
   quadtrees; B^dual-tree (Yiu, Tao, Mamoulis) linearises them with an SFC
   into a B+-tree; kinetic data structures (Agarwal, Arge, Erickson) schedule
   future events that maintain invariants. Dual methods keep two or more
   indexes for successive t_ref windows and drop the oldest when empty.
3. **Primal, time-parameterised**: **TPR-tree** (Šaltenis, Jensen,
   Leutenegger, Lopez, SIGMOD 2000).
4. **Label timestamps + query enlargement**: **Bx-tree** (Jensen, Lin, Ooi,
   VLDB 2004).

### TPR-tree

- R*-tree structure; each bounding rectangle stores per dimension
  `(x_lo(t_ref), x_hi(t_ref), v_lo, v_hi)` with
  `v_lo = min child velocity`, `v_hi = max child velocity`, so the
  rectangle **conservatively contains its children for all t ≥ t_ref**.
- Bounding rectangles are minimal only when computed; **tightening**
  recomputes them whenever a node is modified.
- Timeslice query: evaluate every rectangle at t_q and run an R-tree search.
  Window/moving query: test intersection of the query trapezoid with the
  rectangle's trapezoid in (x,t) space per dimension.
- Insertion heuristics: the R*-tree objective functions (area, margin,
  overlap, centre distance) become functions of time A(t); minimise their
  **integral over [t_c, t_c + H]** where H is the horizon parameter.
- Query quality decays as rectangles expand; a sufficiently high update rate
  (which tightens nodes) is a precondition for good performance.

Descendants: TPR*-tree (Tao, Papadias, Sun, VLDB 2003: better heuristics
targeting a query cost model), R^EXP-tree (expiration times so stale objects
vanish), STAR-tree (self-adjusting, richer bounding shapes), VCI (plain
R-tree plus per-node v_max used to enlarge MBRs at query time).

### Bx-tree

- Partition time into phases of length Δt_mu; each object position is
  re-expressed as of the phase's **label timestamp**; key =
  `[phase partition id] ⊕ SFC(position at label time)` in a B+-tree.
- Query at time t: enlarge the query window by `v_max · |t − t_label|` in each
  partition (or by per-cell velocity histograms to reduce enlargement), map
  the enlarged window to SFC intervals, scan, filter with exact positions.
- Rolling partitions: a phase's partition becomes empty after all its
  objects have updated and is dropped/reused.
- Wins: B+-tree concurrency/recovery for free, high update throughput.

Chen, Jensen, Lin (PVLDB 2008) benchmarked TPR, TPR*, STRIPES, Bx and
B^dual trees; no single winner — update-heavy workloads favour the
B+-tree-based methods.

---

## 6. Implementation and testing checklist

- Represent UC/now symbolically in memory (sentinel) and resolve at query
  time; never bake "max time" into bounding boxes that drive pruning
  without understanding the overlap cost.
- MVBT/TSB: test the weak version condition and that every timeslice query
  equals replaying the log to time t (oracle: a log of changes + naive
  reconstruction). Fuzz with random insert/delete streams and random query
  times including exactly split times.
- Overlapping trees: verify sharing (reference counts) and that writing the
  new version never mutates a shared page (assert page is not reachable from
  an older root before writing).
- Interval indexes: oracle = scan; adversarial lengths (many tiny plus a
  few domain-spanning intervals), identical endpoints, empty intervals,
  open-ended (now/infinity) intervals.
- TPR-trees: property test that for random t ≥ t_ref in [now, now+H], every
  child's position lies within the parent's evaluated rectangle; use
  outward rounding of velocity bounds.
- Bx-tree: verify the enlargement covers v_max drift; test objects with
  maximum speed moving directly out of the query window.

Sources: EDBS *Transaction-Time Indexing* (p.4211), *Valid-Time Indexing*
(p.4360), *Bitemporal Indexing* (p.304), *Indexing Historical
Spatiotemporal Data* (p.1868), *Indexing of the Current and Near-Future
Positions of Moving Objects* (p.1884), *Quadtrees (and Family)* (p.2946).
