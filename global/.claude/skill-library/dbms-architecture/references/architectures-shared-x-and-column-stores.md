# Shared-memory, shared-disk, shared-nothing; database machines; column stores

System-level structural choices: what hardware resources the engine
instances share, what history taught about special-purpose database hardware,
how distribution transparency is graded, and when storage should be organized
by column instead of by row. Read when choosing or reviewing a scale-out
architecture, an offload/accelerator idea, or the row/column organization of
a storage engine. Parallel operator design and data placement detail belong to
`parallel-database-systems` and `parallel-distributed-execution`.

## 1. Where the network cuts the stack

Using Helland's layering (EDBS *Process Structure of a DBMS*):

```
                     shared-everything     shared-disk            shared-nothing
query front-end      ┐                     ┐ per node             ┐ any node (coordinator)
                     │ one memory          │                      ╞═ network: plan fragments ⇄ row sets
query back-end       │                     │                      │ per node, owns its partition
access methods       │                     │                      │
block/page manager   │                     ╞═ network/SAN: blocks │
disks                ┘                     ┘ shared pool          ┘ local disks
```
Only systems that present **one database** — one collection of records over
which relational operations and transactions span — are DBMS architectures in
this sense. Several databases joined by 2PC, or services each with a private
database (SOA), are application architectures; 2PC across them does not make
them one database.

## 2. The three classic architectures

Definitions (EDBS, Valduriez):
- **Shared-memory (shared-everything, SMP):** all processors share main memory
  and disks over a fast interconnect (bus, crossbar) under one OS.
- **Shared-disk:** each node has private memory and its own OS; all disks are
  reachable from all nodes over the interconnect; any node may cache any page,
  so cache coherence is required.
- **Shared-nothing (MPP):** each node owns processor, memory and disks under
  its own OS; nodes communicate only by messages; essentially a distributed
  database on a fast network, reusing partitioning, distributed query
  processing and distributed transaction techniques.

| | Shared-memory | Shared-disk | Shared-nothing |
|---|---|---|---|
| Programming model | like a uniprocessor; shared lock table and directories | DBMS instance per node + global lock/coherence protocol | partitioned DBMS + distributed query/txn processing |
| Load balancing | trivial: next task to least-busy CPU | easy: any node can run any query on any data | hard: decided by **data location**, not current load |
| Scale (EDBS era figures) | a few tens of CPUs, best cost/performance ~16 | up to ~100 nodes | thousands of nodes (Teradata ~1000 processors in the 1980s) |
| Availability | a memory fault can take all CPUs (needs duplexed memory) | node faults isolated; disks shared | node faults isolated; replication needed for data availability |
| Migration from centralized | none needed | easy: data on disk need not be reorganized | requires repartitioning |
| Main costs/risks | complex interconnect; memory contention grows with CPU speed | distributed locking + 2PC, coherence messages, shared disk/SAN bandwidth | complexity of data placement, skew, reorganization when adding nodes |
| Hot spot behaviour | fine within the box | hot page ping-pongs between nodes ("data moves to the operation") | hot row stays on its node; more updates/s per item possible ("operation moves to the data") |
| Lock granularity pitfalls | — | block/page-mode locking causes false conflicts between rows on one page | typically record locking |

Helland's summary: shared-everything gives the highest throughput **per
machine** (no messaging at all) — until the database outgrows the machine.
Shared-disk excels when update conflicts on shared pages are rare (low update
rate, partitionable block sets). Shared-nothing pays more to set up a complex
transaction but can deliver more throughput over a given amount of data,
especially for hot items.

### Component consequences

| Component | Shared-disk | Shared-nothing |
|---|---|---|
| Buffer manager | peer pools; page ownership/coherence protocol (invalidate or ship) | private pool per node |
| Lock manager | global (distributed lock manager) for pages/rows | local per partition; global deadlock detection only for multi-partition txns |
| Log | one log per node; media/crash recovery must merge logs in a global order (e.g. global sequence numbers) | one log per node; multi-node commits need 2PC (or deterministic ordering) |
| Catalog | shared on disk, cached per node with invalidation | replicated to coordinators |
| Optimizer | location-agnostic; can route by affinity to reduce ping-pong | must know partitioning; co-located joins vs repartition/broadcast |

