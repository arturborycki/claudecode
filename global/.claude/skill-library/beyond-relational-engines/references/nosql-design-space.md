# NoSQL design space, CAP, and the return of SQL

Read this when you must reason about key-value / wide-column / document
stores as *design points relative to a relational engine*: what each one
removed from the RDBMS contract, what it bought with that, how it
partitions, routes, replicates and fails over, what CAP and eventual
consistency formally mean, why transactions and SQL came back, and what
multitenancy and elasticity demand from an engine.

---

## 1. The trade, stated precisely

The first-generation scale-out stores (Bigtable 2006, Dynamo 2007, PNUTS
2008, then HBase, Cassandra, MongoDB, Redis, CouchDB) were not "databases
without SQL"; they were databases that deliberately shrank the unit of
atomicity and coordination to **one key (one row, one document)**.

| RDBMS feature removed or weakened | What it bought |
|---|---|
| Multi-row / multi-table ACID transactions | Every request touches one node's state → no distributed commit, no global lock manager; horizontal partitioning scales almost linearly |
| Joins and declarative set-oriented queries | Request cost bounded and predictable (get/put/scan-range); no optimizer misestimates in the serving path |
| Schema-on-write, normalization | Schema evolution without DDL, heterogeneous records, wide sparse rows; application owns the model |
| Strong (linearizable / 1SR) replica consistency | Writes accepted under partition and across data centers with local-latency acks |
| Secondary indexes, constraints, triggers | No cross-partition maintenance on write |
| "Database as a cohesive whole" failure model | Failure of one node makes only *its* keys unavailable; the rest keeps serving |

The last row is underrated. A classical shared-nothing RDBMS (Teradata,
DB2 DPF) treats the database as a single consistent object: a node failure
without a fallback copy stops queries that touch it, and a transaction
spanning nodes blocks on 2PC. Key-scoped semantics turn a partial failure
into partial unavailability rather than total unavailability.

**What was *not* traded away** and is now everywhere: LSM storage
(`lsm-storage`), log-structured replication, consistent hashing, MVCC with
timestamps, Paxos/Raft-replicated metadata, and the idea that the physical
key design *is* the schema.

---

## 2. Data models as a spectrum of value structure

All of them are maps from a key to a value; they differ in how much
structure the system (rather than the application) understands inside the
value.

| Model | Value | Server-visible structure | Typical access | Systems |
|---|---|---|---|---|
| Blob KV | opaque bytes | none | get/put/delete by key | Dynamo, Riak, Redis (plus typed structures), RAMCloud |
| Flat row | fixed or flexible columns | column names, types | get/put row, scan by key range, optional secondary index | PNUTS |
| Wide-column / column-family | set of column families, each a sparse map qualifier → versioned cells | families (physical locality/ACL unit), qualifiers, timestamps | row get, range scan, column/family projection, version reads | Bigtable, HBase, Hypertable, Cassandra |
| Document | nested tree (JSON/BSON/XML/protobuf) | full path structure; indexes on paths | key get, predicate queries on paths, secondary/multikey indexes, aggregation pipelines | MongoDB, CouchDB, Couchbase |
| Graph | nodes/edges with properties | topology | neighborhood expansion, traversal | Neo4j, OrientDB (document + graph) — see `graph-and-rdf-engines.md` |

### Wide-column (Bigtable) in detail
- Logical model: a sorted map keyed by `(row key, family:qualifier,
  timestamp)` → uninterpreted bytes. Rows sorted lexicographically by key;
  sparse — absent cells cost nothing.
- **Column families** are declared in the schema (few, stable); qualifiers
  are data (unbounded, per row). A family is the unit of storage locality
  (locality groups → separate SSTable sets), compression, and access
  control. This is DSM-like vertical partitioning by family, not a true
  column store: within a family, cells of a row are co-located.
- Timestamps give per-cell versioning; GC policy per family (keep last *n*
  versions or versions newer than *t*).
