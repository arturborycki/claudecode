# Time models and query semantics

How time is represented inside an engine (domain, chronon, granularity,
timestamp types), which time dimensions a relation carries, how tuples are
stamped, and what a temporal statement *means* (current / sequenced /
nonsequenced). Everything downstream (algebra, joins, aggregation, storage)
depends on the choices made here, so make them explicit and document them in
the catalog.

Convention used throughout this skill: periods are **half-open** `[s, e)`,
matching SQL:2011. Where a source or legacy system uses closed `[s, e]` over a
discrete domain, convert with `e_open = e_closed + 1 chronon` at the boundary
and never mix the two inside the executor.

---

## 1. Time domain

A time domain is a set of temporal individuals plus relations over them. The
database default is: individuals = instants, relation = a total (linear) order.
Orthogonal axes:

| Axis | Options | Engine consequence |
|---|---|---|
| Structure | linear / branching (partial order, tree or DAG) / circular | Linear is the only one any SQL engine implements; branching appears in "what-if" versioning (think git-like table branches), circular models periodicity |
| Density | discrete / dense / continuous | Every storage format is discrete; dense/continuous only matter for constraint databases. A dense model forbids "next instant", so `meets` must be expressed as `e1 = s2` (half-open) rather than `e1 + 1 = s2` |
| Bounds | bounded / left-, right-bounded / unbounded | A bounded domain gives you sentinel values (`beginning`, `forever`) for free; SQL types are bounded (e.g., year 1..9999) |
| Primitive | instants vs intervals as individuals | Intervals as primitives (Allen-style) are rare in engines; periods are almost always *derived* from instants |
| Metric | none / distance & duration defined | Needed for durations, calendar arithmetic, moving windows |

Anchored values name a position (`DATE '2007-09-14'`); unanchored values are
durations (`7 days`); `anchor ± duration → anchor`, `anchor − anchor →
duration`. SQL vocabulary trap: SQL `INTERVAL` is an **unanchored duration**
(YEAR-MONTH or DAY-TIME), not a time interval; the anchored convex set is a
**period**. SQL-92 has five anchored types (DATE, TIME, TIMESTAMP, and the two
WITH TIME ZONE variants) and two duration types; a `PERIOD` type existed only
in the abandoned SQL/Temporal draft, and SQL:2011 has *period definitions*
over two columns. YEAR-MONTH and DAY-TIME are separate because months vary in
length: a single microsecond duration cannot represent `1 month`, so store
(months, days, micros) if SQL semantics matter.

### Chronon

The smallest indivisible fixed-duration unit the model represents exactly;
the time line is a sequence of chronons whose size the implementation fixes
(e.g., 1 µs). A granule at the finest granularity is a chronon; a bounded
model has finitely many. TSQL2 stays agnostic about the nature of time: a
real instant is far smaller than a chronon and can only be approximated, and
a discrete picture emerges when timestamps are scaled to a granularity at run
time. Upshot: events in the same chronon are indistinguishable by timestamp,
so transaction-time systems pair the clock with a sequence number. Encode
chronons as `int64` since an epoch (cheap compare/sort/hash/SIMD) and keep
calendar conversion out of the hot path.

---

## 2. Temporal granularity

A granularity `G` is a mapping from integers (the index set) to subsets of the
time domain such that:

1. **Order**: if `i < j` and both `G(i)`, `G(j)` are non-empty, every instant
   of `G(i)` precedes every instant of `G(j)` (granules do not overlap and
   index order equals time order).
2. **Contiguous index set**: if `i < k < j` and `G(i)`, `G(j)` are non-empty,
   then `G(k)` is non-empty.

