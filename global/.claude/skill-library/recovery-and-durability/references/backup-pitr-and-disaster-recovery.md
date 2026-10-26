# Backup, PITR, snapshots, disaster recovery, replica and distributed recovery

Crash recovery assumes the permanent database and the online log survived.
Everything in this file handles the cases where they did not, or where the
"database" is spread over several nodes: archive (media) recovery,
point-in-time recovery, storage-level copies, site loss, re-integrating a
replica, and recovering a node that was mid-way through a distributed commit.

## 1. Archive (media) recovery

Components (Härder, Crash Recovery; Rahm, Logging and Recovery):
- **Archive copy (dump)**: a copy of the database as of some point.
- **Archive log**: redo information for all changes since the oldest archive
  copy still relied on; produced by an asynchronous process copying from the
  online (temporary) log; usually **duplexed** on independent devices.
- Restore = latest usable archive copy + chronological redo from the archive
  log (+ online log if it survived), then undo of transactions still in
  flight at the end of the replayed log.

Rules:
1. **Independent failure modes**: archive copy, archive log and the online
   database must not share a device, controller or site, or one fault can
   take out both the data and its means of reconstruction.
2. **Generations**: keep several archive copies; archives are rarely read and
   media decay silently. Because the newest generation may itself be
   unreadable, the archive log must reach back to the **oldest** retained
   generation.
3. **RAID is not backup**: it shortens recovery from single-disk loss but
   cannot exclude data loss (multiple failures, controller bugs, operator
   deletes, logical corruption, which RAID faithfully mirrors).

Making copies without stopping updates (a transaction-consistent dump would
quiesce updates for the whole copy time):
- **Fuzzy dump**: copy pages while transactions run; the copy is
  inconsistent and is made usable by replaying log from a redo point that
  precedes the copy start.
- **Incremental dump**: copy only pages changed since the previous dump;
  restore applies the chain, then the log.
- **Offline merge**: build a newer full copy from an older one plus
  increments (or plus log) in a separate process, so production never pays
  for a full dump ("synthetic full").

## 2. Backup taxonomy

| Type | Contents | Restore needs | Backup cost | Restore cost |
|---|---|---|---|---|
| Full | everything | one image | highest | lowest |
| Cumulative ("differential" in common industry usage) | all changes since the last full | full + latest cumulative | grows until next full | 2 images |
| Chained ("incremental" in common industry usage) | changes since the last backup of any kind | full + every increment in order | smallest | longest chain; one bad link breaks the chain |
| Log/WAL archive | every change record | base image + log range | continuous | replay time |

