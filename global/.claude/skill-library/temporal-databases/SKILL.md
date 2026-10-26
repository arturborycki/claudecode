---
name: temporal-databases
description: "Use when designing, implementing or reviewing temporal data support inside a database engine: valid-time, transaction-time and bitemporal tables, SQL:2011 application-time periods and system-versioned tables, sequenced/current/nonsequenced semantics, coalescing, temporal joins and aggregation, temporal keys, history storage and expiry. Triggers on temporal table, bitemporal, valid time, transaction time, system time, application time, SYSTEM_TIME, FOR SYSTEM_TIME AS OF, FOR PORTION OF, WITHOUT OVERLAPS, PERIOD FOR, time travel, as-of query, history table, timeslice, coalesce/normalize periods, interval overlap join, temporal aggregation, chronon, granularity, now/until changed, TSQL2, Allen relations, temporal vacuuming, schema versioning. Apply even when phrased as 'keep row history', 'effective dating', 'slowly changing dimension', 'gaps and islands', or 'query the table as it was last month'."
---

# Temporal Databases

This skill owns time as an engine feature: period representation, temporal
statement semantics, the operators (timeslice, coalesce, overlap join,
temporal aggregation and difference), sequenced keys, and how transaction-time
history is stamped, stored, indexed and expired. Central idea: **a temporal
relation means a sequence of snapshots but is stored as periods; every
operator must be correct per snapshot and explicit about which
snapshot-equivalent encoding it returns.**

## Mental model

- Three time lines: **valid time** (true in reality; user-supplied, past and
  future, correctable), **transaction time** (current in the database;
  DBMS-supplied, append-only, never future, serialization-consistent),
  **user-defined time** (ordinary column). Bitemporal = VT × TT rectangles.
- Time = discrete, bounded, linear **chronons**; granularities map integers
  to chronon sets; periods are half-open `[s, e)` (SQL:2011).
- Equal snapshots = **snapshot equivalent**; **coalescing** picks the
  canonical encoding (maximal periods per value class), the temporal DISTINCT.
- Semantics: **current** (plain SQL sees `τ_now`), **sequenced** (evaluate per
  snapshot, keep argument timestamps), **nonsequenced** (timestamps are plain
  attributes); statement modifiers (`SEQ VT`, `NSEQ VT`) choose per statement.
- Sequenced operators are implemented by **reduction**: split tuples at the
  relevant change points (normalization/alignment), then run ordinary
  operators with the period as an extra attribute. Joins need only overlap +
  intersection; difference, DISTINCT, union and aggregation need splits.
- Transaction time = MVCC that never forgets (version chains, serialization-
  ordered commit stamps, time-aware index, explicit **vacuuming**).

## Core invariants

1. Every stored period is non-empty (`s < e`), including every piece produced
   by `FOR PORTION OF`, difference or normalization.
2. **Snapshot reducibility**: for every sequenced `opᵀ` and chronon `t`,
   `τ_t(opᵀ(r, s)) = op(τ_t(r), τ_t(s))`.
3. **Current semantics**: enabling temporal support never changes the result
   of a statement that uses no temporal syntax.
4. **Interval preservation**: no operator coalesces implicitly unless the
   table/statement declares it.
5. Coalesced output: per value class, periods disjoint and non-adjacent
   (`e_i < s_{i+1}`); `coal` is idempotent.
6. **Sequenced PK** (`WITHOUT OVERLAPS`): per key, periods pairwise disjoint in
   every committed state, under concurrency.
7. **Sequenced FK**: each child period is covered by contiguous matching
   parent periods in every committed state.
8. Committed history is immutable except closing `tt_end` and replacing a
   provisional XID by its commit timestamp.
9. Transaction timestamps follow the serialization order, are fixed per
   transaction, and agree with every `CURRENT_TIMESTAMP` the transaction saw.
10. `ρ_t` (as-of) returns exactly the committed state at `t`; per key the
    version chain is gap-free with at most one current version.
11. A query needing vacuumed history errors or is flagged, never silently partial.

## Design space & trade-offs

