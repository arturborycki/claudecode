# Keys, normal forms, decomposition, and acyclic schemas

Read this when implementing catalog support for keys and FDs, designing
schema-advisor / normalization tooling, reasoning about lossless
decompositions (vertical partitioning, column groups, denormalized
warehouse tables), or when the optimizer needs to know whether a stored
table's columns are functionally related.

---

## 1. Keys

- **Superkey**: `K ⊆ attr(R)` with `K → attr(R)` implied by the declared FDs
  (equivalently, `closure(K) = attr(R)`); in instances: no two tuples agree
  on `K`. A key is a property of the *schema* (all legal instances), never
  inferred from one instance — an instance-level uniqueness is just a
  statistic.
- **Candidate (minimal) key**: superkey with no proper superkey subset.
  **Primary key**: one chosen candidate key (NOT NULL in SQL). **Prime
  attribute**: member of some candidate key.
- Algorithms:
  - Test superkey: one closure, linear.
  - Find one candidate key: start from `attr(R)`, try dropping each
    attribute, keep the drop if still a superkey — `O(|attr| · closure)`.
  - Enumerate all candidate keys: Lucchesi & Osborn (JCSS 1978), polynomial
    per key output; the number of keys can be exponential in `|attr|`.
  - Is `A` prime? NP-complete.
- SQL nuances: `PRIMARY KEY` = UNIQUE + NOT NULL. `UNIQUE` on nullable
  columns permits multiple NULL rows (standard semantics), so it is only a
  *lax* key: valid as an FD determinant among non-NULL rows, invalid for
  DISTINCT/GROUP BY elimination or for proving "at most one row" when NULLs
  can appear (see `dependencies-chase-and-semantic-optimization.md` §6–7).
  A unique *index* is a key only if it is non-partial, immediate
  (not deferrable), and valid.

---

## 2. Normal forms

All defined relative to a schema `R` and a dependency set `Σ` (closure
implied).

| NF | Condition (for every nontrivial implied dependency) | Prevents | Test complexity |
|---|---|---|---|
| 1NF | atomic domains (no repeating groups) | — | syntactic |
| 2NF | FD `X → A`: `A` prime, or no candidate key strictly contains `X` | partial dependency on part of a key | needs prime attributes (NP-hard in general) |
| 3NF | FD `X → A`: `X` superkey or `A` prime | transitive dependencies (Codd 1972) | NP-complete (Jou & Fischer 1982) |
| BCNF | FD `X → A`: `X` superkey | all FD-based redundancy (Codd 1974) | polynomial on the schema itself: check only the given FDs; checking a *projected* subschema is coNP-complete (Beeri & Bernstein 1979) |
| 4NF | MVD `X ↠ Y`: `X` superkey | MVD redundancy (Fagin 1977) | polynomial (FD+MVD implication) |
| PJ/NF (5NF) | every JD implied by the keys | JD redundancy (Fagin 1979; corrected 5NF definition by Vincent 1997) | via chase |
| DK/NF | every constraint is a consequence of domain and key constraints (Fagin 1981) | all insertion/deletion anomalies | not generally achievable |

Strictness: BCNF ⊂ 3NF ⊂ 2NF; 4NF ⊂ BCNF; PJ/NF ⊂ 4NF. Classic separating
examples (own phrasing):

- `R(A,B,C)`, `Σ = {AB → C, C → B}`: candidate keys `AB`, `AC`; every
  attribute is prime ⇒ 3NF; `C → B` with `C` not a superkey ⇒ not BCNF; and
  **no** BCNF decomposition preserves `AB → C`. (Think `(street, city) → zip`,
  `zip → city`.)
- `R(A,B,C)` with only `A ↠ C` (hence `A ↠ B`): no nontrivial FD ⇒ BCNF;
  `A` not a superkey ⇒ not 4NF; decompose into `AB`, `AC`.

**Anomalies** that normalization removes (Codd): update anomaly (a
fact stored in many rows must be changed in all), deletion anomaly
(deleting the last row of one fact loses an unrelated fact), insertion
anomaly (cannot record a fact without an unrelated one). Example shape:
`Course(number, title, section, room)` with `number → title` repeats the
title per section; decompose into `CourseInfo(number, title)` and
`CourseTerm(number, section, room)`.

---

## 3. Decomposition

A decomposition replaces `R` by projections `R1..Rn` (`∪ attr(Ri) =
attr(R)`). Two desiderata:

**Lossless join (information preservation).** For every legal instance `I`,
`I = π_{R1}(I) ⋈ … ⋈ π_{Rn}(I)` — i.e. the JD `⋈[R1..Rn]` is implied by `Σ`.
(`⊆` direction always holds; losslessness is about no spurious tuples.)

- Binary test: `{R1, R2}` lossless w.r.t. FDs iff `R1 ∩ R2 → R1 − R2` or
  `R1 ∩ R2 → R2 − R1` (the common attributes are a key of one side). With
  MVDs: iff `R1 ∩ R2 ↠ R1 − R2`.
- General test (Aho, Beeri, Ullman 1979): tableau with one row per `Ri`
  (distinguished symbol `a_j` in columns of `Ri`, unique `b_ij` elsewhere);
  chase with `Σ`; lossless iff some row becomes all-distinguished.
- Information capacity view (Hull 1986, "calculous dominance"): `S2`
  dominates `S1` if RA queries map instances back and forth losslessly;
  projection/join decompositions are the special case normalization uses.

**Dependency preservation.** The union of the FDs that hold on the
components (projections of `Σ⁺`) implies `Σ`, so constraints can be checked
per table without joins. Test without computing projected closures:

```
preserves(X -> Y):
   Z := X
   repeat: for each component Ri:  Z := Z ∪ (closure(Z ∩ Ri, Σ) ∩ Ri)
   until Z unchanged
   return Y ⊆ Z                       # polynomial per FD
```

**Algorithms.**

| Target | Algorithm | Lossless | Dep.-preserving | Cost |
|---|---|---|---|---|
| BCNF | analysis: while some `Ri` has a violating `X → A` (`X` not a superkey of `Ri`), split into `XA` and `Ri − A` | yes | not always (may be impossible) | polynomial if violations are found from given FDs; finding violations in projected schemas is the hard part |
| 3NF | synthesis (Bernstein 1976; Biskup, Dayal, Bernstein 1979): minimal cover; one relation per group of FDs with the same left side; add a relation holding a candidate key if none contains one; drop relations contained in others | yes | yes | polynomial |
| 4NF | analysis with MVDs | yes | not always | |

Trade-off: BCNF/4NF eliminate redundancy but may force cross-table checks
(assertions, triggers) for lost FDs; 3NF keeps every FD locally checkable
at the cost of some redundancy.

---

## 4. Join dependencies and acyclic schemas

When a JD `⋈[X1..Xk]` is declared, the decomposition is the design; the
question becomes **consistency**: are the stored fragments projections of
one universal relation? Checking global consistency is exponential in the
number of relations in general. **Acyclic** JDs/schemas (hypergraph
α-acyclic; Beeri, Fagin, Maier, Yannakakis, JACM 1983) have many equivalent
characterizations:

- equivalent to a set of MVDs;
- pairwise consistency of the fragments implies global consistency;
- there is a full semijoin reducer (a semijoin program that removes all
  dangling tuples);
- the GYO reduction succeeds; a join tree exists;
- joins can be computed by Yannakakis' algorithm in `O(input + output)`.

`k`-cyclic generalization (Gyssens 1986): a JD equivalent to JDs with ≤ `k`
components; global consistency follows from `k`-wise consistency. The
hypergraph decomposition theory that grew out of this (hypertree width) is
now the basis of tractable CQ evaluation (see
`containment-and-minimization.md` §8).

---

## 5. Why an engine builder cares

1. **Catalog**: represent keys (PK, UNIQUE NOT NULL, valid unique indexes),
   lax keys (nullable UNIQUE), FKs with trust flags (enforced, deferrable,
   informational/RELY), and optionally declared FDs. These feed property
   derivation (keys/FDs/orders per plan node).
2. **Optimizer**: keys and FDs drive join elimination, DISTINCT/GROUP BY
   simplification, order reduction, and cardinality bounds (a join on a key
   cannot increase cardinality; `γ` on a key is a no-op).
3. **Statistics** (boundary with `cardinality-and-statistics`): an FD
   `X → Y` means `NDV(X,Y) = NDV(X)` and that selectivities of predicates on
   `X` and `Y` are not independent. Denormalized warehouse tables are full of
   *undeclared* FDs (city → state, product → category); detecting them
   (exact or approximate) fixes the independence assumption.
   PostgreSQL's `CREATE STATISTICS … (dependencies)` stores per-column-pair
   functional-dependency degrees for exactly this reason.
4. **Physical design**: vertical partitioning / column groups are lossless
   decompositions on the key (each fragment carries the key or a row id);
   the binary lossless test is the correctness condition for reassembly.
5. **Warehouse modeling** (boundary with `olap-and-warehouse-engines`): star
   schemas are deliberately non-normalized dimensions with FK→PK joins from
   the fact table — precisely the shape where FK-based join elimination and
   order dependencies (date key ↦ date) pay off.

> **Beyond EDBS:** FD discovery from data — TANE (Huhtala, Kärkkäinen,
> Porkka, Toivonen, Computer Journal 1999) and many successors — finds exact
> and approximate FDs level-wise over the attribute lattice using
> partition refinement; it is exponential in the number of attributes and
> roughly linear in rows, and is the practical way to recover FDs for
> statistics on legacy tables. Discovered FDs are statistics, not
> constraints: never use them for semantic rewrites.

---

## 6. Failure modes

- Treating an instance-observed uniqueness or a discovered FD as a key in a
  rewrite.
- Nullable UNIQUE treated as a key for DISTINCT elimination or
  "max one row" proofs.
- BCNF tooling that silently loses dependencies (no warning about FDs that
  now need cross-table enforcement).
- Testing BCNF of decomposed fragments using only the FDs "visible" in the
  fragment's original declaration instead of the projection of `Σ⁺`.
- Vertical partitions that do not repeat a key/row id (lossy reassembly).

## 7. Tests

- Closure/key algorithms vs brute force on random FD sets over ≤ 8
  attributes (enumerate all subsets).
- Lossless test vs explicit join of projections on random instances
  satisfying `Σ` (generate by chasing random seeds).
- 3NF synthesis output: assert lossless (tableau chase), dependency
  preserving (§3 test), and each component in 3NF.
- BCNF decomposition: assert lossless and BCNF of each component w.r.t.
  the projected FDs.

---

Sources: EDBS entries Key (p.2057), Functional Dependency (p.1555), Armstrong
Axioms (p.165), Normal Forms and Normalization (p.2509), Second Normal Form
(2NF) (p.3337), Third Normal Form (p.4122), Boyce-Codd Normal Form (p.336),
Fourth Normal Form (p.1514), Multivalued Dependency (p.2447), Join Dependency
(p.2050), Database Dependencies (p.945), Relational Model (p.3149),
Parameterized Complexity of Queries (p.2680).
