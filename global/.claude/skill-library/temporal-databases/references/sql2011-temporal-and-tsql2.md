# SQL:2011 temporal, TSQL2, SQL language designs, and temporal integrity constraints

What the standard requires an engine to implement, where it came from
(TSQL2, SQL/Temporal, ATSQL), the design space of temporal SQL extensions,
and how temporal integrity constraints (sequenced keys, foreign keys, general
dynamic constraints) are defined and enforced.

---

## 1. SQL:2011 temporal features

History: TSQL2-based change proposals went to ANSI and ISO from 1995; a
SQL/Temporal part (Part 7 of SQL3) with a PERIOD type and valid/transaction
time support was accepted in the mid-1990s; the project was cancelled in 2001
over disagreements about where temporal support belonged. A new, different
proposal started in 2008 and became part of SQL:2011 (Kulkarni & Michels,
SIGMOD Record 2012).

### 1.1 Period definitions

- A **period definition** is a named table component pairing a start and an
  end column. There is no period *data type*.
- At most **one application-time period** (user-chosen name) and **one
  system-time period** (name fixed: `SYSTEM_TIME`) per table; declared only in
  `CREATE TABLE` / `ALTER TABLE`.
- Start and end columns have the same type. Application time: `DATE` or a
  timestamp type. System time: the standard's datetime rules appear to admit
  `DATE` too, but in practice use a high-precision timestamp (products use
  `TIMESTAMP(6)`–`TIMESTAMP(12)`) so distinct transactions get distinct stamps.
- **Closed-open** `[start, end)`. Declaring the period implies a table
  constraint `end > start` (no empty periods).

### 1.2 Application-time period tables (valid time)

```sql
CREATE TABLE assignment (emp_id BIGINT, dept_id BIGINT,
  vt_from DATE, vt_to DATE, PERIOD FOR vt (vt_from, vt_to));
```

- Users set and update period columns freely (past, present, future;
  corrections allowed) via ordinary INSERT/UPDATE/DELETE.
- `UPDATE … FOR PORTION OF vt FROM t1 TO t2` and `DELETE … FOR PORTION
  OF …`: for each qualifying row whose period overlaps `P = [t1, t2)`:
  - period contained in `P` → updated (or deleted) as a whole;
  - otherwise the row is split into two or three contiguous rows: the part
    inside `P` is updated (or removed), the leftover part(s) before and/or
    after `P` keep their original values.

  Example: row `(7, dept 10, [2020-01-01, 2020-12-01))` updated for portion
  `[2020-03-01, 2020-06-01)` to dept 20 becomes `[2020-01-01, 2020-03-01) 10`,
  `[2020-03-01, 2020-06-01) 20`, `[2020-06-01, 2020-12-01) 10`; a DELETE for
  the same portion keeps only the first and last pieces.
- **Temporal primary/unique keys**:
  `PRIMARY KEY (emp_id, vt WITHOUT OVERLAPS)` — rows may share `emp_id` if
  their periods do not overlap (a *sequenced* key: unique in every
  snapshot).
- **Temporal foreign keys**:
  `FOREIGN KEY (dept_id, PERIOD vt) REFERENCES dept (dept_id, PERIOD vt)`
  — every child row's period must be contained in the period of a matching
  parent row, or in the union of the periods of several **contiguous**
  matching parent rows.
- Querying uses ordinary SQL plus period predicates (`CONTAINS`, `OVERLAPS`,
  `EQUALS`, `PRECEDES`, `SUCCEEDS`, `IMMEDIATELY PRECEDES`, `IMMEDIATELY
  SUCCEEDS`; mapping to Allen relations in `time-models-and-semantics.md` §8).
  No sequenced query semantics, no temporal aggregation, no coalescing: the
  user writes the overlap predicates and interval arithmetic.

### 1.3 System-versioned tables (transaction time)

