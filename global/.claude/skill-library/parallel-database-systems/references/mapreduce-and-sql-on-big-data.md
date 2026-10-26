# MapReduce, dataflow platforms and SQL on big data

Two lineages built the same thing from opposite ends: parallel DBMSs
(Teradata, Gamma, GRACE — declarative SQL over partitioned shared-nothing
clusters) and web-scale distributed systems (GFS + MapReduce — user functions
over files on shared-nothing clusters). The second lineage spent a decade
re-adding schemas, columnar storage, cost-based optimization, pipelined
exchange and long-running executors; the result ("SQL-on-Hadoop") is
architecturally an MPP database again. Knowing the mapping lets you borrow
from both.

---

## 1. Layered architecture of dataflow platforms

```
 query / scripting languages   HiveQL, Pig Latin, SCOPE, AQL, Spark SQL
          │  compiler/optimizer (power bounded by semantic info at this layer)
 high-level API                RDD / DataFrame / DataSet transformations (Scala, Java, Python)
          │  dataflow planner: algorithm + DOP selection
 low-level dataflow API        physical operators (sort, hash-join) + higher-order
                               operators taking UDFs (map, reduce, filter); DAG of
                               vertices (operators) and edges (exchange links)
          │
 execution engine              spawns parallel instances per vertex, wires channels
                               by link type (all-to-all, point-to-point), push or pull
```

Design dimensions an engine builder chooses explicitly:

| Dimension | Options | Consequence |
|---|---|---|
| Exchange initiation | push (sender-driven: Hyracks, Dremel, MPP DBs) vs pull (receiver fetches: MapReduce shuffle) | push pipelines with low latency; pull decouples phases and simplifies fault tolerance |
| Element model | explicit record/tuple fields vs opaque objects with **key-selector functions** (Flink, Hyracks) | explicit fields let the optimizer reason about keys, projections, partitioning; opaque objects hide them |
| Scheduling | lazy deployment of tasks in topological order; stage co-scheduling respecting blocking operators (Hyracks) | stages = maximal pipelined subgraphs |
| Iteration | none (driver resubmits a job per iteration) vs engine-native iterations with task-level state and repeated execution (Flink bulk/delta iterations) | without native support every iteration pays job startup and re-reads/re-shuffles loop-invariant data |
| Fault tolerance | pessimistic: materialize intermediates (MapReduce); optimistic: lineage-based recomputation of lost partitions (Spark), or constraint-based reinitialization (iterative ML) | materialization costs every run; lineage costs only on failure but can cascade |

The iteration row matters for recursive SQL (recursive CTEs, graph queries):
semi-naive evaluation needs the delta of the previous iteration and the
accumulated result as engine-held state; implementing it by re-planning a
fresh job per iteration works but repays startup and shuffle of invariant
inputs each round.

---

## 2. MapReduce

### Model
- `map: (k1, v1) → list(k2, v2)` — formally a flatMap over input records.
- shuffle: group intermediate pairs by `k2` (partitioned, distributed
  merge-sort).
- `reduce: (k2, list(v2)) → list(out)` — one call per group.
- MapReduce turns user code into an embarrassingly parallel job with minimal
  synchronization: map tasks never talk to each other, reduce tasks never talk
  to each other.

### Engine (Hadoop)
- Master (with optional secondary) schedules tasks and monitors workers;
  workers run map and reduce tasks.
- Map task: **input** module reads one DFS chunk and splits it into pairs →
  **map** UDF → optional **combine** (the reduce function applied locally as
  pre-aggregation, legal when it is associative and commutative) →
  **partition** module (normally `hash(k2) mod R`) → sorted spill files on the
  *local* file system.
- Reduce task: **pulls** its partition from every map output → **group** by
  merge-sort → **reduce** UDF → output to DFS (consecutive jobs read it back).
- Chunk size is a tuning knob with large effect (task count, startup
  amortization, balance).

### Fault tolerance and stragglers
- Map failure: re-run the task on its chunk (any node holding a replica).
- Reduce failure: start a new reduce task that re-pulls from the materialized
  map outputs. Materialization is what makes phase-local restart possible.
- Backup tasks: the same task assigned to more than one worker; the first to
  finish wins, others are killed — defence against slow nodes.
