# Answering and rewriting queries using views

Scope: the theory (containment, equivalent and maximally-contained
rewritings, complexity), the rewriting algorithms (bucket, inverse rules,
MiniCon, chase & backchase), how production optimizers match materialised
views, view selection, and view adaptation. Ranking-view reuse is at the end.

## 1. Problem variants

Given a query Q over schema Σ (language L_Q), views V1..Vn over Σ (language
L_V), find a query Q' (language L_R) over the views -- and possibly base
relations -- that answers Q. The "parameters" change the problem completely:

| Parameter | Choices | Where it shows up |
|---|---|---|
| Goal | equivalent rewriting / maximally-contained rewriting / cheapest plan | optimizer: equivalent; integration: maximally contained |
| Access | views only (complete rewriting) / views + base tables (partial) | optimizer: partial; LAV mediator: views only |
| View semantics | closed world (view = exactly Q_V(D)) / open world (view ⊆ Q_V(D), sound only) | warehouse MVs: closed; data sources: open |
| Languages | CQ, CQ with comparisons, unions, aggregates, bags, recursion | SQL needs bags + aggregates |
| Constraints | none / keys and FKs / TGDs and EGDs | chase-based methods |
| Source capabilities | arbitrary access / binding patterns | web sources, APIs |

Two architectures in data integration: **global-as-view** (global relations
defined as views over sources; answering = view expansion/unfolding) and
**local-as-view** (sources defined as views over the global schema;
answering = rewriting using views). Query optimisation with MVs is the
closed-world, partial, equivalent-rewriting case.

## 2. Containment, the decision procedure underneath

Conjunctive query: `q(X) :- s1(X1), ..., sn(Xn)`; head variables are
*distinguished*, the rest *existential*; safe if every head variable occurs
in the body.

- `Q1 ⊑ Q2` iff for all databases D, `Q1(D) ⊆ Q2(D)`; equivalence is
  containment both ways.
- **Containment mapping** from Q2 to Q1: a variable mapping that is the
  identity on constants, maps every subgoal of Q2 onto some subgoal of Q1,
  and maps Q2's head to Q1's head.
- **Chandra-Merlin (1977)**: for CQs under set semantics, `Q1 ⊑ Q2` iff a
  containment mapping from Q2 to Q1 exists. Deciding it is NP-complete in
  the query size (subgraph-homomorphism), cheap in practice for small
  queries.
- With arithmetic comparisons the test needs case analysis over orderings
  of variables (Π2p-hard in general); with constraints, chase Q1 first:
  `Q1 ⊑_C Q2` iff `chase_C(Q1) ⊑ Q2` when the chase terminates.
- **Bag semantics** (SQL without DISTINCT): CQ bag-*equivalence* holds iff
  the queries are isomorphic (Chaudhuri and Vardi, PODS 1993); bag
  *containment* of CQs is not known to be decidable in general. Practical
  consequence: optimizers do not run a general containment test for SQL
  rewrites; they use restricted structural matching that guarantees each
  query row maps to exactly one view row (section 5).

A rewriting Q' is checked by **expansion**: replace each view atom by its
definition with fresh existential variables, then test containment or
equivalence against Q.

Small example (own schema):

```
Q(e, c)  :- Works(e, p), Proj(p, c), Mgr(e)
V1(e, p) :- Works(e, p), Mgr(e)
V2(e, c) :- Works(e, p), Proj(p, c)        -- p existential in V2
V3(p, c) :- Proj(p, c)

R1(e, c) :- V1(e, p), V3(p, c)             -- equivalent
R2(e, c) :- V2(e, c), V1(e, p2)            -- equivalent (map p2 -> p)
R3(e, c) :- V2(e, c2), V3(p, c), V1(e, p3) -- NOT contained: Proj(p,c)
                                              is disconnected from e
```

## 3. Characterisation and complexity (LMSS 1995 and follow-ups)

- A rewriting of Q using V exists iff the Boolean projection of Q is
  contained in the Boolean projection of V (for CQs with built-ins).
- For CQs and views without built-ins, a locally minimal complete rewriting
  needs no more view atoms than Q has subgoals, introduces no new variables,
  and uses no relations absent from Q. With functional dependencies the
  bound grows to p + d (d = sum of arities); with built-ins the rewriting can
  be exponentially larger.
- Existence of a rewriting: NP-complete for CQ query with built-ins and CQ
  views without; Π2p-complete when views have built-ins. Finding a rewriting
  with at most k literals (no built-ins anywhere) is NP-complete; with
  built-ins in Σ3p.
