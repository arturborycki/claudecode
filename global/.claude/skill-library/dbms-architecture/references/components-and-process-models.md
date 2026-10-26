# Components, interfaces and process models

How a relational engine is cut into components, which state each one owns,
how requests flow through them, and how the whole thing is mapped onto OS
processes and threads. Read this before adding a module, moving
responsibility between layers, or changing the execution/threading model.

## 1. Reference decomposition

The decomposition most engines approximate (Hellerstein, Stonebraker &
Hamilton 2007, adopted by the EDBS *DBMS Component* entry):

| Component | Sub-components | Owns (state) | Talks to |
|---|---|---|---|
| Client communications manager | local protocols (shared memory, pipes), remote protocols (TCP/TLS wire protocol) | sockets, protocol state, result buffering | process manager |
| Process manager | admission control, dispatch & scheduling | worker pool, run queues, session→worker binding | everything (it runs it) |
| Relational query processor | parse + authorize, rewrite, optimize, plan execution, DDL/utility processing | parse trees, plans, plan cache, executor state | catalog, storage manager |
| Transactional storage manager | access methods, buffer manager, lock manager, log manager (+ transaction manager) | pages, frames, lock table, log buffer, transaction table | OS I/O + sync primitives |
| Shared utilities | catalog manager, memory manager, replication, bulk load, backup | metadata, memory contexts/arenas | all |

Variations are legitimate: a decision-support engine may have no lock
manager worth the name; a main-memory engine may have no buffer manager; a
key-value engine may have no optimizer. What must not vary is that **each
piece of shared state has exactly one owning component**, and others reach it
through that component's interface.

Two kinds of interface (EDBS *DBMS Interface*):

- **External** — SQL (and XQuery etc.), call-level APIs (ODBC/JDBC/ADO.NET),
  embedded SQL, graphical schema tools. Standardized; stability is a business
  requirement because applications are the large investment.
- **Internal** — query processor ↔ storage manager (records, keys, RIDs,
  scans), storage manager ↔ OS (blocks, async I/O, latches). Not
  standardized but just as consequential: a *queue* interface between
  components is what makes staged execution (section 7) possible; a
  record-at-a-time interface is what makes vectorized execution hard.

### Layer formats (Helland's view, EDBS *Process Structure of a DBMS*)

```
 application ──SQL / result sets──▶ query+DML front-end   (statements, row sets)
                                     query+DML back-end    (keys, records)
                                     access methods        (records ↔ blocks)
                                     block & page manager  (pages ↔ physical I/O)
                                     disks
```
The shared-x architectures are exactly the choice of *which arrow becomes a
network*: shared-disk cuts below the page manager; shared-nothing cuts
between query front-end and back-end (see
`architectures-shared-x-and-column-stores.md`).

## 2. Query processor: the statement lifecycle

1. **Parse.** Lexing/parsing into an AST; qualify names to `schema.object`.
2. **Bind + authorize.** Resolve every name against the catalog, type-check,
   and check privileges for the requested operation on each object. Output:
   an internal representation shared by rewriter and optimizer.
3. **Rewrite.** Semantics-preserving, catalog-driven: view expansion,
   constant folding/arithmetic simplification, predicate normalization,
   subquery flattening (see `query-optimizer`).
4. **Plan cache probe.** Before the expensive optimization step, look up a
   cached plan keyed by normalized statement text (+ parameter types, +
   relevant session settings). The plan records the catalog/statistics
   versions it depends on.
5. **Optimize.** Choose access paths, join order/algorithms, parallelism,
   memory grants using statistics and the cost model. Output is usually an
   interpretable operator DAG; some systems emit machine code directly
   (Daytona/Cymbal is the EDBS example).
6. **Execute.** The executor implements the algorithms the optimizer may
   choose — the two are coupled: the optimizer can only pick joins the
   executor implements. Classic interface: iterator `open/next/close`
   (Volcano, Graefe). EDBS notes the tuple-at-a-time iterator's per-tuple
   overhead on modern CPUs (MonetDB/X100 critique).