| Choice | Option | Wins when | Cost / risk |
|---|---|---|---|
| Timestamp | two `int64` columns `[s,e)` | default, vectorises | not closed under difference; needs coalescing |
| | temporal element (sorted disjoint periods) | closed algebra, point-based models | variable length |
| | point stamps | test oracle, coarse granularity | size × duration |
| | attribute-value stamping (N1NF) | one tuple per object history | nest/unnest; key changes |
| Default semantics | current for all dimensions (Teradata) | legacy migration | sequenced must be requested |
| | SQL:2011 (current for system time only) | conformance | users hand-write overlap logic |
| | point-based, always coalesced (TSQL2) | no encoding ambiguity | cannot keep telic facts (two adjacent calls) apart |
| TT storage | layered: start/end columns, cluster `(PK, start)` | no kernel change | as-of scans history; stamping hard |
| | version chain + TSB/MVB index | as-of and time travel fast | kernel work, split policy |
| | current + history table (SQL Server, DB2) | current path untouched | UPDATE writes twice; union plans |
| | snapshot/manifest store (Iceberg, Delta) | cheap whole-table as-of | no per-key history index |
| Open end | max-value sentinel (SQL:2011) | standard | DURATION, histograms, overflow break |
| | flag/variable + bind at query time | correct, now-relative values | every operator must bind |
| Architecture | layered stratum / monolithic / extensible | ship fast / performance / plug-in types | slow difference & aggregation / effort & lock-in / sequenced needs more than types |

## Algorithms that matter

- **Timeslice** `σ(s ≤ t < e)`; as-of on a version store: per key the version
  with greatest `tt_start ≤ t`, skipping delete stubs. Always push down.
- **Coalesce**: sort by `(A, s)`; merge while `next.s ≤ cur.e`; `O(n log n)`,
  `O(n)` pre-sorted. In SQL: running `MAX(e)` over preceding rows (not `LAG`).
- **Sweep overlap join**: sort both by `s`; on each arrival evict the other
  side's active tuples with `e ≤ s`, emit pairs with the rest (period
  `[max s, min e)`), insert self. Each pair emitted once, `O(n log n + out)`;
  per-key active lists for equi-keys. Partitioned: replicate and emit only in
  the partition holding `max(r.s, s.s)`.
- **ITA** (sequenced GROUP BY): per group sort events `(s,+x)`, `(e,−x)`; emit
  `[prev, t)` with the running aggregate. MIN/MAX need an ordered multiset;
  MWTA = extend `e` by `w`; output ≤ `2n − 1` intervals.
- **Sequenced reduction**: normalization `N_B(r; s)` for DISTINCT/union/
  difference/γ; alignment `φ_θ(r; s)` for θ-, outer and anti-joins; copy timestamps
  into attributes for predicates on them (extended S-reducibility).
- **Temporal difference**: per value class, merge against coalesced `s`;
  up to `k+1` pieces per tuple. **FOR PORTION OF**: keep left/right
  remainders, change the middle, re-check PK/FK on all pieces.
- **Sequenced PK probe**: B-tree `(k, s)`; conflict iff the entry with greatest
  `s' < e` has `e' > s` (`O(log n)`). FK: walk parents from greatest `s' ≤ s`,
  require `meets` contiguity until `e` is covered.
- **Overlap cardinality** (exact): `N(s < qe) − N(e ≤ qs)` from two 1-D
  histograms; never multiply `P(s<qe)·P(e>qs)`.
- **Lazy timestamping**: write XID; restamp after commit; persistent XID→time
  map until no unstamped version remains.
- **Vacuuming**: spec = self-maintainable view `E(H;S) = Δ(E(H),S)`; a query is
  answerable iff it can be rewritten over `E(H)`.

## Failure modes & classic bugs

- **No coalescing after projection/union**: GAPS-style queries report gaps
  between adjacent jobs; "start of salary X" returns extra rows. Detect with
  the unfold/fold oracle on adjacent tuples.
- **Implicit coalescing of telic data** (adjacent calls merged); **closed vs
  half-open mix** (one-chronon gaps/merges); **sentinel arithmetic** (8000-year
  durations, `e + 1` overflow, histogram spike).
- **Start-time stamping**: as-of states that never existed (transaction
  spanning midnight); superseding a version stamped later than the updater.
- **SI/SSI history**: as-of states between commits that contradict the
  certified serial order (write skew, read-only anomaly).
- **Non-overlap check under SI**: concurrent overlapping inserts for one key
  both commit; sequenced FK race (parent portion deleted during child insert).
- **`LAG(e)` coalescing** misses a long earlier tuple covering later ones;
  **sweep ties** lose equal-start pairs; **outer join on uncoalesced input**
  emits spurious dangling fragments; **granularity mixing** lacks semantics.