- Under open-world semantics, the maximally-contained rewriting (a union of
  CQs for CQ inputs) yields the *certain answers*; under closed-world
  semantics computing certain answers is harder (Abiteboul and Duschka,
  PODS 1998). Rewriting (producing a query) and answering (producing tuples)
  are distinct problems with different expressiveness (Calvanese, De
  Giacomo, Lenzerini, Vardi, ICDT 2005).

## 4. Rewriting algorithms

### 4.1 Bucket algorithm (Levy, Rajaraman, Ordille 1996)

```
for each non-comparison subgoal g of Q:
    bucket[g] = { V-head instantiated | V has a subgoal unifying with g,
                  every distinguished var of Q in g maps to a distinguished
                  var of V, and comparisons stay satisfiable }
for each element of bucket[g1] × ... × bucket[gk]:
    form conjunctive rewriting; keep it if (after adding comparisons)
    its expansion is contained in Q
answer = union of kept rewritings (then remove redundant ones)
```

Strength: prunes views irrelevant to a subgoal. Weakness: it considers each
subgoal in isolation, so buckets contain views that cannot participate
(R3 above), and the Cartesian product plus a containment test per candidate
dominates cost.

### 4.2 Inverse rules (Duschka and Genesereth 1997; Qian's query folding)

Invert each view definition into one rule per body subgoal, using a Skolem
function `f_{V,i}(head vars)` for each existential variable:

```
V2(e, c) :- Works(e, p), Proj(p, c)
  =>  Works(e, f(e, c)) :- V2(e, c)
      Proj(f(e, c), c)  :- V2(e, c)
```

The rewriting is Q plus all inverse rules (function terms can be eliminated
systematically). Built once per view set in polynomial time, independent of
the query, and works unchanged for recursive (Datalog) queries and for
binding-pattern restrictions with minor changes. Downsides for evaluation:
it re-derives base tuples from views (undoing the view's join work) and may
touch irrelevant views.

### 4.3 MiniCon (Pottinger and Halevy, VLDB 2000; VLDB J 2001)

Key observation: if a query variable x is mapped to an *existential*
variable of a view, the view's extension cannot join on x with anything
else, so **every query subgoal containing x must be covered by the same
view occurrence**.

```
Phase 1: for each query subgoal g, view V, view subgoal g' unifying with g:
    choose head homomorphism h on V (may equate head vars)
    build minimal MCD = (h, φ, G) where φ maps Vars(Q) -> Vars(h(V)) and
      (C1) every distinguished var of Q in the domain maps to a
           distinguished var of h(V)
      (C2) if φ(x) is existential in V, then every subgoal of Q
           containing x is in G and is mapped by φ into V
Phase 2: combine MCDs whose G sets are pairwise disjoint and cover all
    subgoals of Q; each combination yields one CQ rewriting.
Result: union of those CQs (maximally contained w.r.t. unions of CQs).
```

For the example: V2 on `Works(e,p)` maps p to an existential, so its MCD
must also cover `Proj(p,c)` -> G = {Works, Proj}; V1 yields MCDs {Works} and
{Mgr}; V3 yields {Proj}. Valid combinations: {V2:{W,P}, V1:{M}} and
{V1:{W}, V3:{P}, V1:{M}} -- exactly R2 and R1; R3 is never generated. No
containment test is needed in phase 2 for comparison-free queries. As of
the EDBS entry, MiniCon was the most efficient known algorithm for CQs
using CQ views; the shared-variable-bucket (SVB) algorithm of Mitra uses a
similar idea. MiniCount extends the approach to COUNT queries.

### 4.4 Equivalent and efficient rewritings

- **CoreCover** (Afrati, Li and Ullman, SIGMOD 2001) generates
  equivalent rewritings that are globally minimal in the number of view
  atoms, using "tuple-cores" of views, aiming at efficient plans rather than
  maximal answers.
- Afrati, Li and Mitra (PODS 2002) handle arithmetic comparisons.
- Chirkova and Li (PODS 2003) study choosing views of minimal size that
  still answer a workload.

### 4.5 Chase and backchase (Deutsch, Popa, Tannen)

Under constraints C (TGDs and EGDs, including view definitions written as
constraints): **chase** Q with C until no step applies, yielding the
*universal plan* U -- a query over base relations and views containing every
way to answer Q. Completeness rests on the fact that each C-equivalent
minimal rewriting appears (up to variable renaming) inside U. **Backchase**: enumerate subqueries of U,
keep those equivalent to Q (check by chasing the subquery and finding a
containment mapping from Q into the result). Sound and complete when C is
weakly acyclic (the chase terminates). Exponential in |U| but captures
indexes, semantic constraints and views uniformly.

## 5. View matching in production optimizers

### 5.1 SPJG matching (Goldstein and Larson, SIGMOD 2001; SQL Server)

> **Beyond EDBS** (paper not in this cluster, cited here because it is the
> reference industrial algorithm).

The matcher is an optimizer rule that, for an SPJG subexpression E, finds
views V such that E can be computed from V by selections, a projection and
optionally a re-aggregation. Conditions, all decidable cheaply:

1. **Tables**: V references every table of E. Extra tables in V are allowed
   only if each joins to the rest through equijoins on non-null foreign keys
   to unique keys (cardinality-preserving), so they neither drop nor
   duplicate E's rows.
2. **Equijoin subsumption**: build column equivalence classes from equality
   predicates in E and in V; every V class must be a subset of some E class
   (V joins no more than E). Compensation: equalities for E classes that V
   splits.
3. **Range subsumption**: per equivalence class, V's range must contain E's
   range; compensation: E's tighter bounds.
4. **Residual subsumption**: V's residual (non-range, non-equijoin)
   predicates must all appear in E (shallow, normalised-expression
   matching); compensation: E's remaining residuals.
5. **Availability**: every compensating predicate and every E output
   expression must be computable from V's output columns (using equivalence
   classes to substitute columns).
