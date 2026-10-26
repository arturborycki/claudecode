# Consistency, timing and scheduling of view maintenance

Scope: *when* and *under what concurrency* materialised views are brought up
to date -- immediate, deferred, snapshot and streaming policies; delta
capture and the state bug; online maintenance; multi-view scheduling;
warehouse-over-autonomous-sources anomalies; definition and schema change;
and modern streaming materialised views.

## 1. The dimensions

The classic taxonomy (Gupta and Mumick 1995; EDBS View Maintenance and View
Maintenance Aspects) is a product of mostly orthogonal axes:

| Axis | Options | Engine consequence |
|---|---|---|
| Method | recompute / incremental | incremental needs delta capture and a supported view class |
| Timing | immediate / deferred (on demand, before read) / snapshot (periodic, async) | where the cost lands: writer, first reader, background job |
| Reader concurrency | offline (readers wait) / online (readers proceed) | versioning or swap needed for online |
| View language | SPJ / + aggregates / + outer joins / + recursion / + subqueries | determines which algorithms apply |
| Available information | view only / view + some bases / view + all bases / keys and FKs | self-maintenance, remote-source cost |
| Supported modifications | inserts / deletes / updates / batches / definition changes | per-algorithm restrictions |
| Applicability | all instances and all modifications vs only some | prefer algorithms that never silently fail |

ADMS (Roussopoulos and Kang, 1986) was the first system to support several
maintenance policies side by side; Colby, Kawaguchi, Lieuwen, Mumick and
Ross (SIGMOD 1997) studied supporting immediate, deferred and snapshot views
in one engine with shared delta machinery.

