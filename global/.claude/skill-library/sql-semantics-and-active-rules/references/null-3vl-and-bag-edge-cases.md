# NULLs, three-valued logic and bag semantics — the edge cases an engine must get right

Two deliberate departures from Codd's model define SQL's observable semantics:
a single untyped-in-spirit `NULL` marker evaluated under Kleene three-valued
logic (3VL), and relations as bags (multisets) rather than sets. Almost every
"wrong result" bug in a young engine is one of these two leaking through an
operator, a rewrite rule, or a vectorized kernel. This file states the rules
precisely, then lists what each rule obliges the planner and executor to do.

---

## 1. What a NULL means (and why SQL does not quite say)

Research on incomplete information distinguishes several null intentions —
value exists but unknown, attribute inapplicable, value withheld, no
information. The standard and every mainstream engine collapse these into one
marker `NULL`, with nullability declared per column.

The cleanest formal reading is **possible-worlds** semantics: each NULL stands
for some unknown domain value; an incomplete instance denotes the set of
complete instances obtained by substituting values; the **certain answer** to a
query is what holds in every world. SQL's 3VL is *not* certain-answer
semantics, and the gap is testable:

```
SELECT * FROM t WHERE a = 1 OR a <> 1      -- true in every world for every row
```

Under possible worlds every row qualifies; under SQL rows with `a IS NULL`
are dropped (`UNKNOWN OR UNKNOWN = UNKNOWN`). Vector A20 pins this down. SQL
evaluation can therefore *miss* certain answers, and once negation enters
(`NOT IN`, `EXCEPT`, `NOT EXISTS`) it can also *return* answers that are not
certain. The engine's job is to implement SQL's rules exactly, not to be
"smarter" — an optimizer that rewrites `a = 1 OR a <> 1` to `TRUE` is wrong.

> **Beyond EDBS:** Libkin's line of work (e.g., "SQL's three-valued logic and
> certain answers", ICDT 2015 / TODS 2016) characterises when SQL evaluation
> coincides with certain answers and proposes cheap approximation schemes. Useful
> background if you are building a "correct-by-construction" query language
> layer, irrelevant if you are implementing SQL.

## 2. Kleene 3VL — truth tables and predicates

```
AND | T  U  F        OR | T  U  F        NOT
 T  | T  U  F         T | T  T  T         T -> F
 U  | U  U  F         U | T  U  U         U -> U
 F  | F  F  F         F | T  U  F         F -> T
```

`F` dominates `AND`, `T` dominates `OR`. Hence `NULL AND FALSE = FALSE` and
`NULL OR TRUE = TRUE` (A2). Any kernel that "propagates NULL" through boolean
operators like it does through arithmetic is wrong.

Predicate behaviour with NULL operands:

| Construct | Result with a NULL operand | Notes / vector |
|---|---|---|
| `x = y`, `<`, `<>` … | UNKNOWN | A1 |
| `x IS NULL` / `IS NOT NULL` | always T/F | A4 |
| `x IS [NOT] DISTINCT FROM y` | always T/F; NULL not-distinct from NULL | A4, E6 |
| `p IS TRUE / IS FALSE / IS UNKNOWN` | always T/F | A18 |
| `x BETWEEN lo AND hi` | rewrite to `x>=lo AND x<=hi`, then 3VL: may be F even with a NULL bound | A5 |
| `x LIKE p` | UNKNOWN | A6 |
| `x IN (list)` | T if some element equals; else U if any NULL on either side; else F | B1 |
| `x IN (empty subquery)` | F even if `x` is NULL | B2 |
| `x NOT IN (…)` | `NOT (x IN …)` — U as soon as the list holds a NULL and no match | B1, B4 |
| `x θ ALL (S)` | T if S empty; F if some comparison F; else U if any U | B7, B8 |
| `x θ ANY (S)` | F if S empty; T if some comparison T; else U if any U | B7, B8 |
| `EXISTS (S)` | never U; a row of all NULLs counts | A19 |
| `CASE x WHEN NULL …` | simple CASE uses `=`, never matches NULL | A7 |
| `CASE WHEN p …` | U falls through to the next WHEN / ELSE | A14 |
| `COALESCE`, `NULLIF` | `NULLIF(a,b)` = `CASE WHEN a=b THEN NULL ELSE a END` | A8 |
| `'abc' \|\| NULL` | NULL (Oracle: `''` is NULL, so `'abc' \|\| ''`='abc' and `'' IS NULL` is TRUE) | A9, A15 |
| arithmetic | NULL; but `1/0` is an exception (SQLSTATE 22012), not NULL | A16 |

