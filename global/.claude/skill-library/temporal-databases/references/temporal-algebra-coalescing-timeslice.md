# Temporal algebra, timeslice and coalescing

The logical operator set a temporal engine plans with, the two "slice"
operators that turn temporal relations into snapshots, and coalescing — the
operator that is to temporal data what duplicate elimination is to bags, and
the most common source of silently wrong temporal answers.

Notation: `r(A, T)` with explicit attributes `A` and half-open valid-time
period `T = [Ts, Te)`. `τ_t` is valid timeslice at instant `t`; `ρ_t` is
transaction timeslice (rollback).

---

## 1. Desiderata and evaluation styles

A temporal algebra should be **closed** (temporal in, temporal out), a
**consistent extension** of relational algebra, and **reduce** to relational
algebra when only current data is involved. McKenzie & Snodgrass (ACM CSUR
1991) catalogued desirable criteria for temporal algebras and showed that
some are mutually conflicting; every design picks a subset.

Two evaluation styles; an engine typically needs both (they correspond to
sequenced vs nonsequenced semantics):

| Style | Definition | Example |
|---|---|---|
| Snapshot (point, sequenced) | apply the classical operator to each snapshot | `τ_t(r ∪ᵗ s) = τ_t(r) ∪ τ_t(s)` for all `t` |
| Traditional (nonsequenced) | treat timestamps as attributes; operators look at whole stored tuples | `σ_{Te − Ts ≥ 90d}(r)` |

Snapshot definitions of the five basic operators:

```
(r ∪ᵗ s)_t = r_t ∪ s_t        (r −ᵗ s)_t = r_t − s_t
(πᵗ_X r)_t = π_X(r_t)         (σᵗ_F r)_t = σ_F(r_t)
(r ×ᵗ s)_t = r_t × s_t
```

`F` in σ may mix ordinary predicates and period predicates (Allen
relations), in which case the operator is only *extended* snapshot reducible
(see `time-models-and-semantics.md` §6.2).

Value equivalence: two tuples are value equivalent if they agree on all
explicit attributes (timestamps may differ). Under traditional evaluation a
temporal union may merge value-equivalent tuples whose periods overlap; a
temporal difference removes from each `r` tuple the portion shared with
value-equivalent `s` tuples:
`{(a1, [2/07, 11/07))} −ᵗ {(a1, [6/07, 8/07))} = {(a1,[2/07,6/07)), (a1,[8/07,11/07))}`.
Allowing value-equivalent tuples makes queries harder to specify but cheaper
to evaluate; eliminating them is costly (it is coalescing).

### Tuple- vs attribute-timestamped algebras

- Tuple timestamping (1NF): relation gets `From, To` (or a period/element
  column). Points inside periods are reached via snapshot evaluation, via
  explicit endpoint predicates, or via **expansion/contraction** operators
  (Lorentzos & Johnson: expand a period into its points; contract consecutive
  points into a period) — the algebraic ancestors of IXSQL's unfold/fold and
  Teradata's `EXPAND ON`.
- Attribute timestamping (N1NF, *temporally grouped*): an object's history is
  one tuple of temporal atoms `<period, value>`; needs nest/unnest and
  operators that form/break atoms. Temporally grouped algebras are more
  expressive and more complex than ungrouped ones (Clifford, Croker,
  Tuzhilin). Gadia's homogeneous model adds the temporal expression `[[e]]`
  (the time over which `e` is defined, a temporal element) usable inside
  algebra expressions; e.g., for a tuple whose Position is
  `Assistant [4,9), Associate [9,14), Full [14,18)`,
  `[[Position <> Associate]] = [4,9) ∪ [14,18)`.

Granularity: operators are defined independently of granularity; if operands
use different granularities, insert an explicit conversion (see
`time-models-and-semantics.md` §2) — never compare raw chronon counts of
different scales.

---

## 2. Timeslice and rollback

- **Valid timeslice** `τ_t(r)`: tuples of `r` whose valid time contains `t`,
  timestamps removed (or reduced to `t`). Parameter may be an instant, a
  period, or a temporal element; with a period/element parameter it returns a
  temporal relation restricted to that time.
- **Transaction timeslice / rollback** `ρ_t(r)`: the state recorded as current
  at transaction time `t` ("as of" query). "Rollback operator" and "state
  query" are older names; they understate generality because the parameter
  need not be an instant in the past.
