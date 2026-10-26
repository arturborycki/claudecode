# Architecture, scaling metrics, availability and elasticity

Scope: how hardware sharing shapes a parallel DBMS, how to measure whether
parallelism is paying off, the taxonomy of parallelism an engine exposes, and
the "keep it running while it grows/shrinks/heals" concerns (database
clusters, elasticity, online recovery). Placement, operators, skew and
optimization each have their own reference file.

---

## 1. Hardware sharing models

| Model | What is shared | Coordination cost lives in | Scales to (era guidance) | Load balancing | Who used it |
|---|---|---|---|---|---|
| Shared-memory (shared-everything, SMP) | RAM + disks, single OS | memory/interconnect contention | tens of CPUs; best cost/perf historically ~16 | trivial: hand next task to least-busy CPU | every vendor's SMP port; DuckDB-class single-node engines today |
| Shared-disk | disks only; private RAM, one OS per node | cache coherence (distributed lock manager), shared-storage bandwidth | ~100 nodes in the 1990s literature | easy: any node can read any page | Oracle (RAC) |
| Shared-nothing (MPP) | only the network | data placement + network shuffles | hundreds to thousands of nodes | hard: decided by *where data lives*, not by current load | Teradata, Gamma, DB2 PE/DPF, Greenplum, Netezza, Redshift, Impala, Presto |
| Hierarchical / shared-something | shared-nothing across nodes, shared-memory (or disk) within a node | both levels | as shared-nothing | two-level: intra-node dynamic, inter-node by placement | essentially every modern MPP (multi-core nodes) |

Engineering consequences:

- **Shared-memory**: lock tables, catalog, buffer pool are ordinary shared
  structures; inter-query parallelism is nearly free; intra-query parallelism
  needs only a task scheduler and partitioned operators. Limits: memory
  bandwidth and coherence traffic; a memory fault can take down all CPUs.
- **Shared-disk**: migration from a centralized DBMS is easy (no data
  reorganization). Every page cached on two nodes needs a coherence protocol:
  page ownership via a distributed lock manager, plus distributed commit.
  Coherence messages and the shared storage path are the bottlenecks.
- **Shared-nothing**: each node is effectively a site of a distributed DBMS,
  so fragmentation, distributed commit and distributed query processing are
  reused — but the node count is far higher and the interconnect far faster
  than in classic distributed DBMSs, so the algorithms differ (full
  declustering, repartitioning joins, no "maximize local processing" goal
  because users are not attached to nodes). Adding nodes implies data
  reorganization.

> **Beyond EDBS:** Cloud warehouses (Snowflake, SIGMOD 2016; Redshift
> RA3; BigQuery) reintroduce *shared-disk at the storage layer* (object
> store) with *shared-nothing execution* and local SSD caches. Placement then
> matters for cache affinity and pruning (micro-partition/zone-map metadata)
> rather than for ownership. Oracle Exadata pushes predicate/projection
> evaluation into storage cells — the 1980s database-machine idea (below) on
> commodity hardware.

