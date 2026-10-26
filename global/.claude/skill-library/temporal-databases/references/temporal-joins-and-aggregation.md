# Temporal joins and temporal aggregation

The two operators that dominate cost in temporal workloads. Both are hard for
a conventional engine for the same reason: the time predicate is an
**inequality** (interval overlap), not an equality, so hash and plain
merge join do not apply directly, and temporal relations are larger than
their snapshot counterparts because they keep versions.

Notation: `r(A, Ts, Te)`, `s(B, Ts, Te)`, half-open periods `T = [Ts, Te)`;
`overlap(U,V) = [max(Us,Vs), min(Ue,Ve))` if `max(Us,Vs) < min(Ue,Ve)`,
else empty.

---

## Part I — Temporal joins

### 1. Operator definitions (Gao, Snodgrass, Jensen, Soo, VLDB J 2005)

Each conventional join has a temporal counterpart defined so that it behaves
like the conventional join applied independently at each instant.

| Operator | Definition |
|---|---|
| Temporal Cartesian product `r ×ᵀ s` | `{ (x.A, y.B, overlap(x.T, y.T)) | x∈r, y∈s, overlap ≠ ∅ }` |
| Temporal θ-join `r ⋈ᵀ_P s` | `σ_P(r ×ᵀ s)`, `P` over explicit attributes |
| Temporal equijoin | θ-join with `P: r[A'] = s[B']` |
| Temporal natural join `r ⋈ᵀ s` | equijoin on shared explicit attributes `C`, then project one copy of `C`; timestamp = overlap |
| Temporal left outer join | for each coalesced `x`: overlaps with matching coalesced `y` emitted as joined tuples; the **maximal parts of `x.T` not covered by any match** emitted with nulls |
| Temporal full outer join | union of left and right outer joins |
| Outer Cartesian product | outer join with an empty join condition |

The intersection (`overlap`) timestamp is both necessary and sufficient for
snapshot reducibility. The outer joins need two helpers: `coalesce(r)`
(merge value-equivalent tuples into temporal elements) and `expand(T)` (split
a temporal element into its maximal periods). The subtlety: a tuple can be
matched over part of its lifetime and dangle over the rest, so outer joins
emit *partial* dangling tuples, and must coalesce inputs first or they emit
spurious dangling fragments between adjacent value-equivalent pieces.

Snapshot reducibility theorem (proved in Gao et al.): for every chronon `t`,

```
τ_t(r ×ᵀ s)  = τ_t(r) × τ_t(s)        τ_t(r ⋈ᵀ_P s) = τ_t(r) ⋈_P τ_t(s)
τ_t(r ⋈ᵀ s)  = τ_t(r) ⋈ τ_t(s)        τ_t(r ⟕ᵀ s)   = τ_t(r) ⟕ τ_t(s)
τ_t(r ⟗ᵀ s)  = τ_t(r) ⟗ τ_t(s)
```

This is the test oracle: for random `r`, `s` and every `t` in the active
domain, slice the result and compare with the snapshot join.

Worked example (half-open periods):

```
Employee(EmpName, Dept, T)          Manages(Dept, MgrName, T)
  Ron     Ship  [1,6)                 Load  Ed   [3,9)
  George  Ship  [5,10)                Ship  Jim  [7,16)
  Ron     Mail  [6,11)

Employee ×ᵀ Manages:                Employee ⋈ᵀ Manages (on Dept):
  Ron    Ship Load Ed  [3,6)          George Ship Jim [7,10)
  George Ship Load Ed  [5,9)
  George Ship Ship Jim [7,10)       Employee ⟕ᵀ Manages (on Dept):
  Ron    Mail Load Ed  [6,9)          Ron    Ship null [1,6)
  Ron    Mail Ship Jim [7,11)         George Ship null [5,7)
                                      George Ship Jim  [7,10)
                                      Ron    Mail null [6,11)
```

Join variants found in the literature map onto this taxonomy: Clifford &
Croker's θ/equi/natural joins and time-join, Gunadhi & Segev's T-join,
Segev & Gunadhi's TE-join, TE-outerjoin and event join (matching on
surrogates only), TSQL2's valid-time θ- and left joins, Zhang/Tsotras/Seeger's
GTE-join (surrogate range plus time range). Clifford proposed one
*intersection join* for all inner variants and a *union join* for the outer
ones. Joins with other Allen conditions (before, after, meets) exist but
almost all algorithmic work targets overlap.

The temporal natural join is what reconstructs a normalised temporal schema
(the temporal analogue of lossless-join decomposition); it is the operator
to optimise first.

### 2. Evaluation algorithms

Two families: **non-index** (nested loop, sort-merge/sweep, partition) and
**index-based** (probe an interval access path). Gao et al. provide a
taxonomy and experimental comparison of the non-index algorithms; consult
it for which wins under which data characteristics (interval length
distribution, presortedness, memory).

