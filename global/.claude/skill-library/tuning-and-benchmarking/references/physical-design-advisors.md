# Physical design advisors: index, view, partition and clustering selection

Physical design = choosing the redundant and non-redundant access structures
(indexes, materialized views, horizontal/vertical partitions, clustering/MDC,
shared-nothing distribution keys) for a given database and workload. Physical
data independence is what makes this a tuning problem rather than a schema
change: any configuration returns the same answers; only cost differs. That
also makes it automatable — the advisor can try configurations without
touching application semantics.

## 1. Problem statement (make it precise before writing code)

Inputs:
- Database D (schema + statistics; possibly only a sampled or emulated copy).
- Workload W = {(q_i, f_i)}: queries *and* DML, each with a weight (frequency,
  importance, or captured execution count). If W is unknown the problem is
  "dynamic" and belongs to online tuning (see `online-and-self-tuning.md`).
- Structure classes the target engine supports: B+-tree (clustered /
  secondary / covering-with-INCLUDE), bitmap / bitmap-join, MV / AST / indexed
  view, range/list/hash/composite partitioning, MDC, distribution key.
- Constraints: storage budget B, maintenance budget, max number of
  partitions, max fragments N_max, required existing structures (PK/unique
  indexes that must stay), tuning-time budget.
- Objective (non-functional requirements): minimise Σ f_i · cost(q_i, C);
  variants add maintenance cost, energy, cloud price, or count of structures,
  and multi-objective forms combine them.

Output: configuration C ⊆ Candidates minimising the objective subject to
constraints.

Hardness: optimal secondary-index selection is NP-complete even in simplified
cost models (Piatetsky-Shapiro 1983); view selection and derived horizontal
partitioning selection are NP-hard as well. Every production advisor is a
heuristic. The engineering problem is: which heuristic, evaluated against
which cost oracle, at what number of oracle calls.

## 2. Why the optimizer must be the cost oracle

Early tools (1970s–80s, culminating in DBDSGN, Finkelstein/Schkolnick/Tiberio
TODS 1988) estimated benefit with an external model. Failure mode: the tool
"buys" an index the optimizer never picks, or misses one it would. Lesson
adopted by every vendor since AutoAdmin: **benefit of configuration C for
query q is the optimizer's estimated cost of q's best plan under C**. The
advisor and the engine can then never disagree about which structures a
plan uses (they can both be wrong about cost, which is a separate problem).

Server-side hooks required (AutoAdmin "what-if", Chaudhuri & Narasayya SIGMOD
1998):
1. **Hypothetical structure creation**: catalog-only metadata entries flagged
   hypothetical; never visible to normal compilation, never maintained, never
   scanned. Must carry enough physical properties for costing: key columns
   and order, included columns, uniqueness, clustered flag, estimated page
   count and height, partitioning function.
2. **Statistics for hypothetical structures**: histograms / density on the
   leading column(s) and multi-column densities, built by *sampling* rather
   than by building the index. Size estimate from row count × projected entry
   width / fill factor.
3. **Configuration-scoped optimization**: "optimize q as if exactly the set S
   of (real or hypothetical) structures existed", ignoring other real ones.
   Avoids create/drop churn and lets the advisor evaluate dropping existing
   structures.
4. **Access-path request capture** (used by relaxation-style search):
   instrument the optimizer to emit, for each logical access it considered,
   the ideal index/view that would have served it (columns in sargable
   predicates, required order, required output columns).

Engine-builder checklist for the hooks:
- The hypothetical flag must be checked everywhere plans are cached, so a
  what-if plan can never be cached and reused for execution.
- What-if sessions must be isolated per tuning session (session-local
  catalog overlay), not global DDL.
- DML costing must include maintenance of hypothetical indexes (the optimizer
  must cost "update plan + index maintenance" for each candidate on the
  updated table), or the advisor will recommend free-to-maintain indexes.
- Hypothetical statistics must flow through the same cardinality estimator
  as real ones; a separate code path is a guaranteed source of drift.

