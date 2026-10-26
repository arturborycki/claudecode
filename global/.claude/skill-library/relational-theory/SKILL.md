---
name: relational-theory
description: "Use when correctness of a query rewrite, plan property, or SQL semantic decision depends on relational theory: algebraic equivalences under set vs bag semantics, conjunctive-query containment and minimization, Datalog/recursive CTE evaluation, dependencies and the chase, keys/FDs/order dependencies, NULL and three-valued logic, certain answers, consistent query answering. Triggers on relational algebra, relational calculus, domain independence, bag semantics, UNION ALL vs UNION, conjunctive query, homomorphism, query containment, query minimization, Datalog, semi-naive, magic sets, stratified negation, WITH RECURSIVE, functional dependency, chase, join elimination, foreign key, DISTINCT elimination, order dependency, sort elimination, BCNF, NULL, 3VL, NOT IN, COUNT bug, decorrelation, outer join simplification, certain answers. Apply even when phrased as 'is this rewrite safe', 'why do these two plans return different rows', or 'can we drop this join'."
---

# Relational Theory for Engine Builders

This skill owns the correctness theory beneath the optimizer and binder:
which transformations are equivalences under which semantics (set, bag,
bag-set, 3VL) and constraints. Core idea: **every rewrite is a theorem with
side conditions** — duplicates, NULLs, empty inputs and constraint trust are
where engines break, and each has a precise legality criterion.

## Mental model

- **Three semantics, one algebra.** Theory is usually stated for sets; SQL
  executes bags (multiplicities), and most base tables are sets (have keys),
  giving *bag-set* semantics. Positive RA is a semiring computation:
  identities that use only commutativity/associativity/distributivity hold
  for sets and bags; identities that need idempotence (`R ∪ R = R`,
  `R ⋈ R = R`, core minimization) hold only for sets.
- **Queries are patterns; containment is homomorphism.** A conjunctive query
  (SPJ block) is a small relational structure; `Q1 ⊑ Q2` iff `Q2` maps
  homomorphically onto `Q1` (Chandra–Merlin). Decidable (NP) for CQs/UCQs,
  Π2p with comparisons, undecidable for full RA and Datalog, and under bags
  equivalence collapses to isomorphism.
- **Constraints are first-order sentences (tgds/egds); the chase applies
  them to a query.** Containment under constraints = chase, then
  homomorphism. Join/DISTINCT/GROUP BY elimination are bounded chase steps
  plus a multiplicity argument from a key.
- **Recursion is a least fixpoint.** FO (= RA = SQL without recursion, even
  with aggregates) cannot express transitive closure; `WITH RECURSIVE` is
  linear Datalog evaluated semi-naively; negation and aggregation must be
  stratified.
- **NULL is not a value and SQL is not certain-answer semantics.** SQL's
  3VL is sound for positive queries but produces non-certain answers under
  negation and misses tautologies; the executor needs two equalities
  (predicate vs grouping).

## Core invariants

1. A rewrite preserves the output **multiset** of rows (bag equality), the
   output schema, and nullability — unless the consuming context is proven
   duplicate-insensitive (`DISTINCT`, semijoin/`EXISTS`/`IN` side, `MIN`,
   `MAX`, `COUNT DISTINCT`, distinct set ops).
2. Set-only laws (idempotence, absorption, `σ_{p∨q} = σ_p ∪ σ_q`,
   `∩` over `∪` distributivity, CQ minimization, join→semijoin without a
   key) never fire outside a duplicate-insensitive context.
3. A rule that relies on a constraint checks that the constraint is
   enforced at statement time (validated, not deferrable, not
   informational) or is explicitly marked trusted/RELY.
4. Join elimination via FK requires: FK covering exactly the join
   equality, FK columns NOT NULL (or a residual `IS NOT NULL`), referenced
   side unique (bag contexts), no other use of the eliminated table, same
   equality/collation.
5. DISTINCT/GROUP BY elimination uses only NOT NULL keys (nullable UNIQUE
   is a lax key: DISTINCT groups NULLs together).
6. Moved predicates keep their three-valued result; null-rejection is
   derived (strictness analysis), and outer→inner conversion needs a
   null-rejecting predicate on the null-supplying side.
7. Scalar→grouped aggregation rewrites preserve the empty-input value
   (COUNT = 0, others NULL) — the COUNT-bug invariant.
