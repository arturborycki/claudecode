# Uncertain and probabilistic databases (and crowd-powered databases)

Read this when building or reviewing support for uncertain data:
possible-worlds semantics, representation systems (c-tables, U-relations,
tuple-independent and block-independent-disjoint tables), the complexity
dichotomy, extensional evaluation with safe plans, intensional
(lineage-based) evaluation with knowledge compilation and Monte Carlo, and
how these constrain an optimizer and executor. A short final section covers
crowd database systems, which share the "answers are not certain" problem.

---

## 1. Semantics

- An **uncertain database** is a set of possible worlds, each an ordinary
  database over the same schema. A **probabilistic database** adds a
  distribution over the worlds (discrete: P(I) > 0, Σ P(I) = 1).
- **Query semantics** (possible answers): evaluate Q in every world; a tuple
  t is a possible answer if it appears in some world's answer; its
  **marginal probability** is the sum of probabilities of the worlds whose
  answer contains t. Result = set of (t, p) pairs.
- Certain answers (incomplete databases without probabilities): tuples in
  the answer of every world.
- Enumerating worlds is infeasible (2^n for n independent tuples), so
  everything depends on a **succinct representation** that queries can be
  evaluated on directly.

### Tuple-level vs attribute-level uncertainty
Attribute-level uncertainty ("Gizmo's color is red with 0.25, blue with
0.75") is encoded tuple-level by making the alternatives mutually
exclusive tuples sharing a **possible-worlds key** (x-tuples / maybe-tuples,
Trio's x-relations). If the alternatives' probabilities sum to < 1, the
entity may be absent altogether. Continuous attribute uncertainty (pdfs:
sensor readings, locations) needs symbolic representations (Orion) or
sampling (MCDB).

---

## 2. Representation systems

Definitions:
- **Complete** for a family of uncertain databases: every member has a
  representation. Countability arguments show completeness is impossible
  for, e.g., all uncertain databases over the reals; finite world sets
  always have complete representations (naive enumeration).
- **Strong for a query language L**: for every representable I and Q ∈ L,
  the world set {Q(I) | I ∈ I} is again representable — i.e., the system
  is *closed* under query evaluation, so queries can be compiled into
  operations on representations.

| System | Encoding | Strength / completeness | Use |
|---|---|---|---|
| **c-tables** (Imieliński & Lipski 1984) | Tuples may contain variables; each tuple has a Boolean condition over variables (comparisons combined by ∧, ∨, ¬); a global condition restricts valuations. Each valuation satisfying the global condition defines a world | Strong for positive relational algebra (and representing uncountable world sets) | Theoretical backbone; lineage descends from tuple conditions |
| Naive tables (v-tables) | Variables in fields, no conditions; repeated variable = same unknown value across fields | Weak (not strong) for positive RA: naive evaluation yields certain answers of UCQs in PTIME, but tables are not closed under selection; certain answers turn coNP-hard once `≠`/negation enter | Marked nulls in data exchange |
| SQL NULLs | Unmarked nulls with three-valued logic | **Not strong** for positive RA under classical semantics: SQL forgets that two occurrences derive from the same null (e.g., projecting A twice and testing A1 = A2 yields no row) | Practical but semantically lossy |
| **U-relations** (MayBMS) | Probabilistic c-tables restricted to Boolean variables, conditions only in condition columns (conjunctions of var = value), no variables in data | Strong for positive RA **and** complete for finite world sets; positive RA evaluated by rewriting into ordinary RA over the condition columns | Build a probabilistic DBMS as a query-rewriting front-end on a stock RDBMS |
| **Tuple-independent (TI)** | One probability column; tuples independent | Succinct (n tuples → 2^n worlds); not strong for joins | Knowledge bases (Knowledge Vault, NELL), extraction outputs |
| **Block-independent-disjoint (BID)** | Blocks of mutually exclusive tuples (sum ≤ 1), blocks independent | Succinct; conjunctive queries over BIDs are complete | OCR alternatives, entity resolution, attribute uncertainty |
| **PC (probabilistic conditional) databases** | Each tuple annotated with a propositional formula over independent random variables | Complete; closed under RA: join → ∧, union → ∨, difference → ∧¬ | The format of *answers*: the formula is the tuple's **lineage** |
| Graphical-model-backed (PrDB, MarkoViews) | Data + factor graph / Markov logic weights over tuple variables | Arbitrary correlations | Rich correlations at the cost of general inference |

Key separation (worth copying in an engine): a representation = (1) a
mapping from a valuation of random variables to a world's relations (data
side, relational), plus (2) a representation of the joint distribution of
those variables (independent marginals, BID blocks, or a graphical
model). Queries transform (1) and leave (2) untouched — after loading a TI
table as a PC table with one fresh variable per tuple, every operator only
rewrites per-tuple formulas.

Markov Logic Networks (weighted first-order soft constraints) reduce to TI
databases plus a hard constraint: each MLN probability equals a conditional
probability in a TI database with one extra relation per soft rule, so MLN
inference becomes query evaluation (Jha & Suciu 2012).

---

## 3. Complexity

- Data complexity of computing marginals is **#P-hard** in general, even
  for simple join queries on TI tables (the Boolean query
  R(x), S(x,y), T(y) — call it H0 — is the canonical hard case; reduction
  from counting satisfying assignments of positive bipartite DNF).
- **Dichotomy theorems**: for self-join-free conjunctive queries,
  conjunctive queries with negation, unions of conjunctive queries, and
  certain aggregate (HAVING) queries over TI databases, every query is
  either PTIME or #P-hard (Dalvi & Suciu; the UCQ dichotomy, JACM 2012).
  There is no middle ground to optimize toward: recognize the class.
- **Hierarchical criterion** (self-join-free CQs over TI): let at(x) be the
  set of atoms containing variable x. The query is tractable iff for every
  pair of non-head variables, at(x) and at(y) are disjoint or one contains
  the other. H0 fails it (at(x) = {R,S}, at(y) = {S,T}). For BID tables,
  key positions add constraints: queries that are hierarchical can still
  be hard if a variable that must be projected out is not in the key of
  every block-structured atom (the entry's H2/H3 examples are hard in that
  keyed setting).
- Functional dependencies can make hard queries tractable (they shrink
  effective variable sets).

---

## 4. Extensional evaluation: safe plans

Operators carry a probability column and compute output probabilities
assuming specific (in)dependence of their inputs.

| Operator | Output probability | Correct iff |
|---|---|---|
| Selection σ | unchanged | always |
| **Independent join** ⋈ᵖ | p1 · p2 | joined tuples are independent events (different relations / disjoint variables) |
| **Independent project** πᴵ | 1 − ∏ᵢ (1 − pᵢ) over tuples collapsing to the same output | collapsing tuples are independent |
| **Disjoint project** πᴰ | Σᵢ pᵢ | collapsing tuples are mutually exclusive (same possible-worlds key) |
| Independent union | 1 − (1 − p1)(1 − p2) | inputs independent |
| Inclusion–exclusion (for UCQs) | alternating sums over conjunctions of subqueries | via lifted rules with Möbius cancellation |

A **safe plan** applies every operator only where its independence
assumption holds for *every* database instance. Safe plans run in
polynomial time bottom-up; #P-hard queries admit none. For self-join-free
CQs, {selection, independent join, independent project} is complete: a query
is tractable exactly when it has a safe plan; adding disjoint project
covers BID tables.

### Safe-plan construction (self-join-free CQ, TI)
```
SafePlan(Q):                      # Q: set of atoms, head variables H
  if Q is a single atom: return scan(atom) with σ for constants
  if atoms split into components sharing no non-head variable:
      return ⋈ᵖ over SafePlan(component)            # independent join
  find a "root" variable x (non-head) occurring in every atom
  if none: FAIL  → #P-hard (non-hierarchical)
  return πᴵ_{H}( SafePlan(Q with x added to head) )  # independent project
```
For BID atoms, the root variable must also be in the possible-worlds key
where required, and projections over key-sharing tuples use πᴰ.

### Worked example (from the entry, restated)
Product(prod, price, color, shape) is BID keyed on (prod, price);
Order(prod, price, cust) is TI. Query: colors of products ordered by Sue.
- Safe: πᴵ_color( πᴰ_{prod,price,color}(Product) ⋈ᵖ σ_{cust=Sue}(Order) ).
  The inner disjoint project merges exclusive alternatives of one product;
  the join pairs tuples from different relations; the outer independent
  project merges tuples from different products (independent).
- Unsafe: πᴵ_color( Product ⋈ᵖ σ_{cust=Sue}(Order) ) — the outer projection
  can merge two join results sharing the same Order tuple or alternatives
  of the same product, which are not independent.

### Engine implications
- **Safety restricts the plan space.** Join orders and projection
  placements are no longer freely interchangeable; an optimizer must either
  enumerate only safe plans (cost-based among them) or **decouple**: run
  an arbitrary optimal plan to compute answer tuples plus a relational
  encoding of their lineage, then run the safe plan (or a compiled
  evaluation) over the lineage only (SPROUT's lazy vs eager plans).
- Implementable with no kernel change by rewriting SQL to aggregate
  probabilities: independent project = `1 - PRODUCT(1 - p)`; with no
  product aggregate, use `1 - EXP(SUM(LN(1 - p)))`, guarding p = 1
  (log of 0) and precision loss for p near 0 (use `log1p`-style
  functions or log-space accumulation).
- Floating-point: products of many probabilities underflow → accumulate in
  log space; sums of disjoint probabilities must not exceed 1 (assert with
  tolerance; violation indicates a modeling or key error).

---

## 5. Intensional evaluation: lineage

1. Run the query to produce answer tuples annotated with lineage Φ (a
   positive DNF for UCQs: one conjunction per derivation). This is the
   provenance computation of `provenance.md` with the Boolean / PosBool
   semiring.
2. Compute P(Φ) — #P-hard in general — by one of:

**Knowledge compilation** (SPROUT and successors): recursively
- if Φ = Φ1 ∨ … ∨ Φm or Φ1 ∧ … ∧ Φm with pairwise independent (disjoint
  variable sets) or mutually exclusive subformulas, combine their
  probabilities in linear time (this step *is* what safe-plan operators do);
- otherwise apply **Shannon expansion** on a variable v:
  P(Φ) = P(v)·P(Φ|v=1) + (1 − P(v))·P(Φ|v=0).
The trace is a decision diagram (OBDD, d-DNNF) that supports linear-time
probability computation. Variable order decides size (exponential in the
worst case); for known tractable classes (non-repeating queries with
negation, inversion-free UCQs, queries with inequalities) the compiled
OBDDs have polynomial size with compatible variable orders.
**Anytime approximation**: stopping early yields lower and upper bounds that
tighten monotonically; **top-k** stops when k tuples' lower bounds exceed
all others' upper bounds. Model-based bounds: find Φ_L ⊨ Φ ⊨ Φ_U with
tractable Φ_L, Φ_U.

**Monte Carlo**: sample worlds, evaluate Φ, average; the Karp–Luby–Madras
estimator gives an FPRAS for DNF probability (relative error ε with
confidence 1 − δ in polynomial time). MystiQ and MayBMS use such
estimators for hard queries. Drawback: no distinction between easy and
hard queries — simple queries get slow, which violates user expectations.
**MCDB** generalizes: user-defined VG (variable generation) functions
sample uncertain attributes from arbitrary distributions; the engine runs
the plan once over *tuple bundles* (each tuple carries an array of sampled
values, one per Monte Carlo iteration) rather than once per world.

**Dissociation** (Gatterbauer & Suciu): treat repeated occurrences of a
variable as independent copies, producing oblivious upper/lower bounds
computable by safe plans — extensional plans used as approximations for
hard queries.

| Approach | In-database? | Exact? | Systems |
|---|---|---|---|
| Safe plans | yes | yes (tractable only) | MystiQ, SPROUT, Orion |
| Lineage + compilation | out (compiler) | yes / anytime bounds | SPROUT, Trio, MayBMS |
| Monte Carlo over lineage | out | approximate (FPRAS) | MystiQ, MayBMS |
| Tuple-bundle Monte Carlo | in | approximate | MCDB |
| Graphical-model inference | out | exact/approx | PrDB |

Lifted (query-level, first-order) methods with inclusion–exclusion reach
all tractable UCQs; grounded (lineage-level) compilation provably cannot
compile some tractable UCQs to polynomial-size OBDD/FBDD/decision-DNNF
(Jha & Suciu; Beame, Li, Roy & Suciu) — so a system
that only grounds will be exponential on queries the dichotomy calls easy.

---

## 6. Systems and applications
- **Trio**: ULDB = uncertainty + lineage; x-tuples with alternatives and
  '?' (maybe) markers; lineage is stored and used both to compute
  confidences lazily and to keep derived data consistent.
- **MystiQ** (safe plans, Monte Carlo), **MayBMS** (U-relations; SQL
  extensions to create uncertainty such as repair-by-key and to query
  confidence), **SPROUT** (lazy plans, compilation, anytime), **Orion**
  (continuous pdfs), **PrDB** (correlations via graphical models),
  **MCDB** (VG functions, tuple bundles), **ProTDB** (probabilistic XML).
- Applications: information extraction (keep extractor scores), entity
  resolution / fuzzy matching (keep match probabilities rather than
  thresholding into match/non-match/maybe), data integration with
  uncertain schema mappings, sensor/RFID cleaning, web-scale knowledge
  bases of uncertain triples (the largest probabilistic databases).

### Testing oracle
On tiny databases (≤ 15–20 uncertain tuples) enumerate all worlds
explicitly, evaluate Q per world with a trusted deterministic engine, sum
probabilities — compare against safe plans, compiled lineage, and Monte
Carlo (the latter within confidence bounds). Property tests: P ∈ [0,1];
P(Q1 ∨ Q2) ≥ max(P(Q1), P(Q2)); deterministic input (all p = 1) must
reproduce the deterministic answer with p = 1; a planner must reject
(or route to intensional evaluation) every non-hierarchical SJF CQ.

---

## 7. Crowd database systems (brief)

Crowd DBMSs add human input to SQL processing for missing data and
subjective comparisons; architecture = parser → optimizer → executor →
**HIT manager** that instantiates UI templates with tuple values and posts
human intelligence tasks to a marketplace (e.g., Mechanical Turk).

| System | Language extension | Crowd operators | Notable |
|---|---|---|---|
| CrowdDB | `CROWD` columns (values filled by people) and `CROWD` tables (whole tuples unknown); `CROWDEQUAL` (~=), `CROWDORDER` | CrowdProbe (fill fields/new tuples), CrowdJoin (index NLJ whose inner is a crowd table), CrowdCompare | Open-world tables: a crowd table has unbounded cardinality → need LIMIT/stop conditions |
| Qurk | Task UDFs with templates (filter, sort, join, generative) and combiners (majority vote) | Crowd join as block NLJ with **batching** (naïve: several pairs per HIT; smart: grid of two image columns to link); sort by pairwise comparison (quadratic) vs rating (linear, less consistent) | Cost/quality/latency trade-offs of operator implementations |
| Deco | Conceptual vs raw schema; **fetch rules** A1 ⇒ A2 : P (given A1 values, ask for A2), **resolution rules** (dedup, majority-of-3); `AtLeast n` | Fetch, Resolve, Dependent Left Outer Join, Filter, Scan | Avoids empty answers; cost-based optimization over fetch plans |
| CDAS | Crowd-recognizable attributes declared in schema; `JoinFilter` hints | CSelect, CJoin, CFill | Quality control models of worker accuracy, online cost-sensitive decisions |

Optimization objective is three-dimensional: **monetary cost** (#HITs ×
price), **latency** (crowd response time; parallelism of posted HITs),
**quality** (redundancy per HIT combined by majority vote or EM-style
worker-accuracy models). Engine implications: asynchronous, long-running
operators; caching and reusing crowd answers across queries (answers are
data); batching tuples per HIT; pruning candidate pairs with machine-
computable filters before crowd joins (JoinFilter, POSSIBLY); results are
inherently uncertain — a natural fit for BID/TI representations of §2.

Sources: Probabilistic Databases (p.2830); Query Processing over Uncertain
Data (p.3052); Uncertain Data Models (p.4297); Provenance in Databases
(p.2904); Crowd Database Systems (p.689); XQuery Processors (p.4846,
ProTDB).
