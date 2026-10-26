# Dependencies, implication, the chase, and semantic query optimization

Read this when the optimizer wants to use constraints (keys, foreign keys,
NOT NULL, CHECK, functional or order dependencies) to remove joins, DISTINCT,
GROUP BY columns, sorts, or predicates; when deriving keys/FDs/orders as plan
properties; or when reasoning about whether one constraint set implies
another (schema evolution, view constraints).

---

## 1. The dependency zoo, as first-order sentences

Almost every practical constraint is an **embedded dependency**
`∀x̄ ( φ(x̄) → ∃z̄ ψ(ȳ, z̄) )` with `φ` a conjunction of relational atoms and
`ψ` a conjunction of relational atoms (a **tgd**) or equalities (an
**egd**). Full tgd: no `∃`. (Beeri & Vardi named them; Fagin's embedded
implicational dependencies are the same class.)

| Constraint | Class | FO form (example) |
|---|---|---|
| FD `R: X → Y` | egd | `R(x̄,ȳ,z̄) ∧ R(x̄,ȳ',z̄') → ȳ = ȳ'` |
| Key `X` of `R` | egd (FD `X → attr(R)`) | as above with all other columns |
| MVD `X ↠ Y` | full tgd | `R(x,y1,z1) ∧ R(x,y2,z2) → R(x,y1,z2)` |
| JD `⋈[X1..Xn]` | full tgd | `R(ū1) ∧ … ∧ R(ūn) → R(w̄)` with shared vars on overlaps |
| Inclusion dep. `R[X] ⊆ S[Y]` | embedded tgd | `R(z̄,x̄) → ∃w̄ S(x̄,w̄)` |
| Foreign key | IND + key on `S[Y]` | IND + egd |
| Disjunctive (DED), with `≠` | DED≠ | `φ → ∨_i ∃z̄i ψi`; expresses domain constraints (`t ∈ {a,b,c}`), cardinality ("≥2 reviews", "≤2 reviews") |
| CHECK `(p)` | single-row DED≠ / domain constraint | but with SQL's 3VL acceptance (§6.4) |
| Order dependency `X ↦ Y` | not an embedded dependency | lexicographic-order implication (§8) |

An MVD is a two-component JD; `X → Y` implies `X ↠ Y`. FDs/MVDs/JDs are
single-relation and **typed** (each variable stays in one column); INDs relate
relations and are untyped.

---

## 2. Implication

`Σ ⊨ σ`: every instance satisfying `Σ` satisfies `σ`. Two versions:
unrestricted (all instances) and **finite** (finite instances — the one
databases care about). Unrestricted implication of FO dependencies is r.e.;
finite implication is co-r.e.; where they coincide, implication is decidable.
They diverge in general:

> `Σ = { A → B, R[A] ⊆ R[B] }` on `R(A,B)` finitely implies `R[B] ⊆ R[A]`
> (and `B → A`): the FD gives `|π_A| ≥ |π_B|`, the IND gives `π_A ⊆ π_B`,
> finiteness forces equality. The infinite instance `{(i+1, i) | i ≥ 0}`
> satisfies `Σ` but not the conclusion.

Complexity map (`n` = input size):

| Dependencies | Implication | Notes |
|---|---|---|
| FDs | linear time (Beeri & Bernstein 1979) | attribute closure |
| MVDs | `O(n log n)` | dependency basis |
| FDs + MVDs | polynomial (Beeri 1980); sound & complete axioms | |
| JD from FDs | `O(n² log² n)` | |
| JD from MVDs | NP-hard; JD from JD+FD NP-complete | no finite axiomatization for JDs |
| Full tgds/egds | EXPTIME-complete; finite = unrestricted | chase terminates, Church–Rosser |
| INDs | PSPACE-complete; finite = unrestricted; axioms: reflexivity, projection/permutation, transitivity | Casanova, Fagin, Papadimitriou |
| FDs + unary INDs | finite implication decidable (≠ unrestricted) | Cosmadakis, Kanellakis, Vardi |
| FDs + INDs | **undecidable** (finite and unrestricted differ) | Chandra & Vardi 1985; Mitchell |
| Embedded MVDs | finite implication undecidable | Herrmann 1995 |
| tgds (even typed) | undecidable | |

The cruel irony: keys and foreign keys — the constraints engines actually
have — are FDs + INDs, whose general implication is undecidable. Engines
avoid the general problem by only using **pattern-specific** inferences
(join elimination, key derivation) whose soundness is proved once.

**Axiomatizations.**

