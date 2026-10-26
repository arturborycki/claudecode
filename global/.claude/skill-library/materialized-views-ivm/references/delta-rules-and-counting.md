# Delta rules, the counting algorithm, and self-maintenance

Scope: deriving incremental maintenance expressions for non-recursive views
(select, project, join, union, intersection, difference, DISTINCT), the
counting algorithm, filtering irrelevant updates, self-maintainability and
auxiliary views, and the modern "higher-order" generalisation. Aggregates,
outer joins and recursion are in `aggregates-outerjoins-recursion.md`.

## 1. Notation and the three semantics

A change transaction t on base relations R1..Rm is given as, per relation,
a deletion set `R-` and an insertion set `R+`. Updates are modelled as
delete-old + insert-new (but see section 7: keeping the pair is useful for
aggregates). The change is **minimal** when `R- ⊆ R_old` and
`R+ ∩ R_old = ∅`. For a view Q we want `Q-` and `Q+` such that

```
Q(D_new) = (Q(D_old) - Q-) ∪ Q+
```

and, ideally, `Q- ⊆ Q(D_old)` and `Q+ ∩ Q(D_old) = ∅` (minimal view delta;
otherwise the apply step does wasted or wrong work).

Three algebraic settings matter, and the choice drives the whole design:

| Setting | Relation is | Delta is | Linear operators | Non-linear (need aux state) |
|---|---|---|---|---|
| Sets | subset of tuples | pair (Q-, Q+) | σ | π (dedup), ∪, −, ∩ need lookups in old/new state |
| Bags (SQL) | tuple -> count ≥ 0 | pair of bags; monus for deletion | σ, π (no dedup), ⊎, × | δ (DISTINCT), monus/EXCEPT ALL, min, max |
| Z-relations | tuple -> integer | single signed bag dQ | σ, π, ⊎, ×, ⋈ (bilinear) | δ, EXCEPT, MIN/MAX, holistic aggregates |

Engines should implement the **Z-relation** form internally: a delta is a
batch of `(row, weight)` with weight in i64, insert = +1, delete = −1. Union
is weight addition, consolidation sums weights per row and drops zeros. The
set and bag forms are special cases recovered by DISTINCT (weight > 0 -> 1)
and by forbidding negative final weights.

## 2. Operator-by-operator rules (set semantics)

These are the rules in the Qian-Wiederhold tradition, in the corrected
minimal form of Griffin, Libkin and Trickey (the 1991 original could produce
non-minimal deltas). S, T are sub-expressions; `S_old`, `S_new` their old and
new values (which must themselves be available -- materialised or
recomputable -- hence intermediate results become auxiliary relations).

| Q | Q- (to delete) | Q+ (to insert) |
|---|---|---|
| base R | R- | R+ |
| σp(S) | σp(S-) | σp(S+) |
| πA(S) | πA(S-) − πA(S_new) | πA(S+) − πA(S_old) |
| S × T, S ⋈ T | (S- ⋈ T_old) ∪ (S_old ⋈ T-) | (S+ ⋈ T_new) ∪ (S_new ⋈ T+) |
| S ∪ T | (S- − T_new) ∪ (T- − S_new) | (S+ − T_old) ∪ (T+ − S_old) |
| S ∩ T | (S- ∩ T_old) ∪ (S_old ∩ T-) | (S+ ∩ T_new) ∪ (S_new ∩ T+) |
| S − T | (S- − T_old) ∪ (S_old ∩ T+) | (S+ − T_new) ∪ ((S_old − S-) ∩ T-) |

Reading the difference row: a tuple leaves `S − T` because it left S while
it was in the answer, or because it entered T while it was in S. A tuple
joins `S − T` because it entered S and is not in T_new, or because it stayed
in S and left T. Note that projection under set semantics needs the *new*
state of S to know whether another witness survives -- the motivation for
counting (section 4).

Engineering consequence: a set-semantics delta generator needs access to
both `X_old` and `X_new` for many sub-expressions. If only the post-state is
stored (the usual case after base tables are updated), `X_old` must be
reconstructed as `(X_new − X+) ∪ X-` -- a "hypothetical relation" view of the
pre-state. Every rule must be audited for which state it reads.

## 3. Bags and Z-relations: telescoping join deltas