- Atomicity: **single-row read-modify-write** (including multi-column within
  the row). Row design therefore becomes transaction design: put everything
  that must change atomically into one row (e.g., reversed URL as key with
  all crawl attributes).
- Physical: rows are range-partitioned into **tablets**; a tablet = memtable
  + immutable SSTables on a distributed FS, i.e., an LSM tree. Tablet
  location is a 3-level B-tree-like hierarchy (lock-service file → root
  tablet → METADATA tablets → user tablets) cached in clients.
- Master assigns tablets; tablet servers hold **leases** in the lock
  service (Chubby); a server that loses its lease must stop serving.

### Dynamo in detail
- Blob KV; partitioning by **consistent hashing** on a ring with **virtual
  nodes** (each physical node owns many tokens → smoother load, incremental
  rebalancing, heterogeneity by token count).
- Each key replicated on the next N distinct physical nodes clockwise (the
  *preference list*). Reads/writes use **sloppy quorums**: first R/W
  *healthy* nodes in the extended list; a stand-in node keeps a **hint** and
  hands the write back when the owner returns (hinted handoff).
- Concurrent writes produce **siblings** tracked by vector clocks; the
  application reconciles (canonical example: union of shopping-cart items,
  which can resurrect deleted items).
- Background **anti-entropy** with Merkle trees per key range; gossip-based
  membership and failure detection; every node can route ("zero-hop DHT").
- Cassandra = Dynamo's ring, gossip and tunable quorums + Bigtable's
  row/column-family model and LSM storage; later added Paxos-based
  lightweight transactions (compare-and-set on a partition).

### PNUTS in detail
- Ordered or hashed tables of flat records; geo-replicated via a
  publish/subscribe message broker.
- **Per-record timeline consistency**: every record has a master replica
  (can migrate to where writes originate); all replicas apply that record's
  updates in the same order, so they see a prefix of one timeline. API makes
  the consistency choice explicit per call: read-any (possibly stale),
  read-critical(≥ version), read-latest, write, test-and-set-write(version).
- Lesson: a consistency model *between* eventual and linearizable, scoped to
  one record, that is cheap and easy for applications to reason about.

### Document stores in detail
- Collections of self-describing documents; server understands paths, so it
  can build **secondary indexes on paths**, including multikey indexes (one
  entry per array element) and (in some systems) materialized views
  (CouchDB map/reduce views).
- MongoDB: shard key (range or hashed) partitions a collection into chunks;
  routers (mongos) consult config servers for chunk → shard map; each shard a
  replica set with an elected primary; per-operation write concern
  (w=1/majority) and read concern/preference choose the consistency point.
  Storage engine since 3.x is a B-tree/MVCC engine (WiredTiger) — i.e., a
  conventional storage manager under a document API.
- See `semistructured-json-xml-storage-and-indexing.md` for how to store
  and index the document *inside* the engine.

> **Beyond EDBS:** the single-key atomicity boundary eroded quickly.
> MongoDB added multi-document transactions (4.0 for replica sets, 4.2 for
> sharded clusters, snapshot isolation); DynamoDB added transactional
> multi-item APIs (2018); Cassandra lightweight transactions use Paxos per
> partition. The design question shifted from "transactions or scale" to
> "what is the cheapest coordination for *this* transaction's footprint".

---

## 3. Partitioning, routing, cluster management

### Partitioning functions
| Scheme | Wins when | Cost / risk |
|---|---|---|
| Range on key (tablets/regions) | Range scans, prefix scans, locality of related keys (reverse-domain URLs, `(user, ts)` composite keys); easy split/merge | Hotspots on monotonically increasing keys (timestamps, sequences) → salting/bucketing prefixes, which then destroys range scans |
| Hash (mod N) | Uniform load, no metadata beyond N | Changing N moves almost all keys; no range scans |
| Consistent hashing (ring) | Elastic membership; only ~K/N keys move when one of N nodes joins/leaves | Non-uniform arcs without virtual nodes; range scans lost |
| Hash of partition key + range of clustering key (Cassandra) | Spreads entities, keeps one entity's rows sorted and co-located | "Wide partition" hotspots; queries must specify the partition key |
| Directory / lookup table | Arbitrary placement, tenant pinning, workload-aware placement | Directory becomes a dependency; must be replicated and cached |

