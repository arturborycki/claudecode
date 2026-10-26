# Application, schema, concurrency and physical-layer tuning

The Shasha–Bonnet school of tuning (Database Tuning, Morgan Kaufmann 2002;
the EDBS tuning entries are by the same authors) rests on a few principles:
think globally, fix locally; partitioning breaks bottlenecks; **start-up
costs are high, running costs are low**; render on the server what is due on
the server; be prepared for trade-offs. This file applies them layer by
layer, from the application interface down to disks, and says what an engine
builder can do to make the right behaviour the default.

## 1. Application-level tuning

Application-level changes are often a pure win: unlike adding an index
(faster reads, slower writes) a better query formulation usually helps some
statements and hurts none, and the gains often exceed physical changes.

### 1.1 Set-oriented, not row-at-a-time

Anti-pattern ("encapsulation imperative"): every row or field is an object
whose constructor issues its own query, so a collection is assembled by N
small queries plus one driver query — the join runs in the application.

```
-- intended: one statement, join in the server
SELECT o.id, o.detail
FROM   orders o JOIN watchlist w ON o.symbol = w.symbol
WHERE  w.trader = :t;

-- what an object layer generates: 1 + N round trips
SELECT symbol FROM watchlist WHERE trader = :t;          -- 1
for each symbol s: SELECT id, detail FROM orders WHERE symbol = :s;   -- N
```
Cost model: T ≈ N · (round_trip + parse/plan + execute_small) versus
round_trip + execute_join. With small rows the per-call constant dominates;
the entry's MySQL measurement of fetching 200 two-integer tuples showed close
to two orders of magnitude between one range query and a client-side loop.
Engine-side remedies: array/batch fetch, multi-statement batches, server-side
procedures for loops that must stay procedural, and instrumentation that
lets a DBA see "same statement template executed N times per transaction".

> **Beyond EDBS:** this is the ORM "N+1 selects" problem; ORMs expose
> eager/join fetching and batch fetching to fix it. Statement-template
> statistics (e.g., PostgreSQL pg_stat_statements, SQL Server Query Store)
> make the pattern visible as a high-calls, low-rows-per-call template.

### 1.2 The art of insertion

Overheads of putting rows in: (1) interface crossings — too-small batches;
(2) maintenance of every index on the table; (3) logging and constraint
checks.

- Batch inserts (multi-row VALUES, array binding).
- For large volumes: bulk-load a file into an unindexed staging table, then
  one INSERT … SELECT into the target — up to ~100× faster for large tables.
- Create (or rebuild) secondary indexes after the load, not before; a single
  index can multiply load time.
- Engine support: a bulk-load path with minimal logging where recovery
  semantics allow, sorted index build from the loaded data, deferred
  constraint validation.

### 1.3 Prepared statements and plan caching

> **Beyond EDBS:** prepare once, execute many amortises parse + optimize. Two
> engine-design hazards: (a) a plan cached for the first parameter values can
> be terrible for others under skew ("parameter sniffing" in SQL Server);
> PostgreSQL addresses this by planning the first five executions with the
> actual values and only then considering a generic plan if its estimated
> cost is not worse (`plan_cache_mode` overrides); (b) plan caches keyed on
> raw text explode with literal-laden SQL — normalise/parameterise or the
> cache becomes a contention point. Invalidate on DDL and on statistics
> changes, but rate-limit to avoid recompilation storms.

### 1.4 Connection management

> **Beyond EDBS:** connection establishment (authentication, process/thread
> creation, session state) is a start-up cost to amortise with pooling. Size
> the pool from Little's law: active connections needed ≈ request rate ×
> time a request holds a connection. A pool much larger than the engine's
> useful concurrency only moves queueing from the pool (cheap) into the
> engine (where it holds locks, memory and worker threads). Transaction-level
> pooling (e.g., PgBouncer transaction mode) breaks session-scoped state such
> as temp tables, session variables, and (historically) server-side prepared
> statements — the application contract must match the pooling mode.

### 1.5 Other application rules
- Do not hold transactions open across user interaction (see §3.2).
- Retrieve only needed columns (enables covering indexes; reduces transfer).
- Avoid client-side sorting/aggregation of large results; push it down.
- Use the engine's sequence/identity facilities for keys (see §3.1).

## 2. Schema tuning

Normalization eliminates update anomalies by splitting attributes across
tables; it can force joins on hot paths. Schema tuning is the principled
reintroduction of redundancy.

### 2.1 Denormalization
Example: `Ticket(ticket_id, cust_id, …)` and `Customer(cust_id, region)`.
If "tickets by region" is hot, add `region` to `Ticket`. Keep `Customer` so
a customer's region exists even with no tickets (avoids the deletion/
insertion anomaly). Costs: more space, more work per insert, and an update
to a customer's region must fan out to their tickets. The entry's experiment
showed the denormalized lookup clearly faster with both cold and warm
caches.

Rule: start normalized; denormalize sparingly, per measured hot query, and
record which redundant column depends on which source so maintenance code
(trigger, application, or MV) is complete.

