# Algebra, calculus, and the laws that justify rewrites

Read this when you are adding or reviewing a logical rewrite rule, deciding
whether a rule is legal under SQL's bag semantics, handling outer joins or
aggregation in the rule set, or decorrelating subqueries. The theme: every
rewrite is an equivalence theorem with side conditions; most optimizer bugs
are a missing side condition (duplicates, NULLs, empty input, errors).

---

## 1. The formal objects

### 1.1 Relational algebra (RA)

Two presentations, both used in the literature:

| Perspective | Tuples are | Primitive operators | Notes |
|---|---|---|---|
| Unnamed (positional) | n-tuples, columns by index | `{c}` constant singleton, `σ_{i=j}`, `σ_{i=c}`, `π_{i1..ik}` (indices may repeat), `×`, `∪`, `−` | Clean for proofs; `×` is non-commutative (column order) |
| Named (attribute) | functions attr → value | `σ`, `π`, `⋈` (natural), `ρ` (rename), `∪`, `−` | Matches engines; `⋈` subsumes `×` (disjoint attrs) and `∩` (identical attrs) |

Derived operators: `∩` (= `R − (R − S)`, or a natural join on identical
schemas, or `σ`/`π` over `×`), theta-join `σ_θ(R × S)`, equijoin, semijoin
`R ⋉ S = π_{attr(R)}(R ⋈ S)`, antijoin `R ▷ S = R − (R ⋉ S)`, outer joins
(need a null value; not definable in pure RA), division.

Fragment names used throughout the theory:

| Fragment | Operators | Equivalent to |
|---|---|---|
| SPC / SPJ | σ (equality), π, × / ⋈ | conjunctive queries (CQ) |
| SPCU / SPJRU (positive RA) | + ∪ | unions of CQs (UCQ), nonrecursive Datalog with one output predicate |
| Full RA | + − | domain-independent relational calculus (Codd's theorem) |

The positive operators are *monotone*: `I ⊆ J ⇒ Q(I) ⊆ Q(J)`. Difference
is the only source of non-monotonicity in RA. Monotonicity is what makes
positive queries safe for incremental (insert-only) maintenance, for
semi-naive recursion, and for streaming without retraction.

### 1.2 Relational calculus (RC)

Domain RC: `{ ⟨e1..en⟩ | φ }` where `φ` is first-order over the schema plus
constants, and the free variables of `φ` are among the `ei`. Tuple RC (Codd's
original) has variables over tuples and terms `t.k`; it is inter-translatable
with domain RC.

**Domain independence.** Fix the active domain `adom(I) ∪ adom(Q)`. `Q` is
domain independent (d.i.) if `Q(I/D1) = Q(I/D2)` for every `D1, D2` that
contain that active domain. Non-examples:

- `{x | ¬R(x)}` — infinite or domain-sized output.
- `{(x,y) | R(x) ∨ S(y)}` — one column unconstrained when the other side holds.
- `{x | ∀y R(x,y)}` — output values are in adom, but membership depends on
  what `y` ranges over.
- `{x | ∃y (P(x) ∨ R(y))}` — if `R` is non-empty, every domain element
  qualifies.

**Undecidability.** Whether an RC query is d.i. (or finite) is undecidable
as soon as the schema has a relation of arity ≥ 2 (DiPaola 1969, Vardi 1981).
So languages define a decidable *syntactic* subclass ("safe",
"range-restricted", "allowed") that is d.i. and still expresses every d.i.
query up to equivalence. The shared idea:

1. Every free or existentially quantified variable must occur in a positive
   relational atom in its scope (or be equated to such a variable or a
   constant).
2. Every universally quantified variable must occur negatively (i.e. `∀y (R(x,y) → …)`).
3. Both branches of a disjunction must have the same free variables.
4. Variables in negated atoms must be bound positively elsewhere in the conjunction.

With interpreted functions (arithmetic, string concat) safety needs
*finiteness dependencies*: `P(z) ∧ x + y = z ∧ ¬Q(y)` is safe over ℕ because
`z` bounds `x, y`. Whether an "effective syntax" for d.i. queries exists
depends on the domain's operations (Stolboushkin–Taitslin: exists for
equality-only, (ℕ,<), Presburger; there are artificial domains where it
does not).

