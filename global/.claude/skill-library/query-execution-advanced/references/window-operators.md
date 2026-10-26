# Window operators in an RDBMS

Scope: semantics of SQL window functions that the executor must reproduce
exactly, the physical evaluation pipeline (partition → order → frame →
function), algorithms for frame aggregates (incremental, segment tree,
monotonic deque), sharing sorts across multiple window functions,
parallelization, and optimizer uses of window functions.

---

## 1. Semantics the operator must implement

A window function computes, for every input row t, a value over a set of rows
related to t, without collapsing rows (unlike GROUP BY). Specification:

```
f(args) OVER (PARTITION BY p1,…  ORDER BY o1,…  frame_clause)
frame_clause := {ROWS | RANGE | GROUPS} BETWEEN start AND end [EXCLUDE …]
bound        := UNBOUNDED PRECEDING | n PRECEDING | CURRENT ROW
              | n FOLLOWING | UNBOUNDED FOLLOWING
```

First introduced with SQL:1999 and fully incorporated in SQL:2003 (Eisenberg
et al., SIGMOD Rec 2004); SQL:2011 broadened frame specifications (Zemke, SIGMOD Rec 2012). Early
precursor: SRQL, sorted relational query language for sequences (Ramakrishnan
et al., SSDBM 1998). Supported by Oracle (8i onward), DB2, SQL Server,
PostgreSQL and all modern analytic engines.

Typical use: a trailing moving average per group.

```sql
SELECT store_id, sale_date, revenue,
       AVG(revenue) OVER (PARTITION BY store_id ORDER BY sale_date
                          ROWS BETWEEN 29 PRECEDING AND CURRENT ROW) AS avg30
FROM daily_revenue;
```

Written without window functions this needs a correlated subquery or
self-join that re-reads up to 30 rows per output row; the window form is one
sort plus a sliding aggregate.

### Rules that cause most bugs

| Rule | Consequence |
|---|---|
| No PARTITION BY → one partition (the whole input) | Single-partition windows cannot be parallelised by partitioning (section 5) |
| No ORDER BY → frame defaults to the whole partition; ranking functions see all rows as peers | |
| ORDER BY present, no frame → `RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW` | The frame **includes all peers** (rows with equal ORDER BY keys) of the current row, so running sums jump at ties; ROWS-based implementations of the default are wrong |
| ROWS counts physical rows; RANGE uses ORDER BY key distance (offset needs exactly one numeric/temporal ORDER BY key); GROUPS counts peer groups | Three different frame-bound computations |
| `CURRENT ROW` in RANGE/GROUPS means "the current row's peer group boundary" | Start = first peer, end = last peer |
| Offsets must be non-negative constants (or parameters fixed per query) | Frames are monotone (section 3) — exploit it |
| EXCLUDE CURRENT ROW / GROUP / TIES / NO OTHERS | Frames can have holes; incremental algorithms must subtract the excluded part |
| Ranking functions (ROW_NUMBER, RANK, DENSE_RANK, PERCENT_RANK, CUME_DIST, NTILE) ignore the frame | Depend only on partition and order (and peers) |
| LEAD/LAG ignore the frame; offset is in rows within the partition, with default value when out of range | |
| FIRST_VALUE / LAST_VALUE / NTH_VALUE are frame-relative | `LAST_VALUE(x) OVER (ORDER BY o)` with the default frame returns the last *peer* of the current row, not the partition's last row — classic user and implementer surprise |
| Aggregates over a frame skip NULL inputs; empty frame → NULL (COUNT → 0) | Frames can be empty (e.g., `BETWEEN 3 PRECEDING AND 2 PRECEDING` at the partition start) |
| NULLs in the ORDER BY key sort per NULLS FIRST/LAST and form one peer group | Define and test RANGE-offset frames for NULL keys explicitly; common implementations (e.g., PostgreSQL) treat the NULL peer group as the frame for NULL rows |
| Window functions are evaluated after WHERE/GROUP BY/HAVING and before DISTINCT/ORDER BY/LIMIT of the query block | They cannot be referenced in WHERE of the same block; filtering on a rank needs an outer block (or QUALIFY in some dialects) |
| Determinism: ties in ORDER BY make ROW_NUMBER and ROWS frames non-deterministic | Tests must use total orders or compare only tie-insensitive outputs |

---

## 2. Physical evaluation pipeline

```
input ──► partition+sort on (P, O) ──► per partition:
              compute peer-group boundaries
              for each row: frame [start, end) (minus exclusions)
              evaluate f over frame
          ──► output (same rows, extra column(s)), ordered by (P, O)
```