For bags (Griffin and Libkin 1995) and Z-relations, write `R' = R + dR`.
Joins distribute over `+`:

```
R' ⋈ S' = (R + dR) ⋈ (S + dS)
        = R⋈S + dR⋈S + R⋈dS + dR⋈dS
```

so the view delta has three equivalent forms:

```
(pre-state)   dV = dR ⋈ S  + R  ⋈ dS + dR ⋈ dS
(mixed A)     dV = dR ⋈ S  + R' ⋈ dS
(mixed B)     dV = dR ⋈ S' + R  ⋈ dS
(post-state)  dV = dR ⋈ S' + R' ⋈ dS − dR ⋈ dS
```

For n inputs, the telescoping form needs one term per changed input and no
correction terms:

```
d(R1 ⋈ ... ⋈ Rn) = Σ_i  R1' ⋈ ... ⋈ R(i-1)' ⋈ dRi ⋈ R(i+1) ⋈ ... ⋈ Rn
```

Inputs before position i are read in the post-state, inputs after it in the
pre-state. The order is arbitrary but must be fixed for the whole
computation. **Invariant: each term's state vector must match its position
in the chosen order.** Getting this wrong is the deferred-maintenance "state
bug" (Colby et al. 1996): e.g. computing `dR ⋈ S + R ⋈ dS` when both R and S
already include their changes double-counts `dR ⋈ dS`.

Self-joins: a view `R ⋈ R` with a change to R is an n=2 instance with
`dR1 = dR2 = dR`; the telescoping form gives `dR ⋈ R + R' ⋈ dR` -- the two
references must be treated as distinct inputs even though they share
storage. Engines that key delta terms by table name instead of by
reference position produce wrong answers on self-joins.

Selection and bag projection commute with deltas: `dσp(S) = σp(dS)`,
`dπA(S) = πA(dS)` (weights summed). Union-all adds deltas. So for any SPJ
view without DISTINCT the delta query is the view query with one input
replaced by its delta per term, which can be planned and optimised like any
query (choose join order starting from the small delta; probe indexes on
the other inputs).

Cost sketch for an SPJ view with k inputs and a single changed input R:
`cost_inc ≈ |dR| · Π (probe fan-out into the other inputs)` with index
probes, versus `cost_full ≈ cost(Q)`. Incremental wins when |dR| is a small
fraction of R *and* the other inputs have indexes on the join keys used from
the delta side. Without such indexes each delta term degenerates to a scan
of the other inputs, and full recompute can be cheaper even for small
deltas. The refresh planner should cost both using the delta cardinality,
which is known exactly at refresh time.

## 4. The counting algorithm

Gupta, Mumick and Subrahmanian (SIGMOD 1993) maintain non-recursive views
(including those defined with DISTINCT, union and negation/difference) by
storing with every view tuple the number of distinct derivations.

```
store:   MV(t, cnt)                -- cnt ≥ 1 for every stored t
derive:  evaluate the view in bag form over (row, weight) deltas,
         i.e. dCount(t) = Σ weights of derivations of t gained − lost
apply:   for each (t, d) in consolidated dCount:
             old = MV.cnt(t) or 0;  new = old + d
             assert new >= 0                        -- negative = bug
             if old == 0 and new > 0: insert (t, new)   -- emit +t downstream
             elif new == 0:           delete t           -- emit −t downstream
             else:                    update cnt
```

Only the 0 <-> positive transitions change the *set* view; downstream views
see set deltas, which keeps the chain minimal. For a DISTINCT view on top of
a join, cnt is exactly COUNT(*) over the pre-distinct bag.

Difference `S − T` (set) is maintained by storing both `cnt_S(t)` and
`cnt_T(t)` for candidate tuples; t is in the view iff `cnt_S > 0 ∧ cnt_T = 0`.
This auxiliary state is O(|S| + |T ∩ π S|), not O(|view|). Intersection is
symmetric (`cnt_S > 0 ∧ cnt_T > 0`).

Worked example. `V = DISTINCT π_city (Customer ⋈ Order)` with counts:

```
MV: (Paris, 3) (Oslo, 1)
batch: delete Order o7 (customer c2, Oslo); insert Order o9 (c5, Lima)
dCount: (Oslo, −1) (Lima, +1)
apply : Oslo 1 -> 0  => delete Oslo;  Lima 0 -> 1 => insert Lima
```