#### 2.1 Nested loop

Predicate: `θ(x,y) ∧ x.Ts < y.Te ∧ y.Ts < x.Te`. Block nested loop:
`O(|r|·|s|)` comparisons, `O(b_r + b_r·b_s / M)` I/O. Always correct; the
baseline and the fallback for arbitrary θ.

#### 2.2 Equi-key first, then time

When there is an explicit equijoin key (natural join on a surrogate / entity
id): hash or sort on the key, then evaluate overlap within each key group.
Within a group, **sort by Ts and sweep** (2.3) instead of a nested loop: a
key with a long history (thousands of versions) makes the per-bucket nested
loop quadratic. Skew in history length per key is the main risk; detect it
from per-key version counts.

#### 2.3 Sort-merge / plane sweep on start time

Sort both inputs by `Ts`. Sweep in start order, keeping an *active set* per
input (tuples whose period contains the sweep position):

```
merge r and s by Ts (ties: any fixed order)
for next tuple x (from r, say):
    evict from active_s every y with y.Te <= x.Ts
    for y in active_s: if θ(x,y): emit (x, y, [x.Ts, min(x.Te, y.Te)))
    insert x into active_r
(symmetric for tuples from s)
```

Correctness: for a pair with `x.Ts ≥ y.Ts`, the pair overlaps iff `y.Te >
x.Ts` (the other condition `x.Te > y.Ts` is implied), and that is exactly
"`y` is still active when `x` arrives". Each overlapping pair is emitted once,
when its later-starting member arrives.

Cost: `O(n log n)` sort + output + active-set maintenance. The weak spot is
**long-lived tuples**: they stay in the active set for a long time, inflating
memory and the number of non-matching θ comparisons; a merge join on
`Ts` alone has to "back up" over them, which is why plain merge join is a poor
fit. With an equijoin key, keep a hash map `key → active list` so only same-key
candidates are scanned. Active sets that exceed memory must spill (keep them
ordered by `Te` so eviction is a prefix pop).

> **Beyond EDBS:** Two refinements worth knowing. *Forward scan* (Bouros &
> Mamoulis, VLDB 2017): no active lists; for each tuple `x` in start order,
> scan the other sorted input forward from the current position while
> `y.Ts < x.Te`; every scanned `y` is a result (the earlier-starting member
> finds its partners), so comparisons ≈ output + n; the paper also gives
> grouping/bucketing optimisations and a parallel version. *Endpoint-based
> interval join* (Piatov, Helmer & Dignös, ICDE 2016): sweep over a sorted
> endpoint index with cache-friendly active-tuple maps, tuned for main-memory
> hardware.

#### 2.4 Partition-based

Split the time line into `k` ranges `[p_i, p_{i+1})` (boundaries from a sample
so partitions hold similar numbers of tuples). Join partition by partition.
Long tuples span several partitions; two ways to handle them:

- **Replicate** a tuple into every partition it overlaps; join locally; avoid
  duplicate results with the **reference-point rule**: emit a pair only in the
  partition containing `max(x.Ts, y.Ts)` (the start of the intersection).
  Replication factor ≈ `1 + avg_length / partition_width`.
- **No replication**: store each tuple in a single partition (e.g., chosen by
  one of its endpoints) and, while processing partitions in order, carry tuples
  that also overlap partitions yet to be processed in an in-memory *tuple
  cache* (Soo, Jensen & Snodgrass, ICDE 1994; a related spatial-partitioning
  approach is Lu, Ooi & Tan, VLDB 1994).

Partitioning parallelises naturally (partition = unit of work) and bounds
memory, at the price of replication or cache pressure from long tuples.

> **Beyond EDBS:** Overlap Interval Partition join (Dignös, Böhlen & Gamper,
> SIGMOD 2014) partitions by the pair (first granule, last granule) a tuple
> touches, so tuples in a partition have similar extents, no tuple is
> replicated, and only partitions whose spans overlap are joined; the number
> of granules is chosen adaptively.

#### 2.5 Index-based

Probe an interval access path on the inner for each outer tuple
(index nested loop), or join two indexes synchronously.

| Access path | Overlap probe | Notes |
|---|---|---|
| B-tree on `(key, Ts)` | range `Ts < q.Te`, residual `Te > q.Ts` | cost grows with history before `q`; bad for old probes on long histories |
| B-tree on `(key, Te)` | range `Te > q.Ts`, residual `Ts < q.Te` | good for recent probes; bad for future-dated data |
| 2-D index on point `(Ts, Te)` (R-tree, kd-tree, quadtree) | dominance query `Ts < q.Te ∧ Te > q.Ts` | handles both; R-tree overlap degrades with many long intervals |
| interval tree / segment tree | stabbing/overlap in `O(log n + k)` | main-memory |
| Relational Interval Tree (Kriegel, Pötke & Seidl, VLDB 2000) | interval tree mapped onto two B+-trees | works inside an unmodified RDBMS |
| TSB-tree, MVB-tree (transaction time) | key-time rectangles | Zhang, Tsotras & Seeger (ICDE 2002) join using such multiversion indexes |
| now-relative indexes | split by fixed vs growing end | see `time-models-and-semantics.md` §7 |

