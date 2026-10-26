# Provenance: why, how, where — semirings, capture, storage

Read this when adding lineage/provenance to a query engine or reviewing
such a design: the precise definitions (lineage, why-, how-,
where-provenance), the semiring framework and what it implies for the
optimizer, capture strategies (eager propagation, query rewriting,
instrumented execution, lazy inversion), handling updates and curated data,
and how provenance is identified and stored.

---

## 1. Definitions

Let t ∈ Q(D). A **witness** (proof) for t is a subset D′ ⊆ D with
t ∈ Q(D′). Provenance notions differ in which witnesses they keep and how
much of the derivation they record.

| Notion | What it records | Granularity | Origin |
|---|---|---|---|
| **Lineage** (contributing tuples) | For each input relation, the set of tuples that contributed to t (union over all derivations) | Tuple | Cui, Widom, Wiener 2000 (warehouse view lineage) |
| **Why-provenance** | The *set of witnesses* (witness basis); the **minimal witness basis** keeps only inclusion-minimal witnesses | Tuple sets | Buneman, Khanna, Tan 2001 |
| **How-provenance** | A polynomial over tuple identifiers: + for alternative derivations, · for joint use, coefficients/exponents for multiplicity | Tuple + derivation structure | Green, Karvounarakis, Tannen 2007 (provenance semirings) |
| **Where-provenance** | For an output *value*, the input locations (relation, tuple, attribute) it was **copied** from | Attribute value | Buneman, Khanna, Tan 2001 |
| Workflow / coarse provenance | Which process, parameters, software versions produced which data product | Dataset / file | Scientific workflow systems (Kepler, Chimera, VisTrails, Karma) |

Small example: R = {r1: (a,b), r2: (a,c)}, S = {s1: (b,e), s2: (c,e)},
Q = π_{x,z}(R(x,y) ⋈ S(y,z)). Output (a,e) has two derivations:
- lineage: R-tuples {r1, r2}, S-tuples {s1, s2}
- why: {{r1,s1}, {r2,s2}} (both minimal)
- how: r1·s1 + r2·s2
- where of value e: S.z in s1 or in s2 (copied from either, depending on the
  derivation).
Lineage alone cannot tell that {r1, s2} is *not* a witness; why-provenance
can; how-provenance additionally says each derivation is used once and
that there are two — enough to compute bag multiplicity.

Where-provenance is **not invariant under query equivalence**: two
equivalent SPJU queries can copy a value from different places
(e.g., `σ_{A=5}` and then output A vs output the constant 5). DBNotes'
default annotation propagation (along copy paths) inherits this; its
**default-all** scheme propagates over all equivalent formulations so that
equivalent queries propagate identically; custom schemes let users decide.

---

## 2. The semiring framework

A **K-relation** maps each tuple to an annotation in a commutative
semiring (K, ⊕, ⊗, 0, 1); tuples annotated 0 are absent. Positive
relational algebra lifts uniformly:

| Operator | Annotation of output tuple |
|---|---|
| Union R ∪ S | R(t) ⊕ S(t) |
| Projection π | ⊕ of annotations of all input tuples projecting to t |
| Natural join R ⋈ S | R(t1) ⊗ S(t2) |
| Selection σ_θ | R(t) ⊗ (θ(t) ? 1 : 0) |
| Constant relation | 1 per tuple |

Instances: (ℕ, +, ·) = **bag semantics**; (𝔹, ∨, ∧) = set semantics;
(events, ∪, ∩) = probabilistic lineage (`uncertain-and-probabilistic-
databases.md`); (ℝ∞, min, +) tropical = cheapest derivation cost; (ordered
clearance levels, min, max) = access-control levels; (ℕ, +, ·) counting =
the basis of view maintenance by counting.

**Provenance polynomials ℕ[X]** (X = tuple ids) are the *most general*
case: for any semiring K and any valuation X → K, evaluating the query in
ℕ[X] and then applying the induced homomorphism equals evaluating directly
in K ("factorization through ℕ[X]"). Practically: compute ℕ[X] once, then
derive bag counts, set membership, probabilities (when safe), trust,
costs, or the effect of deleting tuples (set their variables to 0) without
re-running the query.

Coarser provenance = homomorphic images of ℕ[X]:
```
ℕ[X] → 𝔹[X] (drop coefficients) ─┐
ℕ[X] → Trio(X) (drop exponents)  ─┴→ Why(X) (sets of witness sets)
Why(X) → PosBool(X) (absorption: minimal witnesses);  Why(X) → Lin(X) (contributing ids = lineage)
```
Choose the weakest form your application needs: storage and computation
shrink rapidly down the chain.

