# EDBS entries behind this skill

Pull any entry in full with the `edbs-reference` skill:
`python3 <edbs-reference>/scripts/edbs.py show "<Entry>"` (add
`--section Foundations` or `--section "Recommended Reading"` to narrow).

| Entry | Printed page | What it gives an engine builder |
|---|---|---|
| Administration Wizards | p.69 | How configuration wizards map workload-level answers (OLTP vs OLAP, user count) onto low-level knobs; import/export and backup wizards. Thin; useful mainly as the argument for eliminating knobs. |
| Application Benchmark | p.122 | Definition of weighted-task application benchmarks versus microbenchmarks; TPC, OO1/OO7, XML benchmark examples. |
| Application-Level Tuning | p.129 | "Start-up costs high, running costs low": set-oriented access vs row-at-a-time loops (measured ~100× gap), object-layer N+1 anti-pattern, bulk insertion via staging tables, index-after-load. |
| Benchmark Frameworks | p.267 | HammerDB and YCSB as driver/generator toolkits; YCSB's latency-vs-load and throughput-vs-servers modes. |
| Data Generation | p.772 | Four sub-problems of synthetic data generation (constraint space, value generation incl. keys and RI, distributions incl. Zipf, assembly); DGL, QAGen, constraint-based generators. |
| Database Administrator (DBA) | p.935 | The DBA as a role and its task list; context for what tuning tools must serve. Thin. |
| Database Benchmarks | p.936 | Benchmark anatomy (SUT, workload, metrics, experiments), Gray's four criteria, TPC/LDBC/YCSB/Linear Road lineage, DeWitt clause, benchmarketing. |
| Database Clustering Methods | p.939 | Data-mining clustering (k-means, BIRCH, DBSCAN, STING). Only tangential here (not physical clustering); see Skipped note. |
| Database Tuning Using Combinatorial Search | p.985 | Physical design as combinatorial search: search space, optimizer-as-metric, what-if server extensions, per-query candidate selection, merging, bottom-up greedy vs top-down relaxation, why staged selection fails. Core entry. |
| Database Tuning Using Online Algorithms | p.989 | Online tuning paradigm: monitor-diagnose-tune loop, online memory allocation, online physical design, self-tuning histograms (STGrid, STHoles, ISOMER, max-entropy), LEO. Core entry. |
| Database Tuning Using Trade-Off Elimination | p.993 | Removing knobs by analysing trade-offs: page size, striping unit, B+-tree vs hash, cache replacement (LRU/LFU/LRFU → LRU-K, 2Q, ARC) and the general lessons. Core entry. |
| Index Tuning | p.1851 | Practical index rules: B+-tree levels vs fanout and key width, hash overflow provisioning, sparse/dense, clustering constraints, covering index column order, scan-vs-secondary break-even, bitmaps for conjunctive DSS predicates. |
| Microbenchmark | p.2255 | Definition: target, parametric measure, parameter guidance; developer-facing purpose (XML context, MemBeR, Michigan). |
| Optimization and Tuning in Data Warehouses | p.2619 | Formal physical design problem (workload, technique classes, constraints, NFRs), redundant vs non-redundant techniques, view/index/partition selection problems, Bell-number vertical partitioning, derived horizontal partitioning, commercial advisor table, observe-predict-react tuning. |
| Performance Analysis of Transaction Processing Systems | p.2732 | Queueing results (M/G/1, priorities, conservation law, fork-join), QNMs and MVA, memory-constrained MPL model, buffer miss rate, RAID performance, standard-locking contention model with thrashing threshold α*≈0.226, restart-oriented locking (RP, WDL), OCC analysis. Core entry. |
| Performance Monitoring Tools | p.2741 | Event monitors, plan explainers, time-based vs counter-based profilers and their overheads. |
| Physical Database Design for Relational Databases | p.2759 | Scope of physical design (normalisation through MDC, partitioning, MVs, memory, storage), pre- vs post-deployment design, OLTP vs DSS design profiles, advisor references (DB2 Design Advisor, AutoAdmin). |
| Physical Layer Tuning | p.2765 | Balanced-system arithmetic (disks per GIPS for OLTP vs DSS), raw vs file-system vs direct async I/O, large extents, dedicated log device, seek-distance placement, thread priorities. |
| Real and Synthetic Test Datasets | p.3110 | Real vs synthetic vs infrastructure-based test data, spatio-temporal generators (GSTD, Oporto, G-TERD, network-based, City Simulator, SUMO). Domain-specific but transferable methodology. |
| Schema Tuning | p.3308 | Principled denormalisation and redundant aggregate tables; measured query speed-up vs insert slow-down with trigger-maintained summary tables. |
| Self-Management Technology in Databases | p.3374 | Configuration×workload→performance framework, inverse problem with SLAs, observe-predict-react, five self-management paradigms, required engine infrastructure, history (COMFORT, AutoAdmin). Core entry. |
| tBench | p.3877 | Benchmark vs family vs framework; five framework principles; derivation of temporal XML/PSM benchmarks by mapping and cross-validation; hidden generator constraints. |
| Tuning Concurrency Control | p.4252 | Counter hot spot vs sequences (latch vs lock, gaps), splitting interactive transactions, rules of thumb, value-of-serializability experiment (snapshot vs lock-based read committed). |
| What-If Analysis | p.4683 | Business-intelligence what-if simulation over cubes (scenarios, source variables, system dynamics, design methodology). Not the optimizer what-if API — that is in Combinatorial Search; see Skipped note. |

## Skipped or used only lightly

- **Database Clustering Methods** — about data-mining clustering of tuples,
  not physical clustering/co-location; only the idea of incremental,
  single-scan summarisation (BIRCH CF-tree) is loosely relevant.
- **What-If Analysis** — BI scenario simulation; relevant only in noting
  index selection as an application. The hypothetical-index mechanism comes
  from Database Tuning Using Combinatorial Search and AutoAdmin papers.
- **Administration Wizards**, **Database Administrator (DBA)** — short
  definitional entries, used for context only.