> **Beyond EDBS:** the two production answers to iterator overhead are
> vectorized pull (MonetDB/X100, Vectorwise, DuckDB: `next()` returns ~1K-value
> vectors) and data-centric compilation (HyPer, Neumann VLDB 2011: fuse
> pipelines into tight loops via LLVM; adaptive execution starts interpreted
> and compiles hot pipelines, Kohn, Leis & Neumann ICDE 2018). See
> `query-execution-advanced`.

Misconception to avoid: "query processor" ≠ "query executor"; the executor
is one of four sub-components.

## 3. Storage manager (transactional storage layer)

Its ancestry is System R's RSS. Graefe's description (EDBS *Storage
Manager*) gives a crisp contract:

**Concepts.** The storage layer speaks *physical* concepts — index,
partition, record, field — not *logical* ones — table, view, row, column,
domain. One row may be many records (a heap/clustered record plus one entry
per secondary index, possibly per vertical partition); one record may cover
many rows (a non-unique secondary index entry with a RID list); one index may
interleave several tables (master-detail clustering of orders and line
items). Use qualified terms: *primary key*, *foreign key*, *index key*,
*search key*.

**Services.** Create/drop index; insert, delete, update, scan, search records.
A heap is an index from RID to record whose RIDs cannot be chosen. All
operations are inside transactions; the layer supports **pre-commit
(prepare)** for 2PC as well as immediate commit.

**What it needs from the OS.** Only two things: I/O (preferably asynchronous —
otherwise simulated with extra threads) and synchronization primitives with
shared and exclusive modes.

**Components.** Access methods, buffer pool, concurrency control (locks and
latches), logging/recovery; less visible: memory management, disk space
allocation, catalogs, async I/O, temporary structures for sort/hash, page
structures for variable-length records, utilities, and "initial access" logic
(opening a database after a crash or from an untrusted source).

**Latch discipline.** Latches protect in-memory structures among threads;
modes shared/exclusive; they do not participate in deadlock detection, so
deadlock must be *avoided* — order latches by level (e.g. B-tree parent
before child, page-table bucket before frame); never hold a latch while
waiting for I/O or for a database lock.

**On disk.** User indexes (clustered and secondary, on tables and
materialized views), catalogs (usually in the same format as user data),
free-space maps (bitmaps; must be readable during boot and recovery), and the
log (often mirrored). Each page: header (with **format version** — lets the
on-disk format evolve without unload/reload — and **pageLSN** for
exactly-once redo), variable-length record area, slot/indirection vector.

**Map everything to B-trees.** Hash indexes, heaps, multi-dimensional indexes
(via linearization), column storage, bitmaps (as compressed RID lists),
master-detail clustering and BLOBs can all be realized on B-trees with
modest overhead — and the expensive part, fine-grained locking + recovery +
testing, is then built once.

**In memory.** Lock-manager hash table, buffer pool, log buffers, transaction
table, checkpoint state, device/I/O state. Caches tuned for in-memory access
(catalog, free-space bitmaps); interior B-tree nodes may hold swizzled
in-memory child pointers — updates must propagate between the cache structure
and the page image.

**Serving queries (not driving them).** Prefetch, read-ahead, shared scans,
write-behind. Optional automatic maintenance of all secondary indexes on row
update — fine for centralized systems or partition-aligned local indexes, but
it forces row-by-row maintenance; index-by-index maintenance (sort the delta
per index) is needed for some unique-index updates and for large batches.
Do **not** bury secondary→primary navigation inside the storage layer: keeping
it in the executor enables covering indexes, RID sorting before fetch, index
intersection (AND) and union (OR), joining two indexes of one table to cover a
query, and index-only semijoin reduction.

**Recovery granularity.** Units of recovery cannot be larger than units of
concurrency control: with key-value or row locking you cannot use page-level
recovery from a file system or SAN. Log shipping to a hot standby that is
perpetually in recovery is a natural storage-layer service.