Row-value predicates follow the standard's pairwise definitions:
`(a1,a2) = (b1,b2)` is `a1=b1 AND a2=b2`, so `(1,NULL)=(2,2)` is F, not U.
`<` on rows is lexicographic and stops at the first decided column, so
`(1,NULL) < (2,NULL)` is T. `ROW(…) IS NULL` is T iff *all* fields are NULL and
`ROW(…) IS NOT NULL` is T iff *no* field is NULL — so `ROW(1,NULL)` is neither
(A12, A13). DuckDB 1.1 compares STRUCT-typed row literals treating NULL as an
ordinary value — a documented deviation (A12 is `skipif duckdb`).

**Clause filters accept only TRUE**: `WHERE`, `HAVING`, `ON`, `QUALIFY`,
`FILTER (WHERE …)`, trigger `WHEN`. **CHECK constraints reject only FALSE**:
UNKNOWN passes (A17). Getting this asymmetry wrong in either direction is a
classic bug — a CHECK implemented by reusing the WHERE filter kernel rejects
NULLs.

## 3. Equality versus "not distinct": which operators use which

SQL uses two different notions of sameness. Implement both, and make each
operator choose deliberately.

| Uses `=` (NULL never matches) | Uses NOT DISTINCT (NULLs collapse together) |
|---|---|
| `WHERE`/`ON` comparisons, equi-join keys | `GROUP BY` keys (C6) |
| `IN`, `ANY`, `ALL` | `DISTINCT`, `COUNT(DISTINCT …)` (NULL then ignored by COUNT) |
| simple `CASE` | `UNION`, `INTERSECT`, `EXCEPT` and their `ALL` forms (D3) |
| `NULLIF` | `PARTITION BY`, window peer groups (G13) |
| referential check (MATCH SIMPLE skips NULL rows) | `ORDER BY` placement (all NULLs adjacent) |
| `UNIQUE` constraints — NULLs are distinct by default (H7) | `UNIQUE NULLS NOT DISTINCT` (SQL:2023; PG15+) |

Engine consequences:
- **Hash tables need two equality modes.** A hash join on `a=b` must drop
  NULL keys on both build and probe (or never match them); a hash aggregate
  must place all NULL keys in one bucket. Use one hash function, but either
  filter NULLs before the join or carry a "null-equal" flag in the key
  comparator. A shared `KeyEq` that treats NULL=NULL silently turns joins into
  NULL-matching joins (E6 catches it).
- **`IS NOT DISTINCT FROM` joins** must still be hash/merge-joinable; do not
  fall back to nested loops. Encode NULL as a distinguished key value in the
  hash/sort key.
- **Set operators** are implemented via grouping/hashing, so they inherit
  NOT DISTINCT. `SELECT a FROM t INTERSECT SELECT x FROM s` returns a NULL row
  when both contain NULL. Rewriting INTERSECT to a semi-join on `=` is wrong
  unless both sides are NULL-free; rewrite to a semi-join on
  `IS NOT DISTINCT FROM`.
- **Unique indexes** default to allowing many NULL keys. A B-tree uniqueness
  check must skip the conflict test when any key column is NULL (unless the
  index is NULLS NOT DISTINCT). SQL Server's unique constraint admits a single
  NULL — a dialect switch, not a standard behaviour.

## 4. NOT IN and the null-aware anti-join

`x NOT IN (SELECT y FROM S)` is not `NOT EXISTS (SELECT 1 FROM S WHERE y = x)`:

| Inner `S` | Outer `x` non-NULL | Outer `x` NULL |
|---|---|---|
| empty | qualifies | qualifies |
| contains `x` | rejected | rejected (U) |
| no `x`, contains NULL | rejected (U) | rejected (U) |
| no `x`, NULL-free | qualifies | rejected (U) |

`NOT EXISTS` qualifies in every "no match" cell (B5 vs B4). A correct
**null-aware anti-join** (NAAJ):

