# Multitenancy, cloud data management, and DHT-based peer data management

Where the classical distributed DBMS met the data center: service models and
elasticity, the key-value store design axes, transactional scale-out by
ownership co-location vs distributed transactions, storage/compute
decoupling, multitenancy models and schema-mapping techniques, tenant
placement and isolation, and the peer-to-peer end of the spectrum — DHTs,
P2P query processing, and peer data management systems (PDMS).

---

## 1. Cloud service models and what they demand of a DBMS

- **IaaS**: VMs, persistent volumes, object storage, virtual networks,
  identities via web-service APIs; requests are acknowledged and completed
  asynchronously (clients poll by request id). The control plane itself needs
  a highly available, scalable internal database — if it cannot always
  determine the state of every request and resource unambiguously, a partial
  failure forces the whole cloud to stop.
- **PaaS**: managed runtimes plus shared services (databases, queues, caches,
  authentication) that the platform scales and fails over.
- **SaaS**: one application, many customers sharing back-end instances — the
  origin of high-consolidation multitenancy (Salesforce).
- **Public vs private**: public clouds cap per-user allocation to a tiny
  fraction of capacity (so no tenant can drain the pool, and provisioning
  tracks population growth); private clouds enforce explicit quotas aligned
  with budgets and must run on hardware they did not co-design.
- SLAs define minimum performance/availability; behind them the provider is
  free to **consolidate** (multitenancy, power down idle machines) and
  **migrate** (live VM migration, volume moves). A DBMS designed for the
  cloud must make both cheap: small per-tenant overhead, and online movement
  of a tenant or partition.

Scale-up vs scale-out: scale-up is software-transparent but super-linear in
cost beyond a point; scale-out is near-linear in hardware cost but requires
partitioning, routing, failure handling and (if transactions span
partitions) distributed commit. Commodity economics made scale-out the
default for serving systems.

## 2. Key-value stores: the design axes

Bigtable, Dynamo, PNUTS and descendants traded relational functionality for
scale-out, geo-replication and availability. Their design space is a useful
checklist for any partitioned store:

| Axis | Options | Consequence |
|---|---|---|
| Data model | blob, flat row, column families, documents (JSON/protobuf) | how much the server can index/filter |
| Access granularity | single-key atomicity; best-effort multi-key | no cross-node coordination per request; failure of a node only affects its keys |
| Partitioning | range (tablets of sorted keys) vs hash (key → ring/space) | range: scans and locality, hot-spot risk; hash: balance, no range scans |
| Request routing | centralized metadata (clients cache tablet locations) vs decentralized (consistent hashing / DHT) | metadata service on the critical path vs O(1)/O(log N) hop routing |
| Cluster management | master + leases (master replicated with Paxos) vs gossip membership and failure detection | single authority for reassignment vs no SPOF but weaker agreement |
| Replication | storage-layer (implicit, e.g. a replicated file system) vs explicit by the store; intra- vs inter-data-center | durability/availability vs WAN latency |
| Consistency | strong (1SR/linearizable per key) … causal, session, eventual; often tunable | admissible executions vs latency/availability |

Lease-based ownership is the key correctness device in master-based designs:
a server serves a partition only while it holds an unexpired lease; the
master reassigns only after the lease must have expired. Correctness depends
on bounded clock drift between lease holder and master — budget for it.

## 3. Transactional scale-out: two families

Flexible cross-node transactions limit scalability, so systems either limit
the transaction's scope or pay for distribution.

### 3.1 Limit transactions to one node (ownership co-location)

Co-locate the *ownership* (exclusive read/write authority) of data items that
are accessed together, then run classical single-node concurrency control and
recovery inside the owner.
- **Static granules from schema patterns**: hierarchical/tree schemas where a
  root entity and its descendants form the transactional unit — Megastore
  entity groups, SQL Azure (Cloud SQL Server) table groups, tree-schema
  partitioning. This is derived horizontal fragmentation (owner/member by key
  prefix) used as the transaction boundary.