> **Beyond EDBS:**
> - Oracle RAC's **Cache Fusion** transfers current block images between
>   instances over the interconnect, coordinated by a global cache service,
>   instead of forcing a write to shared disk; IBM DB2 data sharing (z/OS
>   Parallel Sysplex, later pureScale) centralizes global locks and group
>   buffer pools in a coupling facility.
> - Teradata (shared-nothing since the DBC/1012, 1984): rows hash-distributed
>   by the primary index to AMPs (access module processors) that own their
>   disks; interface processors (later parsing engines) plan and dispatch steps
>   over the interconnect (Ynet, later BYNET).
> - Cloud **disaggregation** revives shared-disk at a new layer: Snowflake
>   (Dageville et al., SIGMOD 2016) separates object storage from elastic
>   compute clusters with local caches; Aurora (Verbitski et al., SIGMOD 2017)
>   ships only redo to a quorum-replicated storage service that materializes
>   pages ("the log is the database"); Socrates (Antonopoulos et al., SIGMOD
>   2019) further separates log, page servers and compute. The old shared-disk
>   costs reappear as cache coherence across compute nodes and as storage
>   network bandwidth; the old shared-nothing costs reappear as data movement
>   for joins.

### Speedup, scaleup and their enemies
(DeWitt & Gray, CACM 1992, cited in EDBS *Database Machine*.)
- **Speedup** = time(small system) / time(big system) on the same problem;
  linear if N× hardware gives N× speed.
- **Scaleup** = time(1, problem P) / time(N, problem N·P); linear if 1.0.
- Barriers: **startup** cost of launching work on many nodes, **interference**
  on shared resources (memory bus, shared disk, locks, coherence), and
  **skew** (the slowest partition decides). Shared-nothing minimizes
  interference at the price of exposing skew; shared-memory/disk hide skew via
  dynamic load balancing but suffer interference.

## 3. Database machines: history and lessons

**Definition** (EDBS, Goda): a computer with hardware designed or tuned for
database access, often a **backend** attached to a frontend host. The idea of
offloading database work to a dedicated "backend computer" dates to the early
1970s (Canaday et al., CACM 1974) and is the ancestor of the client-server
database server.

Filter-processor designs (DeWitt & Hawthorn, VLDB 1981):

| Class | Idea | Cost |
|---|---|---|
| Processor-per-track (PPT) | a cell processor per track filters data on the fly as the track rotates | needs special disks (fixed-head) |
| Processor-per-head (PPH) | a processor per read head; a whole cylinder searched per rotation | special disks with parallel heads |
| Processor-per-disk (PPD) | one processor per commodity disk | cheaper, smaller gain |
| Multi-processor cache (MPC) | several processors and disk-cache modules per drive, exchanging work through the cache | complex |

In the 1980s research shifted to **massively parallel machines built from
general-purpose processors and disks** coupled into nodes and joined by a fast
interconnect — the shared-nothing parallel DBMS (Teradata, Gamma, Tandem
NonStop SQL), which succeeded commercially.

