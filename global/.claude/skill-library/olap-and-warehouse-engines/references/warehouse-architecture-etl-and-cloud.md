# Warehouse architecture, ETL, real-time loading, physical design, MPP and cloud

The system around the query engine: how data arrives (ETL/ELT, CDC, trickle
feeds), how the warehouse is laid out across nodes and storage tiers, how
physical design is chosen and tuned, and how cloud warehouses changed the
storage/compute contract.

## 1. Warehouse properties and their engine implications

Inmon's four properties, read as engine requirements:

| Property | Requirement on the engine |
|---|---|
| Subject-oriented | schemas organised around business entities (star schemas, conformed dimensions) → star-aware optimizer |
| Integrated | heavy transformation before data is queryable → ETL/ELT throughput, staging, bulk load paths |
| Time-variant | years of history; time is always a dimension → time partitioning, rolling windows, historical dimension versions |
| Non-volatile | changes recorded as new rows, not overwrites → append-optimized storage, immutable segments, snapshot reads |

Workload contrast with OLTP that drives design: few concurrent but heavy
queries touching millions of rows; ad hoc, unpredictable predicates;
read/append mostly; loads controlled by a scheduler; response times of
seconds to minutes; data retention of 3–10+ years. HTAP engines (HANA, HyPer,
SQL Server in-memory, MemSQL/SingleStore, VoltDB in EDBS's list) serve both by
running analytics on a consistent snapshot while transactions update the
latest version.

## 2. Architectures

| Architecture | Shape | Engine-relevant consequence |
|---|---|---|
| Independent data marts | separate marts, no conformed dimensions | no drill-across; inconsistent totals; duplicated ETL |
| Data mart bus (Kimball) | marts linked by conformed dimensions/measures; the "EDW" is their union | drill-across joins on conformed levels; incremental delivery |
| Centralized EDW | one warehouse, no dependent marts | one engine must serve all workloads → workload management critical |
| Hub-and-spoke / Corporate Information Factory (Inmon) | normalized atomic EDW feeding dimensional marts | ELT inside the warehouse; marts as materialized derivations |
| Distributed DW | autonomous local warehouses + global warehouse | global queries need distributed joins; partition by geography/division |
| Federated DW | a logical global warehouse over heterogeneous local ones (often after acquisitions) | query federation, pushdown, cross-vendor cost estimation |
| Virtual data mart | dimensional model defined in a virtualization layer, data pulled on demand | no physical aggregates; latency from sources; schema agility |
| Data vault | hubs (business keys), links (relationships), satellites (attributes over time) | insert-only, highly join-heavy; dimensional marts derived on top |

Delivery order matters for the bus architecture: build first the mart that
owns the most widely shared (conformed) dimensions, so later marts plug into
that backbone; the most technically central mart is often not the one users
value most, a trade-off EDBS's life-cycle discussion makes explicit.

Non-conventional sources (documents, web/social data, XML/RDF) clash with
summarizability, which presumes closed, complete, well-structured data. Two
integration styles: (1) keep them in native stores linked to facts (via IR,
information extraction, opinion mining or ontology annotation) and reach them
by drill-through, optionally reflecting derived measures (document counts,
polarity) into cubes; (2) extract structured dimensions/measures from them
and load ordinary cubes.

Five functional layers: sources → ETL/staging (data staging area) → EDW
storage + metadata repository → marts and OLAP engines (ROLAP/MOLAP/HOLAP) →
front-end tools. Metadata comes in three kinds — business (meaning), technical
(tables, partitions, mappings, schedules), process (load events, query
statistics) — and the process metadata is what self-tuning consumes.

## 3. ETL internals

An ETL process is a DAG whose nodes are activities and record sets; edges are
data flow. It must finish inside a window, survive failures, and refresh not
only fact/dimension tables but every derived structure (materialized views,
aggregates, marts, extracts).

### 3.1 Extraction / change data capture

| Method | Mechanism | Source impact | Captures deletes? |
|---|---|---|---|
| Full extract | reload everything | high | implicitly |
| Snapshot differential | compare current snapshot with previous (sort-merge or hash/window algorithms, Labio & Garcia-Molina, VLDB 1996) | moderate (read) | yes |
| Timestamp/sequence columns | extract rows changed since last high-water mark | low | no (unless soft deletes) |
| Triggers | source triggers write change tables | intrusive, runtime overhead | yes |
| Log sniffing (log-based CDC) | parse committed changes from the source's transaction log and replay | minimal | yes, with commit order |

Constraints from the source side: minimal overhead during extraction and
minimal configuration changes on the source. Encrypt and compress data in
transit.

> **Beyond EDBS:** log-based CDC is now the default (e.g. Debezium on database
> logs feeding a message bus); the warehouse applies ordered change batches
> with MERGE, which makes idempotent, ordered apply (by source LSN/SCN) an
> engine requirement.

### 3.2 Transformation problem classes

| Level | Problems | Typical operators |
|---|---|---|
| Schema | homonyms/synonyms, structural conflicts, type conversion | mapping, pivot/unpivot, casts |
| Record | duplicates, contradictions, differing granularity or timeliness across sources | dedup/entity resolution, aggregation to common grain, time alignment |
| Value | format masks ('M'/'Male'/'1'), date formats, surrogate key assignment, defaults, NULL rules | lookups, CASE, string functions |

The **surrogate key pipeline** is the hot path: for each incoming fact, look
up each dimension's natural key → surrogate (current version, or version valid
at event time for SCD type 2); unseen natural keys either get an "inferred
member" row inserted (late-arriving dimension) or route to an error flow.
Implement as hash lookups against in-memory dimension key maps, refreshed per
batch.

