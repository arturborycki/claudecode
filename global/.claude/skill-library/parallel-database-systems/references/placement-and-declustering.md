# Data placement and declustering

Placement decides where the first operators of every query run, which joins
and aggregations can stay local, how skew enters the system, how much data a
reconfiguration moves, and how the load spreads after a failure. In a
shared-nothing engine it is the single most consequential physical-design
decision; the run-time can only partly repair a bad one.

---

## 1. Objectives (they conflict)

| Objective | Pushes toward |
|---|---|
| Maximize I/O and CPU bandwidth for big scans | full declustering across all nodes |
| Minimize total work / messages for small queries | clustering a query's data on one or few nodes |
| Local joins and aggregations (no shuffle) | partitioning on join/grouping keys, aligned across tables |
| Pruning (skip partitions) | range/list on filter columns (dates) |
| Balanced load under skew | round-robin/random or hash on high-cardinality keys |
| Cheap growth and rebalancing | many logical buckets mapped indirectly to nodes |
| Graceful failover | backup copies spread across several nodes |
| Manageability (roll-in/roll-out, partial backup) | range partitions on time |

Unlike distributed DBMS fragmentation, there is no reason to maximize local
processing per site — users are not attached to nodes — and balance across a
large node count is the dominant concern.

---

## 2. Basic horizontal strategies

| Strategy | Placement rule | Full scan | Exact match on key | Range on key | Co-located equi-join | Skew sensitivity |
|---|---|---|---|---|---|---|
| Round-robin | i-th inserted row → `i mod n` | all nodes, perfectly even | all nodes | all nodes | never | none (by construction) |
| Random | uniform random node | all, even in expectation | all | all | never | none |
| Hash | `bucket(h(k))` → node | all, even if k high-cardinality | **one node** | all nodes | yes, if both sides hash on join key with identical function and bucket map | duplicate skew: a heavy key lands on one node |
| Range (interval) | key intervals → nodes | all | one node | **only overlapping nodes** | yes if ranges aligned | high: boundaries need accurate quantiles; data drift unbalances |
| List | explicit value lists → partitions | all | one | n/a | if aligned | high |
| Composite | e.g. range (time) then hash (key) | all | subset | pruned by first level | if second level aligned | mixed |

Vertical partitioning (column groups to different nodes) is rarely used for
parallelism because reconstruction needs joins; column stores apply it inside
a node for I/O reduction instead.

### Hash function engineering (where real bugs live)
- **Co-location requires identical canonical hashing on both sides.** Equal
  SQL values must hash equal across types and encodings: INT vs BIGINT vs
  DECIMAL(18,0), CHAR padding, collation-insensitive strings, `-0.0` vs
  `0.0`, NaN, dictionary-encoded vs plain. Normalize before hashing or
  co-location silently produces wrong join results.
- **NULL keys**: decide where they go (fixed bucket or round-robin) and make
  every consumer agree. For inner equi-joins NULLs never match, so they can be
  dropped before shuffling; for outer joins and GROUP BY they must be kept and
  grouped together.
- **Independence across levels.** If the node-level partition hash and the
  per-node hash-table hash use the same bits, every row on a node shares those
  bits and the local table clusters into a fraction of its slots. Use a
  different seed or different bits for each level (partition → spill
  partition → hash-table slot).
- **Indirection**: hash into B logical buckets (B ≫ n, e.g. thousands to
  ~1M), then map bucket → node with a table. Changing n rewrites the table and
  moves only reassigned buckets; plans never encode node ids. This is the
  Teradata hash-map design (row hash → hash bucket → AMP) and the reason
  `hash mod n` is wrong for a system that grows.

---

## 3. Hybrid and multi-dimensional schemes

- **Hashed small ranges**: cut the key domain into many small ranges and hash
  (or round-robin) the ranges to nodes. Small range queries touch one or two
  nodes with little overhead; large range queries touch all nodes with full
  bandwidth.
- **Range of hash values**: range-partition the hash space — the standard
  "hash buckets → nodes" scheme; makes split/merge of partitions trivial.
- **Two-column, two-level**: one column picks the node, another picks the
  storage location within the node (sub-partition, sort order). Partitioning
  across sites, partitioning within a site, and local physical organization
  are orthogonal choices.
- **Computed-expression partitioning**: partition on `date_trunc(month, ts)`,
  `hash(a, b)`, etc.; the optimizer must recognize derived predicates to prune.
- **Two hash functions for availability**: each item hashed to two sites with
  functions guaranteed to disagree.