The tablet (region, chunk, vnode) — not the node — is the unit of
distribution, load balancing, replication and recovery. Keep it 100s of MB
to a few GB so moves are cheap and per-tablet metadata stays bounded.

### Request routing
- **Centralized metadata + client cache** (Bigtable/HBase, MongoDB config
  servers): clients cache location; a stale cache hit yields a "not serving"
  error and a re-lookup. Invariant: a server must reject requests for
  tablets it no longer owns — otherwise stale clients write to an orphan.
- **Decentralized** (Dynamo/Cassandra): every node knows the ring via gossip
  and forwards; one-hop for clients that are ring-aware.

### Cluster management
- **Master + leases**: data servers hold time-bounded leases on their
  tablets from a highly available lock service; master reassigns on lease
  loss; master itself is replicated with Paxos. Correctness hinges on
  *fencing*: the old owner must stop serving before the new one starts, i.e.
  lease expiry on the server's clock must precede reassignment on the
  master's clock, with a margin for bounded clock drift. (See
  `distributed-consensus`.)
- **Gossip**: periodic state exchange with random peers; failure suspected
  when heartbeats stop arriving; accrual detectors output a suspicion level
  instead of a boolean. No single point of failure, but membership views
  are eventually consistent — two nodes may briefly disagree on ownership,
  which is precisely why such systems need sloppy quorums and repair.

### Replication axes
Implicit (the distributed file system replicates SSTables; the store sees
one copy — Bigtable/HBase) vs explicit (store-level replicas — Dynamo,
Cassandra). Intra-DC vs inter-DC (geo) replication; synchronous vs
asynchronous; primary-copy vs multi-master. Details in
`replication-and-consistency` and `replication-protocols`.

---

## 4. CAP, PACELC and eventual consistency, precisely

### CAP
- Conjectured by Fox & Brewer (1999/2000), proved by Gilbert & Lynch
  (2002) in an asynchronous network model where messages may be lost.
- **C** = linearizability of a read/write register (not ACID "C"). **A** =
  every request received by a non-failed node eventually gets a non-error
  response (total availability, not a percentage SLA). **P** = the network
  may drop arbitrarily many messages between groups of nodes.
- Proof idea: split nodes into G1 and G2 with all inter-group messages lost.
  A write to x on G1 must complete (A); a subsequent read on G2 must
  complete (A) but cannot have learned the write, so it returns the old
  value — violating C.
- Partitions are a property of the environment, not a design choice; so the
  real choice is **what to give up during a partition**: refuse/queue some
  operations (CP) or accept divergence (AP). Outside partitions a system can
  have both.
- **PACELC** (Abadi 2012): if Partition, choose A or C; Else, choose
  Latency or Consistency. The E-branch dominates real designs: synchronous
  cross-region replication costs a WAN round trip on every write even when
  nothing is broken. Dynamo/Cassandra default PA/EL; Spanner-like systems
  PC/EC; PNUTS PC/EL (masters per record).
- Common misuses to flag in reviews: "CAP says pick two" (P is not
  optional); "we are CA" (meaningless for a distributed system); using CAP
  to justify weak consistency in a single-DC deployment where partitions are
  rare and latency is cheap.

### Eventual consistency, formally (Saito & Shapiro framing)
For each replicated object x and node n, let S_n(x) be the schedule of
updates n has executed (aborted/undone updates marked as such). EC holds if
at all times:
1. Some prefix of S_n(x) is *state-equivalent* to a prefix of S_m(x) for
   every other replica m (same initial state → same final state); this is
   the **committed prefix**.
2. The committed prefix only grows; its operations and their order never
   change.
3. Every submitted update eventually appears in the committed prefix exactly
   once, either executed or aborted.
4. Every executed update in the committed prefix satisfied its
   preconditions in the state where it ran.

