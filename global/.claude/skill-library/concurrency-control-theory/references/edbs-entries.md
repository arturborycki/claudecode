# EDBS entries in this skill's bundle

Pull any entry's full text with the `edbs-reference` skill:
`python3 <edbs-reference>/scripts/edbs.py show "<Entry>"`.

| Entry | Printed page | What it gives an engine builder |
|---|---|---|
| ACID Properties | p.23 | The contract split: CC owns isolation, recovery owns atomicity/durability, consistency is the application's; throughput and response time as the performance yardsticks |
| Atomicity | p.186 | All-or-nothing vs combined atomicity+isolation (PL/OS usage); limits for external side effects; retry/idempotence and exactly-once application recovery as the next step |
| B-Tree Locking | p.345 | Locks vs latches; five latching strategies for splits; B-link trees; key-value vs key-range locking, ghost records, instant next-key locks for right-edge inserts, hierarchical key/gap locking, increment locks |
| Compensating Transactions | p.528 | Definition of compensation as state equivalence (not identity) with concurrent work; when compensation is impossible |
| Concurrency Control Manager | p.574 | Role of the lock manager: access table, waits-for list, deadlock test, victim notification to the transaction and recovery managers |
| Concurrency Control: Traditional Approaches | p.575 | Scheduler model (output, block, reject); optimistic vs pessimistic, locking vs non-locking, 2PL vs non-2PL; hybrid rw/ww schedulers; why 2PL dominated |
| Correctness Criteria Beyond Serializability | p.640 | Conflict vs view equivalence, polygraphs; survey of 1SR, semantic consistency, PWSR, epsilon-SR, eventual consistency, QSR, 2LSR |
| Escrow Transactions | p.1332 | val/inf/sup bookkeeping for commuting increments with bounds; escrow log and special recovery; non-blocking long-lived and distributed reservations; IMS Fast Path lineage |
| Extended Transaction Models and the ACTA Framework | p.1428 | Characterising models by structure, commit/abort dependencies and visibility; ACTA's events, dependencies, views, conflict sets |
| Generalization of ACID Properties | p.1579 | Recovery/Consistency/Visibility/Permanence as relaxable axes; sagas, nesting and Flex as instances; delegation |
| Locking Granularity and Lock Types | p.2131 | Multi-granularity locking, IS/IX/S/SIX/X compatibility, warning-lock protocol, escalation by converting intention locks |
| Multilevel Transactions and Object-Model Transactions | p.2353 | Transaction trees per engine layer; commutativity, ordering and pruning rules (tree reducibility); layered 2PL protocol; why undo must be logical; counters and escrow inside the framework |
| Multiversion Serializability and Concurrency Control | p.2454 | Formal MV schedule with version function, view/final-state equivalence, standard serial MV schedules; MV2PL with certify locks (WAB) and its deadlock risk (its view that MVCC is rarely used is dated) |
| Nested Transaction Models | p.2485 | Moss's closed nesting: commit/abort rules, hold vs retain locks and inheritance; savepoint emulation; Argus, Camelot, Berkeley DB |
| Open Nested Transaction Models | p.2597 | Vital/non-vital/contingency/compensating/triggered subtransactions; relaxed visibility; why 2PC does not fit long-running work; WS-BusinessActivity lineage |
| Performance Analysis of Transaction Processing Systems | p.2732 | Locking contention model (Pc, Pw, deadlock probability), wait-chain analysis and the thrashing threshold, restart-oriented policies (RP, WDL, cautious waiting), OCC kill/die and two-phase processing; also queueing/RAID background outside this skill's scope |
| Real-Time Transaction Processing | p.3114 | Hard/firm/soft deadlines, temporal consistency (absolute/relative validity), 2PL-HP, OCC priority-wait, PROMPT commit with lending |
| Sagas | p.3273 | Saga definition and guarantee (all steps or prefix plus compensations); semantic atomicity; application-defined compensation |
| Scheduler | p.3281 | Workflow-engine scheduler definition only; not relevant to transaction scheduling (skipped) |
| Semantic Atomicity | p.3381 | Formal compensation requirement, dirty reads allowed if compensable; transaction classes; NT/PV predicates; O2PC; compensation must not fail and must be resumable; contrast with savepoints |
| Semantics-Based Concurrency Control | p.3435 | Commutativity by arguments and return values; recoverability relation with dynamic commit dependencies (stack push example); deriving compatibility tables from ADT specs |
| Serializability | p.3475 | One-copy serializability for ROWA replicated databases via union of local serialization graphs; when view equivalence is needed (failures, quorums) |
| Serializable Snapshot Isolation | p.3476 | History (Cahill, Ports-Grittner, PSSI, SSN, Lomet); MVSG edge kinds; detecting rw edges on read vs on write via SIREAD; in/out conflict lists and pivot abort; PostgreSQL usage |
| Snapshot Isolation | p.3513 | Snapshot read and first-committer-wins rules; prevented anomalies; write skew; vulnerable edges and the two-consecutive-edge theorem; static dependency graph; materialise/promotion fixes; product usage |
| Software Transactional Memory | p.3543 | STM as ACI without D, motivation versus mutexes; brief |
| Split Transactions | p.3665 | Split and join operations with declared read/write sets for open-ended activities; split-commit, suspend, accept-join |
| SQL Isolation Levels | p.3681 | P1–P3 phenomena and the four ANSI levels; per-transaction level choice; RC vs serializable throughput gap; pointer to the Berenson critique |
| Transaction | p.4186 | Transaction as delegation of concurrency/failure handling to the system; page vs object model; brief |
| Transaction Chopping | p.4187 | Pieces, rollback-safety, chopping graph with S and C edges, SC-cycle theorem; hot-spot motivation; extension to SI and RC |
| Transaction Management | p.4189 | Lost-update and partial-failure motivating examples; CC and recovery tied to any engine layer; overview |
| Transaction Models: The Read/Write Approach | p.4194 | Formal page model: transactions, histories vs schedules, Herbrand semantics, conflict serializability, commutativity rules and reducibility, inverse writes for aborts |
| Tuning Concurrency Control | p.4252 | Counter hot spots and system sequences (gaps), "living dangerously" with user interaction outside transactions, rules of thumb, value-of-serializability and counter experiments |
| Two-Phase Locking | p.4270 | Locked transactions, LUL condition, 2PL rule and lock-point proof, optimality and strictness argument, strict 2PL, read/write lock conditions, deadlocks, phantoms; ordered sharing and altruistic locking |

Entries judged weak or irrelevant for this skill: **Scheduler** (p.3281) is
about workflow scheduling, unrelated to transaction schedulers. **Transaction**
(p.4186), **Software Transactional Memory** (p.3543) and **Concurrency Control
Manager** (p.574) are short overviews with little algorithmic content.
**Generalization of ACID Properties** (p.1579) largely repeats the extended
models entries. The queueing, buffer-miss and RAID sections of **Performance
Analysis of Transaction Processing Systems** (p.2732) belong to
`storage-devices-and-io` / `tuning-and-benchmarking`; only its CC analysis is
used here. Several bundle entries begin or end with fragments of neighbouring
entries (audio, nested loop join, digital libraries, temporal SQL,
tuple-generating dependencies); those fragments were ignored.
