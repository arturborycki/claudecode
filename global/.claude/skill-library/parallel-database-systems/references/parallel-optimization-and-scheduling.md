# Parallel query optimization, scheduling and resource allocation

A parallel optimizer is a conventional optimizer with one more physical
property — **partitioning** — and one more enforcer — **exchange** — plus a
cost model that understands that concurrent work overlaps, and a scheduler
that turns a plan into processor and memory assignments. Most practical
failures come from the cost model (skew blindness, discrete DOP) and from
scheduling, not from enumeration.

---

## 1. Problem structure

Components (as for any optimizer): search space, cost model, search strategy.
Parallel plans are operator trees annotated with: algorithm per operator,
which edges pipeline and which materialize, partitioning of each operator's
input and output, DOP, and (in shared-nothing) the home — the set of sites
where each operator runs.

Four extensions to a serial optimizer:
1. Define the space of **semantically valid** parallel plans (partitioning
   properties per operator).
2. Extend enumeration to explore that space (properties + enforcers).
3. Extend the cost model to price parallel plans.
4. Add heuristics so optimization time does not explode.

---

## 2. One-phase vs two-phase optimization

| Approach | How | Strength | Weakness |
|---|---|---|---|
| Two-phase (XPRS; Hong & Stonebraker) | phase 1: best *serial* plan; phase 2: parallelize it — choose partitioning, DOP, schedule | small search, reuses serial optimizer | the join order was chosen blind to repartitioning; a slightly different order might avoid a shuffle entirely |
| Integrated (one-phase) | partitioning is a physical property; exchange is an enforcer; serial and parallel alternatives compete on cost | finds shuffle-avoiding orders; standard in DB2 PE, SQL Server, Teradata, Greenplum ORCA, Spark/DataFusion physical rules | larger space; needs property heuristics |
| Two-phase with feedback / re-optimization | parallelize, observe at run time, re-plan the remainder at stage boundaries | robust to bad estimates | needs materialization points and plan-switch machinery |

The scheduling half of the two-phase idea — fixing a plan, then allocating
processors and memory to its pipelines — remains a separate step even in
integrated optimizers.

---

## 3. Partitioning as a physical property

### Property domain
`Partitioning ::= Hash(keys, n, fn) | Range(keys, splitters) | RoundRobin(n)
| Replicated | Singleton | Any(n)` — plus equivalence classes of columns
(from join predicates) so `Hash(R.a)` satisfies a requirement on `S.a` after
`R.a = S.a`.

On a shared-everything machine a parallel scan can also be "competitive" —
instances grab the next block as it is read — giving `Any(n)` with natural
load balance; on shared-nothing the scan's property is the stored placement.

### Requirements and derivations

| Operator | Required input property | Output property |
|---|---|---|
| Scan | — | stored placement (or Any(n)) |
| Filter / project | none | same as input (if a projection drops the key, the property still holds physically but can no longer be referenced) |
| Co-located equi-join | both inputs `Hash` on *corresponding* subsets of the join keys, same fn and n (or aligned ranges) | Hash on either side's key (equivalence class) |
| Broadcast join | one side Replicated (only the non-preserved side for outer/semi/anti) | property of the partitioned side |
| Group-by on G | `Hash(K)` with `∅ ≠ K ⊆ G`, or Singleton | Hash(K) |
| Two-phase group-by | none for partial; final as above | Hash(K) |
| Global sort / top-N | Range on sort key (then local sort) or Singleton | Range / Singleton |
| UNION ALL | none | Any (or the common property if both match) |
| UNION / INTERSECT / EXCEPT | co-partitioned on all output columns | Hash(all) |
| Window `PARTITION BY P` | `Hash(K)`, `K ⊆ P` | Hash(K) |

**Subset rule**: hashing on a *subset* of the grouping or join keys is
sufficient (rows equal on all keys are equal on the subset). It is also a
skew risk — fewer distinct values in the subset.

### Enforcer
Exchange creates a required property artificially, exactly as sort creates an
order. It is the "enforcer" in Volcano/Cascades (Graefe) and the "glue" in
Starburst-style rule optimizers (Lee, Freytag, Lohman, VLDB 1988). Applies to
Selinger-style bottom-up DP (DB2) and top-down Cascades (SQL Server) alike.

### Interesting partitionings and search explosion
Treat partitionings like Selinger's interesting orders: keep the best plan
per *interesting* partitioning (keys of later joins, grouping, ordering,
final output), not per possible partitioning. Example of the explosion: a
merge join on `R.a=S.a ∧ R.b=S.b ∧ R.c=S.c` is valid under any ordering on a
subset of (a,b,c) combined with partitioning on any subset of that subset.
Practical heuristics: full key set, the single most selective/most frequent
column, and whatever the inputs already have. Top-down optimizers get this
pruning naturally by only requesting what a parent needs.

