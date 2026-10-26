# NULLs, incomplete information, certain answers, and inconsistent data

Read this when touching anything NULL-related in the binder, rewriter, or
executor (3VL predicates, outer joins, NOT IN, aggregates, hashing/grouping of
NULL), when someone asks whether SQL's answer is "correct" on incomplete
data, or when the engine must answer queries over data that violates its
declared keys (unenforced constraints, integration, dedup).

---

## 1. Kinds of missing information

- **Unknown but existing** (the value exists, we do not know it) — the
  theory below.
- **Inapplicable** (no value can exist: spouse of an unmarried person).
- **No information** (either of the above).

SQL has a single `NULL` for all three, and its semantics (3VL) matches none
of them exactly. Theory models unknown values with variables ("marked" or
"labeled" nulls): Reiter's proof-theoretic reading treats a tuple `(a, ⊥)` as
the sentence `∃x R(a, x)`.

---

## 2. Possible worlds, certain and possible answers

An incomplete database is a finite representation `T` (a *table*) plus an
interpretation `Rep(T)`: the set of complete databases it may stand for. A
**valuation** `v` maps nulls to constants (identity on constants).

- Open-world assumption (OWA): `Rep(T) = { I | v(T) ⊆ I for some v }` —
  missing facts are unknown, not false. Nothing is certainly false, so
  negation is meaningless under OWA.
- Closed-world assumption (CWA): `Rep_cwa(T) = { v(T) | v a valuation }` —
  facts not derivable from `T` are false (Reiter 1977). Datalog's
  minimal-model semantics is a CWA.

For a query `Q`:

- **certain answers** `cert(Q,T) = ∩_{I ∈ Rep(T)} Q(I)` — true in every world;
- **possible answers** `poss(Q,T) = ∪_{I ∈ Rep(T)} Q(I)` — true in some
  world (only interesting under CWA).

**Complexity** (data complexity; Abiteboul, Kanellakis, Grahne, TCS 1991):

| Representation | Query class | `cert` | `poss` |
|---|---|---|---|
| complete DB | FO, Datalog | PTIME | PTIME |
| Codd/naive tables | positive (UCQ, positive Datalog), no `≠`, no `∨` in conditions | PTIME (naive evaluation) | PTIME |
| Codd/naive tables | existential FO with `≠` or disjunction | coNP-complete | NP-complete |
| tables, OWA | full FO | undecidable | — |
| c-tables | identity query | coNP-complete | NP-complete |
| views as CQs (data integration), OWA | Datalog / existential FO queries | PTIME | |
| same, CWA | | coNP-complete | |
| same, query with `≠` | | coNP-complete even under OWA | |
| negation in query or views, or recursive views under OWA | | undecidable | |

The boundary is always the same three knobs: negation (including `≠` and the
negation implicit in CWA), disjunction, and recursion in the mapping.

---

## 3. Representation systems (Imielinski & Lipski, JACM 1984)

Goal: compute a table `q̂(T)` representing the answers, such that
`Rep(q̂(T)) ≈ q(Rep(T))` for the query language at hand — exact equality is
too strong under OWA, so require equal certain answers for every follow-up
query in the language (`≡_Q`). For positive queries this coincides with
"same minimal worlds" (coinitiality); for full RA it means equality.

| Table class | Entries | Conditions | Supports (as a representation system) |
|---|---|---|---|
| **Codd table** | one symbol `⊥`, each occurrence independent | none | only `σ` (incl. `≠`) and `π` — any join or union breaks it |
| **Naive table** (v-table, marked nulls) | named nulls `x, y, …`, may repeat (also across tables) | none | positive RA (`σ` with `=`, `π`, `⋈`, `∪`) and positive Datalog |
| **Conditional table** (c-table) | named nulls | per-tuple Boolean condition over `x = y`, `x = c`, `≠` | positive RA with `≠` under OWA; **full RA under CWA** (strong: `Rep(q̂(T)) = q(Rep(T))`); positive recursion |