6. **Grouping**: if V aggregates, E must group by a set functionally
   determined by V's grouping columns; roll up SUM by SUM, COUNT by SUM of
   counts, AVG by SUM(sum)/SUM(count); MIN/MAX roll up by MIN/MAX. If E's
   grouping equals V's, no re-aggregation is needed.

Scalability: a **filter tree** indexes the view definitions by source table
set, output columns, grouping columns, range-constrained columns and
residual predicate text, so each matching call examines only candidates
that pass all cheap necessary conditions. The rule emits an alternative
(view scan + compensation) into the memo; the cost model decides.

### 5.2 Other systems

> **Beyond EDBS:**
> - **Oracle query rewrite**: text match (full and partial), then general
>   rewrite: join-back to base tables for missing columns via keys,
>   aggregate roll-up, roll-up through hierarchies declared with
>   `CREATE DIMENSION`, filtered-data checks, and partition-change-tracking
>   rewrite that uses the fresh partitions of a partly stale MV.
>   `QUERY_REWRITE_INTEGRITY` = ENFORCED (only enforced constraints, only
>   fresh MVs) / TRUSTED (also RELY constraints and declared dimensions) /
>   STALE_TOLERATED (also stale MVs) makes the soundness/staleness contract
>   explicit.
> - **DB2 materialized query tables**: Zaharioudakis, Cochrane, Lapis,
>   Pirahesh and Urata (SIGMOD 2000) match bottom-up over QGM boxes and
>   handle nested subqueries and complex grouping.
> - **Teradata join indexes** (single-table, multi-table, aggregate,
>   sparse with a WHERE clause) are maintained by the system within the
>   modifying transaction and are never referenced by queries directly:
>   they are used only when the optimizer substitutes them, including
>   partial coverage with a join back to the base table by row identifier.

Earlier: Larson and Yang (VLDB 1985) computed queries from derived
relations; Chaudhuri, Krishnamurthy, Potamianos and Shim (ICDE 1995)
integrated view usage into System-R-style join enumeration by treating a
usable view as an alternative access path for the set of tables it covers.
Outer-join view matching: Larson and Zhou (VLDB 2005).

### 5.3 Engineering rules for a matcher

- Match on the **normalised, bound** representation (resolved column IDs,
  canonical predicate forms, constant folding), never on SQL text.
- Equality semantics: `a = b` does not match NULLs; a view with `a = b`
  cannot answer a query that needs rows where both are NULL. Collations and
  implicit casts must be identical for predicate subsumption.
- Constraint use (extra tables, join-back, functional dependencies for
  grouping) only from enforced constraints, unless a trusted mode is
  explicitly enabled.
- Freshness gate: deferred MVs carry a watermark; allow substitution only
  if the watermark is at or after the query snapshot (or within declared
  tolerance).
- Determinism gate: no volatile functions, session settings, or
  security-context-dependent predicates (row-level security) in V unless
  identical in E.
- Exclude the MV under maintenance from rewriting its own delta queries.
- Assert plan shape in tests so a matcher regression is not silent.

## 6. View selection

Choose the set of views (and indexes) to materialise, maximising query
benefit subject to space and/or maintenance-cost budgets.

- **Harinarayan, Rajaraman and Ullman (SIGMOD 1996)**: cube lattice;
  greedy picks the view with the largest benefit (reduction in total query
  cost) per step; the greedy result achieves at least (1 − 1/e) ≈ 63% of the
  optimal benefit for a fixed number of views. Benefit-per-unit-space
  variant for space budgets.
