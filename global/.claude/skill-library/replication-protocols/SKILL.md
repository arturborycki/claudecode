---
name: replication-protocols
description: "Use when designing, implementing or reviewing database replication as a protocol with a correctness criterion: eager vs lazy, primary-copy vs update-anywhere, one-copy serializability, replica control, certification over total-order broadcast, 1-copy SI/GSI, Paxos-replicated logs, quorum systems, session guarantees, CRDT/conflict resolution, geo-replication and clocks. Triggers on 1SR, one-copy serializability, ROWA, ROWAA, available copies, quorum consensus, weighted voting, grid quorum, deferred update, certification, writeset, abcast, Postgres-R, Galera, Ganymed, GSI, PSI, Walter, COPS, causal+, read-your-writes, monotonic reads, version vector, last-writer-wins, OR-Set, multi-Paxos, Paxos Commit, 1-safe/2-safe, failover, TrueTime, HLC, PACELC, replica freshness. Apply even when phrased as 'add read replicas', 'multi-master', 'active-active', 'make writes survive a region outage', or 'why did my replica lose an update'."
---

# Replication Protocols

Owns the replica-control layer of a DBMS: how logical reads/writes map to
physical copies, how replicas agree on an order, and which single-copy
illusion (if any) clients get. The single most important idea: **a
replication protocol is only defined together with its correctness
criterion** (1SR, strict 1SR, 1-copy SI, GSI, PSI, causal+, eventual) —
"replicated" without a criterion is not a spec, and most production bugs
are an unstated criterion silently weaker than what users assume.

## Mental model

- Two axes (Gray et al. 1996): **when** replicas coordinate (eager = before
  commit; lazy = after) x **where** updates run (primary copy vs update
  anywhere). Two more decide cost: **symmetric** (every replica executes)
  vs **asymmetric** (one executes, others install a writeset), and
  coordination **per operation** vs **per transaction**.
- Update-anywhere on fully replicated data does not scale writes: waits,
  deadlocks or reconciliations grow ~N^3 in Gray's model, and even ideal
  asymmetric full replication caps at `1/(w·wo)` scale-out. Scale writes by
  partitioning, then replicate each partition 3–5x.
- Modern strong replication = **order first, decide locally**: a total
  order (atomic broadcast or a consensus log) fixes the sequence of commit
  requests; each replica runs the same deterministic certification, so no
  2PC among replicas and no distributed deadlock.
- Weak replication = **decide locally, order later (or never)**: updates
  commit at one replica and propagate; conflicts are prevented by a
  primary, merged by commutativity/CRDTs, or reconciled after the fact.
- Correctness lives in replicated histories and their equivalence to a
  one-copy execution; once writes can skip copies, conflict equivalence on
  copies is not enough — you need versions and view equivalence.

## Core invariants

1. **Single-copy equivalence (strong modes):** every committed replicated
   history is equivalent to a serial (1SR) or SI (1-copy SI) execution on
   one logical copy; checkable by building the 1-copy serialization graph
   (with write-order and read-order edges) from a recorded history.
2. **Writer serialization:** concurrent writers of the same item are
   ordered by one mechanism (lock at a quorum intersection, ballot,
   leader, or total-order sequence) — never just by computing `max+1`
   versions independently.
3. **Read freshness by intersection:** a read promised to be current
   touches a read quorum intersecting every write quorum, or a leader whose
   leadership is confirmed (round trip, or lease with a stated clock bound).
4. **Deterministic decision:** in total-order protocols, certification
   depends only on the delivered sequence and message content (no local
   time, lock state, or apply progress); all replicas reach identical
   commit/abort for every transaction.
5. **Prefix snapshots:** a replica never exposes a state that is not a
   prefix of the agreed update order (prevents the indirect-dependency
   anomaly where two read-only transactions see non-conflicting updates in
   opposite orders), unless the model explicitly allows it (PSI long fork).
6. **No acknowledged commit is lost** at the promised safety level: 2-safe
   / quorum modes survive loss of the primary; 1-safe modes report the
   loss window. Uniform delivery (or delayed ack) is required before
   acknowledging a commit decided by group delivery.
7. **Exactly one writer epoch:** after failover, the old primary is fenced
   (epoch/term checked on every write, lease expiry) before the new one
   accepts writes; a partition minority cannot commit.
8. **Recovering copies are unreadable until caught up**; state transfer
   covers every transaction exactly once (snapshot or subsequent stream).