```
build side: hash S on y; record inner_has_null, inner_count
probe row x:
  if inner_count == 0:           emit x
  elif x is NULL:                drop            -- U
  elif inner_has_null:           drop            -- U, unless match (also drop)
  elif probe(x) finds a match:   drop
  else:                          emit x
multi-column (x1,x2) NOT IN (SELECT y1,y2 …): a NULL in some column only
  needs to "possibly match" rows agreeing on the non-NULL columns, so the
  per-row check becomes a set of partial-key probes — or fall back to a
  nested-loop with 3VL evaluation.
```

The common optimizer shortcut — rewrite `NOT IN` to an anti-join when both
`x` and `y` are provably NOT NULL (declared NOT NULL, or filtered by a
null-rejecting predicate) — is legal and important. Prove nullability from the
catalog plus predicates; do not assume it.

> **Beyond EDBS:** Oracle introduced a "null-aware anti join" access path in
> 11g; PostgreSQL still plans unprovable `NOT IN` as a hashed/plain SubPlan
> filter rather than an anti-join, which is why `NOT EXISTS` is the usual
> performance advice there.

## 5. Aggregates, grouping and empty input

| Expression | Over empty input | Over all-NULL input |
|---|---|---|
| `COUNT(*)` | 0 | number of rows |
| `COUNT(e)` | 0 | 0 |
| `SUM`, `AVG`, `MIN`, `MAX` | NULL | NULL (C7) |
| `COUNT(DISTINCT e)` | 0 | 0 |
| `BOOL_AND/EVERY`, `ANY/SOME` | NULL | NULL |

- **Scalar aggregation** (no GROUP BY) over empty input returns **exactly one
  row** (C2). **Grouped aggregation** returns **zero rows** (C4).
  `GROUP BY ()` is the grand-total grouping set and returns one row even for
  empty input (C5). A hash aggregate that "emits one row per bucket" breaks
  C2; a scalar aggregate that emits nothing when its child is empty is the same
  bug inverted. Plan scalar and grouped aggregation as distinct operators or
  carry an `is_scalar` flag.
- `HAVING` without `GROUP BY` makes the whole input one group (C9).
- **Aggregates ignore NULL inputs** (except `COUNT(*)`). `AVG = SUM/COUNT(e)`
  must divide by the non-NULL count.
- Exact numeric `SUM` must not silently become floating point (C14); its
  overflow raises SQLSTATE 22003. Result scale of `AVG` over integers is
  implementation-defined (PG returns NUMERIC, DuckDB DOUBLE).
- `FILTER (WHERE p)` applies 3VL: only TRUE rows feed the aggregate (C10).
- **ROLLUP/CUBE/GROUPING SETS** produce super-aggregate rows whose rolled-up
  columns are NULL; `GROUPING(col)` returns 1 for those, 0 for a genuine data
  NULL group (C13). An engine that encodes "rolled up" as a NULL value without
  a separate grouping-id bit cannot implement `GROUPING()`.
- Scalar subquery: zero rows → NULL (C11); more than one row → cardinality
  violation, SQLSTATE 21000 (C12). Engines that silently take the first row
  (older DuckDB, MySQL in some modes) diverge.
- Functional dependence: SQL:1999 lets the select list reference columns
  functionally determined by the grouping columns (PG: when grouping by a
  primary key). Without that analysis, reject non-grouped columns (K4).

## 6. Outer joins and NULL padding

Padding NULLs are indistinguishable from stored NULLs (E7) — downstream
operators cannot tell them apart, so the planner must reason about them.

1. **ON versus WHERE.** For `L LEFT JOIN R ON p`, predicates in `p` never
   remove L rows; they only decide which R rows pair up (E2, E4). The same
   predicate in `WHERE` filters after padding (E3).
2. **Null-rejecting predicates simplify outer joins.** If a predicate above
   the join evaluates to F/U whenever all R columns are NULL (e.g. `r.w = 'x'`,
   `r.id > 0`, `r.id IS NOT NULL`), the LEFT JOIN can become an INNER JOIN.
   `COALESCE(r.w,'x')='x'` and `r.w IS NULL` are **not** null-rejecting. The
   test: substitute NULL for every R column and constant-fold; if the result
   is not TRUE, the predicate rejects padded rows.
3. **Aggregates over padded rows**: `COUNT(*)` counts the padded row,
   `COUNT(r.col)` does not (E5). Decorrelating a correlated `COUNT` subquery into
   an outer join + group-by must use `COUNT(r.key)`, else empty groups report
   1 — the classic "COUNT bug" of early decorrelation (Kim 1982 / Ganski & Wong
   1987).
