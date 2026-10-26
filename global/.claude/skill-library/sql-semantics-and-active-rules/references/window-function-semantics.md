# Window function semantics — the contract the binder and executor must honour

Window ("analytic OLAP") functions compute, for every input row, a value over
a set of related rows without collapsing them. They entered with the SQL:1999
OLAP amendment, were fully integrated in SQL:2003, and were extended in
SQL:2011 (navigation functions, GROUPS frames). This file fixes the semantics
precisely; physical evaluation (sort sharing, segment trees, parallelism) is
summarised in §7 and covered in depth in `query-execution-advanced`
(references/window-operators.md).

---

## 1. Anatomy and logical position

```
fn(args) [FILTER (WHERE p)] [IGNORE|RESPECT NULLS]
  OVER ( [existing_window_name]
         [PARTITION BY e1, …]
         [ORDER BY k1 [ASC|DESC] [NULLS FIRST|LAST], …]
         [ {ROWS|RANGE|GROUPS} frame_extent [EXCLUDE …] ] )
```

Logical evaluation order of a query block:

```
FROM/JOIN → WHERE → GROUP BY → HAVING → WINDOW → SELECT-list exprs
         → DISTINCT → ORDER BY → OFFSET/FETCH        (QUALIFY, where supported, after WINDOW)
```

Consequences the binder must enforce:
1. Window functions may appear only in the SELECT list and ORDER BY — never
   in WHERE, GROUP BY, HAVING, or inside another window function's arguments
   (G11). Filtering on them needs a derived table (G15) or `QUALIFY`
   (Teradata, Snowflake, DuckDB, BigQuery).
2. In a grouped query, window arguments and PARTITION/ORDER keys range over
   the *grouped* rows, so aggregates may be nested inside: `SUM(SUM(v)) OVER ()`
   (G10). Non-grouped columns are illegal inside the window, just as in the
   SELECT list.
3. `DISTINCT` runs after windows: `SELECT DISTINCT row_number() OVER () …`
   de-duplicates nothing.
4. The window's ORDER BY does not order the query output; only the outer
   ORDER BY does. Tests that rely on window order for output order are flaky.

## 2. Partitions, ordering and peers

- **Partition**: rows equal on the PARTITION BY keys under NOT DISTINCT
  semantics — all NULL keys form one partition. No PARTITION BY → one
  partition.