9. **Convergence (weak modes):** replicas that have received the same set
   of updates are in equivalent states (SEC); merge is associative,
   commutative, idempotent, and mutators are inflationary — property-test
   these laws.
10. **Session guarantees as stated:** if RYW/MR/MW/WFR are promised, a
    read is served only by a replica whose applied version vector (or LSN)
    dominates the session's token.

## Design space & trade-offs

| Option | When it wins | Cost / risk |
|---|---|---|
| Eager primary copy (sync log shipping, quorum-sync standby) | HA for one OLTP DB; simple 1SR | Primary is the write ceiling; failover needs fencing and in-doubt resolution |
| Lazy primary copy + read replicas | Read scale-out with tolerable staleness | Stale reads, RYW violations, 1-safe loss window |
| Eager update-anywhere via distributed 2PL + 2PC | Never, beyond textbooks | Per-op messages, distributed deadlocks on a single item, blocking 2PC |
| Certification over total-order broadcast (deferred update), 1-copy SI | Cluster, read-heavy with moderate writes, strong consistency | Write skew under SI; certifier/GCS throughput; ordered commit defeats group commit |
| Serializable certification (readsets or SSI-style checks) | Need 1SR on a cluster | Readset capture for SQL predicates; higher abort rate |
| Consensus log per partition (Multi-Paxos/Raft) + commit across partitions | Strong consistency with partition tolerance, geo or cluster | ≥1 quorum RTT per commit; leader hot spot; cross-partition 2PC |
| Quorum read/write (Dynamo-style R/W) | Write availability, tunable latency | Not linearizable without writer serialization and read write-back; sloppy quorums break intersection; collection queries need full quorum fetch |
| Causal+ / PSI / CRDT geo-replication | Low latency, always-writable regions | Concurrent-update semantics must be designed per type; invariants (uniqueness, non-negativity) need coordination or escrow |
| LWW multi-master | Only when losing concurrent writes is acceptable | Clock skew silently discards later writes; tombstone GC resurrection |

## Algorithms that matter

**Deferred update with certification** (one abcast per update txn):
```
execute T at delegate on snapshot; read-only -> commit locally
else abcast(T.start_seq, WS(T) [, RS(T)], updates)
on deliver(T) in order at every replica:
  CC = txns certified after T.start_seq
  SI : commit iff ∀T'∈CC: WS(T)∩WS(T')=∅
  SER: commit iff ∀T'∈CC: RS(T)∩WS(T')=∅
  commit -> apply writeset in delivery order (abort local conflicting txns)
```
Cost: 1 total-order broadcast + O(|WS|) hash probes; read-only transactions
are free. Details: `references/si-and-group-communication-replication.md`.

**Quorum consensus with versions** (Gifford/Thomas): votes `v_i`, total
`V`; require `r + w > V` and `2w > V`; read = max version over a read
quorum; write = serialize at the intersection, install `max+1` at a write
quorum. Load lower bound `max(1/c, c/n) ≥ 1/√n`; majority load ≈ 1/2.
Details: `references/one-copy-serializability-and-quorums.md`.

**Available copies** (ROWAA made 1SR for crash-only failures): at commit,
validate that every accessed copy is still up and every skipped copy is
still down; recovering copies are write-only until refreshed. Unsafe under
partitions.

**Multi-Paxos log**: stable leader runs Phase 1 once for all slots ≥ k,
then one Phase 2 per slot/batch; a new leader re-proposes any value voted
in unchosen slots and fills gaps with no-ops; apply strictly in slot
order. 3 message delays per commit in the common case.

**Session guarantees**: client keeps `read_vv`, `write_vv`; serve a read
only where `applied_vv ≥ need`; accept a write only if `applied_vv ≥
write_vv ⊔ read_vv`. **Scale-out bound** (asymmetric, `r` copies, write
fraction `w`, install cost `wo`): `n / (1 + w·wo·(r−1))`.

**Commit wait**: choose `s ≥ now.latest`, release when `now.earliest > s`
(~2ε); **HLC** `(l, c)` gives causality-respecting timestamps near physical
time. Details: `references/geo-replication-and-clocks.md`.

## Failure modes & classic bugs