4. **Reordering**: outer joins are not freely associative/commutative with
   inner joins; legal reorderings need the null-rejection analysis above
   (Galindo-Legaria & Rosenthal, TODS 1997).
5. **Antijoin padding**: `L LEFT JOIN R … WHERE r.key IS NULL` emulates
   `NOT EXISTS` only when `r.key` is non-nullable in R.

## 7. ORDER BY and NULLs

Whether NULLs sort before or after non-NULL values is implementation-defined
unless `NULLS FIRST/LAST` is written. PostgreSQL and Oracle treat NULL as
larger than every value (last in ASC, first in DESC); SQL Server, MySQL and
SQLite treat it as smaller; DuckDB places NULLs last in both directions by
default (F1). Engines must: (a) support the explicit clause, (b) make the
default a single documented rule, (c) make index order, merge-join order and
window ordering agree with it — a merge join whose two inputs come from
indexes with different null placement silently drops or duplicates rows.

---

## 8. Bag semantics — definitions

A bag relation of arity k maps each k-tuple to a natural-number
multiplicity (finite support). A set is the special case with multiplicities
in {0,1}. Operators act on multiplicities:

| Operator | Multiplicity of t in the result | SQL |
|---|---|---|
| σ_P R | R(t) if P(t) is TRUE, else 0 | `WHERE` |
| π_V R | Σ R(t′) over t′ with π_V(t′) = t | `SELECT` list without DISTINCT |
| R × S | R(t1)·S(t2) | `FROM R, S`, joins |
| R ⊎ S | R(t) + S(t) | `UNION ALL` (D4) |
| R ∩ S | min(R(t), S(t)) | `INTERSECT ALL` (D5) |
| R − S | max(R(t) − S(t), 0) (monus) | `EXCEPT ALL` (D5) |
| δ R | min(R(t), 1) | `DISTINCT`; set forms of UNION/INTERSECT/EXCEPT |

`UNION` (set form) is δ(R ⊎ S). `INTERSECT`/`EXCEPT` (set forms) equal
δR ∩ δS and δR − δS — duplicate elimination before the operation is the only
correct reading for `EXCEPT` (D6: `{1,1,2} EXCEPT {2}` gives one row, not two).
Precedence: `INTERSECT` binds tighter than `UNION`/`EXCEPT` (D9).

**Bag-set semantics**: base tables are sets (e.g. have a key) but views and
answers may hold duplicates. This is the realistic model for an optimizer
reasoning about keyed tables.

## 9. Algebraic identities: which survive

| Identity | Sets | Bags | Note |
|---|---|---|---|
| R ⋈ R = R (idempotent self-join) | yes | **no** | multiplicities square (D8) |
| R ∩ (S ∪ T) = (R∩S) ∪ (R∩T) | yes | **no** with ⊎ | D7: 1 row vs 2 rows |
| R ∪ R = R | yes | **no** with ⊎ | |
| σ_P(R ⊎ S) = σ_P R ⊎ σ_P S | yes | yes | |
| σ_P(R − S) = σ_P R − σ_P S | yes | yes | per-tuple arithmetic |
| σ_{P∧Q} = σ_P σ_Q | yes | yes | |
| π(R ⊎ S) = πR ⊎ πS | yes | yes | |
| π(R − S) = πR − πS | **no** | **no** | |
| δ(R ⋈ S) = δR ⋈ δS | yes | yes | lets DISTINCT be pushed below joins |
| δ π_K R = π_K R when K ⊇ key(R) | — | yes | DISTINCT elimination via keys |
| `x IN (SELECT y …)` = join | **no** | **no** | needs semi-join or δ on the inner (B9) |
| conjunctive-query minimization (drop redundant atoms) | yes | **no** | every atom contributes multiplicity |

Engine rules that follow:
- **Never apply set-semantics rewrite rules without checking duplicates.**
  Self-join elimination, join elimination on FK→PK, and subquery-to-join
  flattening are legal only with uniqueness proofs (key on the eliminated or
  inner side) or under a DISTINCT/EXISTS context where multiplicity is
  irrelevant.