```sql
CREATE TABLE account (acct_id BIGINT PRIMARY KEY, balance DECIMAL(18,2),
  tt_from TIMESTAMP(6) GENERATED ALWAYS AS ROW START,
  tt_to   TIMESTAMP(6) GENERATED ALWAYS AS ROW END,
  PERIOD FOR SYSTEM_TIME (tt_from, tt_to)) WITH SYSTEM VERSIONING;
```

DML rules the engine must implement:

| Statement | Effect |
|---|---|
| INSERT | `tt_from` = transaction timestamp; `tt_to` = highest value of the type |
| UPDATE (current rows only) | first insert a historical copy of the old row with `tt_to` = transaction timestamp; then update the row and set `tt_from` = transaction timestamp |
| DELETE (current rows only) | set `tt_to` = transaction timestamp (no physical delete) |
| UPDATE/DELETE of historical rows | not allowed |
| Assigning system-time columns | never allowed (GENERATED ALWAYS) |
| `FOR PORTION OF SYSTEM_TIME` | not allowed |

- The transaction timestamp is implementation-chosen but **fixed for the
  whole transaction**.
- A row is a *current system row* if its system period contains the current
  time; otherwise *historical*. The history of a row forms a gap-free chain.
- Queries: `FOR SYSTEM_TIME AS OF t`; `FROM t1 TO t2` (rows whose system
  period overlaps `[t1, t2)`); `BETWEEN t1 AND t2` (overlaps `[t1, t2]`,
  i.e., inclusive upper bound). No clause = `AS OF CURRENT_TIMESTAMP`
  (current semantics).
- Constraints (PK, FK, UNIQUE) are enforced **only on current rows**: history
  rows are immutable snapshots that were checked when current. So a plain
  `PRIMARY KEY (acct_id)` means exactly one current row per `acct_id`.

### 1.4 Bitemporal tables

Both an application-time period and `SYSTEM_TIME` with `WITH SYSTEM
VERSIONING`. Queries combine `FOR SYSTEM_TIME …` with application-time
predicates; `FOR PORTION OF` applies to the application period and the
resulting changes are themselves system-versioned.

### 1.5 Engine implementation notes

- **FOR PORTION OF** = locate overlapping rows; for each, compute up to three
  pieces; update the original row in place to the middle piece and insert the
  leftovers. Checks: `end > start` on every piece; temporal PK on pieces
  (leftovers cannot conflict with each other, but a SET that changes key
  columns can conflict with other rows); temporal FKs on both sides (removing
  a parent portion can orphan child periods). On a system-versioned table the
  in-place update is itself versioned.
- **System time with begin-time stamps**: see
  `transaction-time-implementation.md` §4.4 for the "superseding a newer
  version" hazard.
- Store `tt_to = max` but treat it as `until changed` in statistics, period
  arithmetic, and display.

> **Beyond EDBS — products (high level).** DB2 (system time, "business time"
> for application time, and bitemporal tables with history tables); Oracle
> (Flashback for transaction time, "Temporal Validity" `PERIOD FOR` for
> application time); SQL Server (system-versioned tables with a current and a
> history table); MariaDB (system-versioned, application-time and bitemporal
> tables); SAP HANA (history tables); Teradata (PERIOD data type, ValidTime and
> TransactionTime columns, `CURRENT`/`SEQUENCED`/`NONSEQUENCED` temporal
> qualifiers, `NORMALIZE`, `EXPAND ON`, `UNTIL_CHANGED`/`UNTIL_CLOSED` open
> ends). PostgreSQL has no SQL:2011 system versioning in core; PostgreSQL 18
> adds `WITHOUT OVERLAPS` primary/unique keys and `PERIOD` temporal foreign
> keys over range columns (no `FOR PORTION OF` yet). Range
> types (`daterange`, `tstzrange`) with `&&` (overlap) and GiST indexes,
> multirange types (finite unions of ranges, i.e., temporal elements), and
> `EXCLUDE USING gist (id WITH =, valid WITH &&)` (with `btree_gist`) give a
> concurrency-safe non-overlap constraint.

