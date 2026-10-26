# Semantic test vectors — catalogue, harness notes, and observed dialect deviations

`semantic-test-vectors.slt` (next to this file) holds ~200 sqllogictest
records encoding the SQL semantic edge cases from the other references. Every
record was executed in October 2026 against **PostgreSQL 16.15** (all records
that apply) and **DuckDB 1.1.3** (records not marked `onlyif postgresql` /
`skipif duckdb`) with zero failures. Use it as a conformance gate for a new
engine and as a regression suite for optimizer rewrites.

## 1. Format and conventions

```
statement ok | statement error         -- DDL/DML; "error" = any exception expected
query <types> [nosort|rowsort]          -- types: one letter per column (I int, T text)
<SQL, possibly multi-line>
----
<one result row per line, columns separated by one space>
```
- NULL prints as `NULL`; empty string as `(empty)`; booleans are avoided.
- Three-valued results are rendered portably:
  `CASE WHEN p THEN 'T' WHEN NOT p THEN 'F' ELSE 'U' END`.
- `rowsort` compares sorted rows (use whenever the query has no total ORDER BY).
- `onlyif postgresql` = PostgreSQL syntax or a standard behaviour DuckDB 1.1
  lacks; `skipif duckdb` = a DuckDB deviation from the standard (listed in §3).
- Records are stateful and ordered: fixtures at the top (`t`, `e`, `s`, `l`,
  `r`, `w`) are used throughout; DML groups create their own tables.

Runners: sqllogictest-rs (Rust; used by DataFusion, RisingWave, Databend)
tokenises on whitespace, so the file works as is; DuckDB's runner expects tab
separators — convert with a one-line `sed`. SQLite's original runner lacks
`statement error` regex checks but accepts the records. Add `statement error
<regex>` if your runner supports matching the error text or SQLSTATE.

## 2. Catalogue

| Group | IDs | What it pins down | Typical bug caught |
|---|---|---|---|
| A — 3VL | A1–A20 | Kleene AND/OR/NOT, IS [NOT] DISTINCT FROM, BETWEEN/LIKE with NULL, simple vs searched CASE, `\|\|` with NULL, row-value comparison and `ROW IS NULL`, `''` vs NULL, 1/0 raises, CHECK passes UNKNOWN, IS TRUE/IS UNKNOWN, EXISTS two-valued, `a=1 OR a<>1` not a tautology | NULL-propagating boolean kernels; CHECK reusing WHERE kernel; constant-folding tautologies |
| B — IN/NOT IN/quantifiers | B1–B10 | IN/NOT IN truth table with NULL in list and outer value, empty subquery decides, NOT IN vs NOT EXISTS, ALL/ANY over empty and NULL-containing sets, IN does not multiply rows, outer-scope binding of an unqualified name | anti-join rewrite of NOT IN; IN → inner join without dedup; binder resolving to the wrong scope |
| C — aggregates/grouping | C1–C14 | COUNT(*) vs COUNT(col), scalar vs grouped aggregation over empty input, GROUP BY (), NULLs group together, SUM over NULLs, COUNT DISTINCT, HAVING without GROUP BY, FILTER, scalar subquery 0 rows → NULL and >1 row → error, ROLLUP + GROUPING(), exact DECIMAL sum | hash aggregate emitting no row for scalar agg; SUM returning 0; first-row scalar subqueries |
| D — bags/DISTINCT/set ops | D1–D10 | DISTINCT and set ops treat NULLs as equal, UNION/INTERSECT/EXCEPT [ALL] multiplicities, EXCEPT dedups operands, non-distributivity of bag ∩ over ⊎, self-join multiplicity, INTERSECT precedence, FETCH WITH TIES | INTERSECT via `=` semi-join; EXCEPT ALL as anti-join; set rewrites on bags |
| E — outer joins | E1–E7 | ON vs WHERE placement, left-side ON predicate, COUNT after padding, NULL keys under `=` vs NOT DISTINCT, FULL JOIN padding indistinguishable from data | illegal outer→inner conversion; hash join matching NULL keys; COUNT bug |
| F — ordering | F1–F2 | default NULL placement (PG vs DuckDB), explicit NULLS FIRST | merge joins / indexes disagreeing on null order |
| G — windows | G1–G15 | default RANGE frame includes peers, ROWS vs RANGE vs GROUPS, whole-partition default, LAST_VALUE trap, ranking family incl. PERCENT_RANK/CUME_DIST with ties, EXCLUDE CURRENT ROW/GROUP/TIES, LAG/LEAD defaults, NTILE remainder, windows over grouped rows, illegal in WHERE, empty frames, RANGE with NULL key, negative offset, top-1-per-group | default frame as ROWS; GROUPS treated as RANGE; empty-frame SUM = 0 |
| H — DML/constraints | H1–H14 | SET clauses read old row (swap), end-of-statement UNIQUE (PG per-row deviation and DEFERRABLE fix), statement atomicity, INSERT…SELECT self-snapshot, self-referencing UPDATE/DELETE see pre-state, UNIQUE with NULLs (and NULLS NOT DISTINCT), MATCH SIMPLE/FULL, deferred FK cycle and commit-time failure, sequence gaps, MERGE cardinality violation and clause order, WITH CHECK OPTION, CASCADE vs NO ACTION | Halloween-style re-reads; per-row constraint checks; partial statement effects |
| I — triggers (PG syntax) | I1–I4 | statement trigger fires on 0 rows, row vs statement counts, transition table contents, BEFORE ROW rewriting NEW before CHECK, BEFORE ROW returning NULL skips the row | statement triggers skipped; constraints checked before BEFORE triggers |
| J — strings/Unicode | J1–J5 | CHAR PAD SPACE vs VARCHAR NO PAD, characters vs bytes, canonical-equivalence inequality and NFC normalisation, case-sensitive LIKE, binary collation order | byte-length functions; LIKE prefix rewrites under non-binary collations |
| K — typing/binding/recursion | K1–K6 | integer division (PG) vs true division (DuckDB), overflow and invalid cast raise, functional-dependency GROUP BY, DISTINCT + ORDER BY rule, recursive CTE UNION termination | wraparound arithmetic; silent casts; binder accepting non-grouped columns |