**Codd's theorem (precise form).** There is a total computable translation
from every RC query `q` to an RA expression `e` with
`e(I) = q(I / adom(I) ∪ adom(q))` — i.e. `e` evaluates `q` under
active-domain semantics. For d.i. `q` that equals `q(I)`. The key lemma: the
active domain is RA-computable (union of all column projections plus query
constants). Conversely every RA expression is d.i. and translates to RC. So
"relationally complete" = expresses RA.

Klug (1982) extended the equivalence to algebra and calculus with aggregate
functions.

**Genericity.** RA/RC queries commute with bijections of the domain that fix
the constants mentioned in the query ("C-generic"). Practical consequence: a
rewrite that is valid only for particular data values is not an algebraic law;
it is a *semantic* rewrite and must be justified by a constraint or a
runtime check.

### 1.3 What this means for an engine

- SQL's `FROM`-bound variables make SQL queries range-restricted by
  construction; domain dependence sneaks back in only via user-defined
  set-returning functions, generators (`generate_series` with
  data-dependent bounds), and "all values of the type" semantics nobody
  implements. The binder should reject or explicitly bound such constructs.
- A calculus-style IR (comprehensions, monoid calculus) is a legitimate
  internal representation: comprehensions express selections as filters,
  joins as nested generators, and normalization rules (generator unnesting,
  filter promotion) correspond to algebraic rewrites; they also make the
  set/bag/list distinction explicit as the collection monoid. (Fegaras &
  Maier, TODS 2000, is the standard engine-oriented treatment.)
- Equivalence of full RA expressions is undecidable (it inherits FO
  validity), so a general "are these two plans equal" checker cannot exist;
  rule-based rewriting with per-rule proofs is the only scalable approach.
  For the decidable fragments see `containment-and-minimization.md`.

---

## 2. Set, bag, and bag-set semantics

A bag relation is a function `R : D^k → ℕ` with finite support. Operator
semantics on multiplicities (SQL keyword in brackets):

| Operator | Multiplicity of `t` in output | SQL |
|---|---|---|
| `σ_p(R)` | `R(t) · [p(t)]` | `WHERE` |
| `π_V(R)` | `Σ_{t' : t'[V]=t} R(t')` | `SELECT` without `DISTINCT` |
| `R × S` | `R(t1) · S(t2)` | `FROM R, S` |
| `R ⊎ S` | `R(t) + S(t)` | `UNION ALL` |
| `R ∩ S` | `min(R(t), S(t))` | `INTERSECT ALL` |
| `R − S` | `max(R(t) − S(t), 0)` (monus) | `EXCEPT ALL` |
| `δ(R)` | `min(R(t), 1)` | `DISTINCT` |
| `UNION` | `δ(R ⊎ S)` | dedup after |
| `INTERSECT`, `EXCEPT` | `δ(R) ∩ δ(S)`, `δ(R) − δ(S)` | dedup the operands first |

For a CQ `Q(x̄) :- A1(z̄1), …, An(z̄n)` the multiplicity is
`Q(t) = Σ_{ν : ν(x̄)=t} Π_i Ai(ν(z̄i))` — sum over satisfying valuations of
the product of source multiplicities. A UCQ sums over its disjuncts.
Repeated atoms therefore matter: `R(x,y), R(x,y)` squares multiplicities.

**Bag-set semantics**: base relations are sets (every SQL table with a
primary key, or any table you can prove duplicate-free), intermediate and
final results are bags. This is the semantics of most real queries and it
matters: repeated identical atoms are harmless under bag-set (1·1 = 1) but
not under bag.

**Semiring view (unifying).** Annotate tuples with elements of a commutative
semiring `K`: Booleans give sets, `(ℕ,+,·)` gives bags, `ℕ[X]` gives
provenance polynomials (Green, Karvounarakis, Tannen, PODS 2007). Positive
RA is defined uniformly: `∪` adds, `⋈` multiplies, `π` sums. Consequence
for rule authors:

> A positive-RA rewrite whose proof uses only commutative-semiring
> identities (associativity and commutativity of `∪` and `⋈`, distributivity
> of `⋈` over `∪`, `σ` commuting with everything, `π` over `∪`) is valid for
> sets, bags, and provenance simultaneously. A rewrite whose proof needs
> **idempotence** (`R ∪ R = R`, `R ⋈ R = R`, absorption, core
> minimization) is valid only for sets.