**Utilities.** Index create/drop, reorganization/defragmentation, partition
moves, backup/restore, statistics, consistency check and repair, catching up
deferred maintenance (MVs, indexes, statistics, replicas). Modes: offline,
online (concurrent readers/writers), incremental (results usable in steps).
Because utilities move data like queries, implement them **on the query
executor** (memory grants, partitioning, pipelining, parallelism): build a new
index from an existing smaller secondary index; run consistency checks as an
aggregation over a disk-order scan rather than per-index random navigation.

**Metadata locks.** If catalogs live above the storage layer, the storage layer
still supplies their indexes and special lock scopes/modes: one lock can cover
a table's metadata *and* data; the weakest mode read-protects metadata only,
the strongest permits arbitrary change to both; ordinary S/X data locks imply
metadata read protection.

## 4. Transaction, concurrency-control and logging/recovery managers

The resource-manager architecture (Gray & Reuter; EDBS entries by Reuter):

- **Transaction manager (TxM)** — itself a resource manager implementing the
  resource type "transaction". Assigns globally unique, never-reused
  transaction ids; drives state transitions (begin, savepoint, rollback,
  abort, prepare, commit); records which resource managers (RMs) and which
  communication sessions (with direction: incoming/outgoing) each transaction
  touched; acts as 2PC coordinator, participant, or both; calls RMs back at
  their registered entry points. Often built as an interpreter of a
  state-machine description so commit-protocol variants can be swapped.
- **Concurrency control manager (CCM, "lock manager")** — sees every access
  request (to tuples, access paths, directory data) as *(txn, object, action,
  time)*. Locking: grant or enqueue, maintain the waits-for relation, detect
  deadlocks. Optimistic: grant immediately, validate at commit against
  concurrent and recently committed transactions. On deadlock/conflict it
  picks the victim and tells the TxM; the actual rollback is done by the
  recovery manager. Multi-version CCMs keep previous versions to increase
  concurrency.
- **Logging/recovery subsystem (LRS)** — log manager appends records; it does
  **not interpret** them. RMs (heap, B-tree, queue …) produce records and
  consume them during undo/redo; the recovery manager just feeds them back.
  Online log (enough for crash recovery) vs archive log (media recovery),
  with background migration. The log also records transaction state
  transitions (begin, prepare, commit, abort, checkpoint) and is the first
  thing opened at restart.

Restart order: recovery manager scans the log → transaction table (the TxM's
state) is rebuilt first → in-doubt (prepared) transactions are handed to the
TxM to finish 2PC → RMs perform redo/undo. (EDBS describes a backward-then-
forward scheme; modern ARIES-style systems do analysis → redo → undo, see
`recovery-and-durability`.)

Abort path, component by component:

```
CCM detects cycle ──victim──▶ TxM.abort(T) ──▶ LRS: read T's log chain backwards
                                    │              └─▶ owning RM.undo(record) (CLRs)
                                    └──▶ CCM.release_all(T) after undo completes
```

## 5. Catalog / data dictionary

Two meanings (EDBS *Data Dictionary*): human documentation of the schema, and
the **system catalog** — a mini-database tightly coupled to the engine that
the binder, optimizer, executor and transaction machinery consult constantly.
Typical contents: tables/columns/types; users, roles, privileges; index
definitions; constraints (keys, referential integrity); schema definitions;
storage allocation parameters; usage statistics; stored procedures and
triggers. The SQL-standard external face is `INFORMATION_SCHEMA` (MySQL's is
virtual).

Engineering rules:
- Store the catalog in ordinary tables of the engine (bootstrapping needs a
  few hard-coded descriptors), so it gets locking, logging and recovery for
  free.
- Cache it in memory; read paths must not take heavy locks. Version every
  object; plans and cached descriptors record versions; DDL bumps versions and
  broadcasts invalidations (across processes or nodes).
- Distributed engines: catalog is read-mostly and hot → replicate it to
  coordinators; in autonomous/federated settings it can only be cached, and
  stale cached metadata can make queries fail *or return wrong data*
  (EDBS *Distributed Architecture*).