> **Beyond EDBS:** PostgreSQL's HypoPG extension implements (1)+(3) as a
> session-local planner hook; Teradata's Index Wizard drives the optimizer
> through what-if demographics, and Teradata System Emulation Tool (TSET)
> lets the optimizer cost a workload as if it ran on a target system's
> configuration and statistics. The pattern is identical: same planner, an
> overlay catalog.

## 3. Search space: why it explodes

For one query with n sargable columns, any subset in any order is a
candidate index key: Σ_{k=1..n} n!/(n−k)! keys, before choosing INCLUDE
columns. MVs: any subset of referenced tables × any grouping × any projection.
The configuration space is the power set of all of that, across all queries.
Vertical partitioning of a table with m non-key attributes alone has Bell(m)
possible fragmentations (Bell(10) = 115,975). Partitioning interacts with
indexing (which index is best depends on how the table is partitioned).

Consequences:
- Candidate generation must be aggressive pruning, not enumeration.
- Optimizer calls dominate tuning time; count them and engineer them down.

## 4. Candidate generation

Step 1 — **syntactic relevance**: from each statement extract indexable
columns: equality predicates, range predicates, join columns, GROUP BY /
ORDER BY columns, and the projection (for covering).

Step 2 — **per-query best configuration** (AutoAdmin, VLDB 1997): treat each
query as a one-statement workload, run the search on it, keep its winning
configuration. Candidate set = union of per-query winners. Rationale: a
structure that is not (near-)optimal for any single query rarely helps the
workload. Cost: |W| small searches; parallelisable.

Step 3 — **multi-column widening**: build 2-column candidates only whose
leading column is a winning 1-column candidate, then 3-column from winning
2-column, etc. (iterative widening). Keeps the multi-column space linear-ish
in practice.

Step 4 — **merging and reduction** (Chaudhuri & Narasayya ICDE 1999 for
index merging; Bruno & Chaudhuri SIGMOD 2005 for relaxation): derive
structures that are optimal for *no* single query but good for the workload
under a storage bound.
- Merge I1=(a,b) and I2=(a,c) → (a,b,c) or (a,b) INCLUDE(c): one structure
  serves both, at less space than two.
- Prefix: (a,b,c) → (a,b).
- Split / reduce: drop rarely-needed trailing or included columns.
- Promote to clustered; remove.
- MV merging: union of grouping columns / predicates relaxed to the common
  generalisation, so one view answers several queries via rewriting.

Step 5 — **workload compression** for large captured workloads: cluster
statements by template (parameter-stripped signature), keep representatives
with summed weights. Error from compression must be bounded/validated against
a held-out sample.

## 5. Cost evaluation tricks (reduce optimizer calls)

| Technique | Idea | Caveat |
|---|---|---|
| Atomic configurations (AutoAdmin 1997) | A query uses at most j structures per table; cost(q, C) = min over atomic subsets of C that q can use; derive large configs from cached small ones | Requires bounding j; index-intersection plans break small j |
| Relevant-subset caching | cost(q,C) = cost(q, C ∩ relevant(q)); memoise on that key | Must include structures on tables q *updates* |
| Plan caching with re-costing (INUM, Papadomanolakis/Dash/Ailamaki VLDB 2007) | Cache plan skeletons per "interesting order" combination, then cost new index sets by plugging in access costs without re-optimizing | Plan space approximation; misses plan shape changes |
| Benefit upper bounds | Skip configs whose optimistic bound cannot beat incumbent | Needs monotone bound |
| Sampling statements | Evaluate on a sample of W, confirm winners on full W | Variance on skewed weights |

Invariant: memoisation keys must include every structure that could change
the plan or the maintenance cost — getting the key wrong silently makes the
advisor optimise a different problem.

## 6. Enumeration algorithms

Notation: cand = candidate set; cost(C) = Σ f_i · optcost(q_i, C) + maint(C);
size(C) = Σ size(s).