1. **Partition and order.** Either a full sort on (P, O), or hash-partition on
   P into many buckets and sort each bucket on (P, O). The second form is
   cheaper (sorts of small buckets, cache-resident) and parallelises; output
   order is then by bucket, not globally by P, so the parent cannot assume P
   order unless it is restored.
2. **Peer boundaries.** One pass over the sorted partition marking where O
   changes (needed for RANGE/GROUPS/default frames and ranking functions).
3. **Frame bounds per row.** ROWS: arithmetic on row index, clamped to the
   partition. RANGE with offset: binary search or a moving pointer on the
   sorted key (`key ≥ cur − n`), respecting ASC/DESC. GROUPS: arithmetic on
   peer-group index.
4. **Evaluate.** Ranking/navigation functions are O(1) per row given row and
   peer indices. Frame aggregates use one of the algorithms in section 3.

Memory: operator is blocking per partition (it must see the partition's last
row before the first row's UNBOUNDED FOLLOWING or LAST_VALUE can be computed);
with only `… PRECEDING AND CURRENT ROW` style frames and no
peer-dependent functions it can stream with a bounded buffer. Huge partitions
must spill (buffer the partition on disk with random access by row index).

---

## 3. Frame aggregate algorithms

Let n be the partition size and w the frame width.

| Algorithm | Per-row cost | Works for | Notes |
|---|---|---|---|
| Naive recomputation | O(w) | anything | O(n·w); fine for tiny frames, quadratic for UNBOUNDED |
| Running (cumulative) aggregate | O(1) | frames with fixed start (UNBOUNDED PRECEDING) | Advance the end only; peer groups advance in steps |
| Removable (invertible) sliding aggregate | O(1) amortised | SUM, COUNT, AVG, and other aggregates with an inverse; monotone frames | Add entering rows, subtract leaving rows |
| Monotonic deque | O(1) amortised | MIN/MAX over monotone frames | Keep a deque of candidate indices with monotone values; pop dominated entries on insert, pop expired at front |
| Segment tree (Leis et al., VLDB 2015) | O(log n) | any associative aggregate, any frame (including non-monotone and EXCLUDE holes) | Build once per partition in O(n); query combines O(log n) nodes |
| Recompute per peer group | O(1) per row after one per group | default RANGE frames | Compute once per peer group, reuse for all peers |

### Incremental (sliding) evaluation

Frames with constant offsets are **monotone**: both start(i) and end(i) are
non-decreasing in i. So as i advances, rows only enter at the end and leave at
the start:

```
state = init()
s, e = 0, 0                       # current frame [s, e)
for i in partition rows:
    while e < end(i):   state = add(state, v[e]);    e += 1
    while s < start(i): state = remove(state, v[s]); s += 1
    out[i] = final(state)         # handle empty frame → NULL / 0
```

Pitfalls:
- `remove` must exist and be exact: integer/decimal SUM, COUNT are exact;
  floating SUM accumulates drift (catastrophic cancellation after removing a
  large value). Use compensated summation, periodic recomputation, or a
  segment tree for floats if bit-for-bit reproducibility with a recompute is
  required.
- NULLs: track a non-NULL count in the state so the result is NULL when every
  value in the frame is NULL.
- EXCLUDE clauses: subtract excluded rows' contribution after adding the frame
  (only for invertible aggregates), or switch to the segment tree.
- DISTINCT aggregates over frames (`COUNT(DISTINCT x) OVER (…)`) need a
  multiset (hash map of counts) as the state; still O(1) amortised add/remove.

### Segment tree

Leaves hold the partition's values in (P, O) order; each internal node holds
the aggregate of its children; fan-out f > 2 trades depth for node width and
cache behaviour. A frame [l, r) is answered by combining the O(f·log_f n)
nodes covering it. Requirements: associative combine with identity; no
inverse needed — so MIN/MAX, BIT_AND/OR, and floating sums (with consistent
association order) work for arbitrary frames. Build cost O(n) per partition,
memory O(n). Leis et al. combined this with parallel partitioning/sorting in
HyPer and showed it is robust across frame types where incremental methods
degrade (e.g., frames whose start does not move monotonically relative to a
cheaply removable state).

Other work exploiting frame overlap: PGWinFunc for PostgreSQL (Ma et al.,
ICDE 2015) — reuse partial results between overlapping frames.

---

## 4. Multiple window functions: sharing partitioning and sorting

A query with several window specifications w1…wm naively sorts once per
specification. Optimizations:

1. **Group specs that can share one sort** (Oracle 8i, Bellamkonda et al.,
   2000). A sort on key sequence K serves a spec (P, O) if some permutation
   of P followed by O (with matching ASC/DESC and NULLS placement on the O
   part) is a prefix of K — e.g., one sort on (a, b, c) serves
   `PARTITION BY a ORDER BY b`, `PARTITION BY b, a ORDER BY c`, and
   `PARTITION BY a, b, c`.
2. **Segmented sorts** (Cao, Chan, Li & Tan, VLDB 2012): if data is already
   sorted on (a, b) and the next spec needs (a, c), sort only within each
   a-segment (cheaper than a full re-sort); if it needs partitioning on a
   superset of the current grouping, no re-sort is needed. Cao et al. also
   frame the choice of spec order and sort keys as an optimization problem
   and add hash-partition-based reorderings to avoid unnecessary full sorts.
3. **Order the evaluation chain** so that the output order required by the
   query's ORDER BY falls out of the last window's sort.
4. **Evaluate several functions with the same spec in one pass** (one frame
   walk, multiple states).

Invariant: the multiset of output rows and every computed column must be
independent of the sharing strategy — test by evaluating each window function
in isolation and joining on a row identifier.

---

## 5. Parallel evaluation

- **Inter-partition parallelism:** hash-distribute on PARTITION BY keys;
  each worker sorts and evaluates its partitions independently (Oracle's
  third technique in the 8i paper). Breaks down when the number of distinct
  partitions is below the degree of parallelism or partitions are skewed.
- **Range distribution on (P, O)** for few/huge partitions (Bellamkonda et
  al., VLDB 2013): split even a single partition across workers by order-key
  ranges; each worker computes local results and boundary information
  (running totals, ranks at the start of its range, the last rows needed for
  preceding frames) that are exchanged and applied as a fix-up.
- **Intra-partition parallelism with segment trees** (Leis et al.): build the
  tree in parallel and let workers evaluate disjoint row ranges of a large
  partition, since segment-tree queries are read-only.
- Ranking functions under range distribution: worker j adds the count of rows
  in workers < j of the same partition to ROW_NUMBER/RANK; DENSE_RANK must
  also account for a peer group spanning the boundary (do not double count).

---

## 6. Optimizer interactions

- **Rank predicate pushdown** (Oracle 8i): `WHERE rn <= k` over
  `ROW_NUMBER() OVER (PARTITION BY p ORDER BY o)` becomes a per-partition
  top-k: keep at most k rows per partition during the sort (bounded heap per
  partition) and stop emitting a partition after k rows. Valid for
  ROW_NUMBER; for RANK/DENSE_RANK keep ties at the boundary.
- **Predicate pushdown through windows:** a filter on PARTITION BY columns
  can be pushed below the window operator (it removes whole partitions);
  filters on other columns cannot (they change frames).
- **Subquery elimination with window aggregates** (WinMagic, Zuzarte et al.,
  SIGMOD 2003; Oracle, Bellamkonda et al., VLDB 2009): a correlated aggregate
  subquery over the same table as the outer block, e.g. "employees earning
  more than their department's average", becomes
  `AVG(sal) OVER (PARTITION BY dept)` plus a filter — one scan instead of a
  join or per-row subquery. Valid only when the subquery's FROM and WHERE
  match the outer block's (same rows per partition), modulo the correlation
  predicate that becomes the PARTITION BY.
- **Self-join elimination:** LAG/LEAD replace self-joins on "previous row"
  conditions when the join key is the ORDER BY position.

---

## 7. Tests

- Differential oracle: naive O(n·w) evaluator implementing the standard rules
  of section 1 literally; compare against the optimized operator on random
  data with heavy ties, NULL order keys, NULL argument values, empty frames,
  frames entirely outside the partition, EXCLUDE variants and all three frame
  units.
- Property: for invertible aggregates, incremental == segment tree ==
  naive (exact types); for floats, within tolerance.
- Partition size sweep: 0, 1, 2, cache-sized, larger than memory (spill).
- Parallel equivalence: DOP 1 vs N with a single partition and with skewed
  partitions; especially ROW_NUMBER, DENSE_RANK and running sums at range
  boundaries.
- Sort-sharing equivalence (section 4 invariant).
- Plan tests: a rank filter produces a per-partition top-k plan; a filter on
  PARTITION BY columns is pushed below the window.

Sources: EDBS entry Window Operator in RDBMS (p.4693); related to Evaluation
of Relational Operators (p.1348) for sort and aggregation machinery.