> **Naming caution:** the EDBS Backup and Restore entry (p.251) defines the
> two terms the other way round (its "incremental" is cumulative since the
> last full, its "differential" is since the last backup). Most products and
> operators use the convention in the table, but not all: IBM Db2 calls the
> cumulative kind "incremental" and the chained kind "delta", and Oracle RMAN
> uses "cumulative" vs "differential" level-1 incrementals. Always define the term in
> interfaces and runbooks by its baseline ("since last full" vs "since last
> backup").

Change tracking for incrementals: a per-extent modified bitmap maintained on
page write, a per-page LSN compared against the previous backup's start LSN
(scan cost but no extra state), or the log itself (derive changed page set
from records). The pageLSN comparison is the most robust because it needs no
extra crash-consistent structure.

## 3. Online backup consistency and PITR

A hot physical backup is a fuzzy dump plus a log range:

```
backup():
  start = force a checkpoint; startLSN = its redo point (min recLSN)
  enable full-page images for the duration      // torn pages read by the copier
  copy every file/page (any order, concurrently with updates)
  stopLSN = current end of log; force a log switch so stopLSN is archived
  write backup label {startLSN, stopLSN, timeline}
restore(target):
  lay down copy; replay log from startLSN; DB is NOT consistent until stopLSN
  continue replay to target (LSN, commit timestamp, txn id, named restore point)
  stop before/after the target commit; roll back txns open at the stop point
  open as a NEW incarnation/timeline so later log of the old line is not mixed in
```

Invariants:
- Never open a restored DB before replay passes stopLSN (the "minimum
  recovery point"); pages copied late may be newer than pages copied early.
- The copier may read a page while it is being written (a torn read).
  Either read through the buffer manager under a share latch, or ensure the
  log contains a full image of every page modified during the backup.
- The backup is only as good as the archived log range [startLSN, stopLSN];
  verify both exist before declaring success.
- A PITR target in the past forks history: assign a new timeline id and
  never apply log of the abandoned branch.

> **Beyond EDBS:** PostgreSQL's base backup + continuous WAL archiving is
> exactly this design: backup start forces a checkpoint and temporarily
> forces full-page writes, the `backup_label` records the start point,
> recovery targets are time/LSN/xid/restore-point, and promotion or PITR
> creates a new timeline with a history file. Oracle's equivalent opens
> with RESETLOGS to start a new incarnation.

## 4. Point-in-time copies (snapshots) at the storage layer

A point-in-time (PiT) copy is a copy of data as it appeared at one instant.
Classically it is taken while the application quiesces so the copy is
consistent (Fujimoto, Point-in-Time Copy entry).

| Technique | First write after snapshot | Snapshot read | Space | Notes |
|---|---|---|---|---|
| Full clone / split mirror | n/a (mirror broken off) | independent | 100% | needs resync; good for offloading backup I/O |
| Copy-on-write (COW) | read old block, write it to snapshot area, write new block in place: 1 read + 2 writes | from snapshot area if copied, else live volume | changed blocks only | active volume layout stays contiguous; write penalty grows with snapshot count (classic LVM snapshots) |
| Redirect-on-write (ROW) | write new block elsewhere, update map: 1 write | old blocks stay in place | changed blocks only | no write penalty; active volume fragments; deleting snapshots needs reference counting / GC (WAFL, ZFS, Btrfs-style) |

Consistency levels:
- **Crash-consistent**: equivalent to pulling the power at the snapshot
  instant. A WAL database recovers from it by ordinary restart — **if** data
  and log volumes are captured at the same instant with write-order fidelity
  (a *consistency group*). Snapshotting the log volume a moment after the data
  volume can produce a data page newer than the log describes: undetectable
  WAL violation.
- **Application-consistent**: the DB is told to checkpoint and suspend writes
  (or enter backup mode) during the snapshot; restore needs less or no redo.
- Snapshots on the same array are not backups against array loss; replicate
  or copy them elsewhere.

## 5. Continuous data protection (CDP)

CDP captures every change to storage so that a copy for *any* past instant
can be produced later; the user picks the recovery point at restore time,
not at backup time (Fujimoto, CDP entry). Implementation: a journal of writes
(with timestamps and order) alongside a base copy; restore = base + journal
replay up to the instant. Products differ in restorable granularity, from
crash-consistent volume images to logical objects (files, mailboxes,
database files, logs).

For a DBMS, WAL archiving + base backups is CDP at the database level, with
transaction-level recovery points. Storage CDP below a DBMS must preserve
write order across all volumes of the database, otherwise its "any point"
images are not even crash-consistent.

## 6. WORM retention

Write-once-read-many storage prevents alteration or erasure (Fujimoto, WORM
entry). Physical WORM: media that can be written once (optical). Logical
WORM: rewritable media plus enforcement in the storage system (keys,
retention locks), driven by retention and e-discovery regulation. Uses for
an engine: immutable archive logs and backups (ransomware and insider
defence), audit trails. Interplay: retention periods must exceed the
oldest generation the restore procedure depends on, and encryption keys must
be retained as long as the data.

> **Beyond EDBS:** object stores offer logical WORM (e.g. S3 Object Lock in
> compliance mode), now the common way to make backup sets immutable.

## 7. Disaster recovery (site failure)

Disaster recovery restores data, access to it and the processing around it
at a redundant site after loss of all or part of a data centre (fire,
earthquake, flood, grid failure, attack). It covers hardware, software and
work space, not only data (Fujimoto, Disaster Recovery entry). The data path
is replication to an off-site location at the database, file system or
storage level; the classic DB path is shipping the log to a remote copy and
applying it continuously (Rahm, Logging and Recovery).

Objectives:
- **RPO** (recovery point objective): maximum tolerated data loss, measured in
  time or transactions. RPO = 0 requires synchronous (2-safe) durability at
  the remote site.
- **RTO** (recovery time objective): maximum tolerated outage. Driven by
  standby temperature, failover automation, client reconnection and redo lag.

| Standby | Remote state | RTO | Cost | Notes |
|---|---|---|---|---|
| Cold | backups + archived log (or only a log of events) | hours | low | restore then replay |
| Warm | applies log lazily, lags primary | minutes | medium | replay backlog at failover |
| Hot | applies log immediately; may serve reads | seconds | high (as powerful as primary) | failover = promote |

1-safe vs 2-safe (Kemme, Replication for Availability):
- **1-safe** (lazy/asynchronous): primary commits, then ships. A primary loss
  after commit and before shipping loses that transaction at the new primary
  — neither atomicity nor durability holds for it. Reintegrating the old
  primary later requires reconciling (or discarding) its divergent tail.
- **2-safe** (eager/synchronous): shipping precedes commit; an agreement
  protocol (2PC or Paxos) makes the outcome atomic across sites. Pays WAN
  latency on every commit.
- Middle ground: commit when the log is durable at k of n remote sites
  (quorum), or "very safe" (all) vs "2-safe if reachable, else 1-safe" —
  document which, because the latter silently degrades RPO.

Failover mechanics that bite:
- Backups must agree on the set of transactions committed before the primary
  failed; with more than one backup use an agreement protocol to pick the new
  primary.
- Client drivers know the backups and reconnect; a transaction without a
  commit request gets an abort exception; a transaction whose commit was in
  flight has an **unknown outcome** and the driver must ask the new primary
  (see `application-recovery-and-exactly-once.md`).
- **Partitions**: an unreachable primary is indistinguishable from a slow one;
  two primaries can emerge (split brain). Use quorums (any two write quorums
  intersect; read quorums intersect write quorums) or fencing/leases so a
  minority side stops accepting writes. CAP: under partition you choose
  consistency or availability per operation.
- After failover the old primary must be rewound to the divergence point
  (or rebuilt) before rejoining as a replica.

## 8. Replica recovery (re-join) without stopping the system

Replica recovery integrates a failed or new replica. Offline recovery
(quiesce, copy, resume) defeats the point of replication; **online
recovery** transfers state while the system keeps processing, so the state
is a moving target (Jiménez-Peris, Online Recovery in Parallel Database
Systems; Kemme).

Correctness: split the transaction sequence into two disjoint sets — those
whose effects are in the transferred state, and those the recovering replica
will process (or receive updates for) after transfer. No transaction may fall
in both or neither.

Five phases:
1. **Local recovery** — the failed replica runs ordinary crash recovery.
2. **Find last committed update** — from its log; may be approximate
   (earlier is safe if re-applied updates are idempotent, e.g., full row
   after-images).
3. **Global recovery start** — announce join, report the last known update,
   elect a recoverer.
4. **Global recovery** — transfer state, synchronised with replica control.
5. **End-of-recovery handshake** — agree the cut-over transaction.

Transfer strategies: whole database (simple, required for a fresh replica,
wasteful for a short outage); only items changed during the downtime (needs
change tracking); or the **missed log suffix** (cheapest for short outages,
needs log retention on the recoverer — another truncation-pinning term).

Protocols from the literature:
- **Recovery locks** (Kemme, Bartoli & Babaoglu, DSN 2001): atomically set
  special read locks on all data, then stream items, releasing each lock after
  send. The atomic lock acquisition is the cut. Reads proceed, updates to
  not-yet-sent items wait; the recovering replica buffers updates submitted
  after the cut.
- **Multi-round**: round 1 sends what was missed until recovery start, round 2
  what changed during round 1, …; when a round is small, a final round runs
  while the recovering replica buffers new requests. Minimises buffering.
- **Log-based with handshake** (Jiménez-Peris, Patiño-Martínez & Alonso, SRDS
  2002, over the Nodo/Middle-R protocol): per conflict class, the recoverer
  streams the class's log while it keeps growing; at the log end it asks the
  class master to piggyback an end-of-recovery marker on its next update,
  which tells both sides exactly where the cut is. Classes recover
  independently and in parallel, with adaptive recoverer counts to protect
  throughput.
- **Historical queries** (Lau & Madden, VLDB 2006): catch up with lock-free
  time-travel queries from the last known time to near-present, then a short
  locked query for the final delta.
- **Byzantine settings**: tolerate f arbitrary failures with 3f+1 replicas;
  state transfer must come from enough recoverers to outvote faulty ones;
  proactive recovery reboots replicas round-robin from read-only media to
  bound the window of vulnerability (Castro & Liskov, TOCS 2002).

Metric: **performability** (cumulative delivered throughput through failures
and recoveries), not only availability: a recovery that keeps the system "up"
at 0.1% throughput is not acceptable.

## 9. Distributed recovery: commit-protocol logging and in-doubt transactions

Each site runs WAL locally; in addition, commit-protocol state transitions are
logged so a restarted site knows where it was (Tan, Distributed Recovery entry).

2PC log records:
- Coordinator: start-2PC record listing participants; global COMMIT or
  ABORT decision (forced); END after all acks (lazy).
- Participant: PREPARED / ready (forced, with undo/redo and locks) or ABORT;
  then COMMIT or ABORT on the decision.

Restart decisions:

| Site | Last 2PC record found | Action |
|---|---|---|
| Coordinator | none | commit protocol never started: abort (or re-initiate) |
| Coordinator | start-2PC, no decision | abort and inform participants (or restart voting) |
| Coordinator | decision, no END | re-send decision until all ack |
| Participant | none (no PREPARED) | abort unilaterally: coordinator cannot have decided commit |
| Participant | PREPARED, no decision | **in doubt**: reacquire locks, ask coordinator or run termination protocol with peers; never decide alone |
| Participant | COMMIT / ABORT | done (finish local redo/undo) |

Optimisations (Mohan, Lindsay & Obermarck, R*, TODS 1986):
- **Presumed abort**: no information ⇒ abort. Coordinator need not log
  start-2PC or force abort records, and participants do not ack aborts.
  Read-only participants vote READ and drop out of phase 2.
- **Presumed commit**: coordinator forces a collecting record (participant
  list) before phase 1; then commits need no acks and participants need not
  force commit records; no information ⇒ commit.

In-doubt handling as engineering:
- In-doubt transactions hold locks across restarts; the analysis pass must
  reinstate them before admitting new work, and the log cannot truncate past
  them. Expose an admin view (XA `recover`) and time-based alerts.
- **Heuristic decisions** (operator forces commit/abort of an in-doubt
  branch) break atomicity if they disagree with the coordinator; log them,
  report the "heuristic mixed" outcome back, and require reconciliation.
- 2PC blocks if the coordinator stays down; 3PC (Skeen 1981) is
  non-blocking only without partitions; modern systems replicate the
  coordinator and participants with consensus (see `distributed-transactions`).
- Replicated logging can replace the local force: ClustRa logged redundantly
  to main memory at a remote node; HARBOR removes the log by recovering from
  replicas.

## 10. "The log is the database" (Beyond EDBS)

> **Beyond EDBS:** *Aurora* (Verbitski et al., SIGMOD 2017) sends only redo
> records from the database instance to a storage service that keeps six
> copies across three availability zones with write quorum 4/6 and read
> quorum 3/6. Storage nodes materialise pages from the log in the background
> and on demand, and back up continuously to object storage. The instance
> never writes data pages, does no checkpoint I/O, and at restart the storage
> layer only establishes the durable log point (truncating records above it);
> the database opens without a redo pass, and loser undo runs online.
> *Socrates* (Antonopoulos et al., SIGMOD 2019, Azure SQL Hyperscale) splits
> the log tier (a low-latency durable landing zone plus an XLOG service that
> disseminates log) from page servers that apply log for their partition and
> from long-term storage (XStore) where backups are storage snapshots taken in
> constant time. Neon applies the same split to PostgreSQL (Paxos-replicated
> safekeepers for WAL, page servers for page reconstruction). Consequences
> for engine design: durability = quorum log write; page writes and
> checkpoints leave the critical path; PITR and branching become reading
> pages "as of LSN" from the page service; restart time is dominated by
> cache warm-up, not redo.

## 11. Review checklist

- [ ] Restore has been executed end-to-end from the oldest retained
      generation, not just "backup succeeded".
- [ ] Every backup records its required log range and the archive holds it.
- [ ] Data + log snapshots come from one consistency group.
- [ ] Backup terms are defined by baseline in UI and docs.
- [ ] RPO/RTO stated per tier, measured continuously (replication lag, time to
      promote), and degraded-mode behaviour (sync → async) is alarmed.
- [ ] Old primary rewinds or rebuilds before rejoin.
- [ ] In-doubt transactions are listed, aged, and resolvable by an operator.
- [ ] Immutable copies (WORM/object lock) for at least one generation.

Sources: EDBS Backup and Restore p.251; Point-in-Time Copy p.2769;
Continuous Data Protection p.613; Write Once Read Many p.4732; Disaster
Recovery p.1121; Crash Recovery p.660; Logging and Recovery p.2133;
Replication for Availability and Fault Tolerance p.3187; Online Recovery in
Parallel Database Systems p.2564; Distributed Recovery p.1212; Application
Recovery p.123 (standby temperatures).