State equivalence is weaker than conflict equivalence: commuting operations
may appear in different orders; a blind overwrite makes earlier operations
irrelevant. Everything outside the committed prefix is **tentative** and may
be reordered or undone by reconciliation. Engine consequence: if the store
exposes tentative state to readers (it almost always does), clients can
observe values that later disappear — exactly the anomaly session
guarantees (read-your-writes, monotonic reads, …; Terry et al. 1994, Bayou)
and CRDTs (convergence by construction) address. See
`replication-and-consistency`.

> **Beyond EDBS:** "Rethinking eventual consistency" (Bernstein & Das,
> SIGMOD 2013) and the measurement literature (probabilistically bounded
> staleness) argue EC should be specified with *bounds* (staleness in time
> or versions) and session guarantees, not as a bare liveness property.

---

## 5. Getting transactions back: two families

### Family A — co-locate the transaction's footprint on one node
Restrict the schema/workload so that most transactions touch one
"ownership granule"; then run a classical single-node concurrency control
(2PL, OCC, MVCC) on that node with no distributed commit.

| Mechanism | Granule | Notes |
|---|---|---|
| Entity groups (Megastore) | Root entity + child entities sharing a key prefix | ACID within a group via a Paxos-replicated per-group log; cross-group via 2PC or async messaging; OCC + MVCC |
| Table groups (SQL Server-based cloud DB) | Rows sharing a partition key across a set of tables | Lock-based CC; each partition is a replicated unit |
| Tree schema (one root table, others reference it) | Key of the root table | Partition everything by the root key; foreign-key closure stays local |
| Dynamic key groups (G-Store / ElasTraS line) | Application-declared set of keys | System migrates ownership of the keys to one node for the group's lifetime, then dissolves it |
| Workload-driven partitioning (Schism-style) | Graph partition of co-accessed tuples | Minimizes distributed transactions; needs a lookup directory |

Decoupling **ownership** from **storage** (compute owns keys, a replicated
storage layer holds pages/log) makes ownership migration cheap — just move
the right to serve plus warm cache — which is the root of elastic OLTP
(see §7) and of later log-is-the-database designs.

### Family B — make distributed transactions affordable
- Multi-version storage + timestamp ordering + 2PC whose participants are
  Paxos groups (so a coordinator failure no longer blocks forever).
- **Spanner**: TrueTime API returns an interval [earliest, latest] with
  bounded uncertainty (GPS + atomic clocks); a commit timestamp `s` is taken
  at the interval's upper end (`≥ TT.now().latest`) and the leader **waits out
  the uncertainty** (until `TT.after(s)`) before
  making the commit visible, yielding externally consistent (strict
  serializable) transactions and lock-free snapshot reads at any timestamp.
- **Percolator** (Bigtable + client-side SI with a timestamp oracle),
  **Calvin** (deterministic ordering before execution removes 2PC),
  **CockroachDB** (hybrid logical clocks, serializable, Raft ranges),
  F1 (SQL on Spanner). See `distributed-transactions`.

---

## 6. Why SQL came back (and what stayed)

1. **Application-side joins and integrity were bug farms.** Without
   multi-key atomicity, every invariant spanning two keys needed hand-rolled
   compensation; denormalized copies drifted.
2. **Secondary indexes are needed anyway**, and maintaining them
   consistently across partitions *is* a distributed transaction.
3. **Analytics** over operational data needs scans, joins and aggregation —
   which leads straight back to a query optimizer.
4. **The cost of coordination fell**: datacenter RTTs dropped to tens of
   microseconds, Paxos/Raft became libraries, RAM-resident working sets
   made commit latency dominated by replication rather than disk.
5. **Declarative access is how organizations scale people**, not just
   machines: SQL is the lingua franca of tools.

"NewSQL" (Spanner/F1, CockroachDB, FoundationDB with SQL layers, VoltDB,
Clustrix, TiDB) kept the NoSQL lessons: range/hash-partitioned key space as
the physical layout, LSM or MVCC B-tree storage per range, consensus-
replicated ranges, online splitting/rebalancing, and JSON/document columns
for schema flexibility. Relational engines in turn absorbed native JSON
types and path indexes. Convergence, not victory.