### Consequences for the optimizer (the part engine builders miss)
- Query equivalence is **semiring-dependent**. Rewrites valid under set
  semantics (𝔹) are not all valid under ℕ[X]: e.g., self-join
  elimination using idempotence (R ⋈ R = R under sets, but r·r ≠ r in
  ℕ[X]), moving or removing DISTINCT, minimizing CQs via containment
  mappings. For conjunctive queries, equivalence under ℕ[X] is exactly
  query isomorphism (Green 2009) — far stricter than set equivalence.
- Therefore a provenance-aware engine must tag plans with the semiring
  they are evaluated in and **disable rewrites not sound for it** —
  otherwise two "equivalent" plans return different provenance. For
  why-/lineage-level provenance more rewrites are allowed (PosBool is
  idempotent and absorptive).
- Aggregation needs **semimodules** (Amsterdamer, Deutch, Tannen 2011):
  aggregate values become formal sums of (annotation ⊗ value) pairs, e.g.,
  SUM = r1⊗10 + r2⊗20, with tensor-product structure; comparisons on
  aggregates (HAVING) produce symbolic conditions.
- Difference/negation needs semirings with a monus (m-semirings) or
  extensions with negated variables; recursion (Datalog) needs
  ω-continuous semirings and formal power series, and representations as
  **circuits** (shared subexpressions) rather than expanded polynomials to
  stay polynomial-size.

---

## 3. Capture and querying strategies

| Strategy | How | Pros | Cons | Systems |
|---|---|---|---|---|
| **Eager annotation propagation** | Annotations stored with source data and carried by every operator into results | Provenance always available; uniform model | Every query pays; annotation blowup; operators must be annotation-aware | DBNotes, Trio, Orchestra |
| **Query rewriting** (instrumentation in SQL) | Rewrite Q to Q⁺ whose result contains t plus the full source tuples of each witness (one output row per witness, provenance columns appended) | Runs on an unmodified RDBMS; the optimizer optimizes provenance computation too; provenance is queryable relationally | Result width explosion; one row per derivation (multiplicative for joins); relational encoding of nested derivations is denormalized | Perm, GProM |
| **Reenactment** for updates/transactions | Express past updates/transactions as queries over time-travel snapshots, then apply query provenance rewriting | Provenance of DML and of whole transactions (including concurrency effects under SI) without logging per-tuple annotations | Needs time travel / temporal storage; reenactment cost | GProM |
| **Lazy inversion (backward tracing)** | Store nothing extra; when asked "why t?", run inverse queries that find source tuples matching t | Zero overhead on normal queries | Expensive per request; needs invertible or annotated views; sensitive to updates after the fact | Cui & Widom lineage tracing |
| **Instrumented execution** (Beyond EDBS) | Physical operators emit rid-level lineage (e.g., arrays of input rids per output) during execution, building lineage indexes | Interactive-speed backward/forward lineage queries for visualization/debugging | Engine changes in every operator; memory | Smoke (VLDB 2018) |
| **Language extension** | SQL extended with provenance queries over semiring annotations (paths in the derivation graph) | Expressive provenance queries; indexing of provenance graphs | New language and storage | ProQL (Orchestra) |

### Curated and versioned databases
Curated scientific databases are built by people copying, pasting and
editing from other sources, not by queries, so query provenance does not
apply. Approaches: model curation as **provenance-aware transactions** of
copy/insert/delete operations, logged with hierarchical (subtree-level)
compression so that copying a subtree records one provenance link, not one
per node (Buneman, Chapman, Cheney 2006); **LIVE** couples ULDB lineage
with full versioning and uses lineage for incremental maintenance of
derived data; **MMP** tracks provenance at multiple granularities (field,
row) and user confidence/doubt.

### Applications that justify the cost
- Data quality and trust: estimate reliability from sources; Orchestra uses
  provenance to evaluate trust policies and prioritize updates during
  update exchange between peers.
- Debugging schema mappings and ETL ("routes" explaining which mapping
  produced a target tuple).
- Probabilistic query answering (lineage → probability).
- View maintenance (counting/ℕ annotations; deletion propagation = set
  deleted variables to 0) and view update.
- Why-not provenance (missing answers), explanations, access control
  (security semiring), GDPR-style data subject tracing.

---

## 4. Implementation choices in a relational engine

1. **Representation of annotations**: (a) explicit polynomial/formula
   objects in a column (compact for small derivations, opaque to SQL); (b)
   relational encoding — one row per monomial/witness with id columns
   (Perm-style; queryable, large); (c) circuits/DAGs with shared
   subformulas (polynomial-size even when expanded polynomials are
   exponential, e.g., recursive queries or many-way joins with high fan-in);
   (d) factorized representations (d-representations) that factor
   provenance like factorized databases.