Without counts, deleting o7 would require a probe "does any other Oslo
customer still have an order?" against the post-state -- the set-semantic
projection rule.

Limits: counting is complete for non-recursive views. For recursive views,
derivation counts can be infinite on cyclic data and exponential on acyclic
data, so DRed is used instead (see the recursion reference).

## 5. Filtering irrelevant updates

Blakeley, Larson and Tompa (SIGMOD 1986) observed that many base changes
provably cannot affect a view. For an SPJ view with condition C, an
inserted or deleted tuple r of R is **irrelevant** if substituting r's values
into C leaves an unsatisfiable condition (over the remaining variables). For
conjunctions of comparisons this is a satisfiability test on a small
constraint graph, polynomial for the common cases.

Engine mapping:

- Push the view's local predicates on R into the delta scan of R: dR rows
  failing them are dropped before any join (the trivial, always-on case).
- For join conditions with constants after substitution (e.g. `R.a = S.b ∧
  S.b > 10` with `r.a = 5`), the satisfiability test removes the row too.
- At the trigger/log level, a cheap column-mask check rejects UPDATEs that
  touch no column referenced by any dependent MV (Buneman-Clemons style
  alerters were the precursor).
- Declared constraints create more irrelevance: with a foreign key
  `R.s -> S.key` enforced and S.key unique, *inserting* into S cannot change
  `R ⋈ S` (no existing R row can reference a new key), and deletion from S
  is blocked or cascades into R deltas. Oracle and SQL Server style
  maintainers exploit this to skip whole delta terms.

## 6. Self-maintenance and auxiliary views

A view is **self-maintainable** (SM) for a class of updates if its new
state is determined by its old state, the view definition and the update
alone -- no base relation access. Two notions (Gupta and Mumick 1995):

- **Compile-time SM**: holds for all database states and all updates of the
  given kind (e.g. "all insertions into R"). Decided from the definition.
- **Run-time SM**: holds for this particular update given the current view
  contents (and possibly a specified subset of base relations). More
  aggressive: may succeed where compile-time fails, at the cost of a check
  per batch.

Typical compile-time results (conjunctive/SPJ views, no self-joins):

| View | Inserts into R | Deletes from R | Notes |
|---|---|---|---|
| σ(R) | SM | SM if view keeps R's key (or a count) | deletion needs to identify the row |
| π(R) with dedup | SM | not SM without counts | another witness may survive |
| R ⋈ S | not SM (need S) | SM if R's key is in the view | delete all view rows with that key |
| R ⋈ S with FK R->S, view keeps S columns needed | SM for inserts into S (irrelevant) | -- | constraints convert lookups into no-ops |
| aggregate with COUNT(*) | SM for SUM/COUNT/MIN/MAX | SM for SUM/COUNT only | MIN/MAX deletions need base or aux |

Results in the literature:

- Tompa and Blakeley (1988) and Gupta and Blakeley (1995): conditions for
  maintaining SPJ views without (or with partial) base access, single
  relation insertions or deletions.
- Huyn (1996): for conjunctive views and insertions, the run-time SM test is
  a simple query over the view itself, generated from the definition via a
  "minimum z-partition" of the subgoals; the maintenance is then an update
  query over the view. Huyn (VLDB 1997) extends to multiple views, mixed
  insertions and deletions, and generalised SM where some base relations are
  available, and shows that SM reduces to query containment.

**Auxiliary views.** When a view is not SM, store extra materialised views
that make the *set* {view + auxiliaries} self-maintainable.