### 3.3 Loading

- Bulk-load utilities beat row-at-a-time INSERT by large factors: no SQL
  parsing per row, minimal logging, no per-row rollback segments, direct
  segment/page construction. "Open-loop fetch" (insert one row per round
  trip) is the classic anti-pattern.
- Upsert: MERGE (insert new, update existing) — or partition exchange:
  build a new partition offline and swap it in (metadata-only).
- Indexes and MVs: either maintain incrementally during load, or disable and
  rebuild per partition after load — a cost decision based on the fraction of
  the table loaded.
- Restartability: stage intermediate results to disk so a failed workflow
  resumes from the last staged point; Labio et al. (SIGMOD 2000) resume
  interrupted loads by exploiting properties of the transforms (e.g. order
  preservation) to skip already-loaded input.

### 3.4 Optimizing ETL workflows

ETL flows are not big queries: black-box operators (UDFs, external calls),
staging forced by recoverability, multiple engines and time windows. Hence
"ETL as a complex transaction" rather than as a query. Research approaches:

- Logical state-space optimization (Simitsis, Vassiliadis, Sellis, ICDE 2005;
  TKDE 2005): transitions such as swapping adjacent activities (push
  selective filters earlier), factorizing/distributing activities across
  branches of unions, merging activities; requires knowing which attributes
  each black box reads and writes.
- Cost-based optimization needs statistics on intermediate results; which
  statistics are essential is itself a problem (Halasipuram et al., EDBT 2014).
- Multi-objective (QoX: freshness, recoverability, cost) and multi-engine
  flow placement (Simitsis et al., SIGMOD 2012).
- ELT: load raw data into the (powerful) target and transform there with SQL;
  transformations then compete with queries, turning ETL into a workload
  management problem. Variants ETLT, ELTL; on-demand ETL triggered by queries
  (pull rather than push).
- Parallel ETL on clusters/MapReduce (ETLMR, CloudETL — dimension lookups and
  SCD handling on Hadoop/Hive).

> **Beyond EDBS:** TPC-DI (2014) is the dedicated data-integration
> benchmark; TPC-DS includes a data maintenance phase. EDBS notes the lack
> of principled ETL benchmarking at its time.

## 4. Active, real-time and right-time warehousing

Definitions:

- **Active DW**: captures transactions as they change and integrates them,
  alongside scheduled batch refresh, and can push decisions back into OLTP
  systems automatically (Teradata's "active data warehousing", Brobst).
- **Real-time DW**: query results reflect the current state of sources —
  low-latency loading (seconds to minutes after source commit).
- **Right-time DW**: freshness chosen per need while keeping bulk-load insert
  speed (RiTE: Thomsen, Pedersen, Lehner, ICDE 2008 — a main-memory "catalyst"
  holds new rows in memory tables queryable on demand and materializes them
  into the physical warehouse according to a policy).
- **Intellective DW**: adds ML/IR to automate ingestion, metadata,
  explanation — aspirational in EDBS.

### 4.1 Analysis rules (Thalhammer, Schrefl, Mohania 2001)

An active DW automates routine decisions with ECA-style analysis rules:

| Component | Meaning |
|---|---|
| Event | calendar event, relative temporal event ("20 days after launch"), derived from OLTP method events loaded via ETL (rules cannot fire directly on OLTP events because those arrive with load latency) |
| Primary dimension level + primary condition | which objects (e.g. products) are candidates |
| Analysis graph | the cubes examined, coarse to fine |
| Decision steps | per cube: condition to decide now, and condition to drill into finer cubes |
| Action | an OLTP method to invoke (reduce price, withdraw product) |
| Conflict resolution | conflict table ⟨m1, m2, m_resolve⟩ for contradictory decisions in one cycle; unresolved conflicts go to analysts |

See `sql-semantics-and-active-rules` for trigger/rule execution semantics.

### 4.2 Real-time loading options

| Option | Mechanism | Trade-off |
|---|---|---|
| Near-real-time ETL | run batches more often | simplest; freshness bounded by batch period |
| Direct trickle feed | continuously insert into fact tables | freshest; contends with queries, index/MV maintenance per row |
| Trickle and flip | trickle into a staging copy with the same format; periodically swap it with the fact (partition exchange) | freshness = flip period; queries unaffected between flips |
| External real-time cache | recent data in a separate (in-memory) store; queries touching recent data are routed or federated there | warehouse untouched; query federation complexity |
| Log shipping | ship source logs, replay near the warehouse | efficient change detection; replay must be ordered |
| Data streams / CEP | treat changes as event streams, analyse continuously | moves analysis out of the warehouse |
| Integrated OLTP/OLAP (HTAP) | one engine; analytics on snapshots (HyPer: fork-based virtual-memory snapshots; HANA) | no ETL latency; contention managed inside the engine |

Engine features that make real-time feasible: partition exchange as a
metadata swap; snapshot isolation so loads never block readers; delta stores
in column engines; incremental MV maintenance; workload management that
throttles loads or queries.

## 5. Physical design and tuning

### 5.1 Problem statement

Inputs: the warehouse schema, a workload W = {(q_i, f_i)} (or none: dynamic
design), the optimization technique classes the DBMS supports, resource
constraints per class (space, maintenance time), non-functional requirements
(response time, maintenance cost, energy, cloud price). Output: a
configuration of techniques satisfying the constraints. Every instance is
NP-hard; algorithms are greedy, randomized, evolutionary or hybrid.

| Class | Techniques | Redundant (extra storage + maintenance)? |
|---|---|---|
| Materialized views | aggregates, pre-joins; query rewriting by the optimizer | yes |
| Indexes | bitmap, bitmap join, join, projection, B-tree | yes |
| Vertical partitioning | column groups (extreme: column store) | slightly (keys duplicated) |
| Denormalization | pre-joined dimension attributes in facts or flattened dims | yes |
| Horizontal partitioning | range/list/hash/composite, derived (reference), virtual-column | no |
| Parallel processing | fragment allocation, replication, load balancing | no (unless replicated) |

Sizes of the search spaces explain the heuristics: vertical partitioning of m
non-key attributes has B(m) (Bell number) candidate fragmentations —
B(10) = 115,975; derived horizontal partitioning yields Π m_i fact fragments;
view selection is exponential in the lattice size.

Views and indexes compete for the same space and maintenance budget — select
them jointly (Gupta 1997; Agrawal, Narasayya, Yang, SIGMOD 2004 integrate
vertical and horizontal partitioning into automated design). Bitmap join index
selection has been approached with data mining over the workload (frequent
predicate attribute sets).

Commercial advisors (as listed in EDBS): SQL Server Database Tuning Advisor
(partitioning, MVs, indexes), Oracle SQL Access Advisor (same), DB2 design
advisor (adds MDC clustering).

### 5.2 Tuning (keeping the design right)

Static designs decay as data and workload change. Two self-tuning styles:

- **Threshold-triggered**: estimate benefit of a new configuration versus the
  current one; recommend or apply when the gain exceeds a threshold within
  constraints.
- **Observe–predict–react** loop: observe workload and structure usage
  statistics; predict near-future performance of current vs alternative
  configurations; react by creating/dropping structures at good moments.
  Unused indexes/views are dropped; cracking-style adaptive indexing builds
  structures as a side effect of queries.

Open issues EDBS flags: cost models for non-traditional objectives (energy,
cloud cost) calibrated with ML; extending cracking to views and partitions;
in-memory DWs changing which structures pay off; exploiting multi-query
optimization (shared subexpressions across canned reports) in design.

### 5.3 Partition management in practice

Two-level partitioning is the norm: primary by time (month/day), sub-partition
by another dimension (region, product group, or hash for parallelism). New
data is loaded into a staging table, transformed, converted into a partition
and attached atomically; expired partitions are detached and archived. The
optimizer prunes partitions statically (literals) and dynamically (values
known only at run time, e.g. from a dimension filter).

## 6. Parallel and distributed warehouses

Design tuple ⟨Arch, DP, DA, DR, LB⟩: architecture, data partitioning, data
allocation, data replication, load balancing — each NP-hard on its own.

- **Architecture**: shared-memory, shared-disk, shared-nothing (plus hybrids).
  Shared-nothing commodity clusters won on cost/scalability (Gamma, DeWitt &
  Gray 1992); turnkey MPP appliances (Teradata, Netezza, Exadata, Greenplum,
  SQL Server PDW) vs clusters of commodity DBMS instances glued by a
  partition-aware layer.
- **Partitioning**: fact table partitioned (horizontally; derived from
  dimension fragments), small dimensions replicated to every node; each node
  runs the query on ≈1/P of the fact; results are small and merged.
- **Physical vs virtual partitioning**: physical fragments suffer from data
  skew fixed at design time; virtual partitioning (Akal, Böhm, Schek 2002)
  replicates the fact on all nodes and assigns key-range sub-queries
  dynamically (load balancing at the cost of P copies and possible full
  scans); adaptive virtual partitioning (Furtado, Lima, Pacitti, Valduriez,
  Mattoso 2005) layers small dynamically sized virtual ranges over physical
  partitions, probing the DBMS to find the largest sub-query size that still
  uses indexes.
- **Allocation and replication**: place fragments for locality, replicate for
  availability and to enable load balancing (replica placement is NP-hard);
  iterative design (partition, then allocate, then replicate, each with its
  own cost model) ignores their interdependence; conjoint designs fuse
  phases. EDBS reports a conjoint partition+allocation design performing 38%
  better than an iterative one on SSB in Teradata.
- **Skew**: data skew (non-uniform partitioning attribute) and processing skew
  (work concentrates on few nodes); mitigated by better partitioning keys,
  replication and dynamic reassignment, at a communication cost.

Teradata as described in EDBS: the AMP (access module processor) is the unit
of parallelism owning a data portion, locks and buffers; nodes host several
AMPs; BYNET interconnects AMPs within and across nodes.

> **Beyond EDBS (Teradata specifics):** rows are distributed by hashing the
> primary index value to a hash bucket, mapped to an AMP through the hash
> map; the primary index therefore fixes both distribution and join
> co-location. Join planning chooses among AMP-local joins (co-located on
> the same PI), redistributing one or both inputs by the join column, or
> duplicating a small (often dimension) spool to all AMPs. Partitioned primary
> indexes (PPI, multilevel PPI) add row partitioning within each AMP for
> partition elimination (static and dynamic); USIs are global (hash-
> distributed by the index value), NUSIs are AMP-local. Skewed PI choice is
> the dominant tuning failure.

> **Beyond EDBS (other MPP/cloud):** Redshift distribution styles (KEY, ALL,
> EVEN, AUTO) and sort keys map onto the same decisions: co-locate the fact
> with its largest dimension on the join key, replicate small dimensions,
> sort by time for zone-map pruning.

## 7. Cloud warehouses

### 7.1 Systems covered by EDBS

| System | Engine | Key ideas |
|---|---|---|
| Hive (Facebook) | MapReduce | HiveQL compiled to MR jobs; metastore (catalog); external tables over files; pluggable formats (RCFile); 5–10 s latency even for trivial queries |
| HadoopDB (Abouzeid et al. 2009) | Hadoop + PostgreSQL per node | push as much of the plan as possible into the per-node DBMS; MR fault tolerance with near-parallel-DBMS speed |
| Shark (Xin et al. 2013) | Spark | in-memory RDDs with lineage-based recovery; in-memory columnar storage + compression; "map pruning" via load-time statistics; partial DAG execution re-optimizes using runtime statistics; ms task launch → many reducers, skew resistance |
| Spark SQL (Armbrust et al. 2015) | Spark | DataFrames with schemas, lazy evaluation, extensible optimizer with code generation; mixes relational and procedural code |
| BlinkDB (Agarwal et al. 2013) | Hive/Spark | uniform + stratified samples (rare groups over-represented); user bounds error or time; reports error at a confidence level |
| Presto (Facebook) | own engine | pipelined stages, no intermediate disk writes, connectors to many sources; reading/decoding HDFS data dominated time → native format work |
| Amazon Redshift (Gupta et al. 2015) | ParAccel-derived MPP | leader node plans, compute nodes store and execute; columnar, compressed, co-located joins; data replicated within the cluster and backed up to S3; minimal tuning knobs |

The MapReduce-versus-parallel-DBMS debate (Pavlo et al., SIGMOD 2009;
Stonebraker et al. and Dean & Ghemawat, CACM 2010): parallel DBMSs were much
faster on analytical tasks; MapReduce offered fault tolerance at scale,
heterogeneous hardware tolerance and schema-less flexibility. The systems
above progressively re-imported DBMS techniques (columnar storage, statistics,
cost-based and adaptive optimization, pipelining) into the cluster stack.

### 7.2 Storage/compute separation

> **Beyond EDBS:** Snowflake (Dageville et al., SIGMOD 2016) splits the
> warehouse into (1) storage — tables as immutable, columnar,
> compressed micro-partitions in cloud object storage, (2) compute — elastic,
> isolated "virtual warehouses" (clusters) that cache object-store files on
> local SSD, files assigned to workers by consistent hashing so caches survive
> resizing, and (3) a cloud services layer holding metadata, optimizer,
> transactions and security. Per-micro-partition min/max metadata drives
> pruning (no indexes); immutability gives snapshot isolation, time travel
> and zero-copy cloning. Redshift RA3 (managed storage) and BigQuery (Dremel:
> columnar storage on a distributed file system, compute slots, a separate
> in-memory shuffle tier) follow the same separation.

Engine implications of separation:

- The unit of storage, pruning and caching is the immutable file/segment;
  updates are copy-on-write (rewrite affected files) or merge-on-read
  (delete files/bitmaps applied at scan time).
- Metadata becomes the bottleneck at scale: pruning must start from compact
  per-file statistics without listing object stores.
- Remote reads are high-latency, high-throughput: large sequential reads,
  aggressive prefetch, and caching on local NVMe matter more than seek
  avoidance.
- Elasticity changes physical design economics: scanning more with more
  compute can replace some precomputed aggregates; concurrency scales by
  adding clusters rather than by sharing one.

### 7.3 Open table formats

> **Beyond EDBS:**
> - **Parquet**: file → row groups → column chunks → pages; encodings include
>   dictionary, RLE/bit-packing hybrid, delta binary packed, delta byte array,
>   byte-stream-split; min/max/null-count statistics per column chunk and per
>   page (page index); optional Bloom filters. Nested data via Dremel-style
>   repetition/definition levels.
> - **ORC**: stripes with lightweight indexes (min/max per 10,000-row group by
>   default), optional Bloom filters, and stripe/file statistics.
> - **Apache Iceberg**: table metadata → manifest list (per snapshot) →
>   manifests listing data files with partition values and per-column
>   lower/upper bounds and counts; hidden partitioning via transforms
>   (day(ts), bucket(N, col), truncate) with partition evolution; snapshots
>   committed by atomically swapping the metadata pointer (optimistic
>   concurrency); format v2 adds position and equality delete files for
>   merge-on-read; v3 adds deletion vectors (stored in Puffin files) and
>   row lineage.
> - **Delta Lake** (Armbrust et al., PVLDB 2020): ordered JSON transaction log
>   with periodic Parquet checkpoints over Parquet data files; optimistic
>   concurrency; data skipping via per-file statistics; Z-ordering.
>
> Pruning in a lakehouse is hierarchical: partition values → manifest/file
> column bounds → row-group statistics → page index → Bloom filters → in-page
> predicate evaluation. Each level must be conservative (invariant 5).
> Small-file proliferation from streaming ingestion requires compaction, and
> compaction must preserve or improve clustering for pruning to keep working.

## 8. Approximate and online answering

- **Online aggregation** (Hellerstein, Haas, Wang, SIGMOD 1997): return
  running estimates with confidence intervals that tighten as random samples
  of the data are processed. Requires random-order access; rarely shipped
  commercially because it changes the query processor fundamentally.
- **Synopsis-based AQP** (Garofalakis & Gibbons tutorial, VLDB 2001): answer
  from precomputed or on-the-fly synopses — uniform/stratified samples,
  histograms, wavelets — with error bounds; BlinkDB is a system instance.
- Engine requirement: the result must carry its error model; joins over
  samples need care (sample of a join ≠ join of samples — sample the fact,
  join full dimensions).

## 9. Hardware acceleration (pointer)

EDBS lists GPU co-processing for scans, filters, joins and aggregation (He,
Lu, He, PVLDB 2013 on coupled CPU-GPU hash joins) and FPGAs for query and
join operators (Teubner, Woods 2013). The warehouse workload (scan-heavy,
compressed, regular) is the best case for such offload; data movement over
the interconnect is usually the limiting factor.

## 10. Pitfalls

- MERGE applying CDC batches out of source commit order (lost updates) or
  non-idempotently on retry (double inserts).
- Surrogate-key lookup against "current" dimension rows for late-arriving
  facts (wrong SCD2 version).
- Partition exchange without validating constraints (rows outside the
  partition range attached silently).
- Trickle feed maintaining bitmap indexes row by row.
- Replicated dimensions updated non-atomically across nodes (queries see
  mixed versions).
- Hash distribution on a low-cardinality or NULL-heavy key (skew).
- Lakehouse readers using stale manifests, or writers committing without
  conflict detection on overlapping files.

## 11. Tests

- CDC apply: random interleavings of insert/update/delete with retries and
  reordering; warehouse state equals source state at each applied LSN.
- Load restart: kill the load at random points; resume; final state equals an
  uninterrupted load.
- Partition lifecycle: attach/detach under concurrent queries; queries see
  either before or after state.
- MPP: distribution-skew tests (heavy hitters), redistribution vs duplication
  plan choices across dimension sizes; results invariant to node count.
- Table formats: concurrent commits with overlapping and disjoint file sets;
  snapshot reads stable; time travel returns historical results exactly.

Sources: EDBS — Data Warehousing Systems: Foundations and Architectures
p.916; Data Warehouse p.876; Data Mart p.793; Extraction, Transformation,
and Loading p.1432; Active, Real-Time, and Intellective Data Warehousing
p.41; Optimization and Tuning in Data Warehouses p.2619; Parallel and
Distributed Data Warehouses p.2644; Data Warehousing in Cloud Environments
p.908; Query Processing in Data Warehouses p.3039; Multidimensional Modeling
p.2328 (data vault); recovered tails (supplement) of Data Warehouse p.876
(adjacent Data Warehouse Life Cycle and Design text) and Data Warehousing in
Cloud Environments p.908 (adjacent Data Warehousing on Nonconventional Data text).