- **Split brain**: backup promotes on a partition while the old primary still writes. Detect overlapping epochs in logs; prevent with quorum election + fencing tokens.
- **Lost acknowledged commit**: non-uniform delivery, 1-safe shipping, or a new Paxos leader not re-proposing voted-but-unchosen entries.
- **ROWAA without validation**: two transactions each write the copy the other did not read → logically cyclic, physically conflict-free history.
- **Quorum store returns old value after new**: no read write-back, or concurrent writers both computing `max+1`.
- **Indirect dependency / long fork**: non-conflicting updates applied in different orders; read-only transactions see incompatible states.
- **Certifier GC by local time**: long transaction certified against an incomplete conflict set → lost update.
- **Statement-replication non-determinism**: `NOW()`, `RAND()`, sequences, unordered `LIMIT`, triggers → permanent divergence.
- **Apply blocked by local lock**: certified writeset waits on a local row lock → stall/deadlock against the total order.
- **Stale-replica RYW violation**: commit acked at primary/delegate, next read routed to a lagging replica.
- **LWW skew loss / tombstone resurrection**: fast clock wins; tombstone GC'd before every replica saw it.
- **CRDT metadata explosion**: tombstones/vector entries never collected; retired replica ids reused.
- **Lease reads after a GC pause**: old leader serves reads after its lease expired in real time.

## Implementation checklist (C/C++/Rust)

- Version every copy: `(value, version | (hlc, node_id) | log_index)`;
  make the version total-order key explicit in the type.
- Writesets as sorted vectors of canonical key hashes + row images;
  certifier index `HashMap<KeyHash, commit_seq>` with GC frontier =
  min over replicas of oldest active snapshot (gossiped, persisted).
- Single-threaded deterministic apply loop per replica (or a
  dependency-aware parallel applier that preserves conflict order and only
  publishes prefix snapshots); commit sequence persisted atomically with
  the data change.
- Persist Paxos/Raft acceptor state (`promised`, `voted`) and replication
  epochs with fsync before replying; check epoch on every append.
- Client tokens: return commit LSN/sequence or a version vector with each
  write; propagate it on the next request; replicas wait (bounded) or
  redirect.
- Failover: global transaction ids so the driver can resolve in-doubt
  commits; never auto-retry non-idempotent transactions blindly.
- Separate protocol state machines from I/O so deterministic simulation can
  inject drops, duplicates, reorders, partitions, crashes and clock skew.
- CRDT/merge code is pure and versioned; Rust: encode lattice laws in a
  trait and test with `proptest`; C++: same with rapidcheck.

## How to test it

- **History checkers**: record client-observed histories under fault
  injection; check linearizability (Knossos/Porcupine) for single-key
  ops, isolation anomalies (Elle-style cycle detection) for transactions,
  session guarantees with per-session vector checks.
- **Oracles**: 1-copy reference execution in the recorded serial order;
  replica state digests (Merkle) must match at equal applied positions.
- **Adversarial cases**: crash delegate after local commit before ack;
  crash leader after Phase 2 on a minority; partition primary from backup
  and clients separately; recover a replica during heavy writes; skew one
  clock by +5 s; reorder/duplicate CRDT messages; long-running transaction
  across certifier GC.
- **Canaries**: write-skew pair (documents SI vs 1SR); RYW across replicas;
  concurrent increment under LWW (must lose updates — proves you know it).
- **Model checking**: TLA+/P specs for the commit and failover paths;
  property tests for merge laws and certification determinism.

## Expert review questions

1. What is the correctness criterion, stated as a history property, for
   update transactions and separately for read-only transactions?
2. Where is the serialization point for concurrent writers of one item,
   and what happens to it during failover?
3. Is the guarantee strict (real-time) or does 1SR permit a client to see
   its committed write "undone" on a replica? Are session guarantees
   promised?
4. Which component's log is authoritative after a total cluster crash, and
   how is the longest committed prefix determined?
5. Symmetric or asymmetric? What is `wo`, and what does the scale-out
   formula predict at the target node count and write fraction?
6. How is the old primary fenced? What prevents a minority partition from
   committing?
7. Under total order, is delivery uniform before the client is acked?
8. How does the certifier garbage-collect, and what is the oldest snapshot
   it can still certify correctly?
9. Can two replicas ever expose snapshots that are not prefixes of the same
   order? Is that allowed by the stated model?
10. For quorum reads: do concurrent writers get serialized, and do reads
    write back before returning?
11. Which concurrent-update semantics per data type (LWW, siblings, CRDT,
    abort)? Which invariants require coordination or escrow?
12. What clock assumptions exist (leases, LWW, commit wait), how are they
    enforced, and what breaks if a node's clock is off by 10 s?
13. How is a new or recovering replica integrated online without missing or
    double-applying a transaction?