- Armstrong (FDs): reflexivity (`Y ⊆ X ⇒ X → Y`), augmentation
  (`X → Y ⇒ XZ → YZ`), transitivity. Sound and complete. Derived: union,
  decomposition, pseudo-transitivity.
- FDs + MVDs (Beeri, Fagin, Howard 1977): MVD complementation, reflexivity,
  augmentation, pseudo-transitivity (`X ↠ Y, Y ↠ Z ⇒ X ↠ Z − Y`), plus
  conversion (`X → Y ⇒ X ↠ Y`) and interaction
  (`X ↠ Y, XY → Z ⇒ X → Z − Y`).
- Finite axiomatizability ⇒ decidability of finite implication (r.e. + co-r.e.),
  but not conversely (JDs: decidable by chase, no finite axiom system).

---

## 3. Attribute closure, minimal cover, keys

```
closure(X, F):                 # F: list of FDs Li -> Ri ; linear time
  for each fd i: missing[i] := |Li| ; for each attr a in Li: watch[a].push(i)
  result := X ; queue := X
  while queue: a := pop(queue)
    for i in watch[a]:
      missing[i] -= 1
      if missing[i] == 0:
        for b in Ri: if b ∉ result: result.add(b); queue.push(b)
  return result
Σ ⊨ X → Y  iff  Y ⊆ closure(X, Σ)
```

Minimal (canonical) cover: split right sides to single attributes; remove
extraneous left-side attributes (`B ∈ L` extraneous if `A ∈ closure(L−B)`);
remove redundant FDs (`A ∈ closure(L, F − {L→A})`). Not unique.

Keys: `K` is a superkey iff `closure(K) = attr(R)`; a candidate key if
minimal. Finding one key: start from all attributes and greedily drop
attributes while the closure stays complete (polynomial). Enumerating all
keys can be exponential in output; deciding whether an attribute is prime
(belongs to some key) is NP-complete (Lucchesi & Osborn 1978). See
`normalization-and-keys.md`.

---

## 4. The chase