## 6. Data independence as the architectural contract

Three-schema architecture: external schemas (views per user class) →
conceptual schema (whole database in the data model) → internal schema
(files, storage structures, indexes). **Physical data independence**: change
the internal schema without changing the conceptual one. **Logical data
independence**: change the conceptual schema without changing external ones.
Implemented by *mappings* between levels owned by the DBMS; changing a lower
level only changes the mapping to the level above.

Helland (EDBS *Database Management System*) puts it more strongly: the DDL
abstraction *is* the essence of a DBMS — above it applications evolve and new
applications share the same data, below it storage evolves with technology.
Corollary: **performance independence** — the optimizer, not the program,
picks the strategy, so programs survive changes in hardware and data size
(the ideal is approximate for complex queries).

What this demands of the engine:

| Change | What must stay invariant | Mechanism |
|---|---|---|
| Add/drop index, change layout, compress, repartition | query results | plans re-derived; plans versioned |
| Add column, add table, add constraint | existing queries/views | binder tolerates extension; `SELECT *` expansion at view-definition time |
| Move storage medium / tiering | results, semantics | buffer/storage manager only |

Leaks to watch for: exposing physical RIDs/ctids to applications; results
whose order silently depends on clustering (no `ORDER BY`); index hints
baked into application SQL; storage-specific error codes surfacing in the
SQL layer. Test with differential runs across physical designs.

## 7. Process models

### History (EDBS *Process Structure of a DBMS*)
1. DBMS as a **library inside the application process** — cheap calls, no
   protection of data from application bugs.
2. DBMS in a **protected ring / shared protected memory**, entered via
   hardware-protected transitions — still in-process, shared across
   applications.
3. Portability across OSes and distribution pushed the DBMS out into its own
   processes: INGRES split itself into **four processes** (originally for
   memory limits) — an early staged design; Tandem NonStop SQL kept an
   in-memory call API but fanned out cross-process/cross-processor.
4. **Two-tier client-server** (ODBC connection carries statements and result
   sets across the process boundary), then **three/N-tier**, then SOA (no
   shared DBMS or transactions across service boundaries — invisible to the
   DBMS).

> **Beyond EDBS (Hellerstein et al. 2007, production systems):**
>
> | Model | Examples | Notes |
> |---|---|---|
> | Process per DBMS worker | PostgreSQL (postmaster forks one backend per connection), Oracle dedicated server | shared state in an explicitly mapped shared-memory segment; strong fault isolation; per-backend memory (catalog caches, work_mem) multiplies with connections |
> | Thread per DBMS worker | classic MySQL, many embedded engines | cheap, but thousands of threads → scheduler and latch thrash |
> | Pool of processes/threads with dispatcher | Oracle shared server (dispatchers + shared servers), SQL Server (SQLOS: user-mode, cooperative scheduler, worker pool per scheduler/core), MySQL/Percona thread pool | sessions ≫ workers; a worker must yield at I/O and lock waits or the pool starves |
> | Embedded/in-process | SQLite, DuckDB | the 1960s library model again, now by choice |
>
> OS threads vs DBMS-level ("user-mode") threads: the latter give the engine
> control over scheduling and avoid kernel context switches but require
> non-blocking I/O everywhere. External poolers (PgBouncer) exist because
> process-per-connection engines cannot hold tens of thousands of sessions;
> transaction-mode pooling breaks session-scoped state (temp tables, `SET`,
> session advisory locks, and — in older versions — named prepared
> statements).

### Admission control
Two layers (Hellerstein et al.): (a) at the dispatcher — cap concurrent
requests/sessions so the system never exceeds what memory and CPU can hold;
(b) at execution — after optimization, admit a query only when its memory
grant (sort/hash work areas) and other resources are available; queue
otherwise. Without (b), many concurrent hash joins each spill or, worse,
oversubscribe memory and thrash — the same collapse the hot-set scheduler
avoids for buffer frames (see `buffer-management.md`). Differentiated service
(administrator connections that are always admitted) is a requirement, not a
nicety (EDBS *Connection*).