> **Beyond EDBS:** The Timeline Index (Kaufmann et al., SIGMOD 2013, SAP
> HANA) stores, per table, an event list of (version-id, activate/invalidate)
> ordered by time plus periodic checkpoints of the active set; temporal
> joins, time travel and temporal aggregation become merges over event lists.

### 3. Cardinality estimation for overlap predicates

Exact identity worth building into the estimator. For a query period
`[qs, qe)` over a relation of non-empty periods:

```
#{ x : x overlaps [qs,qe) } = #{ x : x.Ts < qe } − #{ x : x.Te <= qs }
```

(every tuple with `Te ≤ qs` also has `Ts < qe`, so the subtraction is exact).
The stabbing count at instant `t` is `#{Ts ≤ t} − #{Te ≤ t}`. Hence two
**1-D histograms (on Ts and on Te) give exact-in-the-limit overlap
selectivities**; assuming independence between `Ts` and `Te` (multiplying
`P(Ts<qe)·P(Te>qs)`) is wrong because the two are strongly correlated.

Join size: `|r ⋈ᵀ s| = Σ_{x∈r} (N_s^start(< x.Te) − N_s^end(≤ x.Ts))`, which
can be estimated by convolving histograms. Back-of-envelope with uniform
placement over a window `W` and mean lengths `L_r, L_s ≪ W`:
`|r ⋈ᵀ s| ≈ |r|·|s|·(L_r + L_s)/W` (times the equi-key selectivity). Tuples
with open end (`now`/sentinel) overlap every later probe: estimate them as a
separate class.

### 4. Planner checklist

- Recognise the overlap pattern `a.s < b.e AND b.s < a.e` (and SQL:2011
  `OVERLAPS`) as a join *kind*, not as two independent range predicates.
- Prefer equi-key + sweep when an equality key exists; sweep or partition
  when the predicate is pure overlap.
- Track physical properties: sorted on `(key, Ts)` (enables sweep and
  coalescing without re-sort), coalesced, open-ended fraction.
- Push timeslices (`AS OF`, `CONTAINS t`) below the join; they are cheap and
  turn temporal joins into snapshot joins.

---

## Part II — Temporal aggregation

### 5. Forms

Grouping is by explicit attributes **and** by time; how the time line is
partitioned defines the form.

| Form | Aggregation group at `t` (or per span) | Result timestamps |
|---|---|---|
| Instantaneous (ITA) | tuples whose period contains `t` | maximal *constant intervals* (data-dependent); optionally split further so each result has a single lineage (same contributing set) |
| Moving-window / cumulative (MWTA) | tuples valid at some point in `[t − w, t]` (or `[t − w, t + w']`) | constant intervals |
| Span (STA) | tuples overlapping each predefined span (week, month, user-defined) | the spans themselves, data-independent |
| Multi-dimensional (MDTA, Böhlen, Gamper & Jensen EDBT 2006) | result groups decoupled from aggregation groups; constant-interval semantics (covers ITA, MWTA) or fixed-interval semantics with arbitrary, possibly overlapping intervals (covers STA) | as specified |

Facts:

- ITA output can be up to about **2×** the input: `n` tuples have at most
  `2n` distinct endpoints, hence at most `2n − 1` elementary intervals.
- ITA is exactly sequenced semantics applied to `GROUP BY` (`SEQ VT SELECT
  COUNT(*) ...`), so it inherits snapshot reducibility. TSQL2:
  `GROUP BY VALID(r) USING INSTANT`; nonsequenced count needs `SELECT
  SNAPSHOT COUNT(*)`.
- For MWTA with fixed `w`, a tuple `[s, e)` contributes at `t` iff `s ≤ t`
  and `e > t − w`, i.e., iff `t ∈ [s, e + w)`: **extend each end by `w` and
  run ITA**.
- STA with regular spans: a tuple contributes to span indexes
  `⌊s/W⌋ … ⌊(e−1)/W⌋`; with calendar spans use the granularity index
  function. Duration-weighted aggregates (TSQL2 supports weighting values by
  duration) multiply by `|T ∩ span|`.
- Writing ITA in plain SQL takes around two dozen lines of nested `NOT
  EXISTS` and is evaluated badly; this is the strongest argument for a native
  operator.

TSQL2 extended all SQL-92 aggregates to temporal grouping, added
duration weighting and a new `RISING` aggregate, and its aggregate taxonomy
identifies 14 kinds.

