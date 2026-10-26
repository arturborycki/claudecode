---
name: materialized-views-ivm
description: "Use when designing, implementing or reviewing views as an engine feature: view definition and expansion, MV storage and refresh, incremental view maintenance (IVM), rewriting queries using views, view selection, or updates through views. Triggers on materialized view, MV, MQT, indexed view, join index, summary table, REFRESH MATERIALIZED VIEW, fast refresh, MV log, delta rules, counting algorithm, DRed, summary-delta, change table, MIN/MAX under deletes, outer-join view maintenance, self-maintainable view, auxiliary view, deferred maintenance, state bug, view matching, query rewrite, containment mapping, bucket algorithm, MiniCon, view selection, view adaptation, updatable view, INSTEAD OF trigger, WITH CHECK OPTION, view update problem, DBToaster, differential dataflow, streaming materialized view. Apply even when phrased as 'cache this aggregate and keep it fresh', 'why does the optimizer ignore my summary table', or 'make this dashboard query cheap without serving stale numbers'."
---

# Materialized Views and Incremental View Maintenance

This skill owns the view subsystem: the catalog object a view is, how it is
expanded into queries, how a materialized copy is kept equal to its defining
query as base data changes, how the optimizer substitutes views for
subqueries, and how DML issued against a view is translated to base tables.
The one idea to keep: **treat every relation as a map tuple -> signed
multiplicity**. Selection, bag projection, union-all and joins are then
linear (or bilinear) in the change, so their deltas are mechanical; everything
hard in IVM -- DISTINCT, EXCEPT, MIN/MAX, outer-join padding, recursion --
is a non-linear operator that needs auxiliary state to stay incremental.

## Mental model

```
 base DML --> delta capture --> propagate (delta plan) --> apply/REFRESH --> MV storage
  (txn)      trigger | MV log |  dV = f(dR, R or R', aux)   merge on key/group,   |
             WAL/CDC | xition    one term per changed        counts, subsumption   |
             tables              relation (telescoping)      clean-up              |
 query --> binder: expand virtual views --> optimizer: view matching ------------- +
 DML on view --> translator: W such that Q_V(W(I)) = U(Q_V(I)), or reject
```

- **Virtual view** = macro: binder substitutes the definition (query
  modification); the optimizer may merge it into the outer block.
- **Materialized view** = stored table + freshness contract `MV = Q_V(D_t)`;
  axes: *how* (full/incremental), *when* (immediate/deferred/periodic/
  streaming), *whether readers block* (online/offline).
- **Optimizer resource**: containment plus compensation (residual filters,
  re-aggregation, join-back). **DML target**: a translation must exist, be
  unique (or policy-chosen) and be side-effect free.

## Core invariants

1. **Freshness**: after a refresh stamped t, MV = `Q_V(D_t)` as a bag (NULL
   groups, multiplicities). Immediate MVs hold this at every commit and
   inside the writing transaction.
2. **Delta oracle**: `apply(MV_old, dV) == recompute(Q_V, D_new)` per batch.
3. **State consistency**: each delta term reads each relation in exactly the
   state its telescoping derivation assumes (pre or post). Evaluating
   pre-state formulas against post-state tables is the *state bug*.
4. **Counts**: every MV that deduplicates or groups stores a derivation count;
   a row is present iff count > 0. `SUM(x)` over nullable x also stores
   `COUNT(x)` so the SUM can return to NULL.
5. **Delta minimality**: no zero-weight entries; under set semantics
   deletions ⊆ MV_old and insertions ∩ MV_old = ∅.
6. **Rewrite soundness**: a view is substituted only if its expansion plus
   compensation is bag-equivalent to the replaced subexpression under
   constraints that are enforced (or trusted by an explicit policy) and the
   view's staleness is within the query's tolerance.
7. **Recursive MVs**: after deletions every surviving tuple has a derivation
   in the new state (no unfounded tuples).
8. **Outer-join MVs**: minimal form -- no stored tuple subsumes another.
9. **Delta logs**: every committed base change lands in exactly one refresh
   window, in commit order; refresh is idempotent relative to its watermark.
