# Claude Code Configuration Templates

Based on production patterns from running multi-agent Claude Code deployments.

## Quick Start

```bash
# Clone the repo
git clone https://github.com/arturborycki/claudecode.git
cd claudecode

# One-time global setup
./setup-global.sh

# Set up a new project
./setup-project.sh /path/to/my-project
```

## Folder Structure

```
├── setup-global.sh                  # Script to install global config
├── setup-project.sh                 # Script to initialize new projects
├── tools/
│   └── gen-inventory.py             # Regenerates the Inventory section of this README
├── global/                          # Copy to ~/.claude/
│   └── .claude/
│       ├── MEMORY.md                # System-wide standards (all projects)
│       ├── INFRASTRUCTURE.md        # Global server/service reference
│       ├── settings.json            # Global permissions & env vars
│       ├── skill-library/           # Menu of skills to pick from per-project
│       │   ├── README.md            # Library guide: every skill, agent, composition examples
│       │   ├── <skill>/SKILL.md     # 35 database-internals skills (each may have references/, scripts/)
│       │   ├── edbs-reference/      # Index of all 1,414 EDBS entries + scripts/edbs.py lookup tool
│       │   ├── agents/              # 12 agents: rdbms-architect, 10 specialists, engine-dev
│       │   └── rules/               # engine-internals.md, rdbms-expert-method.md
│       ├── bin/
│       │   └── claude-skills-init   # Interactive skill picker (NEW)
│       ├── commands/                # Global custom commands
│       │   ├── wrap.md              # /wrap — End session, commit
│       │   ├── sup.md               # /sup — Quick status check
│       │   ├── fragile.md           # /fragile — Review danger zones
│       │   ├── plan.md              # /plan — Two-phase planning
│       │   ├── research.md          # /research — Deep exploration
│       │   ├── infra.md             # /infra — Infrastructure reference
│       │   ├── new-project.md       # /new-project — Initialize project
│       │   └── skills.md            # /skills — Add library skills to a project (NEW)
│       └── rules/
│           └── infrastructure-access.md  # Global infra access rules
│
└── project/                         # Copy to your project root
    ├── CLAUDE.md                    # Project context (read first)
    ├── INFRASTRUCTURE.md            # Project-specific servers/services
    ├── _FRAGILE.md                  # Danger zones documentation
    ├── _NEXT_SESSION_MEMO.md        # Session handoff notes
    ├── _VOCABULARY.md               # Canonical terminology
    ├── .mcp.json.example            # MCP server config template
    └── .claude/
        ├── commands/                # Project-specific commands
        └── rules/
            └── infrastructure.md    # Project infra access rules
```

## Installation

### Using Setup Scripts (Recommended)

```bash
# Global setup (one time)
./setup-global.sh

# Per-project setup
./setup-project.sh /path/to/my-project
```

### Manual Installation

<details>
<summary>Click to expand manual steps</summary>

#### Global Setup (One Time)

```bash
# Copy all global files
cp global/.claude/MEMORY.md ~/.claude/
cp global/.claude/INFRASTRUCTURE.md ~/.claude/
cp global/.claude/settings.json ~/.claude/

# Copy global commands
cp -r global/.claude/commands ~/.claude/

# Copy global rules
mkdir -p ~/.claude/rules
cp -r global/.claude/rules/* ~/.claude/rules/
```

#### Per-Project Setup

```bash
# From your project root:
cp /path/to/claudecode/project/CLAUDE.md ./
cp /path/to/claudecode/project/INFRASTRUCTURE.md ./
cp /path/to/claudecode/project/_FRAGILE.md ./
cp /path/to/claudecode/project/_NEXT_SESSION_MEMO.md ./
cp /path/to/claudecode/project/_VOCABULARY.md ./

# Copy project .claude folder
cp -r /path/to/claudecode/project/.claude ./

# Optional: Set up MCP servers
cp /path/to/claudecode/project/.mcp.json.example ./.mcp.json
# Then edit .mcp.json with your actual values
```

</details>

## Commands Usage

After installing the global commands, use them in any Claude Code session:

| Command | Purpose | When to Use |
|---------|---------|-------------|
| `/wrap` | End session properly | End of work session |
| `/sup` | Quick status check | Anytime, fast overview |
| `/fragile` | Review danger zones | Before touching sensitive code |
| `/plan` | Two-phase planning | Complex features, no YOLO |
| `/research` | Deep exploration | Investigation tasks |
| `/infra` | Infrastructure reference | Before server/DB operations |
| `/new-project` | Initialize new project | Starting a new codebase |
| `/skills` | Add skills from the library | Project needs domain skills |