8. `NOT IN` becomes a plain antijoin only when both sides are NOT NULL;
   otherwise null-aware antijoin or mark join.
9. Recursive CTE filters are pushed into the anchor only on invariant
   columns; negation/aggregation over the recursive reference is rejected
   (unstratified).
10. Derived keys/FDs/orders attached to plan nodes are sound: brute-force
    verification on random data never finds a violation.
11. Containment/implication checkers are sound; on timeout or outside the
    implemented fragment they answer "unknown → do not rewrite".

## Design space & trade-offs

| Decision | Option | When it wins | Cost / risk |
|---|---|---|---|
| Semantics tracking | per-node "duplicate-insensitive" + "proven set" flags | always | needs top-down propagation pass; omission = silent multiplicity bugs |
| Equivalence reasoning | per-rule proofs (law catalog) | general RA, outer joins, aggregates | proof burden on authors |
| | CQ containment engine (homomorphism/CSP) | view matching, redundant-join removal, subsumption | NP worst case; set semantics only |
| Constraint use | pattern-based (FK join elimination, key derivation) | production default | incomplete but cheap and sound |
| | full chase / Chase & Backchase | MV/index rewriting with many constraints | termination (cyclic FKs), cost |
| Constraint trust | enforced only | safety-critical | loses rewrites on warehouses |
| | informational/RELY | lakehouse/warehouse with unenforced PK/FK | wrong answers on dirty data; plan-dependent results |
| Property derivation | keys + equivalence classes + constant columns | most engines | misses general FDs |
| | full FD sets with closure | GROUP BY/ORDER BY reduction heavy workloads | projected-FD blowup; cap it |
| Recursion | semi-naive linear (working table) | SQL `WITH RECURSIVE` | `UNION` dedup state = full result |
| | magic sets / goal-directed | selective goals on non-invariant columns | magic relation can be large; may break stratification |
| | nonlinear (doubling) | long chains, distributed | more work per round, double-delta care |
| Cyclic multi-way joins | binary join plans | acyclic / low-skew | polynomially suboptimal on cycles |
| | worst-case optimal (generic/leapfrog) | triangles, cliques, graph patterns | needs trie/sorted indexes |
| NULL semantics | SQL 3VL (standard) | compatibility | non-certain answers under negation |
| | certain-answer-preserving translation | integration, compliance queries | extra predicates, slower plans |

## Algorithms that matter

- **Attribute closure** `X⁺` (counter per FD, watch lists): `O(|Σ|)`;
  `Σ ⊨ X→Y` iff `Y ⊆ X⁺`. Keys: drop attributes while closure stays full.
- **CQ containment** `Q1 ⊑ Q2`: evaluate `Q2` on frozen `D_{Q1}` (homomorphism
  search, most-constrained-first), check the frozen head. NP; polynomial for
  bounded treewidth of `Q2` or ≤2 occurrences per predicate in `Q1`.
- **Minimization**: delete atoms one at a time while a homomorphism
  `Q → Q−α` fixing the head exists; result is the core. Sets only.
- **Chase**: violated tgds add atoms with fresh nulls; egds substitute nulls
  (fail on distinct constants); weak acyclicity guarantees termination.
  `P ⊑_Σ Q` iff `chase_Σ(P) ⊑ Q`.
- **Semi-naive**: `ΔT_{k+1} = (ΔT_k ⋈ E) − T_{≤k}`; for `k` IDB atoms per
  rule, `k` delta rules with old/Δ/all versions. Stratify via SCCs of the
  predicate dependency graph; reject negative edges inside an SCC.
- **Magic sets**: adorn from the goal (SIPS), add `magic_p` guards and
  binding-propagation rules, evaluate semi-naively.
- **Yannakakis** (acyclic CQs): GYO join tree; semijoin up and down (full
  reducer); early projection: `O(in+out)` full CQs, `O(in·out)` projected.
- **Naive evaluation** (nulls as distinct constants, drop null tuples) =
  certain answers for UCQs/positive Datalog.
- **Decorrelation**: Apply → semijoin/antijoin/outer join + aggregate with
  `COUNT(non-null inner column)` or `COALESCE(agg, agg(∅))`; null-aware
  antijoin for `NOT IN`; mark join for subqueries under `OR`/`NOT`/SELECT.

## Failure modes & classic bugs

- **COUNT bug**: correlated `COUNT` decorrelated into a grouped inner join
  loses zero-match outer rows; or `COUNT(*)` counts the padded row.