10. **View DML**: either `Q_V(W(I)) = U(Q_V(I))` holds or the statement errors;
    rows written through a `WITH CHECK OPTION` view satisfy its predicate
    (and underlying views' predicates per CASCADED/LOCAL).
11. **Dependencies**: view dependencies form a DAG; refresh runs in
    topological order; DDL on a base object invalidates or adapts dependents.

## Design space & trade-offs

| Refresh method | Wins when | Cost / risk |
|---|---|---|
| Full recompute | large delta fraction, any view class, bulk loads | O(base) work each refresh; long staleness window |
| Incremental (delta rules) | small deltas, indexes on join keys of other inputs | needs aux state for non-linear ops; correctness surface large |
| Partition-change tracking | base partitioned on a column the MV groups/filters by | only coarse-grain; recompute of touched partitions |
| Self-maintainable incremental | remote/unavailable bases, warehouse loads | restricts view class or needs auxiliary views |

| Timing | Wins when | Cost / risk |
|---|---|---|
| Immediate (in txn) | readers need read-your-writes; OLTP-sized deltas | write amplification, hot-spot locks on group rows |
| Deferred (refresh on demand / before read) | write-heavy, read-rare | first reader pays; state-bug risk; log growth |
| Periodic snapshot | dashboards tolerant to staleness | bounded-stale answers; rewrite must know staleness |
| Streaming/async dataflow | continuous fresh results, many views | operator state memory; consistency of multi-input outputs |

| Aggregate | Insert | Delete | Extra state |
|---|---|---|---|
| COUNT, SUM | add | subtract | COUNT(*) per group; COUNT(x) for nullable x |
| AVG, VAR, STDDEV | via SUM, COUNT, SUM(x^2) | same | store components, derive at read |
| MIN / MAX | compare | if current extreme deleted: recompute group or use aux multiset | per-group ordered multiset or top-k buffer |
| COUNT DISTINCT, MEDIAN, percentile | per-value counts / order-statistic tree | same | proportional to group cardinality |

## Algorithms that matter

**Join delta in Z-relations** (bag semantics, signed multiplicities):
```
d(R |><| S) = dR |><| S  +  R' |><| dS          -- R' = R + dR (post), S pre
            = dR |><| S' +  R |><| dS           -- symmetric form
            = dR|><|S + R|><|dS + dR|><|dS      -- all pre-state
n-way: d(R1..Rn) = sum_i  R1'..R(i-1)' |><| dRi |><| R(i+1)..Rn
```
One delta query per changed input, probing indexes on the others: cost ~ sum_i |dRi| x probe cost.

**Counting algorithm** (non-recursive views with DISTINCT/union/projection):
store `cnt(t)`; propagate signed counts through the bag plan; apply with
`cnt += d`; delete rows reaching 0; emit row on transition 0 -> positive.
EXCEPT needs both operand counts as auxiliary columns.

**Summary-delta apply** (aggregate MVs): aggregate the signed delta by the
view's group key (`SUM(+/-x)`, `SUM(+/-1)`), then MERGE: absent group ->
insert if count > 0; present -> combine; count hits 0 -> delete; MIN/MAX
deletion hitting the stored extreme -> mark group for recompute.

**DRed** (recursive, stratified): per stratum (1) over-delete: propagate
deletions semi-naively over the old state; (2) rederive: put back
over-deleted tuples with an alternative derivation in the new state;
(3) insert: semi-naive propagation of insertions over the new state.

**Outer-join MV maintenance** (Larson-Zhou): primary delta = the view
expression with the updated table T moved to the left on its root path,
FOJ->LOJ and ROJ->inner along that path, T replaced by dT; secondary delta =
null-extended tuples of indirectly affected terms that the primary delta now
subsumes (delete on insert) or orphans (insert on delete).

**SPJG view matching**: same table set (or extra tables joined through
non-null FKs to keys); view equijoin classes refine query's; view ranges
contain query ranges; view residuals subset of query residuals; all
compensating predicates and outputs computable from view columns; query
GROUP BY functionally determined by view GROUP BY; roll up SUM->SUM,
COUNT->SUM, AVG->SUM/SUM.

## Failure modes & classic bugs

- **State bug**: deferred refresh evaluates `dR |><| S` after S already holds
  dS, double-counting `dR |><| dS`. Fuzz with both join inputs changed per window.
- **Group lifetime**: no COUNT(*) -> empty groups linger with SUM 0, or a group
  whose SUM transiently hits 0 is dropped. **SUM = 0 instead of NULL** after
  the last non-null input is deleted.
- **MIN/MAX** stale after deleting the extreme, or recompute of all groups on
  any delete. **HAVING views** that drop failing groups cannot revive them.
- **Outer-join orphans**: first matching child inserted but the null-padded
  parent row kept; last child deleted but the padded row not reinstated.
- **Recursion**: DRed over-deletion explodes near hubs; counting diverges on cycles.
- **Unsound rewrite**: join-back/extra-table matching on an FK declared NOT
  ENFORCED but violated; stale deferred MV substituted for a current query.
- **Divergence from recompute**: float SUM drift (use decimals/compensated
  sums), or now(), random(), collation, time zone inside the definition.
- **Disappearing rows**: UPDATE through a view moves a row out of its
  predicate (no CHECK OPTION, or LOCAL where CASCADED was needed).
- **Log boundary**: entries lost/doubled when log purge races a refresh.

## Implementation checklist (C/C++/Rust)

- Catalog: bound view tree (resolved IDs, `SELECT *` frozen at create) plus
  text; dependency edges for invalidation and topological refresh order.
- Classify each MV at CREATE (incremental? self-maintainable for which
  updates?), persist delta plans, and explain any full-refresh fallback.
- Hidden columns: `__count`, `COUNT(x)` per nullable SUM, SUM(x^2) for VAR,
  a non-null key column per source table to detect null-extension.
- Deltas as Z-set batches `(row, i64 weight)`; consolidate (hash/sort, sum,
  drop zeros) before apply. Keep `(old,new)` pairs until a key changes.
- Capture: statement-level transition tables over row triggers; deferred
  logs keyed by (commit_seq, table, row, sign) with a netting pass.
- Apply = MERGE on the MV's unique key; no unique index, no incremental apply.
- Concurrency: immediate aggregate MVs need commutative increment/escrow
  locks or per-txn delta buffers merged at commit; deferred refresh is one
  snapshot-isolated txn that also advances the watermark.
- MIN/MAX side state: per-group `BTreeMap<value, count>` / `std::map` when
  deletes are frequent; otherwise dirty-group recompute flags.
- Rewrite: index views by table set/outputs (filter tree) so matching is
  sublinear in #MVs; compensation is ordinary logical operators.
- View DML: rewrite to base DML with the view predicate conjoined; enforce
  CHECK OPTION on the final row after defaults and base BEFORE triggers.

## How to test it

- **Recompute oracle**: random schema, view (from the supported grammar) and
  change batches; after each refresh compare MV and fresh result as bags.
- **Batch-split invariance**: refresh(B) == refresh(B1); refresh(B2).
- **Adversarial deltas**: insert+delete of one row in a batch; group-key
  updates; delete current MIN; delete a group's last row; NULL keys and
  measures; self-joins changed on both sides.
- **Recursive**: cyclic graphs, deletions with alternative paths; DRed vs CTE.
- **Rewrite**: run original and rewritten plans on random data (including
  FK-violating data when constraints are unenforced); assert plan shape.
- **View DML**: `Q_V(W(I)) == U(Q_V(I))`; CHECK OPTION LOCAL/CASCADED matrix.
- **Crash** mid-refresh: MV is at the old or new watermark, never between.

## Expert review questions

1. What is each MV's freshness contract, and how do readers and the
   optimizer learn its watermark?
2. Which operators are non-linear, and what auxiliary state makes each incremental?
3. For a batch changing both sides of a join, which state does each delta term read?
4. Where is COUNT(*) stored; what happens when a group's SUM crosses 0?
5. Worst-case cost of deleting the current MAX?
6. Self-maintainable for inserts/deletes/updates? If not, which bases are
   read during maintenance, under what isolation?
7. Who wins on a hot group row: concurrent writers or the immediate MV?
8. How are repeated changes to one row within a refresh window netted?
9. Which constraints does each rewrite rely on -- enforced or trusted?
10. How many MVs can the matcher handle before optimization time regresses?
11. When is full refresh chosen over incremental, on what delta estimate?
12. Outer-join MVs: which non-null column identifies null-extension per table?
13. View DML: which tables are key-preserved; what error on ambiguity?
14. On ALTER/DROP COLUMN or definition change: invalidate, adapt, or rebuild?

## Go deeper

- `references/delta-rules-and-counting.md` -- set/bag/Z delta rules, pre/post
  state, counting, irrelevant updates, self-maintenance, auxiliary views,
  higher-order IVM. Read before writing a delta-plan generator.
- `references/aggregates-outerjoins-recursion.md` -- summary-delta, change
  tables, MIN/MAX/AVG/holistic, outer-join normal form and primary/secondary
  deltas, DRed/PF, first-order TC, top-k. Read for GROUP BY, OUTER JOIN, WITH RECURSIVE.
- `references/query-rewriting-using-views.md` -- containment, bucket/inverse
  rules/MiniCon/chase, optimizer view matching (SQL Server, Oracle, DB2,
  Teradata), view selection, view adaptation. Read when wiring MVs into the optimizer.
- `references/view-updates.md` -- definition/expansion internals, view update
  problem, complements, updatable-view rules, CHECK OPTION, INSTEAD OF.
- `references/consistency-and-scheduling-of-maintenance.md` -- timing
  policies, delta logs, state bug, online refresh, multi-view scheduling,
  ECA/Strobe, streaming MVs. Read when building the refresh scheduler.
- `references/edbs-entries.md` -- all cluster entries with printed pages.

## Related skills

- `query-optimizer` (rule/cost framework; this skill supplies view matching),
  `query-plan-design` (delta plans, MERGE/REFRESH nodes), `sql-frontend`
  (parses CREATE VIEW; expansion semantics and dependencies live here).
- `join-algorithms`, `storage-and-indexing`, `index-structures-catalog`:
  delta joins probe unchanged inputs; MVs and join indexes are stored structures.
- `transactions-and-recovery`, `concurrency-control-theory`,
  `recovery-and-durability`: in-txn maintenance, hot-spot locks, atomic refresh.
- `relational-theory` (containment, chase -- applied here);
  `sql-semantics-and-active-rules` (trigger semantics; CHECK OPTION and view
  DML translation are owned here).
- `olap-and-warehouse-engines` (cube storage; cube maintenance and view
  selection here); `stream-processing-engines` (windows, watermarks, state;
  delta algebra here).
- `cardinality-and-statistics`, `tuning-and-benchmarking` (delta estimates,
  advisors); `replication-and-consistency`, `replication-protocols`,
  `distributed-dbms-design` (snapshot replication, autonomous sources).
- `temporal-databases`, `database-security-internals`,
  `query-execution-advanced`, `beyond-relational-engines` (recursion/Datalog),
  `query-engine-testing` (oracles, plan-shape tests).

## Grounding

EDBS 2nd ed.: Views p.4461; View Definition p.4444; View Maintenance p.4445;
View Maintenance Aspects p.4448; Incremental Computation of Queries p.1830;
Incremental Maintenance of Views with Aggregates p.1838; Maintenance of
Materialized Views with Outer-Joins p.2165; Maintenance of Recursive Views
p.2170; Self-Maintenance of Views p.3372; View Adaptation p.4443; Answering
Queries Using Views p.114; Rewriting Queries Using Views p.3241; Ranking Views
p.3092; Updates Through Views p.4349; Side-Effect-Free View Updates p.3487;
Web Views p.4682; Data Warehouse Maintenance, Evolution, and Versioning p.884.
Seminal: Stonebraker 1975; Adiba-Lindsay 1980; Blakeley-Larson-Tompa 1986;
Qian-Wiederhold 1991 / Griffin-Libkin-Trickey 1997; Gupta-Mumick-Subrahmanian
1993; Griffin-Libkin 1995; Colby et al. 1996; Mumick-Quass-Mumick 1997;
Larson-Zhou 2007; Levy-Mendelzon-Sagiv-Srivastava 1995; Pottinger-Halevy 2001;
Halevy 2001; Goldstein-Larson 2001; Harinarayan-Rajaraman-Ullman 1996;
Bancilhon-Spyratos 1981; Dayal-Bernstein 1982; Keller 1985; Gupta-Mumick 1999.
