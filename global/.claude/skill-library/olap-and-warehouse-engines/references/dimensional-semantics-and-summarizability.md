# Dimensional semantics and summarizability

What the engine must know about facts, dimensions, hierarchies and measures in
order to aggregate correctly and to reuse precomputed aggregates safely. This
is the semantic layer underneath every pre-aggregation, rewrite and rollup
optimization in the rest of the skill.

## 1. The canonical multidimensional model, stated precisely

| Concept | Precise meaning | Engine artefact |
|---|---|---|
| Dimension | a set of dimension values partially ordered by containment, with a single top value ALL (⊤) | dimension table(s) + hierarchy metadata |
| Level (category) | a class of dimension values at one grain (Day, Month, Year) | column(s) of the dimension table, or one table per level (snowflake) |
| Hierarchy | a path (or DAG) of levels from a bottom level to ⊤; several hierarchies may share bottom levels (fiscal vs calendar) | ordered list of level ids per hierarchy |
| Level property | descriptive, non-hierarchical attribute of a level (weekday of a date, colour of a product) | non-grouping attribute; does not add a cube axis |
| Fact | a non-empty cell: a combination of one bottom-level value per dimension | fact row with one FK per dimension |
| Grain | the levels a fact's coordinates are drawn from ("day × product × store") | declared on the fact table; drives join cardinality |
| Measure | numeric property of the fact **plus** an aggregation rule | fact column + catalog aggregation metadata |
| Cube | the measure-valued function over the cross product of dimension domains | fact table (ROLAP) or array (MOLAP) |

Observations that matter to an engine:

- Dimension values usually carry **no ordering or metric** other than
  containment; Time is the exception (ordering enables YTD, moving windows,
  LAST_VALUE semantics). Treat ordered dimensions specially in the catalog.
- Real cubes typically have 4–12 dimensions; tooling degrades past 10–15.
  Sparsity grows with dimensionality and with finer grains — this is why
  dense-array MOLAP needs chunking (see `array-and-multidimensional-storage.md`).
- Redundancy is tolerated in dimensions (denormalized star) but not in facts.
  An engine can therefore assume dimension tables are small and replicable,
  fact tables are huge and partitioned.
- Most models force each fact to map to exactly one bottom-level value per
  dimension. Multi-valued dimensions (a sale attributed to several
  salespeople) violate this and need a bridge table with weights.

### Fact types (Kimball; Jensen–Pedersen–Thomsen)

| Fact type | Represents | Additivity consequence |
|---|---|---|
| Event (transaction) fact | one real-world event, 1:1 or many:1 compacted | measures typically additive (flow) |
| Snapshot fact | state of a process at an instant (inventory per SKU per month) | measures semi-additive over time (stock) |
| Cumulative snapshot fact | state up to an instant (sales year-to-date) | additive across non-time dims; never re-summed over time |
| Factless fact | events with no measure (attendance, coverage) | only COUNT; coverage tables for "what did not happen" |

The same base data (goods movements) commonly feeds a flow cube, a stock cube
and a YTD cube; the engine should not try to derive one from the other with
plain SUM.

## 2. Star and snowflake as schema graphs

- **Star**: one central table whose compound key consists of FKs, one per
  dimension table; no other FKs anywhere. Hierarchies are flattened into the
  dimension table (typically 2NF).
- **Snowflake**: same centre, but dimension tables may have FKs to further
  level tables, forming trees rooted at the fact table; each non-fact table is
  referenced by exactly one FK. Typically 3NF dimensions.
- Both use **surrogate keys** (dense integers generated at load). For an
  engine this is gold: dense 0..n keys allow array lookups instead of hash
  tables in star joins and make range-encoded key sets compact.

Engine consequences:

1. Star detection is a graph check: one node with ≥ 2 outgoing FK edges to
   nodes that are much smaller and have no FKs (star), or whose FK subtrees
   are disjoint (snowflake). Once detected, the optimizer can restrict join
   enumeration (dimensions only join through the fact) and treat each
   snowflake branch as one composite dimension subplan.
2. Join cardinality is predictable: an inner join from fact to dimension on a
   trusted FK neither adds nor removes fact rows. That makes join elimination
   (dimension not referenced except through key) and group-by pushdown legal —
   but only if the FK is enforced or declared RELY and the loader honours it.