Non-empty `G(i)` are *granules*: a single instant, a contiguous range, or a
non-contiguous set (a business month = that month's business days). *Labels*
are external names ("September 2008") mapped to indexes. *Image* = union of
granules; *extent* = smallest interval covering it (equal for days, months,
years; not for business days). Relationships (catalog predicates that decide
which conversions are lossless):

| Relationship | Definition | Examples |
|---|---|---|
| `G` groups into `H` | every granule of `H` is a union of granules of `G` | days into weeks; days into months; **not** weeks into months |
| `G` finer than `H` | every granule of `G` lies inside some granule of `H` | business days finer than weeks (but do not group into weeks) |
| `G` groups periodically into `H` | groups-into, and the grouping pattern repeats: `n` granules of `H` are built from granules of `G` shifted by `m` | days→weeks (`m=7, n=1`); days→business days (`m=7, n=5`); months→years (`m=12, n=1`); days→years (`m=146097, n=400`, the Gregorian 400-year cycle) |
| bottom granularity | a granularity related to every other in the set by the chosen relation | `{weeks, months}` has no bottom w.r.t. groups-into; adding days provides one |
| calendar | a set of granularities containing a bottom w.r.t. groups-into | Gregorian = {days, months, years} |

Calendar algebra (Bettini, Wang & Jajodia): **Group_k** (`week =
Group_7(day)`, suitably aligned) and **altering-tick** (periodically add/drop
granules: months from 30-day groups, plus/minus days, leap-year February) do
most of the work; **Shift**, **Combine** (business week from business days),
**Subset** and **Select** (first day of each week) are auxiliary. Periodic
granularities have finite (also automaton-based) representations, making
equivalence and minimisation decidable.

Engine implications:

- Store at the base chronon; a granularity is a *view* (label ↔ index
  functions); `date_trunc('week', ts)` is a groups-into index function.
- **Coarse→fine conversion is not syntactic**: "salary in March" may mean
  every day or some day of March. Declare the semantic assumption per column,
  or a day-stamped ⋈ month-stamped join has no defined answer.
- Convert operands before temporal operators: to the finer granularity when
  the coarser groups into it, otherwise via the bottom granularity.
- Granularity constraints ("salary constant within a fiscal year") need a
  `same_granule` predicate; business-day distances need the business-day
  index function, not raw arithmetic.

---

## 3. Time dimensions

| Dimension | Meaning | Who supplies it | Bounds | Mutability |
|---|---|---|---|---|
| **Valid time** (SQL:2011 "application time", DB2 "business time") | when the fact holds in the real world being modeled | user / application | past, present, future | arbitrary updates and corrections |
| **Transaction time** (SQL:2011/DB2 "system time"; Oracle/Teradata "transaction time") | when the fact (any database entity, not just facts) is current in the database and retrievable | DBMS | from database creation to now; never future | append-only; logical delete closes the period |
| **Bitemporal** | both; a tuple is stamped with a rectangle (VT period × TT period) | both | — | — |
| **User-defined time** | any other time-valued attribute; no built-in semantics | user | any | ordinary column |

- Transaction time of `f` is the valid time of "f is current in the
  database"; it is supported separately because the DBMS supplies it and it
  is well-behaved (monotone, bounded by creation time and now) — the basis of
  audit. It must be **consistent with the serialization order** (a CC
  requirement; see `transaction-time-implementation.md`).
- "Decision time", "event time": model as VT (or TT) of a related fact.
- *Bitemporal relation*: exactly one VT and one TT aspect (strict
  definition; the loose one allows several, e.g., multiple perceived
  realities or TT carried across migrations). *Bitemporal interval*: a VT × TT
  rectangle, i.e., a set of bitemporal chronons; temporal elements generalise
  to finite unions of n-dimensional intervals.

---

## 4. Timestamp shapes and where they attach

### Shapes

| Timestamp | Closed under | Uniqueness of representation | Engine fit |
|---|---|---|---|
| instant | — | unique | events; point model for theory |
| period `[s,e)` | intersection only (not union, difference, complement) | many snapshot-equivalent encodings | two fixed-width columns; the industrial default |
| temporal element (finite union of periods) | union, intersection, complement (difference) | canonical if stored as sorted, disjoint, non-adjacent maximal periods | variable-length; needed for closed algebra, BCDM, TSQL2 |
| instant set | as sets | unique | TSQL2 event tables |

Non-closure under difference is why temporal difference must emit several
tuples per input (`[1,10) − [4,6)` = `[1,4)`, `[6,10)`). Temporal element
normal form: sorted `[s,e)` vector with `e_i < s_{i+1}`; set operations are
linear merges.

### Attachment

| Model | Stamp attaches to | Pros | Cons |
|---|---|---|---|
| tuple timestamping, 1NF (period-stamped) | tuple | maps to conventional storage; all of SQL:2011 | facts about one object spread over many rows; needs coalescing |
| tuple timestamping with temporal elements (BCDM) | tuple | one tuple = full history of one fact; syntactic identity = semantic identity | variable-length stamp |
| attribute-value timestamping (N1NF, parametric) | each attribute value is a function time→value | one tuple can hold an object's whole history ("temporally grouped"); more expressive | nest/unnest needed; key changes over time break grouping; awkward to store |
| relation/database timestamping | whole state | snapshot sequence | only for versioned stores |

Homogeneity: a temporal relation is homogeneous if all attributes of a tuple
share the same time reference. Non-homogeneous attribute-stamped tuples make
snapshots contain nulls; most algebras assume homogeneity.

### Point-stamped vs period-stamped models (the core distinction)

- **Point-stamped (abstract)**: facts are associated with individual instants.
  Two equivalent views: the *snapshot model* (database = function from time to
  ordinary relational instances, a Kripke structure) and the *timestamp model*
  (every relation gains one time attribute; each snapshot must be finite).
  They are isomorphic; queries in Temporal Relational Calculus (two-sorted FO
  logic with explicit time variables) and First-Order Temporal Logic
  (implicit time via connectives such as "sometime in the past") can use
  either. TRC is strictly more expressive than FOTL. With a fixed number of
  time dimensions there is no temporal algebra equivalent to TRC (you need an
  unbounded number of timestamp attributes); with varying, user-defined
  timestamp attributes only the timestamp view makes sense.
- **Period-stamped (concrete)**: tuples carry periods. Two readings:
  - *weak* period model: the period is just a compact encoding of a convex set
    of points; snapshot-equivalent relations carry the same information and a
    canonical (coalesced) form is natural.
  - *strong* period model: the period itself carries meaning. Two
    consecutive phone calls with the same attributes are not one long call;
    a salary paid for two adjacent half-years is two bonuses, not one.
    Coalescing would destroy information.

The **telic/atelic** distinction (Terenziani & Snodgrass, TKDE 2004) is the
semantic test: atelic facts (states: "is employed") are downward-hereditary
and can be coalesced; telic facts (accomplishments: "baked a cake", "flew
Venice→Montreal", a phone call) hold over an interval as a whole and must not
be split or merged. An engine should let a table (or column) declare which
it holds; coalescing and sequenced splitting are only safe for atelic data.

### Abstract vs concrete languages (Chomicki)

Abstract languages are defined over the point-stamped database; concrete
languages manipulate the interval encoding. The correctness criterion for
compiling an abstract query `Q` to a concrete query `eval(Q)` over an encoding
`E` with meaning function `‖·‖`:

```
Q(‖E‖) = ‖eval(Q)(E)‖        for every encoding E
```

FOTL evaluation model (useful for implementing it): a query is evaluated
at an *evaluation point* (think `now`); its first-order part runs on that
instant's snapshot, and the connectives `since`/`until` (and derived
"sometime in the past/future") move the evaluation point, so one query can
reference several snapshots. `Q1 since Q2` holds now if `Q2` held at some
past instant and `Q1` at every instant from then until now. Evaluating at
every instant yields a point-stamped answer relation. (Lineage: Prior's tense
logic; Pnueli brought it to verification; Sernadas first proposed it for
databases; de Castilho et al. for integrity constraints; Tuzhilin & Clifford
as a query language.)

Several encodings (`E1`, `E2`) may denote the same abstract database; the
compiled query must not depend on which one is stored. FOTL and TRC queries
can be compiled to plain first-order queries over a relational representation
of interval encodings (Toman; Chomicki, Toman & Böhlen TODS 2001), and the
same works under SQL duplicate semantics (SQL/TP). This is the theoretical
licence for "sequenced semantics by reduction to snapshot queries" below.

Classic failure of concrete languages: the GAPS query ("persons with gaps in
employment, with the gaps"). Over `Employment(VT, EID, Company)` it is
`∃I1,I2: [∃c Employment(I1,x,c)] ∧ [∃c Employment(I2,x,c)] ∧ I1 precedes I2 ∧
I = [end(I1), begin(I2))`, and it is **wrong unless each bracketed
subexpression is coalesced**: a person employed back-to-back by c1, c2, c3 is
reported with a spurious gap. Coalescing the base table is not enough; the
projection `∃c` creates new value-equivalent adjacent tuples. Abstract
languages never have this bug.

---

## 5. Snapshot equivalence

Let a relation have `n` time dimensions with timeslice operators
`τ¹ … τⁿ`. Tuples (or relations) `x`, `y` are **snapshot equivalent**
(weakly equivalent) iff for all instants `t1 ∈ D1 … tn ∈ Dn`:
`τⁿ_tn(…τ¹_t1(x)…) = τⁿ_tn(…τ¹_t1(y)…)`. Example: `{(a,[3,10))}` and
`{(a,[3,6)), (a,[6,10))}` differ but are snapshot equivalent.

Engine uses:

- It is the equivalence an optimizer may exploit for **point-based**
  queries; it is *not* the equivalence for queries that look at timestamps
  (duration, count of stored tuples). A rewrite that is valid only up to
  snapshot equivalence must be tagged as such (Slivinskas & Jensen: extensible
  optimizers with multiple equivalence types — list, multiset, snapshot).
- It is the oracle for testing: compare engine output against a reference
  after unfolding both to points (see SKILL.md "How to test it").
- Coalescing picks the canonical representative of a snapshot-equivalence
  class for 1-D relations. For multi-dimensional (bitemporal) relations a
  meaningful canonical coalesced form is not known to exist in general.

---

## 6. The semantics trichotomy

### 6.1 Current semantics (temporal upward compatibility)

A non-temporal statement on a temporal database must behave as if run on the
non-temporal database obtained by the timeslice at `now`. For non-temporal
modifications `M1…Mn` and non-temporal query `Q`, at any `t ≤ now`:

```
Q(Mn(…M1(Dt)…)) = Q(Mn(…M1(τ_now(Dt))…))
```

With `n = 0`: `Q(Dt) = Q(τ_now(Dt))`. Modifications additionally must persist
into the future (an update made now holds until overwritten), because now
keeps moving. Constraints and assertions are checked on the current state.

Engine meaning: enabling versioning or a valid-time period changes no
existing statement's result; reads default to `AS OF now`, writes to "from now
until changed". New reserved words technically break this (identifier
collisions); accept it if statements not using them keep their meaning.

SQL:2011, DB2, Oracle 12c and SQL Server give current semantics for
transaction-time (system-versioned) tables. Teradata applies current
semantics uniformly to valid-time, transaction-time and bitemporal tables.

> **Beyond EDBS:** In SQL:2011 an application-time table queried without
> predicates returns *all* rows (past and future), i.e., application time
> does **not** get current semantics; only system time defaults to `AS OF
> CURRENT_TIMESTAMP`. Teradata instead uses statement qualifiers derived from
> TSQL2/ATSQL statement modifiers (`CURRENT VALIDTIME`, `SEQUENCED VALIDTIME`,
> `NONSEQUENCED VALIDTIME`, and the TRANSACTIONTIME counterparts) with current
> as the default, which is the closest production realisation of the
> trichotomy.

### 6.2 Sequenced semantics

Goal: any non-temporal statement `q` can be made temporal by a fixed,
statement-independent wrapper (`SEQ VT q`), and the result means "evaluate
`q` on every snapshot and assemble the results". Three components (Böhlen &
Jensen):

