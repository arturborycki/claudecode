# Datalog, recursion, and the expressive-power limits that force it

Read this when implementing or optimizing `WITH RECURSIVE`, building a
Datalog/rule engine, deciding where negation or aggregation may appear inside
recursion, pushing predicates into a recursive query (magic sets), or
explaining why some query cannot be written without recursion.

---

## 1. Why recursion: what FO (= RA = SQL without recursion) cannot do

| Query | Expressible in FO/RA? | Why not / tool |
|---|---|---|
| Transitive closure / reachability | no (Fagin 1975; Aho & Ullman 1979 for RA) | not *local*: an FO formula of quantifier rank `r` cannot tell `(j,k)` from `(k,j)` on a long path once `j, k, k−j, n−k` are large |
| Graph connectivity | no — not even in existential monadic SO (Fagin) | if TC were FO, connectivity = `∀x∀y TC(x,y)` |
| Parity / EVEN of `|R|` | no (even over linear orders) | EF games; violates the 0–1 law (probability oscillates) |
| "Is `|R| > |S|`" | no | FO cannot compare cardinalities; SQL adds `COUNT` for this |
| Acyclicity, being a tree, bipartiteness | no | EF games / locality |

**Tools, briefly.**

- **Ehrenfeucht–Fraïssé games.** Spoiler and Duplicator alternately pick
  elements in structures `A` and `B` for `r` rounds; Duplicator wins if the
  picked elements induce a partial isomorphism. Theorem: Duplicator has a
  winning strategy for `r` rounds iff `A` and `B` agree on all FO sentences
  of quantifier rank ≤ `r`. To show `P` not FO: for every `r`, exhibit
  `A_r ⊨ P`, `B_r ⊭ P`, Duplicator wins `r` rounds. (Variants exist for
  finite-variable logics and MSO.)
- **Locality** (Gaifman, Hanf): FO formulas only see bounded-radius
  neighborhoods of their free variables in the Gaifman graph. Easier than
  games and survives counting quantifiers and SQL-style aggregation over
  unordered domains (Hella, Libkin, Nurmonen, Wong, JACM 2001; Libkin, TCS
  2003). **So SQL with GROUP BY/aggregates but without recursion still cannot
  compute transitive closure.** With an order on the domain plus arithmetic,
  proving this becomes as hard as separating complexity classes (uniform
  TC0 vs NLOGSPACE).
- **0–1 laws.** For FO (and LFP, infinitary `L^ω_∞ω`, but not ESO or MSO),
  every constant-free Boolean query is almost surely true or almost surely
  false on random structures of size `n → ∞`. A query whose limit
  probability is not 0 or 1 (EVEN: 1/2) is not definable. Caveat: an almost
  surely true query can still be inexpressible (connectivity).

**Capturing complexity classes.**

| Language | Power |
|---|---|
| FO (RA, RC, pure SQL) | AC0 data complexity; local |
| FO + aggregates (SQL-92 style) | still local on unordered data |
| Datalog | PTIME, monotone, cannot express non-monotone queries |
| Stratified Datalog¬ | strictly more; still not all of PTIME on unordered structures |
| FO + LFP / IFP (inflationary Datalog¬) | = PTIME on **ordered** structures (Immerman, Vardi 1982) |
| `While` (RA + assignment + while-change loops) | = PSPACE on ordered structures; cannot express EVEN without order (Chandra) |
| `LC`/`WhileN` (+ integer counters) | complete on ordered domains, still not EVEN without order |
| `QL` (untyped relation variables, Chandra & Harel 1980), `WhileNew` (invent values, Abiteboul & Vianu) | computationally complete for generic queries |
| Embedded SQL with cursors | complete but nondeterministic (cursor order); determinism undecidable |

Open: a logic capturing PTIME on unordered structures (FO + fixpoint +
counting falls short).

**Engine implications.**

1. Recursion needs a real fixpoint operator; it cannot be desugared into a
   fixed number of joins (boundedness is undecidable for Datalog).
2. Cursor-loop / procedural fallbacks buy completeness at the price of
   determinism; plan-dependent iteration order must not leak into results.
3. Order and arithmetic are what make recursion with counters powerful
   (and termination undecidable) — restrict them inside recursive bodies, or
   enforce iteration limits.

---

## 2. Datalog: syntax and three equivalent semantics

Rule `T(x̄) :- B1(ȳ1), …, Bk(ȳk)`: a CQ with a named head. EDB predicates
occur only in bodies (stored tables); IDB predicates occur in some head
(derived). Range restriction: every head variable occurs in the body. No
function symbols (that is what separates Datalog from Prolog and guarantees
termination).