## 3. Deviations observed while verifying

| Behaviour | Standard / PostgreSQL 16 | DuckDB 1.1.3 |
|---|---|---|
| `(1, NULL) = (1, 2)` | UNKNOWN (pairwise 3VL) | FALSE — row literal becomes a STRUCT compared with NULL as a value |
| `1 / 0` | exception 22012 | NULL |
| `7 / 2` (integers) | 3 (exact numeric; scale implementation-defined) | 3.5 (`/` is true division; `//` integer) |
| default NULL order with DESC | PG: NULLs first (NULL is "largest") | NULLs last in both directions |
| `GROUPS` frame unit | supported (SQL:2011) | not implemented |
| negative frame offset | error 22013 | accepted |
| `WITH CHECK OPTION` views | supported | not implemented |
| `UPDATE u SET id = id + 1` on a non-deferrable PK | standard: succeeds (end-of-statement check); **PG fails** (per-row check) | also fails ("duplicate key"; documented over-eager ART index constraint checking) |

Other well-known deviations to encode as `onlyif`/`skipif` if you target them:
Oracle `'' IS NULL` is TRUE; MySQL evaluates `SET x=y, y=x` left to right,
uses case-insensitive default collations (`'ABC' LIKE 'abc'` TRUE), and
forbids a trigger from modifying its own table; SQL Server's UNIQUE admits a
single NULL; SQLite sorts NULLs first and uses dynamic typing (K2/K3 differ).

## 4. What sqllogictest cannot express — use these instead

| Area | Tool / method |
|---|---|
| isolation levels and anomalies (P0–P3, lost update, write skew) | PostgreSQL `isolationtester` spec files (multi-session step permutations); Kleppmann's *Hermitage* test matrix; Jepsen/Elle for distributed engines (see `concurrency-control-theory`) |
| deferred triggers across sessions, NOTIFY after commit | isolationtester-style scripted sessions |
| client API semantics (describe-before-execute, portal suspension, cancel) | driver-level tests in the API's language (JDBC/ODBC conformance suites; protocol fuzzers) |
| optimizer equivalence on random data | SQLancer TLP and NoREC oracles; differential testing vs PostgreSQL/SQLite/DuckDB |
| collation version drift | rebuild-and-compare: build an index, switch collation library, verify with `amcheck`-style ordering checks |

## 5. Extending the catalogue

1. Write the expected output from the **standard's** rule first; then run on a
   reference engine; disagreements are either your misunderstanding or a
   dialect row for §3 — never silently copy an engine's output.
2. Every new rewrite rule gets at least one vector with duplicates **and**
   NULLs on each input it touches.
3. Make window/ordering vectors totally ordered (tie-break on every column)
   unless the vector is *about* peers.
4. Keep vectors tiny (≤ 6 rows) so failures are diagnosable by eye; bulk
   coverage comes from randomized oracles, not from this file.

---

Sources: derived from the semantics in the other reference files (Bag
Semantics p.252, Null Values p.2522, SQL p.3666, SQL Isolation Levels p.3681,
Window Operator in RDBMS p.4693, Database Trigger p.985, Key p.2057, Unicode
p.4335). Expected values verified by execution — > **Beyond EDBS**.