1. **S-reducibility**: each non-temporal `q` has a syntactically similar
   temporal `qᵗ = S1 q S2` with `τ_t(qᵗ(r)) = q(τ_t(r))` for all `t`;
   `S1`, `S2` are *statement modifiers* changing the whole statement's meaning.
2. **Extended S-reducibility**: predicates/functions on timestamps inside the
   statement (`DURATION(VTIME(E)) > DURATION(VTIME(S))`, returning argument
   periods) — not evaluable on a timestamp-free snapshot, but still "per
   snapshot plus a predicate". Implement by copying each argument timestamp
   into an explicit attribute before reduction.
3. **Interval preservation**: among the snapshot-equivalent results, default
   to *preserving argument timestamps* (lineage). Coalescing is irreversible,
   so it is an explicit operator, never the default.

Example (sequenced NOT EXISTS): employees with no salary at each instant. With
Employee(Pam, [4,13)) and Salary(Pam, [6,10)) the answer is `(Pam,[4,6))`,
`(Pam,[10,13))` — computed by interval subtraction, conceptually per snapshot.

### 6.3 Nonsequenced semantics

Timestamps are plain attributes (`NSEQ VT`). Needed for expressiveness
(temporal logic is strictly weaker than FO with explicit time), for
cross-state queries ("Employee's valid time precedes Salary's"), and for
legacy SQL — the assembly language of temporal querying; it requires period
predicates (Allen relations) and functions.

