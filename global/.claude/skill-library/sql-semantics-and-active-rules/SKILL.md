---
name: sql-semantics-and-active-rules
description: "Use when implementing, reviewing or testing the semantic contract of an SQL engine or its active-database features: NULL and three-valued logic, bag/duplicate semantics, set operators, aggregates over empty input, outer-join padding, window frames, DML/constraint timing, MERGE, keys, catalog, isolation levels as the standard defines them, ODBC/JDBC cursor and prepare semantics, stored procedures, triggers and ECA rules. Triggers on NOT IN with NULL, IS DISTINCT FROM, COUNT(*) vs COUNT(col), GROUP BY NULL, INTERSECT ALL, EXCEPT ALL, ROWS vs RANGE vs GROUPS, peers, LAST_VALUE, deferrable constraint, SET CONSTRAINTS, Halloween problem, MERGE cardinality violation, MATCH SIMPLE, INFORMATION_SCHEMA, SQLSTATE, holdable cursor, prepared statement, SECURITY DEFINER, BEFORE/AFTER/INSTEAD OF trigger, transition table, coupling mode, composite event, triggering graph, confluence, collation, sqllogictest. Apply even when phrased as 'why does this query return no rows' or 'is this rewrite legal'."
---

# SQL Semantics and Active Rules

This skill owns the *meaning* of SQL — the observable contract every planner
rewrite and executor kernel must preserve — and the active machinery (triggers,
ECA rules, coupling modes) that runs inside DML and commit. The single most
important idea: SQL is a **bag algebra under Kleene three-valued logic with two
notions of sameness** (`=` and NOT DISTINCT), and statements are **set-oriented
and atomic**; nearly every wrong-results bug is one of these leaking.

## Mental model

- **Values**: one NULL; comparisons yield UNKNOWN; filters keep TRUE; CHECK rejects FALSE.
- **Collections**: bags; `ALL` operators add/min/monus multiplicities, set forms
  apply δ; grouping-like operators treat NULLs as equal, joins/IN/UNIQUE do not.
- **Statements**: computed on the pre-statement state, applied as a unit,
  constraints checked at statement end (or commit if deferred); failure leaves no trace.
- **Rules**: event (DML, transaction, time, signal; possibly composite) →
  condition → action, each coupled immediate, deferred (pre-commit) or detached
  (separate, possibly causally dependent txn). SQL triggers = immediate/immediate.
- **Clients**: prepare/describe/execute, typed parameters, cursors (sensitivity,
  scroll, hold), block fetch with portal suspension, SQLSTATE codes.

## Core invariants

1. A WHERE/ON/HAVING/FILTER/WHEN predicate passes a row iff it evaluates to
   TRUE; a CHECK constraint fails a row iff it evaluates to FALSE.
2. `NULL AND FALSE = FALSE`, `NULL OR TRUE = TRUE`, `NOT UNKNOWN = UNKNOWN`.
3. `x NOT IN (S)` is UNKNOWN whenever S is non-empty, has no match and holds a
   NULL, or x is NULL and S is non-empty; it is TRUE for empty S regardless of x.
4. `x θ ALL (∅)` is TRUE and `x θ ANY (∅)` is FALSE, even for NULL x.
5. Scalar aggregation over empty input returns exactly one row (COUNT 0,
   others NULL); grouped aggregation over empty input returns zero rows;
   `GROUP BY ()` returns one.
6. GROUP BY, DISTINCT, UNION/INTERSECT/EXCEPT and PARTITION BY place all
   NULLs in one group; equi-joins and IN never match NULL to NULL.
7. `UNION ALL` = m+n, `INTERSECT ALL` = min(m,n), `EXCEPT ALL` = max(m−n,0);
   set forms equal δ applied to operands/results; INTERSECT binds tighter.
8. `x IN (SELECT …)` never increases outer multiplicity.
9. A LEFT JOIN with only left-side or ON predicates returns ≥ 1 row per left
   row; padding NULLs are indistinguishable from stored NULLs.
10. With a window ORDER BY and no frame, the frame is RANGE UNBOUNDED
    PRECEDING to the current row's last peer; without ORDER BY, the partition.
11. A data-change statement reads only the pre-statement state (no Halloween
    effects); `SET x = y, y = x` swaps.
12. Non-deferred constraints are checked at end of statement, deferred ones at
    COMMIT/`SET CONSTRAINTS … IMMEDIATE`; a commit-time failure rolls back all.