Lessons an engine architect should carry:
1. **Special hardware loses the race to commodity hardware** unless its
   advantage is structural. Boral & DeWitt (1983, "Database Machines: An Idea
   Whose Time Has Passed?") argued that associative/filter hardware was
   bottlenecked by disk I/O bandwidth, not by processing.
2. **The durable contribution was software**: partitioned dataflow,
   parallel operators, hash partitioning — which run on commodity clusters.
3. **Offload is worth it when it cuts data movement** across the narrowest
   link. That is why the idea keeps returning: smart-scan predicate and
   projection offload in storage cells (Oracle Exadata), FPGA filtering near
   disk (Netezza), computational storage and SmartNICs, GPUs/FPGAs as
   co-processors.
4. **Accelerators need batch-sized work to amortize transfer.** EDBS *Stream
   Processing on Modern Hardware*: GPU kernels require copying data over PCIe,
   so streams must be mini-batched, and warps executing in lockstep make
   data-dependent branching expensive; FPGAs can host compiled
   select-project(-join) windowed queries and consume directly from the NIC.
   Synchronous-dataflow programs (static selectivities, static schedules) map
   to such hardware far more easily than data-dependent asynchronous streams.
   On multicore CPUs the mapping tools are **fusion** (run a subgraph of
   operators in one thread to remove queues/scheduling) and **fission**
   (replicate stateless or partitioned-stateful operators; hash the partition
   key; re-merge for order if required). See `stream-processing-engines`.

## 4. Distribution architectures and transparency

EDBS *Distributed Architecture* (Risch) grades multi-node systems by who
places the data and what is hidden from whom.

| Architecture | Nodes autonomous? | Who decides data placement | Users see one database? | Updates transparent? | Single global schema? |
|---|---|---|---|---|---|
| Parallel DBMS | no | the system (schema transparency even for the DBA) | yes | yes | yes |
| Regular distributed DBMS | no | DBA (fragmentation + replication rules) | yes | yes | yes |
| Federated | yes | pre-existing component DBs | yes, via the integration schema | limited | yes (integration schema) |
| Mediators | yes | sources | via user-defined views | limited (updatable views) | no — many views |
| Multi-database | yes | sources | no — queries name individual databases | no | no |
| Peer-to-peer | yes (independently managed) | peers | yes, with relaxed answer correctness | yes (relaxed) | no |

- **Homogeneous** (one distributed DBMS manages everything) systems are
  designed top-down; **heterogeneous** ones bottom-up, integrating existing
  schemas.
- Transparency kinds: *schema* (system places data), *query* (distribution
  invisible in queries; optimizer prunes to affected nodes), *update*
  (distributed transaction manager propagates writes), *naming* (one name for
  a fragmented/replicated relation).
- Manual distribution tools: **fragmentation** (disjoint pieces on different
  nodes — parallel access and node pruning) and **replication** (faster reads,
  costlier writes unless consistency is relaxed via lazy propagation).
- Strong update transparency needs 2PC/3PC, expensive with many nodes or wide
  areas (speed of light); many systems offer lazy propagation as an option.
- In a parallel DBMS the cluster nodes run kernel code fully controlled by the
  one system; nodes may specialize (query processing, locking, recovery) —
  the system is monolithic though physically distributed.
- **Catalog**: read-intensive and slowly changing in homogeneous systems →
  replicate (enables precompiled distributed plans); with autonomous sources
  → cache with validation, or risk failed queries and wrong answers.

Details: `distributed-dbms-design`, `replication-protocols`.

## 5. Row stores vs column stores

### 5.1 Models
- **NSM (n-ary storage model):** store each record's attributes contiguously,
  records one after another — the conceptual row as the storage unit.
- **DSM (decomposition storage model, Copeland & Khoshafian, SIGMOD 1985):**
  decompose a relation into binary relations *(surrogate, attribute value)*,
  one per attribute. Any number of attributes is handled uniformly and changing
  an attribute does not change the storage structure. Physical column stores
  store each attribute's values contiguously and usually make the surrogate
  implicit (position).
- **PAX:** NSM pages internally organized by attribute (see
  `cache-conscious-and-main-memory.md`).
- **Column families** (Bigtable, HBase, Cassandra, Hypertable) are a different
  thing: groups of related columns stored together per key, sparse wide rows —
  hybrid row/column storage, not a relational column store.

### 5.2 Lineage
Transposed files (1970s) → DSM (1985) → K/kdb (1990s, finance) and Sybase IQ
(mid-1990s) → MonetDB, MonetDB/X100 (vectorized execution), C-Store (2005,
read-optimized) → commercial spin-offs Vectorwise (from X100) and Vertica
(from C-Store) → SAP HANA (in-memory columnar, integrated with business
applications) → columnar options in legacy engines (InfiniDB for MySQL;
Greenplum's hybrid row/column tables on PostgreSQL).

### 5.3 When each wins
| Workload | Better | Why |
|---|---|---|
| Aggregates over few columns of many rows (OLAP, read-mostly) | column | read only needed columns; sequential; compresses well |
| Fetch/update most columns of one row (OLTP) | row | one I/O / few lines per row; columnar needs one access per column |
| Wide tables with sparse access | column | proportional I/O |
| Insert-heavy, row-at-a-time | row (or column with write-optimized delta) | columnar inserts touch every column file |

Comparisons are workload-specific (Halverson et al., UW–Madison tech report
2006; Harizopoulos et al., VLDB 2006). Abadi,
Madden & Hachem (SIGMOD 2008, "Column-stores vs. row-stores: how different are
they really?") showed that vertically partitioning or fully indexing a row store
does not recover column-store performance: the gains come from column-aware
execution — compression operated on directly, late materialization, block
iteration, and the invisible join.

### 5.4 What a column engine needs beyond layout
- **A column-aware optimizer and executor**; bolting columns under a
  row-at-a-time executor wastes most of the benefit.
- **Compression** exploiting value similarity: run-length (incrementally
  maintainable — Mohapatra & Genesereth 2012), dictionary, bit-packing, delta.
- **Tuple reconstruction** strategy: early vs **late materialization** (carry
  position lists, stitch columns only when needed); self-organizing
  reconstruction with **sideways cracking** (Idreos, Kersten & Manegold,
  SIGMOD 2009).
- **Indexes** on block addresses, keys and values (zone maps / min-max per
  block) to skip column blocks.
- **Parallel, sequential execution**: columns partition naturally across
  cores; sequential memory access suits in-memory engines.
- Applications cited: data warehouses; RDF via vertical partitioning into one
  two-column (subject, object) table per property (Abadi et al., VLDB 2007),
  with scalability caveats when property tables vary greatly in size
  (Sidirourgos et al., VLDB 2008); convergence with search engines (X100 as a
  search backend).

> **Beyond EDBS:**
> - Open file formats Parquet and ORC are PAX-like at file scale: row groups
>   (stripes) containing per-column chunks with min/max statistics.
> - HTAP designs pair a write-optimized store with a read-optimized columnar
>   one: SAP HANA's delta store merged into the main store; SQL Server
>   columnstore indexes with delta rowgroups; Oracle Database In-Memory's dual
>   format (row on disk, columnar in memory).
> - See `olap-and-warehouse-engines` for compression, vectorized operators and
>   late materialization in depth, `columnar-arrow-layout` for the in-memory
>   Arrow format.

## 6. Review questions

- Will the database outgrow one box within the design horizon? If not,
  shared-everything is the highest-throughput and simplest answer.
- Where are the hot items, and does the architecture move data to them or
  operations to them?
- What is the lock granularity under shared-disk coherence, and does it
  create false conflicts?
- How is a partition added, and how much data moves? How is skew detected?
- Which layer would an accelerator offload, and does it cut bytes on the
  narrowest link after accounting for transfer batching?
- For a column store: is the executor column-aware end to end, and how are
  single-row inserts and updates absorbed?

Sources: EDBS *Shared-Memory Architecture* (p.3485), *Shared-Disk
Architecture* (p.3484), *Shared-Nothing Architecture* (p.3486), *Process
Structure of a DBMS* (p.2867), *Database Machine* (p.956), *Client-Server
Architecture* (p.439), *Distributed Architecture* (p.1152), *Stream
Processing on Modern Hardware* (p.3772), *Column Stores* (p.518),
*Cache-Conscious Query Processing* (p.389), *Memory Locality* (p.2229).