1. **Model-theoretic**: each rule is a Horn clause
   `∀x̄ (∃ȳ body → T(x̄))`. Among all instances that agree with the EDB and
   satisfy the clauses, there is a unique **minimum** model.
2. **Proof-theoretic**: facts provable by proof trees whose leaves are EDB
   facts and whose internal nodes are rule instantiations.
3. **Fixpoint**: the immediate-consequence operator `T_P(I) = I_EDB ∪
   { heads derivable in one step from I }` is monotone; its least fixpoint
   `T_P^ω(∅)` is reached after finitely many steps because no new constants
   are invented (the IDB lattice over `adom` is finite). `T_P` is expressible
   in SPCU algebra (no difference).

All three coincide. Datalog without recursion = UCQ = positive RA.

---

## 3. Bottom-up evaluation: naive and semi-naive

**Naive**: `I_{k+1} = T_P(I_k)` until no change. Rederives everything every
round: `O(#rounds × cost of full rule evaluation)`.

**Semi-naive** (differential): only fire rule instances that use at least
one fact new in the last round.

```
for each IDB P:  P := rules_nonrecursive(EDB);  ΔP := P
loop:
  for each recursive rule  H :- A1, ..., Ak   (Ai over IDB/EDB)
     # one delta rule per IDB body atom position j:
     #   H_new ∪= A1_old ⋈ ... ⋈ A_{j-1}_old ⋈ ΔA_j ⋈ A_{j+1}_all ⋈ ... ⋈ A_k_all
     #   (old = before last round, all = old ∪ Δ)  -> each new derivation counted once
  for each IDB P:  ΔP := P_new − P ;  P := P ∪ ΔP
until all ΔP = ∅
```

- For **linear** rules (one IDB atom in the body), there is exactly one delta
  rule: `ΔT_{k+1} = (ΔT_k ⋈ E) − T`. This is precisely the "working table"
  algorithm of SQL recursive CTEs.
- For **nonlinear** rules (e.g. `T(x,y) :- T(x,z), T(z,y)`), the
  old/Δ/all split avoids deriving the same fact from two deltas twice.
  Nonlinear TC converges in `O(log diameter)` rounds versus `O(diameter)`
  for linear TC, at higher per-round cost.
- Correctness requires monotonicity of every rule body in the recursive
  predicates — exactly what stratification guarantees (§5).
- The set-difference `P_new − P` is where set semantics enters: it is a
  hash-anti-join against the accumulated result and is the dominant memory
  cost (the accumulated relation must be indexed).

> **Beyond EDBS:** Modern Datalog engines (Soufflé, Jordan, Scholz &
> Subotić, CAV 2016; LogicBlox/LogiQL; differential-dataflow-based engines)
> compile semi-naive evaluation to specialized nested-loop/index-join code
> with per-relation B-tree/trie indexes chosen from the rule access
> patterns, and LogicBlox used worst-case-optimal leapfrog triejoin for rule
> bodies.

---

## 4. Goal-directed evaluation: top-down, QSQ, magic sets

Bottom-up ignores constants in the query goal (`?- anc('ann', Y)`) and may
derive facts irrelevant to any answer. Top-down (SLD resolution, Prolog)
uses goal bindings but is tuple-at-a-time and can loop on left recursion;
**tabling**/QSQ (query-subquery) applies resolution set-at-a-time with
memoized subgoals.

**Adornments / binding patterns.** Annotate each IDB occurrence with which
arguments are bound (`b`) or free (`f`) under a **sideways information
passing strategy** (SIPS) — the left-to-right order in which body atoms pass
bindings. `anc^{bf}` = first argument bound.

**Magic-sets rewriting** (Bancilhon, Maier, Sagiv, Ullman, PODS 1986)
simulates top-down binding propagation inside bottom-up evaluation:

```
1. Adorn the program from the goal using a SIPS.
2. For each adorned IDB p^α, create magic_p^α holding the bound-argument
   tuples that are "asked for".
3. Seed: magic_goal(constants of the goal).
4. Each rule  p^α(x̄) :- B1..Bk  gets magic_p^α(bound part of x̄) prepended
   to its body (restricts derivations to requested bindings).
5. For each IDB atom Bj^β in a rule body, emit a magic rule:
   magic_Bj^β(bound args of Bj) :- magic_p^α(bound x̄), B1, ..., B_{j-1}
   (the bindings available to the left of Bj under the SIPS).
6. Evaluate the rewritten program semi-naively.
```

Example (same generation, `?- sg('john', Y)`):