14. What happens to in-flight transactions at failover, and how does the
    client learn the outcome of an in-doubt commit?

## Go deeper

- `references/replication-design-space.md` — Gray taxonomy, dangers model, scale-out arithmetic, replica-control phases, kernel vs middleware, statement vs writeset, primary-backup failover, provisioning, multi-tier. Read first for architecture choices.
- `references/one-copy-serializability-and-quorums.md` — replicated histories, conflict vs view equivalence, 1-SG, ROWA/ROWAA/available copies, quorum families, load/availability, replicated 2PL/OCC. Read when proving correctness or sizing quorums.
- `references/si-and-group-communication-replication.md` — GCS primitives, deferred update/certification, 1-copy SI/GSI, Ganymed/Tashkent/Galera, Multi-Paxos as ordering layer, Paxos Commit. Read when building cluster replication.
- `references/consistency-models-and-session-guarantees.md` — model hierarchy, formal eventual consistency, session guarantees, HATs, CAP/PACELC, freshness metrics. Read when specifying promises.
- `references/optimistic-replication-and-crdts.md` — version vectors, LWW pitfalls, Bayou, OT TP1/TP2, CRDT laws and catalogue, OR-Set, invariants. Read for multi-master/offline merges.
- `references/geo-replication-and-clocks.md` — WAN protocol classes, Spanner, MDCC, Replicated Commit, Walter/PSI, COPS/Eiger, coordination avoidance, edge caching, TrueTime, HLC. Read for multi-region designs.
- `references/edbs-entries.md` — all 29 EDBS entries with printed pages.

## Related skills

- `replication-and-consistency` — general view (anti-entropy, Merkle, gossip, tunable quorums); this skill is DB protocol depth.
- `distributed-consensus` — Paxos/Raft internals and leader election; used here as the ordering layer.
- `distributed-transactions` — 2PC/Spanner/Calvin across partitions; here: agreement among copies.
- `concurrency-control-theory` — serializability, SI/SSI, MVCC that replicated CC extends.
- `recovery-and-durability`, `transactions-and-recovery` — WAL, group commit, log shipping, per-replica recovery.
- `distributed-dbms-design` — fragmentation/allocation deciding replication degree; `parallel-database-systems`, `parallel-distributed-execution` — partitioned execution, online recovery.
- `materialized-views-ivm` (views as replicas), `temporal-databases` (clocks, timestamps), `tuning-and-benchmarking` (lag, aborts, scale-out), `dbms-architecture`, `database-security-internals` (Byzantine replicas), `stream-processing-engines` (CDC feeds).

## Grounding

EDBS (Liu & Özsu, 2nd ed., 2018), 29 entries — full table in
`references/edbs-entries.md`. Core: Concurrency Control for Replicated
Databases p.566; One-Copy-Serializability p.2555; Replica Control p.3161;
Quorum Systems p.3064; Replication Based on Group Communication p.3177;
Replication Based on Paxos p.3184; Replication with Snapshot Isolation
p.3207; Strong/Weak Consistency Models for Replicated Data p.3809/p.4595;
Consistency Models for Replicated Data p.582; Causal Consistency p.406;
Eventual Consistency p.1403; CAP Theorem p.395; Optimistic Replication and
Resolution p.2612; Replicated Data Types p.3171; Replica Freshness p.3168;
Multi-data Center Replication Protocols p.2314; Multi-datacenter
Consistency Properties p.2320; Replication for Availability and Fault
Tolerance p.3187; Replication for Scalability p.3194; Partial Replication
p.2685; Middleware Support for Database Replication and Caching p.2257;
Data Replication p.833; WAN Data Replication p.4584; Physical Clock p.2758.

Seminal: Bernstein-Hadzilacos-Goodman 1987; Gifford SOSP 1979; Thomas TODS
1979; Gray et al. SIGMOD 1996; Kemme & Alonso VLDB 2000; Pedone et al. 2003
(DBSM); Lin et al. SIGMOD 2005; Elnikety et al. SRDS 2005 (GSI); Lamport
TOCS 1998; Gray & Lamport TODS 2006 (Paxos Commit); Terry et al. PDIS 1994;
Shapiro et al. SSS 2011; Corbett et al. OSDI 2012; Sovran et al. SOSP 2011;
Lloyd et al. SOSP 2011; Kraska et al. EuroSys 2013; Bailis et al. VLDB
2014/2015; Abadi 2012; Kulkarni et al. 2014 (HLC).