- Duality: a valid-time algebra and a transaction-time algebra have the same
  operator set, each with its own slice operator.
- Slice is *redundant* (expressible with selection on endpoints) but central:
  it expresses natural-language "when", it is the anchor for current
  semantics, and it is what snapshot reducibility is stated with. An
  attribute-level slice `τ_{B,C}(Q)` clips attribute `B`'s timestamps to those
  of attribute `C` (synchronising attributes inside a grouped tuple).
- Result type choices: given an instant, timeslice of a valid-time relation
  may return a snapshot relation; timeslice of a bitemporal relation in one
  dimension returns a relation temporal in the other. Some operators always
  return the argument's type. Decide once and document it in the plan
  operator's schema derivation.

Bitemporal queries: applying `ρ_t` first and then valid-time operators is the
common pattern ("what did we believe at `t` about history?"); applying
bitemporal operators to the whole relation without a rollback is also
legitimate (audit queries over belief changes).

Implementation of `τ_t`: `σ_{Ts ≤ t < Te}`; for system time `ρ_t` over a
version store, see `transaction-time-implementation.md` (find the version with
largest start ≤ `t`). Both are the cheapest temporal operators and should be
pushed down like any selection.

> **Beyond EDBS:** Oracle exposes transaction timeslice as Flashback Query
> (`AS OF TIMESTAMP` / `AS OF SCN`) and key-transaction-time-range queries as
> Flashback Version Query (`VERSIONS BETWEEN`). SQL:2011 `FOR SYSTEM_TIME AS
> OF` is the standard spelling of `ρ_t`.

---

## 3. Temporal projection

Temporal projection pairs computed facts with times, usually derived from
the times of the contributing facts. In most languages it is implicit
(intersection of contributing timestamps, as in a temporal join); TSQL2 makes
it explicit with `VALID` / `VALID INTERSECT` clauses on the select list
("temporal assignment" maps time values to attribute values). Design rule
from TSQL2: allow flexible temporal projection but make non-default
projections syntactically visible.

Projection hazards:

- Projecting out explicit attributes creates **value-equivalent** tuples with
  overlapping/adjacent periods (temporal analogue of duplicates). A
  duplicate-preserving projection of a coalesced relation is generally not
  coalesced.
