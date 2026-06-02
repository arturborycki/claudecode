# Database / Query-Engine Internals — Claude Code Skill Library

Fourteen composable skills for building a database or query engine in
C/C++ or Rust, plus a dev-agent config. Each skill owns one box of the
engine and encodes the reference-grade detail (cost formulas, lock
matrices, Arrow invariants, consensus corner cases) that's easy to get
fuzzy on.

## Sources

- **HQEW** — *How Query Engines Work*, Andy Grove (modern columnar pipeline)
- **DBMS** — *Database Systems: The Complete Book*, 2e, Garcia-Molina/Ullman/Widom (algorithms, cost models, theory)
- **DI** — *Database Internals*, Alex Petrov (byte-level storage, LSM, distributed systems)

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
Each subdirectory is a self-contained skill (`<name>/SKILL.md`). Drop the
directories into your Claude Code `skills/` location, or package one with
the skill-creator's `package_skill.py`. The `agents/engine-dev.md` +
`CLAUDE.md` configure the systems-language dev agent that wields them.