**Greedy(m, k) bottom-up (AutoAdmin 1997)**
```
C := best configuration of size ≤ m found exhaustively over cand   # m small, e.g. 2
while |C| < k and budget remains:
    s* := argmin_{s ∈ cand \ C, size(C ∪ {s}) ≤ B} cost(C ∪ {s})
    if cost(C ∪ {s*}) >= cost(C): break
    C := C ∪ {s*}
return C
```
Optimizer calls O(k · |cand| · |W|) before caching. Exhaustive seed of size m
mitigates the greedy's blindness to pairs that only help together (e.g., two
indexes enabling an index-intersection or a merge join).

**Knapsack by benefit density (DB2 Advisor, Valentin et al. ICDE 2000)**
```
for each candidate s (generated by the optimizer itself in a
    "recommend indexes" explain mode that injects virtual indexes):
    benefit(s) := Σ_q f_q · (cost(q, ∅) − cost(q, {s}))   # from the plan that used s
order by benefit(s)/size(s) descending; fill budget B
then: randomized swap phase — exchange chosen/unchosen candidates, keep improvements,
      re-evaluate the *whole* configuration with the optimizer
```
Cheap (one optimization per query to harvest candidates). Weakness: benefit
attributions are non-additive; the swap phase repairs some of the error.

**Top-down relaxation (Bruno & Chaudhuri SIGMOD 2005)**
```
C := union over queries of the optimal structures from captured access-path requests
     # typically far over budget, but cost(C) is a lower bound for the workload
while size(C) > B:
    for each relaxation r ∈ {merge, prefix, split, remove, demote} applicable to C:
        penalty(r) := (cost(r(C)) − cost(C)) / (size(C) − size(r(C)))
    C := apply argmin penalty
keep best feasible C seen
```
Wins when the budget is large (few relaxations needed) and gives a
quality yardstick (lower bound) for free. Bottom-up wins when budget is tiny.

**Integer programming (CoPhy, Dash/Polyzotis/Ailamaki VLDB 2011)**: with
INUM-style cost decomposition, index selection becomes a binary IP solvable
near-optimally by off-the-shelf solvers, with an optimality gap reported.

**Randomized / evolutionary**: simulated annealing, genetic algorithms, hill
climbing — common for view selection and partitioning (survey in Mami &
Bellahsene SIGMOD Record 2012 classifies view-selection algorithms as
deterministic, randomized, evolutionary, hybrid).

Benefit non-additivity: structures substitute (two indexes that serve the same
predicate) or complement (two that together enable a plan neither enables
alone). The benefit set function is therefore not submodular in general and
greedy carries no (1−1/e) guarantee. Index-interaction analysis (Schnaitter
et al. VLDB 2009) quantifies degree of interaction to partition candidates
into near-independent groups that can be tuned separately.

> **Beyond EDBS:** Kossmann, Halfpap, Jankrift, Schlosser (VLDB 2020)
> re-implemented and compared the classic algorithms (Drop heuristic, AutoAdmin,
> DB2Advis, Relaxation, CoPhy, DTA-style anytime, Extend) on TPC-H/DS and JOB
> under one what-if layer. Takeaways consistent with the theory above:
> runtime is dominated by what-if calls (so caching/cost-request reuse matters
> as much as the search strategy); the ranking of algorithms depends on the
> storage budget and workload; and greedy extension of multi-column indexes
> (Extend, Schlosser et al. ICDE 2019) offered a good quality/runtime
> balance. Use such a harness to evaluate any new advisor rather than
> reporting quality on one benchmark at one budget.

## 7. Integrated vs staged selection

Staging ("indexes first, then views", "partition first, then index") is a
classic bug in advisors:
1. Structures interact — the best index depends on partitioning and vice
   versa; a view can make an index redundant.
2. Staging produces redundant recommendations (an index plus a view that
   covers the same access).
3. There is no principled split of the storage budget between classes.