### 2.2 Redundant (aggregate) tables
`RegionTotals(region, open_tickets)` maintained on insert. Wins when many
aggregate queries need exact answers; costs update time and a hot-spot row
per region (a concurrency problem — see §3). Maintained by trigger it is a
hand-made materialized view: the entry's experiment shows inserts much
slower, aggregate queries much faster. Prefer engine-maintained MVs where
available (correct incremental maintenance, optimizer rewrite).

### 2.3 Vertical partitioning
Split a wide table into fragments, each with the key, grouped by access
affinity; queries touching few columns scan less. Search space is
Bell(m) for m non-key columns, so use grouping (start with singletons, merge
by affinity) or splitting (start whole, split by access frequencies)
heuristics. Column stores are the limit; for row stores, a "hot narrow /
cold wide" split is the practical win.

### 2.4 Warehouses
Denormalized star/snowflake schemas with summary tables are normal there
because loads happen off-hours and the day is read-mostly.

## 3. Tuning concurrency control

Goal: reduce the number, duration and scope of lock conflicts. The
correctness/performance trade-off (Gray et al. 1976, degrees of consistency)
is the dial.

### 3.1 Counters and other hot items
Ad-hoc counter: `SELECT next FROM counter; INSERT …; UPDATE counter SET
next = next + 1` inside the user transaction → every inserter holds the
counter row lock until commit; throughput collapses as threads increase, and
worse as the transaction's other work grows (lock hold time grows).
System sequences/identity hold only a short latch for the increment and
release it at statement end. Price: gaps when a transaction that drew a
value aborts. Most applications accept gaps; some (legal invoice numbering)
cannot — for those, assign the number in a short separate step at the end,
or accept serialisation on that step only.

> **Beyond EDBS:** generalise to any hot spot: per-CPU/per-partition
> sub-counters summed on read (striping), sequence caching (hand out blocks
> of values per session/node), and avoiding monotonically increasing keys
> on a shared B-tree right edge in high-insert OLTP (hash/reverse keys or
> partitioning) when the right-edge leaf latch becomes the bottleneck.

### 3.2 "Living dangerously": cut transactions at interaction points
A reservation transaction that reads available seats, waits for a human
conversation, then books, holds read locks on the whole flight for minutes.
Split it: read availability in one short transaction, talk, then book in a
second transaction that re-validates. Still no double booking (the booking
step is serialised), but the user may be told a seat is free that is gone a
moment later. Most applications accept that weaker guarantee.

### 3.3 Rules of thumb
When blocking (more rarely deadlock) statistics point to a CC bottleneck:
1. Reorder transactions so accesses to hot items come last (shortens hold
   time under strict 2PL — locks are held from acquisition to commit).
2. Use system facilities that hold latches instead of locks (sequences),
   or MVCC/snapshot reads for long readers.
3. Lower isolation where application semantics allow, knowingly.
4. Chop long transactions (below).
5. Choose lock granularity per workload: row locks for OLTP point access;
   coarser (page/table) for scans to bound lock-manager overhead; watch
   escalation thresholds, which convert many row locks into a table lock
   and can serialise unrelated work.

### 3.4 Value of serializability (and why measurements mislead)
Experiment design from the entry: table R(a PK, b); one transaction sums b,
many concurrent transactions swap b values (sum invariant). Measure
correctness of the sum and throughput vs number of swap threads at
SERIALIZABLE vs READ COMMITTED.
- On engines where READ COMMITTED reads a statement snapshot (MySQL InnoDB,
  Oracle), the sum is always correct at both levels; READ COMMITTED has
  higher throughput because SERIALIZABLE takes next-key locks during the
  scan.
- On lock-based READ COMMITTED (the entry cites SQL Server, DB2 in that
  configuration), only about 40% of sums were correct.
Lesson for engine builders: the isolation *name* does not determine
behaviour; document and test the actual anomaly set (see
`concurrency-control-theory`). Lesson for benchmarkers: an isolation-level
comparison must check correctness, not only throughput.

### 3.5 Transaction chopping
> **Beyond EDBS:** (cross-referenced but not described in the bundle.)
> Shasha, Llirbat, Simon, Valduriez (TODS 1995): split each transaction into
> pieces executed as separate transactions such that every execution remains
> serializable. Build the SC-graph: S-edges link sibling pieces of the same
> transaction; C-edges link pieces of different transactions that conflict.
> A chopping is correct iff the graph has no cycle containing both an S-edge
> and a C-edge (SC-cycle); additionally, any rollback statements must be in
> the first piece so later pieces never need to undo. There is a unique
> finest correct chopping computable in polynomial time. Use: chop a long
> batch update into mini-batches when concurrent short transactions'
> conflict pattern permits — it shortens lock hold times without weakening
> isolation for that known workload.

### 3.6 Quantify before tuning
Use the lock-contention model in `performance-models-and-monitoring.md`:
conflict probability per request ≈ (M−1)·k/(2D) for M concurrent
transactions of k exclusive locks over D items; thrashing begins around
(M−1)k²/D ≈ 1.4. The k² term is why shortening or chopping long
transactions beats almost every other CC tuning.

