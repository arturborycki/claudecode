# RDBMS expert method: how agents approach database-internals work

Installed alongside `engine-internals.md`. That file sets the hard rules;
this one sets the *way of thinking* the agent team applies to every
internals task.

## 1. Contracts before mechanisms
State the observable contract first: SQL result semantics (bag + 3VL),
isolation level as phenomena prevented, durability point, failure model,
and latency/throughput targets. Mechanisms are chosen *against* a contract;
a mechanism without one can't be reviewed.

## 2. Literature before invention
Classic problems have named solution families with known trade-offs. Before
designing, run `edbs-reference` `search` for the problem and read the
matching library skill. A novel design must say which known approach it
departs from and why.

## 3. Invariants are the design
Every subsystem change lists its invariants as numbered, testable statements
(e.g. "redo is idempotent via pageLSN", "GC never removes a version visible
to an active snapshot", "a rewrite preserves bag semantics given key K").
Each invariant names how it is enforced (assertion, type, protocol step)
and how it is tested.

## 4. Two designs minimum
Compare at least two options in a trade-off table: correctness argument,
cost model, concurrency impact, recovery interaction, operational
complexity, failure behaviour. Record why the loser lost.

## 5. Adversarial inputs are the spec
NULLs, duplicates, empty inputs, skew (one key = 50% of rows), larger-than-
memory, concurrent conflicting writers, crash at every write/fsync boundary,
network partitions, clock skew. If the test plan doesn't name them, it
isn't finished.

## 6. Independent review
Designs and code that touch the optimizer, storage format, concurrency
control, recovery, replication or commit go to `db-correctness-auditor`
before they are called done. Performance claims go through
`db-performance-engineer` methodology (repeated runs, intervals, mechanism
explanation).

## 7. Cite and date
Design docs cite EDBS 2e entries (`"<Entry>", p.<printed page>`) and the
primary papers. Mark anything that depends on post-2018 practice or on a
specific system version, and verify it against current documentation.

## Agent team
`rdbms-architect` (lead, routes work) · `query-optimizer-engineer` ·
`execution-engine-engineer` · `storage-engine-engineer` ·
`transaction-recovery-engineer` · `distributed-db-engineer` ·
`analytics-engine-engineer` · `db-security-engineer` ·
`db-performance-engineer` · `db-correctness-auditor` (independent review) ·
`rdbms-professor` (theory, literature, teaching) · `engine-dev` (implementation).
