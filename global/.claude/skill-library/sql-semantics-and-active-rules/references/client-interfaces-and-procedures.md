# Client interfaces (ODBC, JDBC, SQL/CLI, embedded SQL) and stored procedures

Client APIs fix what the engine must expose beyond "run this SQL text":
separate prepare and execute, typed parameters, result metadata before
execution, cursors with defined sensitivity, scrollability and holdability,
incremental fetch, cancellation, and standard error codes. Stored procedures
and functions are the other side of the boundary — code that runs inside the
server and must be compiled, cached, secured and transaction-scoped. This file
lists those obligations.

---

## 1. Ways to couple a host language to SQL

| Approach | How | Plan binding | Notes |
|---|---|---|---|
| Embedded SQL (ESQL/C, COBOL, SQLJ) | SQL statements inside host code, extracted by a **precompiler** | at precompile/bind time (static SQL; DB2 packages) | type checking and authorisation done ahead of time; plans must be rebound when stats or schema change |
| Call-level interface (SQL/CLI, ODBC, JDBC) | host program calls library functions passing SQL strings | at run time (dynamic SQL) | dominant today; the driver hides DBMS specifics |
| Server-side procedural code (SQL/PSM, PL/SQL, T-SQL, PL/pgSQL) | the program itself runs in the server | per embedded statement, cached | removes round trips; vendor-specific dialects |

Three-tier deployments (client ↔ application server ↔ DBMS over ODBC/JDBC)
make the API the only interface the engine sees: connection pools, statement
pools and ORMs sit between it and users. The **impedance mismatch** — different
type systems and set-vs-record processing on each side — is the root of most
API complexity (type mapping, cursors, array binding).

## 2. ODBC and SQL/CLI

ODBC was published by the SQL Access Group in 1992 and is
language-, DBMS- and OS-independent. SQL/CLI (1995; Part 3 of SQL:1999) is the
ISO counterpart. Structure:

```
application ──ODBC API──> driver manager ──> DBMS-specific driver ──wire protocol──> server
                          (loads drivers,     (translates calls and SQL dialect,
                           maps versions)      reports capabilities)
```
Drivers also exist for non-relational sources (spreadsheets, text, XML), so
the API cannot assume a full SQL engine — capability discovery
(`SQLGetInfo`, `SQLGetFunctions`, `SQLGetTypeInfo`) is part of the contract.

Handle hierarchy: environment → connection → statement → descriptors
(application/implementation × parameter/row: APD, IPD, ARD, IRD).
Canonical flow:

```
SQLAllocHandle(ENV) → SQLAllocHandle(DBC) → SQLDriverConnect
SQLAllocHandle(STMT)
SQLPrepare("… WHERE k = ?")          -- parse/bind/plan on the server
SQLNumParams / SQLDescribeParam       -- parameter metadata before execution
SQLNumResultCols / SQLDescribeCol     -- result metadata before execution
SQLBindParameter(…) ; SQLExecute      -- may use parameter arrays (PARAMSET_SIZE)
SQLBindCol(…) ; SQLFetch / SQLFetchScroll  -- block fetch via ROW_ARRAY_SIZE
SQLGetData                            -- piecewise retrieval of long values
SQLMoreResults                        -- next result set (procedures, batches)
SQLEndTran(COMMIT|ROLLBACK) ; SQLCancel ; SQLGetDiagRec (SQLSTATE + native code)
```

Cursor types: forward-only, static (insensitive snapshot), keyset-driven
(membership fixed at open, row values refreshed), dynamic (sees inserts and
deletes), mixed. Escape clauses (`{fn …}`, `{call proc(?)}`, `{d 'yyyy-mm-dd'}`,
`{oj …}`) are rewritten by the driver into native syntax. Catalog functions
(`SQLTables`, `SQLColumns`, `SQLPrimaryKeys`, `SQLForeignKeys`,
`SQLStatistics`, `SQLProcedures`) become catalog queries.

## 3. JDBC

Part of Java SE since JDK 1.1; JDBC 3.0 = JSR 54, RowSets = JSR 114, JDBC 4.0
= JSR 221 (later revisions continued under the JCP). Relational-only, unlike
ODBC. Key objects and their engine-relevant knobs:

| Object | Knobs that reach the server |
|---|---|
| `DriverManager` / `DataSource` | URL, properties, pooling |
| `Connection` | `setAutoCommit` (default **true**), `setTransactionIsolation`, `setReadOnly`, savepoints, `setHoldability`, `prepareStatement(sql, RETURN_GENERATED_KEYS)` |
| `Statement` / `PreparedStatement` / `CallableStatement` | `setFetchSize`, `setMaxRows`, `setQueryTimeout`, `cancel`, `addBatch/executeBatch`, `getMoreResults`, `getGeneratedKeys`, `getParameterMetaData`, OUT parameters |
| `ResultSet` | type `FORWARD_ONLY` / `SCROLL_INSENSITIVE` / `SCROLL_SENSITIVE`; concurrency `READ_ONLY` / `UPDATABLE`; holdability `HOLD_CURSORS_OVER_COMMIT` / `CLOSE_CURSORS_AT_COMMIT` |
| `DatabaseMetaData` | ~150 capability and catalog methods |