13. A failing statement undoes its own effects (cascades, trigger actions) only.
14. MERGE raises a cardinality violation when one target row is matched by more
    than one source row; WHEN clauses are tried in order.
15. A statement trigger fires once per statement, even for zero rows; AFTER
    triggers observe the complete post-statement state.
16. Sequence/identity values are never rolled back.
17. The prepare-time result description equals the shape of rows returned.
18. Equal-under-collation strings hash and group identically.

## Design space & trade-offs

| Decision | Option | When it wins | Cost / risk |
|---|---|---|---|
| NOT IN execution | null-aware anti-join | always correct, hash speed | needs inner-has-NULL/empty tracking, multi-column partial probes |
| | rewrite to anti-join | x and y provably NOT NULL | wrong results if nullability proof is sloppy |
| Unique check timing | per-row index probe | simple, PG default | violates standard for `id = id + 1` |
| | provisional insert + end-of-statement recheck | standard semantics, deferrable | pending-key list, recheck cost |
| FK enforcement | per-row trigger probes | small DML | O(rows) probes |
| | statement-end anti-join of changed keys | bulk DML | memory for change sets |
| Halloween protection | MVCC command-id visibility | MVCC engines | none extra |
| | spool target rows first | in-place engines | materialisation |
| DDL | transactional vs implicit commit | safe migrations vs simplicity | catalog MVCC/locks vs non-atomic migrations |
| AFTER ROW firing | queued to statement end (standard, PG) | consistent state, no mutating-table errors | queue memory |
| | per row (Oracle, MySQL) | low latency | partial states, mutating-table restrictions |
| Rule coupling | immediate | integrity, simple | latency on writers |
| | deferred (pre-commit) | multi-statement invariants | commit-time failures |
| | detached causally dependent (outbox/NOTIFY) | side effects with external systems | eventual, needs durable queue |
| Cursor sensitivity | snapshot vs materialise | cheap in MVCC vs holdable/scrollable | holds vacuum horizon vs spill I/O |
| Window aggregation | sliding/invertible | SUM/COUNT on moving frames | float drift; not for MIN/MAX |
| | segment tree | arbitrary frames, EXCLUDE, parallel | O(n log n), memory |
| Collations | deterministic (byte tie-break) | hash on bytes, fast | no case-insensitive equality |
| | non-deterministic (ICU strength) | CI/AI semantics | must hash sort keys everywhere |

## Algorithms that matter

- **Null-aware anti-join** (O(|R|+|S|)): build hash on S, track
  `inner_empty`, `inner_has_null`; probe emits x iff inner empty, or x non-NULL,
  no NULL inner, no match. → `references/null-3vl-and-bag-edge-cases.md` §4.
- **Null-rejection test**: substitute NULL for the nullable side's columns,
  constant-fold; not TRUE ⇒ the predicate converts the outer join to inner.
- **Statement execution with triggers and constraints** (SQL:1999 model):
  BEFORE STATEMENT → per row BEFORE ROW + apply + capture transition → cascades
  (recursive) → immediate constraint checks → AFTER ROW/STATEMENT with
  transition tables. → `references/eca-rules-and-trigger-execution.md` §6.
- **Deferred-constraint queue**: per-transaction list of (constraint, key);
  drain at COMMIT or SET CONSTRAINTS IMMEDIATE; failure ⇒ rollback (40002).
- **Window frame bounds**: peer-group boundary vector per partition; ROWS by
  index arithmetic, RANGE by monotone two-pointer key search with overflow
  saturation, GROUPS by peer-group index. → `references/window-function-semantics.md`.
- **Composite event detection**: event graph, per-node buffers consumed per
  context (recent/chronicle/continuous/cumulative); cost = context + buffer GC.
- **Triggering-graph termination check**: edge ri→rj if ri's action write-set
  intersects rj's event set; acyclic ⇒ termination; refine with activation
  (condition) analysis; confluence needs pairwise commutativity of unordered
  rules. O(rules² × ops) at rulebase DDL time.
- **Portal suspension**: run to n rows, freeze operator state, resume on fetch.

## Failure modes & classic bugs

- Boolean kernels that propagate NULL like arithmetic (breaks A2) or treat
  UNKNOWN as FALSE before NOT (breaks A11).
- NOT IN planned as NOT EXISTS/anti-join without NOT NULL proof (B4).
- Hash join key equality reused from hash aggregation, so NULL keys join (E6).
- Scalar aggregate over empty input emits no row; SUM of nothing returns 0.
- Decorrelated COUNT subquery uses COUNT(*) over an outer join (empty → 1).
- Set-semantics rewrites (self-join elimination, subquery flattening,
  distributivity) applied to bags (D7, D8, B9).