- **Workload-derived granules**: analyze access patterns and co-locate
  partitions physically (graph partitioning of co-accessed tuples).
- **Dynamic granules**: the application declares a group of keys at run time
  and the system migrates ownership of those keys to one node for the group's
  lifetime (G-Store's key groups; Das's thesis).
- Inside the owner any CC works: 2PL (Cloud SQL Server), OCC (ElasTraS-style),
  OCC + MVCC (Megastore). Failure of one owner affects only its granules.

### 3.2 Storage coupled vs decoupled from ownership

- **Coupled**: owner node also stores the data (classical shared-nothing;
  moving ownership means moving data).
- **Decoupled**: a replicated, fault-tolerant storage layer holds data;
  owners cache the working set and hold transactional authority. Benefits:
  storage handles replication/HA, owners handle transactions; the layers scale
  independently; ownership migration is cheap (move the cache/authority, not
  the bytes), which enables elasticity and load balancing. Fast data-center
  networks make remote storage access for cache misses close to local disk.

### 3.3 Transactions across nodes

When co-location is impossible: MVCC + 2PC, with the commit protocol's
participants or coordinator replicated by Paxos to avoid blocking (Spanner:
TrueTime-bounded timestamps for externally consistent commits and lock-free
snapshot reads). See distributed-transactions for the modern protocols; the
classical pieces are in commit-protocols-and-recovery.md and
distributed-cc-and-deadlock.md.

### 3.4 Replication as an orthogonal axis

Synchronous vs asynchronous; primary-copy vs multi-master; intra- vs inter-
data-center. Each combination fixes a point in consistency / normal-case
latency / availability / durability-under-site-loss. Consistency menu: 1SR
and linearizability down through causal, session guarantees and eventual
consistency (Bernstein & Das SIGMOD 2013). See replication-protocols.

## 4. Multitenancy models

A tenant is an application (or customer) whose data and performance must be
isolated from the others sharing the service. The design tension is
**consolidation** (tenants per server) vs **isolation** (how much a noisy
neighbor can hurt you) vs functionality vs engineering effort.

| Model | Sharing boundary | Consolidation | Isolation | Per-tenant cost | Typical use |
|---|---|---|---|---|---|
| Shared hardware (VM per tenant) | hypervisor | low (duplicate OS + DBMS processes, uncoordinated buffer pools, separate logs and I/O patterns) | strong (hypervisor quotas), easy live migration & HA | full DBMS instance | DBaaS with arbitrary engines |
| Shared process (database/schema per tenant in one instance) | DBMS process | medium–high | soft: shared buffer pool, log, CPU; needs engine-level governance | catalog entries, connections, files | SQL Azure, Relational Cloud |
| Shared table (tenant id column in shared tables) | rows | very high | weakest: isolation and privacy enforced by an access layer; query rewriting required | rows in metadata tables | SaaS platforms with many small tenants |

Consolidation limits in practice: per-tenant catalog/metadata size, dedicated
connections, redundant components, and **uncoordinated resource use** (e.g.
many independent write-ahead logs each doing sequential I/O on the same
device becomes random I/O).

### 4.1 Schema-mapping techniques for shared tables

Aulbach, Grust, Jacobs, Kemper, Rittinger (SIGMOD 2008) catalogued how to map
many tenants' logical schemas (base schema plus per-tenant extensions) onto
one physical schema:

| Technique | Physical layout | Pros | Cons |
|---|---|---|---|
| Private tables | each tenant gets its own tables (renamed) | native performance, native indexes | catalog explosion; buffer pool fragmentation |
| Extension tables | shared base table + shared extension tables per extension, joined on (tenant, row) | shares common columns | reconstruction joins; extension proliferation |
| Universal table | one wide table: tenant, table, col1…colN (generic, usually VARCHAR) | one table for all | many NULLs, type casting, weak indexing |
| Pivot tables | one row per field value: (tenant, table, column, row, value), possibly one pivot table per type | fully flexible schema | n-way self-joins to rebuild a row; per-field overhead |
| Chunk tables | rows split into fixed-width typed chunks: (tenant, table, chunk, row, int1, str1, …) | fewer joins than pivot, typed columns, indexable | still reconstruction joins |
| Chunk folding | frequently used columns in conventional tables, the long tail in chunk tables | best of both for skewed column popularity | needs usage statistics; layout migration |

Related engine features: sparse columns (store only non-NULL values), and
JSON/XML columns as a schemaless extension area. The Force.com design
(Weissman & Bobrowski SIGMOD 2009) stores all tenants' records in a generic
heap with typeless "flex" columns described by metadata tables, and maintains
separate typed pivot tables to support indexing and uniqueness — query
compilation always goes through the metadata layer and injects the tenant
predicate.

Correctness checklist for shared-table designs:
- Tenant predicate injection must be impossible to bypass (rewrite at the
  binder, not in application code); test with adversarial queries (subqueries,
  views, functions, set operations, CTEs) that every base-table access is
  tenant-filtered.
- Statistics are per (tenant, logical table, column), not per physical
  column, or the optimizer mis-plans small tenants with large tenants' stats.
- Uniqueness and referential constraints are per tenant; physical indexes
  must lead with tenant id.
- Per-tenant schema evolution must be metadata-only (no physical ALTER).

### 4.2 Placement, isolation and migration (shared process and VM models)

- **Resource modeling and placement**: profile tenants (CPU, memory working
  set, I/O), predict combined load of co-located tenants, bin-pack under SLOs
  (Curino et al. SIGMOD 2011 for workload-aware consolidation; Relational
  Cloud CIDR 2011; Delphi/Pythia, Elmore et al. SIGMOD 2013, for
  characterizing tenant behavior and crisis mitigation; RTP, Schaffner et al.
  SIGMOD 2013, for placement robust to server failure in in-memory clusters).
- **Engine-level reservations**: SQLVM (Narasayya et al. CIDR 2013) reserves
  CPU, buffer pool memory and I/O per tenant inside one DBMS process and meters
  delivered vs promised resources — virtualization semantics without VMs.
- **VM-level**: allocate VM resources per tenant to hit latency/throughput
  SLOs (Xiong et al. ICDE 2011).
- **Live migration** of a tenant/partition is the elasticity primitive:
  copy a snapshot, ship deltas, then a short handover of ownership. In
  shared-storage designs, migrate the cache and ownership, not the data. Must
  preserve in-flight transactions or abort them predictably; must never allow
  two owners to accept writes for the same tenant at the same time (lease or
  epoch fencing).

## 5. Peer-to-peer data management

### 5.1 Distributed hash tables

A DHT provides put/get over a key space spread across nodes connected by a
**structured overlay**; each node owns the keys "close" to its own identifier
and routes lookups toward the owner.

- **Key space**: typically 160-bit identifiers (SHA-1 output) for both keys
  and nodes.
- **Consistent hashing** (Karger et al. STOC 1997): place node ids and key
  hashes on a ring; a key belongs to its successor node. A join or leave
  moves only O(K/N) keys, from or to the neighbor. Virtual nodes (several
  ring positions per physical node) smooth load and let heterogeneous nodes
  take proportional shares.
- **Chord** (Stoica et al. SIGCOMM 2001): finger table entry i of node n
  points to successor(n + 2^(i−1)); lookups take O(log N) hops with O(log N)
  state; periodic stabilization repairs successor pointers under churn.
- **CAN**: d-dimensional torus, O(d·N^(1/d)) hops with O(d) neighbors.
  **Pastry/Tapestry**: prefix routing, O(log_{2^b} N) hops; **Kademlia**: XOR
  metric.