## 4. Physical layer tuning

### 4.1 Hardware: build a balanced system
Back-of-envelope from the entry's (dated but instructive) figures, assuming
~500k instructions of DBMS work per I/O:
- OLTP (random I/O, ~70 IOPS per disk): an n-GIPS processor is
  disk-bound until it has roughly 30·n disks; transactions spend far more
  time waiting for heads than computing.
- DSS (sequential 64 KB I/Os at 50 MB/s ≈ 8000 IOPS per disk): an n-GIPS
  processor saturates with roughly n/4 disks; the bus may bottleneck first.
Method, which outlives the numbers: per I/O CPU cost × I/O rate per device
→ devices per core needed to balance; redo with current flash IOPS and
bandwidth (flash moves OLTP from disk-bound toward CPU/latch-bound).

### 4.2 Operating system and I/O path
- Raw device vs file system: raw gives control and avoids double buffering
  (OS page cache + buffer pool); file systems give manageability. Direct
  asynchronous I/O on files gives most of both — and out-of-the-box configs
  often still use buffered I/O, so verify.
- Synchronous I/O blocks the issuing thread; asynchronous lets the server
  keep many requests in flight across files (needed for prefetch and for
  write-behind).
- Lay out scanned tables and sequentially written files (log, history) in
  few large extents; sequential bandwidth can be 10–100× random.
- **Log placement**: give the log (and any append-only history file) a
  device to itself; any other frequently accessed file there turns
  sequential log writes into seeks. Exception: a device with a large non-volatile write
  cache absorbing the log stream.
- Random-access placement: seek time ≈ a + b·√distance, so cluster
  co-accessed hot data in nearby cylinders when disks are still in play.
- Thread priorities: favour latency-critical work (log writes), keep
  fairness, avoid starvation and priority inversion (a low-priority thread
  holding a latch that a high-priority one needs).

> **Beyond EDBS:** on Linux the modern path is O_DIRECT with io_uring (or
> libaio) and explicit fsync/fdatasync discipline for durability; NVMe
> devices want deep queues and many submitting threads, which changes the
> optimal I/O scheduler (often none) and makes CPU per I/O the limit.

### 4.3 RAID choices
| Level | Read | Small write cost (uncached) | Degraded mode | Fits |
|---|---|---|---|---|
| RAID0 striping | parallel, removes access skew | 1 | data loss | scratch/temp |
| RAID1 mirroring | either copy (≈2× read bandwidth, smart routing) | 2 writes | surviving disk takes 2× read load; interleaved declustering spreads it to n/(n−1) | log, write-heavy OLTP data (RAID10) |
| RAID5 parity | parallel | 4 accesses (read old data + old parity, write both) | reconstruct via fork-join over N−1 disks; read load doubles | read-mostly, large sequential |
| RAID6 (two checks) | parallel | 6 accesses | survives 2 failures / latent sector errors during rebuild | large arrays where rebuild windows are long |

Mitigations: non-volatile controller cache for fast writes (writes
acknowledged once in NVS; dirty blocks overwritten before destaging;
batched destage with disk scheduling); clustered RAID with parity group
G < N reduces degraded-mode load to (G−1)/(N−1); distributed sparing uses the
spare's bandwidth during normal operation; rebuild-in-idle-time
("vacationing server") limits rebuild impact on foreground response time.
Striping unit: ~1 MB is robust for database mixes (see
`online-and-self-tuning.md` §4). Detailed device modelling belongs to
`storage-devices-and-io`.

### 4.4 Memory configuration
Memory is zero-sum across buffer pool, sort/hash work areas, lock table,
statement/plan cache, and connection memory. OLTP: buffer pool dominant;
DSS: large work areas too. Prefer an automatic broker (online algorithm) and
validate it with a buffer-miss-rate vs size curve measured from a trace (the
"knee" sizing method).

## 5. Configuration wizards and the DBA role

Configuration wizards map a few high-level answers (OLTP vs OLAP, expected
concurrent users) to dozens of knobs (log buffer size, thread pool size,
memory split). Engine-builder lesson: if a wizard can derive a knob from a
workload description, the engine can derive it at run time from observed
workload — prefer eliminating the knob (trade-off elimination) over a
better wizard. Other wizards: import/export mapping, backup/restore
(full/incremental, scope, target).

The DBA is a role (often several people) covering installation,
configuration, monitoring, security, backup/recovery, migration — and,
crucially, post-deployment physical design: application developers design on
small samples on unknown hardware; the DBA tunes on the real data and real
server. Every tuning feature an engine adds should serve that workflow:
observable, reversible, explainable recommendations.

Sources: Application-Level Tuning (p.129); Schema Tuning (p.3308); Tuning
Concurrency Control (p.4252); Physical Layer Tuning (p.2765); Performance
Analysis of Transaction Processing Systems (p.2732); Database Tuning Using
Trade-Off Elimination (p.993); Administration Wizards (p.69); Database
Administrator (DBA) (p.935); Physical Database Design for Relational
Databases (p.2759); Optimization and Tuning in Data Warehouses (p.2619).