> **Beyond EDBS:** Quass, Gupta, Mumick and Widom (PDIS 1996, "Making views
> self-maintainable for data warehousing") give a minimal set of auxiliary
> views for SPJ views using keys and referential integrity: per base
> relation, store only its tuples that can still contribute (local
> selections applied, semijoin-reduced against relations it references via
> FKs) and only the columns the view or the joins need. With FK chains in a
> star schema, the fact relation often needs no auxiliary view at all
> because dimension auxiliaries suffice.

Design guidance: auxiliary views trade storage and their own maintenance
for independence from base access -- decisive when bases are remote,
autonomous, or locked. Inside a single engine the bases are local, so
auxiliaries are mainly used for non-linear operators (per-group multisets
for MIN/MAX, operand counts for EXCEPT) rather than for joins.

## 7. Updates, keys and the delete+insert model

Modelling UPDATE as delete-old + insert-new is complete but wasteful:

- An update that changes only non-referenced columns should produce no
  delta at all (column-mask filtering).
- An update that changes a measure but not the group key of an aggregate MV
  can be applied as a single in-place adjustment (`+new − old`) instead of
  two group probes.
- An update that changes a *group key* or *join key* must be split: it moves
  contribution from one group/join partner to another.

Keep `(old_row, new_row)` pairs through the delta pipeline as long as the
operators can use them; split into (−old, +new) only at operators where the
key changes.

## 8. Incremental computation beyond views

The same machinery serves integrity-constraint checking (a constraint is a
view that must stay empty), active-database condition monitoring (a rule
condition is a view whose insertions fire the rule), and trigger
optimisation. Incremental evaluation can also *increase expressiveness*:
transitive closure is not expressible in relational algebra, yet for some
graph classes it can be maintained by relational-algebra update queries
(see the recursion reference, "Dyn-FO").

> **Beyond EDBS: higher-order IVM.** Koch (PODS 2010, "Incremental query
> evaluation in a ring of databases") treats generalised multiset relations
> as a ring and shows that for queries built from joins, unions and
> aggregation (polynomials in the inputs), the delta of a degree-k query is
> a degree-(k−1) query; repeating, the k-th delta is independent of the
> database. DBToaster (Ahmad, Kennedy, Koch, Nikolic, VLDB 2012 and VLDB
> Journal 2014) materialises the delta queries themselves as views,
> recursively, so a single-tuple update costs a few map lookups and
> additions rather than a join. The trade-off is many auxiliary maps and
> high memory; it is best for low-latency, single-tuple update streams
> with fixed queries.
>
> **Beyond EDBS: DBSP.** Budiu, Chajed, McSherry, Ryzhyk and Tannen (VLDB 2023)
> formalise streaming IVM over Z-sets: a query Q is incrementalised as
> `D ∘ Q ∘ I` (integrate the change stream, apply Q, differentiate), with a
> chain rule so each operator is incrementalised independently; linear
> operators are their own incremental version, joins use the bilinear
> rule of section 3, and DISTINCT/aggregates use integrated state. It is a
> clean blueprint for an operator-at-a-time IVM compiler, and it covers
> recursion via nested time. Feldera is the commercial implementation.

## 9. Pitfalls checklist

- Delta terms keyed by table instead of by reference position (self-joins).
- Pre-state formulas evaluated against post-state tables (state bug).
- Set-semantic rules applied to SQL bag views (or vice versa): wrong
  multiplicities after DISTINCT is pushed or pulled during optimisation of
  the *delta* query.
- Consolidation skipped: the same row arrives as +1 and −1 in one batch and
  the apply step deletes a row it never inserted (or hits a unique-key
  violation).
- Counting views whose count column overflows i32 under heavy fan-out joins.
- Irrelevance filtering that trusts constraints declared `NOT ENFORCED`.
- Optimiser rewrites the delta query using the MV being maintained
  (circular rewrite) -- disable view matching for maintenance plans of that
  MV.

## Key papers

Qian and Wiederhold, IEEE TKDE 1991; Griffin, Libkin and Trickey, IEEE TKDE
1997; Griffin and Libkin, SIGMOD 1995 (bags); Gupta, Mumick and
Subrahmanian, SIGMOD 1993 (counting, DRed); Blakeley, Larson and Tompa,
SIGMOD 1986; Colby, Griffin, Libkin, Mumick and Trickey, SIGMOD 1996
(deferred, state bug); Gupta and Mumick, IEEE Data Eng. Bull. 1995
(problem taxonomy) and the 1999 MIT Press book; Tompa and Blakeley, Inf.
Syst. 1988; Gupta and Blakeley, Inf. Syst. 1995; Huyn, VLDB 1997.

Sources: EDBS "Incremental Computation of Queries" (p.1830), "View
Maintenance" (p.4445), "View Maintenance Aspects" (p.4448), "Self-Maintenance
of Views" (p.3372), "Incremental Maintenance of Views with Aggregates"
(p.1838), "Maintenance of Recursive Views" (p.2170).