**Design-review heuristics** distilled:
- If your workload's transactions have a natural root key, Family A beats
  Family B on cost; encode the root key as the leading partition and
  clustering key everywhere (including secondary indexes, or they become
  global and need distributed maintenance).
- Global secondary indexes on a partitioned store are either synchronously
  maintained (distributed transaction per write) or asynchronously
  maintained (index reads can miss recent writes) — make the choice visible
  in the API.
- Range partitioning + monotonically increasing keys = one hot tablet. Detect
  in testing with a sequential-key insert benchmark.

---

## 7. Main-memory DBMS as a family

- When the database fits in RAM, I/O stops being the cost unit; the
  bottlenecks become CPU instructions per tuple, cache misses, latching,
  and logging. Consequences: lean tuple formats (no slotted-page
  indirection required), cache-conscious indexes (T-tree in the 1980s,
  later CSB+-trees and cache-line-sized B-tree nodes with low fan-out),
  pointer-based rather than RID-based references, and columnar layouts for
  analytics (MonetDB).
- Durability despite volatile storage: (i) redo logging to stable storage
  (group commit) + periodic checkpoints; (ii) battery-backed / non-volatile
  RAM; (iii) synchronous replication to a standby with automatic failover
  (ClustRa, MySQL Cluster/NDB).
- Historical niche: telecom and real-time systems needing predictable
  latency (TimesTen, solidDB, DataBlitz/Dalí, ClustRa); later OLTP and
  analytics. Also deployed as a read cache in front of a disk-based DBMS.
- Key-value variants keep all data in DRAM (Redis, RAMCloud) or cache
  through memory-mapped files (early MongoDB).

> **Beyond EDBS:** the modern main-memory OLTP lineage — H-Store/VoltDB
> (partitioned, single-threaded serial execution per partition, command
> logging), Hekaton (latch-free Bw-tree and hash indexes, optimistic MVCC,
> compiled stored procedures), HyPer (fork-based snapshots, then MVCC;
> data-centric code generation), Silo (epoch-based OCC) — is covered in
> `concurrency-control-theory`, `recovery-and-durability` and
> `dbms-architecture`. Anti-caching (evicting cold tuples to disk while
> keeping memory as the primary home) inverts the buffer-pool relationship.

---

## 8. Multitenancy, elasticity, SaaS as engine requirements

