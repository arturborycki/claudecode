# Database / Query-Engine Internals — Claude Code Skill Library

Thirty-five composable skills for building a database or query engine in
C/C++ or Rust, plus a twelve-agent specialist team. The original fourteen
skills cover the engine spine; the **EDBS expansion** (twenty-one skills) adds the
theory, the less-common subsystems and the literature depth behind them. Each skill owns one box of the
engine and encodes the reference-grade detail (cost formulas, lock
matrices, Arrow invariants, consensus corner cases) that's easy to get
fuzzy on.

## Sources

- **HQEW** — *How Query Engines Work*, Andy Grove (modern columnar pipeline)
- **DBMS** — *Database Systems: The Complete Book*, 2e, Garcia-Molina/Ullman/Widom (algorithms, cost models, theory)
- **DI** — *Database Internals*, Alex Petrov (byte-level storage, LSM, distributed systems)
- **EDBS** — *Encyclopedia of Database Systems*, 2nd ed., Liu & Özsu (eds.), Springer 2018 — 1,414 entries; ~560 distilled into the expansion skills, all 1,414 indexed and retrievable via `edbs-reference`

## The skills

### Query pipeline
| Skill | Owns | Sources |
|---|---|---|
| `query-plan-design` | logical/physical plan model, operator interface, explain | HQEW, DBMS 15–16 |
| `sql-frontend` | tokenizer, Pratt parser, binding/planning | HQEW, DBMS 16.1 |
| `query-optimizer` | rule- and cost-based optimization, join ordering | DBMS 16, HQEW |
| `join-algorithms` | nested-loop / sort-merge / hash / grace, bloom, semantics | DBMS 15, HQEW |

### Storage substrate
| Skill | Owns | Sources |
|---|---|---|
| `columnar-arrow-layout` | Arrow buffers, validity bitmaps, vectorized exec | HQEW |
| `storage-and-indexing` | buffer pool, B-trees, hash/bitmap indexes, variants | DBMS 13–14, DI 2/4/5/6 |
| `page-and-file-format` ★ | on-disk encoding, slotted pages, checksums, versioning | DI 3–4, DBMS 13 |
| `lsm-storage` ★ | LSM trees, memtable/SSTable, compaction, amplification | DI 7 |

### Transactions
| Skill | Owns | Sources |
|---|---|---|
| `transactions-and-recovery` | 2PL, lock matrix, MVCC, WAL/ARIES, recovery | DBMS 17–19, DI 5 |

### Scale-out (two distinct axes)
| Skill | Owns | Sources |
|---|---|---|
| `parallel-distributed-execution` | partitioning, exchange/shuffle, query stages | HQEW, DBMS 20 |
| `replication-and-consistency` ★ | CAP, consistency models, quorums, anti-entropy, CRDTs | DI 11–12 |
| `distributed-consensus` ★ | failure detection, leader election, Paxos, Raft | DI 8/9/10/14 |
| `distributed-transactions` ★ | 2PC/3PC, Calvin, Spanner, Percolator | DI 13, DBMS 20 |

### Cross-cutting
| Skill | Owns | Sources |
|---|---|---|
| `query-engine-testing` | golden/sqllogictest, fuzzing, simulation testing, benchmarks | HQEW |

★ = added/expanded thanks to *Database Internals*.

## EDBS expansion (twenty-one skills)

Each skill has a compact `SKILL.md` operating manual plus `references/`
deep dives and `references/edbs-entries.md` (source entries with printed
page numbers). Content is distilled and paraphrased, not copied; pull any
original entry from your own PDF with `edbs-reference`.

### Foundations & architecture
| Skill | Owns |
|---|---|
| `dbms-architecture` | component decomposition, process/thread models, buffer management in depth, cache-conscious & main-memory design, shared-x architectures |
| `relational-theory` | algebra/calculus, rewrite laws under bags & NULLs, containment, chase & dependencies, Datalog/recursion, incomplete information |
| `sql-semantics-and-active-rules` | the SQL semantic contract (3VL, bags, windows, constraints), triggers/ECA execution, client APIs, edge-case test vectors |
| `storage-devices-and-io` | HDD/SSD/NVMe cost models, RAID, storage networks, integrity/checksums, the I/O model |