- **Churn tolerance**: overlay maintenance plus replication of each key to
  the next r nodes in the key space (a joining node fetches the keys it now
  covers from its neighbors; Rhea et al. USENIX 2004 on handling churn).
- DHT routing gives exact-match lookup only. Range queries need
  order-preserving placement (with load balancing against skew) or a
  tree/skip-graph overlay (e.g. BATON, P-Grid); multi-dimensional and spatial
  indexes have been layered on structured overlays (VBI-tree, P2P R-trees).
- **Query processing over a DHT** (PIER, Huebsch et al. VLDB 2003): relations
  are published into DHT namespaces; joins rehash both inputs into a temporary
  namespace on the join key (symmetric hash join in the network), or fetch
  matches by key lookups — the distributed join strategies of the classical
  DDBMS re-expressed over overlay routing.

In data-center stores the same mechanisms serve request routing and
membership (Dynamo: consistent hashing, preference lists of N successors,
gossip membership).

### 5.2 Unstructured P2P search

Queries flood or random-walk through a random overlay with a hop limit (TTL);
answers are best-effort — completeness is traded for autonomy and
scalability, like a search engine. Peer databases (PeerDB, Ng et al. ICDE
2003) combine such propagation with local relational engines.

### 5.3 Peer Data Management Systems

A PDMS is a triple ⟨P, S, M⟩: autonomous peers P, heterogeneous schemas S,
and pairwise schema mappings M that allow query reformulation between two
schemas. There is no mediated global schema; a query posed on one peer's
schema is reformulated along mapping paths, transitively, to reach data
anywhere in the network.
- Mapping languages derive from GLAV (global-and-local-as-view) formulas,
  with inclusion and equality mappings; query answering targets **certain
  answers** (Piazza, Halevy et al. TKDE 2004).
- Instance-level mappings: mapping tables relating values across peers
  (Hyperion, Arenas et al. SIGMOD Record 2003).
- Mapping quality: composing mappings along cycles exposes inconsistencies;
  GridVine detects them probabilistically on a structured overlay
  (Cudré-Mauroux).
- Overlays: unstructured (flooding/random walks) or structured (DHT index over
  schema and mapping metadata).
- Engineering concerns: reformulation blow-up along long mapping paths
  (prune by mapping quality and hop count), termination on mapping cycles
  (track visited peer/schema pairs), and the absence of any global
  transaction manager — updates and consistency are local or eventual.

## 6. Distributed recovery and transactions in P2P/cloud settings

Open issues the entries flag: in P2P networks the participants of a
transaction may have left when a failed peer recovers, so commit-protocol
recovery that assumes eventual reconnection fails; relaxed serializability
and multiversioning are more practical. In clouds, storage services look like
a huge shared disk with best-effort consistency, so concurrency control is
chosen per application ("à la carte").

> **Beyond EDBS:** The decoupled-storage pattern became the dominant cloud
> OLTP architecture: Amazon Aurora ships redo log records to a replicated
> storage tier that materializes pages ("the log is the database"), and
> Microsoft Socrates separates compute, log service and page servers; both
> make compute nodes nearly stateless, so failover and scaling are ownership
> moves. Multitenant serverless databases add per-tenant scale-to-zero on top
> of the shared-process or shared-storage models. Region-aware SQL systems
> (Spanner placement policies, CockroachDB multi-region tables) turn the
> classical allocation problem plus data-residency constraints into
> declarative table-level options; the cost model of
> fragmentation-and-allocation.md still explains their latency behavior.

Sources: Cloud Computing (p.475); Data Management in Data Centers (p.786);
Multitenancy (p.2440); Distributed Hash Table (p.1190); Peer Data Management
System (p.2696); Distributed Architecture (p.1152); Distributed Transaction
Management (p.1222); Distributed Recovery (p.1212); Distributed Spatial
Databases (p.1215) for P2P spatial indexes.
