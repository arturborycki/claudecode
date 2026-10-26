# Aggregates, outer joins and recursion in IVM

These are the three view features that break the linear delta algebra of
`delta-rules-and-counting.md`. Each needs its own auxiliary state and apply
logic. Top-k ("ranking") views are covered at the end as a special case of a
non-distributive aggregate.

## 1. Aggregates

### 1.1 Classification that matters for maintenance

The data-cube classification (distributive / algebraic / holistic) predicts
roll-up behaviour; for IVM the relevant question is per update kind.

| Function | Class | Insert | Delete | State per group |
|---|---|---|---|---|
| COUNT(*) | distributive | +1 | −1 | the count itself; mandatory |
| COUNT(x) | distributive | +[x not null] | −[x not null] | count |
| SUM(x) | distributive | +x | −x | sum + COUNT(x) (to return NULL) |
| MIN/MAX(x) | distributive for insert only | compare | not maintainable if extreme deleted | extreme, or ordered multiset |
| AVG(x) | algebraic | via SUM, COUNT | via SUM, COUNT | SUM(x), COUNT(x) |
| VAR/STDDEV(x) | algebraic | via SUM, SUM(x²), COUNT | same | three components (watch numerics) |
| COUNT(DISTINCT x) | holistic | per-value counts | per-value counts | O(distinct x in group) |
| MEDIAN, percentile, mode | holistic | order-statistic structure | same | O(group size) |

Store algebraic aggregates as their components and compute the final value
at read time (or in a computed column). Never store AVG alone.

### 1.2 Summary-delta method (single aggregation at the top)

Mumick, Quass and Mumick (SIGMOD 1997) split maintenance into two phases:

1. **Propagate**: compute a *summary-delta* table from the changes, using
   the view's own grouping. Inserted rows contribute `(+x, +1)`, deleted
   rows `(−x, −1)`:

```
SD = SELECT g, SUM(sx) AS dsum, SUM(sc) AS dcnt, SUM(snn) AS dnn,
            MIN(x_ins) AS min_ins, MAX(x_del) AS max_del ...
     FROM ( SELECT g,  x AS sx, 1 AS sc, (x IS NOT NULL)::int AS snn ...
              FROM ins(V-input)
            UNION ALL
            SELECT g, -x, -1, -(x IS NOT NULL)::int ...
              FROM del(V-input) )
     GROUP BY g
```

   Here `V-input` is the view's pre-aggregation expression evaluated on the
   delta (the SPJ delta rules apply below the aggregate).

2. **Refresh**: merge SD into the MV, one probe per affected group:

```
for (g, dsum, dcnt, dnn, ...) in SD:
    row = MV.lookup(g)
    if row is None:
        assert dcnt > 0
        MV.insert(g, sum = dnn>0 ? dsum : NULL, cnt = dcnt, nn = dnn, min = min_ins ...)
    else:
        cnt = row.cnt + dcnt;  nn = row.nn + dnn
        if cnt == 0: MV.delete(g); continue
        sum = nn == 0 ? NULL : coalesce(row.sum,0) + dsum
        min = handle_min(row.min, min_ins, deleted_values_for_g)   # 1.3
        MV.update(g, ...)
```

The propagate phase can run outside the batch window (it reads only the
changes), and the refresh phase is short -- the original motivation. For a
data cube, compute the summary-delta for the finest cuboid and derive the
coarser cuboids' summary-deltas by rolling up along the lattice, rather than
from raw changes each time.

Worked example. `sales(store, item, amt)`, `store(store, region)`;
`MV = SELECT region, SUM(amt), COUNT(*) FROM sales JOIN store USING(store)
GROUP BY region`.

```
MV:       (West, 900, 6)  (East, 300, 2)
changes:  +sales(s1 West, i4, 50)  +sales(s9 East, i2, 20)  -sales(s3 East, i1, 120)
SD:       (West, +50, +1)  (East, 20-120 = -100, +1-1 = 0)
refresh:  West -> (950, 7);  East -> (200, 2)       -- count unchanged, group stays
```

### 1.3 MIN and MAX under deletion

Insertions: `new_min = min(old_min, min_ins)`. Deletions are the problem:
if a deleted value is greater than the stored minimum, nothing changes; if it
equals the stored minimum, the new minimum is unknown without more state.
Options:

| Strategy | Cost on delete of extreme | Extra space | Use when |
|---|---|---|---|
| Recompute affected groups from base | one group re-aggregation (index on group key needed) | none | deletes rare or groups small |
| Per-group ordered multiset (value -> count) | O(log n) | O(group size) | frequent deletes, moderate groups |
| Top-k' buffer per group (k ≤ k' ≤ kmax) | O(1) until buffer drains, then refill from base | O(kmax) per group | mostly-insert workloads |
| Lazy: mark group dirty, recompute on read | deferred to reader | dirty bit | write-heavy, read-light |

Palpanas, Sidle, Cochrane and Pirahesh (VLDB 2002) address
non-distributive aggregates by identifying, from the delta, exactly which
groups need recomputation and re-aggregating only those from the base data.
Batch the recomputations: one join of the dirty-group keys against the base
input, not one query per group.

Engines that restrict MV classes to keep maintenance purely delta-driven
simply disallow MIN/MAX in immediately maintained views.

> **Beyond EDBS:** SQL Server indexed views require `COUNT_BIG(*)` whenever
> GROUP BY is present and do not allow MIN, MAX, AVG or outer joins; they
> are maintained synchronously inside the modifying statement's plan. This
> is a deliberate restriction to views that are self-maintainable from the
> delta alone. Oracle fast refresh similarly requires `COUNT(*)` and
> `COUNT(x)` companions for SUM/AVG and materialised view logs with the
> needed columns; `DBMS_MVIEW.EXPLAIN_MVIEW` reports which refresh
> capabilities a definition has.

### 1.4 Numerics

- Floating-point SUM maintained by repeated add/subtract drifts from a fresh
  recompute (non-associativity, cancellation). VAR via `SUM(x²) −
  SUM(x)²/n` is numerically unstable at large means. Prefer exact DECIMAL
  accumulators, or compensated (Kahan/Neumaier) sums with periodic
  re-baselining, and make test oracles tolerance-aware for float types.
- Integer SUM overflow: accumulate in a wider type than the input (i128 for
  i64 inputs) and check on store.

### 1.5 HAVING and nested aggregation

- `HAVING` on an MV: a group that currently fails the predicate is not in
  the visible result, but its aggregates must still be maintained, because
  a later change may make it qualify. Store all groups (hidden) and apply
  HAVING at read time or via a filtered secondary structure.