Integrated search over the union candidate space (DTA lineage: Agrawal,
Chaudhuri, Narasayya VLDB 2000 for views+indexes; Agrawal, Narasayya, Yang
SIGMOD 2004 adding horizontal+vertical partitioning; DB2 Design Advisor, Zilio
et al. VLDB 2004, covering indexes, MQTs, MDC and shared-nothing partitioning)
is the accepted design. Practical compromise: integrated search, but with
alignment constraints (e.g., require indexes to be partition-aligned so
partition switching for roll-in/roll-out stays possible).

## 8. Structure-specific rules an advisor (and a human) must know

**B+-tree indexes**
- Levels matter more than anything: height ≈ ceil(log_F N) + 1; with fanout
  F = 1000, 10^6 rows needs 3 levels, 10^9 needs 4; fanout 10 needs 7 and 10.
  Wide keys shrink F, so prefer narrow keys or key compression.
- Clustered vs secondary: one clustering order per table; any second
  clustering index must be a prefix relation of the first. Secondary indexes
  must be dense (one entry per row); sparse indexes must be clustered.
- Covering: if the index contains all referenced columns, no base-table
  dereference. Put WHERE-clause equality columns first, then range column,
  then covering/INCLUDE columns. Order of key columns is decisive.
- Scan vs non-clustered index break-even is low: with prefetching
  sequential I/O, a full scan can be several times faster than an
  unclustered index retrieving even ~1% of rows on a cold cache. The
  optimizer's break-even must come from the I/O cost model, not a constant.
- Hash: one probe for equality if buckets are provisioned at ≥ 2× data space
  to keep overflow chains short; no ranges.
- Bitmaps: conjunctions of individually unselective predicates (DSS); cheap
  AND/OR/COUNT; poor for high-update OLTP. Bitmap join index = bitmap on the
  fact table keyed by dimension attribute (pre-joined star filtering).
- Every index taxes inserts/updates/deletes and bulk load (a single index can
  slow a batch load by an order of magnitude or more). Load then index.

**Materialized views / summary tables**
- Selection is only half; the optimizer must *match* (rewrite) queries to
  views, which is hard except for exact matches (see
  `materialized-views-ivm`). An advisor must only propose views the engine's
  matcher can actually use — again, use the optimizer as oracle.
- Maintenance cost (incremental vs recompute, immediate vs deferred) is part
  of the objective. Views and indexes compete for the same storage and
  maintenance budget; treat them in one search.

**Horizontal partitioning**
- Range by date for roll-in/roll-out and backup granularity; hash on a
  (near-)unique key for even distribution across CPUs/nodes; list for
  categorical; composites (range-hash, range-list, …).
- Derived (referential) partitioning: partition dimensions by predicate,
  then partition the fact table by semi-join with dimension fragments.
  Effect: pre-joins fact to dimension fragments and turns dimension
  selections into partition elimination. Constraint: number of fact
  fragments N ≤ threshold (management and metadata cost).
- Partitioning is non-redundant: no extra storage, no extra maintenance —
  but it changes every plan, so it must be in the integrated search.

**Vertical partitioning**
- Key duplicated in each fragment; reconstruction via key join. Algorithms:
  grouping (start one attribute per fragment, merge by affinity) or splitting
  (start whole, split by query access frequencies). Column stores are the
  limit case.

**Clustering / MDC**
- Cluster on range-predicate columns, or on equality columns whose
  matches are numerous; MDC (DB2, Padmanabhan et al. SIGMOD 2003) clusters
  on several dimensions with block indexes. MDC advisor (Lightstone &
  Bhattacharjee VLDB 2004) must model space blow-up from sparse cells:
  choose dimension granularity (coarsify via functions like month(date)) so
  that cells fill blocks.

**Shared-nothing distribution key**
- Choose for skew-free hashing *and* collocated joins; the parallel advisor
  (Rao, Zhang, Megiddo, Lohman SIGMOD 2002) runs the optimizer in a
  "recommend partitioning" mode and evaluates candidates by what-if.

> **Beyond EDBS (Teradata):** the primary index is simultaneously the
> distribution key (row hash → AMP) and the primary access path; PPI adds
> row partitioning within each AMP, and column partitioning gives a columnar
> layout. Physical design there is a joint choice of PI (skew + join
> collocation + single-AMP access), PPI expression (partition elimination,
> roll-in/out), secondary/join/hash indexes, and statistics — the same
> integrated-search argument applies, and skew of the PI is a first-class
> constraint (measure with hash-bucket distribution before committing).