Input: an instance (or a query's frozen body) with constants and **labeled
nulls**, and a set `Σ` of tgds and egds.

- **tgd step**: if `φ(ā, b̄)` holds but no `c̄` makes `ψ(ā, c̄)` hold, add
  `ψ(ā, n̄)` with **fresh, distinct** nulls `n̄`.
- **egd step**: if `φ` forces `a1 = a2` and they differ: if one is a null,
  replace it everywhere by the other; if both are distinct constants, the
  chase **fails** (no model exists — for a query: the query is unsatisfiable
  under `Σ`, return empty).
- Result (if it terminates) `U`: satisfies `Σ`; `I → U` (homomorphism);
  and `U` maps homomorphically into every model of `Σ` containing a
  homomorphic image of `I` — a **(strongly) universal model**. Results of
  different chase orders are homomorphically equivalent.

Variants:

| Variant | Fires | Terminates |
|---|---|---|
| Oblivious | every trigger, even if already satisfied | least often |
| Standard / restricted | only violated triggers (as above) | order-dependent |
| Parallel | all violated triggers per round | |
| Core chase (Deutsch, Nash, Remmel, PODS 2008) | parallel round + compute core | **complete**: terminates iff a finite universal model exists |

Termination is undecidable in general. Sufficient, cheaply checkable:
**weak acyclicity** (Fagin, Kolaitis, Miller, Popa 2005; Deutsch & Tannen's
"stratified witnesses"):

```
Graph over positions (R, i).
For each tgd, for each universally quantified variable x that occurs in the head:
   for each body position p of x:
      normal edge  p -> q   for every head position q of x
      special edge p -> q'  for every head position q' of an existential variable
Weakly acyclic  iff  no cycle goes through a special edge.
=> standard chase terminates in polynomially many steps (data complexity).
```

Full tgds (no `∃`) always terminate. **Cyclic foreign keys** (`Emp.dept →
Dept`, `Dept.mgr → Emp`; or a self-referencing `manager_id`) are *not* weakly
acyclic: an oblivious chase invents an infinite management chain. The egds of
the keys may stop it (a manager manages his own department), depending on
firing order. Engines therefore do bounded, pattern-based chasing — one FK
step per join being eliminated — rather than a full chase.

### 4.1 What the chase decides

- **Containment under constraints**: freeze `P`, chase with `Σ` to `P^Σ`;
  then `P ⊑_Σ Q` iff `P^Σ ⊑ Q` (plain homomorphism test). If the chase fails,
  `P` is empty under `Σ`. This reduces semantic optimization to the
  Chandra–Merlin test.
- **Implication** `Σ ⊨ (∀x̄ (α → ∃z̄ β))`: chase the frozen `α`; implied iff
  the frozen `β` maps in (tgd) or the equality was produced (egd).
- **Lossless join** of a decomposition (Aho, Beeri, Ullman 1979): chase the
  tableau with one row per component (distinguished symbols on its
  attributes); lossless iff some row becomes all-distinguished.
- **Equivalent rewriting with views and constraints**: Chase & Backchase
  (Deutsch, Popa, Tannen, VLDB 1999) — sound and complete for minimal
  rewritings when the chase terminates.
- **Data exchange**: universal solutions are chase results; certain answers
  of a UCQ = evaluate on the universal solution and discard tuples with
  nulls (Fagin, Kolaitis, Miller, Popa, TCS 2005); the core is the smallest
  universal solution.

---

## 5. Constraint propagation to views

`R:Σ ⊨ V:σ` — every view instance `V(I)` with `I ⊨ Σ` satisfies `σ`. Needed
to derive keys/FDs of derived tables (views, CTEs, subqueries) in the
optimizer. Complexity: undecidable for RA views even with FDs only; for
SPCU views, polynomial with FDs+MVDs, NP-complete with FDs+JDs to a JD,
EXPTIME-complete for full dependencies (Klug 1980 and successors). Hence
again: derive properties operator-by-operator with sound rules (§7), accept
incompleteness.

---

## 6. Semantic query optimization: the rewrites and their exact conditions

### 6.1 Inner join elimination (FK → PK)

`π_{cols(R)}(R ⋈_{R.f = S.k} S)` → `σ_{R.f IS NOT NULL}(R)` is legal when:

1. **Existence (IND)**: a foreign key `R.f → S.k` covers *all* join
   columns, and the join predicate is exactly the FK equality (same
   columns, same column order for composites).
2. **NULLs**: SQL FKs (MATCH SIMPLE) do not check rows with any NULL FK
   column. Either `R.f` is NOT NULL, or keep `R.f IS NOT NULL` (all
   columns, for composite FKs) as a residual filter — the join would have
   dropped those rows.
3. **Multiplicity**: under bag semantics `S.k` must be unique (it is, if the
   FK references a PK/UNIQUE constraint) so each `R` row matches exactly
   once. In a duplicate-insensitive context, (3) is unnecessary.
4. **No other use of `S`**: no `S` column needed above except `S.k`
   (replace by `R.f`), and no other predicate on `S`.
5. **Trust**: the constraint is validated and enforced *at statement
   time*. Not deferrable (a `DEFERRABLE INITIALLY DEFERRED` FK may be
   violated mid-transaction), not disabled/`NOT VALID`/`NOVALIDATE`.
   Informational constraints (`RELY` in Oracle, Teradata "soft RI"
   `REFERENCES WITH NO CHECK OPTION`, unenforced PK/FK in cloud warehouses)
   are a user promise: using them is allowed but wrong data ⇒ wrong
   answers. Make it a per-constraint flag the optimizer checks.
6. **Same equality**: the join uses the same equality the constraint
   enforces (same collation; no implicit cast that changes matching, e.g.
   `varchar` join under a case-insensitive collation vs a case-sensitive
   key).

The chase view: chasing `R(x̄, f)` with the IND adds `S(f, n̄)`, so the
frozen `R`-only query maps onto the join query; the key egd makes the
mapping one-to-one, which is what makes it bag-safe.

### 6.2 Left outer join elimination

`R ⟕_p S` → `R` when no `S` column is used above and `p`'s equality columns
cover a unique key of `S` (≤ 1 match per `R` row). No FK needed; no NOT NULL
needed. In a duplicate-insensitive context even uniqueness is unnecessary.
Commonly needed for ORM/BI-generated "join everything" views.

### 6.3 Self-join and DISTINCT/GROUP BY elimination

- **Self-join on a key**: `R r1 ⋈_{r1.k = r2.k} R r2` with `k` a key (NOT
  NULL) → single scan: the key egd unifies the two atoms (chase), leaving a
  duplicate atom, which is removable because `R` is a set. Bag-safe.
- **DISTINCT elimination**: `δ(E)` → `E` if `E`'s output columns contain a
  derived key of `E` **whose columns are NOT NULL**. A nullable UNIQUE column
  allows several NULL rows, and `DISTINCT` treats NULLs as equal, so it
  would collapse them — nullable UNIQUE is *not* a key for this purpose.
- **GROUP BY reduction**: grouping by `K ∪ A` with `K → A` (e.g. a key)
  ⇒ group by `K` only; non-grouped columns functionally dependent on the
  grouping columns may appear in the select list (SQL:1999 feature; PostgreSQL
  accepts it when grouping by a primary key). Group-by removal entirely when
  the grouping columns form a NOT NULL key of the input (each group is one
  row; aggregates become scalar expressions: `COUNT(*)`→1, `SUM(x)`→`x`,
  `COUNT(x)`→`CASE WHEN x IS NULL THEN 0 ELSE 1 END`).
- **Semijoin elimination**: `R ⋉_{R.f=S.k} S` → `σ_{R.f IS NOT NULL}R` under
  a trusted FK (uniqueness irrelevant: semijoins are duplicate-insensitive
  on the right).

### 6.4 Predicate introduction and elimination from CHECK/NOT NULL

- `CHECK (p)` accepts a row unless `p` is FALSE — rows where `p` is UNKNOWN
  (NULL inputs) pass. So the implied fact is `p OR (some input IS NULL)`,
  not `p`. Introducing `p` as a filter would drop NULL rows. Correct
  derived filter: `p IS NOT FALSE`; it is usable as `p` only for columns
  declared NOT NULL.
- Contradiction detection: `WHERE x < 0` with `CHECK (x >= 0)` and `x` NOT
  NULL ⇒ empty result (skip the scan; partition pruning is the same idea
  with partition-bound constraints).
- Redundant predicate removal: drop a WHERE conjunct implied by
  constraints + other conjuncts (implication restricted to the decidable
  interval/equality fragment, see `containment-and-minimization.md` §4.2).
- Transitive closure of equalities and constants over equivalence classes
  (`a = b ∧ b = 5 ⇒ a = 5`; safe in 3VL because an equality that is TRUE
  implies non-NULL operands), subject to the type-equality caveat in
  `algebra-calculus-and-rewrite-laws.md` §6.3.

### 6.5 Join introduction (rarer)

Adding a join to reach an index, a partitioning column, or an MV is legal by
the same FK/key argument run backwards (chase adds the atom; key makes it
bag-safe). C&B formalizes it.

---

## 7. Deriving FDs and keys as plan properties

Each logical node carries: candidate keys (sets of columns), an FD set
(or equivalence classes + FDs), constant columns, NOT NULL columns. Rules
(Darwen 1992; Paulley's thesis, Waterloo 2000):

| Operator | Derived properties |
|---|---|
| Base table | PK and NOT NULL UNIQUE ⇒ keys; nullable UNIQUE ⇒ *lax* key (holds among non-NULL rows only) |
| `σ_p` | inherit; `a = b` conjunct ⇒ `a ↔ b` (merge equivalence classes); `a = const` ⇒ `∅ → a` (constant column); null-rejecting conjunct ⇒ NOT NULL |
| `π` | keep keys/FDs fully inside the kept columns; computing all projected FDs needs closure over subsets (exponential worst case) — keep only FDs whose sides survive |
| `R ⋈_{R.a = S.b} S` | union of FDs, plus `a ↔ b`; if `S.b` is a key of `S` then every key of `R` is a key of the result (N:1 join); if both sides' join columns are keys, both sides' keys survive; in general `key(R) ∪ key(S)` is a key |
| `R ⟕ S` | `R`'s FDs and keys survive (if the join preserves cardinality); `S`'s FDs become lax (padding NULLs can violate them); equivalence `a ↔ b` holds only on matched rows |
| semijoin/antijoin | inherit from left |
| `γ_G` | `G` is a key of the output; FDs among `G` survive; `G → each aggregate` |
| `δ` | all output columns form a key |
| `UNION ALL` | keys lost (unless provably disjoint by a discriminating constant column); FDs lost in general |
| `INTERSECT`, `EXCEPT` (distinct) | all columns a key; left side's FDs survive for `EXCEPT`/`INTERSECT` (subset of left) |
| Window/`ROW_NUMBER() OVER (PARTITION BY P)` | `P ∪ {rn}` is a key |
| `LIMIT 1` / max-one-row | empty set is a key (`∅ → all columns`) |

Strict vs lax FDs: SQL equality treats NULL ≠ NULL in predicates but NULL =
NULL in grouping/DISTINCT. An FD derived from a nullable unique column or
from an outer join holds only for non-NULL determinants. Track the
distinction or restrict to NOT NULL columns.

---

## 8. Order dependencies and sort elimination

An **order specification** is a list of attributes with asc/desc
(`ORDER BY` semantics, lexicographic). OD `X ↦ Y` ("X orders Y") holds on
`r` if for all tuples `s, t`: `s ≤_X t ⇒ s ≤_Y t`. Unidirectional ODs use a
single direction throughout.

- ODs subsume FDs: `X → Y` iff `X ↦ XY` (prefix `X` onto `Y`); e.g. `salary
  → tax` iff `[salary] ↦ [salary, tax]`. They also express "orders"
  relations FDs cannot: `date ↦ year(date)`, `ts ↦ day_bucket(ts)`,
  `order_id ↦ order_date` for monotone surrogate keys, `salary ↦ tax`.
- Inference for ODs (and unidirectional ODs) is co-NP-complete (Szlichta,
  Godfrey, Gryz, Zuzarte, VLDB 2013); FD inference from unidirectional ODs
  is linear; sound and complete axiomatization for unidirectional ODs (6
  axioms; Szlichta et al. VLDB 2012); chase-style procedures exponential in
  the number of attributes; discovery is exponential in attributes, linear
  in tuples (set-based canonical ODs, VLDB 2017).

Engine use:

| Use | Reasoning |
|---|---|
| Sort elimination | input ordered on `X` (index scan, prior sort, merge join) and `X ↦ Y` ⇒ already ordered on `Y`; skip the sort |
| Interesting orders (Selinger) | reduce order requirements before costing: drop attributes functionally determined by a prefix (`ORDER BY a, b` with `a → b` ≡ `ORDER BY a`), drop constant-bound columns (`a = 5`), substitute equivalence-class members (Simmen, Shekita, Malkemus, SIGMOD 1996; Neumann & Moerkotte, ICDE 2004 for an efficient framework) |
| Monotone expression ordering | `ORDER BY year(d)` satisfied by an index on `d` (`d ↦ year(d)`, non-strict monotone); range predicates on `year(d)` rewritten into ranges on `d` (DB2 "predicate derivation and monotonicity", Malkemus et al., ICDE 2005) |
| Warehouse joins | ODs between surrogate keys and dates let a date range on a dimension become a key range on the fact table, eliminating the join |

Pitfalls: non-strict monotone functions (`year(d)`) give `d ↦ year(d)` but
not `year(d) ↦ d`; collation-dependent string order; `NULLS FIRST/LAST`
defaults differ across engines and directions (PostgreSQL/Oracle sort NULL
as largest, SQL Server/MySQL as smallest); mixed asc/desc; local-time
conversions with DST are not monotone in UTC; floating-point NaN placement.

---

## 9. Failure modes

- Join elimination with a nullable FK and no residual `IS NOT NULL`
  (returns rows the join would drop).
- Join elimination on a deferrable or `NOT VALID` FK; or after a
  constraint was disabled for bulk load and never revalidated.
- DISTINCT elimination via a nullable UNIQUE column.
- CHECK-derived filter dropping NULL rows.
- Key derivation through `UNION ALL` or through the null-supplying side of
  an outer join.
- Using informational keys in dedup-sensitive rewrites on data that
  actually violates them (results then differ between plans — a
  non-determinism users will report as a bug).
- Chasing cyclic FKs without a bound (optimizer hang).

## 10. Tests

- For each semantic rule, generate instances that satisfy the constraints
  and compare rewritten vs original (bags, with NULLs in nullable columns).
- Negative tests: violate each side condition (nullable FK, non-unique
  referenced column, deferred constraint inside a transaction with a
  temporary violation, collation mismatch) and assert the rule does **not**
  fire.
- Property derivation: on random plans, brute-force verify derived keys
  (no duplicate key values in output), FDs, and orders on random data.
- Implication: closure-based FD implication vs brute-force Armstrong
  derivation on small attribute sets; chase-based lossless-join test vs
  explicit join of projections on random instances.

---

Sources: EDBS entries Database Dependencies (p.945), FOL Modeling of
Integrity Constraints (Dependencies) (p.1501), Implication of Constraints
(p.1808), Chase (p.418), Equality-Generating Dependencies (p.1331),
Tuple-Generating Dependencies (p.4256), Functional Dependency (p.1555),
Armstrong Axioms (p.165), Multivalued Dependency (p.2447), Join Dependency
(p.2050), Key (p.2057), Order Dependency (p.2631), Query Processing in
Deductive Databases (p.3046), Relational Model (p.3149).