### Database machines (historical lineage)
1970s–80s attempts to put computation next to the disk: processor-per-track,
processor-per-head (search a cylinder per rotation), processor-per-disk
(cheapest, least gain), and multi-processor-cache designs. They lost on
cost/performance to software on commodity parts; the durable lesson was
"raise I/O bandwidth by declustering across many disks", which is exactly
the shared-nothing data placement principle (and RAID's). The idea returns
whenever storage gets compute (smart SSDs, storage-side filtering, S3
Select-style pushdown).

---

## 2. Speedup, scaleup and why they break

Definitions (make them measurable in your benchmark harness):

- **Speedup** (fixed problem): `S(p) = T(1, D) / T(p, D)`. Linear iff
  `S(p) = p`.
- **Scaleup** (problem grows with machine): `U(p) = T(1, D) / T(p, p·D)`.
  Linear iff `U(p) = 1` (elapsed time constant).
  - *Batch scaleup*: one query over p× data.
  - *Transaction scaleup*: p× concurrent clients over p× database; the
    natural target for inter-query parallelism.

Barriers (DeWitt & Gray 1992 framing):

1. **Startup** — fixed cost of launching p operator instances, opening p²
   exchange connections, shipping plan fragments. Model it as
   `T(p) ≈ W/p + c_start·p` for per-instance startup or `+ c·p²` for
   all-to-all connection setup; the optimum DOP is finite even with perfect
   balance.
2. **Interference** — contention for shared resources (bus, memory
   bandwidth, a shared disk, a coordinator, a lock or latch, the network
   switch). Each added processor slows the others a little.
3. **Skew** — elapsed time equals the *slowest* instance: `T(p) = max_i t_i`.
   With a mean of `W/p`, a single partition holding fraction `f` of the work
   caps speedup at `1/f` regardless of p.

Amdahl bound for a plan with serial fraction `s` (coordinator merge, final
top-N, serial plan compilation): `S(p) ≤ 1 / (s + (1−s)/p)`.

**Super-linear speedup is real and legitimate** when the aggregate memory of p
nodes turns an external algorithm into an in-memory one (external sort →
in-memory sort, Grace → one-pass hash join), or when smaller per-node
partitions fit in cache. Report it, but do not let it hide a startup or skew
regression at higher DOP.

**Response time vs total work.** Intra-query parallelism lowers response time
but raises total work (communication, partitioning, synchronization).
Inter-query parallelism raises throughput but also adds total work through
interference. Clustering a query's data on one node minimizes work. Every
placement and DOP decision is a point on this trade-off; an optimizer that
only minimizes single-user response time will starve a multi-user system.

---

## 3. Taxonomy of parallelism

```
parallelism
├── inter-query        many queries at once  -> throughput (OLTP, mixed)
└── intra-query        one query, many processors -> response time
    ├── inter-operator (operator-level)
    │   ├── pipelined   producer/consumer run concurrently   f(g(X))
    │   └── independent (bushy) no data dependency           f(g(X), h(Y))
    └── intra-operator  same operator on disjoint partitions  (SIMD-like, data parallel)
        ├── static partitioning   = stored placement (scans, selections)
        └── dynamic partitioning  = repartitioning at run time (joins, aggregates)
```

Properties an engine builder must internalize:

- **Inter-query** is orthogonal to intra-query; both coexist. Its hard part is
  ACID under concurrency, not parallelism.
- **Pipelined** parallelism avoids materializing intermediates (saves memory
  and I/O) but: relational pipelines are short (≈10 operators is long),
  blocking (stop-and-go) operators — sort, hash-join build, hash aggregation
  — cut pipelines, and the slowest stage sets the rate (execution skew).
  Startup/teardown idling: stages near the pipeline end idle at start; stages
  near the beginning idle at the end.
- **Independent** parallelism interferes only through shared resources
  (memory, caches, bandwidth), so it is easy to schedule — but enlarges the
  working set.
- **Intra-operator** parallelism is where nearly all scalable speedup comes
  from. Easy for unary operators, needs real algorithms for binary ones.
- Pure pipelining yields poor load balance; partitioning (especially hashing)
  delivers higher and more reliable speedup. When there are more processors
  than active users, intra-operator parallelism is the only way to use them.

> **Beyond EDBS:** On multi-core nodes, *morsel-driven* parallelism (Leis et
> al., SIGMOD 2014; used by HyPer/Umbra and DuckDB) replaces fixed
> per-operator DOP with a pool of workers pulling small input chunks
> ("morsels") through a whole pipeline, with NUMA-aware dispatch and
> shared (or per-thread then merged) sink state. DOP becomes elastic inside
> a pipeline and intra-node skew mostly disappears; the exchange/shuffle
> only remains *between nodes*. A distributed engine built on DuckDB thus has
> two levels: morsel parallelism inside a node, Volcano-exchange parallelism
> across nodes.

---

## 4. Database clusters (parallelism from outside the DBMS)

A *database cluster* (DBC) runs an unmodified sequential DBMS on each node and
puts a middleware layer between applications and the nodes, intercepting
calls at the driver (JDBC/ODBC). It is non-intrusive: no change to the
application, the DBMS, or the database. Typical layout: shared-nothing nodes,
**full replication** of the database, middleware split into a global
component (routing, scheduling, consistency) and a local one (local tuning
for load balancing).

- **Inter-query parallelism**: route any read-only query to any replica.
  Updates require a scheduler that applies conflicting updates in the same
  order at every replica (and freshness rules for lazy schemes).
  Systems: C-JDBC, Sequoia (OLTP/e-commerce), RepDB* (preventive
  replication), Pgpool, Leganet/FAS (freshness-aware routing).
- **Intra-query parallelism**: the black-box DBMSs cannot produce cooperating
  parallel plans and physical repartitioning would break autonomy, so DBCs
  use **virtual partitioning** (see `placement-and-declustering.md` §7):
  rewrite one query into range-restricted subqueries over the replicas and
  compose the partial results. Systems: PowerDB (ETH, origin of the idea),
  ParGRES, OLAP*.
- Reported results (ParGRES on TPC-H, 32 nodes) show super-linear speedups for
  many queries — smaller ranges stay cache/memory-resident on each node.

Why it matters today: "a coordinator over many single-node engines" is the
architecture of most DuckDB-, SQLite- or Postgres-based distributed engines
(Citus, HadoopDB, many MotherDuck-style designs). The DBC literature names
the core limitation: each node's optimizer is unaware of the others, so the
middleware must own decomposition, partial-result composition and balancing.

---

## 5. Elasticity

Elasticity = scalability that is **self-managed and online**: add *and remove*
nodes in response to load, without an administrator taking the system down
or clients seeing interruptions. Requirements:

1. Monitor workload (per-partition load, not just per-node).
2. Model resource needs (when to grow/shrink, how many nodes, which data
   moves).
3. Physically reconfigure partitioning online, with consistent hand-off of
   ownership while transactions/queries continue.

Replication and load balancing are usually combined with it. Representative
systems: ElasTraS (Das et al., TODS 2013), RTP robust tenant placement for
in-memory clusters (Schaffner et al., SIGMOD 2013), E-Store fine-grained
partitioning for hot tuples (Taft et al., PVLDB 2014).

Design rules for an MPP engine:

- **Never make compiled plans depend on physical location.** The run-time
  must resolve partition → node (associative access) so a reorganization does
  not force recompilation. In a Teradata-style design this is the hash map
  (hash bucket → AMP); in a Ballista/DataFusion-style design it is the
  scheduler binding stages to executors at run time.
- **Indirect through many logical buckets** (≫ nodes): reconfiguration moves
  whole buckets, and the move set is computable (only buckets whose owner
  changes). Plain `hash(k) mod n` moves almost every row when n changes.
- Contraction needs the same machinery in reverse plus drain semantics for
  in-flight exchanges.

> **Beyond EDBS:** Squall (Elmore et al., SIGMOD 2015) gives a concrete
> live-migration protocol for partitioned main-memory OLTP. Storage-disaggregated
> warehouses make compute elasticity cheap (no data move, only cache warm-up)
> and push the hard problem into cache affinity and workload isolation.

---

## 6. Availability and online recovery

### Replica placement for availability (shared-nothing)
- **Mirroring**: primary + backup on two nodes. On failure the survivor's load
  doubles → the slowest node now sets elapsed time for every query.
- **Interleaved declustering** (Teradata): the backup of one node's
  partition is spread across the other nodes of its cluster; after a failure,
  the extra load spreads over many nodes. Two failures in the same cluster
  make data unavailable; rebuilding a primary from scattered backups is
  costly. (Teradata *fallback* with clusters of AMPs bounds this.)
- **Chained declustering** (Gamma; Hsiao & DeWitt 1990): backup of node i's
  partition lives on node i+1. Two *adjacent* failures are needed to lose
  data (less likely than "any two"). After a failure, the read load of the
  failed node can be shifted fractionally along the chain so every survivor
  carries `1 + 1/(n−1)` of normal load.
- A placement trick from the execution literature: hash each item to two sites
  with two hash functions constructed so the sites always differ.

### Online recovery of a replica
Offline recovery (quiesce, copy, resume) defeats the purpose of replication.
Online recovery transfers state while the state changes underneath. Generic
phases:

1. **Local recovery** — ordinary crash recovery to a locally consistent state
   (empty for a brand-new replica).
2. **Find last committed update** — scan the local log for the last update
   transaction reflected (approximation allowed if later effects are
   idempotently rewritten). A new replica first obtains an online checkpoint
   (point-in-time copy).
3. **Global recovery start** — announce join, report last known update, elect
   a recoverer.
4. **Global recovery (state transfer)** — synchronized with replica control so
   the transferred state is a consistent cut.
5. **End-of-recovery handshake** — split the transaction stream into "covered
   by the transfer" and "to be applied after", with no gap and no overlap.

Protocol families:

| Protocol | Mechanism | Availability during recovery | Notes |
|---|---|---|---|
| Recovery locks (Kemme, Bartoli, Babaoglu 2001) | atomically take special read locks over the whole DB; ship tuples, release locks progressively; recovering node buffers incoming updates | writes blocked initially, improves as locks release | kernel-based; reads never blocked |
| Multi-round | ship missed updates in rounds; each round ships what changed during the previous one; final short round with buffering | fully online | buffering only in the last round |
| Log-based (Jiménez-Peris et al. 2002, on Nodo/Middle-R) | recoverer replays log suffix per *conflict class*; master injects an end-of-recovery marker into the update stream to close the race | fully online | per-class recovery, parallel recoverers, adaptive number of recoverers by load |
| Historical queries (Lau & Madden 2006, warehouses) | catch up with lock-free as-of-time queries, then a final locking query | near-online | needs time-travel capability |

Metric: **performability** = cumulative delivered performance across failures
and recoveries. Staying "available" at 0.1% of normal throughput is a failure
by this metric; adaptive recoverers trade recovery speed against foreground
throughput.

Middleware-based replication can only use what the DBMS interface offers
(logs exposed as update streams, as-of queries); kernel-based replication can
use internal locks. Byzantine and diverse-replica variants need multiple
recoverers and value translation across vendors.

> **Beyond EDBS:** For *query* fault tolerance (as opposed to replica
> recovery) the spectrum is: restart the whole query (classic MPP; cheap
> when queries are short), restart a failed stage from materialized shuffle
> output (MapReduce, Spark, Ballista), or recompute lost partitions from
> lineage (Spark RDDs). Trino's fault-tolerant execution spools exchange data
> to external storage so tasks can be retried. The choice is a pipelining vs
> materialization trade: spooling every exchange costs latency on the
> failure-free path.

---

Sources: Parallel Database Management (p.2663); Shared-Memory Architecture
(p.3485); Shared-Disk Architecture (p.3484); Shared-Nothing Architecture
(p.3486); Database Machine (p.956); Parallel Query Processing (p.2677);
Parallel Query Execution Algorithms (p.2668); Inter-query Parallelism
(p.2029); Intra-query Parallelism (p.2030); Inter-operator Parallelism
(p.2028); Intra-operator Parallelism (p.2030); Operator-Level Parallelism
(p.2601); Database Clusters (p.940); Virtual Partitioning (p.4462);
Elasticity (p.1269); Parallel Data Placement (p.2661); Online Recovery in
Parallel Database Systems (p.2564).