- **Ordering**: sorts each partition; NULL placement follows NULLS FIRST/LAST
  or the engine default (must match the engine's ORDER BY default).
- **Peers**: rows of a partition that are not distinct on *all* window ORDER BY
  keys. Without ORDER BY, every row of the partition is a peer of every other.
  Peers are the unit for RANGE and GROUPS frames, for RANK/DENSE_RANK/
  CUME_DIST/PERCENT_RANK, and for EXCLUDE GROUP/TIES.

## 3. Frames

### 3.1 Defaults (the single most important rule)

| Window has ORDER BY? | Default frame |
|---|---|
| no | the whole partition (`RANGE BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING`) |
| yes | `RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW` — i.e. up to and **including all peers** of the current row |

So a "running sum" ordered by a non-unique key gives peers the same value
(G1), and `LAST_VALUE(v) OVER (ORDER BY k)` returns the last *peer* of the
current row — with a unique key, the current row itself (G4). Both are user
surprises but correct; an engine that implements the default as ROWS is
wrong.

### 3.2 Units

| Unit | `n PRECEDING/FOLLOWING` means | `CURRENT ROW` as start / end |
|---|---|---|
| ROWS | n physical rows away | exactly the current row |
| RANGE | rows whose ORDER BY key is within n of the current key (key arithmetic) | first / last peer |
| GROUPS (SQL:2011) | n peer groups away | first / last peer of current group |

Legality rules (raise a syntax/semantic error otherwise):
- `RANGE` with an offset requires **exactly one** ORDER BY key whose type
  supports `key ± offset` (numeric with numeric offset, datetime with interval).
  RANGE with only UNBOUNDED/CURRENT ROW bounds accepts any keys.
- `GROUPS` requires an ORDER BY.
- Offsets must be constant (no column references, aggregates or window
  calls), non-NULL and **non-negative** (PostgreSQL raises 22013 for a negative
  ROWS offset; DuckDB 1.1 accepts it — G14).
- The start bound may not be `UNBOUNDED FOLLOWING`; the end bound may not be
  `UNBOUNDED PRECEDING`; a start of `CURRENT ROW` cannot have an end of
  `n PRECEDING`; a start of `n FOLLOWING` cannot have an end of `CURRENT ROW` or
  `n PRECEDING`.
- Short form `ROWS n PRECEDING` ≡ `ROWS BETWEEN n PRECEDING AND CURRENT ROW`.
- An offset frame can legitimately be **empty** (e.g. `ROWS BETWEEN 2
  FOLLOWING AND 3 FOLLOWING` at the last row, or `3 PRECEDING AND 5 PRECEDING`);
  aggregates then return their empty-input value: SUM → NULL, COUNT → 0
  (G12).

### 3.3 RANGE corner cases
- **NULL keys**: NULL ± offset is undefined, so the frame bound for a row
  whose key is NULL is taken to be its NULL peer group; for non-NULL rows, NULL
  rows never fall inside an offset bound. Whether UNBOUNDED PRECEDING reaches
  them depends on NULLS FIRST/LAST (G13).
- **Overflow**: `key + offset` near the type maximum must behave as +∞ (the
  frame extends to the partition end), not raise or wrap. PostgreSQL's
  `in_range` support functions encode this explicitly; build the same rule
  into your comparator rather than computing `key + offset` naively.
- **DESC ordering**: PRECEDING means larger keys. Implement bound search in
  terms of the sort direction, not raw arithmetic.
- Floating keys: NaN/±Infinity must have a defined position consistent with
  ORDER BY.

### 3.4 Frame exclusion (EXCLUDE)

| Option | Removes from the frame |
|---|---|
| `EXCLUDE NO OTHERS` (default) | nothing |
| `EXCLUDE CURRENT ROW` | the current row |
| `EXCLUDE GROUP` | the current row and all its peers |
| `EXCLUDE TIES` | the peers of the current row, but keeps the current row |

Vector G7 checks all three on a partition with a tie. Exclusion makes the
frame non-contiguous, which breaks naive sliding-window algorithms (handle as
"frame minus at most two sub-ranges" or fall back to segment-tree queries).

## 4. Function families

| Function | Uses frame? | Definition (n = partition size) |
|---|---|---|
| `ROW_NUMBER()` | no | 1..n in window order; arbitrary among peers |
| `RANK()` | no | 1 + number of rows strictly before the current peer group (gaps) |
| `DENSE_RANK()` | no | number of distinct peer groups up to and including the current one |
| `PERCENT_RANK()` | no | (RANK − 1)/(n − 1); 0 when n = 1 |
| `CUME_DIST()` | no | (rows before or peer with current)/n |
| `NTILE(k)` | no | buckets of size ⌊n/k⌋ or ⌈n/k⌉, larger buckets first (G9) |
| `LAG(e [,off [,default]])`, `LEAD(…)` | no | value `off` rows back/forward within the partition; default NULL when outside (G8) |
| `FIRST_VALUE`, `LAST_VALUE`, `NTH_VALUE(e, n) [FROM FIRST|LAST]` | **yes** | positional within the frame; NULL if the frame is too small |
| aggregates (`SUM`, `COUNT`, `AVG`, `MIN`, `MAX`, …) | **yes** | aggregate over the frame (after FILTER) |

Vectors G5 show the ranking family both with a total order (ties broken) and
with peers.

Further rules:
- `IGNORE NULLS` (navigation and value functions) skips NULL values when
  counting offsets/positions; `RESPECT NULLS` is the default. Supported by
  Oracle, Snowflake, DuckDB and others; not by PostgreSQL up to 16.
- `COUNT(DISTINCT x) OVER (…)` is not supported by PostgreSQL; Oracle allows
  DISTINCT aggregates only without a window ORDER BY. Decide and document.
- **Determinism**: `ROW_NUMBER`, `ROWS` frames, `FIRST_VALUE/LAST_VALUE/
  NTH_VALUE` and `LAG/LEAD` are non-deterministic when the window order is not
  total. Parallel or re-sorted plans may legitimately change the result; tests
  must use a total order.
- Ranking functions ignore any frame clause (some engines reject one).

## 5. Named windows

`WINDOW w AS (PARTITION BY g ORDER BY o)` then `OVER w` or `OVER (w …)`.
Copy rules (standard/PostgreSQL): the referencing specification inherits the
referenced PARTITION BY and may not add its own; it may add ORDER BY only if
the referenced window has none; the referenced window must not have a frame
clause if anything is added. Several window calls with identical
specifications must be detected so they share one sort/partition pass.

## 6. Equivalences the optimizer may use (and their guards)

| Rewrite | Guard |
|---|---|
| `WHERE rn <= k` over `ROW_NUMBER() OVER (PARTITION BY p ORDER BY o)` → per-partition top-k (heap) | filter is on rn with ≤/< /=; also usable for RANK with ties kept |
| Predicate push-down below the window | predicate references only PARTITION BY columns (filters whole partitions) |
| Share one sort among windows | their (PARTITION BY ∪ ORDER BY) keys are compatible prefixes — choose an order that covers the most windows |
| Correlated aggregate subquery → window aggregate (WinMagic, SIGMOD 2003; Oracle 2009) | the subquery aggregates the same table on the correlation keys; bag semantics preserved |
| Self-join "moving average" → `AVG … ROWS BETWEEN 6 PRECEDING AND CURRENT ROW` | ordering key per group is unique (the self-join form groups by key values, ROWS by rows) |
| Eliminate a window whose output is unused | always |

Pushing a predicate on a non-partition column below a window changes frames
and is illegal — a common optimizer bug.

## 7. Evaluation (summary — see `query-execution-advanced`)

1. Hash-partition (for parallelism) then sort by (PARTITION BY, ORDER BY), or
   sort once on the concatenated key. Order windows so consecutive ones reuse
   sort order (Cao, Chan, Li & Tan, VLDB 2012; Oracle's grouping of window
   functions by sort, Bellamkonda et al. 2000).
2. Within a partition compute peer-group boundaries once (vector of group
   starts), then frame bounds per row: ROWS by index arithmetic; RANGE by a
   monotone two-pointer search on the key; GROUPS by peer-group indices.
3. Aggregate per frame:
   - frames anchored at UNBOUNDED PRECEDING: running accumulation, O(n);
   - sliding frames with invertible aggregates (SUM, COUNT, AVG): add/remove,
     O(n) — but only for exact arithmetic (inverse transitions on floats drift;
     PostgreSQL only uses moving-aggregate inverses where they are exact);
   - MIN/MAX on monotonic sliding frames: monotone deque, amortised O(n);
   - arbitrary frames, EXCLUDE, or non-invertible aggregates: **segment tree**
     over the partition, O(n log n) total (Leis, Kundhikanjana, Kemper &
     Neumann, VLDB 2015), which also parallelises within a large partition.
4. Few large partitions starve parallelism; parallelise inside partitions
   (segment tree, range-partitioned sort) as in Leis et al. 2015 and
   Bellamkonda et al. VLDB 2013.

## 8. Classic bugs and how to catch them

| Bug | Detect with |
|---|---|
| Default frame implemented as ROWS (peers get different running sums) | G1 |
| LAST_VALUE/NTH_VALUE ignore the frame or use the partition | G4 |
| RANGE offset uses row counts, or GROUPS treated as RANGE | G6 (o = 1,2,2,5) |
| NULL ordering key crashes or joins neighbouring frames | G13 |
| Empty frame returns 0 for SUM | G12 |
| EXCLUDE TIES drops the current row | G7 |
| Predicate on a non-partition column pushed below the window | compare plans with/without push-down on random data |
| Sort shared between windows with incompatible NULLS FIRST/LAST or collation | windows differing only in null ordering |
| Overflow in `key + offset` at INT_MAX / timestamp max | keys at type extremes with `1 FOLLOWING` |
| Window over grouped input binds to pre-aggregation columns | G10 |

Oracle: run every window query also as its correlated-subquery definition (the
"semantic expansion" — for each row, aggregate over rows satisfying the frame
predicate) on small random tables with duplicates and NULLs; results must match
exactly when the window order is total.

---

Sources: Window Operator in RDBMS (p.4693); SQL (p.3666) — OLAP/WINDOW
facility. Frame-legality details, EXCLUDE, NULL/overflow handling and dialect
notes are > **Beyond EDBS** (standard text and PostgreSQL/DuckDB behaviour,
verified for the cases covered by the test vectors).