Rule of thumb: incremental beats recompute when the change is a small
fraction of the base data; after bulk deletes or reloads, recompute is
faster. A refresh planner should decide per refresh from the actual delta
size, falling back to full refresh when incremental is not supported or
not profitable (Oracle's FORCE refresh mode behaves this way).

## 2. Immediate maintenance

The base change and the MV change commit atomically in one transaction,
typically via statement-level triggers or -- better -- maintenance operators
compiled into the DML plan (SQL Server builds indexed-view maintenance into
the modifying statement's plan).

Costs and hazards:

- Every update transaction pays, even if the MV is never read.
- **Hot spots**: aggregate MVs funnel many base rows into few group rows; all
  writers to a group serialise on it. Mitigations: commutative increment
  locks/escrow (increments compatible with each other, incompatible with
  reads of the exact value), per-transaction delta buffers merged at commit,
  or demoting the MV to deferred.
- Deadlocks between writers that touch base rows in one order and MV rows
  in another; lock MV rows in a canonical order (group-key order).
- Inside the transaction the MV must reflect the transaction's own writes
  if the optimizer is allowed to rewrite the transaction's queries to it.

> **Beyond EDBS:** Graefe and Zwilling (SIGMOD 2004, "Transaction support
> for indexed views") describe increment (escrow-style) locking and related
> techniques that let concurrent transactions update the same aggregate row
> of an indexed view.

## 3. Deferred maintenance

The view is allowed to diverge and is refreshed later -- on demand, right
before a read, or by a scheduled job. Requirements (Hanson 1987 and later):
(i) decide which views a change can affect, (ii) record changes since the
last refresh, (iii) propagate them without recomputation.

### 3.1 Change capture

| Mechanism | Pros | Cons |
|---|---|---|
| Row triggers into log tables | simple, portable | per-row overhead on writers |
| Statement-level transition tables | batched, cheap | needs engine support |
| MV logs (per base table, shared by all its MVs) | one capture for many MVs; purge after slowest consumer | extra write per change |
| WAL / CDC decoding | zero writer overhead | needs replica identity / old values; decoding lag |
| Hypothetical relation (single insert/delete table `AD`) consulted at read time (Woodfill and Stonebraker 1983; Hanson 1987) | no refresh needed for correctness | every read merges base with AD; Bloom filter avoids most AD probes |

A log entry should carry: commit sequence (or SCN/LSN), table, operation
sign, row identity, old and new values for referenced columns. **Netting**
collapses entries for the same row within a refresh window (insert then
delete = nothing; update chain = first-old to last-new) before propagation.

### 3.2 The state bug

At refresh time the base tables are already in the *post-update* state.
Most early delta formulas assume the *pre-update* state; evaluating them
against post-state tables is incorrect -- the state bug identified by Colby,
Griffin, Libkin, Mumick and Trickey (SIGMOD 1996). Two fixes:

- **Reconstruct pre-state**: `R_old = (R_new − R+) ⊎ R-` using the log
  (cheap only if the delta is small and indexed).
- **Post-state formulas**: derive maintenance expressions for the
  post-update state directly; this also handles a larger class of views and
  update patterns. In Z-relation form: `dV = dR ⋈ S' + R' ⋈ dS − dR ⋈ dS`,
  or use the telescoping order with explicit state per term
  (`delta-rules-and-counting.md`, section 3).

Test: refresh after a window containing changes to every input of a join,
including the same key on both sides.

### 3.3 Refresh as a transaction

```
refresh(mv):
    begin
    lo = mv.watermark;  hi = current commit sequence (snapshot)
    deltas = netted log entries with lo < seq <= hi for mv's inputs
    if cost_incremental(deltas) > cost_full: recompute into mv
    else: dV = delta plan(deltas, base@hi, aux@lo); apply dV (MERGE)
    mv.watermark = hi                     -- same transaction as the apply
    commit
    advance log purge point to min watermark over all consumers
```

The watermark and the MV data commit atomically, so a crash leaves the MV at
lo or at hi. Reading the bases at snapshot `hi` gives a consistent state
for all inputs.

> **Beyond EDBS:** Salem, Beyer, Lindsay and Cochrane (SIGMOD 2000, "How to
> roll a join") propagate deltas asynchronously in small steps, each input's
> changes over its own time interval, so maintenance does not need one large
> consistent snapshot; Lindsay et al. (SIGMOD 1986) gave a differential
> refresh algorithm for snapshots.

### 3.4 Separating propagate from refresh

Mumick, Quass and Mumick (SIGMOD 1997) compute summary-deltas
("propagate") while the warehouse is online, reading only the change
tables, and keep the "refresh" step that touches the MV short. The same
split generalises: delta tables can be pre-joined and pre-aggregated
continuously; refresh becomes a cheap MERGE.

## 4. Snapshot (periodic) views and staleness

Adiba and Lindsay (VLDB 1980) introduced database snapshots: a copy of
part of the database as of the refresh time, refreshed periodically and
asynchronously. Batching amortises cost and readers rarely conflict with
updates, at the price of bounded staleness. The engine must expose the
snapshot time: users need it, and the optimizer must not substitute a
stale MV for a query that requires current data (see the freshness gate in
`query-rewriting-using-views.md`).

## 5. Online maintenance (readers do not wait)

- **Horizontal redundancy -- 2VNL** (Quass and Widom, SIGMOD 1997): each
  MV tuple carries extra columns for the pre-update values plus version and
  operation markers; a reader session pinned to the previous version reads
  the old values, the maintenance transaction writes new ones, and neither
  blocks the other. Generalises to n versions.
- **Vertical redundancy**: extra rows per version (Labrinidis and
  Roussopoulos's evaluation of online warehouse update algorithms).
- **MVCC**: in an MVCC engine the refresh transaction simply writes new row
  versions; snapshot readers see the old MV. This is the modern default and
  subsumes 2VNL.
- **Build-and-swap**: recompute into a shadow table, then atomically switch
  (rename or partition exchange). Readers never see partial results; cost is
  a full recompute and double space.
- **Recompute-and-diff**: recompute into a temporary table, diff against the
  MV on its unique key, and apply only the differences (PostgreSQL's
  `REFRESH MATERIALIZED VIEW CONCURRENTLY`, which requires a unique index on
  the MV). Readers are not blocked, but the cost is still a full
  recomputation plus a diff.
- **Distributed setting**: online maintenance may require extra queries to
  sources to compensate for concurrent updates (section 7).

## 6. Many views: ordering and sharing

- **View dependency graph**: edge B -> V when V's definition references B
  (base table or another view). Refresh in topological order; the delta of
  an upstream MV is the input delta of downstream MVs, so compute it once.
- **Shared deltas**: several MVs over the same join share delta join work;
  multi-query optimisation of the maintenance plans (Mistry, Roy, Sudarshan
  and Ramamritham, SIGMOD 2001) can also add transient or permanent
  auxiliary views to make the whole set cheaper to maintain.
- **Freshness-driven scheduling**: when one base update triggers refreshes
  of many derived objects, the order affects the freshness users observe.
  For database-backed web pages (Web Views), Labrinidis and Roussopoulos
  compared serving pages virtually, materialised in the DBMS, or
  materialised at the web server (SIGMOD 2000), chose which views to
  materialise online under a performance/freshness balance (VLDB 2003, VLDB
  J 2004), and ordered update propagation to maximise data quality (VLDB
  2001). The same scheduling problem appears for any background refresher
  with more stale MVs than capacity.
- **Policy per view**: immediate for small, hot, freshness-critical MVs;
  deferred for write-heavy ones; snapshot for heavy analytic rollups.

## 7. Warehouses over autonomous sources

When the MV lives in a warehouse and the base relations live in independent
sources, computing a delta may require querying the sources, which keep
changing. Zhuge, Garcia-Molina, Hammer and Widom (SIGMOD 1995) showed the
resulting anomalies: the answer to the warehouse's maintenance query
reflects source updates that happened after the one being processed, so
contributions are double-counted or lost. Their **ECA** (Eager Compensating
Algorithm) adds compensating queries that cancel the effect of updates that
arrived while earlier queries were pending. They define consistency levels
for the warehouse relative to the source state sequence:

| Level | Guarantee |
|---|---|
| Convergence | after updates stop, the view eventually equals the view of the final source state |
| Weak consistency | every warehouse state equals the view of some valid source state |
| Strong consistency | weak, and warehouse states follow the source state order |
| Completeness | strong, and every source state is reflected by some warehouse state |

> **Beyond EDBS:** Strobe (Zhuge, Garcia-Molina and Wiener, PDIS 1996)
> extends compensation to multiple sources; SWEEP (Agrawal, El Abbadi,
> Singh and Yurek, SIGMOD 1997) compensates locally at the warehouse using
> the queued updates instead of extra source queries.

Self-maintainable views (and auxiliary views) remove the problem at its
root: maintenance never queries the sources. Chronicle views (Jagadish,
Mumick and Silberschatz, PODS 1995) are the extreme case: one input is an
append-only stream that is not stored, so the views over it must be
maintainable from the new chronicle entries and the view state alone --
the ancestor of streaming aggregation.

## 8. Definition and schema change

- **View adaptation** (definition changes): reuse the old MV, in place
  where possible -- see the change table in `query-rewriting-using-views.md`
  section 7.
- **Source schema change**: Rundensteiner, Koeller and Zhang (CACM 2000)
  built an evolvable view environment where view definitions carry
  preferences (which attributes/relations are dispensable or replaceable),
  so that after a source schema change the view is redefined into a possibly
  non-equivalent but acceptable view, then adapted.
- **Warehouse structure evolution** (Eder, Koncilia, Wiggisser): changes at
  the schema level (dimensions, categories, hierarchies) and instance level
  (members, member re-parenting, splits/merges) force re-aggregation or
  transformation of stored cells -- i.e. massive MV adaptation. *Evolution*
  keeps only the latest structure (fast queries, no cross-version queries);
  *versioning* keeps all structure versions (cross-version queries via
  transformation functions or augmented schemas, at query-time or storage
  cost). Kimball's slowly-changing-dimension types (overwrite; new row with
  surrogate key and validity interval; extra "previous value" column) are
  the instance-level special cases. For an engine: aggregate MVs over a
  dimension hierarchy must be maintained when dimension rows are re-parented
  -- a dimension update is a delta to every MV that groups by that
  hierarchy level.
- **Engine DDL policy**: on ALTER of a base column referenced by an MV,
  choose among reject, invalidate (MV unusable for rewrite until rebuilt),
  or adapt; never silently keep serving the MV for rewrite.

## 9. Streaming materialised views

> **Beyond EDBS** -- the post-2018 state of practice. Treat these as design
> references; verify product details against current documentation.
>
> - **Differential dataflow** (McSherry, Murray, Isaacs and Isard, CIDR
>   2013) represents collections as streams of `(data, time, diff)` with
>   partially ordered times; operators maintain indexed state
>   ("arrangements", shareable across queries -- McSherry et al., VLDB 2020,
>   "Shared arrangements") and emit output differences. Progress tracking
>   (frontiers) tells consumers when all differences for a time are final,
>   so multi-input outputs are consistent per timestamp rather than showing
>   transient "glitches".
> - **Materialize** compiles SQL views onto differential dataflow and serves
>   reads from maintained arrangements at chosen timestamps, offering
>   strict serializability across views; recursive views via
>   `WITH MUTUALLY RECURSIVE`.
> - **ksqlDB** (Kafka Streams) maintains `CREATE TABLE AS SELECT`
>   aggregations continuously in local state stores backed by changelog
>   topics; pull queries read the materialised state, push queries stream
>   changes; consistency is per-partition and eventual, with grace periods
>   for out-of-order events in windows.
> - **DBSP / Feldera** (Budiu et al., VLDB 2023): IVM compiler over Z-sets
>   with a per-operator chain rule; see `delta-rules-and-counting.md`.
> - **Noria** (Gjengset et al., OSDI 2018): partially-stateful dataflow for
>   read-heavy web applications; evicted state is refilled on demand by
>   "upqueries", trading memory for occasional read latency; eventually
>   consistent.
> - **Cloud warehouses** expose declarative freshness instead of refresh
>   commands: e.g. Snowflake dynamic tables declare a target lag and the
>   system chooses incremental or full refresh.
>
> Design lessons that transfer to an RDBMS: represent deltas as weighted
> rows with explicit timestamps; make freshness a declared contract (target
> lag / watermark) the optimizer can reason about; share indexed state
> between views over the same inputs; and expose per-timestamp consistency
> rather than per-operator eventual consistency when users join several
> views.

## 10. Failure modes specific to scheduling and consistency

- Log purge races refresh: entries removed before a slow MV consumed them.
- Watermark advanced in a separate transaction from the MV apply.
- Refresh reads base tables without a snapshot: different inputs at
  different times -> join deltas inconsistent.
- Immediate MV on a hot aggregate collapses write throughput (lock convoy).
- Deferred MV used by the optimizer without a freshness check.
- Downstream MV refreshed before its upstream MV in the same cycle.
- Warehouse maintenance queries to live sources without compensation
  (duplicate or lost contributions).
- Schema change on a base table leaves MV maintenance plans referencing a
  dropped or retyped column.

## Key papers

Adiba and Lindsay, VLDB 1980; Roussopoulos and Kang, IEEE Computer 1986
(ADMS); Woodfill and Stonebraker, VLDB 1983; Hanson, SIGMOD 1987;
Blakeley, Larson and Tompa, SIGMOD 1986; Colby et al., SIGMOD 1996 and
SIGMOD 1997; Quass and Widom, SIGMOD 1997; Zhuge et al., SIGMOD 1995;
Mumick, Quass and Mumick, SIGMOD 1997; Jagadish, Mumick and Silberschatz,
PODS 1995; Labrinidis and Roussopoulos, SIGMOD 2000, VLDB 2001, VLDB 2003;
Gupta, Mumick, Rao and Ross, Inf. Syst. 2001; Rundensteiner, Koeller and
Zhang, CACM 2000; Kimball, DBMS Magazine 1996.

Sources: EDBS "View Maintenance" (p.4445), "View Maintenance Aspects"
(p.4448), "Web Views" (p.4682), "Self-Maintenance of Views" (p.3372), "Data
Warehouse Maintenance, Evolution, and Versioning" (p.884), "View Adaptation"
(p.4443), "Incremental Maintenance of Views with Aggregates" (p.1838).