### 6. Algorithms

| Algorithm | Structure | Time | Memory | Notes |
|---|---|---|---|---|
| Two scans (Tuma 1992) | scan 1: constant intervals; scan 2: aggregate per interval | `O(m·n)` | result | first ITA algorithm |
| Aggregation tree (Kline & Snodgrass, ICDE 1995) | unbalanced binary tree of intervals with partial aggregates, built in one scan; DFS emits results in time order | `O(n²)` worst (unbalanced) | main memory | k-ordered variant garbage-collects nodes left of the sweep when input is nearly sorted; basis of parallel algorithms (Gao et al., DPDB 2004) |
| Balanced tree (Moon, Vega Lopez & Immanuel, TKDE 2003) | balanced tree keyed by endpoints; per node: partial aggregate of tuples starting and of tuples ending there; in-order traversal accumulates | `O(n log n)` for SUM/COUNT/AVG | main memory | MIN/MAX via a merge-sort-style algorithm; *bucket* variant partitions time and keeps long-lived tuples in a meta-array to fit memory |
| SB-tree (Yang & Widom, VLDB J 2003) | disk-based segment-tree/B-tree hybrid holding intervals with partial aggregates | point `O(h)`; range `O(h + r)` | disk | incremental maintenance; MWTA via end extension (fixed `w`) or a pair of SB-trees (arbitrary `w`) |
| MVSB-tree (Zhang et al., PODS 2001) | logically one SB-tree per timestamp | log | can exceed data size | adds a range predicate on one non-temporal attribute; Tao, Papadias & Faloutsos (ICDE 2004) give approximate linear-space, log-time alternatives |
| MDTA fixed-interval (Böhlen et al.) | group table, one row per result group | avg `O(n log m)`, worst `O(n·m)` | result size | each tuple updates every group it contributes to |
| MDTA constant-interval | endpoint tree of currently valid tuples keyed by end | avg `O(n·n_o)`, worst `O(n²)` | max overlap `n_o` | emits results as time advances |

#### The endpoint sweep (what to implement in a vectorised executor)

```
events = [(x.Ts, +x) for x in r] ++ [(x.Te, −x) for x in r]   # per group G
sort events by time
state = empty; prev = None
for each distinct time t in events (all events at t applied together):
    if prev is not None and state is non-empty:
        emit (G, agg(state), [prev, t))
    apply all +x / −x at t to state
    prev = t
```

- COUNT/SUM/AVG: `state` is a running (count, sum) — `O(1)` per event,
  `O(n log n)` total dominated by the sort; this is the balanced-tree
  algorithm in streaming form.
- MIN/MAX: need deletions — use an ordered multiset or a heap with lazy
  deletion, `O(log n)` per event.
- COUNT DISTINCT: hash multiset of values.
- Constant-interval (coalesced) output: merge consecutive emits with equal
  aggregate values. Lineage-preserving output: emit at every event time even
  if the value is unchanged.
- Gaps: whether to emit `COUNT = 0` rows for empty elementary intervals is a
  semantic choice (some languages emit nothing when no tuple is valid);
  decide and document.
- Partition by grouping attributes `G` first (hash), then sweep each group;
  parallelises across groups. Time-range parallelism: clip tuples to each
  worker's range (replicating long ones), sweep locally, concatenate, and
  merge equal-valued neighbours at boundaries if coalesced output is wanted.

> **Beyond EDBS:** The same sweep is expressible with window functions in
> any modern SQL engine:
> ```sql
> WITH ev AS (SELECT ts AS t, 1 AS d FROM r UNION ALL SELECT te, -1 FROM r),
>      c  AS (SELECT t, SUM(SUM(d)) OVER (ORDER BY t) AS cnt,
>                    LEAD(t) OVER (ORDER BY t) AS nxt
>             FROM ev GROUP BY t)
> SELECT cnt, t AS ts, nxt AS te FROM c WHERE nxt IS NOT NULL AND cnt > 0;
> ```
> Add `PARTITION BY g` for grouped ITA. Only invertible aggregates work this
> way; MIN/MAX need the native operator.

### 7. Where temporal aggregation shows up

Data warehouses (time variance is a defining property; years of
time-referenced facts) and stream processing (windowed aggregates are ITA/MWTA
over a transaction-time-like stream). Spatio-temporal aggregation (Vega
Lopez, Snodgrass & Moon, TKDE 2005) generalises the problem. See also
`stream-processing-engines` and `olap-and-warehouse-engines`.

Sources: EDBS entries Temporal Joins (p.3986), Temporal Aggregation
(p.3899), Temporal Query Processing (p.4028), Temporal Algebras (p.3905),
SQL-Based Temporal Query Languages (p.3683), TSQL2 (p.4246), Now in
Temporal Databases (p.2517), Period-Stamped Temporal Models (p.2742).