### Query processing
| Skill | Owns |
|---|---|
| `query-execution-advanced` | iterator/pipelining/memory, sort/aggregate/set ops, window operators, top-k/rank-join/skyline, adaptive & approximate processing |
| `cardinality-and-statistics` | System R lineage, join enumeration, selectivity, histograms, sampling, sketches, query rewrite, MQO |
| `materialized-views-ivm` | incremental view maintenance, answering queries using views, view updates |

### Transactions & durability
| Skill | Owns |
|---|---|
| `concurrency-control-theory` | serializability theory, 2PL/B-tree locking, MVCC/SI/SSI, isolation anomalies, extended transaction models |
| `recovery-and-durability` | WAL taxonomy, ARIES in full, checkpointing, main-memory recovery, backup/PITR/DR |

### Access methods
| Skill | Owns |
|---|---|
| `index-structures-catalog` | B+-tree engineering, hashing schemes, bitmap/join indexes, text/string indexes, Bloom filters |
| `multidimensional-and-similarity-indexing` | GiST/R-trees, space-filling curves, spatial join & NN, high-dimensional/metric, temporal indexes, vector ANN (HNSW/IVF-PQ/DiskANN) |

### Scale-out
| Skill | Owns |
|---|---|
| `parallel-database-systems` | MPP placement/declustering, parallel operators, skew taxonomy & mitigation, parallel optimization, SQL-on-big-data |
| `distributed-dbms-design` | fragmentation/allocation, distributed QP & semijoins, distributed CC/deadlock, commit protocols, multitenancy |
| `replication-protocols` | eager/lazy × primary/update-anywhere, 1SR & quorums, SI/group-communication replication, consistency models, CRDTs, geo-replication |

### Analytical & specialised engines
| Skill | Owns |
|---|---|
| `olap-and-warehouse-engines` | summarizability, cube computation, star joins, column-store engineering, warehouse architecture |
| `stream-processing-engines` | CQL semantics, windows & punctuations, scheduling/load shedding, exactly-once, synopses, CEP |
| `temporal-databases` | valid/transaction time, sequenced semantics, temporal joins/aggregation, SQL:2011 temporal |
| `beyond-relational-engines` | NoSQL design space, JSON/XML storage & indexing, graph/RDF engines, OR extensibility, probabilistic DBs, provenance |

### Operations & safety
| Skill | Owns |
|---|---|
| `tuning-and-benchmarking` | physical-design advisors, self-tuning, performance models, benchmark methodology, workload management |
| `database-security-internals` | authorization enforcement, MLS, encryption in the engine, integrity verification, audit & compliance |

### Literature
| Skill | Owns |
|---|---|
| `edbs-reference` | index of all 1,414 EDBS entries (pages, cross-references, skill map) + `scripts/edbs.py` to pull any entry from your PDF (`EDBS_PDF=/path/to/edbs.pdf`) |

## Agent team (`agents/`)

| Agent | Use for | Preloads |
|---|---|---|
| `rdbms-architect` | cross-cutting designs, ADRs, routing to specialists | dbms-architecture, edbs-reference, relational-theory |
| `query-optimizer-engineer` | rewrites, decorrelation, enumeration, cardinality, MV matching | query-optimizer, cardinality-and-statistics, relational-theory, materialized-views-ivm, sql-semantics-and-active-rules |
| `execution-engine-engineer` | operators, vectorization, memory/spill, windows, top-k | query-execution-advanced, join-algorithms, columnar-arrow-layout, query-plan-design, dbms-architecture |
| `storage-engine-engineer` | formats, buffer pool, indexes, device-aware I/O | storage-and-indexing, page-and-file-format, index-structures-catalog, storage-devices-and-io, lsm-storage |
| `transaction-recovery-engineer` | isolation, CC, WAL/ARIES, backup | concurrency-control-theory, recovery-and-durability, transactions-and-recovery |
| `distributed-db-engineer` | MPP, partitioning, skew, replication, consensus, commit | parallel-database-systems, distributed-dbms-design, replication-protocols, distributed-consensus, distributed-transactions, parallel-distributed-execution |
| `analytics-engine-engineer` | OLAP, streams, temporal | olap-and-warehouse-engines, stream-processing-engines, temporal-databases, materialized-views-ivm, columnar-arrow-layout |
| `db-security-engineer` | authz, encryption, audit | database-security-internals, sql-semantics-and-active-rules, page-and-file-format |
| `db-performance-engineer` | benchmarks, profiling, tuning, workload mgmt | tuning-and-benchmarking, query-engine-testing, storage-devices-and-io, dbms-architecture |
| `db-correctness-auditor` | independent adversarial review (read-only + Bash) | query-engine-testing, relational-theory, sql-semantics-and-active-rules, concurrency-control-theory, recovery-and-durability |
| `rdbms-professor` | theory, literature, reading plans, examination | edbs-reference, relational-theory, dbms-architecture |
| `engine-dev` | Rust/C/C++ implementation with guardrails | query-engine-testing |