- Projecting out the timestamp turns a temporal relation into a set of facts
  "ever true" — under implicit time this must be an explicit conversion, or
  the result is not a valid temporal relation (Sarda's observation).
- "Stamp projection" (project only on time: "when was at least one employee
  paid") yields a relation with no explicit attributes; decide whether your
  algebra allows it (it is just the coalesced union of all periods).

---

## 4. Temporal coalescing

### 4.1 Definition

Coalescing is a unary operator that merges value-equivalent tuples whose
periods overlap or meet into one tuple with the maximal covering period.
Result: for each value class, a set of pairwise disjoint, **non-adjacent**,
maximal periods.

```
coal(r) = { (a, P) | P is a maximal period such that every point of P is
            covered by some tuple of r with value a }
```

Equivalently: unfold to points, deduplicate, fold to maximal periods.
Under temporal elements, coalescing is the union of all elements of a value
class (BCDM forbids value-equivalent tuples, so its relations are always
coalesced).

Example: Bonus1 = {(Ron, 2K, [Jan81, May81)), (Ron, 2K, [May81, Oct81)),
(Pam, 3K, [Apr81, Jun81))} coalesces to {(Ron, 2K, [Jan81, Oct81)), (Pam,
3K, [Apr81, Jun81))}.

### 4.2 Why it matters for correctness

Coalescing never changes snapshots, but it changes the answer of any
operator that observes the representation:

| Operator class | Coalescing-sensitive? | Example |
|---|---|---|
| explicit-attribute selection, timeslice | no | `σ_{dept='Ship'}` |
| duration / length predicates | **yes** | "tuples spanning ≥ 3 months"; "2-day rentals" |
| nonsequenced COUNT / SUM over stored tuples | **yes** | number of bonuses paid |
| endpoint queries ("when did X start") | **yes** | first start of each maximal period |
| GAPS / "precedes" between facts | **yes** | spurious gaps between adjacent uncoalesced tuples |
| sequenced aggregates | no (pointwise), but output periods depend on lineage choice | |

Two tuples for Alex at salary 150 over `[300,500)` and `[800,1000)`, plus a
new insertion `(Alex,150,[400,800))`, give three "start of salary 150"
answers (300, 400, 800) instead of two (300, 800) unless coalesced.

And conversely, coalescing is **wrong** when periods carry meaning (strong
period model, telic facts): Ron's two adjacent 2K bonuses are two bonuses;
two back-to-back phone calls are two calls. Hence:

- Sequenced semantics defaults to *interval preservation* (no implicit
  coalescing); coalescing is an explicit operator, like DISTINCT.
- Point-based models (TSQL2, BCDM) require coalesced relations and cannot
  represent the distinction at all.
- SQL:2011 has no coalescing operator (a frequently criticised omission).

Where coalescing must be inserted for correctness: on **every intermediate**
whose representation is later observed (after projection or union, before
duration predicates, before endpoint-sensitive comparisons). Coalescing the
stored base relation is not sufficient (GAPS example in
`time-models-and-semantics.md` §4).

### 4.3 Which operators preserve coalescedness

Useful for an optimizer that tracks a `coalesced` physical property (like
`sorted` or `distinct`). For coalesced inputs, with result keeping all
explicit attributes of the inputs:

| Operator | Output coalesced? | Reason |
|---|---|---|
| σ on explicit attributes | yes | keeps or drops whole value classes |
| σ on timestamps (duration etc.) | yes (subset of a coalesced set) | but the *answer* differs vs uncoalesced input |
| timeslice with period parameter | yes | intersection with one period keeps pieces non-adjacent |
| π dropping explicit attributes | **no** | new value classes merge |
| ∪ᵗ | **no** | pieces from `r` and `s` may meet |
| ⋈ᵗ / ×ᵗ (all attributes kept) | yes | value-equivalent results come from value-equivalent, non-adjacent inputs; intersections of non-adjacent periods are non-adjacent |
| −ᵗ | yes | pieces of one `r` tuple are separated by `s` coverage; pieces of different `r` tuples are already non-adjacent |
| sequenced γ (ITA) with lineage | **no** by design | equal aggregate values over adjacent constant intervals stay separate |

Rewrite rules (all valid up to identity, not just snapshot equivalence):

```
coal(σ_P(r))         = σ_P(coal(r))              P on explicit attributes only
coal(π_X(coal(r)))   = coal(π_X(r))              inner coalesce redundant
coal(r ∪ᵗ s)         = coal(coal(r) ∪ᵗ coal(s))
coal(coal(r))        = coal(r)                   idempotent
coal(r) = r          if property(r).coalesced
```

Not valid: pushing `coal` below a duration predicate, below a nonsequenced
aggregate, or below a projection. Böhlen, Snodgrass & Soo (VLDB 1996) study
coalescing placement and optimization in depth.

### 4.4 Algorithms

**(a) Sort + single scan (the one to implement).** Sort (or hash-partition
then sort) by `(A, Ts)`; keep one current tuple:

```
cur = first
for t in rest (ordered by A, Ts):
    if t.A == cur.A and t.Ts <= cur.Te:      # overlaps or meets (half-open)
        cur.Te = max(cur.Te, t.Te)
    else:
        emit cur; cur = t
emit cur
```

`O(n log n)` for the sort, `O(n)` scan, `O(1)` state; streams; parallelises
by hash-partitioning on `A`. If input is already ordered by `(A, Ts)` (index
scan, sorted run from a prior operator), it is a pipelined `O(n)` operator.
Use `<` instead of `<=` to merge only overlapping, not meeting, periods (the
"overlaps but not meets" variant some products expose).

**(b) Declarative SQL (no new operator).** Coalescing adds no expressive power
to SQL. One statement: join `f` (first) and `l` (last) of a chain with the
same value; a `NOT EXISTS` ensures no gap between them (every start `m.S`
inside `(f.S, l.E)` is covered by some tuple starting before it and reaching
it), a second `NOT EXISTS` ensures maximality (no tuple extends `f` to the
left or `l` to the right). Correct but nested-anti-join cost is cubic-ish;
conventional optimizers treat the inequality predicates with nested loops.

**(c) Iterated UPDATE to fixpoint.** Repeatedly extend each tuple's end to the
max end of overlapping later tuples with the same value until nothing
changes; then remove subsumed tuples. Number of iterations bounded by chain
length; still far slower than (a).

**(d) Recursive SQL** (Leung & Pirahesh, DB2): chain discovery as a recursive
CTE.

> **Beyond EDBS:** With window functions, (a) becomes a standard
> "gaps and islands" query, which modern optimizers execute as one sort plus
> one window pass:
> ```sql
> SELECT a, MIN(s) AS s, MAX(e) AS e FROM (
>   SELECT a, s, e, SUM(brk) OVER (PARTITION BY a ORDER BY s, e
>                                  ROWS UNBOUNDED PRECEDING) AS grp
>   FROM (SELECT a, s, e,
>           CASE WHEN s <= MAX(e) OVER (PARTITION BY a ORDER BY s, e
>                    ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING)
>                THEN 0 ELSE 1 END AS brk
>         FROM r) x) y
> GROUP BY a, grp;
> ```
> Note the running `MAX(e)` over *all* preceding rows, not `LAG(e)`: a long
> earlier tuple can cover later short ones (the classic bug). Teradata offers
> coalescing natively as `SELECT NORMALIZE [ON MEETS OR OVERLAPS | ON
> OVERLAPS] ...` over PERIOD columns, and unfolding as `EXPAND ON`.

**(e) Main-memory client-side.** Load ordered tuples via a cursor and coalesce
with one tuple of state (the EDBS entry shows an ODBC loop) — the DBMS as a
storage manager. Fast but outside the optimizer.

### 4.5 Bitemporal and multi-dimensional coalescing

There is no unique coalesced form of a set of rectangles: merging along VT
first vs TT first yields different (snapshot-equivalent) tuple sets. Rule
for data-maintenance queries: coalesce valid time **within** each
transaction-time slice (fix TT, coalesce VT). An engine should either refuse
2-D coalescing or define the dimension order explicitly.

### 4.6 Fold/unfold as a reference implementation

`unfold(r)`: one point-stamped tuple per chronon of each period. `fold(r)`:
maximal periods of value-equivalent points. `fold(q(unfold(r)))` is a correct
(point-based) implementation of sequenced `q`, but it is coalescing by
construction, so it loses lineage: the car-rental example yields
`(1, [19,23))` where lineage-preserving semantics wants `(1,[19,21))`,
`(1,[21,23))`. Point-based languages also need a surrogate identifier
(`SeqNo`) to express time-invariant counts and "2-day rentals", and even then
a temporal difference keyed on that identifier silently degenerates. Use fold/
unfold as a test oracle (it is obviously correct up to snapshot equivalence),
not as a production plan.

---

## 5. Temporal difference

The operator conventional DBMSs support worst. Per value class, subtract the
union of `s` periods from each `r` period:

```
for each value class a (sorted by Ts on both sides):
    S = coalesced periods of s with value a       # sorted, disjoint
    for each r tuple [rs, re):
        cursor over S starting at first period with e > rs
        emit maximal sub-periods of [rs, re) not covered by S
```

Sort-merge on `(A, Ts)` gives `O((|r|+|s|) log + output)`. A tuple may emit
`k+1` pieces when `k` `s` periods fall inside it. Dunn, Davey, Descour &
Snodgrass ("Sequenced subset operators", ICDE 2002) give algebraic
formulations and efficient implementations for this family. In SQL it
requires nested `NOT EXISTS` with endpoint arithmetic.

---

## 6. Algebraic identities: what survives

Some relational identities carry over to temporal operators under snapshot
evaluation (σ pushdown through ×ᵗ, commutativity/associativity of ⋈ᵗ, since
each holds pointwise); others fail for the representation even when they hold
up to snapshot equivalence (anything involving projection followed by a
representation-sensitive operator). Rule for an optimizer: tag every rewrite
with the equivalence it preserves (identity / multiset / snapshot) and only
apply snapshot-equivalence rewrites below a coalesce or under a point-based
consumer. Gadia & Nair (TKDE 1998) give identities for a parametric model.

Sources: EDBS entries Temporal Algebras (p.3905), Timeslice Operator
(p.4159), Temporal Projection (p.4016), Temporal Coalescing (p.3917),
Snapshot Equivalence (p.3512), Period-Stamped Temporal Models (p.2742),
SQL-Based Temporal Query Languages (p.3683), Temporal Query Processing
(p.4028), Abstract Versus Concrete Temporal Query Languages (p.2), Temporal
Extensions in the SQL Standard (p.3963; includes the Temporal Expression
fragment).
