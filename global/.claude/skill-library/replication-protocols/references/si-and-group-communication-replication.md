# Total-order replication: group communication, certification, snapshot isolation, Paxos

Read this when building or reviewing eager update-anywhere or primary-copy
replication on a cluster (Postgres-R / Galera / Group-Replication style),
when defining 1-copy SI vs GSI vs strong-session SI, or when using a
Paxos/Raft log as the ordering layer under a database.

---

## 1. Why total order changes everything

State-machine replication (Lamport 1978; Schneider 1990) needs two
properties:

- **Agreement**: every non-faulty replica receives every request.
- **Order**: every non-faulty replica processes requests in the same order.

Plus **determinism** of each replica given the same input sequence.

The 1990s observation (Schiper & Raynal) was that transactional properties
map onto group-communication properties: isolation ≈ ordering, atomicity ≈
agreement. If a group-communication system (GCS) delivers commit requests
in a total order, every replica can decide each transaction's fate locally
and identically (*non-voting termination*): no 2PC, no distributed
deadlock.

---

## 2. Group communication primitives

| Primitive | Guarantee |
|---|---|
| Reliable multicast | Agreement: if one correct member delivers `m`, all correct members do. |
| FIFO | Messages from one sender delivered in send order. |
| Total order (atomic broadcast, `abcast`) | All correct members deliver all messages in the same order, regardless of sender. FIFO is not implied (a sender's `m` then `m'` may be delivered `m'` first, as long as everyone agrees) — use FIFO-total if you need both. |
| Uniform delivery | Agreement also covers members that crash right after delivering — essential when delivery triggers a durable commit. |
| Views (dynamic groups) | Membership is a sequence of views `v0, v1, ...`; a new view is installed on suspected crash or join. |
| Sending-view delivery (virtual synchrony, `vscast`) | A message multicast in view `v_i` is delivered in `v_i` (before `v_{i+1}` is installed) by all members that survive into `v_{i+1}`. |
| State transfer | A recovering/joining member receives the state it missed before resuming; defined relative to a view change. |

Atomic broadcast is equivalent to consensus (so it inherits FLP: safety
always, liveness under partial synchrony). Implementations: sequencer-based,
token ring, Paxos-based (Ring Paxos, Multi-Paxos log, XCom in MySQL Group
Replication).

**Uniformity is not optional for databases.** With non-uniform delivery a
replica can deliver a writeset, commit it, acknowledge the client, and
crash, while the survivors never deliver it: an acknowledged commit is
lost. Either require uniform total order, or delay the client
acknowledgement until delivery is known stable.

---

## 3. The functional model and the main protocol families

Phases (Wiesmann et al. 2000): (1) client request, (2) server coordination,
(3) execution, (4) agreement coordination, (5) client response.

| Family | Phase use | Notes |
|---|---|---|
| Distributed 2PL over abcast | 1–3,5 repeated per operation; no phase 4 | abcast lock requests → consistent lock grant order; per-op cost; whole stored procedures can be abcast once and executed deterministically (Middle-R, Amir & Tutu). |
| Active replication (symmetric) | 1, 2 (abcast request), 3 at all, 5 | Requires determinism of the whole transaction (multi-threaded engines need a deterministic scheduler). |
| Eager primary copy over `vscast` | 1, 3 at primary, 4 (`vscast` redo to secondaries), 5 | FIFO keeps the primary's update order; sending-view delivery makes primary failover clean (updates from a dead primary are delivered-or-not consistently before the new primary's updates). |
| **Deferred update / certification** | 1, 3 at one replica, 4 (abcast + certify), 5 | The dominant family. One abcast per update transaction; read-only transactions are local. |

---

## 4. Deferred-update (certification-based) replication

### 4.1 Protocol skeleton

```
on client txn T at replica R (its "delegate"):
   execute T locally against a snapshot (SI) or with local locks (SER)
   if T is read-only: commit locally, reply            -- no coordination
   else: abcast(T.id, T.start_ts, T.readset?, T.writeset, T.updates)

on deliver(T) at every replica, in delivery order:
   if certify(T): apply T.updates (if not delegate), commit; commit_ts = next
   else:          abort (delegate rolls back local execution)
   delegate replies to client after its local decision
```

`CC(T)` = transactions certified (committed) after `T` started and before
`T` is certified. With total order and a deterministic `certify`, every
replica computes the same `CC(T)` and the same decision.

