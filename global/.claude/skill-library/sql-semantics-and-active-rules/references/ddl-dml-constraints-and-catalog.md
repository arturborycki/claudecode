# DDL/DML semantics, constraints, keys, catalog, isolation levels and character data

The contract an engine signs when it says "SQL": statements are set-oriented
and atomic, constraints are checked at defined points, the catalog describes
every object and is itself queryable, transaction isolation is named by the
standard's levels, and character comparison is governed by collations. This
file is the implementer's reading of those rules.

---

## 1. SQL's evolution — what each revision obliges an implementer to support

| Revision | Size (approx.) | Implementer-relevant additions |
|---|---|---|
| SEQUEL (1974), SEQUEL 2 (1976) | — | query blocks, grouping, set ops, aggregates; then DML, views, access control, assertions, triggers (System R) |
| SQL-86 (ANSI X3.135-1986; ISO 9075:1987) | <100 pp | basic queries, updates, table definitions |
| SQL-89 "Integrity Enhancement" | ~120 pp | PRIMARY KEY, FOREIGN KEY, UNIQUE, CHECK, DEFAULT |
| SQL-92 | ~600 pp | orthogonality (subqueries as tables/scalars), datetime types, INTERSECT/EXCEPT, outer joins, INFORMATION_SCHEMA, ALTER TABLE, isolation levels, deferrable constraints, CAST; conformance levels Entry/Intermediate/Full (NIST testing ended 1996) |
| SQL/CLI (1995), SQL/PSM (1996) | — | call-level API (basis of ODBC); stored procedures with control flow, handlers |
| SQL:1999 | >2000 pp, split into parts | triggers, recursive queries, LOBs, BOOLEAN, ROLLUP/CUBE/GROUPING SETS, UDTs/methods, user-defined functions, roles, functional-dependency-aware GROUP BY |
| SQL:2003 | — | window functions fully integrated, MERGE, sequence generators, identity and generated columns, SQL/XML (Part 14) |
| SQL:2006 | — | SQL/XML with XQuery |
| SQL:2008 | — | TRUNCATE, INSTEAD OF triggers, FETCH FIRST/OFFSET, MERGE with DELETE and conditional WHEN clauses, ORDER BY outside cursors |
| (SQL3 drafts, 1996) | — | SQL/Temporal "Part 7" with a PERIOD type was accepted as a work item but never published; temporal support only arrived in SQL:2011 (see `temporal-databases`) |
| SQL:2011 | — | temporal: application-time periods, system-versioned tables; window navigation functions and GROUPS frames |
| SQL:2016 | — | JSON functions, row pattern recognition (MATCH_RECOGNIZE), polymorphic table functions, LISTAGG |
| SQL:2019 | — | Part 15 multidimensional arrays |
| SQL:2023 | — | Part 16 property-graph queries (SQL/PGQ), JSON type, UNIQUE NULLS [NOT] DISTINCT, ANY_VALUE, GREATEST/LEAST |

Rows up to SQL:2006 follow EDBS; later rows are > **Beyond EDBS** (the entry
stops at "more than 3600 pages").

Standard parts an engine team actually reads: Part 1 Framework, **Part 2
Foundation** (almost all semantics), **Part 3 CLI**, **Part 4 PSM**, Part 9 MED
(foreign data wrappers), Part 10 OLB (embedded SQL in Java), **Part 11
Schemata** (INFORMATION_SCHEMA), Part 13 JRT (Java routines), Part 14 XML,
Part 15 MDA, Part 16 PGQ. Conformance is "Core SQL" plus optional features
named by IDs; claim features individually.

Design goals stated by its authors still explain many rules: a nonprocedural
language for an optimizing compiler, relationally complete; keyboard-friendly
English keywords; one language for query, update and administration (so DDL
runs online, inside sessions, not via offline reconfiguration); usable for both
decision support and OLTP (hence prepared/parameterized execution). Criticisms
the standard later patched: missing keys/RI (fixed in 89), lack of closure and
unnamed result columns (fixed in 92), NULLs, duplicates, and the impedance
mismatch with host languages (addressed by PSM, CLI, embedded SQL).

## 2. Statement semantics

### 2.1 Statement-level atomicity
An SQL statement that raises an exception has **no effect** on SQL-data: all
rows it inserted, updated or deleted — including cascaded referential actions
and trigger effects — are undone, but the transaction continues (vector H3).
Exceptions of class 40 (serialization failure 40001, deadlock, integrity
failure at commit 40002) roll back the whole transaction.