## Skills & Agents

Skills are reusable playbooks Claude loads on demand; agents are specialized
workers. This repo ships a **skill library** (a menu) plus a picker so each
project gets only the skills it needs — global skills would clutter every
unrelated project with descriptions they don't use.

```
~/.claude/skill-library/   # installed by setup-global.sh — the menu
~/.claude/bin/claude-skills-init   # the interactive picker
```

### Add skills to a project

`setup-project.sh` offers to run the picker at the end. To add skills later,
from the project root:

```bash
claude-skills-init            # interactive multi-select (gum > fzf > plain)
claude-skills-init --list     # just list what's available
claude-skills-init --link     # symlink instead of copy (single source of truth)
```

Selected skills land in `.claude/skills/`. The picker also offers the bundled
agent team into `.claude/agents/` and rules into `.claude/rules/`. Commit
`.claude/` so skills and agents travel with the repo (including to Claude
Code web sessions and teammates). Inside a session you can use `/skills`
instead of dropping to the shell.

Agents preload skills by name (`skills:` in their frontmatter), so when you
install an agent, install the skills it lists. For an engine repo, picking
`a` (all) is simplest. To refresh skills a project already has, run
`claude-skills-init --force`.

### What's in the library

**Database / query-engine internals** for C/C++/Rust engine work: skills
spanning the whole engine (SQL front end → optimizer → execution → storage →
transactions/recovery → parallel and distributed execution, plus analytical,
temporal, streaming, security and tuning topics), and a team of specialist
agents led by `rdbms-architect`. Skills are built from four references: *How
Query Engines Work* (Grove), *Database Systems: The Complete Book*
(Garcia-Molina/Ullman/Widom), *Database Internals* (Petrov) and the
*Encyclopedia of Database Systems*, 2nd ed. (Liu & Özsu, eds., "EDBS").

EDBS-based skills carry `references/` deep dives and a
`references/edbs-entries.md` source map with printed page numbers. Content
is paraphrased and synthesised, not copied, and was independently reviewed
for technical accuracy; material newer than the 2018 book is marked
*Beyond EDBS*. `sql-semantics-and-active-rules` includes ~200 runnable
sqllogictest vectors checked against PostgreSQL 16 and DuckDB 1.1.

Typical flow: `rdbms-architect` designs → specialists go deep →
`engine-dev` implements → `db-correctness-auditor` reviews. Ask by name
("have rdbms-architect design …") or let Claude delegate from the agent
descriptions; `/agents` lists them.