### Design rules for a worker model
- Size the active worker pool to cores (per NUMA node); sessions are
  separate objects that bind to a worker only while running a request.
- Every potentially long wait (I/O, lock, network, latch with spin limit)
  must be a yield point; otherwise convert the waiting worker into a
  stalled core.
- Keep per-session memory small and bounded; put caches (catalog, plans) in
  shared memory with versioned invalidation rather than per-backend copies.
- Fault isolation: in a threaded server, contain errors with
  per-statement memory contexts and exception boundaries; a crash still kills
  every session, so durability cannot depend on graceful shutdown.

## 8. Staged DBMS and work sharing

**Problem:** the thread-per-query model lets the OS scheduler interleave
unrelated queries at arbitrary points (I/O, lock wait, quantum expiry), so
each context switch evicts the instructions and data the previous thread was
using, and the developer can optimize single queries but never the
*interleaving* of many.

**Staged design** (Harizopoulos & Ailamaki, CIDR 2003; roots in Larus &
Parkes cohort scheduling and Welsh et al. SEDA): the engine is a set of
self-contained **stages** (e.g. connect, parse, optimize, scan, join, sort,
aggregate, send). A stage = queue + worker-thread pool + own resource
management + mostly private code and data. Requests travel as **packets**
holding the query's state (pointers only, in shared memory).