- Load balance: map tasks are pulled by free workers (work stealing over
  chunks).

### Relational operators on MapReduce

| Relational op | MapReduce realization | Parallel-DB equivalent |
|---|---|---|
| Selection, projection | in map | local scan/filter/project |
| GROUP BY + aggregate | map emits (g, v); combiner pre-aggregates; reduce finalizes | two-phase (local/global) aggregation with hash repartition |
| Equi-join (repartition) | map tags each record with its source, emits (join key, tagged record); reduce joins the two lists | repartition-both hash join (but sort-based grouping) |
| Broadcast / replicated (map-side) join | small table shipped to every mapper (distributed cache), joined in map | broadcast join |
| Global sort | sampled range partitioner + sorted reducers | sample-based range repartition + local sort |
| Multi-job queries | each job materializes to DFS | blocking exchange with spool to replicated storage |

Limitations: fixed two-phase plan shape; no first-class multi-input
operators; job launch latency; full materialization between jobs; no schema,
indexes or statistics; UDF opacity blocks optimization.

### The debate and its outcome
DeWitt and Stonebraker's critique ("a major step backwards") and the Pavlo et
al. benchmark (SIGMOD 2009): parallel DBMSs were markedly faster on complex
analytics thanks to schemas, indexes and optimized execution, while
MapReduce was easier for ad-hoc one-off processing and for loading. The
follow-up work imported DB techniques into MapReduce — indexing and a
performance study (Jiang et al., PVLDB 2010), query optimization, replicated
and fuzzy joins (Afrati et al.), shared scans across jobs (MRShare) — and
hybrids appeared: **HadoopDB** (Abouzeid et al., PVLDB 2009) pushes
single-table work into a DBMS per node and uses Hadoop for joins and
coordination; DBMSs (Aster, Oracle) exposed MapReduce as table UDFs. Google
announced in 2014 that it had replaced MapReduce with Dataflow for scale and
latency reasons.

---

## 3. Post-MapReduce dataflow engines

| System | Key idea for an engine builder |
|---|---|
| Dryad / DryadLINQ / SCOPE (Microsoft) | arbitrary DAG of sequential programs connected by one-way channels; the job is a graph generator and the graph may change during execution; SCOPE adds an SQL-like typed rowset language with built-in physical operators |
| Hyracks / AsterixDB | push-based runtime; jobs are DAGs of operators and connectors (redistribution); scheduler co-schedules stages subject to operator blocking; AsterixDB adds a JSON-like data model and query language |
| Spark | RDDs: in-memory intermediates with lineage-based recovery; enables iteration and mini-batch streaming; Spark SQL on top |
| Flink (Stratosphere) | key selectors instead of (k, v) pairs; **cost-based choice of algorithms and data-shipping strategies**; off-heap memory holding serialized records and operators that work directly on serialized bytes; native bulk and delta iterations |
| Dremel | columnar storage for nested records; multi-level serving tree with push; returns partial results early to cut straggler tail |
| Tez | DAG runtime that lets Hive compile one query into one job with pipelined edges |

---

## 4. SQL analytics on big data ("SQL-on-Hadoop")

### What is different from a classic MPP warehouse
1. Nested and semi-structured types (arrays, maps, structs, JSON) are the
   norm.
2. Heavy UDF use for ETL and business logic.
3. **The engine does not own the data**: files are added or rewritten by other
   frameworks, so statistics and indexes are hard or impossible to keep
   current; schema-on-read.
4. Table partitioning is the **directory layout**; partition pruning happens
   statically (predicate on partition columns known at plan time) or
   dynamically (values from a join or a subquery at run time).
5. Storage: write-once append-only DFS; columnar formats (RCFile → ORC;
   Parquet, Dremel-style nested encoding, with min/max zone maps for
   skipping).

### Architectural families

