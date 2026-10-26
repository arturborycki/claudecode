# EDBS entries in the recovery-and-durability cluster

Pull any entry in full with the `edbs-reference` skill:
`python3 <edbs-reference>/scripts/edbs.py show "<Entry>"`.

| Entry | Printed page | What it gives an engine builder |
|---|---|---|
| Application Recovery | p.123 | Exactly-once execution for applications: soft vs hard failures, TP-monitor steps, piecewise determinism, checkpoint + logged non-determinism vs replication, committed interaction contract (sender/receiver duties), logless component optimisations, cold/warm/hot standby. |
| Atomicity | p.186 | All-or-nothing as the contract recovery implements; atomicity vs isolation; why atomicity does not mask failures (ambiguous return codes, retry and idempotence); pointer to open nested transactions and exactly-once extensions. |
| Backup and Restore | p.251 | Short glossary entry (fragment in bundle): purposes of backup (hardware loss, disaster, operator error, malicious change) and incremental/differential definitions — note its naming is inverted relative to common industry usage. |
| Checksum and Cyclic Redundancy Check Mechanism | p.423 | Checksum vs CRC, polynomial-division construction, burst-error detection up to generator degree; basis for page and log-record integrity checks. |
| Continuous Data Protection | p.613 | Capture every storage change so any past instant can be restored; restorable-object granularity from crash-consistent images to logical objects. |
| Crash Recovery | p.660 | Core taxonomy: transaction-consistent goal, why crash recovery cannot roll forward, logical vs physical vs physiological logging and their consistency preconditions, the three log-forcing rules, steal/force four-class taxonomy, checkpoint need, fuzzy and incremental dumps, archive log generations, NVRAM and redo-only fast-restart directions. |
| Disaster Recovery | p.1121 | Definition of DR as restoring data, access and processing at a redundant site after data-centre loss; replication at DB, file-system or storage level (fragment in bundle). |
| Distributed Recovery | p.1212 | Per-site WAL plus logging of 2PC state transitions; coordinator and participant restart case analysis; termination protocol; low-overhead alternatives (agent-based replay, remote in-memory redundant logging, HARBOR log-less recovery from replicas). |
| Logging and Recovery | p.2133 | Overview of failure classes (transaction, system, media, disaster) and the components involved (DB buffer, log buffer, log file, archive copy, archive log); RAID does not replace archive recovery; log shipping for DR. |
| Logging/Recovery Subsystem | p.2135 | Role split between log manager, recovery manager and resource managers (opaque log records); online vs archive log; WAL and commit statements; a pre-ARIES backward-undo-then-forward-redo restart sequence. |
| Main Memory DBMS | p.2164 | How in-memory engines get ACID durability: journal logging + recovery, NVRAM, replication with failover; CPU/cache-oriented design; reading list includes DeWitt et al. 1984, Dalí, ClustRa. |
| Middleware Support for Precise Failure Semantics | p.2264 | x-ability: exactly-once correctness for replicated services via history reduction over idempotent and undoable actions; client/service requirements R1–R5; e-transactions for three-tier systems. |
| Multilevel Recovery and the ARIES Algorithm | p.2344 | Why fine-grained locking breaks page-level recovery; requirements (operation atomicity, high-level undo, testability, efficient redo); repeating history; CLRs with backward pointers; nested crash handling; media recovery speed; worked log example. |
| Online Recovery in Parallel Database Systems | p.2564 | Re-integrating replicas without stopping: five phases, recovery locks, multi-round transfer, log-based transfer with end-of-recovery handshake (conflict classes), historical-query catch-up, Byzantine and proactive recovery, performability metric. |
| Point-in-Time Copy | p.2769 | Definition of PiT copy/snapshot, typically taken while the application quiesces for consistency (fragment in bundle). |
| Replication for Availability and Fault Tolerance | p.3187 | Primary-backup architecture, 1-safe vs 2-safe propagation and what each loses, hot/cold standby, failover with driver-side outcome inquiry, replica recovery data-transfer strategies, partitions, quorums, Paxos, lazy replication with persistent queues. |
| Write Once Read Many | p.4732 | Physical vs logical WORM storage for retention and tamper resistance of archives. |

## Entries judged thin

- Backup and Restore, Disaster Recovery, Point-in-Time Copy: the bundle holds
  only definition fragments; the skill supplements them from standard
  practice (marked as such).
- Atomicity: mostly conceptual; used for framing and the retry/idempotence point.
- Write Once Read Many: peripheral to engine internals; kept for archive
  immutability.
