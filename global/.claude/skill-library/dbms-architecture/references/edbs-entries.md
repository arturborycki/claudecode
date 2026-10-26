# EDBS entries in the dbms-architecture cluster

Pull any full entry with the `edbs-reference` skill:
`python3 <edbs-reference>/scripts/edbs.py show "<Entry>"`.

| Entry | Printed page | What it gives an engine builder |
|---|---|---|
| Application Server | p.128 | Role of the business-logic tier in three/multi-tier systems; app-server clusters and transactional middleware above the DBMS. |
| Architecture-Conscious Database System | p.155 | Hardware trends that drive engine design: flash vs disk, cache misses, prefetching, branch misprediction (branch-free selection data), SIMD, CMP/SMT and the warning that work sharing can limit parallelism. |
| Buffer Management | p.350 | Deepest treatment of replacement: VM vs predictive schools, LRU-K, 2Q, LRFU/CRF, the scan problem, hot set model, simple/loop/index reuse, QLSM/DBMIN, IRM-optimal and OLRU level allocation, OPT limits, thrashing and hot-set scheduling. |
| Buffer Manager | p.357 | The buffer-pool API (pin, latch, force, write-order retention, hints), dirty-page retention, write-behind/read-ahead/prefetch sizing, steal/no-force, careful write ordering for B-tree splits, cooperative pools. |
| Buffer Pool | p.360 | Frames, descriptors, frame states, multiple page versions in the pool, one pool per page size, hash lookup and LRU list mechanics, why VM/file caches are rejected, memory stealing, deep hierarchies. |
| Cache-Conscious Query Processing | p.389 | Catalogue of cache techniques: column/PAX layout, CSS/CSB+-trees, blocking, buffered index probes, i-cache buffering, partitioned/radix joins, prefetching, TLB-aware partitioning with write-combining, sampling-based algorithm choice. |
| Client-Server Architecture | p.439 | Split of DBMS functions between client and server, SQL-level communication, client caching of data/locks, single vs multiple servers, heavy vs light clients, path to three-tier. |
| Column Stores | p.518 | NSM vs DSM, column-store lineage (KDB, Sybase IQ, MonetDB, C-Store, Vertica, HANA), workload trade-offs, compression, tuple reconstruction, late materialization; distinction from column-family stores. |
| Concurrency Control Manager | p.574 | The lock manager as a component: access-request table, waits-for list, deadlock/conflict victim selection handed to the transaction manager, rollback by recovery manager. |
| Connection | p.581 | Connection establishment (handshake, auth, protocol negotiation), connections as the main concurrency source, server caps and priorities, client connection pools, ODBC/JDBC/ADO.NET. |
| Data Dictionary | p.749 | Two meanings of data dictionary; what a system catalog contains (schema, privileges, indexes, constraints, storage parameters, statistics, procedures/triggers); INFORMATION_SCHEMA. |
| Data Management Fundamentals: Database Management System | p.784 | Generic DBMS definition, functionality-vs-overhead trade-off (full DBMS vs NoSQL), data independence motivation for relational systems. |
| Database Machine | p.956 | Special-purpose database hardware: PPT/PPH/PPD/MPC filter processors and the shift to parallel machines of commodity nodes. |
| Database Management System | p.957 | Helland's view: history (CODASYL, IMS, relational), the DDL abstraction as the essence of a DBMS, independent evolution, performance independence, ACID, access methods and why B+-trees won. |
| DBMS Component | p.1005 | Canonical decomposition: communications manager, process manager (admission, dispatch), relational query processor, transactional storage manager (access methods, buffer, lock, log), shared utilities. |
| DBMS Interface | p.1005 | External vs internal DBMS interfaces; internal queue interfaces enable staged execution. |
| Distributed Architecture | p.1152 | Taxonomy of parallel, distributed, federated, mediator, multi-database and P2P systems; schema/query/update/naming transparency; fragmentation, replication, consistency cost, distributed catalog replication vs caching. |
| I/O Model of Computation | p.1741 | Counting block transfers as the cost metric; seek/rotate/transfer; random vs sequential; B+-tree vs binary tree; buffering and bucket transfers. |
| Locality | p.2117 | Cross-reference stub pointing to *Locality of Queries* (Hanf/Gaifman locality in finite model theory, a logic notion unrelated to memory locality); use *Memory Locality* (p.2229) instead. |
| Logging/Recovery Subsystem | p.2135 | Log manager vs recovery manager roles, online vs archive log, WAL statement, log records opaque to the log manager and owned by resource managers, restart scan outline. |
| Logical and Physical Data Independence | p.2136 | Three-schema architecture and the definitions of physical and logical data independence via inter-level mappings. |
| Main Memory | p.2162 | DRAM, virtual memory and paging, the memory wall (~50 ns minimum latency), cache lines, on-die memory controllers, NUMA; implications for DBMS data layout. |
| Main Memory DBMS | p.2164 | In-memory DBMS definition, CPU/cache-oriented design, durability via logging, NVRAM or replicated standby, historical systems and use cases. |
| Memory Hierarchy | p.2222 | Formal cache model: capacity, line size, associativity, inclusive/exclusive, four miss types, sequential vs random latency and bandwidth, TLB, unified per-level cost parameters, calibration. |
| Memory Locality | p.2229 | Temporal and spatial locality, working sets, and how partitioned joins, clustered indexes, PAX and row/column choice exploit them. |
| Multitier Architecture | p.2443 | Fat client vs fat server, three/N-tier with horizontal distribution, TP-monitor dispatching, 2PC and multi-level transactions across tiers, queued transactions, mid-tier caching. |
| Process Structure of a DBMS | p.2867 | Evolution from in-process library to client-server/N-tier/SOA; DBMS layer formats; transaction identity across tiers and connections; shared-everything/disk/nothing as cut points; hot-spot and page-locking trade-offs. |
| Processor Cache | p.2887 | Cache organization and miss types, TLB reach and huge pages, multi-level caches, coherence in multicore, hardware vs software prefetching, DSM/PAX and cache-conscious joins. |
| Query Processor | p.3058 | Parser/authorization, rewriter, plan cache, optimizer, executor lifecycle; optimizer-executor coupling; iterator model and its overhead on modern CPUs. |
| Session | p.3484 | Session as sequence of client interactions holding in-flight state, cursors and session-private temp tables (entry text is fragmentary). |
| Shared-Disk Architecture | p.3484 | Definition, cache coherence via distributed locking, advantages (cost, ~100-node extensibility, availability, load balance, easy migration) and drawbacks. |
| Shared-Memory Architecture | p.3485 | SMP definition, simplicity and load balancing benefits, cost/extensibility/availability limits. |
| Shared-Nothing Architecture | p.3486 | MPP definition, Teradata as first major product, scalability and availability benefits, complexity and partition-driven load balancing. |
| Staged DBMS | p.3696 | Stage/packet architecture with per-stage queues and threads, two-level scheduling, QPipe/Cordoba, work sharing vs MVs, MQO and shared scans. |
| Storage Manager | p.3736 | Storage-layer contract: physical vs logical concepts, services, OS requirements, latch rules, page format (version, pageLSN), mapping all structures to B-trees, index maintenance and navigation placement, recovery granularity, utilities on the executor. |
| Stream Processing on Modern Hardware | p.3772 | SDF vs asynchronous streaming, pipeline/task/data parallelism, fusion and fission on multicore, GPU batching constraints, FPGA query compilation; lessons for accelerator offload. |
| Transaction Manager | p.4194 | TxM as resource manager: unique transaction ids, state transitions, RM and session registration, 2PC coordinator/participant, first component rebuilt at restart, in-doubt resolution. |

Weak or skipped: *Locality* (p.2117) is a cross-reference stub. *Session*
(p.3484) and *Connection* (p.581) are short; their content is absorbed into
`components-and-process-models.md` §9. The bundle's leading fragments of
neighbouring entries (frequent-itemset mining before *Architecture-Conscious
Database System*, stream classification before *Client-Server Architecture*,
multitenancy before *Multitier Architecture*, consistency models after
*Connection*) were ignored.