| Family | Examples | Execution | Trade-off |
|---|---|---|---|
| SQL compiled to a batch runtime | Hive on MapReduce → Tez → (Spark); Shark; Spark SQL | runtime's tasks and shuffle | scale and fault tolerance; startup latency (mitigated by Tez single-DAG jobs, LLAP) |
| Native MPP daemons co-located with storage | Impala, Presto, Drill, HAWQ, Big SQL | long-running per-node processes, own exchange | interactive latency — "full circle back to shared-nothing" (Floratou, Minhas, Özcan, PVLDB 2014) |
| DBMS reuse | HadoopDB/Hadapt (DBMS storage per node), HAWQ (Greenplum code), VectorH (Vectorwise code), PolyBase (split processing between SQL Server and Hadoop) | DB engine, sometimes split with MR/Tez | mature optimizer and execution; integration with external formats |
| Update-oriented | Phoenix, Splice Machine over HBase; Kudu (Raft-replicated partitions, columnar storage, accessed via Impala/Spark/Drill) | HBase/Kudu scans | updates and transactions; HBase scans slow for OLAP |

### System notes worth stealing
- **Hive**: HiveQL compiled to MapReduce jobs with shuffle-based joins and
  grouping; moved to Tez (one DAG per query, pipelined edges); added ACID,
  Calcite-based cost optimizer, shuffle-avoiding rewrites, run-time partition
  pruning; **LLAP** long-running daemons with in-memory caching and
  vectorized ORC execution, with clients choosing how much of a query runs in
  LLAP vs Tez containers.
- **Impala**: new C++/Java engine; an `impalad` on every DataNode, any of them
  can plan and coordinate (multi-master → distributed admission control is
  hard); Statestore (pub/sub cluster membership/health) and Catalog (proxy to
  the Hive Metastore); planner → coordinator → plan fragments → exchange;
  short-circuit local reads bypass the DataNode protocol; HDFS caching for
  memory-speed reads; Volcano iterators over row batches; LLVM run-time code
  generation for hot paths.
- **Big SQL**: DB2 technology over HDFS/HBase sharing the Hive Metastore;
  coordinator on a head node; a scheduler assigns HDFS blocks to workers
  **per query at run time**, which gives failure tolerance and elasticity for
  free (new or lost nodes are picked up by the next query); dedicated HDFS
  reader processes; decorrelation and window-based subquery rewrites; workload
  management and admission control; runs under YARN.
- **Spark SQL**: Catalyst optimizer built on Scala pattern matching —
  extensible rule framework; DataFrame API tightly integrated with procedural
  code; Hive-compatible and native interfaces.
- **Presto**: MPP runtime with connectors to HDFS, HBase, MySQL, Cassandra —
  federation by design. **Drill**: SQL over self-describing data without a
  catalog.

---

## 5. Lessons for building a distributed SQL engine today

1. **Long-running executors** beat per-query job launch for interactive SQL;
   keep a batch/fault-tolerant mode for long ETL.
2. **Pipelined vs materialized exchange** is the central dial: pipelining
   gives latency; materialized (spooled) shuffles give stage-level retry,
   re-optimization points and elastic re-scheduling. Staged engines
   (Spark, Ballista) materialize at every shuffle; MPP engines pipeline and
   restart the query on failure.
3. **Locality-aware split assignment at run time** (Big SQL, Hadoop map
   scheduling): bind input splits to executors when the stage starts, prefer
   nodes holding the data or its cache, and you get load balance, failure
   tolerance and elasticity from one mechanism.
4. **Statistics for data you do not own**: collect them at write time in file
   footers and table metadata, and treat them as possibly stale.
5. **Expose structure to the optimizer**: explicit columns over opaque UDF
   objects, declarative over procedural; every layer of opacity removes
   rewrites.
6. **Bucketed layouts enable shuffle-free joins** only if hash function,
   bucket count and key normalization match the writer exactly.

> **Beyond EDBS:** Open table formats (Apache Iceberg, Delta Lake, Hudi) add
> snapshot isolation, schema evolution and per-file column statistics in
> manifests over object storage — restoring pruning and partial
> "ownership" without a monolithic engine. Trino (Presto fork) added
> fault-tolerant execution with spooled exchanges; Databricks Photon is a
> vectorized C++ engine under Spark SQL. DataFusion/Ballista and DuckDB-based
> distributed engines sit in the "native MPP over open formats" family: plan
> with partitioning properties, stage at shuffles, read Parquet/Iceberg
> directly, and decide per deployment whether shuffles pipeline or spool.

---

Sources: Big Data Platforms for Data Analytics (p.268); MapReduce (p.2206);
SQL Analytics on Big Data (p.3675); Parallel Database Management (p.2663);
Parallel Query Optimization (p.2674).