### Multitenancy models
| Model | Isolation | Consolidation | Per-tenant schema freedom | Engine work |
|---|---|---|---|---|
| Shared hardware (VM per tenant) | Strong (hypervisor caps, live VM migration) | Lowest: duplicated OS/DBMS processes, buffer pools and logs; uncoordinated I/O (each tenant's log flushes compete) | Full | None |
| Shared process, private database/schema | Medium-soft: shared buffer pool, log, CPU scheduler; few DBMSs enforce per-tenant limits | Medium; limited by per-database metadata, connections, files | Full | Resource governance, catalog scaling |
| Shared tables (tenant id column; pivot/universal tables) | Weak at engine level; enforced by an access layer and query rewriting | Highest (thousands–millions of tenants per server) | Via metadata-driven virtual schemas | Heavy: query rewriting, generic storage, custom indexing, statistics per tenant |

**Universal/pivot table design (Salesforce-style):** one large heap table
whose rows carry (tenant id, object/table id, record id, and a few hundred
generic "flex" value columns stored as strings); metadata tables describe
each tenant's virtual tables and columns and their types; separate pivot
tables hold typed copies of indexed values (so a B-tree can sort numbers
correctly) and uniqueness constraints. Every tenant query is rewritten from
the virtual schema onto the physical one. Alternatives studied for SaaS
schemas: sparse columns, chunk tables and *chunk folding* (vertical slices
of tenant tables folded into shared conventional tables), extension tables.

Engine requirements derived from the models:
1. Tenant id is the leading key of every clustered and secondary index, and
   of the partitioning function, so one tenant's data is contiguous and
   prunable.
2. Statistics, plan cache and histograms must be **per tenant** in shared
   tables; a skewed big tenant otherwise poisons every small tenant's plans.
3. Catalog must scale to millions of objects (shared-process model) or be
   virtualized (shared-table model).
4. Resource governance inside the engine: per-tenant reservations or caps on
   CPU, buffer-pool memory, I/O bandwidth (SQLVM-style "virtual machine
   inside the DBMS"), plus metering for billing.
5. Per-tenant backup/restore/point-in-time recovery and data export —
   hard when tenants share pages and log.
6. Row-level security as defense in depth for shared tables (see
   `database-security-internals`).

### Placement and consolidation
Tenant placement is multidimensional bin packing over CPU, memory, I/O and
working-set size, with SLO constraints; it needs models of tenant resource
use and of co-location interference (workload-aware consolidation such as
Kairos/Relational Cloud), robustness to node failure (RTP: place replicas so
that a failure's load spreads without overload), and placement of replicas.
Soft-isolation systems rely on placement plus migration rather than hard
limits.

### Elasticity
Elasticity = scaling out *and in* online, without operator intervention and
without stopping clients. It needs (i) monitoring, (ii) a resource model to
decide when/what to move, and (iii) **live reconfiguration** of
partitioning. Migration techniques:
- Stop-and-copy (simple, long unavailability).
- Iterative copy for shared storage (Albatross-style): copy the cache/state
  in rounds while the source keeps serving, then a short handover.
- Ownership-transfer for shared-nothing (Zephyr-style): a dual mode where
  the destination takes new transactions and pulls pages on demand while
  the source finishes in-flight ones; no transaction aborted by the move.
- Fine-grained hot-tuple placement for skewed OLTP (E-Store): monitor tuple
  heat, move hot tuples individually and cold data in large blocks;
  incremental reconfiguration engines (Squall) execute the plan without
  downtime.

Correctness invariants for migration: exactly one owner may commit writes
for a key at any time; reads served during handover must come from a
committed state no older than what the client has seen (session
monotonicity); in-flight transactions at the source either complete there or
are cleanly aborted — never half-applied on both sides.

### SaaS / cloud framing
SaaS = one application deployment multiplexed over many tenants with
per-tenant customization; PaaS/IaaS supply the substrate (cloud entries
describe IaaS: VMs, persistent volumes and eventually consistent object
stores, networks, identity; PaaS: managed runtimes and services). For the
engine builder the cloud matters through: SLAs/SLOs instead of raw
throughput targets, pay-per-use metering, consolidation for power
efficiency (idle machines can be powered down only if tenants can be
packed and migrated), and the eventual consistency of the object stores
underneath many modern engines.

> **Beyond EDBS:** serverless/elastic relational services (Aurora
> Serverless, Neon, Azure SQL elastic pools) push the shared-storage,
> ownership-migration design to scale-to-zero; their engine requirements
> (fast cold start, cache warm-up, page-server tiers) extend §5's
> ownership/storage decoupling.

---

## Pitfalls checklist
- Treating "eventual" as "soon": no bound unless you engineer one.
- LWW conflict resolution with unsynchronized clocks silently drops writes.
- Hinted handoff without anti-entropy: hints lost on the stand-in's failure
  leave permanent divergence.
- Tombstones GC'd before every replica has seen them → deleted data
  resurrects via repair (the gc-grace problem).
- Vector clocks pruned by size truncate causality → false concurrency
  (siblings) or, worse, false dominance.
- Leases without fencing tokens → two owners after a GC pause.
- Shared-table multitenancy with global statistics → plan regressions for
  small tenants.

Sources: NoSQL Stores (p.2513); Data Management in Data Centers (p.786);
CAP Theorem (p.395); Eventual Consistency (p.1403); Column Stores (p.518);
Main Memory DBMS (p.2164); Multitenancy (p.2440); Elasticity (p.1269);
Cloud Computing (p.475); Software-as-a-Service (SaaS) (p.3544).