Implementation: an implicit savepoint per statement (Oracle, DB2), or a
subtransaction/command id that is marked aborted (PostgreSQL, which however
puts the *transaction* in an aborted state after any error until `ROLLBACK`
or `ROLLBACK TO SAVEPOINT` — a deviation clients must handle). Costs to budget:
undo for statement rollback must be cheap (per-statement undo chains, not a full
transaction rollback); savepoints must nest (triggers and procedures add levels).

### 2.2 Set-oriented semantics and the Halloween problem
Every data-change statement behaves as if (1) the set of target rows and all
new values were computed against the state at statement start, then (2)
applied. Consequences that must hold:
- `UPDATE sw SET x = y, y = x` swaps (H1; MySQL evaluates left to right).
- Subqueries in `SET`/`WHERE` see the pre-statement state (H5, H6).
- `INSERT INTO h SELECT … FROM h` reads a snapshot and terminates (H4).
- An `UPDATE` scanning an index on the column it raises must not revisit moved
  rows (the **Halloween problem**, found in System R).

Mechanisms: **command-id visibility** (PostgreSQL stamps each tuple version
with the creating command id; a scan ignores versions created by the current
command), **phase separation / spooling** (materialize target RIDs and new
values first — an "eager spool" in SQL Server plans), or planner avoidance of
access paths on modified columns. MVCC engines get much of this from the
snapshot; in-place-update engines must spool. Test with an index on the updated
column and a predicate that the update keeps satisfying.

### 2.3 Constraint checking time
| Declaration | Checked |
|---|---|
| `NOT DEFERRABLE` (default) | at the end of each SQL statement ("immediate") |
| `DEFERRABLE INITIALLY IMMEDIATE` | end of statement, but `SET CONSTRAINTS … DEFERRED` can postpone |
| `DEFERRABLE INITIALLY DEFERRED` | at COMMIT (or when `SET CONSTRAINTS … IMMEDIATE` is executed) |

"Immediate" means **end of statement, not per row**: `UPDATE u SET id = id+1`
over keys 1,2,3 must succeed. PostgreSQL checks non-deferrable UNIQUE/PK per
row and fails it; declaring the key `DEFERRABLE INITIALLY IMMEDIATE` restores
standard behaviour (H2). A failing deferred check at COMMIT rolls back the
transaction (H9). `SET CONSTRAINTS … IMMEDIATE` must verify all pending
violations at that moment.

Implementation patterns:
- **Per-row index check + deferred re-check list**: insert into the unique
  index allowing a provisional duplicate, record (index, key) in a pending list,
  and at statement end (or commit) re-probe each recorded key. PostgreSQL's
  deferrable unique indexes work this way.
- **FK as system AFTER triggers** that queue (row, constraint) events and run at
  statement end or commit (PostgreSQL, and the model in Cochrane, Pirahesh &
  Mattos, VLDB 1996).
- Bulk/statement-level FK checking: one anti-join of the changed child keys
  against the parent at statement end beats per-row probes for large DML.
- CHECK: UNKNOWN passes (A17). NOT NULL is a special CHECK.
- `CREATE ASSERTION` (schema-wide constraints, SQL-92) is essentially
  unimplemented in products because efficient checking is incremental view
  maintenance of a boolean query (see `materialized-views-ivm`).

### 2.4 Referential integrity
- **MATCH SIMPLE** (default): if any FK column is NULL the row is exempt
  (H8). **MATCH FULL**: all NULL or none NULL. **MATCH PARTIAL**: the non-NULL
  columns must match some parent row (rarely implemented).
- Actions `ON DELETE/UPDATE`: `NO ACTION` (checked at end of statement,
  deferrable), `RESTRICT` (checked immediately, never deferred — fails even if the
  statement would repair the violation), `CASCADE`, `SET NULL`, `SET DEFAULT`
  (H14).
- Cascades are part of the triggering statement: they run inside its atomic
  unit, fire the child table's triggers, and may cascade further. Diamond
  cascade paths that would modify the same row in conflicting ways raise
  **triggered data change violation** (SQLSTATE 27000).
- The parent side needs an index on the referenced key (required: it must be
  PK/UNIQUE); the child side should have one on the FK columns or every parent
  delete is a child scan — lint for it.

### 2.5 MERGE
Semantics (SQL:2003, extended in SQL:2008): join target with source on the
`ON` condition; for each source row, the first `WHEN [NOT] MATCHED [AND cond]`
clause whose condition holds determines the action (H12). Rules:
- A target row matched by more than one source row is a **cardinality
  violation** (SQLSTATE 21000; H11). Engines must detect it — typically by
  tracking target row ids touched in this statement.