> **Beyond EDBS:** Three named declustering schemes worth knowing:
> - *Hybrid-range partitioning* (Ghandeharizadeh & DeWitt, VLDB 1990): split
>   the key range into many fragments sized from the expected resource demand
>   of the typical range query, then spread them so that a query of typical
>   size touches the "right" number of nodes — few for cheap queries (low
>   startup), many for expensive ones (bandwidth).
> - *MAGIC* (Ghandeharizadeh, DeWitt, Qureshi, SIGMOD 1992): a
>   multi-dimensional grid over two or more attributes, with cells assigned to
>   nodes so that a selection on any one attribute touches only a row or
>   column of the grid, not every node.
> - *BERD* (Bubba's extended range declustering): range on the primary
>   attribute plus an auxiliary relation on the secondary attribute pointing
>   to the nodes that hold matching rows.
> - Teradata's primary index (hash across AMPs) plus row partitioning
>   (PPI/multi-level PPI by range or CASE expressions within each AMP) is the
>   production form of "one column across sites, another within sites".

---

## 4. Degree of declustering

- **Full partitioning** (every relation across all n nodes) maximizes
  bandwidth but hurts complex join queries (every operator spans n nodes, n²
  exchange connections) and is pointless for relations of a few blocks.
- **Variable partitioning** (Bubba, Copeland et al. SIGMOD 1988): the number
  of nodes a relation spans is a function of its size and access frequency
  ("heat"). Growth of a relation (e.g. doubling) should widen its spread
  (8 → 16 nodes), which requires reorganization — hence the need for
  location-independent plans.
- **Replicate small relations** to every node (dimension tables in a star
  schema, lookup tables). Joins with them are always local; cost is storage
  and the write fan-out on update. Replicated tables are also the cheapest
  "broadcast" — paid once at load instead of per query.

---

## 5. Aligned (co-located) partitioning

Terminology to keep straight:

| Term | Meaning |
|---|---|
| Local index / table partitioning | an index partitioned exactly like its base table (index entries live with their rows) |
| Aligned partitioning | two *different* tables partitioned identically on the join key (same function, bucket map, node set) |
| Global index / index partitioning | an index partitioned on its own search key, independent of the table |
| Non-aligned | anything else — joins need repartitioning or broadcast |

Aligned partitioning usually follows frequent join paths, foreign keys and
complex objects (order ↔ lineitem on orderkey). If all indexes of a table are
partitioned like the table, index intersection and RID fetches stay local; on
the other hand an index partitioned on its own key gives single-node lookups
on that key. Choose per index; the optimizer must know which.

**Derived (referential) horizontal partitioning**: partition S by the
partitioning of R it references (S joins R on a FK). Feasible only along a join
link. In warehouses: partition a dimension by a selection-predicate scheme,
then derive the fact table's partitioning from it, so star joins and
dimension-restricted queries prune fact partitions. (Oracle 11g ships this as
reference partitioning.)

> **Beyond EDBS:** Production vocabulary for the same ideas: Greenplum/
> Redshift distribution keys (`DISTKEY`, `DISTSTYLE ALL|EVEN|KEY|AUTO`),
> Citus colocation groups, Teradata "same PI" for AMP-local joins. In
> lakehouse formats (Iceberg/Delta/Hudi) partitioning is about *pruning*;
> bucketing (Hive/Spark bucketed tables, Iceberg `bucket[N]` transform) is
> what enables shuffle-free joins, and it only works if the engine's hash and
> bucket count match the writer's exactly.

---

## 6. Data-warehouse placement design

Model: one or more huge fact tables, several dimension tables of moderate size,
star-join queries (fact participates in every join), small result sets.
Standard layout: fact horizontally partitioned across P nodes (each node
answers `≈1/P` of the fact), dimensions replicated.

Design is a tuple `<Arch, DP, DA, DR, LB>` — architecture, data partitioning,
data allocation, data replication, load balancing — and each component's
optimization problem is NP-hard on its own (replica placement included).
Inputs: query workload with frequencies, a fragment budget W (W ≥ P, often
W ≫ P so fragments can be balanced), a replication budget R ≤ P, and
tolerances for attribute-value skew, placement skew and processing skew.

| Methodology | Sequence | Weakness |
|---|---|---|
| Iterative | partition (own cost model) → allocate (own cost model) → replicate | ignores that the best partitioning depends on allocation and replication |
| Conjoint, variant 1 | partition → (allocate + replicate together) | partition choice still blind |
| Conjoint, variant 2 | (partition + allocate together) → replicate | replication blind to allocation |
| Conjoint, full | partition + allocate + replicate in one search | largest search space (genetic, hill-climbing heuristics) |

Reported evidence (Bellatreche et al., on Teradata with SSB SF10): a conjoint
partition+allocation design ran the workload ~38% faster than iterative.

Load imbalance in warehouses comes from *data skew* (uneven fragment sizes or
contents) and *processing skew* (uneven work even on even data). Classic
remedy: move work from heavily loaded processors to idle ones — the data
migration costs communication, so replication of fragments is used to make
work movable without moving data.

---

## 7. Virtual partitioning (VP)

Used when you cannot (or will not) physically partition: fully replicated
database, black-box DBMS per node (database clusters), or skewed data that
defeats a priori striping.

**Simple VP (SVP)**: rewrite query Q over table T into n subqueries
`Q ∧ v_i ≤ T.vpkey < v_{i+1}`, one per node, each over its local replica;
compose the partial results with a final query.

```
Q:      SELECT SUM(price) FROM orders WHERE category = 'bolt'
Q_i:    SELECT SUM(price) AS sp FROM orders
        WHERE category = 'bolt' AND order_id >= :lo_i AND order_id < :hi_i
Final:  SELECT SUM(sp) FROM partials
```

Composition rules the rewriter must implement:

| Aggregate | Subquery emits | Combiner |
|---|---|---|
| SUM, COUNT | SUM, COUNT | SUM |
| MIN, MAX | MIN, MAX | MIN, MAX |
| AVG | SUM and COUNT | SUM(s)/SUM(c) (never average the averages) |
| COUNT(DISTINCT x) | distinct x values (or sketch) | COUNT DISTINCT over union — unless VP key = x |
| GROUP BY g | per-group partials | regroup on g |
| ORDER BY … LIMIT k | local top-k | merge, take k |
| Variance/stddev | n, Σx, Σx² (or Welford/Chan merge state) | combine moments |

Requirements and pitfalls:
- Tuples must be **physically clustered on the VP attribute** (ideally a
  clustered index). Otherwise each subquery is a full scan and parallelism
  multiplies work instead of dividing it.
- If a range is too large, the local optimizer may switch to a table scan.
- The VP attribute should be the clustering key of the largest table; other
  tables in the query are joined locally from full replicas.

**Adaptive VP (AVP; Lima, Mattoso, Valduriez 2004)**: each node processes its
range as a sequence of small subqueries whose size grows (e.g. doubling)
while response time per tuple improves and shrinks when it degrades — probing
for the largest size that still uses the index. Unfinished ranges can be
**stolen** by idle nodes, giving dynamic load balancing without moving data.
**Physical + virtual** (Furtado et al. 2005): physically partition the fact
table, replicate partitions, and layer small virtual partitions on top, so
work is re-locatable among replica holders.

Cost: P copies of the fact table for full replication; mitigated by partial
replication.

---

## 8. Reorganization and placement drift

- Range partitions drift as data arrives (time-ordered keys put all inserts on
  the last node). Hash partitions drift only with duplicate skew.
- Rebalancing must be transparent to compiled queries: resolve location at run
  time (bucket map / catalog lookup at stage scheduling).
- Remedy for skewed partitions: split oversized partitions further (subdivide
  a range, or give a heavy hash bucket more than one owner with a secondary
  key) rather than re-partitioning everything.

---

## 9. Placement review checklist

1. For each big table: distribution key, why, and its distinct-value count
   and top-k frequency (duplicate skew).
2. Which join paths are co-located? Which require shuffles every time?
3. Which tables are replicated, what is their update rate, how big may they
   grow before replication is wrong?
4. Bucket count vs node count; what moves when one node is added?
5. Canonical hashing spec shared by loader, storage, and executor (types,
   NULLs, collation) — with a cross-component test.
6. Pruning: are partition predicates derivable from typical filters
   (including computed expressions and joins to dimensions)?
7. Failure: after losing one node, what is the max per-node load factor?

---

Sources: Parallel Data Placement (p.2661); Data Partitioning (p.802);
Parallel Query Execution Algorithms (p.2668); Parallel Hash Join, Parallel
Merge Join, Parallel Nested Loops Join (p.2666); Parallel and Distributed
Data Warehouses (p.2644); Virtual Partitioning (p.4462); Database Clusters
(p.940); Parallel Query Processing (p.2677); Shared-Nothing Architecture
(p.3486).