- **Over-eager vacuum**: snapshot still needed by a reader or tag; key
  evolution validated on current data only, history violates the new key.

## Implementation checklist (C/C++/Rust)

- `struct Period { i64 s, e; }` asserting `s < e`; chronons as `i64` since
  epoch; SQL `INTERVAL` as `{months, days, micros}`. No closed periods inside.
- `TemporalElement` = small vector of sorted, disjoint, non-adjacent periods;
  union/intersect/minus as linear merges (property-tested).
- Open end as a bit or reserved encoding plus a `Bind` plan operator.
- Catalog: period definitions (name, columns, dimension), granularity,
  telic/atelic flag, vacuuming spec, schema versions with stable attribute ids.
- Planner: semantic mode per statement and dimension; physical properties
  `sorted(key, s)`, `coalesced`, `open_end_fraction`; rewrites tagged with the
  equivalence they preserve (identity / multiset / snapshot).
- Vectorised operators over `(s, e)` columns: `Timeslice`, `Coalesce`,
  `Normalize`, `Align`, `OverlapJoin` (sweep / partitioned / index NL),
  `TemporalDiff`, `ITA`/`MWTA`/`STA`. Active sets as min-heaps or ring
  buffers keyed on `e`; spill ordered by `e`.
- Constraints: `(k, s)` predecessor probe plus next-key locks, or
  exclusion-style re-check that waits on in-progress conflicting transactions.
- Version header `{xid_or_ts: u64, stamped: bit, prev, delta: bit}`; backward
  deltas with the newest version whole; persistent XID→ts table with
  refcounts; idempotent, logged restamping.
- Stamp at the CC serialization point (commit under strict 2PL, validation
  under OCC); clock + sequence number for ties; per-transaction feasible
  window for `CURRENT_TIMESTAMP`.
- History index: TSB/MVB key×time pages or current B-tree + historical 2-D
  index; sealed history pages are write-once.

## How to test it

- **Unfold oracle**: random relations over ≤ 64 chronons; unfold, run the
  snapshot query, fold; assert snapshot equivalence for every sequenced
  operator, identity where lineage fixes the boundaries.
- **Coalesce properties**: idempotent; output disjoint and non-adjacent;
  `unfold(coal(r)) = dedup(unfold(r))`; rewrite rules as differential tests.
- **Adversarial periods**: equal starts/ends, meets, nesting, one chronon,
  very long, open-ended, domain min/max, empty inputs, partition boundaries
  exactly at endpoints.
- **Cross-implementation**: sweep vs partitioned vs nested-loop on skewed
  per-key histories. **Current semantics**: non-temporal suite unchanged with
  versioning on.
- **Concurrency**: two sessions inserting overlapping periods for one key at
  every isolation level; parent-portion delete vs child insert.
- **Transaction time**: record commit order and stamps; every as-of read must
  equal replaying commits with ts ≤ t; crash between commit and restamp;
  midnight-spanning `CURRENT_DATE`.
- **Vacuuming/estimation**: retained queries unchanged, expired ones error;
  overlap estimates vs truth on Zipfian lengths and open ends.

## Expert review questions

1. Default semantics per dimension and statement type — documented?
2. Half-open everywhere? Where are closed periods converted; is `meets` right?
3. Which operators return uncoalesced results, which consumers are
   representation-sensitive, where is `Coalesce` inserted — and is the data
   telic (must never be coalesced)?
4. How is `now` stored, bound, indexed and reflected in statistics?
5. What serialization point produces transaction timestamps; can an as-of
   state fall outside the serial order? How is `CURRENT_TIMESTAMP` reconciled?
6. Show the protocol enforcing `WITHOUT OVERLAPS` under concurrent inserts.
7. How do `FOR PORTION OF` pieces interact with PK, FK and triggers?
8. What bounds as-of cost far in the past, and operator memory under
   long-lived tuples? Does overlap selectivity assume `s`/`e` independence?
9. Is the vacuuming spec self-maintainable, what does a query needing expired
   history get, and which schema version reads old data?
10. Which rewrites hold only up to snapshot equivalence, and are they fenced
    from timestamp-observing consumers?

## Go deeper

- `references/time-models-and-semantics.md` — read first: domain, granularity,
  dimensions, point vs period models, the trichotomy and its reduction, NOW, Allen.