3. Conformed dimensions (one product dimension shared by all marts) are the
   precondition for **drill-across** (combining measures of two facts on
   shared dimensions): join the two aggregated results on the conformed
   levels, never the raw facts (that would multiply rows). Precise test
   (Golfarelli, after Kimball): two dimension copies are conformed iff they
   are identical — same keys, same attribute values — or one is a proper
   subset of the other (e.g. a Month-level calendar derived from the Day-level
   one). An engine can verify this mechanically (key-set containment plus
   attribute equality on shared keys) before enabling drill-across.

## 3. Hierarchy regularity: strict, onto, covering

Let levels L_low → L_high be consecutive in a hierarchy and `parent(v)` the
set of L_high values containing v.

| Property | Definition | Violation example | Symptom when violated |
|---|---|---|---|
| Strict | every non-top value has at most one parent: \|parent(v)\| ≤ 1 | skimmed milk in both "Diet" and "Dairy" | values counted once per parent: roll-up of child aggregates exceeds total |
| Onto (balanced) | every non-bottom value has at least one child at the next lower level; uniform depth | a Research department with no sub-groups; facts attached at department level | facts attached above the bottom are lost by aggregates materialized at the bottom level |
| Covering (non-ragged) | containment links connect only adjacent levels | Danish cities directly under Denmark (no state level) | aggregates at the skipped level omit those values; totals derived from them are too low |

Also: **multiple hierarchies** (calendar/fiscal; week does not roll into
month) — roll-up from Week to Month is invalid; the lattice of a dimension is
a DAG, not a chain, and the rewriter must check reachability, not depth.

### Normalization techniques (Pedersen, Jensen, Dyreson 1999; Niemi et al. 2001)

- Non-onto → add placeholder children ("Research-other") down to the bottom
  so facts attached higher can be re-attached at the bottom level.
- Non-covering → insert placeholder values at skipped levels
  ("Denmark-state") so every path passes every level.
- Non-strict → either (a) choose a primary parent for summarizable roll-up and
  keep the others as an alternative, non-reusable hierarchy, or (b) use a
  bridge table (child, parent, weight) with Σ weights per child = 1 so that
  allocated measures sum correctly; or (c) accept double counting at the
  middle level (often desired: both groups report the product) but forbid
  reusing those middle aggregates for the grand total.

Engines that support "practical pre-aggregation" for irregular hierarchies
first apply these transformations, then pre-aggregate only on the normalized
hierarchy.

## 4. Measures: additivity and aggregate-function classes

Two orthogonal classifications; both belong in the catalog.

### 4.1 Additivity of the measure (semantic, per dimension)

| Class | Measure type (statistics) | Example | SUM valid along |
|---|---|---|---|
| Additive | flow (events over a period) | sales amount, units, clicks | all dimensions |
| Semi-additive | stock (level at an instant) | inventory, account balance, headcount | all except time (and sometimes other "snapshot" dims) |
| Non-additive | value-per-unit (ratio, rate, price) | unit price, margin %, discount % | none |

For semi-additive measures the valid temporal rules are LAST (closing
balance), FIRST (opening), AVG over time, MIN, MAX. Non-additive measures are
recomputed from additive components: margin% = SUM(profit)/SUM(cost) — store
the components, never the ratio.

### 4.2 Lenz–Shoshani temporal summarizability (who may aggregate what over time)

| Measure type | MIN | MAX | SUM | AVG | RANGE |
|---|---|---|---|---|---|
| stock | yes | yes | **no** | yes | yes |
| flow | yes | yes | yes | yes | yes |
| value-per-unit | yes | yes | **no** | yes | yes |

Non-temporal aggregation: all combinations are fine except SUM of
value-per-unit. This table is a directly implementable rule set: attach
`measure_type` to each measure and `is_temporal` to each dimension; reject
(or rewrite) a SUM that violates it.

> **Beyond EDBS:** commercial semantic layers implement exactly this. SQL
> Server Analysis Services offers per-measure aggregate functions such as
> LastNonEmpty, FirstNonEmpty, LastChild, AverageOfChildren and ByAccount;
> DAX exposes semi-additive patterns via functions like LASTNONBLANK and
> CLOSINGBALANCEMONTH. If an engine wants BI tools to stop producing wrong
> totals, the metadata has to live in the engine or its semantic layer.

### 4.3 Aggregate function classes (Gray et al.)

| Class | Definition | Examples | Storable in cube / reusable |
|---|---|---|---|
| Distributive | F(∪ partitions) = G(F(p1),…,F(pk)) with fixed-size state | SUM, COUNT, MIN, MAX | yes, directly |
| Algebraic | computable from a fixed number of distributive sub-aggregates | AVG (SUM,COUNT), STDDEV (SUM, SUM², COUNT), MAX-N | yes, if the components are stored |
| Holistic | no constant-size state suffices | MEDIAN, MODE, RANK, COUNT DISTINCT | no; store at every needed level or recompute from base |