- **Gupta (ICDT 1997)** generalises to AND/OR view graphs (multiple plans per
  view); Gupta, Harinarayan, Rajaraman and Ullman (ICDE 1997) add index
  selection for OLAP.
- **Maintenance-cost constraint** (Gupta and Mumick, ICDT 1999): the benefit
  function is no longer monotone (adding a view can lower others'
  maintenance cost), so simple greedy loses its guarantee; they give
  heuristics (an inverted-tree greedy and an A*-style search).
- **Theodoratos and Sellis (VLDB 1997)**: warehouse configuration as state
  search over view sets that can answer all queries, combining query and
  maintenance cost.
- **Dynamic**: DynaMat (Kotidis and Roussopoulos, SIGMOD 1999) materialises
  query-result fragments on the fly and evicts by a benefit metric; Web
  Views apply the same trade-off to page fragments outside the DBMS.

> **Beyond EDBS:** Agrawal, Chaudhuri and Narasayya (VLDB 2000) select
> indexes and materialised views jointly from a workload by pruning
> candidates syntactically, merging similar views, and evaluating
> configurations with the optimizer's what-if costing -- the basis of SQL
> Server's tuning advisor. Mistry, Roy, Sudarshan and Ramamritham (SIGMOD
> 2001) use multi-query optimisation to share work among maintenance plans
> and to pick extra views that make maintenance cheaper.

Engineering point: view selection is only as good as the matcher -- the
advisor must call the same matching code the optimizer uses, or it will
recommend views the optimizer never uses.

## 7. View adaptation (definition change)

When an MV definition changes slightly, compute the new MV from the old
one instead of from scratch (Gupta, Mumick and Ross, SIGMOD 1995; Gupta,
Mumick, Rao and Ross, Inf. Syst. 2001). It is related to answering the new
definition using the old view, but also allows **in-place** changes.

| Change | Adaptation |
|---|---|
| Drop output column | projection in place (needs counts if it creates duplicates under DISTINCT) |
| Add output column | join back to base via a key kept in the view; else recompute |
| Strengthen WHERE (add conjunct) | delete non-qualifying rows in place |
| Weaken WHERE (drop conjunct p) | insert rows from base satisfying `new ∧ ¬old` |
| Add a join (FROM) | join the view with the new relation (key-preserving -> in place) |
| Drop a join | needs base data unless the join was cardinality-preserving |
| Coarsen GROUP BY | roll up if aggregates are distributive/algebraic components |
| Refine GROUP BY | recompute (information lost) |
| Change HAVING | re-filter if all groups are stored (see aggregates reference) |
| UNION / EXCEPT branches | add or subtract branch results; counts make EXCEPT adaptable |

Several changes can sometimes be applied in a single pass. Extensions to
distributed and fragment-based settings exist (Mohania and Dong 1996;
Bellahsene 2004).

## 8. Answering ranking queries using ranking views

For a new linear (monotone) ranking function g, reuse materialised ranked
lists: Onion (Chang et al., SIGMOD 2000) precomputes nested convex hulls so
the top-i answers for any linear function lie in the first i layers; PREFER
(Hristidis, Koudas and Papakonstantinou, SIGMOD 2001) picks the closest
materialised ranking view and reads a prefix down to a *watermark* score
that guarantees the top results under g have been seen, with prefix-only
storage in a follow-up (VLDB J 2004); Das, Gunopulos, Koudas and Tsirogiannis
(VLDB 2006) combine several top-m views via linear programming.

## Key papers

Levy, Mendelzon, Sagiv and Srivastava, PODS 1995; Halevy, VLDB J 2001
(survey); Chandra and Merlin, STOC 1977; Levy, Rajaraman and Ordille, VLDB
1996; Duschka and Genesereth, PODS 1997; Qian, ICDE 1996; Pottinger and
Halevy, VLDB J 2001; Deutsch, Popa and Tannen, SIGMOD Record 2006; Afrati,
Li and Ullman, SIGMOD 2001; Abiteboul and Duschka, PODS 1998; Lenzerini,
PODS 2002; Larson and Yang, VLDB 1985; Chaudhuri et al., ICDE 1995;
Theodoratos and Sellis, VLDB 1997; Gupta and Mumick, ICDT 1999; Kotidis and
Roussopoulos, SIGMOD 1999; Gupta, Mumick and Ross, SIGMOD 1995.

Sources: EDBS "Answering Queries Using Views" (p.114), "Rewriting Queries
Using Views" (p.3241), "View Adaptation" (p.4443), "View Maintenance"
(p.4445, view selection remarks), "Web Views" (p.4682), "Ranking Views"
(p.3092), "View Definition" (p.4444).