| Criterion | Certification test |
|---|---|
| Serializability (DBSM, Pedone et al.) | `∀ T' ∈ CC(T): RS(T) ∩ WS(T') = ∅` — needs readsets |
| Snapshot isolation (first-committer-wins) | `∀ T' ∈ CC(T): WS(T) ∩ WS(T') = ∅` — writesets only |

SER without shipping readsets is possible with an extra round (Kemme &
Alonso): broadcast only the writeset; on delivery the delegate acquires
write locks, aborts conflicting *local* readers (if they have not been
broadcast yet; otherwise it broadcasts an abort), then broadcasts a commit
message.

### 4.2 Certifier state and its invariants

The certifier keeps recently committed writesets indexed by item, each
tagged with its commit sequence number.

- C1 (determinism): `certify` depends only on the delivered sequence and
  the message contents — never on local timing, local lock state, wall
  clock, or apply progress.
- C2 (garbage collection): a writeset may be dropped once every replica's
  oldest active snapshot is newer than its commit number; otherwise a
  long-running transaction is certified against an incomplete `CC(T)`. A
  common bug is GC by local time or local snapshot only.
- C3 (key canonicalization): writesets are compared on primary keys (or a
  stable row identity) normalized identically everywhere — including
  unique secondary keys if you need to catch duplicate-key races, and
  foreign-key parent rows if you need referential integrity across
  concurrent transactions.
- C4 (apply order): commits are applied at each replica in certification
  order, *or* in any order that preserves the order of conflicting
  writesets **and** never exposes a snapshot that is not a prefix of the
  global order (otherwise you reintroduce the indirect-dependency anomaly).

### 4.3 Local conflicts on the delegate and remote apply

On a replica, an incoming certified writeset may conflict with a *local*
transaction still executing (holding row locks, not yet broadcast).
The certified one must win: abort the local transaction (it would fail
certification anyway under SI). Never let a local lock block the apply of
a certified writeset — that is a distributed deadlock between the GCS
order and the local lock manager.

### 4.4 Durability and ordered commit

Committing in global order at each replica serializes commit and defeats
group commit (each commit waits for its predecessor's fsync). Tashkent
(Elnikety, Dropsho, Pedone 2006) "unites durability with ordering":
either make the middleware certifier's log the durable record (replicas
may then commit without synchronous flush), or pass the global order down
to the engine so it can group-commit a batch in that order. In any design,
state explicitly which component's log is authoritative after a full
cluster crash.