The complete, generated list of every skill, agent, rule and command is in
[Inventory](#inventory) below; composition examples are in
`global/.claude/skill-library/README.md`. Drop your own skill folders into
the library to extend the menu, then regenerate the inventory.

### EDBS lookup tool (optional)

`edbs-reference` searches all 1,414 entry titles and their cross-references
offline. To print an entry's full text it reads your own PDF copy of the
encyclopedia:

```bash
export EDBS_PDF=/path/to/edbs.pdf   # add to ~/.zshrc
brew install poppler                              # provides pdftotext (or: pip install pypdf)
python3 .claude/skills/edbs-reference/scripts/edbs.py search snapshot isolation
python3 .claude/skills/edbs-reference/scripts/edbs.py show "Serializable Snapshot Isolation" --section Foundations
```

### Updating the library

Edit skills in this repo → `git pull` on each machine → `./setup-global.sh`
→ in each project run `claude-skills-init --force` and commit `.claude/`.

### A note on hooks

A hook can't present the picker — Claude Code hooks are non-interactive
scripts (their stdin is JSON event context, not your keyboard). The live
checkbox menu only works in your terminal, so the picker is a standalone
script; `/skills` and `setup-project.sh` are the integration points.

## Inventory

<!-- INVENTORY:START -->
<!-- Generated by tools/gen-inventory.py from the files on disk. Do not edit by hand; run `python3 tools/gen-inventory.py` after changing skills, agents, rules or commands. -->

**35 skills** (14 core, 21 EDBS-based) · **12 agents** · **2 library rules** · **8 commands** — 170 skill files, 44,789 lines.

*Source*: **Core** = built from *How Query Engines Work*, *Database Systems: The Complete Book* and *Database Internals*; **EDBS** = built from the *Encyclopedia of Database Systems*, 2nd ed. (has `references/edbs-entries.md` mapping each skill to its source entries).

### Skills

All skills live in `global/.claude/skill-library/<skill>/`.

#### Query pipeline

| Skill | Source | What it covers | Deep-dive references | Lines | Preloaded by |
|---|---|---|---|---:|---|
| `query-plan-design` | Core | Defining or changing the plan layer of a query engine: logical/physical plan node types, operator interfaces, plan printing/explain output, expression trees, or the logical→physical lowering step | — | 90 | `execution-engine-engineer` |
| `sql-frontend` | Core | Building or extending the SQL front end of a query engine: tokenizer/lexer, parser, operator precedence, or the binder/analysis pass that turns a parse tree into a validated logical plan | — | 87 | — |
| `query-optimizer` | Core | Implementing or reviewing query optimization: rewrite rules (predicate push-down, projection push-down, constant folding, common-subexpression elimination), cardinality/cost estimation, or cost-based plan and join-order selection | — | 90 | `query-optimizer-engineer` |
| `join-algorithms` | Core | Implementing, choosing between, or tuning join operators: nested-loop, block-nested-loop, sort-merge, hash join, grace/partitioned hash join, index nested-loop, bloom-filter joins, and semi/anti/outer join semantics | — | 93 | `execution-engine-engineer` |
| `query-execution-advanced` | EDBS | Implementing or reviewing execution-engine internals beyond the basic join catalogue: the iterator (Volcano) open/next/close contract, pipelining vs blocking (stop-&-go) operators, memory budgets and spilling, access path selection … | `access-paths-and-reducers`, `adaptive-and-approximate-processing`, `iterator-pipelining-and-memory`, `sort-aggregate-setops`, `topk-rank-join-and-skyline`, `window-operators` | 2,100 | `execution-engine-engineer` |
| `cardinality-and-statistics` | EDBS | Designing, implementing or reviewing the optimizer's estimation and search machinery: statistics collection, histograms, sampling, sketches, selectivity and join-size estimation, cost models, join-order enumeration, and estimate-sensitive … | `histograms`, `query-rewrite-and-mqo`, `sampling-and-sketches`, `selectivity-and-cost-models`, `system-r-and-join-enumeration` | 1,927 | `query-optimizer-engineer` |
| `materialized-views-ivm` | EDBS | Designing, implementing or reviewing views as an engine feature: view definition and expansion, MV storage and refresh, incremental view maintenance (IVM), rewriting queries using views, view selection, or updates through views | `aggregates-outerjoins-recursion`, `consistency-and-scheduling-of-maintenance`, `delta-rules-and-counting`, `query-rewriting-using-views`, `view-updates` | 1,997 | `analytics-engine-engineer`, `query-optimizer-engineer` |

#### Foundations

| Skill | Source | What it covers | Deep-dive references | Lines | Preloaded by |
|---|---|---|---|---:|---|
| `dbms-architecture` | EDBS | Designing or reviewing the whole-system structure of a relational engine: component boundaries (query processor, storage manager, buffer/lock/log/transaction managers, catalog), process and thread models, connections and sessions … | `architectures-shared-x-and-column-stores`, `buffer-management`, `cache-conscious-and-main-memory`, `components-and-process-models` | 1,861 | `db-performance-engineer`, `execution-engine-engineer`, `rdbms-architect`, `rdbms-professor` |
| `relational-theory` | EDBS | Correctness of a query rewrite, plan property, or SQL semantic decision depends on relational theory: algebraic equivalences under set vs bag semantics, conjunctive-query containment and minimization, Datalog/recursive CTE evaluation … | `algebra-calculus-and-rewrite-laws`, `containment-and-minimization`, `datalog-and-recursion`, `dependencies-chase-and-semantic-optimization`, `normalization-and-keys`, `nulls-and-incomplete-information` | 2,281 | `db-correctness-auditor`, `query-optimizer-engineer`, `rdbms-architect`, `rdbms-professor` |
| `sql-semantics-and-active-rules` | EDBS | Implementing, reviewing or testing the semantic contract of an SQL engine or its active-database features: NULL and three-valued logic, bag/duplicate semantics, set operators, aggregates over empty input, outer-join padding, window frames … | `client-interfaces-and-procedures`, `ddl-dml-constraints-and-catalog`, `eca-rules-and-trigger-execution`, `null-3vl-and-bag-edge-cases`, `semantic-test-vectors`, `window-function-semantics`<br>+ `semantic-test-vectors.slt` | 3,246 | `db-correctness-auditor`, `db-security-engineer`, `query-optimizer-engineer` |

#### Storage & access methods

| Skill | Source | What it covers | Deep-dive references | Lines | Preloaded by |
|---|---|---|---|---:|---|
| `columnar-arrow-layout` | Core | Working with columnar in-memory data and vectorized execution: Apache Arrow record batches, column vectors/arrays, validity (null) bitmaps, offsets buffers, dictionary encoding, zero-copy slicing, the type system, or batch-at-a-time … | — | 75 | `analytics-engine-engineer`, `execution-engine-engineer` |
| `storage-and-indexing` | Core | Working on the storage layer or access methods of a database: buffer pool/buffer manager, B-tree/B+-tree implementation (search, split, merge, rebalance), hash indexes, bitmap indexes, index selection, or B-tree variants (copy-on-write … | — | 87 | `storage-engine-engineer` |
| `page-and-file-format` | Core | Designing or implementing the on-disk byte layout of a storage engine: page structure, slotted pages, cell layout, record/tuple encoding, variable-size data management, fixed vs variable encoding, endianness, alignment, versioning, and … | — | 100 | `db-security-engineer`, `storage-engine-engineer` |
| `lsm-storage` | Core | Implementing or tuning a log-structured / LSM storage engine: memtables, SSTables, compaction strategies (size-tiered, leveled), the read/write/space amplification tradeoff, tombstones and deletes, bloom filters for SSTable reads … | — | 97 | `storage-engine-engineer` |
| `storage-devices-and-io` | EDBS | Engine behaviour depends on the device and I/O stack beneath the page layer: HDD seek/rotation cost, SSD internals (FTL, erase blocks, garbage collection, write amplification, wear, queue depth), NVMe, RAID levels and the small-write … | `device-cost-models`, `integrity-checksums-and-durability-of-io`, `io-model-and-algorithm-costs`, `raid-and-storage-networks`, `ssd-and-flash-for-db-engines` | 1,866 | `db-performance-engineer`, `storage-engine-engineer` |
| `index-structures-catalog` | EDBS | Choosing, implementing or reviewing one-dimensional and text index structures at implementation depth: index taxonomy (clustered vs secondary, dense vs sparse, covering, unique), ISAM, B+-tree engineering (bulk load, fill factor, key … | `bitmap-and-join-indexes`, `bloom-filters`, `btree-engineering`, `hashing-schemes`, `index-taxonomy-and-access-paths`, `text-and-string-indexes` | 2,054 | `storage-engine-engineer` |
| `multidimensional-and-similarity-indexing` | EDBS | Designing, implementing or reviewing multidimensional, spatial, temporal or similarity access methods and the operators on top of them: GiST/SP-GiST operator classes, R-tree/R*-tree/Hilbert R-tree, STR bulk loading, quadtrees, kd-trees … | `gist-and-rtree-family`, `high-dimensional-and-metric-indexing`, `space-filling-curves-and-grids`, `spatial-join-and-nn-search`, `temporal-and-moving-object-indexes`, `vector-ann-indexes-beyond-edbs` | 2,377 | — |

#### Transactions & durability

| Skill | Source | What it covers | Deep-dive references | Lines | Preloaded by |
|---|---|---|---|---:|---|
| `transactions-and-recovery` | Core | Implementing or reviewing concurrency control and durability in a single-node database: locking (2PL, lock modes, intention locks, deadlocks), serializability theory, optimistic and multi-version concurrency control (MVCC, snapshot … | — | 107 | `transaction-recovery-engineer` |
| `concurrency-control-theory` | EDBS | Designing, implementing, proving or reviewing concurrency control in a database engine at expert depth: serializability theory, lock managers, B-tree key locking, MVCC, snapshot isolation, SSI, OCC, isolation-level semantics and anomaly … | `cc-performance-and-tuning`, `isolation-levels-and-anomalies`, `locking-and-btree-concurrency`, `mvcc-si-ssi`, `semantic-and-extended-transaction-models`, `serializability-theory` | 2,059 | `db-correctness-auditor`, `transaction-recovery-engineer` |
| `recovery-and-durability` | EDBS | Designing, implementing or reviewing how a database survives failures: write-ahead logging, ARIES restart (analysis/redo/undo), checkpoints, media and archive recovery, backup/PITR, snapshots, disaster recovery, replica re-join, in-doubt … | `application-recovery-and-exactly-once`, `aries-deep-dive`, `backup-pitr-and-disaster-recovery`, `checkpointing-and-main-memory-recovery`, `crash-testing-recovery-code`, `wal-and-logging-taxonomy` | 1,924 | `db-correctness-auditor`, `transaction-recovery-engineer` |

#### Scale-out

| Skill | Source | What it covers | Deep-dive references | Lines | Preloaded by |
|---|---|---|---|---:|---|
| `parallel-distributed-execution` | Core | Adding parallelism or distribution to query EXECUTION (not data replication): partitioning schemes, exchange/repartition (shuffle) operators, partition pruning, parallel and distributed joins/aggregates, query stages, streaming vs blocking … | — | 91 | `distributed-db-engineer` |
| `parallel-database-systems` | EDBS | Designing, implementing or reviewing a parallel/MPP database engine: shared-nothing vs shared-disk vs shared-memory, data placement and declustering, speedup/scaleup limits, inter-/intra-operator parallelism, broadcast vs repartition vs … | `architecture-and-scaling`, `mapreduce-and-sql-on-big-data`, `parallel-operators-join-aggregate`, `parallel-optimization-and-scheduling`, `placement-and-declustering`, `skew-taxonomy-and-mitigation` | 1,876 | `distributed-db-engineer` |
| `distributed-dbms-design` | EDBS | Designing, implementing or reviewing a classical distributed DBMS (Ozsu-Valduriez lineage): distribution transparency, federated/multidatabase architecture, fragmentation and allocation, fragment-query localization, communication-aware … | `commit-protocols-and-recovery`, `distributed-cc-and-deadlock`, `distributed-query-processing-and-semijoins`, `fragmentation-and-allocation`, `multitenancy-and-cloud` | 1,907 | `distributed-db-engineer` |
| `replication-and-consistency` | Core | Designing replication and consistency for a distributed data store: CAP tradeoffs, consistency models (linearizability, sequential, causal, eventual), session guarantees (read-your-writes, monotonic reads), quorums (R + W > N), tunable … | — | 91 | — |
| `replication-protocols` | EDBS | Designing, implementing or reviewing database replication as a protocol with a correctness criterion: eager vs lazy, primary-copy vs update-anywhere, one-copy serializability, replica control, certification over total-order broadcast … | `consistency-models-and-session-guarantees`, `geo-replication-and-clocks`, `one-copy-serializability-and-quorums`, `optimistic-replication-and-crdts`, `replication-design-space`, `si-and-group-communication-replication` | 2,319 | `distributed-db-engineer` |
| `distributed-consensus` | Core | Implementing or reasoning about agreement among distributed nodes: consensus algorithms (Paxos, Multi-Paxos, Raft), leader election, failure detection (heartbeats, phi-accrual, gossip), broadcast and atomic/total-order broadcast … | — | 95 | `distributed-db-engineer` |
| `distributed-transactions` | Core | Implementing transactions that span multiple nodes/partitions: atomic commitment (two-phase commit 2PC, three-phase commit 3PC), and the modern designs — Calvin (deterministic), Spanner (TrueTime + 2PC over Paxos), Percolator (snapshot … | — | 94 | `distributed-db-engineer` |

#### Analytical & specialised engines

| Skill | Source | What it covers | Deep-dive references | Lines | Preloaded by |
|---|---|---|---|---:|---|
| `olap-and-warehouse-engines` | EDBS | Designing, implementing or reviewing an analytical/warehouse engine: star/snowflake schemas as the optimizer sees them, hierarchies, measures and summarizability, CUBE/ROLLUP/GROUPING SETS execution, cube computation and aggregate … | `array-and-multidimensional-storage`, `column-store-engineering`, `cube-computation-and-view-selection`, `dimensional-semantics-and-summarizability`, `star-join-processing`, `warehouse-architecture-etl-and-cloud` | 2,252 | `analytics-engine-engineer` |
| `stream-processing-engines` | EDBS | Designing, implementing or reviewing a data stream management system or a streaming operator: continuous-query semantics, windows, watermarks and punctuations, out-of-order data, window joins and aggregation sharing, operator scheduling … | `complex-event-processing`, `fault-tolerance-and-exactly-once`, `scheduling-load-shedding-adaptivity`, `stream-semantics-and-cql`, `stream-synopses`, `windows-and-punctuations` | 2,516 | `analytics-engine-engineer` |
| `temporal-databases` | EDBS | Designing, implementing or reviewing temporal data support inside a database engine: valid-time, transaction-time and bitemporal tables, SQL:2011 application-time periods and system-versioned tables, sequenced/current/nonsequenced … | `schema-evolution-and-versioning`, `sql2011-temporal-and-tsql2`, `temporal-algebra-coalescing-timeslice`, `temporal-joins-and-aggregation`, `time-models-and-semantics`, `transaction-time-implementation` | 2,337 | `analytics-engine-engineer` |
| `beyond-relational-engines` | EDBS | An RDBMS engineer must design, integrate or review an adjacent engine family as a design choice relative to the relational engine: NoSQL key-value/wide-column/document stores, JSON/XML storage and indexing, XQuery processing, graph and RDF … | `graph-and-rdf-engines`, `nosql-design-space`, `object-relational-and-extensibility`, `provenance`, `semistructured-json-xml-storage-and-indexing`, `uncertain-and-probabilistic-databases` | 2,220 | — |

#### Operations & safety

| Skill | Source | What it covers | Deep-dive references | Lines | Preloaded by |
|---|---|---|---|---:|---|
| `query-engine-testing` | Core | Testing or benchmarking any database/query-engine component: unit tests for operators and optimizer rules, SQL parse tests, golden/snapshot tests (sqllogictest-style), property/fuzz testing, deterministic simulation testing for … | — | 81 | `db-correctness-auditor`, `db-performance-engineer`, `engine-dev` |
| `tuning-and-benchmarking` | EDBS | Designing, implementing or reviewing DBMS performance engineering: physical design advisors (index/MV/partition selection, what-if hypothetical indexes), online and self-tuning (feedback histograms, LEO, memory brokering, cache … | `application-schema-and-layer-tuning`, `benchmark-design-and-methodology`, `online-and-self-tuning`, `performance-models-and-monitoring`, `physical-design-advisors` | 1,875 | `db-performance-engineer` |
| `database-security-internals` | EDBS | Designing, implementing or reviewing security machinery inside a DBMS: privilege enforcement (GRANT/REVOKE, grant option, cascading revocation, RBAC, separation of duty, temporal access control), row-level security and query modification … | `auditing-intrusion-and-compliance`, `authorization-models-and-enforcement`, `encryption-and-key-management-in-engines`, `integrity-verification-and-trusted-hardware`, `mls-and-secure-concurrency-control` | 2,200 | `db-security-engineer` |

#### Literature

| Skill | Source | What it covers | Deep-dive references | Lines | Preloaded by |
|---|---|---|---|---:|---|
| `edbs-reference` | EDBS | A database-internals question needs authoritative depth beyond what a library skill states: pulling the full Encyclopedia of Database Systems (EDBS, 2nd ed.) entry on a concept, finding which of the 1,414 entries cover a topic, following … | —<br>+ `scripts/edbs.py`, `index.tsv` | 317 | `rdbms-architect`, `rdbms-professor` |

### Agents

All agents live in `global/.claude/skill-library/agents/<agent>.md` and install to a project's `.claude/agents/`. Install every skill an agent preloads.

| Agent | Model | Tools | Preloads skills | Use for |
|---|---|---|---|---|
| `analytics-engine-engineer` | opus | all (inherited) | `olap-and-warehouse-engines`, `stream-processing-engines`, `temporal-databases`, `materialized-views-ivm`, `columnar-arrow-layout` | Analytical-feature specialist. Use for OLAP/warehouse engine features (CUBE/ROLLUP/GROUPING SETS, star-join processing, column-store compression and late materialization, aggregate navigation, partition pruning), materialized aggregates, stream processing (windows, watermarks/punctuations, CEP, exactly-once), and temporal/versioned data (system-versioned tables, time travel, bitemporal queries). |
| `db-correctness-auditor` | opus | Read, Grep, Glob, Bash | `query-engine-testing`, `relational-theory`, `sql-semantics-and-active-rules`, `concurrency-control-theory`, `recovery-and-durability` | Adversarial reviewer for database-internals designs and code. Use proactively before merging or finalizing any change to the optimizer, operators, storage formats, concurrency control, recovery, replication or commit paths. It hunts for semantic bugs (NULL/bag/empty-input), isolation anomalies, crash-point and torn-write bugs, lost or duplicated rows, and untested failure paths, and it returns a ranked findings list with reproducers. |
| `db-performance-engineer` | opus | all (inherited) | `tuning-and-benchmarking`, `query-engine-testing`, `storage-devices-and-io`, `dbms-architecture` | Database performance specialist. Use for benchmark design and execution (TPC-H/DS/C, YCSB, microbenchmarks), profiling engine hot paths, diagnosing regressions, physical design/index/MV advisors, workload management (admission control, throttles, priorities), and configuration and tuning of buffer, log, concurrency and I/O. |
| `db-security-engineer` | opus | all (inherited) | `database-security-internals`, `sql-semantics-and-active-rules`, `page-and-file-format` | Database security internals specialist. Use for authorization models and their enforcement points (GRANT/REVOKE semantics, RBAC, row/column-level security, views as security), authentication, encryption at rest and in transit (page/column level, key rotation, interaction with indexes and compression), querying encrypted data, audit logging and tamper evidence, inference control, and secure engine development. |
| `distributed-db-engineer` | opus | all (inherited) | `parallel-database-systems`, `distributed-dbms-design`, `replication-protocols`, `distributed-consensus`, `distributed-transactions`, `parallel-distributed-execution` | Distributed and parallel DBMS specialist. Use for MPP/shared-nothing design, data partitioning and placement, exchange/shuffle and distributed joins, skew handling, distributed query optimization, replication protocols and consistency models, consensus (Paxos/Raft), distributed commit (2PC/3PC, Percolator/Spanner-style), geo-replication, elasticity and multitenancy. |
| `engine-dev` | inherit | all (inherited) | `query-engine-testing` | Systems-language implementer for database/query-engine internals in Rust or C/C++. Use to write or modify engine code once the design is settled (by the user or a specialist agent), always test-first and benchmark-gated, with ownership/RAII/unsafe-invariant guardrails. |
| `execution-engine-engineer` | opus | all (inherited) | `query-execution-advanced`, `join-algorithms`, `columnar-arrow-layout`, `query-plan-design`, `dbms-architecture` | Query execution specialist. Use for physical operators (joins, aggregation, sort, window functions, top-k, set ops), the operator/iterator or push-based contract, vectorized or compiled execution, memory budgets and spilling, intra-node parallelism, adaptive execution, and operator performance on modern CPUs. |
| `query-optimizer-engineer` | opus | all (inherited) | `query-optimizer`, `cardinality-and-statistics`, `relational-theory`, `materialized-views-ivm`, `sql-semantics-and-active-rules` | Optimizer and SQL-semantics specialist. Use for rewrite rules, subquery decorrelation, join ordering/enumeration, cost models, cardinality and statistics (histograms, sketches, sampling), materialized-view matching and maintenance, plan regressions, and any change whose correctness depends on algebraic equivalence under bag/NULL semantics. |
| `rdbms-architect` | opus | all (inherited) | `dbms-architecture`, `edbs-reference`, `relational-theory` | Lead database-internals architect. Use proactively for any cross-cutting RDBMS design question or feature that touches more than one engine subsystem (e.g. "add MVCC", "support recursive CTEs", "make writes survive node loss", "design a column store"), for design docs/ADRs, and to decompose work and route it to the specialist agents. |
| `rdbms-professor` | opus | Read, Grep, Glob, Bash, WebSearch, WebFetch | `edbs-reference`, `relational-theory`, `dbms-architecture` | Deep-theory and literature agent for database systems. Use to explain any database-internals concept rigorously (with proofs, examples and the history of competing approaches), to research "what is the known solution to X" in the Encyclopedia of Database Systems and the primary papers, to build reading plans and study guides, and to examine understanding with probing questions. It answers with citations; it does not write production code. |
| `storage-engine-engineer` | opus | all (inherited) | `storage-and-indexing`, `page-and-file-format`, `index-structures-catalog`, `storage-devices-and-io`, `lsm-storage` | Storage-engine specialist. Use for page and file formats, buffer pool design, B+-tree/hash/bitmap/LSM/multidimensional/vector index structures, bulk loading, compression, device-aware I/O (SSD, NVMe, RAID, object storage), checksums and torn writes, and on-disk format versioning. |
| `transaction-recovery-engineer` | opus | all (inherited) | `concurrency-control-theory`, `recovery-and-durability`, `transactions-and-recovery` | Transactions, concurrency control and recovery specialist. Use for isolation levels and anomalies, 2PL/MVCC/OCC/SI/SSI design, lock managers and deadlock handling, B-tree concurrency, WAL/ARIES, checkpoints, group commit, backup/PITR, and proving or testing that a design is serializable and crash-safe. |

### Rules

| File | Installs to | Purpose |
|---|---|---|
| `global/.claude/rules/infrastructure-access.md` | `~/.claude/rules/` (global) | Infrastructure Access Rules |
| `global/.claude/skill-library/rules/engine-internals.md` | project `.claude/rules/` (via picker) | Engine internals — project rules (installed by skill picker) |
| `global/.claude/skill-library/rules/rdbms-expert-method.md` | project `.claude/rules/` (via picker) | RDBMS expert method: how agents approach database-internals work |

### Commands

| Command | File | Purpose |
|---|---|---|
| `/fragile` | `global/.claude/commands/fragile.md` | Review Danger Zones |
| `/infra` | `global/.claude/commands/infra.md` | Infrastructure Quick Reference |
| `/new-project` | `global/.claude/commands/new-project.md` | Initialize Project with Claude Code Templates |
| `/plan` | `global/.claude/commands/plan.md` | Two-Phase Planning Workflow |
| `/research` | `global/.claude/commands/research.md` | Deep Exploration Mode |
| `/skills` | `global/.claude/commands/skills.md` | Add skills from the global library to this project |
| `/sup` | `global/.claude/commands/sup.md` | Quick Status Check |
| `/wrap` | `global/.claude/commands/wrap.md` | End of Session |

### Tools

| Tool | Purpose |
|---|---|
| `global/.claude/bin/claude-skills-init` | Interactive picker: installs chosen skills, agents and rules into a project |
| `global/.claude/skill-library/edbs-reference/scripts/edbs.py` | Search the EDBS index; print any entry from your own PDF (`EDBS_PDF`) |
| `tools/gen-inventory.py` | Regenerates this inventory (`--check` fails if it is stale) |

<!-- INVENTORY:END -->

## Startup Prompt Template

Use this pattern when starting a session:

```
Read CLAUDE.md. Read _FRAGILE.md. Read _NEXT_SESSION_MEMO.md.
Working on [TASK/RFD]. Your role: [ROLE]. Write permission: [SCOPE].
```

### Role Examples

- **Review agent**: Read-only code review
- **Testing agent**: Write only to test files
- **Security agent**: Output to SECURITY_REPORT.md only
- **Coding agent**: Full implementation access

## File Reference

### CLAUDE.md
Project-specific context. What you're building, tech stack, architecture decisions, conventions. Every agent reads this first.

### _FRAGILE.md
Document code that breaks in non-obvious ways: auth flows, payments, RLS policies, migrations. Agents must check before modifying.

### _NEXT_SESSION_MEMO.md
Handoff documentation. Updated at session end via `/wrap`. Contains completed work, in-progress items, blockers, and next steps.

### _VOCABULARY.md
Canonical terminology. Prevents confusion from inconsistent naming (e.g., "user" vs "member" vs "account").

### MEMORY.md (Global)
System-wide standards that apply to all projects. Code quality rules, git practices, security defaults.

### INFRASTRUCTURE.md (Global & Project)
Server details, connection info, credentials references. **Never store actual passwords** — use environment variable references like `$SSH_USER`.

### settings.json
Permissions and environment variables. Controls what Claude can access (allow/ask/deny rules).

### .mcp.json
MCP (Model Context Protocol) server configurations. Enables Claude to interact with external services like GitHub, databases, Docker, Kubernetes.

### rules/*.md
Modular rules files. Split large instruction sets by topic (infrastructure, security, testing, etc.).

## Infrastructure Configuration

### Security: Never Store Secrets Directly

```markdown
# WRONG - Never do this
- **Password**: `mysecretpassword123`

# CORRECT - Use environment variable references
- **Password**: `$DB_PASSWORD` (set in environment)
```

### Environment Variables

Set credentials in your shell profile (`~/.zshrc` or `~/.bashrc`):

```bash
# SSH
export DEV_SSH_USER="your-username"
export PROD_SSH_USER="your-prod-username"

# Database
export DB_USER="dbuser"
export DB_PASSWORD="from-secrets-manager"

# Cloud
export AWS_PROFILE="default"
```

### MCP Servers for Infrastructure

Enable Claude to interact with external services by configuring `.mcp.json`:

```json
{
  "mcpServers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": { "GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_TOKEN}" }
    },
    "postgres": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-postgres"],
      "env": { "DATABASE_URL": "${DATABASE_URL}" }
    }
  }
}
```

### Permission Levels in settings.json

```json
{
  "permissions": {
    "allow": ["Bash(ssh:*dev*)"],       // Auto-approved
    "ask": ["Bash(ssh:*prod*)"],         // Requires confirmation
    "deny": ["Read(.env)", "Read(~/.ssh/*)"]  // Blocked entirely
  }
}
```

## Best Practices

1. **Short prompts + comprehensive docs** beats elaborate role definitions
2. **Update _NEXT_SESSION_MEMO.md** religiously via `/wrap`
3. **Use `/fragile`** before touching auth, payments, or security code
4. **Use `/plan`** for any feature that spans multiple files
5. **Keep files under 300 lines** for reviewable diffs
6. **Single source of truth** for env vars, formatters, query keys

## Customization

Edit the template files to match your:
- Tech stack and frameworks
- Coding conventions
- Project structure
- Domain vocabulary
- Team processes