## 9. OLTP vs DSS design profiles

| Aspect | OLTP / ERP | DSS / warehouse |
|---|---|---|
| Page/block size | small pages | large pages, large prefetch blocks |
| Schema | highly normalised | 3NF or star/snowflake, denormalised |
| Indexes | PK/FK B-trees, clustering index | bitmaps, join indexes, covering, MDC |
| Partitioning | rarely by range | range on date (month/quarter), hash for parallelism |
| MVs | rare | central |
| Memory split | buffer pool dominant, statement cache | buffer pool + large sort/hash work areas |
| Concurrency | very high; locks matter | low; scans matter |

Memory allocation across buffer pool, sort/hash work areas, lock lists and
statement cache is zero-sum: tuning one starves another, so it belongs in the
same search or in an online memory broker (see `online-and-self-tuning.md`).

## 10. Advisor lineage (for design docs)

| System / paper | Contribution |
|---|---|
| Finkelstein, Schkolnick, Tiberio, TODS 1988 (DBDSGN, System R) | first optimizer-aware design tool |
| Chaudhuri & Narasayya VLDB 1997 (AutoAdmin, SQL Server 7 Index Tuning Wizard) | per-query candidates, greedy(m,k), atomic configurations |
| Chaudhuri & Narasayya SIGMOD 1998 | what-if index analysis API |
| Agrawal, Chaudhuri, Narasayya VLDB 2000 | joint index + MV selection |
| Valentin et al. ICDE 2000 (DB2 Advisor) | optimizer-generated virtual candidates, knapsack + swap |
| Rao et al. SIGMOD 2002 | shared-nothing partitioning advisor |
| Agrawal, Narasayya, Yang SIGMOD 2004 | integrated vertical + horizontal partitioning |
| Agrawal et al. VLDB 2004 (DTA, SQL Server 2005) | integrated, scalable, alignment constraints |
| Zilio et al. VLDB 2004 (DB2 Design Advisor) | indexes, MQTs, MDC, partitioning together |
| Papadomanolakis & Ailamaki SSDBM 2004 (AutoPart) | vertical partitioning for scientific DBs |
| Bruno & Chaudhuri SIGMOD 2005 | relaxation-based top-down search |
| Chaudhuri & Narasayya VLDB 2007 | "a decade of progress" survey |

Commercial advisors around 2007–2013: SQL Server DTA (partitioning, MVs,
indexes), Oracle SQL Access Advisor (same set), DB2 Design Advisor (plus
clustering/MDC); storage-level automation in Oracle ASM and DB2 automatic
storage.

## 11. Validation of an advisor

- **Recommend-then-measure**: build the recommended structures on a copy,
  run the workload, compare actual vs predicted improvement. A consistently
  optimistic advisor points at cost-model or what-if-statistics bugs.
- **Never-used check**: after deployment, every recommended structure must
  appear in at least one executed plan within the observation window;
  unused ones are a what-if/real divergence bug (or a workload shift).
- **Monotonicity tests**: adding a structure to C must never increase the
  estimated *query* cost of a SELECT (the optimizer can ignore it); it may
  increase DML cost. Violations indicate costing non-determinism.
- **Budget tests**: B → ∞ must converge to the union of per-query optima;
  B = 0 must return existing required structures only.
- **Regression risk**: estimated improvement is an expectation; individual
  queries can regress because the optimizer picks a new plan on misestimated
  cardinalities. Gate rollout per query (see `online-and-self-tuning.md`,
  verification loop).

Sources: Database Tuning Using Combinatorial Search (p.985); Physical Database
Design for Relational Databases (p.2759); Optimization and Tuning in Data
Warehouses (p.2619); Index Tuning (p.1851); Schema Tuning (p.3308);
Self-Management Technology in Databases (p.3374).