Contrast on `COUNT(*)` over Bonus: nonsequenced counts stored tuples (3);
sequenced returns a time-varying count (2 at each instant in the example);
current returns the count of the snapshot at now.

### 6.4 Implementing sequenced semantics by reduction

The engine never materialises snapshots. Three strategies:

| Strategy | Idea | Cost | When |
|---|---|---|---|
| Unfold / fold (IXSQL, SQL/TP style) | expand each tuple to one row per chronon, run `q` grouped by `t`, fold back to maximal periods | `O(Σ duration)` rows; loses lineage (fold coalesces) | coarse granularity, tests/oracles only |
| Constant-interval splitting (normalization / alignment) | split argument tuples at every change point relevant to the operator, then evaluate `q` with the period as an ordinary attribute | output up to `O(n²)` pieces worst case, typically near-linear | general-purpose kernel implementation |
| Operator-specific kernels | overlap join with intersection, sweep-line aggregation, interval subtraction | `O(n log n + output)` | production hot paths |

Correctness: within an *elementary interval* (between consecutive relevant
change points) all snapshots are identical, so one evaluation per elementary
interval equals pointwise evaluation (S-reducibility); splitting only at the
arguments' own boundaries gives interval preservation.

Operator-by-operator reduction (Dignös, Böhlen, Gamper: *temporal
normalization* `N` and *temporal alignment* `φ`, SIGMOD 2012; kernel
integration in TODS 2016):