> **Beyond EDBS:** In DataFusion every `ExecutionPlan` declares
> `required_input_distribution()` (`UnspecifiedDistribution`,
> `SinglePartition`, `HashPartitioned(exprs)`) and `output_partitioning()`
> (`RoundRobinBatch`, `Hash(exprs, n)`, `UnknownPartitioning`); the
> `EnforceDistribution` and `EnforceSorting` physical rules insert
> `RepartitionExec` / `CoalescePartitionsExec` / sort enforcers, and
> equivalence properties carry the column-equivalence classes. Ballista cuts
> stages at the shuffle boundaries those rules produce. A distributed planner
> on top of DuckDB has to supply this property layer itself because DuckDB's
> own optimizer is single-node.

---

## 4. Tree shape and operator-level parallelism

Split each hash join into build and probe; draw the **operator dependency
graph** (Schneider & DeWitt, "Tradeoffs in processing complex join queries
via hashing in multiprocessor database machines", VLDB 1990; their
SIGMOD 1989 paper is the Gamma evaluation of four parallel join algorithms):
pipelined groups are the nodes, blocking edges
force order.

| Shape | Available parallelism | Memory | Notes |
|---|---|---|---|
| Left-deep (probe input is the previous join's output) | only scan + one build + one probe concurrently; no independent parallelism | low: ~2 hash tables resident | long chain of short pipelines |
| Right-deep (build inputs are base relations) | all scan→build pairs independent; one long probe pipeline through all tables | high: all hash tables resident at once (or spill) | maximal pipelining |
| Bushy | both pipelined and independent, deeper pipelines possible | between | balancing deep pipelines is hard (execution skew) |
| Segmented right-deep (Chen, Lo, Yu, Young, VLDB 1992) | right-deep segments sized to memory, segments composed bushily | bounded by segment | outperformed pure left/right-deep in studies |

Rules of thumb:
- Pipelines are short and broken by stop-and-go operators; the slowest stage
  dominates; end-of-pipeline processors idle at start and front-of-pipeline
  processors idle at the end.
- Independent parallelism is easy to schedule but enlarges the working set
  (cache misses, memory bandwidth, spills).
- **Bushy branch synchronization**: two sorts feeding a merge join — the one
  that finishes first holds its memory idle until the other is done. Co-time
  branches so they finish together, or prefer plans that do not pin memory
  while waiting.

---

## 5. Costing parallel plans

Default practice (and its flaw): cost one partition assuming uniform
distribution, add synchronization cost, minimize **single-user response
time**, and compare "all nodes" against serial only. That model:
- is blind to skew (use `max` partition, not `mean` — see the skew file);
- ignores that parallelism increases total resource consumption, so it
  over-parallelizes under concurrency;
- never considers an intermediate DOP.

Better model for an engine builder:

```
cost(plan) = (response_time, total_work[, peak_memory])

pipeline segment P with operators o_j at dop_j:
  T(P) = startup(P) + max_j( work(o_j) · skew_factor(o_j) / dop_j )      # overlap, not sum
plan:
  T(plan) = longest path through the segment DAG (blocking edges serialize)
  W(plan) = Σ_j work(o_j) + Σ_exchanges network_cost
```

Compare plans on response time under a work (or resource-vector) budget that
reflects current concurrency, not response time alone.

> **Beyond EDBS:** Ganguly, Hasan, Krishnamurthy (SIGMOD 1992) argued
> response-time optimization is not a single-metric problem and that parallel
> cost must be at least two-dimensional (work and time); Garofalakis &
> Ioannidis (VLDB 1996/SIGMOD 1997) cast scheduling with multi-dimensional
> resource vectors (CPU, disk, memory, network). Treat both as the
> conceptual basis for a resource-vector cost; do not copy constants.

---

## 6. Degree of parallelism

- **Optimal DOP is finite.** With per-instance startup c and divisible work
  W: `T(p) = W/p + c·p` is minimized at `p* = sqrt(W/c)`. Small queries
  should run at low DOP (or one node); this also protects throughput.
- **Discreteness.** A cost model may want 1.5, 3.8 and 2.4 processors for
  three pipelined operators; rounding to 2, 3, 2 differs from the skew-aware
  optimum 1, 4, 2. Allocate integer processors by optimizing the max-stage
  time directly (e.g. greedily give the next processor to the current
  bottleneck stage), not by rounding.
- **Rate matching** (Mehta & DeWitt, VLDB 1995): choose producer and consumer
  DOPs so production rate ≈ consumption rate; choose *which* sites from
  current memory/CPU/disk utilization.
- Shared-nothing constraint: base-table scans run where the data is; only
  operators after an exchange (e.g. a repartitioned hash join) have a free
  home and DOP.
- Minimum useful work per instance (rows or bytes) avoids degenerate
  instances; cap DOP at the number of distinct partition-key values for
  hash-partitioned operators (more instances than keys are idle).

---

## 7. Scheduling and processor allocation

Problems identified by Wilschut, Flokstra, Apers (SIGMOD 1995) for static
allocation: inaccurate cost model (interference, memory contention, skew
unknowable at compile time), discretization error, and **pipeline delay**
(late-pipeline processors idle while early operators filter everything).

| Technique | Architecture | Idea |
|---|---|---|
| Allocation tree (Hsiao, Chen, Yu, SIGMOD 1994) | shared-disk/memory | nodes = pipeline chains, edges = precedence; give *all* processors to the root chain, then split processing power among children top-down so their outputs arrive in sync |
| IO/CPU pairing (Hong, SIGMOD 1992, XPRS) | shared-memory | classify independent tasks as IO-bound or CPU-bound, run complementary pairs together at their balance point, adjust intra-op DOP dynamically |
| Rate match (Mehta & DeWitt 1995) | shared-nothing | DOP from producer/consumer rates, sites from current utilization |
| Dynamic multi-resource (Rahm & Marek, VLDB 1995) | shared-nothing | monitor CPU, memory, disk; adjust DOP and placement at run time |
| Control operators (Brunie & Kosch 1996) | shared-nothing | compare estimates with actuals mid-plan; redistribute, change DOP |
| Dynamic processing (Bouganim et al. 1996) | hierarchical | small activations, horizontal + vertical work stealing, local first |

Scheduling rules:
- Gang-schedule producer/consumer pairs that must run together; do *not*
  co-schedule the first and last stage of a deep pipeline (the last would
  idle).
- After repeated allocate/release, a few processors may be stranded
  (fragmentation); combining intra- with inter-operator parallelism can absorb
  them, at the cost of a harder allocation problem.
- Shared-disk and shared-memory give freedom: any processor for any operator,
  no physical partitioning needed. Shared-nothing ties leaf operators to data.

### Memory as the scarce resource
- Right-deep and bushy plans require concurrent hash tables; the scheduler must
  grant memory per operator *before* choosing in-memory vs Grace vs hybrid,
  and all instances of one operator must make the same choice when the
  schedule depends on it.
- Admission control and workload classes (throttles, priorities, concurrency
  limits — Teradata TASM/TDWM, Big SQL, Impala admission control) are the
  inter-query complement of intra-query allocation; a perfectly parallel plan
  that blows the memory budget under concurrency is a bad plan.

---

## 8. Adaptive and run-time optimization

- Stage boundaries (materialized shuffles) are natural **re-optimization
  points**: actual sizes, distinct counts and heavy hitters are known.
- Typical run-time decisions: switch shuffle join → broadcast when the build
  turns out small; coalesce many tiny shuffle partitions; split skewed ones;
  push runtime (bloom/min-max) filters into probe-side scans; prune
  partitions dynamically from join-side values.

> **Beyond EDBS:** Spark 3 Adaptive Query Execution implements exactly these
> (coalesce post-shuffle partitions, convert sort-merge join to broadcast,
> skew-join splitting); Spark DPP and Impala runtime filters implement
> dynamic pruning. In a Ballista-style scheduler, the same hooks belong in the
> stage planner that runs when a shuffle stage completes.

---

## 9. Implementation checklist

- Partitioning property type with `satisfies(required, actual, eq_classes)`
  implementing the subset rule, function/bucket-count equality, and
  replicated/singleton cases; unit-test it exhaustively.
- Exchange enforcer insertion as a rule, not ad hoc in each operator.
- Cost = (time, work, memory) tuple with a skew factor from MCV statistics.
- DOP chosen per pipeline segment; cap by data volume and key cardinality.
- Plan output records per-operator expected rows *per instance* so
  EXPLAIN ANALYZE can compare against actual per-instance rows.
- Plans reference logical buckets/partitions, never node ids.

## 10. Testing

- Plan-shape snapshots: for canonical star/snowflake queries assert where
  exchanges appear (co-located join must have none; broadcast threshold
  respected).
- Property tests: random plans + random input partitionings → executed
  result equals serial result; enforcer insertion must make every plan valid.
- Outer/semi/anti join broadcasts: generate cases where the preserved side is
  small and verify the optimizer never broadcasts it.
- DOP sweep benchmarks (1, 2, 4, … nodes) checking that small queries pick
  low DOP and large ones scale.

---

Sources: Parallel Query Optimization (p.2674); Parallel Query Processing
(p.2677); Operator-Level Parallelism (p.2601); Query Load Balancing in
Parallel Database Systems (p.3004); Parallel Query Execution Algorithms
(p.2668); Parallel Hash Join, Parallel Merge Join, Parallel Nested Loops
Join (p.2666); SQL Analytics on Big Data (p.3675).