2. **Identity of base tuples**: stable tuple ids (rowid + table id +
   version), not physical addresses that change on update/compaction;
   versioned for time-travel provenance.
3. **Operator semantics**: hash aggregation computes ⊕ per group; joins
   compute ⊗; duplicate elimination computes ⊕ over duplicates (it must
   *not* discard annotations); sort and exchange operators carry
   annotations; LIMIT/top-k need care (which derivations are kept is
   nondeterministic under ties).
4. **Optimizer**: semiring tag per plan; rule filter (above); cost model
   includes annotation size (polynomial size can grow multiplicatively
   with join depth).
5. **Granularity knobs**: tuple vs attribute (where) vs coarse
   (statement-/job-level); sampling or bounded provenance for analytics
   workloads.

---

## 5. Provenance storage

### Identity first
Provenance is a recursive dependency graph between data products and the
transformations that consumed/produced them; without stable identity of
products across steps, you cannot connect "output of step i" to "input of
step j", and recursive origin/impact queries break.
- **Naming conventions** (PROV uses URIs/IRIs; equal identifiers mean the
  same entity): simple, but hard to impose across organizations and
  storage systems.
- **Content-bound identifiers**: cryptographic hash of the content, so
  independent observers derive the same id without coordination and can
  deduplicate reports. Hash choice trades throughput, collision resistance
  and digest size (e.g., SHA-256: larger digest, strong collision
  resistance, slower; MD5: faster, smaller, collision-broken — do not use
  where adversarial collisions matter).
- Context-bound identifiers (content + producing context) when the same
  bytes produced by different processes must stay distinct.

### Storage organization
The provenance graph is a DAG; typical queries are graph queries (all
ancestors/descendants, shortest dependency chain, k-step impact).

| Option | Pros | Cons |
|---|---|---|
| **With the data** (embedded in the product: file headers, XML/JSON/BSON sidecars, cryptographically bound metadata) | Portable; travels with the data; easy exchange | No global index; cross-product queries need scanning everything; trees (XML/JSON) express DAGs only via ID/IDREF pointers or duplication — good interchange format, poor query format |
| **Separate relational store** (node table + edge table) | Mature tooling; excellent for bulk/attribute queries ("all provenance owned by Bob") | Path-associative queries ("2–5 steps downstream of X") become dynamically constructed recursive SQL with joins per step; developers reimplement graph algorithms; mitigated by reachability/interval indexes on DAGs |
| **Graph database / triple store** (Cypher, SPARQL) | Model match (directed graph); path queries natural and indexed by edges | Weaker on bulk attribute queries; separate system |
| **Flat files / logs** (e.g., MapReduce lineage capture, RAMP) | Cheap capture at scale | Post-processing needed to query |
| **Hybrid / compressed** | Factorize repeated substructures (shared subgraphs, nested collections), compress hierarchical provenance; inherit-from-parent encodings | Complexity in query rewriting over compressed form |

Interchange standards (OPM, W3C PROV with entities, activities, agents and
relations such as used / wasGeneratedBy / wasDerivedFrom; Dublin Core;
domain standards such as CDISC, ISO 19115) define *exchange*, not storage:
store in whatever layout makes your queries fast and export to PROV.
Centralized stores dominate; decentralized/distributed provenance stores
exist for multi-organization settings (with the identity problem
magnified).

### Size management
Fine-grained provenance can exceed the data by orders of magnitude (each
output tuple of a k-way join references k inputs; aggregates reference
whole groups). Levers: coarsen granularity (block/partition-level
lineage), store weakest sufficient semiring, factorize/circuit
representations, compress sorted id lists (delta/bitmap), retain by
policy (TTL), and compute on demand by reenactment instead of storing.

---

## 6. Review checklist
- Which provenance notion do consumers actually need (lineage, why, how,
  where)? Is the cheapest sufficient one stored?
- Is the optimizer prevented from applying rewrites unsound for the
  annotation semiring (self-join elimination, DISTINCT movement, CQ
  minimization)?
- Do DISTINCT/aggregation combine annotations (⊕) instead of dropping them?
- Are base tuple identifiers stable across updates, vacuum/compaction and
  partition moves?
- Is provenance of updates/transactions required (reenactment, versioned
  storage) or only of queries?
- Oracles: compute provenance by brute force — for each subset of the
  (tiny) input, check membership of t — and compare minimal witnesses to
  the system's why-provenance; evaluate ℕ[X] results under random
  homomorphisms into ℕ and 𝔹 and compare against bag/set query execution
  (the factorization property gives a free differential test).

Sources: Provenance in Databases (p.2904); Provenance Storage (p.2923);
Query Processing over Uncertain Data (p.3052); Uncertain Data Models
(p.4297); Graph Database (p.1639).