c-tables are *closed* under RA: the extended operators propagate conditions
(selection conjoins `t.A = a` to the tuple's condition; join conjoins both
conditions and the join equality; difference conjoins "differs from every
tuple of the subtrahend"). The price: satisfiability of a c-table is
NP-complete, membership in the certain answer coNP-complete, containment of
c-tables Π2p-complete. They are the natural representation for the possible
worlds of materialized views and of view updates (a deletion through a join
view = a c-table with a fresh variable choosing which base tuple goes).

> **Beyond EDBS:** The semiring/provenance framework (Green, Karvounarakis,
> Tannen, PODS 2007) generalizes c-tables: condition annotations form a
> semiring, and probabilistic databases (e.g. MayBMS, Trio/ULDBs) are
> c-tables with probabilities on the variables.

### 3.1 Naive evaluation (the algorithm that matters)

```
naive_eval(Q, T):
   treat every marked null as a fresh constant, distinct from every real
   constant and from every other null; equal only to itself
   evaluate Q with ordinary RA/Datalog machinery
certain(Q, T) = { t ∈ naive_eval(Q, T) | t contains no nulls }
```

Correct (computes certain answers) for UCQs and positive Datalog on naive
tables — same complexity as complete data. Example: `T = {(a, x, c)}` over
`(A,B,C)`. `π_{AB}` and `π_{BC}` have no certain answers on their own, but
`π_{AC}(π_{AB} ⋈ π_{BC})` evaluates naively to `{(a, c)}`, which *is* certain,
because the two `x`'s are the same null. Lesson: when an answer is stored
as a view for further querying, keep the null-containing tuples (the "exact
answer"); certain answers alone are not compositional.

---

## 4. SQL's NULL semantics

**Three-valued logic (Kleene):** comparisons with a NULL operand yield
UNKNOWN. `NOT U = U`; `F AND U = F`; `T AND U = U`; `T OR U = T`;
`F OR U = U`.

Where each truth value goes:

| Context | Keeps |
|---|---|
| `WHERE`, `ON`, `HAVING`, `CASE WHEN`, `FILTER` | only TRUE |
| `CHECK` constraint | everything except FALSE (UNKNOWN passes) |
| FK `MATCH SIMPLE` (default) | row with any NULL FK column is not checked |
| `UNIQUE` | NULLs are distinct (multiple NULL rows allowed); PostgreSQL 15 adds `NULLS NOT DISTINCT`; some engines differ |
| `GROUP BY`, `DISTINCT`, `UNION/INTERSECT/EXCEPT`, `PARTITION BY` | NULLs are *not distinct* (grouped together) |
| `IS [NOT] DISTINCT FROM` | two-valued, NULL-equal comparison |
| Aggregates | ignore NULL inputs, except `COUNT(*)`; on empty or all-NULL input `SUM/AVG/MIN/MAX` return NULL, `COUNT` returns 0 |
| `ORDER BY` | NULL position implementation-defined unless `NULLS FIRST/LAST` |
| Row comparison | `(1, NULL) = (1, 2)` is UNKNOWN; `(1, NULL) = (2, 2)` is FALSE |

Executor consequence: the engine needs **two equality semantics** for the
same type — predicate equality (NULL never matches: hash-join build can skip
NULL keys) and grouping equality (NULL matches NULL: hash aggregation,
set operations, `DISTINCT`, and null-aware antijoin must hash NULL to a real
bucket). Mixing them up is a classic bug class (e.g. implementing
`INTERSECT` with a hash join).

---

## 5. Why SQL's answers are not certain answers

SQL evaluates with one unmarked NULL per occurrence (Codd semantics) and
3VL. Relative to certain answers it errs in both directions:

- **False negatives** (misses certain answers): `SELECT * FROM R WHERE a = a`
  drops rows with `a` NULL, though `a = a` holds in every world.
  `WHERE a = 1 OR a <> 1` likewise. Every tautology that 3VL fails to see.
- **False positives** (returns non-certain answers) — only with negation:
  ```sql
  -- R(a) = {1}, S(a) = {NULL}
  SELECT a FROM R EXCEPT SELECT a FROM S;          -- returns 1
  SELECT a FROM R r WHERE NOT EXISTS (SELECT * FROM S s WHERE s.a = r.a); -- returns 1
  -- yet in the world where S's NULL is 1, the answer is empty: 1 is not certain.
  SELECT a FROM R WHERE a NOT IN (SELECT a FROM S); -- returns nothing (UNKNOWN)
  ```
  The three "equivalent" anti-join formulations give different answers;
  only `NOT IN` happens to be cautious here, and it errs the other way
  elsewhere.

What holds (Libkin and coauthors): for positive queries (selection with
equality conjunctions/disjunctions, projection, join, union — no `NOT`, `≠`,
`EXCEPT`, `NOT EXISTS`, `NOT IN`, `ALL`), every NULL-free tuple SQL returns
is a certain answer: SQL is **sound but incomplete** there. Negation is
where wrong (non-certain) answers come from.

> **Beyond EDBS:** Libkin, "SQL's three-valued logic and certain answers"
> (ICDT 2015 / TODS 2016), and Guagliardo & Libkin, "Making SQL queries
> correct on incomplete databases" (PODS 2016), give translations
> `Q ↦ (Q⁺, Q?)` that guarantee no false positives with modest overhead on
> TPC-H-style queries; Guagliardo & Libkin (VLDB 2017) formalize SQL's
> actual semantics including NULL and bags, which is a useful reference
> model for a test oracle.

---

## 6. NULL-sensitive rewrite laws (optimizer checklist)

| Rewrite | Legal? |
|---|---|
| `NOT (a = b)` → `a <> b` | yes (both UNKNOWN on NULL) |
| De Morgan, double negation, distributivity of AND/OR | yes in Kleene 3VL |
| `p OR NOT p` → TRUE; `p AND NOT p` → FALSE | **no** (UNKNOWN on NULL) |
| `x = x` → TRUE | **no**; → `x IS NOT NULL` (in WHERE) |
| `x * 0` → `0`, `x - x` → `0` | **no** (NULL); also wrong for NaN/infinity |
| `R − σ_p(R)` → `σ_{NOT p}(R)` | **no**: rows with `p` UNKNOWN are in the left side only; correct: `σ_{p IS NOT TRUE}(R)` |
| `σ_p(R) ∪ σ_{NOT p}(R)` → `R` | **no**: misses UNKNOWN rows (this is exactly SQLancer's TLP oracle) |
| `x NOT IN (subq)` → antijoin `x = y` | only if `x`, `y` NOT NULL; else null-aware antijoin (`algebra…` §6.2) |
| `NOT EXISTS (… s.y = r.x)` → antijoin | yes |
| `x > ALL(subq)` → `x > MAX(…)` | **no** (empty set, NULL members) |
| Outer join → inner join under a WHERE predicate | only if the predicate is null-rejecting on the null-supplying side |
| `LOJ … WHERE s.col IS NULL` → antijoin | only if `s.col` is NOT NULL in `S` or is the equi-join column |
| `COUNT(x)` → `COUNT(*)` | only if `x` NOT NULL |
| `SUM(x)` over empty/all-NULL → 0 | **no** (NULL) |
| `a = b AND b = c` → add `a = c` | yes (TRUE equality implies non-NULL) |
| `CHECK (p)` ⇒ add filter `p` | only `p IS NOT FALSE`, or `p` when its columns are NOT NULL |
| Push `IS NULL` filter on a padded column below the outer join | **no** (changes meaning: padded vs stored NULL) |
| `COALESCE(a, b) = c` → index on `a` | not without a disjunctive plan |
| `GROUP BY` / `DISTINCT` implemented via predicate-equality hash | **no**: NULLs must group together |
| Hash-partitioning a join on a nullable key | fine for inner/semi joins (NULLs never match: may drop or route anywhere); for outer/anti joins the NULL-key rows must still be emitted by their preserving side |

---

## 7. Inconsistent databases and consistent query answering (CQA)

A database is **inconsistent** w.r.t. `Σ` if it violates `Σ`. Causes that
matter for engines: constraints declared but not enforced (performance,
bulk loads, informational keys in warehouses and lakehouses), integration
of individually-consistent sources (two systems reuse the same student
number), legacy data under new constraints.

**Repairs** (Arenas, Bertossi, Chomicki, PODS 1999): a repair of `D` is a
consistent `D'` such that no consistent `D''` has a strictly smaller
symmetric difference `D Δ D''` ⊂ `D Δ D'` (set inclusion). For key
constraints, repairs keep exactly one tuple from each group of key-equal
tuples (deletions only). For INDs, repairs may delete or insert (insertions
need NULLs/fresh values — and then the null semantics of constraint
satisfaction matters).

**Consistent answers** = answers true in every repair = certain answers over
the possible worlds "repairs". Example: `Students(id, name)` with key `id`,
containing `(101, 'john')`, `(101, 'joe')`, `(104, 'claire')`:

- `Q(x,y) :- Students(x,y)` → consistent answers `{(104,'claire')}`.
- `Q(x) :- ∃y Students(x,y)` → `{101, 104}` (every repair has some 101 row).

**Computing them.** Rewrite `Q` to `Q'` evaluated on the inconsistent
database: for the first query, `Q'(x,y) = Students(x,y) ∧ ¬∃z
(Students(x,z) ∧ z ≠ y)` — keep tuples whose key group is a singleton —
polynomial and SQL-expressible. In general first-order rewriting may not
exist; CQA can be coNP-complete for simple CQs and key constraints, and
rewritings may need disjunctive/stable-model Datalog.

> **Beyond EDBS:** For self-join-free CQs under primary keys, CQA is in FO
> (SQL-rewritable) iff the query's *attack graph* is acyclic (Wijsen, TODS
> 2012), and otherwise L-complete or coNP-complete — a trichotomy (Koutris &
> Wijsen, PODS 2015 / TODS 2017). Fuxman & Miller (ICDT 2005; ConQuer,
> SIGMOD 2005) gave the first practical rewriting class (`C_forest`).

Engine relevance even without a CQA feature: if the optimizer trusts an
unenforced key that the data violates, different plans (with and without
join/DISTINCT elimination) return different answers. Either refuse to use
informational constraints in multiplicity-changing rewrites, or document
that results are only guaranteed on consistent data.

---

## 8. Tests

- **Possible-worlds oracle**: for tiny instances with marked nulls over a
  small domain (active domain plus `k` fresh constants suffices for
  generic queries), enumerate valuations, evaluate on each world,
  intersect. Compare against naive evaluation for UCQs (must match) and
  against SQL evaluation (assert soundness for positive queries).
- **3VL partitioning (TLP)**: for random predicates `p`, assert
  `Q = Q WHERE p ⊎ Q WHERE NOT p ⊎ Q WHERE p IS NULL` (bags), and the
  analogous aggregate decompositions (Rigger & Su, OOPSLA 2020). NoREC
  (Rigger & Su, ESEC/FSE 2020): compare an optimized `WHERE p` against an
  unoptimizable `SUM(CASE WHEN p THEN 1 ELSE 0 END)`.
- Golden tests for every row of the §6 table, each with a NULL-bearing and an
  empty-input instance.
- Executor: hash join vs nested loop vs merge join with NULL keys for every
  join type (inner, left, full, semi, anti, null-aware anti, mark).
- CQA: repair enumeration oracle on small key-violating instances vs the
  rewritten query.

---

Sources: EDBS entries Incomplete Information (p.1819), Certain (and Possible)
Answers (p.408), Naive Tables (p.2459), Conditional Tables (p.578), Null
Values (p.2522), Inconsistent Databases (p.1825), Consistent Query Answering
(p.584), Join (p.2049), Relational Model (p.3149), Chase (p.418).