- **Track a "duplicate-insensitive" property** top-down in the planner
  (true below DISTINCT, EXISTS, IN, set-form set operators, MIN/MAX, and
  semi/anti joins). Under it, set-semantics rules become legal.
- **Uniqueness inference** (keys flowing up through joins, group-bys and
  filters with equality to constants) drives DISTINCT removal, semi-join →
  join conversion, and group-by elimination.
- Recursive queries: under bag semantics a derivation can be repeated
  unboundedly (infinite multiplicity); SQL's `WITH RECURSIVE … UNION` uses set
  union per iteration to terminate (K6), while `UNION ALL` relies on the query
  converging by data.

## 10. Containment and equivalence under bags (what the optimizer can decide)

| Problem | Set semantics | Bag semantics |
|---|---|---|
| CQ equivalence | NP-complete | same as isomorphism (Chaudhuri & Vardi, PODS 1993) |
| UCQ equivalence | NP-complete | isomorphism (Cohen, Nutt & Serebrenik 1999) |
| CQ containment | NP-complete | Π₂ᵖ-hard; decidability open (as of the entry) |
| UCQ containment | NP-complete | **undecidable** (Ioannidis & Ramakrishnan, TODS 1995) |
| CQ≠ containment | Π₂ᵖ-complete | undecidable (Jayram, Kolaitis & Vee, PODS 2006) |
| CQ≠/UCQ≠ equivalence | — | in PSPACE |
| Bag-set equivalence of irredundant CQs | — | isomorphism (a Lovász homomorphism-count theorem) |

Practical reading: view matching and rewrite verification under bag semantics
should use **structural (isomorphism-based) matching plus key reasoning**, not a
containment test. "Combined semantics" (Cohen, PODS 2006) models DISTINCT at
intermediate nodes — exactly what a planner with a duplicate-insensitive flag
does.

> **Beyond EDBS:** provenance semirings (Green, Karvounarakis & Tannen, PODS
> 2007) generalise bag semantics: annotate tuples with elements of a commutative
> semiring (ℕ for bags, Boolean for sets, polynomials for provenance). The same
> annotated-relation algebra underlies counting-based incremental view
> maintenance (see `materialized-views-ivm`) and factorised/semiring
> aggregation engines.

## 11. Implementation checklist

1. Representation: a validity bitmap per vector (Arrow-style) plus Kleene
   kernels for AND/OR/NOT that consult both value and validity; never
   materialise UNKNOWN as FALSE before the filter boundary.
2. Short-circuit evaluation of `AND`/`OR` is an optimisation only: the SQL
   result must equal full Kleene evaluation, and errors in skipped branches
   (e.g. `x <> 0 AND 1/x > 1`) are not guaranteed to be avoided by the standard.
   Document your evaluation-order guarantee (`CASE` is the only portable guard).
3. One function decides "null-rejecting(predicate, columns)" by constant
   folding with NULL substitution; reuse it for outer-join simplification,
   NOT IN → anti-join, and IS NOT NULL inference.
4. Hash/sort key encoding has an explicit NULL tag; comparators take an
   `nulls_equal: bool` and a `nulls_first: bool`.
5. Aggregate states distinguish "no input seen" from "zero"; `SUM` returns
   NULL when no non-NULL input was seen.
6. Keep `CHECK` evaluation separate from filter evaluation (reject only F).

## 12. Tests and oracles

- Run `references/semantic-test-vectors.slt` groups A–F on every build.
- **Differential testing** against PostgreSQL / SQLite / DuckDB with a
  dialect allow-list (null ordering, integer division, 1/0).
- **Ternary Logic Partitioning** (Rigger & Su, OOPSLA 2020, SQLancer): for a
  random predicate p, `Q` must equal `Q WHERE p ⊎ Q WHERE NOT p ⊎ Q WHERE p IS
  NULL`. This metamorphic oracle catches exactly the 3VL and outer-join bugs
  in this file; **NoREC** (Rigger & Su, ESEC/FSE 2020) compares an optimised
  `WHERE p` against an unoptimisable `SELECT p` count.
- Property: any rewrite rule must be validated with randomly generated bag
  instances containing duplicates *and* NULLs; set-only test data hides most
  bag bugs.

---

Sources: Bag Semantics (p.252); Null Values (p.2522); SQL (p.3666) — nulls,
duplicates and criticisms sections; Key (p.2057). Beyond-EDBS items are flagged
inline.
