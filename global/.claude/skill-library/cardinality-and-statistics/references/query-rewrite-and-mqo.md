# Query rewriting and multi-query optimization

Rewrites reshape the query before (or around) cost-based enumeration;
multi-query optimization (MQO) shares work across queries or within one query.
Both interact closely with estimation: rewrites decide which joins and
predicates the estimator ever sees, and many rewrites are only wins when the
estimates say so.

## 1. The rewrite phase

After parsing and translation into an internal form (relational algebra,
Starburst's Query Graph Model), the rewriter transforms the query into an
equivalent one using rules that do **not** depend on the physical state
(table sizes, load). Its three goals:

- **Standardization**: a canonical starting point for the optimizer (normal
  forms for predicates, flattened blocks, consistent operand order).
- **Simplification**: remove redundancy (duplicate predicates, joins that do
  not affect the result, impossible branches).
- **Amelioration**: produce forms that evaluate better (unnested subqueries,
  index-friendly predicates).

Typical rewrites: view expansion and merging, predicate rewriting to match
index capabilities, semantic optimization (redundant join and predicate
elimination), subquery flattening. Rewrite can be the first phase of the
optimizer or a separate component in front of it (Starburst's rule-based
rewrite engine, Pirahesh, Hellerstein & Hasan, SIGMOD 1992).

Heuristic vs costed. Some rewrites are always (or almost always) beneficial —
predicate pushdown, constant folding, simple view merging. Others can lose:
unnesting into a large join, complex view merging that pulls GROUP BY above a
join, magic sets, aggregation pushdown. Those should be costed, either by
running the enumerator on both alternatives or by keeping both in the memo.

> **Beyond EDBS:** Oracle made this explicit with cost-based query
> transformation (Ahmed et al., VLDB 2006): transformations such as complex view
> merging, subquery unnesting and group-by placement are applied in alternative
> combinations and each resulting query is costed by the physical optimizer.

## 2. Canonical translation and the first rewrites

A SELECT-FROM-WHERE block translates naively into a cross product of the FROM
items, a selection with the WHERE condition and a projection. The first
rewrites turn conjuncts that reference two inputs into join predicates and push
single-table conjuncts below the join. Everything after that is enumeration plus
the rewrites below.

## 3. View merging and predicate pushdown into views

- **Simple (SPJ) view merging**: substitute the view body and flatten into the
  outer block; the enumerator then sees all joins together and can interleave
  view tables with outer tables. Optimizing the view separately and treating it
  as a base relation with fixed cost loses such plans and blocks predicate
  pushdown.
- **Complex view merging**: views with DISTINCT or GROUP BY. Merging pulls the
  aggregation above the outer block's joins; legal when the grouping is
  extended with a unique key of each joined outer table (Oracle adds rowids),
  so the join cannot merge or split groups. May increase the join input size,
  so cost it.
- **Predicate pushdown into non-mergeable views** (legal cases):
  through GROUP BY only for predicates on grouping columns; through window
  functions only for predicates on PARTITION BY columns; into both branches of
  UNION ALL; into the preserved side of an outer join only when the predicate is
  on preserved columns; never through LIMIT/TOP or non-deterministic functions.
- **Outer-join simplification**: a WHERE predicate on the null-supplying side
  that rejects NULLs converts LEFT JOIN to inner join (and FULL to LEFT/RIGHT),
  unlocking free reordering. Predicates in ON vs WHERE differ in meaning for
  outer joins; preserve that distinction in the IR.

## 4. Subquery unnesting (decorrelation)

System R optimized nested blocks separately; a correlated block was
re-evaluated per outer tuple (or per distinct correlation value). Nested-loop
evaluation of a dependent subquery is the single biggest source of
"query never finishes" plans; unnesting makes the subquery evaluable
independently and joins its result back.

Kim's classification (TODS 1982): type N (uncorrelated, no aggregate; IN),
type A (uncorrelated, aggregate; evaluate once as a constant), type J
(correlated, no aggregate), type JA (correlated with aggregate).

Semantics-preserving mapping:

| Construct | Unnested form | Trap |
|---|---|---|
| `x IN (SELECT y ...)` | semijoin on x = y | rewriting to an inner join duplicates rows unless y is unique |
| `EXISTS (corr. subq)` | semijoin on correlation predicates | |
| `NOT EXISTS (corr. subq)` | anti-join | |
| `x NOT IN (SELECT y ...)` | **null-aware** anti-join | if any y is NULL the predicate is never true; if x is NULL it is unknown (TRUE only for an empty subquery) — plain anti-join is wrong |
| scalar subquery `= (SELECT agg ...)` correlated | group-by on correlation columns + outer join | COUNT bug |
| scalar subquery without aggregate | join with a runtime at-most-one-row check | must raise an error on >1 row |

**The COUNT bug** (Kiessling 1985; Ganski & Wong, SIGMOD 1987): for
`WHERE R.n = (SELECT COUNT(*) FROM S WHERE S.k = R.k)`, rewriting to an inner
join with `S GROUP BY k` loses every R row whose k has no S rows — exactly the
rows where COUNT should be 0. Correct form: left outer join R to the grouped S,
and compare with `COALESCE(cnt, 0)` (or count a non-nullable S column after
the outer join). The same issue affects any aggregate whose value on the empty
set is not NULL.

Generalizations:
- Dayal (VLDB 1987): unnest with outer joins and aggregation in general;
  Muralikrishna (VLDB 1992): improved algorithms for join-aggregate queries.
- **Magic decorrelation** (Seshadri, Pirahesh & Leung, ICDE 1996): compute the
  distinct set of correlation values from the outer block, evaluate the
  subquery once for that whole set (grouped by the correlation columns), then
  join back. Works for arbitrary nesting depth.
- **Apply operator** (Galindo-Legaria & Joshi, SIGMOD 2001): represent
  correlation explicitly as Apply (dependent join) and remove it with algebraic
  rules that push Apply down until the right side no longer references the left.
- **Reusing invariants** (Rao & Ross, SIGMOD 1998): when full unnesting is not
  possible, compute the part of a correlated subquery that does not depend on
  the outer row once and reuse it across invocations; memoize results per
  distinct correlation value.

> **Beyond EDBS:** Neumann & Kemper, "Unnesting arbitrary queries" (BTW 2015),
> decorrelate any dependent join by computing the domain of the free variables,
> pushing the dependent join down through every operator type until it becomes a
> regular join, and eliminating the domain when it is implied by existing
> predicates. HyPer/Umbra use it, and DuckDB adopted the approach.

Estimation consequences: unnested forms expose semijoins and grouped joins to
the estimator. Semijoin selectivity is the fraction of outer values with at
least one match (estimate as min(1, NDV_inner / NDV_outer) under containment),
not the inner-join selectivity.

## 5. Predicate inference and move-around

- **Equivalence classes**: from `a = b` and `b = c` derive `a = c`; with a
  constant, `a = 5 and a = b` gives `b = 5`, pushing a filter onto the other
  table; ranges propagate too (`a > 5 and a = b` gives `b > 5`). Every join edge
  inside a class becomes an enumeration option, so connectivity improves.
- **Predicate move-around** (Levy, Mumick & Sagiv, VLDB 1994): move predicates
  up out of views and blocks and down into others, including through
  aggregation when functional dependencies or grouping keys permit, so a filter
  written in one view restricts another.
- **Constraint-based inference**: CHECK constraints and partition bounds
  imply predicates; contradiction detection (`a > 5 and a < 3`) yields an empty
  result without execution.

Estimator rule: implied predicates must be tagged; an equivalence class
contributes its selectivity once per relation set no matter how many redundant
edges are applied (see SKILL.md invariant 7).

## 6. Magic sets

Origin: bottom-up Datalog evaluation (Bancilhon, Maier, Sagiv & Ullman, PODS
1986; Beeri & Ramakrishnan). For SQL: Mumick, Finkelstein, Pirahesh &
Ramakrishnan, "Magic is relevant" (SIGMOD 1990); costed integration in Seshadri
et al. (SIGMOD 1996).

Idea (sideways information passing): when a derived table — usually an
aggregating view — is joined with a selective outer, compute the set of join
values the outer can ever ask for (the magic set: distinct projection of the
filtered outer on the join columns), restrict the view's inputs to those values
by a semijoin **before** the expensive work (aggregation, recursion), then join
as usual.

```
Q:  SELECT e.name FROM emp e, dept d, avg_sal_by_dept v
    WHERE e.dept = d.id AND d.city = 'Lisbon' AND v.dept = d.id AND e.sal > v.avg
magic(dept) = SELECT DISTINCT d.id FROM dept d WHERE d.city = 'Lisbon'
v'          = SELECT e2.dept, AVG(e2.sal) FROM emp e2 SEMIJOIN magic ON e2.dept = magic.dept
              GROUP BY e2.dept
Q'          = Q with v replaced by v'
```

Cost trade-off: the magic set and extra semijoin cost something; the win is
proportional to how much the semijoin cuts the view's input. Unselective outer
-> loss. Hence costed application. Runtime analogues: semijoin reduction in
distributed plans (R*), Bloom-filter/runtime-filter pushdown from a hash-join
build side into the probe-side scan — the cheap, adaptive cousin of magic sets
used by most modern engines.

Magic sets matter most for recursive queries (WITH RECURSIVE): restricting the
seed by the outer binding can turn a full transitive closure into a reachability
query from a few start nodes.

## 7. Semantic optimization

Using declared (and trusted/enforced) constraints:
- **Join elimination**: a FK -> PK join where no PK-side column is used, the FK
  is NOT NULL and the constraint is enforced, can be dropped (common with views
  over star schemas). With nullable FK, replace by `fk IS NOT NULL`.
- **DISTINCT / GROUP BY elimination** when a key of the input is contained in
  the grouping set; reduce grouping columns by functional dependencies.
- **ORDER BY elimination** when input order is guaranteed (physical property).
- **Outer join to inner** when a FK guarantees a match.
- **Redundant predicate removal** using CHECK constraints.
Unenforced "informational" constraints are a correctness risk; only trust them
when the user opted in.

## 8. Aggregation placement

- Push GROUP BY below a join (eager aggregation) when it reduces the join
  input and the join does not change group membership, adding compensation:
  SUM over a duplicating join needs multiplication by the partner count; AVG
  splits into SUM and COUNT; COUNT(DISTINCT) and other holistic aggregates do
  not decompose.
- Pull GROUP BY above a join (lazy aggregation) when the join is very
  selective.
- Partial (local) pre-aggregation before a shuffle in MPP plans, whose benefit
  depends on the NDV of the grouping key per partition — an estimation problem.
- References: Yan & Larson (ICDE 1994, VLDB 1995), Chaudhuri & Shim (VLDB 1994).

## 9. Small but valuable rewrites

- Sargability: `col + 1 = 5` -> `col = 4`; `substr(col, 1, 3) = 'abc'` ->
  `col LIKE 'abc%'` (a range); `date_trunc('day', ts) = d` -> half-open range.
- OR expansion: `a = 1 OR b = 2` -> UNION ALL of index-friendly branches with
  duplicate suppression (`... AND (a = 1) IS NOT TRUE` in the second branch —
  plain `NOT (a = 1)` loses rows where `a` is NULL; Oracle's `LNNVL`).
- Large IN-lists -> join with a VALUES relation (estimable, hashable).
- Constant folding, CASE simplification, NOT pushdown (De Morgan) with
  three-valued logic preserved.

## 10. Multi-query optimization

Goal: a consolidated evaluation plan for a set of queries (or for one query with
repeated subexpressions) that shares work — computing a **common
subexpression (CSE)** once, or sharing one scan among several consumers.

Benefit of sharing expression E among k consumers (materialized):

```
saving = (k - 1) * cost(E)  -  cost(write E)  -  k * cost(read E)
```

EDBS's example: batches (A join B join C) and (B join C join D), scans 10, joins
100: independent plans 460; computing and materializing B join C once and
reading it twice gives 370, about 20% less — and the gap grows with batch size.

Why it is hard: with sharing, the principle of optimality fails. The globally
best consolidated plan may use a subplan that is suboptimal for its own query
(e.g., a join order for one query that exposes the shared B join C). So per-query
DP followed by matching ("share only among each query's best plan",
Subramanian & Venkataraman, SIGMOD 1998) is cheap but can be far from optimal.

The practical algorithm (Roy, Seshadri, Sudarshan & Bhobe, SIGMOD 2000):
1. Build one **Logical Query DAG (LQDAG)** for all queries: the Volcano memo
   extended to many roots. Equivalence nodes = distinct intermediate results;
   operation nodes = alternative ways to compute them. Memoization here is
   equivalent to System R-style DP.
2. Identify **sharable** equivalence nodes (used by more than one query, or
   more than once in one plan) in a single bottom-up traversal.
3. **Greedy** selection: repeatedly materialize the node with the largest
   benefit (cost decrease of the best consolidated plan given nodes already
   chosen) until no node helps. Make it affordable with incremental cost
   re-computation over the DAG and a monotonicity heuristic (a node's benefit
   does not grow as others are chosen, so stale upper bounds can be checked
   lazily).
Variants in the same work: Volcano-SH (post-pass deciding which shared nodes of
Volcano's best plans to materialize) and Volcano-RU (optimize queries in
sequence, favouring reuse of earlier results).

Refinements:
- **Pipelining** instead of materializing shared results, under limited
  buffers, with schedules that avoid deadlock (Dalvi et al., JCSS 2003).
- **Scheduling and caching** shared results in limited memory (Diwan,
  Sudarshan & Thomas, COMAD 2006).
- **Similar subexpressions** (Zhou, Larson, Freytag & Lehner, SIGMOD 2007,
  in SQL Server): subexpressions that differ in predicates can share a
  *covering* subexpression (union of predicates, superset of columns) with
  compensating filters on each consumer.

Applications: OLAP and reporting batches over the same joins; CTEs referenced
several times (materialize vs inline is an MQO decision); invariant parts of
correlated subqueries; maintenance plans for many materialized views (Mistry et
al., SIGMOD 2001); XPath-to-SQL translations with overlapping queries; shared
aggregation over streams (Krishnamurthy, Wu & Franklin, SIGMOD 2006).

> **Beyond EDBS:** PostgreSQL (12+) inlines a CTE referenced once and
> materializes one referenced several times by default, with `MATERIALIZED` /
> `NOT MATERIALIZED` overrides — a fixed policy rather than a costed choice;
> a costed engine should evaluate both.

Implementation notes:
- Detect CSEs by **hash-consing** canonical expressions in the memo:
  normalize commutative operands and conjunct order, resolve column
  equivalences, and hash. Subsumption (covering) needs predicate implication tests.
- A shared node has several parents: cost it once, attribute it to the plan
  root, and model materialization as write + per-consumer read, or pipelining as
  a memory (spatial) constraint.
- Shared scans at runtime (cooperative/circular scans) are the execution-side
  counterpart; they need no plan-time CSE detection.

## 11. Pitfalls

- Unnesting `NOT IN` as a plain anti-join (NULL semantics).
- Unnesting `IN` into an inner join without a uniqueness proof (duplicates).
- COUNT bug and its siblings for other non-NULL-on-empty aggregates.
- Pushing predicates through LIMIT, window functions on non-partition columns,
  or volatile functions.
- Magic/semijoin rewrites applied unconditionally on unselective outers.
- Derived predicates double counted by the estimator.
- Join elimination on unenforced constraints.
- MQO greedy recomputing every benefit from scratch each round (quadratic
  optimizer calls); use incremental DAG cost propagation.
- Materializing a shared CTE whose consumers each push a different selective
  predicate into it: inlining with pushdown would have been cheaper.

Sources: Query Rewriting p.3060; Query Optimization (in Relational Databases)
p.3009; Query Optimization p.3008; Multi-query Optimization p.2425; System R
(R*) Optimizer p.3866.