- **NOT IN as plain antijoin** with nullable sides; `> ALL` → `> MAX`.
- **Self-join removed under bags** by containment — row counts change.
- **FK join elimination** with nullable/deferrable/disabled FK, partial-NULL
  composite FK, or collation mismatch.
- **DISTINCT eliminated** via nullable UNIQUE; **CHECK turned into a filter**
  (drops NULL rows; CHECK accepts UNKNOWN).
- **Outer join simplified** under a non-null-rejecting predicate
  (`COALESCE`, `IS NULL`, `OR`).
- **Wrong equality**: grouping/set ops with predicate equality (NULLs don't
  group), or substitution across non-identity equality (CI collation, `-0.0`).
- **Recursive CTE**: filter on a non-invariant column; `UNION ALL` on cycles;
  unstratified aggregation accepted.
- **Guard reordering**: `x <> 0 AND 1/x > 1` evaluated out of order.
- **Informational keys on dirty data**: plan-dependent answers.

## Implementation checklist (C/C++/Rust)

- Cached, immutable plan-node properties: `keys`, `lax_keys` (bitset
  `ColSet`s), `equiv_classes: UnionFind<ColId>`, `const_cols`, `not_null`,
  capped `fds`, `ordering: Vec<(ColId, Dir, NullsPos)>`, `dup_insensitive`
  (top-down), `is_set` (bottom-up).
- Strictness analysis per scalar expression (`null_rejecting_on(cols)`),
  computed bottom-up with function metadata (`strict`, `volatile`,
  `may_raise`, `equality_preserving`).
- Constraint catalog entries carry `enforced`, `deferrable`, `validated`,
  `rely` flags; rules query a single `trusted(constraint, txn_ctx)` API.
- CQ IR (`Vec<Atom{rel, terms}>` + union-find for equalities) extracted from
  SPJ blocks for containment/minimization; canonical form (sorted atoms,
  first-use variable renaming) for memo keys — remember canonical equality =
  isomorphism.
- Homomorphism search with a node budget; exhaustion = "not contained".
- Executor: two hash/equality functions per type (predicate vs
  grouping/"not distinct"); null-aware antijoin and mark join operators;
  max-one-row enforcement for scalar subqueries.
- Recursive CTE operator: working table + accumulated hash set (spillable);
  iteration cap; `CYCLE`/`SEARCH` support; invariant-column analysis for
  pushdown; distributed version partitions dedup state by full-tuple hash.

## How to test it

- **Rewrite fuzzing**: per rule, random tiny instances (3–4 values,
  duplicates, NULLs, empty tables); compare plans as **multisets**; add
  instances violating each side condition and assert the rule does not fire.
- **Reference evaluator**: slow bag-RA + 3VL + grouping-equality interpreter
  as oracle. **SQLancer oracles**: TLP (`p`/`NOT p`/`p IS NULL` partitions
  union to the whole), NoREC (Rigger & Su, 2020).
- **Containment**: literature golden pairs; brute-force counterexample
  search; the frozen `D_{Q1}` must refute every "not contained".
- **Properties**: verify derived keys/FDs/orders on random outputs.
- **Recursion**: naive vs semi-naive vs magic on cyclic random graphs;
  pushed vs unpushed filters; unstratified programs rejected.
- **Certain answers**: possible-world enumeration with marked nulls; SQL
  must be sound on positive queries. Provers (Cosette, CIDR 2017) for
  high-value rules.

## Expert review questions

1. Bag-legal, or only in a duplicate-insensitive context — checked where?
2. Behavior on empty input, all-NULL input, and scalar (ungrouped) aggregates?
3. Which constraints does it use; enforced, deferrable, or informational *now*?
4. Does every moved predicate keep its TRUE/FALSE/UNKNOWN; is null-rejection
   derived or assumed?
5. FK join elimination: FK NOT NULL, referenced key unique, predicate exactly
   the FK equality, same collation?
6. Does any equal-value substitution cross a type whose equality is not identity?
7. Subqueries: `NOT IN` with NULLs, `ALL` on empty sets, scalar 0/>1 rows?
8. Outer-join reordering: which predicates are strict on which sides?
9. Recursive CTE: still stratified, filter on an invariant column, terminates
   on cycles?
10. Can it evaluate a volatile or error-raising expression on new rows or a
    different number of times?