---

## 2. TSQL2 (1993–1995)

A consensus temporal extension of SQL-92 designed by an 18-member committee
entirely by e-mail (spec and commentaries published as a book in 1995;
Snodgrass ed.). Its data model is the Bitemporal Conceptual Data Model
(Jensen, Soo & Snodgrass, Inf. Syst. 1994).

Design decisions that still matter:

| Decision | Consequence for an engine |
|---|---|
| Snapshot-equivalent instances are identical (point-based) | relations are coalesced; tuples stamped with temporal elements |
| One valid-time dimension; tuple timestamping; homogeneous tuples | simple storage, 1NF-implementable |
| Fully upward compatible with SQL-92; temporal support optional per table | current semantics; snapshot tables unchanged |
| No operation gives explicit attributes special semantics (no reliance on keys) | temporal operators work on any attribute set |
| Must be implementable on period-stamped 1NF tuples with an algebra that is snapshot reducible to relational algebra | existing optimizer rules keep working; a representational algebra was demonstrated |
| Allow representational models other than the conceptual one (e.g., attribute-stamped) | logical/physical separation |

Language concepts:

- **Time ontology**: bounded at both ends; refuses to decide discrete vs
  dense vs continuous; an instant is approximated by a timestamp at the
  chronon; granularity (scale) attached to instants; a period is a pair of
  instants in the same scale.
- **Baseline clock**: gives physical meaning to stored seconds (UTC is
  undefined before 1958 and unsuited to prehistoric dates); piecewise clocks
  with synchronization points; calendar independent.
- **Data types**: SQL-92 datetime and interval plus `PERIOD`, with
  specifiable range and precision; multiple calendars, calendric systems
  and languages for I/O; **surrogates** (identity without observable value,
  to tie together states of one object; not a key replacement).
- **Three time lines**: user-defined, valid, transaction. Special values
  `beginning` and `forever` (valid/user-defined) and `until changed`
  (transaction time; bounded below by database `initiation`).
- **Indeterminacy**: determinate or indeterminate instants/periods with
  mass functions; per-query credibility and ordering plausibility.
- **Now-relative** instants (`now - 1 day`), bound at query time unless
  stored with `NOBIND`.
- **Six table kinds**: snapshot; valid-time state (temporal elements);
  valid-time event (instant sets); transaction-time; bitemporal state;
  bitemporal event.