- Window default frame implemented as ROWS; LAST_VALUE over the partition;
  predicate on a non-partition column pushed below a window.
- Per-row unique checks reject `UPDATE … SET id = id + 1` (PG, DuckDB).
- Statement failure leaves trigger or cascade effects behind.
- Statement triggers skipped for 0-row statements; trigger order follows OID/hash;
  unbounded trigger recursion crashes the backend instead of raising.
- Prepared statement returns rows of a new shape after ALTER TABLE.
- Byte hashing with a case-insensitive collation; LIKE-prefix range scan under a
  linguistic collation; index order corrupted by a collation library upgrade.

Detection: `references/semantic-test-vectors.slt` plus SQLancer TLP/NoREC.

## Implementation checklist (C/C++/Rust)

- Vectors carry a validity bitmap; AND/OR/NOT kernels implement Kleene logic
  over (value, validity); filters convert to selection vectors only at the
  clause boundary; CHECK uses a separate "not FALSE" kernel.
- Key comparators/hashers take `nulls_equal` and `nulls_first` parameters and
  the column collation; hashing for non-deterministic collations uses the sort
  key (Rust: `trait KeyHasher { fn hash(&self, v: &Datum, coll: &Collation) }`).
- Planner tracks per-node properties: nullability per column, unique keys,
  functional dependencies, and a top-down `duplicate_insensitive` flag gating
  set-semantics rules.
- Aggregate states distinguish "no input" from zero; scalar vs grouped is a flag.
- Statement execution context: snapshot + command id, savepoint for
  statement atomicity, after-trigger queue, transition-table stores
  (spillable), cascade/nesting depth counter with a configurable cap.
- Transaction context: deferred-constraint queue, deferred-trigger queue,
  pre-commit hook, post-commit durable notification queue.
- Catalog: OIDs, dependency table, per-index collation provider+version,
  invalidation messages at DDL commit, plan-cache dependency lists.
- Protocol: Parse/Bind/Describe/Execute(max_rows)/Sync with named and unnamed
  statements and portals; out-of-band cancel; SQLSTATE in every error.
- Routines: volatility/determinism/strictness/security attributes in the
  catalog, enforced where cheap (no MODIFIES SQL DATA in index expressions);
  pinned name-resolution path for definer-rights routines.

## How to test it

- Gate every build on `references/semantic-test-vectors.slt` (≈200 records,
  verified on PostgreSQL 16.15 and DuckDB 1.1.3); add `skipif` rows only for
  documented dialect choices.
- Differential testing against PostgreSQL, SQLite and DuckDB with an
  allow-list of known deviations (null ordering, integer division, 1/0).
- Metamorphic oracles: TLP (`Q = Q∧p ⊎ Q∧¬p ⊎ Q∧(p IS NULL)`), NoREC;
  every rewrite rule fuzzed with inputs containing duplicates and NULLs.
- Window oracle: each window query vs its correlated-subquery definition.
- Isolation: isolationtester-style specs, Hermitage (`concurrency-control-theory`).
- Triggers: 0-row firing counts, order stability, atomicity on failure,
  recursion-limit errors, deferred failures at COMMIT.
- Client API: describe/actual type parity, block fetch 1/7/1000 = full fetch,
  cancel storms, DDL under prepared statements.

## Expert review questions

1. Where in the code is "TRUE-only" vs "not-FALSE" decided, and is CHECK
   evaluated through a different path from WHERE?
2. How does the planner prove NOT NULL before turning NOT IN into an
   anti-join, and what is the fallback operator?
3. Which hash tables use `=` and which NOT DISTINCT — is that a type-level
   distinction or a convention?
4. Which rewrite rules assume set semantics, and what property gates them?
5. Does a scalar aggregate over an empty, filtered, or partitioned-away input
   still emit its single row in parallel plans?
6. Is UNIQUE checked at statement end? What happens for `id = id + 1` and for
   a deferred PK across two statements?
7. What exactly is undone when a statement fails after its cascades fired
   AFTER triggers that wrote other tables?
8. How is MERGE's one-match-per-target rule enforced, and is MERGE safe against
   concurrent inserts at READ COMMITTED?
9. In what order do triggers fire, is it documented and stable, and what bounds
   recursion?
10. Which coupling modes does the engine offer, and where is the durable queue
    for actions that must happen only after commit?