```
dequeue(packet) → restore query state → run stage code → one of:
   (i)  destroy packet (query done with this stage)
   (ii) forward to next stage (parse → optimize)
   (iii) re-enqueue to own queue (waiting on a condition)
   (+ may create new packets for other stages)
```
Two-level scheduling: local (which packet in a stage's queue) and global
(which stage gets CPU). Batching packets per stage keeps that stage's
instructions and data cache-resident — the same principle as buffering
operator calls for the instruction cache (see
`cache-conscious-and-main-memory.md`).

**Work sharing** is the killer application: detect redundant computation or
data access across concurrent queries.

| Technique | When sharing is detected | Limitation |
|---|---|---|
| Materialized views | design time | workload must be known; maintenance cost |
| Multi-query optimization (Sellis 1988; Roy et al. 2000) | optimization of a batch | batch required; often materializes shared results |
| Shared/cooperative scans (Teradata, SQL Server, DB2; Zukowski et al. VLDB 2007) | run time, scan level | only for order-insensitive scans; buffer-manager policy work |
| QPipe "one operator, many queries" micro-engines | run time, every operator | dispatcher + per-operator overlap rules |

QPipe turns each relational operator into a micro-engine with its own queue
and threads; a packet dispatcher converts plans to packets; every new packet
is checked against in-flight ones for overlap (e.g. another query already
sorting the same input) and the result is pipelined to all consumers, avoiding
materialization.

**Caveat (Johnson et al., VLDB 2007):** on chip multiprocessors, sharing can
*reduce* throughput for in-memory workloads because the shared operator
becomes a serialization point limiting parallelism. Share when the system is
I/O- or bandwidth-bound or under-utilized; stop sharing when cores are idle
waiting on the shared producer.

> **Beyond EDBS:** morsel-driven parallelism (Leis et al. SIGMOD 2014) is the
> dominant modern alternative: a fixed pool of NUMA-pinned workers pulls
> small input fragments (morsels) of pipeline jobs from a dispatcher, giving
> elastic intra-query parallelism and locality without per-operator stages.

## 9. Connections and sessions

- **Connection** (EDBS *Connection*): the channel through which a client
  issues SQL. Opening it names server, database and credentials; the
  handshake authenticates and authorizes, and negotiates protocol version and
  data encoding. Transport: IPC (pipes, shared memory) locally, TCP remotely.
  APIs: ODBC (derived from the SQL CLI standard), JDBC, ADO.NET.
- Connections are **the main source of concurrency** in a server, so servers
  cap them and prioritize some (DBA). Clients keep **connection pools** to
  avoid connect/teardown cost and to avoid tying up resources with too many
  open connections.
- **Session** (EDBS *Session*): the sequence of interactions on behalf of a
  client; holds in-flight command state, cursors, session-private temporary
  tables, settings, prepared statements. Session-level consistency
  (read-your-writes) is trivial centrally, hard with replicas.

Identity rules once tiers multiply (Helland): in two-tier, a transaction is a
time interval on one connection; in three-tier, the transaction id travels
with the RPC from presentation to logic tier and **the same transaction may
arrive on several database connections**, so the engine must key
transactional state by transaction id, not by connection. Distributed
transactions across databases add 2PC between servers and client-side
transaction objects independent of any connection.

## 10. Client-server and multitier deployment

Client-server DBMS (EDBS *Client-Server Architecture*, Özsu): the server
does storage, optimization and transactions (locking, recovery); the client
holds the application, UI and a DBMS client module that may **cache data and
even cached locks**. Communication is at the SQL level — the client ships
statements unoptimized, the server returns result relations. (Client-side
query validation is possible but needs a replicated catalog, so it is rare.)

| Variant | Property |
|---|---|
| Multiple clients, single server | simple, predictable (server only does data management), but the server is the scaling bottleneck |
| Multiple clients, multiple servers, **heavy client** | each client manages its own server connections; simpler servers |
| Multiple clients, multiple servers, **light client** | client talks to a home server that coordinates others; transparency at the server |
| Three-tier / application server | presentation / business logic / data management on separate tiers; app servers cluster horizontally behind a dispatcher (TP monitor style) |

Where business logic lives (EDBS *Multitier Architecture*):
- **Fat client / thin server** — embedded SQL or CLI calls from the client;
  heavy network traffic, painful client rollout.
- **Thin client / fat server** — stored procedures/persistent stored modules;
  server becomes bottleneck and single point of failure.
- **Three-tier** — app server holds logic; needs distributed transactions
  (2PC via OTS/JTA-style services), ideally multi-level transactions that
  respect the layering (SAP R/3 is the cited example), queued transactions
  over persistent message queues for asynchronous steps, and caching
  (replicas, materialized views) at the middle tier.

> **Beyond EDBS:** data shipping vs query shipping is the core client-server
> query-processing trade-off (Franklin, Jónsson & Kossmann, SIGMOD 1996):
> shipping pages/objects to clients exploits client CPU and cache, shipping
> queries to the server exploits server-side indexes and reduces traffic;
> hybrids decide per operator. For object stores, DeWitt et al. (VLDB 1990)
> compared page-server, object-server and file-server designs; page servers
> won under good clustering.

## 11. Review checklist for a component change

- Which component owns the new state? Is there exactly one writer path?
- Does the change cross a layer in the wrong direction (storage layer calling
  the optimizer, executor touching frames without pinning)?
- Is the interface batch- or record-at-a-time, and does that block
  vectorization or staging later?
- Does it add a wait that is not a scheduler yield point?
- Does it add per-session memory that scales with connections?
- Does DDL invalidate whatever new cache it adds?
- Does it preserve physical/logical data independence (no physical detail
  observable through SQL)?
- Can utilities that touch this structure run online and on the executor?

Sources: EDBS *DBMS Component* (p.1005), *DBMS Interface* (p.1005), *Query
Processor* (p.3058), *Storage Manager* (p.3736), *Transaction Manager*
(p.4194), *Concurrency Control Manager* (p.574), *Logging/Recovery Subsystem*
(p.2135), *Data Dictionary* (p.749), *Logical and Physical Data Independence*
(p.2136), *Database Management System* (p.957), *Data Management
Fundamentals: Database Management System* (p.784), *Process Structure of a
DBMS* (p.2867), *Staged DBMS* (p.3696), *Connection* (p.581), *Session*
(p.3484), *Client-Server Architecture* (p.439), *Multitier Architecture*
(p.2443), *Application Server* (p.128), *Distributed Architecture* (p.1152).