Driver types: 1 (JDBC–ODBC bridge, removed in Java 8), 2 (native client
library), 3 (middleware), 4 (pure-Java wire protocol — the norm).

## 4. What these APIs require from the engine

### 4.1 Prepare / describe / execute
1. **Parse+bind+plan without executing**, returning a statement handle.
2. **Parameter typing**: placeholders arrive untyped; infer from context
   (`k = ?` takes k's type; `? + ?` is ambiguous → error or a documented
   default). Expose the inferred types (`SQLDescribeParam`,
   `ParameterMetaData`). Unknown-typed literals that later conflict must fail at
   prepare, not at execute.
3. **Result description before execution** (`SQLDescribeCol` after
   `SQLPrepare`; JDBC `PreparedStatement.getMetaData`): names, types,
   precision/scale, nullability. The binder must produce it without running the
   query.
4. **Stability**: if DDL changes the result shape of a prepared statement,
   either re-plan transparently when the shape is unchanged or fail with a clear
   "cached plan must not change result type" error. Never return rows of a new
   shape under an old description.
5. Lifecycle: named and unnamed server statements, explicit close/deallocate,
   per-session limits, and survival rules across transaction end. Connection
   poolers multiplexing sessions in transaction mode must either track prepared
   statements (PgBouncer ≥ 1.21 does) or clients must disable server-side
   prepares — design the protocol so statement identity is not tied to a
   physical connection if you expect poolers.

### 4.2 Cursors (standard model)

```
DECLARE c [SENSITIVE | INSENSITIVE | ASENSITIVE] [SCROLL | NO SCROLL] CURSOR
          [WITH HOLD | WITHOUT HOLD] [WITH RETURN | WITHOUT RETURN]
  FOR <query> [FOR READ ONLY | FOR UPDATE [OF cols]]
FETCH {NEXT | PRIOR | FIRST | LAST | ABSOLUTE n | RELATIVE n} FROM c
UPDATE … WHERE CURRENT OF c ;  DELETE … WHERE CURRENT OF c
```

