# EDBS entries in this cluster

Pull any entry in full with the `edbs-reference` skill:
`python3 <edbs-reference>/scripts/edbs.py show "<Entry>"`.

| Entry | Printed page | What it gives an engine builder |
|---|---|---|
| Big Data Platforms for Data Analytics | 268 | Layered model of dataflow platforms (language → API → dataflow DAG → engine), push vs pull exchange, explicit fields vs key selectors, lineage vs materialization fault tolerance, native iteration requirements; Hadoop, Dryad/SCOPE, Hyracks/AsterixDB, Spark, Flink, Dremel |
| Data Partitioning | 802 | Short definitions of hash, range, list, round-robin, composite horizontal partitioning and vertical partitioning; pruning and manageability motivations |
| Data Skew | 849 | Walton–Dale–Jenevin taxonomy: intrinsic AVS vs partition skew (TPS, SS, RS, JPS); Zipf as the skew model |
| Database Clusters | 940 | Middleware parallelism over unmodified per-node DBMSs with full replication; inter-query routing with ordered updates, intra-query via virtual partitioning; C-JDBC, Sequoia, RepDB*, ParGRES, Pgpool, OLAP*; super-linear TPC-H speedups |
| Database Machine | 956 | Historical filter-processor taxonomy (per-track, per-head, per-disk, multi-processor cache) and the shift to commodity shared-nothing; lineage of storage-side pushdown |
| Elasticity | 1269 | Elastic = self-managed, online growth and contraction; needs monitoring, resource modelling, live repartitioning; ElasTraS, RTP, E-Store |
| Execution Skew | 1412 | Definition: disparate run times of concurrent operator instances, from data skew or transiently unavailable resources; affects both operator-level and intra-operator parallelism |
| Inter-operator Parallelism | 2028 | Pipelined vs independent parallelism between operators; pipelining avoids materialization but constrains consumer memory |
| Inter-query Parallelism | 2029 | Concurrent independent queries for throughput; orthogonal to intra-query parallelism; ACID is the hard part |
| Intra-operator Parallelism | 2030 | Same operator over disjoint partitions; static (stored placement) vs dynamic (repartitioning, typically hashing on the join key) partitioning |
| Intra-query Parallelism | 2030 | Decomposition of one query into concurrent tasks: operator-level (pipelinable operators only) and intra-operator (partitioned, then merged) |
| MapReduce | 2206 | Map/combine/partition/shuffle/group/reduce pipeline, pull-based shuffle with local materialization, task-level fault tolerance and backup tasks; DB-vs-MR debate, HadoopDB, decline in favour of Dataflow/Spark |
| Online Recovery in Parallel Database Systems | 2564 | Five-phase online replica recovery; recovery-lock, multi-round, log-based (end-of-recovery marker), historical-query protocols; performability metric; per-conflict-class parallel recovery |
| Operator-Level Parallelism | 2601 | Independent (bushy) vs pipelined parallelism; left-deep vs right-deep vs bushy via operator dependency graphs (build/probe split); limits: short pipelines, blocking operators, execution skew, processor allocation and fragmentation; segmented right-deep trees |
| Parallel and Distributed Data Warehouses | 2644 | Star-schema placement (partitioned fact, replicated dimensions), primary vs derived horizontal partitioning, physical vs virtual vs adaptive virtual partitioning, design tuple <Arch, DP, DA, DR, LB>, iterative vs conjoint design (Teradata validation), replica placement NP-hardness, load balancing by work migration |
| Parallel Data Placement | 2661 | Round-robin/hash/range trade-offs by access type, full vs variable partitioning (size and heat), location-independent compiled plans, skew remedies, mirrored vs Teradata interleaved vs Gamma chained backup placement |
| Parallel Database Management | 2663 | Goals (performance, availability, extensibility), the I/O-bottleneck origin, shared-memory/disk/nothing and hierarchical architectures and their trade-offs, OLTP/OLAP separation |
| Parallel Hash Join, Parallel Merge Join, Parallel Nested Loops Join | 2666 | Partition-both vs replicate-one, grid scheme for non-equi joins, aligned vs non-aligned partitioning, bit-vector filtering per algorithm, broadcast-vs-repartition heuristic (size ratio vs DOP), average vs max cost metric |
| Parallel Query Execution Algorithms | 2668 | Speedup/scaleup (incl. super-linear), demand- vs data-driven pipelines and buffer slack, partitioning methods and hybrids, co-location, bushy-branch synchronization, exchange operator, parallel sort Halloween coordination, Grace/hybrid agreement, local/global aggregation rule (group size > DOP), merging-exchange deadlock, nested-iteration exchange, top-N limits, parallel updates and index creation |
| Parallel Query Optimization | 2674 | Partitioning as a physical property with exchange as enforcer, co-located vs broadcast joins, outer/semi-join broadcast restriction, single-partition response-time costing and its assumptions, interesting-partitioning heuristics; Teradata/Gamma/GRACE/XPRS/DB2 PE lineage |
| Parallel Query Processing | 2677 | End-to-end view: data-based parallelism, linear speedup/scaleup ideals, response time vs total work, inter- vs intra-operator complementarity, annotated operator trees as the search space |
| Query Load Balancing in Parallel Database Systems | 3004 | Worked example of skew propagation through a pipelined plan; static allocation's three failures (cost-model error, discretization, pipeline delay); adaptive reallocation, sampling-based range-partitioned hash join, rate matching, allocation trees, IO/CPU task pairing, dynamic processing for hierarchical machines |
| Shared-Disk Architecture | 3484 | Cache coherence via distributed lock management, easy migration, ~100-node extensibility, shared storage as bottleneck; Oracle |
| Shared-Memory Architecture | 3485 | Simplicity and dynamic load balancing; cost, limited extensibility (tens of CPUs, ~16 best cost/perf) and availability problems |
| Shared-Nothing Architecture | 3486 | MPP: low cost, thousands of nodes, availability via replication; complexity, placement-driven load balancing, reorganization on growth; Teradata as first major product |
| SQL Analytics on Big Data | 3675 | SQL-on-Hadoop evolution (Hive on MR → Tez/LLAP, Spark SQL, native MPP: Impala, Presto, Drill, HAWQ, Big SQL; HBase/Kudu engines), constraints of data the engine does not own, directory-based partition pruning, columnar formats |
| Virtual Partitioning | 4462 | Query rewriting into range-restricted subqueries over replicas plus result composition; requires clustering on the VP attribute; adaptive VP for load balancing |