- Source rows not matched and not handled by a clause are ignored.
- `WHEN NOT MATCHED BY SOURCE` (act on target rows with no source row) is a
  SQL Server extension, also in PostgreSQL 17.
- MERGE is **not** an atomic upsert under concurrency: at READ COMMITTED a
  concurrent insert of the same key can make the NOT MATCHED branch fail with a
  unique violation. Atomic insert-or-update needs a speculative-insertion
  protocol (PostgreSQL `INSERT … ON CONFLICT`) or key-range locking (SQL Server
  MERGE with HOLDLOCK).
- Triggers: statement-level triggers for each action type mentioned fire;
  row-level triggers fire per affected row per action.

### 2.6 Views and DML through views
A view is updatable when each view row maps to exactly one base-table row so
updates translate unambiguously. `WITH [CASCADED|LOCAL] CHECK OPTION` rejects
changes producing rows invisible through the view (H13). Non-updatable views can
take `INSTEAD OF` triggers. View-update theory and materialized views belong to
`materialized-views-ivm`.

### 2.7 Other statement semantics worth a test each
- `TRUNCATE` does not fire DELETE triggers; it may be non-transactional or
  take an exclusive lock; it typically resets nothing about sequences unless
  asked (`RESTART IDENTITY`).
- Sequences/identity values are **not** rolled back (H10) — gaps are normal.
  Do not promise gap-free identities.
- `DEFAULT` expressions are evaluated per row; volatile defaults (`now()` vs
  `clock_timestamp()`) must have documented statement/transaction stability.
- `SELECT DISTINCT … ORDER BY e` requires `e` in the select list (K5).

## 3. DDL semantics and schema change

The schema (database definition) declares object types, relationships and
constraints once; data must conform. Engines differ in whether DDL is
transactional:

| Engine family | DDL in transactions |
|---|---|
| PostgreSQL, DB2, SQL Server (mostly) | transactional, rollback-able |
| Oracle, MySQL | implicit commit before/after DDL (MySQL 8.0 DDL is atomic but still auto-commits) |

Requirements regardless of choice:
1. **Catalog versioning + plan invalidation**: every cached plan records the
   catalog objects (and versions) it depends on; DDL bumps versions and
   invalidates. Prepared statements must re-plan or fail cleanly
   (result-shape changes are a client-visible error).
2. **Lock protocol**: DDL takes a strong lock on the object (or a metadata
   lock, MySQL MDL); long-running queries block DDL and queued DDL blocks new
   queries — offer lock timeouts and online variants.
3. **Online schema change** in distributed engines: intermediate states so
   nodes on adjacent schema versions remain compatible (F1: delete-only →
   write-only → public; Rae et al., VLDB 2013).
4. `DROP … RESTRICT | CASCADE` needs a dependency graph (views, FKs,
   triggers, routines, defaults, sequences owned by columns).

## 4. Keys

- A **superkey** K of R: K → R holds in F⁺ (the closure of the declared FDs);
  equivalently no two tuples of any *valid* instance agree on K.
- A **candidate (minimal) key**: a superkey none of whose proper subsets is
  a superkey. A schema may have several (e.g., `CustomerID` and
  `(Name, Address)`).
- **Primary key**: the chosen candidate key; SQL forces its columns NOT NULL.
- Key-ness is a property of the schema, not of an instance: a column that
  happens to be unique today is not a key.
- **BCNF**: every non-trivial FD X → Y on R has X a superkey.

What the engine does with keys:
- Enforcement through unique indexes (NULL handling per §3 of the NULL file).
- **Uniqueness inference** for the optimizer: DISTINCT elimination, join
  elimination (FK→PK with NOT NULL FK and no columns used from the parent),
  IN/EXISTS → inner join, GROUP BY simplification, functional-dependency GROUP
  BY (K4).