Agents preload skills by name (`skills:` frontmatter), so **install the skills
an agent preloads into the same project** (choosing `a` for all in
`claude-skills-init` is simplest for an engine repo). The
`rules/rdbms-expert-method.md` file describes the team's working method.

### More composition examples
- *"Add serializable isolation to our MVCC engine"* → `rdbms-architect` → `transaction-recovery-engineer` (`concurrency-control-theory`) + `storage-engine-engineer` (index gap tracking) → `db-correctness-auditor`
- *"Distributed recursive CTEs (Ballista)"* → `relational-theory` (semi-naive, stratification) + `parallel-database-systems` + `query-optimizer`
- *"Vector index on Iceberg"* → `multidimensional-and-similarity-indexing` + `olap-and-warehouse-engines` + `storage-devices-and-io`
- *"Our estimates are off on correlated predicates"* → `query-optimizer-engineer` (`cardinality-and-statistics`)
- *"Incremental refresh for aggregate MVs"* → `materialized-views-ivm` + `olap-and-warehouse-engines`

## How they compose

A task pulls in several skills at once. Examples:
- *"Add a hash-join operator"* → `query-plan-design` + `join-algorithms` + `columnar-arrow-layout` + `query-engine-testing`
- *"Build an LSM storage engine"* → `lsm-storage` + `page-and-file-format` + `transactions-and-recovery`
- *"Make the cluster survive a node crash"* → `distributed-consensus` + `replication-and-consistency`
- *"Cross-shard transaction support"* → `distributed-transactions` + `distributed-consensus` + `transactions-and-recovery`

## Two distinct "distributed" axes — don't confuse them

- **`parallel-distributed-execution`** splits one query's *work* across cores/nodes (exchange operators, stages). This is query *execution*.
- **`replication-and-consistency` / `distributed-consensus` / `distributed-transactions`** keep *data* correct across nodes (agreement, replication, atomic commit). This is the distributed *data system*.

## Suggested first three
If building incrementally: `columnar-arrow-layout` (the data substrate),
`query-plan-design` (the operator contract), `query-engine-testing` (the
safety net — bugs in systems code are memory-unsafe). Layer the rest on.

## Install
Each subdirectory is a self-contained skill (`<name>/SKILL.md`, plus
`references/` and, for `edbs-reference`, `scripts/`). Copy whole folders,
not just `SKILL.md`. The normal route is `./setup-global.sh` (installs this
library to `~/.claude/skill-library`) followed by `claude-skills-init` in a
project, which copies the chosen skills to `.claude/skills/` and optionally
the `agents/` team to `.claude/agents/` and `rules/` to `.claude/rules/`.

## EDBS expansion — quick start
1. `./setup-global.sh` (copies the library, including `references/` and `scripts/`, to `~/.claude/skill-library`).
2. In an engine repo: `claude-skills-init` → `a` (all skills) → yes to agents and rules.
3. Point the lookup tool at your copy of the book:
   `export EDBS_PDF=~/books/edbs.pdf` (needs `pdftotext` from poppler, or `pip install pypdf`).
   Smoke test: `python3 .claude/skills/edbs-reference/scripts/edbs.py show "Serializable Snapshot Isolation" --section Definition`.
4. Start cross-cutting work with the `rdbms-architect` agent; run `db-correctness-auditor` before merging
   anything that touches optimizer rules, storage formats, concurrency control, recovery or replication.
5. `sql-semantics-and-active-rules/references/semantic-test-vectors.slt` is a ready-to-run sqllogictest file
   (~200 records, checked against PostgreSQL 16 and DuckDB 1.1, with per-engine `skipif` for known deviations).

Content note: the expansion skills paraphrase and synthesise EDBS entries (no verbatim passages; an automated
12-word overlap scan against the full book text reports zero matches). Post-2018 practice is marked
`Beyond EDBS` and product-specific details carry "verify against current docs" where they may drift.