Engine rule: an aggregate state type must declare `init / update / merge /
finalize`; only distributive and algebraic states have bounded `merge`. A
materialized aggregate must store the *state*, not the finalized value, for
any algebraic measure it is supposed to roll up.

> **Beyond EDBS:** mergeable sketches move several holistic aggregates into
> "distributive-in-sketch-space": HyperLogLog (Flajolet et al. 2007) for
> COUNT DISTINCT, KLL or t-digest for quantiles. They make rollup reuse
> possible at the price of bounded error; the engine must label such results
> approximate and keep sketch parameters identical across merged partials.

## 5. Summarizability: the three conditions

A dimension is summarizable for a measure if aggregating that measure over
the dimension (and every level of its hierarchy) gives correct results.
Lenz and Shoshani identify three necessary conditions (sufficiency is
believed but not proven):

1. **Disjointness** — between consecutive levels the child sets of distinct
   parents are disjoint (strictness; one-to-many from high to low).
2. **Completeness** — every parent's children are all present, relative to
   the measure's meaning. "Population by city → state" is incomplete (rural
   population is missing) unless the measure is defined as
   "population in cities" or an `other_areas` member is added. Age bands
   0–10 … 90–100 are complete only if no one is older than 100.
3. **Type compatibility** — measure type, aggregate function and dimension
   kind (temporal or not) must be compatible (table 4.2).

Pedersen et al. phrase the structural part as: the aggregate function must be
distributive and the hierarchy strict, onto and covering. Hurtado and
Mendelzon (ICDT 2001; TODS 2005) give a constraint-based characterization for
heterogeneous dimensions: a level is summarizable from a set of lower levels
iff certain dimension constraints hold, which can be tested on the dimension
instance — this is the formal basis for a rewriter guard.

### 5.1 Implementable checks (run at load and before enabling reuse)

```sql
-- strict: no child with two parents at the next level
SELECT child_key FROM dim_edges WHERE child_level = :L
GROUP BY child_key HAVING COUNT(DISTINCT parent_key) > 1;

-- covering + onto: every bottom member reaches every declared level
SELECT b.member FROM bottom_members b
LEFT JOIN ancestors a ON a.member = b.member AND a.level = :L
WHERE a.member IS NULL;

-- FK completeness of facts (invariant 4 in SKILL.md)
SELECT COUNT(*) FROM fact f LEFT JOIN dim d ON f.dim_sk = d.sk
WHERE d.sk IS NULL;
```

Record the result per (hierarchy, level pair) as a catalog bit; the rewriter
consults it. If data can change, re-verify per load or maintain counters
incrementally (parents-per-child histogram).

### 5.2 Rewrite guard (aggregate navigation) — pseudo-code

```
can_answer(Q, V):
  for each dimension d:
     lq = Q.level[d]; lv = V.level[d]
     if not reachable(lv -> lq in hierarchy DAG of d): return false
     for each edge (a -> b) on the path lv..lq:
        if not catalog.summarizable(d, a, b): return false
  for each aggregate f in Q:
     if f.class == HOLISTIC and Q.level != V.level: return false
     if f.class == ALGEBRAIC and not V.stores_components(f): return false
     for each dimension d rolled up: if not measure_rule_allows(f, d): return false
  if not predicates_expressible(Q.where, V.columns ∪ FK-derivable columns): return false
  if V.freshness < Q.required_freshness: return false
  return true
```

## 6. Slowly changing dimensions as an engine concern

Kimball's types and their engine impact:

| Type | Behaviour | Engine impact |
|---|---|---|
| 0 | keep original value | none |
| 1 | overwrite | historical reports change; aggregates grouped by the attribute become stale — must be refreshed |
| 2 | new row (new surrogate) per change, validity interval, current flag | dimension grows; fact FK points to version; "as-was" reporting free, "as-is" needs join on natural key + current flag |
| 3 | previous + current value columns | limited history; extra columns |
| 4 | current table + history table | two-table lookup at load |
| 6 | 1+2+3 combined (version rows plus current-value column) | both as-was and as-is from one row |

Minidimensions split volatile attributes (income band) from stable ones
(name) to stop type-2 explosion. Invariant: a type-2 lookup at load must use
the version valid at the **event time**, not at load time — late-arriving
facts break naive "current row" lookups.