- **Informational / unenforced constraints** (DB2, Snowflake, BigQuery; the
  standard's NOT ENFORCED characteristic) feed the optimizer without
  enforcement cost. A wrong informational constraint produces wrong results —
  treat as a user contract and document it.

## 5. Catalog / data dictionary

Two meanings: human documentation of an information system, and — what
matters here — the **system catalog**, a database of metadata managed by and
tightly coupled to the DBMS, used by the binder, optimizer, executor and
security layer. Since System R and INGRES the catalog has been stored as
relations queried with the engine's own machinery.

Contents (minimum): tables, columns, types; views (definition text and parsed
form); constraints incl. referential ones; indexes and their columns/ordering;
schemas/namespaces; users, roles, privileges; storage allocation parameters;
statistics; stored procedures, functions and triggers; sequences; collations
and character sets; dependency records.

Standard surface: SQL-92 introduced standardized catalog views —
`INFORMATION_SCHEMA` (Part 11) defined over a conceptual `DEFINITION_SCHEMA`.
Hierarchy: SQL-environment → catalogs → schemas → schema objects. Clients
(ODBC `SQLTables/SQLColumns`, JDBC `DatabaseMetaData`) are implemented as
queries on it, so it must be fast and stable.

Engine design checklist:
1. **Bootstrap**: catalog tables describe themselves; hard-code the
   descriptors of the core catalog relations and build the rest by DDL at
   initdb time.
2. **Stable identifiers** (OIDs) separate from names; renames must not break
   dependencies or plans.
3. **Catalog cache** per session/process (PostgreSQL syscache/relcache) with
   **invalidation messages** shipped at DDL commit; readers must see a
   catalog state consistent with their transaction (MVCC catalog snapshots) —
   or take locks that freeze the object.
4. **Dependency table** for DROP CASCADE/RESTRICT and for "which plans
   reference this".
5. **Versioned catalog** if the engine supports time travel or lake-table
   snapshots: the schema must be resolvable as of the data snapshot (Iceberg
   stores schema ids per snapshot).
6. Statistics live in the catalog but must not be MVCC-heavy hot rows; update
   them out of band (see `cardinality-and-statistics`).

## 6. Isolation levels as the standard states them

The SQL levels derive from Gray et al.'s "degrees of consistency" (1976) and
are defined by which phenomena they forbid:

- **P1 dirty read**: `w1[x] … r2[x]` before T1 ends — T2 may read a value that
  never existed if T1 aborts.
- **P2 non-repeatable read**: `r1[x] … w2[x] c2 … r1[x]` returns a different
  value.
- **P3 phantom**: T1 reads `{rows : P}`; T2 inserts/updates/deletes rows
  changing that set; T1's re-read returns a different set.

| Level | P1 | P2 | P3 |
|---|---|---|---|
| READ UNCOMMITTED | possible | possible | possible |
| READ COMMITTED | prevented | possible | possible |
| REPEATABLE READ | prevented | prevented | possible |
| SERIALIZABLE | prevented | prevented | prevented — and executions must be serializable |

Rules an engine must honour:
- `SET TRANSACTION ISOLATION LEVEL …` per transaction; access mode
  `READ ONLY | READ WRITE`. The standard's default is SERIALIZABLE; products
  default to READ COMMITTED (PostgreSQL, Oracle, SQL Server, DB2's CS) or
  REPEATABLE READ (MySQL InnoDB).
- An implementation may run a transaction at a *stronger* level than
  requested, never weaker. (PostgreSQL maps READ UNCOMMITTED to READ COMMITTED;
  its REPEATABLE READ is snapshot isolation, which forbids P3 as defined.)
- Levels are per transaction, so a SERIALIZABLE transaction can read data
  written by a READ COMMITTED one — consistency guarantees only hold if every
  updater runs SERIALIZABLE.
- Serialization failures surface as SQLSTATE 40001; clients must retry.
- Throughput motivation: one simulation study (Bober & Carey, ICDE 1992)
  measured READ COMMITTED at 2.5–3x the throughput of SERIALIZABLE.

The phenomena-based definitions are ambiguous (broad vs strict readings),
omit dirty writes (P0), lost updates, read/write skew, and cannot place
snapshot isolation — the critique of Berenson et al. (SIGMOD 1995) and Adya's
generalized definitions. Mechanisms and the critique live in
`concurrency-control-theory` (references/isolation-levels-and-anomalies.md).

## 7. Character data: Unicode, collation, comparison and indexing

Unicode assigns code points to the characters of all significant scripts.
Encodings: **UTF-8** (variable 1–4 bytes, ASCII-compatible, byte order =
code-point order, the default storage choice), **UTF-16** (2 or 4 bytes via
surrogate pairs; Java, Windows, SQL Server `NVARCHAR`), **UTF-32** (fixed 4
bytes). The entry adds little beyond this; the engine consequences below are
> **Beyond EDBS:**

1. **Length semantics.** `CHAR_LENGTH` counts characters (code points),
   `OCTET_LENGTH` bytes (J2). User-perceived characters (grapheme clusters)
   are a third unit; SQL functions do not use it. `SUBSTRING` offsets are code
   points — never slice UTF-8 at byte offsets.
2. **Normalization.** Canonically equivalent strings (`é` U+00E9 vs `e`+U+0301)
   are different code-point sequences; binary comparison says unequal (J3).
   Either normalize on input (NFC) or offer `NORMALIZE()` / `IS NORMALIZED`
   (standard functions; PostgreSQL 13+).
3. **Collation** determines `=`, `<`, `ORDER BY`, `GROUP BY`, `DISTINCT`,
   `UNIQUE`, `LIKE` and `MIN/MAX`. Unicode Collation Algorithm (UTS #10) with
   CLDR tailorings, usually via ICU: multi-level comparison — primary (base
   letter), secondary (accents), tertiary (case), quaternary. "Case-insensitive"
   = compare at secondary strength; "accent-insensitive" = primary.
4. **Deterministic vs non-deterministic collations.** A deterministic
   collation breaks ties by code point, so equal ⇔ bytewise equal and hashing
   bytes is valid. Non-deterministic (case/accent-insensitive) collations make
   distinct byte strings equal; then **hash joins, hash aggregation, unique
   indexes and DISTINCT must hash the collation sort key** (ICU sort key or a
   normalized form), not the bytes. Mixing a byte-hash with collation-aware
   equality is a silent wrong-results bug.
5. **PAD SPACE vs NO PAD.** Under PAD SPACE, shorter strings are conceptually
   padded with spaces before comparison, so `'a' = 'a  '`. SQL `CHAR(n)`
   behaves so; PostgreSQL `text`/`varchar` are NO PAD (J1). MySQL's legacy
   collations are PAD SPACE, its `utf8mb4_0900_*` collations NO PAD.
6. **Index order depends on the collation implementation version.** An OS
   libc upgrade that changed collation rules (glibc 2.28, 2018) left PostgreSQL
   B-trees mis-ordered and unique constraints unenforced. Record the collation
   provider + version in the catalog per index, warn on mismatch, and prefer a
   pinned ICU version or a builtin code-point collation for keys.
7. **LIKE and range scans.** Rewriting `col LIKE 'abc%'` into
   `col >= 'abc' AND col < 'abd'` is valid only under a collation whose order is
   bytewise-prefix-compatible (C/binary, or PG's `text_pattern_ops`).
8. **Case mapping is locale-sensitive** (Turkish dotted/dotless i; `ß`
   uppercases to `SS`, changing length). `UPPER(x) = UPPER(y)` is not a
   substitute for a case-insensitive collation.
9. **Collation derivation.** The standard assigns each string expression a
   collation and a derivation (explicit via `COLLATE`, implicit from a column,
   or none); conflicting implicit collations in one comparison are an error
   unless resolved explicitly. Implement it in the binder, not at runtime.
10. **Sort performance**: compare precomputed sort keys (or an abbreviated
    fixed-width prefix of them) instead of calling the collator per comparison;
    PostgreSQL disabled abbreviated keys for libc collations after `strxfrm`
    inconsistencies — verify `strcoll(a,b)` agrees with `memcmp(strxfrm(a),
    strxfrm(b))` before relying on it.
11. MySQL's `utf8` (= `utf8mb3`) cannot store 4-byte characters (emoji,
    many CJK extension characters); `utf8mb4` is the real UTF-8.

## 8. SQLSTATE classes an engine must raise correctly

| Code | Meaning | Typical trigger |
|---|---|---|
| 21000 | cardinality violation | scalar subquery >1 row (C12); MERGE double match (H11) |
| 22003 | numeric value out of range | overflow (K2) |
| 22012 | division by zero | A16 |
| 22P02 / 22018 | invalid text representation / invalid character value for cast | K3 (PG / standard) |
| 23xxx | integrity constraint violation | unique, FK, CHECK, NOT NULL (PG: 23505/23503/23514/23502) |
| 27000 | triggered data change violation | conflicting cascades |
| 40001 | serialization failure | SERIALIZABLE/SI conflicts — retryable |
| 40002 | transaction integrity constraint violation | deferred constraint fails at COMMIT |
| 42xxx | syntax error or access rule violation | binder errors, privileges |

Clients and ORMs branch on these codes (retry on 40001, map 23505 to "already
exists"); emitting a generic error class is an API break.

---

Sources: SQL (p.3666); SQL Isolation Levels (p.3681); Data Definition Language
(p.748); Data Manipulation Language (p.792); Database Schema (p.973); Data
Dictionary (p.749); Key (p.2057); Query Language (p.2994); QUEL (p.2975);
Unicode (p.4335).