```
sg(X,X)   :- person(X).
sg(X,Y)   :- par(X,X1), sg(X1,Y1), par(Y,Y1).
-- rewritten (adornment bf):
magic_sg('john').
magic_sg(X1) :- magic_sg(X), par(X,X1).
sg(X,X)      :- magic_sg(X), person(X).
sg(X,Y)      :- magic_sg(X), par(X,X1), sg(X1,Y1), par(Y,Y1).
```

Properties: the rewritten program computes the same goal answers, and its
semi-naive evaluation derives the same facts as QSQ-style top-down
evaluation. Variants: supplementary magic (materialize rule prefixes shared
between magic and modified rules), counting (tracks derivation depth;
cheaper for some linear programs, unsafe on cyclic data). Magic sets apply to
non-recursive SQL too: Mumick, Finkelstein, Pirahesh, Ramakrishnan ("Magic is
relevant", SIGMOD 1990) and Seshadri et al. (magic decorrelation, ICDE 1996)
used it in Starburst/DB2 to push outer-query bindings into views and
correlated subqueries.

When it loses: the magic set itself is large (weakly selective goal), or the
SIPS order is poor. Cost it like any other rewrite. With negation, the
rewritten program may stop being stratified even if the original was
(remedies: restrict SIPS, or "soft stratification", Behrend, PODS 2003).

Other optimization axes from the deductive-database literature: algebraic
rewriting of the fixpoint equations (CSE, selection pushing), reduction of
variables/constants, and **semantic** optimization with integrity
constraints (Chakravarthy, Grant, Minker 1986) — e.g. answering from a
constraint without touching the data.

---

## 5. Negation and stratification

Datalog¬ allows negated body atoms (safety: their variables must occur in a
positive body atom). Naive fixpoint semantics breaks: there may be no
fixpoint, several minimal ones, or a derived negative fact may later become
positive.

**Stratification** (Chandra & Harel 1985; Apt, Blair, Walker; Van Gelder):

```
Dependency graph: node per IDB predicate; edge p -> q if q occurs in a body
of a rule with head p; mark the edge negative if q occurs negated.
Program is stratified iff no cycle contains a negative edge.
Algorithm: SCC decomposition; reject if any SCC contains a negative edge;
topologically order SCCs; evaluate SCCs in order, treating lower strata as
EDB; negation = anti-join against the completed lower stratum.
```

The result (perfect model) is independent of the chosen stratification.
Beyond stratification: locally stratified programs, well-founded semantics
(3-valued; always exists), stable models (may be none or many — answer set
programming). Engines that implement SQL recursion only need stratification.

**Aggregation** inside recursion follows the same rule: *stratified
aggregation* — if `p` aggregates over `q`, `q` must not depend on `p`.
Stratified aggregation (sum, avg, min, max, count) cannot express
"summarized explosion" (bill of materials with quantities), but adding `+`
and constants 0, 1 makes it complete on integers even with only `max`
(Mumick & Shmueli 1995). Monotonic aggregation (Ross & Sagiv, JCSS 1997)
admits recursion through aggregates that are monotone in a lattice (e.g.
`min` for shortest paths).

> **Beyond EDBS:** The "pre-mappability" (PreM) condition of Zaniolo et al.
> (TPLP 2017), used in BigDatalog/DeALS, characterizes when a `min`/`max`
> can be pushed into the recursion (shortest path, connected components by
> min label) while preserving the stratified semantics; this is the
> principled way to support `MIN` inside a recursive CTE as an extension.

---

## 6. Bag semantics and recursion

Multiplicity of a derived fact = Σ over its derivation trees of the product
of leaf multiplicities. Recursive programs can have **infinitely many
derivation trees** (cycles in the data), giving infinite multiplicity.
Deciding whether a given output count is infinite is polynomial in data
complexity even with safe stratified negation (Mumick & Shmueli); deciding
statically whether counts are finite on *all* inputs is decidable for plain
Datalog but undecidable with stratified negation.

Consequence for SQL: `WITH RECURSIVE … UNION ALL` is bag-semantics Datalog.
On cyclic data it does not terminate (the engine keeps re-deriving), whereas
`UNION` gives set semantics and always terminates on finite data.

---

## 7. Mapping to SQL recursive CTEs

| Datalog notion | SQL `WITH RECURSIVE` |
|---|---|
| base rules | non-recursive (anchor) member(s) |
| recursive rules | recursive member(s), combined with `UNION [ALL]` |
| linear recursion | standard requires each recursive member to reference the CTE once (PostgreSQL enforces it); mutual recursion allowed by the standard, rarely implemented |
| set semantics fixpoint | `UNION`: each new row checked against all rows produced so far |
| bag semantics | `UNION ALL`: no dedup; may not terminate |
| semi-naive Δ | the "working table": the recursive member reads only last round's rows |
| stratified negation/aggregation | standard forbids aggregation, `DISTINCT` (in older versions), `NOT EXISTS`/`EXCEPT` and outer-join null-padding *on the recursive reference* within the recursive member; non-recursive tables may be negated freely |
| cycle detection | SQL:1999 `CYCLE` clause (PostgreSQL ≥ 14 implements `SEARCH`/`CYCLE`); otherwise carry a path array and test membership |
| traversal order | `SEARCH DEPTH/BREADTH FIRST BY` adds an ordering column; the fixpoint itself is order-free |

**Executor algorithm (linear, set semantics):**

```
result := dedup(anchor);  work := result;  seen := hash_set(result)
while work not empty:
   next := eval(recursive_member, CTE := work)       # pipelined joins
   next := { t ∈ next | t ∉ seen }   ; seen ∪= next   # anti-join vs all
   emit next ; work := next
```

**Predicate pushdown into a recursive CTE.** A filter `σ_c(CTE)` from the
outer query can be pushed into the anchor (and thus into every round) iff
`c` references only columns that the recursive member copies unchanged from
the recursive reference — **invariant columns**. In

```sql
WITH RECURSIVE tc(src, dst) AS (
  SELECT src, dst FROM edge
  UNION
  SELECT e.src, t.dst FROM edge e JOIN tc t ON e.dst = t.src)
SELECT * FROM tc WHERE dst = 42;
```

`dst` is invariant (copied from `t.dst`), so `dst = 42` moves into the
anchor: the recursion computes only paths ending at 42. A filter on `src`
(which changes each round) cannot be pushed; it needs the magic-set rewrite
(seed a magic relation with 42 and grow it along edges) or, for this
symmetric shape, re-associating the recursion to the other side
(left-linear vs right-linear). Bounding filters like `depth < 10` on a
column the recursive member increments monotonically *can* be pushed into
the recursive member (they prune; monotonicity guarantees no later row
re-enters).

**Termination.** Under `UNION` and no value invention, termination is
guaranteed (finite lattice). Value invention (arithmetic like
`depth + 1`, string concatenation, path arrays) makes each row new and
breaks the guarantee; engines should support an iteration cap and cycle
clauses.

**Distributed / parallel semi-naive.** Partition the accumulated relation and
the delta by a hash of the **full tuple** (or of a key that determines it)
so dedup is local; join with EDB by repartitioning the delta on the join key
(or broadcasting a small EDB); global termination = all partitions' deltas
empty in the same round (a barrier per iteration, or asynchronous
termination detection for monotone programs). Non-linear rules need both
operands' deltas exchanged.

> **Beyond EDBS:** Monotone (negation-free) programs can be evaluated
> without coordination barriers — the CALM principle (Hellerstein 2010;
> formalized by Ameloot, Neven, Van den Bussche, PODS 2011/JACM 2013):
> a query has a coordination-free distributed implementation iff it is
> monotone. Stratum boundaries (negation, aggregation) are exactly where
> barriers are needed.

---

## 8. Failure modes

- Pushing a filter on a non-invariant column into a recursive CTE (silently
  drops answers).
- Treating `UNION ALL` recursion as terminating on graphs (cycles) or
  `UNION` as cheap (the `seen` set grows to the full result).
- Allowing `NOT EXISTS`/aggregation on the recursive reference (unstratified)
  — results depend on iteration order.
- Semi-naive with nonlinear rules computing `Δ ⋈ Δ` twice, or missing the
  `Δ ⋈ old` term (incomplete results).
- Magic-set rewrite producing an unstratified program from a stratified one.
- Distributed dedup partitioned on the join key rather than on the tuple —
  duplicates across partitions, non-termination under `UNION`.

## 9. Tests

- Oracle: naive evaluation (trivially correct, slow) vs semi-naive vs
  magic-rewritten, on random graphs including self-loops, cycles, disconnected
  parts, empty EDB.
- Same-generation, TC (linear and nonlinear forms), bill-of-materials with
  stratified aggregation; assert identical sets.
- Recursive CTE suite: cyclic data with `UNION` (must terminate),
  `UNION ALL` with iteration cap (must error or stop as specified), pushed
  vs unpushed filters (identical answers), `CYCLE` clause correctness.
- Static checks: unstratified programs/CTEs rejected with a clear error.

---

Sources: EDBS entries Datalog (p.1000), Query Processing in Deductive
Databases (p.3046), Expressive Power of Query Languages (p.1415),
Ehrenfeucht-Fraïssé Games (p.1268), Zero-One Laws (p.4859), Computationally
Complete Relational Query Languages (p.547), Bag Semantics (p.252),
Aggregation: Expressiveness and Containment (p.74), Query Containment
(p.2981).