- `references/temporal-algebra-coalescing-timeslice.md` — algebra, timeslice,
  projection, difference, coalescing rules and algorithms.
- `references/temporal-joins-and-aggregation.md` — join/aggregation algorithms,
  overlap cardinality.
- `references/transaction-time-implementation.md` — versions, TSB/MVB, stamping
  and CC, vacuuming, MVCC and lakehouse time travel.
- `references/sql2011-temporal-and-tsql2.md` — SQL:2011, TSQL2, design space,
  temporal integrity constraints. `references/schema-evolution-and-versioning.md`
  — schema change over history. `references/edbs-entries.md` — entry index.

## Related skills

- `transactions-and-recovery`, `concurrency-control-theory`,
  `recovery-and-durability` — own MVCC/locking/WAL; this skill adds stamping
  at the serialization point, history retention, as-of correctness.
- `query-optimizer`, `cardinality-and-statistics` — host the temporal rewrite
  rules, equivalence types and overlap selectivity defined here.
- `sql-frontend`, `sql-semantics-and-active-rules` — binding of period
  definitions, `FOR SYSTEM_TIME`, `FOR PORTION OF`, modifiers; triggers for
  historyless constraint checking.
- `join-algorithms`, `query-execution-advanced` — equi-joins and vectorised
  machinery; overlap joins and sweeps live here.
- `index-structures-catalog`, `multidimensional-and-similarity-indexing` —
  interval trees, R-trees over `(s,e)`, multiversion B-trees.
- `materialized-views-ivm` — self-maintainable views behind vacuuming and
  bounded history encodings.
- `olap-and-warehouse-engines`, `stream-processing-engines` — slowly changing
  dimensions, windowed aggregates, expiration operators as synopses.
- `parallel-database-systems`, `distributed-dbms-design`,
  `replication-protocols` — partitioned temporal operators; HLC/TrueTime stamps.
- `relational-theory`, `dbms-architecture`, `database-security-internals`,
  `query-engine-testing` — weak equivalence; placement; audit; oracles.

## Grounding

EDBS (2nd ed., 2018), printed pages — core: Current / Sequenced /
Nonsequenced Semantics 716 / 3467 / 2506; Snapshot Equivalence 3512; Now in
Temporal Databases 2517; Point- / Period-Stamped Temporal Models 2770 / 2742;
Abstract Versus Concrete Temporal Query Languages 2; Temporal Algebras 3905;
Temporal Coalescing 3917; Temporal Joins 3986; Temporal Aggregation 3899;
Supporting Transaction Time Databases 3857; Temporal Vacuuming 4040;
Temporal Extensions in the SQL Standard 3963; TSQL2 4246; SQL-Based Temporal
Query Languages 3683; Temporal Integrity Constraints 3980; Temporal
Granularity 3970; Time Domain 4139; Schema Evolution / Versioning 3287 /
3311. Glossary-level: Allen's Relations 95, Bitemporal Interval 309,
Bitemporal Relation 310, Chronon 425, Temporal Data Models 3940, Temporal
Database 3945, Temporal Element 3962, Temporal Projection 4016, Temporal
Query Processing 4028, Timeslice Operator 4159, Transaction Time 4200,
Valid Time 4359.

Seminal work: Allen (CACM 1983); Snodgrass, TQuel (TODS 1987); Jensen, Soo &
Snodgrass, BCDM (Inf. Syst. 1994); Snodgrass (ed.), TSQL2 (1995); Böhlen,
Snodgrass & Soo, coalescing (VLDB 1996); Clifford et al., "now" (TODS 1997);
Böhlen, Jensen & Snodgrass, statement modifiers (TODS 2000); Chomicki,
bounded history encoding (TODS 1995); Lomet & Salzberg, TSB-tree (SIGMOD
1989); Becker et al., MVB-tree (VLDB J 1996); Salzberg & Tsotras (CSUR 1999);
Kline & Snodgrass (ICDE 1995); Moon et al. (TKDE 2003); Yang & Widom, SB-tree
(VLDB J 2003); Gao et al., temporal joins (VLDB J 2005); Lomet et al.,
in-engine transaction time (ICDE 2006); Kulkarni & Michels, SQL:2011
(SIGMOD Rec. 2012); Dignös, Böhlen & Gamper, temporal alignment (SIGMOD
2012, TODS 2016).