> **Beyond EDBS:** Galera Cluster and MySQL Group Replication are
> production descendants of this design: row writesets keyed by primary
> key are totally ordered by a group-communication layer (Galera's own
> GCS; XCom, a Paxos variant, in Group Replication), certified with a
> first-committer-wins rule, and applied asynchronously ("virtually
> synchronous"). Both expose the expected SI-family anomaly (write skew)
> and the expected operational issues: large transactions stall the total
> order, hot rows cause certification-failure storms, and reads on a
> replica can lag the commit acknowledgement unless a causality/"wait for
> applied" read option is used.

---

## 5. Snapshot-isolation-based replication

### 5.1 Centralized SI recap

A transaction reads the most recent committed state as of its start;
writes are buffered as new versions; two concurrent transactions (neither
committed before the other started) may not both commit if their
writesets intersect (first-committer-wins / first-updater-wins). SI
permits write skew and read-only anomalies; it forbids lost updates,
dirty/non-repeatable reads, and phantoms in the read snapshot.

### 5.2 Replicated variants

| Model | Snapshot a transaction may read | Session/real-time guarantee | Typical implementation |
|---|---|---|---|
| **1-copy SI** (Lin, Kemme et al.) | The latest snapshot committed *at its local site* when it starts; the execution must equal some centralized SI execution | implicit only at the local site | Certification over abcast (Postgres-R(SI), SRCA middleware) |
| **Conventional/strong SI** | The globally latest committed snapshot | external consistency (real time) | Expensive: needs a global commit order and up-to-date local replica or waiting |
| **GSI** (Elnikety, Zwaenepoel, Pedone 2005) | Any committed snapshot that is a prefix of the global order (possibly older) | none | Lazy-ish: replicas lag; certification still uses the global order |
| **Strong session SI** (Daudjee & Salem 2006) | Any prefix snapshot, but not older than the commit of the session's previous transaction | per-session | Lazy primary copy + session tagging |
| **PSI** (Walter) | Site-local snapshot; sites may order non-conflicting transactions differently | causal across sites | Preferred sites + vector timestamps; see `geo-replication-and-clocks.md` |

Key facts:

- Workloads that are serializable under centralized SI (e.g., TPC-C,
  TPC-W) remain serializable under GSI.
- SI anomalies carry over: 1-copy SI permits write skew. Serializable
  replicated SI requires extra detection — e.g., the SSI-style
  dangerous-structure check (Bornea et al. ICDE 2011: 1SR with SI "under
  the hood"; Jung et al. VLDB 2011) — which needs readsets or read
  summaries at the certifier.
- Read-only transactions never block, never abort, never need
  coordination: this is *the* reason SI is the default for replicated
  clusters.

### 5.3 Primary-copy SI with satellites (Ganymed)

- All update transactions run at a master; the master's writesets are
  propagated in commit order to satellites (possibly heterogeneous
  engines).
- Read-only transactions are routed to a satellite that has applied
  through (at least) the snapshot the client must see; if none, wait or go
  to the master. Transactions must be tagged read-only up front.
- Gives 1-copy SI with almost-linear read scaling; writes bounded by the
  master.

### 5.4 Session guarantees on a certification-based cluster

Commit at the delegate can return before remote replicas have applied the
writeset. A client then reading at another replica may miss its own write.
Two fixes:

1. Delay the commit acknowledgement until all replicas applied (slows
   every update).
2. Piggyback the client's last commit sequence number on its next
   transaction; the serving replica delays the snapshot until it has
   applied through that number (slows only that client's next read).

Prefer (2); it is the same mechanism as Raft read-index waits and
PostgreSQL `remote_apply`-equivalent client tokens.

---

## 6. Paxos as the ordering layer

### 6.1 Single-decree Paxos (roles: proposers, acceptors, learners; one coordinator)

```
Phase 1a  coordinator picks unique ballot b, sends PREPARE(b) to acceptors
Phase 1b  acceptor: if b > promised: promised := b;
          reply PROMISE(b, last_voted_ballot, last_voted_value)
Phase 2a  on a majority of promises: v := value of highest voted ballot
          among replies, or the client's command if none; send ACCEPT(b, v)
Phase 2b  acceptor: if b >= promised: promised := b; vote (b, v); reply
Decision  majority of 2b for (b, v) -> v is chosen; inform learners
```

- Safety (no two learners learn different values) holds in a fully
  asynchronous system; liveness needs eventually a single non-faulty
  coordinator and a live majority (dueling coordinators can livelock).
- Durable state per acceptor: `promised`, `(voted_ballot, voted_value)` —
  fsync before replying.
- Message steps: 6 naive (client → coordinator → 1a → 1b → 2a → 2b →
  learners); 3 with optimizations: run Phase 1 ahead of time for all future
  instances (Multi-Paxos) and send 2b directly to learners.

### 6.2 Multi-Paxos for a replicated database log

- Slot `i` of the log = consensus instance `i`; a stable leader runs Phase
  1 once for "all slots ≥ k", then one Phase 2 round per slot (or per batch
  of commands).
- On leader change, the new leader runs Phase 1 for all slots above its
  known-chosen prefix and must re-propose any value it learns was voted in
  those slots (filling gaps with no-ops). Skipping this re-proposal is the
  classic "lost committed entry" bug.
- Execution: apply slot `i` only after all slots `< i` are chosen and
  applied (or use commutativity knowledge: Generalized Paxos lets
  independent commands be learned in different orders).
- Linearizable reads: route through the log, or serve at the leader after
  confirming leadership (a heartbeat round, i.e., read-index) or under a
  time-based lease (requires bounded clock drift).
- Paxos can replicate just part of a system's state (metadata, membership,
  locks) while bulk data uses cheaper replication — Windows Azure Storage
  and Chubby-style lock services do this.

Variants worth knowing: Fast Paxos (proposers send directly to acceptors,
two message delays in the conflict-free case, larger quorums); Cheap Paxos
(only a quorum of active acceptors, auxiliaries on failure); Disk Paxos
(acceptors are disks); Ring Paxos and Multi-Ring Paxos (throughput,
network multicast; multiple ordered streams merged deterministically);
Mencius (rotating coordinators, WAN); EPaxos (leaderless; commands commute
→ fast path); Speculative Paxos and NetPaxos (network-assisted ordering).
Systems: Chubby, Boxwood, Spinnaker, F1/Spanner, Windows Azure Storage,
Megastore.

> **Beyond EDBS:** Raft (Ongaro & Ousterhout 2014) is Multi-Paxos with a
> strong leader and a log-matching invariant; it is the common choice for
> new engines (etcd, CockroachDB, TiKV, YugabyteDB). The invariants that
> matter for a DB log are identical: a leader commits an entry from a
> previous term only by committing an entry of its own term after it;
> durable `currentTerm/votedFor/log` before replying; membership changes
> via joint consensus or single-server steps. See `distributed-consensus`.

### 6.3 Paxos Commit (atomic commit without a blocking coordinator)

> **Beyond EDBS:** Gray & Lamport ("Consensus on Transaction Commit", TODS
> 2006). Each resource manager's vote (Prepared/Aborted) is decided by its
> own Paxos instance over a shared set of `2F+1` acceptors; the
> transaction commits iff every RM's instance chose Prepared. Classic 2PC
> is the degenerate case `F = 0` (the coordinator is the single acceptor),
> which is why 2PC blocks on coordinator failure. Paxos Commit tolerates
> `F` acceptor failures with the same message delay as 2PC in the normal
> case (more messages, though). The production equivalent is "2PC whose
> coordinator state and participants are each Paxos/Raft-replicated"
> (Spanner, CockroachDB parallel commits), covered in
> `distributed-transactions`.

### 6.4 Total-order transaction protocols built on a consensus log

- **Order then validate**: the log orders commit requests; each replica
  validates deterministically in log order (deferred update over Paxos;
  Megastore per-entity-group logs).
- **Validate then order**: validate a transaction for a specific log
  position, then try to place it there (retry on conflict).
- **Order before execution (deterministic DB)**: Calvin orders whole
  transactions (with declared read/write sets) before execution; every
  replica executes deterministically with locks acquired in log order — no
  commit protocol among replicas at all, but non-deterministic or
  dependent-read transactions need reconnaissance (OLLP).

---

## 7. Failure handling in total-order replication

- **Replica crash**: GCS installs a new view; survivors continue; no
  transaction blocks (contrast 2PC). Transactions whose delegate crashed
  before abcast are lost (client retries); those already delivered are
  decided by everyone.
- **Recovery/join**: state transfer must be synchronized with the view
  change: the joiner receives a snapshot consistent with a specific point
  in the total order and then every message after it. Options: full copy,
  changed items only, or missed log suffix (only for a returning member).
  Do it online by tagging the state with the last delivered sequence
  number and buffering deliveries at the joiner.
- **Partition**: only a primary component (majority view) may continue;
  minority members must stop accepting writes (and, for strong reads,
  reads). A GCS without primary-component semantics is unsafe for a DB.
- **Total cluster failure**: recovery must determine the longest durable
  prefix of the total order among survivors — requires each replica to
  log the sequence number of every applied writeset atomically with the
  data change.

---

## 8. Tests that catch real bugs

- Deterministic-simulation harness: randomize delivery timing, crash a
  delegate between local commit and acknowledgement, between abcast and
  delivery, and during state transfer; assert all replicas' committed
  sequences are prefix-equal and that the history is 1-copy SI (build the
  serialization graph from a recorded history; check with an Elle-style
  checker).
- Write-skew canary: two transactions each read `{x, y}` and write one of
  them under a constraint `x + y ≥ 0`; confirm the protocol's documented
  behaviour (allowed under 1-copy SI, forbidden under serializable
  certification).
- Session canary: write at replica A, immediately read at replica B with
  and without the session token.
- GC canary: start a long read-write transaction, push 10^6 small
  committed writesets through, then commit the long one with a write that
  conflicts with an early writeset — it must abort.

---

Sources: EDBS — Replication Based on Group Communication (p.3177),
Replication Based on Paxos (p.3184), Replication with Snapshot Isolation
(p.3207), Concurrency Control for Replicated Databases (p.566), Strong
Consistency Models for Replicated Data (p.3809), Middleware Support for
Database Replication and Caching (p.2257), Replica Control (p.3161),
Replication for Scalability (p.3194); Kemme & Alonso VLDB 2000 and TODS
2000; Pedone, Guerraoui, Schiper DAPD 2003; Wu & Kemme ICDE 2005; Lin et
al. SIGMOD 2005 and TODS 2009; Elnikety et al. SRDS 2005, EuroSys 2006;
Plattner & Alonso Middleware 2004; Daudjee & Salem VLDB 2006; Wiesmann &
Schiper TKDE 2005; Lamport TOCS 1998, Fast Paxos 2006; Schneider CSUR 1990.