11. Does the window operator implement RANGE offsets with overflow saturation
    and NULL peer groups, and GROUPS/EXCLUDE without falling back to O(n²)?
12. What does a prepared statement do after the referenced table changes shape?
13. How are holdable and scrollable cursors materialised, and what snapshot
    or locks do they keep?
14. Which collation version built each index, and what happens when the
    library changes?
15. Do definer-rights routines pin name resolution and avoid caching
    authorisation decisions in plans?

## Go deeper

- `references/null-3vl-and-bag-edge-cases.md` — predicates, NOT IN/quantifiers,
  aggregates, outer joins, set operators, any possibly set-only rewrite; bag laws.
- `references/ddl-dml-constraints-and-catalog.md` — SQL revisions/parts, atomicity,
  Halloween, constraint timing, FKs, MERGE, DDL/catalog, keys, standard isolation
  levels, Unicode/collation, SQLSTATE.
- `references/window-function-semantics.md` — OVER clauses: defaults, peers,
  frame legality, EXCLUDE, function families, legal rewrites.
- `references/eca-rules-and-trigger-execution.md` — triggers, rule systems,
  coupling modes, composite events, termination/confluence, ADBMS architecture.
- `references/client-interfaces-and-procedures.md` — wire protocol, ODBC/JDBC,
  cursors, prepared statements, stored procedures/UDFs, routine plan caching.
- `references/semantic-test-vectors.md` + `.slt` — runnable verified catalogue
  and observed PostgreSQL/DuckDB deviations.
- `references/edbs-entries.md` — every bundle entry with page and use.

## Related skills

- `sql-frontend` (parse/bind) and `query-plan-design` (operator contracts): this
  skill defines what the bound plan and each operator must *mean*.
- `query-optimizer`, `relational-theory`: rewrite machinery and algebraic laws;
  this skill supplies their NULL/bag guards.
- `query-execution-advanced`: physical window/sort/aggregate/set-op operators;
  this skill is their correctness spec. `cardinality-and-statistics`: catalog stats.
- `materialized-views-ivm`: view updates, assertions, transition-table maintenance.
- `transactions-and-recovery`, `concurrency-control-theory` (ANSI-level critique),
  `recovery-and-durability`: mechanisms behind isolation, savepoints, rollback.
- `stream-processing-engines`: CEP beyond in-DBMS composite events;
  `temporal-databases`: SQL:2011 periods; `database-security-internals`: privileges
  and definer rights in depth.
- `query-engine-testing`, `tuning-and-benchmarking`: harnesses around these vectors;
  `dbms-architecture`: where rule manager, catalog and protocol sit;
  `distributed-dbms-design`, `parallel-database-systems`: online schema change,
  determinism under parallel plans.

## Grounding

EDBS (29 entries; full table in `references/edbs-entries.md`): Active Database
Coupling Modes p.25, Execution Model p.27, Knowledge Model p.28, ADBMS
Architecture p.29, Rulebase p.35, Active Database p.35; Bag Semantics p.252;
Composite Event p.531; DDL p.748; Data Dictionary p.749; DML p.792; Database
Schema p.973; Database Trigger p.985; ECA Rule Action p.1262, Condition p.1263,
ECA Rules p.1263; Event in Active Databases p.1371; Event Specification p.1389;
JDBC p.2045; Key p.2057; Null Values p.2522; ODBC p.2596; QUEL p.2975; Query
Language p.2994; SQL p.3666; SQL Isolation Levels p.3681; Stored Procedure
p.3764; Unicode p.4335; Window Operator in RDBMS p.4693.

Seminal work: Codd (CACM 1970); Chamberlin & Boyce, SEQUEL (1974); Gray et
al., degrees of consistency (1976); Dayal et al., HiPAC (SIGMOD Record 1988);
Widom & Finkelstein, set-oriented production rules (SIGMOD 1990); Aiken, Widom
& Hellerstein, termination/confluence (SIGMOD 1992); Chakravarthy et al.,
Snoop contexts (VLDB 1994); Berenson et al., critique of ANSI isolation (SIGMOD
1995); Cochrane, Pirahesh & Mattos, triggers + constraints (VLDB 1996); Paton &
Diaz survey (ACM CSUR 1999); Chaudhuri & Vardi, bag CQs (PODS 1993); Ioannidis &
Ramakrishnan (TODS 1995); Leis et al., window functions (VLDB 2015); Rigger &
Su, TLP/NoREC (2020). Systems: PostgreSQL, Oracle, SQL Server, DB2, MySQL,
DuckDB, Starburst, POSTGRES rules.