Sharper, for UCQs: two positive expressions are bag-equivalent iff their
UCQ normal forms are isomorphic as multisets of CQs, counting repeated atoms
and repeated disjuncts (Chaudhuri–Vardi for CQs, Cohen–Nutt–Serebrenik for
UCQs). Under bag-set semantics: iff the forms with duplicate atoms removed
are isomorphic. Under set semantics: iff homomorphically equivalent
(Sagiv–Yannakakis). The UCQ normal form can be exponential, so this is a
proof technique for a rule, not a runtime check.

---

## 3. Law catalog: which identities survive bags

`p, q` predicates; `attr(p) ⊆ attr(R)` written `p/R`. "Bags" means SQL
without `DISTINCT`. NULL issues are separate (§5 and
`nulls-and-incomplete-information.md`); this table assumes two-valued
predicates.

| # | Law | Sets | Bags | Why / side condition |
|---|---|---|---|---|
| L1 | `σ_{p∧q}R = σ_pσ_qR` | yes | yes | multiplicity factor `[p][q]` |
| L2 | `σ_{p∨q}R = σ_pR ∪ σ_qR` | yes | **no** | rows satisfying both counted twice under `⊎`; use `σ_pR ⊎ σ_{q∧¬p}R` |
| L3 | `σ_p(R ⋈ S) = σ_pR ⋈ S`, `p/R` | yes | yes | |
| L4 | `σ_p(R ∪ S) = σ_pR ∪ σ_pS` | yes | yes | must push to both sides |
| L5 | `σ_p(R − S) = σ_pR − S` (= `σ_pR − σ_pS`) | yes | yes | monus with factor 0/1 |
| L6 | `π_V(R ∪ S) = π_VR ∪ π_VS` | yes | yes | |
| L7 | `π_V(R − S) = π_VR − π_VS` | **no** | **no** | fails even for sets |
| L8 | `π_V(R ∩ S) = π_VR ∩ π_VS` | **no** | **no** | only ⊆ holds |
| L9 | `π_V π_W R = π_V R`, `V ⊆ W` | yes | yes | |
| L10 | `π` commutes with `σ_p` when `attr(p) ⊆ V` | yes | yes | otherwise keep `attr(p)` below |
| L11 | `⋈` associative, commutative (named) | yes | yes | |
| L12 | `R ⋈ (S ∪ T) = R⋈S ∪ R⋈T` | yes | yes | distributivity |
| L13 | `R ∩ (S ∪ T) = (R∩S) ∪ (R∩T)` | yes | **no** | `min(r, s+t) ≠ min(r,s)+min(r,t)` |
| L14 | `R ∪ R = R` | yes | **no** | idempotence |
| L15 | `R ⋈ R = R` (same schema) | yes | **no** | squares multiplicities; true under bag-set only if `R` is a set |
| L16 | `R ∩ R = R` | yes | yes | `min(r,r)=r` |
| L17 | `R ∩ S = R − (R − S)` | yes | yes | `r − max(r−s,0) = min(r,s)` |
| L18 | `(R − S) − T = R − (S ∪ T)` | yes | yes | with `⊎` |
| L19 | `R − (S ∪ T) = (R−S) ∩ (R−T)` | yes | **no** | De Morgan needs idempotence |
| L20 | `R ⋈ S = R ⋉ S` when only `R` columns needed | yes | **no** | bags need each `R` row to match ≤1 `S` row (join key unique in `S`) |
| L21 | `R ⋉ S = R ⋉ δ(S)` | yes | yes | semijoin is duplicate-insensitive on the right |
| L22 | `δ(R ⋈ S) = δR ⋈ δS` | — | yes | |
| L23 | `δ(R ⊎ S) = δ(δR ⊎ δS)` | — | yes | partial dedup (pre-dedup per partition) is legal |
| L24 | `δ π_V R = π_V δ R` | — | **no** | dedup must come after projection |
| L25 | `δ(σ_p R) = σ_p δ R` | — | yes | |
| L26 | `R ⊎ (S − T) = (R ⊎ S) − T` | **no** | **no** | (`T` may cancel `R`'s copies) |
| L27 | Core minimization (drop redundant atoms) | yes | **no** | bag equivalence of CQs = isomorphism |

Engineering pattern: keep a **duplicate-insensitive context** flag that the
rewriter propagates top-down. A subtree is in such a context when its
consumer is `δ`, a semijoin/antijoin right input, `EXISTS`/`IN`/`NOT EXISTS`,
the argument of `MIN`, `MAX`, `COUNT(DISTINCT)`, `BOOL_AND/OR`, or an operand
of `UNION`/`INTERSECT`/`EXCEPT` (distinct forms). Inside that context the
set-only laws (L2, L14, L15, L20, L27, join elimination without uniqueness)
become legal. Outside it, they are bugs that change row counts.

---

## 4. Outer joins

`R ⟕_p S` = `(R ⋈_p S) ⊎ ((R ▷_p S) × {null_S})`. The padded nulls are
indistinguishable from stored nulls in SQL, which is what makes the laws
delicate.

**Null-rejecting (strict) predicate.** `q` is null-rejecting on attribute set
`A` if `q` evaluates to FALSE or UNKNOWN whenever all of `A` are NULL. `x = 5`,
`x > y`, `x IS NOT NULL` are null-rejecting on `x`; `x IS NULL`,
`COALESCE(x,0) = 0`, `x = 5 OR y = 3` (only on `{x}` alone it is not),
`CASE`-wrapped tests generally are not. Derive strictness bottom-up over
expressions: strict functions propagate, `OR` is strict on `A` only if both
arms are, `AND` if either arm is.

| Law | Condition |
|---|---|
| `σ_q(R ⟕_p S) = σ_q(R ⋈_p S)` (outer-join simplification) | `q` null-rejecting on some attribute of `S` |
| `σ_q(R ⟕_p S) = (σ_qR) ⟕_p S` | `q/R` and `q` is in `WHERE` (above the join) |
| ON-clause predicate on preserved side | **cannot** be pushed into `R`; it only decides matching. It can be pushed into neither input; it stays in `p` |
| ON-clause predicate on null-supplying side | can be pushed into `S` |
| `(R ⟕_{p} S) ⟕_{q} T = R ⟕_{p} (S ⟕_{q} T)` | `q` references only `S,T` and is null-rejecting on `S` |
| `(R ⋈_p S) ⟕_q T = R ⋈_p (S ⟕_q T)` | `q` references only `S,T` |
| `R ⟕ (S ⋈ T)` vs `(R ⟕ S) ⋈ T` | not equivalent in general |
| Full outer join reassociation | strict predicates on both sides involved |
| `R ⟕_p S = R` (LOJ elimination) | no column of `S` used above, and each `R` row matches ≤1 `S` row under `p` (unique key on `S` covering `p`'s equality columns); in a duplicate-insensitive context uniqueness is unnecessary |
| `R ⟕_p S` with `σ_{S.k IS NULL}` on top = `R ▷_p S` | `S.k` is NOT NULL in `S` (or is the equi-join column) — otherwise genuine stored NULLs pass the test |

Full enumeration of reorderings for mixed inner/outer/semi/anti joins needs
conflict detection; see Galindo-Legaria & Rosenthal (TODS 1997),
Moerkotte & Neumann (SIGMOD 2008, hypergraph DP), and Moerkotte, Fender &
Eich (SIGMOD 2013) for a correct and complete conflict-detector.

> **Beyond EDBS:** The EDBS algebra entries define outer joins but not their
> reordering theory; the references above are the standard modern sources and
> are what production DP enumerators (e.g. in HyPer/Umbra-lineage systems)
> implement.

---

## 5. Aggregation

`γ_{G; f1(a1),…}(R)` groups by `G`. Two facts dominate correctness:

1. **Scalar vs grouped aggregation on empty input.** `γ_{∅; COUNT(*)}(∅)`
   returns **one** row `(0)`; `γ_{∅; SUM(x)}(∅)` returns one row `(NULL)`;
   `γ_{G;…}(∅)` with `G ≠ ∅` returns **zero** rows. Any rewrite that turns
   a scalar aggregate into a grouped one (decorrelation, pushdown below a
   join) changes the empty-group behavior.
2. **Aggregates are duplicate-sensitive or not.** `COUNT`, `SUM`, `AVG` are
   sensitive; `MIN`, `MAX`, `COUNT(DISTINCT)`, `SUM(DISTINCT)` are not.
   Insensitive aggregates tolerate bag→set rewrites and redundant joins that
   only duplicate rows.

**Decomposability** (Gray et al. data cube classification): distributive
(`COUNT`, `SUM`, `MIN`, `MAX`: `f(X ⊎ Y) = g(f(X), f(Y))`), algebraic
(`AVG` via `(SUM, COUNT)`, variance via `(n, Σx, Σx²)`), holistic (median,
mode, exact distinct count: no bounded partial state). Decomposability is
what licenses:

- `γ_{G;f}(R ⊎ S) = γ_{G;g}(γ_{G;f}R ⊎ γ_{G;f}S)` — partial/final
  aggregation in parallel and distributed engines.
- Eager aggregation below a join (Yan & Larson, VLDB 1995; Chaudhuri & Shim,
  VLDB 1994): for `γ_{G; f(R.x)}(R ⋈_{R.a=S.b} S)` pre-aggregate `R` on
  `(G ∩ attr(R)) ∪ {a}`, then join, then (usually) re-aggregate on `G`.
  Conditions: (i) `f` decomposable; (ii) if `S` can match an `R` group more
  than once, duplicate-sensitive aggregates must be scaled — `SUM` becomes
  `SUM(partial_sum · cnt_S)`, `COUNT` becomes `SUM(partial_cnt · cnt_S)`,
  `MIN/MAX` need no scaling; when `S.b` is a key (FK→PK join) no scaling is
  needed; (iii) the final re-aggregation can be dropped only if the
  pre-aggregation groups map one-to-one onto output groups (e.g. `G`
  contains `a`, or `a → G` holds after the join).
- `DISTINCT` aggregates are not decomposable across arbitrary partitions;
  they become decomposable when data is partitioned by the distinct
  argument (or by `G ∪ {arg}`).

Expressiveness note: adding aggregation strictly increases power (RA cannot
compare cardinalities: "is `|R| > |S|`" is not FO), but RA with aggregates
over unordered domains remains *local* (Hella, Libkin, Nurmonen, Wong;
Libkin, TCS 2003), so it still cannot express transitive closure. See
`datalog-and-recursion.md`.

---

## 6. Subqueries and decorrelation

Model correlated subqueries with a dependent join / `Apply(R, E(r))`
operator (Galindo-Legaria & Joshi, SIGMOD 2001): for each `r ∈ R` evaluate
`E` with `r` bound. Decorrelation = pushing `Apply` down until the right side
no longer references `r`, then replacing it by a join. The rewrites are
algebraic, but each one carries a NULL/empty/duplicate side condition.

### 6.1 The COUNT bug (Kiessling, VLDB 1985; Ganski & Wong, SIGMOD 1987)

```sql
SELECT d.id FROM dept d
WHERE d.planned_headcount = (SELECT COUNT(*) FROM emp e WHERE e.dept_id = d.id);
```

Kim's (TODS 1982) transformation: join `dept` with
`(SELECT dept_id, COUNT(*) c FROM emp GROUP BY dept_id)` and test
`planned_headcount = c`. A department with no employees and
`planned_headcount = 0` qualifies in the original (scalar `COUNT` of empty =
0) but vanishes after the rewrite (grouped aggregate produces no group, the
inner join drops the department).

Correct rewrite: outer join, then aggregate, and count a non-nullable
column of the inner side:

```
γ_{d.*; COUNT(e.id)}( dept ⟕_{e.dept_id = d.id} emp )   -- COUNT(e.id), not COUNT(*)
```

`COUNT(*)` after the outer join would count the padded row as 1. Equivalent
alternative: aggregate first, outer join, then `COALESCE(c, 0)` — where the
coalesced value must be *the aggregate's value on the empty bag*, which is
0 for `COUNT`, NULL for `SUM/MIN/MAX/AVG`, and the initial-state result for
user-defined aggregates. Generalization: any expression over the subquery
result that is non-NULL on empty input (`COUNT`, `COALESCE(SUM(x),0)`,
`x IS NULL`, UDAs with non-null init) is affected. Neumann & Kemper (BTW 2015)
give a general unnesting algorithm that handles this uniformly by joining
with the domain of outer bindings.

### 6.2 Rewrite table for subquery predicates (WHERE context)

| Construct | Rewrite | Legal when |
|---|---|---|
| `EXISTS (…corr…)` | semijoin | always |
| `NOT EXISTS (…corr…)` | antijoin | always (a NULL correlation value matches nothing, so the outer row survives; that is the antijoin's behavior too) |
| `x IN (SELECT y …)` | semijoin on `x = y` | always in WHERE/ON conjunct context (UNKNOWN and FALSE both reject) |
| `x NOT IN (SELECT y …)` | antijoin on `x = y` | only if `x` and `y` are both NOT NULL; otherwise use a **null-aware antijoin**: empty subquery → keep all rows; any `y` NULL → reject every row; `x` NULL with non-empty subquery → reject |
| `x IN (…)` under `OR`, `NOT`, `CASE`, or in the SELECT list | **mark join** producing TRUE/FALSE/UNKNOWN | three-valued result must be preserved |
| `x > ALL (SELECT y …)` | `NOT EXISTS (… WHERE NOT (x > y) …)` with 3VL care | rewriting to `x > (SELECT MAX(y) …)` is **wrong**: empty set gives TRUE for ALL but `MAX` = NULL → UNKNOWN; a NULL `y` makes ALL UNKNOWN but `MAX` ignores it |
| `x > ANY (SELECT y …)` | `x > MIN(y)` | WHERE context only, and needs `MIN` NULL-on-empty to coincide with FALSE (it does in WHERE) |
| scalar subquery `(SELECT y … corr)` | outer join | must preserve "more than one row ⇒ runtime error" (insert a max-one-row check) and "zero rows ⇒ NULL" |

### 6.3 Other side conditions that bite rule authors

- **Errors and evaluation order.** `WHERE x <> 0 AND 10/x > 1` — reordering
  or pushing the second conjunct below a filter that guards it can raise a
  division error. Either treat potentially-raising expressions as
  non-reorderable, or evaluate them in a mode that maps errors to NULL only
  when the guarding conjunct is known false. `CASE` is the only
  order-guaranteeing construct users can rely on.
- **Volatile and non-deterministic expressions** (`random()`, sequence
  `nextval`, clock functions with per-row semantics) block CSE, predicate
  pushdown that changes how many times they are evaluated, and duplicate
  elimination of "identical" subexpressions.
- **LIMIT/TOP without ORDER BY** is non-deterministic; filters cannot move
  across a `LIMIT` at all.
- **Window functions**: a predicate can move below a window operator only if
  it references only `PARTITION BY` columns.
- **Equality is type-specific.** Substituting `a` for `b` after `a = b`
  (equivalence classes, transitive predicates) requires every function
  applied afterwards to respect that equality: under case-insensitive
  collations `'a' = 'A'` but `x || ''` differs; for floats `0.0 = -0.0` but
  `1/x` differs; for `PAD SPACE` collations trailing blanks differ. Restrict
  substitution to types/collations where equality is identity, or to
  functions declared equality-preserving.

---

## 7. Rule-authoring template

For every logical rule, write down and test:

1. **Pattern** and **rewrite**.
2. **Semantics assumed**: set / bag / bag-set (are inputs proven
   duplicate-free?), and whether the rule needs a duplicate-insensitive
   context.
3. **Constraint dependencies**: which keys/FKs/NOT NULL/CHECK it relies on,
   and whether those are enforced, informational, or deferrable (see
   `dependencies-chase-and-semantic-optimization.md`).
4. **NULL behavior**: is every moved predicate's three-valued result
   preserved? Are null-rejection claims derived, not assumed?
5. **Empty-input behavior**: scalar aggregates, `ALL`, `NOT IN`, outer joins.
6. **Errors/volatility**: can the rewrite evaluate an expression on rows
   where the original did not, or a different number of times?
7. **Output schema** (names, types, nullability) identical.
8. **Proof sketch** referencing the laws above, and a property test that
   runs both plans on random small instances with duplicates, NULLs and
   empty relations.

---

Sources: EDBS entries Relational Algebra (p.3146), Relational Calculus
(p.3147), Safety and Domain Independence (p.3269), Computationally Complete
Relational Query Languages (p.547), Positive Relational Algebra (p.2776),
Bag Semantics (p.252), Aggregation: Expressiveness and Containment (p.74),
Selection (p.3371), Projection (p.2893), Join (p.2049), Cartesian Product
(p.399), Union (p.4344), Difference (p.1071), Comprehensions (p.534),
First-Order Logic: Syntax (p.1484), First-Order Logic: Semantics (p.1482),
Relational Model (p.3149).