- **Restructuring** in FROM: coalesce on a subset of columns ("when did Tony
  earn 10,000, whatever his manager") and partition temporal elements into
  maximal periods.
- **Temporal selection/projection**: `VALID(r)`, `TRANSACTION(r)` in WHERE;
  default implicit `VALID` clause = intersection of argument valid times
  (designed for snapshot reducibility); `VALID INTERSECT` and explicit
  `VALID` to override; `SNAPSHOT` keyword to return a non-temporal result.
- **Aggregates**: temporal grouping, duration weighting, `RISING`; taxonomy
  of 14 aggregate kinds.
- Update statements extended with temporal extent; cursors can return valid
  time; minimal **schema versioning**; simple **vacuuming**; catalog tables
  extended with temporal metadata.

Payoff evidence: a set of case studies needed 1,848 lines of SQL-92 versus
520 lines of SQL/Temporal for the same functionality (Snodgrass 1999).
Oracle's Workspace Manager later offered period types, valid/transaction/
bitemporal tables and sequenced keys, uniqueness, referential integrity,
selection and projection close to the SQL/Temporal proposals.

---

## 3. Design space of temporal SQL (Böhlen, Gamper, Jensen, Snodgrass)

Benchmarks: Q1 rentals overlapping `[7,9]`; Q2 2-day rentals (duration);
Q3 how many vehicles rented (time-varying count, sequenced); Q4 how many
rentals in total (time-invariant, nonsequenced); Q5 current rentals.

| Approach (language) | Mechanism | Good at | Bad at |
|---|---|---|---|
| Abstract data types (SQL/ATD) | period type + Allen-style predicates and functions | Q1, Q2, Q4, Q5; minimal language impact | Q3 (two dozen lines of nested `NOT EXISTS`); no systematic way to make a snapshot query temporal |
| Fold/unfold (IXSQL, Lorentzos) | `unfold` periods to points, query, `fold` back | systematic temporal generalisation (Q3) | loses lineage (fold coalesces); technicalities left to the programmer |
| Point timestamps (SQL/TP, Toman) | relations are point-stamped; periods only physical | Q3 via `GROUP BY T`; clean semantics | needs surrogate ids (SeqNo) for Q1/Q2/Q4; temporal difference with ids degenerates |
| Syntactic defaults (TSQL2) | implicit clauses (intersection valid clause, instant grouping) | succinct common queries | defaults hard to make comprehensive and orthogonal; "does not scale" over constructs |
| Statement modifiers (ATSQL) | `SEQ VT` / `NSEQ VT` / none (current) prefix any statement | any statement made sequenced; works with period predicates; legacy queries unaffected | a deep change to the language |
| Temporal expressions (TempSQL, Gadia) | parametric model; `[[X]]` returns the temporal element where `X` holds | elegant point-based formulations; automatic ITA | little follow-up work; Q4 needs workarounds |

Statement modifiers are the cleanest mapping onto an engine: the parser
records a semantic mode per (sub)statement and the planner applies the
reduction of `time-models-and-semantics.md` §6.4.

---

## 4. Temporal integrity constraints

### 4.1 Kinds

Expressed in first-order temporal logic (FOTL) over point-stamped data
(past operators `●` previous, `◆` sometime in the past, `since`; future
operators `○` next, `◇` sometime in the future, `until`), or in two-sorted
logic with explicit time variables.

| Kind | States referenced | Example | Check after an update needs |
|---|---|---|---|
| static | current | primary key, foreign key ("no employee has two salaries") | new state |
| transition | previous + current | "today's salary ≥ yesterday's" | previous and new state |
| general temporal | arbitrary past/future | "an employee dropped from project Pulse never works for it again" | potentially the whole history — or a bounded encoding |

Static constraints written in FOTL read exactly like ordinary FO constraints
and mean "hold in every state" — i.e., sequenced constraints. Granularity
and arithmetic extend expressiveness (a `month(t1,t2)` predicate for "salary
does not change within a month"; integer division for weeks). With both
valid and transaction time, constraints can relate history to the
database's knowledge of history.

### 4.2 Satisfaction over a finite, growing history

Formulas are interpreted at a reference point `i` of a history `H = ⟨H0,
H1, …⟩`; `H ⊨ C` iff `C` holds at every point. Only a finite prefix
`⟨H0..Hn⟩` is ever known (append-only, past immutable), so:

- **Potential satisfaction** `⊨pot`: the prefix extends to an infinite
  history satisfying `C`. Natural, but undecidable even for some past-only
  constraints (Chomicki).
- `⊨fin`: the prefix extends to an infinite history in which `C` holds at
  each of the points `0..n`. Decidable for past-only constraints (future
  states are irrelevant); `⊨pot` implies `⊨fin`, and for most practical past
  constraints they coincide. Restricted future classes with decidable
  `⊨pot` exist (Chomicki & Niwiński).

Example: "everyone hired is promoted before retiring" and "no one retires
twice"; the prefix `⟨{Hire(Ed)}, {Hire(An)}, {Retire(Ed)}⟩` is already
inconsistent.

### 4.3 Historyless checking (bounded history encoding)

Goal: check temporal constraints without storing (or scanning) the history.
Chomicki's construction (TODS 1995) for past FOTL with `since`: an extended
schema `T`, an initial state `J_init`, an incremental update function `Δ`,
and non-temporal constraints `C'` over `T` such that

```
H ⊨temp C  ⇔  E(H) ⊨ C'          E(⟨H0..Hn⟩) = Δ(E(⟨H0..Hn-1⟩), Hn)
```

`|E(H)|` is polynomial in the number of distinct constants in `H`,
independent of history length. Example: maintain `DroppedFromPulse(x)`;
whenever `WorksFor(x, Pulse)` is deleted, insert `x`; the temporal constraint
becomes the static check `¬∃x (WorksFor(x,Pulse) ∧ DroppedFromPulse(x))`.
"Remember who, forget when." Natural implementation: active-database
triggers — abort a violating update, otherwise maintain the auxiliary
relations (Chomicki & Toman, TKDE 1995; Sistla & Wolfson). This is the same
self-maintainable-view idea as temporal vacuuming.

Alternative, operational approach: allow updates only through predefined
transactions whose possible sequences generate exactly the consistent
histories (Bidoit & de Amo).

### 4.4 Constraints on period-stamped tables

Two tuples may share a key without violating it, so a unique index on the key
no longer enforces a primary key. Constraints come in two flavours:

- **Sequenced** (the default meaning of a static constraint): must hold in
  every snapshot. Sequenced PK = `WITHOUT OVERLAPS` + NOT NULL on key
  columns. Sequenced FK = child period covered by the union of contiguous
  parent periods.
- **Representational**: about the encoding itself, e.g., "tuples must be
  coalesced whenever possible".
- **Non-sequenced** constraints over interval variables with Allen relations
  ("salaries never decrease": `Earns(x,y|i1) ∧ Earns(x,z|i2) ∧ before(i1,i2)
  ⇒ y ≤ z`).
- **Current** constraints (only the current snapshot), which is what SQL:2011
  applies to system-versioned tables.

Efficient sequenced constraint checking: Li, Snodgrass, Deng, Gattu &
Kasthurirangan (ICDE 2001).

#### Sequenced primary key check (O(log n))

Invariant: for each key `k`, stored periods are pairwise disjoint, hence
ordered identically by start and by end. With a B-tree on `(k, s)`:

```
insert (k, [s, e)):
    p = entry with key k and the greatest start < e      # one probe
    conflict  iff  p exists and p.e > s
```

Proof: any overlapping `x` has `x.s < e`; among such tuples `p` has the
largest start, hence (disjointness) the largest end; if `p.e ≤ s` no tuple
overlaps. UPDATE = delete + insert under the same check (exclude the row's
old version).

#### Sequenced foreign key check

Parents for key `k` are disjoint (sequenced PK on the parent):

```
check child (k, [s, e)):
    p = parent with key k and greatest start <= s
    if p is null or p.e <= s: fail
    cover = p.e
    while cover < e:
        p = next parent of k in start order
        if p is null or p.s != cover: fail       # gap: parents must meet
        cover = p.e
```

Parent side: `DELETE`/`UPDATE … FOR PORTION OF` on a parent must find
children overlapping the removed portion and restrict (or cascade with the
same portion).

#### Concurrency (the classic bug)

Two concurrent inserts `(k,[1,5))` and `(k,[3,8))` touch different index
keys, so a unique index or "check then insert" under snapshot isolation lets
both commit (a write-skew pattern). Correct options: key-range (next-key)
locking covering the gap from the predecessor entry to `e`; predicate locks
on `(k, [s,e))`; or exclusion-constraint style: insert the index entry,
then re-scan for overlapping entries including uncommitted ones and wait for
their transactions to finish before deciding. The FK check has the mirror
race (parent portion deleted while a child referencing it is inserted): take
shared range locks on the covering parent rows.

Sources: EDBS entries Temporal Extensions in the SQL Standard (p.3963),
TSQL2 (p.4246), SQL-Based Temporal Query Languages (p.3683), Temporal
Integrity Constraints (p.3980), Temporal Data Models (p.3940), Current
Semantics (p.716), Nonsequenced Semantics (p.2506), Transaction Time
(p.4200), Valid Time (p.4359), Period-Stamped Temporal Models (p.2742).