| Property | Semantics | Engine cost |
|---|---|---|
| INSENSITIVE | result fixed at OPEN; later changes (including the session's own) invisible | MVCC snapshot held for the cursor's life, or materialise |
| SENSITIVE | changes made after OPEN become visible (at least the session's own) | re-fetch by row id per FETCH, or cursor over base table access paths; cannot materialise |
| ASENSITIVE | implementation-defined | whatever is cheapest — document it |
| SCROLL | backward and absolute positioning | operators must support backward scan, or materialise into a spillable tuple store |
| WITH HOLD | survives COMMIT (closed on ROLLBACK) | materialise at commit (PostgreSQL) or keep snapshot/locks past commit; release row locks either way |
| FOR UPDATE / WHERE CURRENT OF | positioned DML on the row under the cursor | cursor must expose a stable row identity; plan must be updatable (no aggregation/DISTINCT/joins that lose identity) |

Optimizer interaction: a cursor signals that early rows matter — plan for
fast-first-rows (PostgreSQL `cursor_tuple_fraction`, default 0.1; `FAST n`
hints elsewhere). Holdable or scrollable cursors over huge results need a
spill-to-disk tuple store with backward reads.

### 4.3 Fetch protocol and streaming
- **Block fetch**: the client asks for n rows (`ROW_ARRAY_SIZE`,
  `setFetchSize`); the server runs the plan until n rows are produced, then
  **suspends the portal** (PostgreSQL `Execute` with a row limit returns
  `PortalSuspended`). The executor must be able to pause and resume a plan
  with all operator state intact — the iterator model gives this for free; a
  push-based pipeline needs explicit suspension points.
- Without a cursor or row limit the server streams everything and back-pressure
  is the socket; drivers often buffer the whole result (PgJDBC uses
  cursor-based fetching only when autocommit is off and a fetch size is set).
- `setMaxRows`/`FETCH FIRST` should reach the planner as a LIMIT, not be applied
  by discarding rows client-side.

### 4.4 Transactions through the API
- Both ODBC and JDBC default to **autocommit**: each statement is its own
  transaction. The server must cheaply start/commit implicit transactions,
  and a result set being fetched in autocommit must stay valid until closed
  (or the API must close it at commit — define which).
- `setTransactionIsolation` / `SQL_ATTR_TXN_ISOLATION` map to `SET
  TRANSACTION ISOLATION LEVEL`; report the level actually provided
  (an engine may upgrade, never downgrade). Changing isolation mid-transaction
  is an error.
- Savepoints map to `SAVEPOINT` / `ROLLBACK TO` / `RELEASE`.
- Retryable failures must carry SQLSTATE 40001 (serialization) or the deadlock
  code so frameworks can retry automatically.

### 4.5 Batches, generated keys, multiple results
- **Parameter arrays / `executeBatch`**: one prepared statement, many parameter
  sets. Support it natively (pipelined Bind/Execute without per-row round trips,
  or array binding in the protocol) and return per-element update counts and
  per-element errors; define whether a failure stops the batch.
- **Generated keys**: `INSERT … RETURNING` (PostgreSQL, Oracle `RETURNING
  INTO`, SQL Server `OUTPUT`) lets drivers implement `getGeneratedKeys` without
  a second query.
- **Multiple results**: a procedure call or multi-statement batch may return
  several result sets and update counts interleaved; the protocol must frame
  each with its own description, and OUT/INOUT parameters come back after them.

### 4.6 Cancellation, timeouts, errors, metadata
- **Out-of-band cancel** (`SQLCancel`, `Statement.cancel`): PostgreSQL sends a
  cancel request over a separate connection with a secret key; TDS sends an
  attention packet. Long-running operator loops, sorts, hash builds and
  procedural loops must poll an interrupt flag frequently.
- **Statement timeouts** server-side, not only client-side.
- **Diagnostics**: SQLSTATE + native code + message (+ position, constraint
  and object names where available); warnings use class 01 (e.g. 01004 string
  data right truncation) and surface as `SQL_SUCCESS_WITH_INFO` /
  `SQLWarning`.
- **Metadata calls** run constantly (ORMs and BI tools call them per
  connection): make catalog queries fast, consistent with the session's
  snapshot, and correct about search patterns (`%`, `_`, escape character).
- **Type mapping**: DECIMAL precision/scale, TIMESTAMP with/without time zone,
  INTERVAL, BOOLEAN, LOBs (streamed or via locators), and character-set
  negotiation (client encoding vs server encoding with conversion on the wire).

> **Beyond EDBS:** a reference wire protocol to study is PostgreSQL's extended
> query protocol — `Parse` (named/unnamed statement), `Bind` (parameters,
> per-column text/binary formats → portal), `Describe`, `Execute` (row limit),
> `Sync` (transaction/error boundary), `Close`; it supports pipelining many
> Bind/Execute pairs before one Sync. Others: TDS (SQL Server), DRDA (DB2),
> Arrow Flight SQL (columnar result transfer), and Teradata's CLIv2 parcels.

## 5. Stored procedures and user-defined routines

### 5.1 Definitions
A stored procedure is a program written in the query language (or a host
language) that is created by DDL (`CREATE PROCEDURE`), compiled and stored in
the server, executed there, and typically has side effects on the database.
Procedures are invoked by `CALL` (or vendor `EXEC`) from applications or
interactive SQL — not from inside queries; side-effect-free **user-defined
functions** are the routines allowed in expressions. SQL/PSM (1996; Part 4
since SQL:1999) standardised the procedural language — assignment, control
flow, cursors, condition handlers — after PL/SQL and Transact-SQL had set
de facto practice; external routines in C or Java (Part 13) are the other
option. Benefits: fewer round trips over slow or unreliable links, logic kept
with the data. Cost: every vendor's language differs, so procedures are the
least portable part of an application.

### 5.2 Routine characteristics the optimizer and executor rely on

| Characteristic (standard) | PostgreSQL analogue | Used for |
|---|---|---|
| `DETERMINISTIC` / `NOT DETERMINISTIC` | `IMMUTABLE` / `STABLE` / `VOLATILE` | constant folding, index/expression keys, caching results, moving calls across operators |
| `NO SQL` / `CONTAINS SQL` / `READS SQL DATA` / `MODIFIES SQL DATA` | volatility + `PARALLEL SAFE/RESTRICTED/UNSAFE` | whether calls can run in parallel workers, in read-only transactions, inside constraints |
| `RETURNS NULL ON NULL INPUT` / `CALLED ON NULL INPUT` | `STRICT` | skipping calls, and proving null-rejection for outer-join simplification |
| `SQL SECURITY DEFINER` / `INVOKER` | `SECURITY DEFINER` / `INVOKER` | privilege checks inside the body |

A mislabelled routine is a wrong-results bug: a function declared
deterministic that reads a table will be constant-folded into stale plans or
index expressions. Engines cannot verify the label in general; at minimum
reject `MODIFIES SQL DATA` routines in CHECK constraints, index expressions and
generated columns.

### 5.3 Execution models

| Model | Example | Characteristics |
|---|---|---|
| interpreted with lazily planned embedded SQL | PL/pgSQL, PL/SQL, T-SQL | each embedded statement is parsed once, planned on first execution, cached; procedural ↔ SQL engine context switch per statement (Oracle's `BULK COLLECT`/`FORALL` exist to batch it) |
| compiled to native code | SQL Server Hekaton natively compiled procedures (Freedman et al., 2014); HyPer-style compiled queries | fastest; restricted feature set; recompilation on schema change |
| external language runtime | Java/C/Python UDFs, out-of-process sandboxes | isolation and safety via process boundary; serialisation cost per call; batch (vectorised) UDF interfaces amortise it |

Design rules: compile once per (routine version, relevant session settings);
make SQL inside routines participate in the same plan cache and invalidation
as top-level statements; give routines a set-oriented calling convention
(table-valued parameters, vectorised UDFs) so they do not force row-at-a-time
execution.

### 5.4 Plan caching and parameter sensitivity
Embedded statements are parameterised by routine variables, so the generic vs
specific plan dilemma is central:
- **SQL Server** compiles using the first call's parameter values ("parameter
  sniffing"); mitigations `OPTION (RECOMPILE)`, `OPTIMIZE FOR`, and
  parameter-sensitive plan optimisation in recent versions.
- **PostgreSQL** (`plan_cache_mode = auto`) plans the first five executions
  with the actual values, then switches to a generic plan if its estimated
  cost is not markedly worse than the average custom plan.
- **Oracle** peeks bind values at hard parse and uses adaptive cursor sharing to
  spawn child cursors for different selectivity ranges.
Invalidation triggers: DDL on any dependency, statistics refresh, changes to
name-resolution settings (schema search path), privileges. Keep a dependency
list per cached plan.

### 5.5 Security
Definer-rights routines are privilege amplification (setuid): the body runs
with the owner's privileges. Hazards an engine must help prevent: name
resolution through the caller's search path (pin it per routine — PostgreSQL
`SET search_path` on the function), dynamic SQL built from arguments
(injection with the owner's rights), and leaking errors that reveal protected
data. Invoker-rights routines need privilege checks at each embedded statement
for the *current* user — so cached plans must not bake in authorisation
decisions. Broader authorisation design: `database-security-internals`.

### 5.6 Transactions and exceptions inside routines
- Standard: a routine runs inside the caller's transaction and cannot commit it.
  PostgreSQL 11+ allows `COMMIT`/`ROLLBACK` inside a **procedure** invoked by a
  top-level `CALL` outside an explicit transaction block, never inside a
  function. SQL Server nests `BEGIN TRAN` as a counter (`@@TRANCOUNT`) — inner
  commits do not commit. Oracle autonomous transactions run an independent
  transaction from inside a routine.
- SQL/PSM condition handling: `DECLARE {CONTINUE | EXIT | UNDO} HANDLER FOR
  SQLSTATE '…' | SQLEXCEPTION | SQLWARNING | NOT FOUND`, `SIGNAL`, `RESIGNAL`,
  `GET DIAGNOSTICS`. An UNDO handler (and PL/pgSQL's `EXCEPTION` block) needs a
  savepoint at block entry — a subtransaction per loop iteration is a common
  performance trap (it costs a savepoint, may consume a transaction id, and
  defeats bulk paths).
- Cursors declared `WITH RETURN` hand result sets back to the caller — the
  multiple-results machinery of §4.5.

### 5.7 Tests
- Prepare/describe parity: for every statement in the conformance corpus,
  the described result types must equal the types of the rows actually
  returned.
- DDL-under-prepared-statement: alter/drop a referenced table or column between
  executions; expect re-plan or a clean error, never wrong-shaped rows.
- Portal suspension: fetch in blocks of 1, 7 and 1000 from the same query and
  compare with a single fetch, including through sorts, hash joins and window
  operators.
- Holdable/scrollable cursors: commit in the middle; scroll backward across
  spill boundaries; positioned UPDATE then FETCH PRIOR.
- Cancel storm: cancel random statements at random times; the session must stay
  usable and no locks/temp files leak.
- Routine labels: property test that functions declared deterministic return
  identical results under repeated and reordered invocation.
- Parameter sensitivity: skewed column; the same prepared statement executed
  with a frequent and a rare value must not regress catastrophically after the
  plan goes generic.

---

Sources: Open Database Connectivity (p.2596); Java Database Connectivity
(p.2045); SQL (p.3666) — CLI, PSM, embedded SQL vs call interfaces, three-tier
architecture; Stored Procedure (p.3764); Query Language (p.2994). Protocol,
cursor-implementation and plan-cache details are > **Beyond EDBS**.