| Sequenced operator | Reduction |
|---|---|
| σ_P (P on explicit attributes) | σ_P unchanged |
| π_X (bag) | π_{X,T}; result may be uncoalesced |
| π_X (set, i.e., DISTINCT) | normalize on X, then DISTINCT on (X, T) |
| r ×ᵗ s, r ⋈ᵗ_θ s | ⋈_{θ ∧ overlap(r.T,s.T)}, result T = r.T ∩ s.T (no split needed) |
| r ∪ᵗ s (set) | normalize r and s against each other on all explicit attributes, union on (values, T), deduplicate |
| r −ᵗ s | normalize r and s against each other on all explicit attributes (`N_A(r;s) − N_A(s;r)`), then difference on (values, T) |
| r ∩ᵗ s | as join on all attributes with intersection |
| γ_{G; F} (aggregation) | normalize r against itself grouped by G (split at all starts/ends within each group), then γ_{G,T; F} — this is instantaneous temporal aggregation |
| outer joins | align both sides; dangling portions padded with nulls |
| NOT EXISTS / anti-join | alignment + anti-join |

`N_B(r; s)` splits each `r` period at the endpoints of `B`-matching `s`
tuples that fall inside it; `φ_θ(r; s)` emits, per `r` tuple, its
intersections with θ-matching `s` tuples plus the maximal uncovered
remainders. Both are sweeps over (group key, start) order.

> **Beyond EDBS:** Dignös et al. prototyped normalize/align in the PostgreSQL
> kernel: two new plan operators plus timestamp propagation suffice, and the
> rest reuses ordinary operators and their optimizer rules.

---

## 7. NOW and variables in time

Three distinct uses; never conflate them in the implementation.

1. **Nullary functions** `CURRENT_DATE`, `CURRENT_TIME`, `CURRENT_TIMESTAMP`.
   SQL evaluates all references in a statement at one implementation-chosen
   instant. What users need is the transaction's logical execution instant,
   placed consistently with the serialization order — i.e., its commit time,
   which is not yet known while the statement runs.
   Worked anomaly: T1 starts 23:49 Jan 14, inserts $200, commits 00:07 Jan 15;
   T2 starts 23:51, inserts $500, commits 23:59. Stamping with start time (or
   statement time) makes "total balance on Jan 14" = $700, a state that never
   existed (true history: $0 → $500 on Jan 14 → $700 on Jan 15).
   Fix (Lomet, Snodgrass, Jensen 2005): each `CURRENT_DATE` call *narrows* the
   allowed commit-time window to that day; reading data written by another
   transaction raises the window's lower bound above the writer's
   timestamp; at commit pick the earliest instant in the window; if it ever
   becomes empty, abort. Coarse-grained calls (DATE) constrain little, so
   aborts are rare.
2. **Stored variable** (`now`, `until changed`; also written `-`, `∞`, `@`)
   in end columns: the period grows with the clock without per-chronon
   updates. SQL cannot store `CURRENT_DATE` in a column, so products store the
   type's maximum value (SQL:2011 system end).
3. **Now-relative values**: `now − 3 days` (a signed span from now), e.g.,
   employment known only up to three days ago because of reporting lag; may
   be indeterminate.

Semantics: *extensionalization* maps the variable database to a ground one
with instant stamps plus a **reference time** attribute (when variables get
their meaning). Evaluation: a **bind** operator grounds variables at the
observer's reference time (query start, ideally the serialization time);
other operators are unchanged. TSQL2 binds implicitly; `NOBIND` stores a
variable.