- Aggregates over aggregates (stacked views): propagating insertions and
  deletions through an intermediate aggregate (Quass's approach) forces the
  delta of the intermediate view to be computed by re-aggregating the
  affected groups from base data when the intermediate is not materialised.

**Change-table technique** (Gupta and Mumick, Inf. Syst. 2006). Instead of
turning an aggregate's change into insert/delete pairs, propagate a *change
table* -- the summary-delta generalised to any node -- up the expression,
and apply it with a parameterised `REFRESH` operator (parameters: the match
condition between change-table rows and view rows, and how each aggregate
column combines). Because the change table of a SUM/COUNT aggregate depends
only on the base changes, it propagates through joins with dimension tables
and through further SUM/COUNT aggregates without touching the base fact
table. In their analysis this costs about an order of magnitude fewer tuple
accesses than insertion/deletion propagation for typical warehouse
workloads. It also handles outer-join nodes.

Example: `SI = sales grouped by (store, item)` (not materialised);
`CitySales = SI ⋈ store` grouped by city; `CatSales = SI ⋈ item` grouped by
category (both materialised). Change table `cSI` is computed from the sales
delta alone; `cCity = γ_city(cSI ⋈ store)`, `cCat = γ_cat(cSI ⋈ item)`;
then `CitySales REFRESH cCity`, `CatSales REFRESH cCat`. The sales table is
never read.

## 2. Outer joins

### 2.1 Why outer joins are different

An outer-join result contains null-extended tuples whose presence depends on
the *absence* of matches. Inserting the first matching row on the other side
must remove the null-extended row; deleting the last match must reinstate
it. So the delta of an outer-join view has a second, non-monotone component.

### 2.2 Join-disjunctive normal form (Galindo-Legaria 1994)

Definitions (restated):

- **Outer union** `T1 ⊎ T2`: pad each operand with nulls to the union of
  their schemas, then union without duplicate removal.
- t1 **subsumes** t2 (same schema) if t1 equals t2 on every column where t2
  is non-null and t1 has strictly fewer nulls.
- `T↓` removes every tuple subsumed by another tuple of T.
- **Minimum union** `T1 ⊕ T2 = (T1 ⊎ T2)↓`; commutative and associative.

Then `T1 ⟕p T2 = (T1 ⋈p T2) ⊕ T1`, `T1 ⟖p T2 = (T1 ⋈p T2) ⊕ T2`, and
`T1 ⟗p T2 = (T1 ⋈p T2) ⊕ T1 ⊕ T2`. Inner join distributes over ⊕. Any
outer-join expression over table set U therefore normalises bottom-up to

```
E = E1 ⊕ E2 ⊕ ... ⊕ En,   Ei = σ_pi(T_i1 × ... × T_ik)
```

each term with a unique *source set* `Ti ⊆ U`, null-extended on `U − Ti`.
Terms whose predicates can never hold (a join predicate between tables not
both in Ti) are dropped.

Example (own): `V = C ⟕(c.id = o.cust) (O ⟕(o.id = l.oid) L)`.

```
O ⟕ L           = OL ⊕ O
C ⟕ (OL ⊕ O)    = C⋈(OL ⊕ O) ⊕ C = COL ⊕ CO ⊕ C
```

### 2.3 Subsumption graph and affected terms

Nodes are terms; an edge joins a term to each term whose source set is a
*minimal* proper superset of its own (its "parents"). A tuple of a term can
only be subsumed by tuples of its parents, so subsumption checks look one
level up. For the example: `C -> CO -> COL`.

When base table T changes, each term is:

- **directly affected** if T ∈ Ti;
- **indirectly affected** if T ∉ Ti but T is in the source set of some
  parent of the term;
- **unaffected** otherwise.

Updating L: COL direct; CO indirect; C unaffected. Updating O: COL, CO
direct; C indirect.

The stored result is the outer union of each term's *net contribution*
(its non-subsumed tuples), so `V = V_direct ⊎ V_indirect ⊎ V_unaffected`
and maintenance needs a **primary delta** (direct terms) and a **secondary
delta** (indirect terms).

### 2.4 Larson-Zhou procedure (ICDE 2007), insertions into T

**Primary delta** -- a rewrite of the view expression:

1. Along the path from T to the root, commute every join so the input
   containing T is on the left.
2. On that path, turn full outer joins into left outer joins, and right
   outer joins into inner joins.
3. Replace T by dT.

The path now contains only selections, inner joins and left outer joins,
with the delta always on the preserved side. Insert the result into V.

For the example and `dL`: `O ⟕ L` becomes `L ⟖ O` -> inner: `dL ⋈ O`; the
outer `C ⟕ (...)` becomes `(...) ⟖ C` -> inner. Primary delta:
`dL ⋈ O ⋈ C`. For `dO`: `(dO ⟕ L) ⋈ C`.

**Secondary delta** -- for each indirectly affected term, find its stored
null-extended tuples that are now subsumed by tuples of a parent term in the
primary delta, and delete them. Tuples of a specific term are recognisable
with null tests: pick for every source table one column that is never null
in base data (a key column); `null(T)` = that column is null. For the term
CO in the example:

```
secondary(CO) = σ[¬null(C) ∧ ¬null(O) ∧ null(L)] (V after primary insert)
                ⋉_{C,O columns equal}  σ[¬null(C,O,L)] (primary delta)
```

i.e. currently orphaned CO rows that just gained an L partner. Delete them.
The primary delta extracted per term may need duplicate elimination because
one parent tuple can extend several children.

**Deletions** are the mirror image: delete the primary delta (the same
rewritten expression on the deleted rows), then for indirectly affected
terms *insert* the null-extended tuples whose last subsuming parent tuple
disappeared (an anti-semijoin of the candidate parents' projections against
what remains in V or in the base tables).

**Foreign keys simplify**: with `L.oid -> O.id` NOT NULL and enforced, every
L row joins an O row, so terms containing L but not O are empty, and
inserting into O never makes an L tuple stop being an orphan. Prune terms
and maintenance steps using declared, enforced constraints.

History and caveats: Griffin and Kumar (1998) gave the first algebraic
change propagation for outer joins; the Gupta-Mumick (2006) procedure is
more efficient but does not always produce correct results (per Larson);
Larson-Zhou is the reference algorithm. View *matching* for outer-join views
is Larson and Zhou (VLDB 2005).

## 3. Recursive views

### 3.1 Evaluation background

A recursive view (Datalog, or SQL `WITH RECURSIVE`, which the standard
restricts to linear recursion and stratified negation) is the least
fixpoint of its rules. **Naive** bottom-up evaluation re-joins the whole
current result each iteration; **semi-naive** evaluation joins only the
tuples new in the previous iteration (one incremental rule per recursive
subgoal; subgoals over stored relations need no incremental rule). Set
semantics in bottom-up evaluation is what makes it terminate on cyclic
data. Top-down evaluation with memoing and magic-sets rewriting add
goal-directed filtering, which is irrelevant when the whole view is
materialised but matters for partially materialised recursive views.

With negation, rules are stratified: a relation used under negation must be
fully computed in a lower stratum. Maintenance proceeds stratum by stratum.

### 3.2 Why counting fails

Under bag semantics a tuple of a recursive view can have infinitely many
derivations (any cycle), and exponentially many on acyclic graphs. Counting
is therefore restricted to non-recursive strata.

### 3.3 DRed (Gupta, Mumick, Subrahmanian 1993)

For each rule `p :- q1, ..., qk` generate k deletion rules; the i-th uses
the current *over-estimate of deletions* for qi and the old state for the
others. Then:

```
DRed(stratum):
  1. over-delete:  δ−(p) := fixpoint of deletion rules over OLD state
                   (seeded with base deletions and lower-strata deletions)
  2. rederive:     δ+(p) := { t ∈ δ−(p) | t has a derivation using
                              NEW state of lower relations and
                              (MV − δ−(p)) ∪ δ+(p) for p itself }   -- fixpoint
  3. actual deletions = δ−(p) − δ+(p);  apply
  4. insert:       semi-naive propagation of insertions over NEW state
  5. pass actual changes to the next stratum
```

Worked example (own). Edges: a→b, b→c, c→d, a→c. Materialised reach.
Delete edge b→c.

```
over-delete: (b,c) from the base rule
             (b,d)  = δ−reach(b,c) ⋈ edge(c,d)
             (a,c)  = reach(a,b) ⋈ δ−edge(b,c)
             (a,d)  = δ−reach(a,c) ⋈ edge(c,d)
rederive:    (a,c) via edge(a,c)            -- survives
             (a,d) via reach(a,c), edge(c,d) -- survives, needs (a,c) first
deleted:     {(b,c), (b,d)}
```

Rederivation must itself iterate to a fixpoint, because one rederived tuple
can justify another.

Cost: the over-deletion set can be far larger than the true change (a
deleted edge near a hub over-deletes most of the closure), and each
rederivation check is a join against the new state. Indexes on both
endpoints of the edge relation and on reach are required in practice.

### 3.4 PF (Propagation-Filtering, Harrison and Dietrich 1992)

PF, developed for top-down memoing, filters each potential change
*immediately*: a candidate deletion is checked for an alternative derivation
before it is propagated; only confirmed changes propagate further. DRed
instead propagates over-estimates through the whole stratum and filters
once. Neither dominates: PF wins when over-estimates would cascade widely;
DRed wins when per-tuple filtering repeats work that a set-at-a-time
rederivation shares. For insertions, DRed simply runs semi-naive evaluation;
PF also filters candidate insertions against the old state.

### 3.5 First-order maintenance of transitive closure

Dong and Su showed that for acyclic directed graphs, transitive closure can
be maintained by first-order (relational algebra) queries without auxiliary
relations, even though TC itself is not first-order definable:

```
insert edge (a,b) (graph stays acyclic):
  TC' = TC ∪ {(a,b)} ∪ {(x,b) | TC(x,a)} ∪ {(a,y) | TC(b,y)}
           ∪ {(x,y) | TC(x,a) ∧ TC(b,y)}

delete edge (a,b):
  Sus   = {(x,y) | (x=a ∨ TC(x,a)) ∧ (y=b ∨ TC(b,y))}    -- may lose support
  Trust = (TC − Sus) ∪ E'                                -- certainly remain
  TC'   = Trust ∪ Trust∘Trust ∪ Trust∘Trust∘Trust
```

(∘ is relational composition.) Undirected graphs need auxiliary relations
(a node order, a spanning forest, and a ternary on-path relation); shortest
paths need arithmetic (+, <). This line of work (Patnaik-Immerman's
Dyn-FO class, Dong-Su arity bounds) characterises what is maintainable by
SQL-without-recursion update queries -- useful when an engine must maintain
a closure with only its non-recursive executor.

> **Beyond EDBS:** the question EDBS lists as open -- whether reachability
> in arbitrary directed graphs is maintainable in first-order logic under
> edge deletions -- was resolved positively by Datta, Kulkarni, Mukherjee,
> Schwentick and Zeume ("Reachability is in DynFO", ICALP 2015; JACM 2018),
> using auxiliary relations; the construction is theoretical, not a
> practical engine technique.
>
> **Beyond EDBS:** differential dataflow (McSherry, Murray, Isaacs, Isard,
> CIDR 2013) maintains iterative/recursive computations incrementally by
> indexing differences with a partially ordered (outer version, iteration)
> timestamp, so a change re-executes only the affected iterations. It is the
> practical route to incrementally maintained recursive SQL views
> (Materialize supports `WITH MUTUALLY RECURSIVE` on this basis). Most
> commercial MV implementations do not incrementally maintain recursive
> views at all.

## 4. Top-k (ranking) views

A materialised top-k view `R_f` (tuples ordered by a scoring function f,
first k kept) is self-maintainable for insertions (compare with the k-th
score) but not for deletions or score-lowering updates of a member: refilling
the k-th slot requires querying R. Yi, Yu, Yang, Xia and Chen (ICDE 2003)
store a buffer of k' tuples with k ≤ k' ≤ kmax, where kmax comes from a cost
model minimising amortised refill cost; the view refills from base only when
the buffer drops below k. This is the same pattern as 1.3's top-k' buffer
for MIN/MAX.

Answering a new ranking function g from materialised ranking views
(PREFER, Onion, Das et al. 2006) is a rewriting problem; see
`query-rewriting-using-views.md`.

## 5. Pitfalls

- No COUNT(*) in aggregate MV: group lifetime undecidable.
- MIN/MAX delete detection compares against the *stored* extreme with the
  wrong collation or NULL ordering.
- HAVING groups dropped from storage.
- Change-table REFRESH applied with the wrong combine function (SUM of
  COUNT vs COUNT of rows) when propagating through a second aggregate.
- Outer-join null tests on a nullable column, misclassifying a real NULL as
  null-extension.
- Outer-join secondary delta computed before the primary delta is applied
  (or vice versa for deletions) -- the procedure fixes the order.
- DRed rederivation reading the old state, or not iterating.
- Recursive MV with negation maintained across strata in the wrong order.

## Key papers

Mumick, Quass and Mumick, SIGMOD 1997; Quass, PhD thesis 1997; Gupta and
Mumick, Inf. Syst. 2006; Palpanas et al., VLDB 2002; Gray et al., data cube
(ICDE 1996) for the classification; Galindo-Legaria, SIGMOD 1994; Griffin and
Kumar, SIGMOD Record 1998; Larson and Zhou, VLDB 2005 and ICDE 2007; Gupta,
Mumick and Subrahmanian, SIGMOD 1993; Harrison and Dietrich 1992; Dong and
Su, Inf. Comput. 1995 and SIGMOD Record 2000; Pang, Dong and Ramamohanarao,
TODS 2005; Yi et al., ICDE 2003.

Sources: EDBS "Incremental Maintenance of Views with Aggregates" (p.1838),
"Maintenance of Materialized Views with Outer-Joins" (p.2165), "Maintenance
of Recursive Views" (p.2170), "Incremental Computation of Queries" (p.1830),
"Ranking Views" (p.3092).