11. Does a checker timeout degrade to "no rewrite"?
12. Do derived keys/orders survive outer joins, `UNION ALL`, nullable UNIQUE —
    and on data violating an informational key, do plans disagree?

## Go deeper

- `references/algebra-calculus-and-rewrite-laws.md` — RA/RC, Codd's theorem,
  safety, set-vs-bag law catalog, outer joins, aggregation pushdown,
  decorrelation/COUNT bug, rule template. Read before adding any logical rule.
- `references/containment-and-minimization.md` — homomorphism theorem,
  minimization, UCQ/CQAC/Datalog/bag/aggregate containment, views, acyclic
  joins, WCOJ. Read for view matching, redundancy removal, implication.
- `references/datalog-and-recursion.md` — expressive-power limits, semi-naive,
  magic sets, stratification, recursive CTE mapping and pushdown, distributed
  recursion. Read for `WITH RECURSIVE` and rule engines.
- `references/dependencies-chase-and-semantic-optimization.md` — implication
  complexity, closure, chase and termination, semantic rewrites with exact
  conditions, FD/key/order derivation. Read before using any constraint.
- `references/nulls-and-incomplete-information.md` — certain answers,
  Codd/naive/c-tables, SQL 3VL contexts, NULL rewrite checklist, CQA. Read
  for anything NULL-related.
- `references/normalization-and-keys.md` — keys, normal forms, lossless and
  dependency-preserving decomposition, acyclic schemas. Read for catalog/key
  support and schema tooling.
- `references/edbs-entries.md` — all 50 source entries with pages.

## Related skills

- `query-optimizer` — rule/cost framework; this skill supplies legality proofs.
- `sql-frontend` — binder; must encode the 3VL/subquery/safety semantics here.
- `query-plan-design` — node interfaces; carry keys/FDs/orders/dup-flags.
- `join-algorithms` — physical joins; null-aware anti/mark/semi semantics here.
- `query-engine-testing` — harnesses; oracles (reference evaluator, TLP) here.
- `sql-semantics-and-active-rules` — clause-level SQL standard and triggers;
  this skill is the logic-level theory beneath it.
- `cardinality-and-statistics` — keys/FDs as bounds and correlation; FD
  discovery is statistics, not constraints.
- `materialized-views-ivm` — view matching/maintenance using containment and C&B.
- `query-execution-advanced` — executes recursive CTEs, mark joins, WCOJ.
- `olap-and-warehouse-engines` — star joins, decomposable aggregates,
  unenforced-FK join elimination.
- `distributed-dbms-design`, `parallel-database-systems` — semijoin reducers,
  distributed semi-naive, partial aggregation.
- `beyond-relational-engines` — graph/Datalog engines; `temporal-databases` —
  snapshot (weak) equivalence.

## Grounding

EDBS (printed pages): Relational Algebra (3146), Relational Calculus (3147),
Safety and Domain Independence (3269), Bag Semantics (252), Aggregation:
Expressiveness and Containment (74), Conjunctive Query (580), Query
Containment (2981), Datalog (1000), Query Processing in Deductive Databases
(3046), Expressive Power of Query Languages (1415), Database Dependencies
(945), Implication of Constraints (1808), Chase (418), Order Dependency
(2631), Normal Forms and Normalization (2509), Incomplete Information (1819),
Certain (and Possible) Answers (408), Inconsistent Databases (1825); all 50
in `references/edbs-entries.md`.

Seminal: Codd (1970, 1972); Chandra & Merlin (STOC 1977); Sagiv & Yannakakis
(JACM 1980); Yannakakis (VLDB 1981); Imielinski & Lipski (JACM 1984); Beeri &
Vardi (JACM 1984); Bancilhon et al. (PODS 1986); Chaudhuri & Vardi (PODS
1993); Abiteboul, Hull & Vianu (1995); Arenas, Bertossi & Chomicki (PODS
1999); Deutsch, Popa & Tannen (VLDB 1999). Beyond EDBS: Ganski & Wong (SIGMOD
1987), Galindo-Legaria & Joshi (SIGMOD 2001), Neumann & Kemper (BTW 2015) on
decorrelation; Moerkotte et al. (SIGMOD 2013) outer-join reordering; Yan &
Larson (VLDB 1995); Simmen et al. (SIGMOD 1996); Ngo et al. (PODS 2012);
Libkin (TODS 2016); Koutris & Wijsen (TODS 2017); Rigger & Su (2020).