Indexing now-relative data (growing extents violate the "stationary between
updates" assumption of most indexes): for transaction time, index closed
versions in one structure (e.g., R-tree over `[s,e)`) and current versions in a
second index on `s` only, probing both; for bitemporal data, four R-trees,
where the three growing shapes (growing in VT, in TT, or stair-shaped) are
each transformed into stationary regions with matching query transformations
(Bliujūtė et al. 2000); or the GR-tree, whose bounding regions may be static
or growing, rectangles or stairs. Statistics should record the open-ended
fraction: it skews sort-merge on end time and histogram overlap estimates.

> **Beyond EDBS:** Sentinel pitfalls: ~8000-year durations, a histogram spike
> at the maximum, overflow in time-zone conversion or `e + 1`. Prefer a flag or
> reserved encoding plus a bind step.

---

## 8. Allen's interval relations as predicates

Thirteen mutually exclusive, jointly exhaustive relations between two
non-empty periods (Allen, CACM 1983). Any non-empty subset of the 13 is a
relation of Allen's interval algebra (2¹³ − 1 of them), used for partially
known orderings ("I1 before, meets or overlaps I2") and qualitative
constraint reasoning. Endpoint conditions for half-open `I=[s1,e1)`,
`J=[s2,e2)`:

| Relation (I r J) | Endpoint condition | Inverse |
|---|---|---|
| before | `e1 < s2` | after |
| meets | `e1 = s2` | met_by |
| overlaps | `s1 < s2 < e1 < e2` | overlapped_by |
| starts | `s1 = s2 ∧ e1 < e2` | started_by |
| during | `s2 < s1 ∧ e1 < e2` | contains |
| finishes | `s2 < s1 ∧ e1 = e2` | finished_by |
| equals | `s1 = s2 ∧ e1 = e2` | equals |

For closed discrete periods `[s,e]`, `meets` is `e1 + 1 = s2` and `before` is
`e1 + 1 < s2`.

SQL:2011 period predicates are *unions* of Allen relations (they are "true"
overlap/containment tests, unlike Allen's narrow `overlaps`/`contains`):

| SQL:2011 predicate | Condition (half-open) | Allen relations covered |
|---|---|---|
| `P OVERLAPS Q` | `s1 < e2 ∧ s2 < e1` | all except before, after, meets, met_by (9) |
| `P CONTAINS Q` (period) | `s1 ≤ s2 ∧ e2 ≤ e1` | contains, started_by, finished_by, equals |
| `P CONTAINS t` (instant) | `s1 ≤ t < e1` | — |
| `P EQUALS Q` | `s1 = s2 ∧ e1 = e2` | equals |
| `P PRECEDES Q` | `e1 ≤ s2` | before, meets |
| `P SUCCEEDS Q` | `s1 ≥ e2` | after, met_by |
| `P IMMEDIATELY PRECEDES Q` | `e1 = s2` | meets |
| `P IMMEDIATELY SUCCEEDS Q` | `s1 = e2` | met_by |

Executor/optimizer consequences:

- Allen predicates are conjunctions of endpoint comparisons, so normalise them
  into range predicates for B-trees and zone maps: `OVERLAPS [qs,qe)` = `s <
  qe AND e > qs`; on an `(s)` index the `e > qs` part is a residual filter,
  hence poor selectivity on long histories.
- As a 2-D point `(s,e)`, OVERLAPS is a dominance range query — why R-trees,
  kd-trees and the relational interval tree apply.
- Composition of Allen relations (the 13×13 composition table) supports
  predicate inference in joins (`I before J ∧ J before K ⇒ I before K`);
  consistency checking of general Allen networks is NP-complete, so do not
  attempt full qualitative reasoning in an optimizer.

Sources: EDBS entries Time Domain (p.4139), Chronon (p.425), Temporal
Granularity (p.3970), Valid Time (p.4359), Transaction Time (p.4200),
Bitemporal Interval (p.309), Bitemporal Relation (p.310), Temporal Element
(p.3962), Temporal Data Models (p.3940), Point-Stamped Temporal Models
(p.2770), Period-Stamped Temporal Models (p.2742), Abstract Versus Concrete
Temporal Query Languages (p.2), Snapshot Equivalence (p.3512), Current
Semantics (p.716), Sequenced Semantics (p.3467), Nonsequenced Semantics
(p.2506), Now in Temporal Databases (p.2517), Allen's Relations (p.95),
Temporal Database (p.3945); Temporal Logic in Database Query Languages
fragment (p.3992, recovered supplement).