> **Beyond EDBS:** SQL:2011 application-time/system-time periods are the
> engine-native alternative to hand-built type-2 tables; see
> `temporal-databases`.

## 7. OLAP operator algebra (Romero–Abelló reference set)

A minimal, mutually independent operator set; any OLAP session is a sequence:

| Operator | Effect | Relational realization |
|---|---|---|
| Selection (dice) | keep cells satisfying a predicate on dimension attributes | WHERE on dimension columns (semijoin into the fact) |
| Roll-up | coarsen one dimension along a part-whole hierarchy edge | join to level, GROUP BY coarser level (guarded by §5) |
| Drill-down | inverse of roll-up | re-query at finer grain (needs finer data/aggregate) |
| ChangeBase | re-arrange the space: pivot axes, add/remove dimensions | change grouping set / output order |
| Drill-across | change the fact, keep the space | aggregate each fact separately, join on conformed levels |
| Projection | choose a subset of measures | SELECT list |
| Set operations | union/difference/intersection of cubes over the same space | UNION/EXCEPT/INTERSECT on aggregated results |

Derived: slice = selection fixing one value + ChangeBase removing the
dimension; drill-through = go below the mart's grain to source data.
Well-formedness: aggregated categories must partition the lower level
(complete and disjoint) and measure/function/dimension must be compatible —
the same conditions as §5.

### MDX semantics in one paragraph

`SELECT <sets> ON COLUMNS, <sets> ON ROWS FROM cube WHERE (<slicer tuple>)`
places the cube's cells in the space spanned by the axis sets; every
dimension not on an axis is implicitly sliced at its default member (usually
ALL); `WITH MEMBER` defines calculated members evaluated per cell. Compiling
MDX to SQL means: each axis tuple becomes a grouping-set member, the slicer
becomes a WHERE predicate, calculated members become expressions over
aggregated components (so they must be algebraic). Non-empty behaviour
requires suppressing all-NULL tuples — an anti-join against the fact.

## 8. What-if analysis (hypothetical cubes)

What-if analysis runs a simulation model over historical cube data to
predict dependent variables under a scenario. Vocabulary (Rizzi): business
variables; **source variables** (the levers the user sets: promotion type,
duration, product category); **scenario parameters** (technical: regression
type, history length); the prediction is itself a cube explored with OLAP.

Engine-level requirements:

- Hypothetical updates as an ordered set of modifications layered over a base
  cube without copying it (Balmin, Papadimitriou, Papakonstantinou, Sesame,
  VLDB 2000): evaluate queries over "base ⊕ hypothetical deltas", ideally by
  rewriting to base aggregates plus delta aggregates.
- **Disaggregation** operator: apportion a value forecast at a coarse level
  down a hierarchy by a weight derived from another measure (transport cost
  by branch-month split by product type proportionally to shipped quantity).
  Weights must sum to 1 per parent — the same contract as bridge tables.
- Write-back/planning cubes need copy-on-write versions of cells; keep
  scenarios isolated (per-session overlays) and never let them leak into
  shared aggregates.
- Distinguish from sensitivity analysis (small perturbations) and from plain
  forecasting (extrapolation); system-dynamics models introduce feedback loops
  of stock and flow variables — the stock/flow distinction is the same one
  that governs additivity.

A seven-phase design method (goal analysis, business modelling, source
analysis, multidimensional modelling, simulation modelling, implementation,
validation) is proposed by Golfarelli, Rizzi and Proli (DOLAP 2006).

## 9. Pitfalls checklist

- Aggregating a ratio, or storing finalized AVG in an aggregate table.
- Summing balances across months; summing YTD snapshots.
- Rolling Week into Month; mixing fiscal and calendar paths.
- Reusing middle-level aggregates of a non-strict hierarchy for totals.
- Joining facts to a type-2 dimension on natural key.
- Treating NULL produced by ROLLUP as a real NULL value.
- Drill-across by joining raw fact tables.
- Facts with FKs to missing dimension rows (inner join drops them).

Sources: EDBS — Multidimensional Modeling p.2328; Measure p.2217; Dimension
p.1099; Hierarchy p.1705; Summarizability p.3843; Star Schema p.3703;
Snowflake Schema p.3520; Online Analytical Processing p.2558; Cube p.709;
Data Mart p.793; Data Warehouse p.876 (recovered tail: conformed-dimension
test from the adjacent life-cycle text); What-If Analysis p.4683.
