---
name: recovery-and-durability
description: "Use when designing, implementing or reviewing how a database survives failures: write-ahead logging, ARIES restart (analysis/redo/undo), checkpoints, media and archive recovery, backup/PITR, snapshots, disaster recovery, replica re-join, in-doubt 2PC transactions and exactly-once application recovery. Triggers on WAL rule, commit rule, steal/no-force, LSN, pageLSN, recLSN, dirty page table, CLR, undoNextLSN, repeating history, nested top action, physiological logging, logical undo, fuzzy checkpoint, group commit, log truncation, torn page, full-page writes, doublewrite, CRC32C, command logging, point-in-time recovery, incremental backup, copy-on-write snapshot, RPO/RTO, log shipping, in-doubt transaction, idempotent redo, exactly-once. Apply even when phrased as 'restart is slow', 'we lost a committed row', 'the log keeps growing', 'is this fsync enough' or 'can we skip undo'."
---

# Recovery and Durability

This skill owns the part of the engine that turns "committed" into a promise
that holds through crashes, disk loss, site loss and client retries: the log
manager, the restart algorithm, checkpointing, archive/backup, and the
contracts that extend atomicity past the DBMS boundary. The single most
important idea: **the log is the authority, pages are a cache of the log**.
Every rule below exists to keep that statement true at every instant a
failure can strike, including in the middle of recovery itself.

## Mental model

- **State = stable log + permanent database (+ archive copies).** Volatile
  state (buffer pool, lock table, transaction table, log tail) is gone after
  a crash; restart may use only what is on non-volatile media.
- **Failure classes** drive mechanisms (details in
  `references/wal-and-logging-taxonomy.md`):
  | Class | Lost | Repaired by |
  |---|---|---|
  | Transaction failure | one txn's in-flight work | undo from log (rollback, savepoint) |
  | System crash | all volatile state | restart: redo + undo from online log |
  | Single-page failure | one bad/torn/lost page | page repair from backup + per-page log chain |
  | Media failure | a device's contents | archive copy + archive log redo |
  | Site/disaster | the whole data centre | remote replica fed by log shipping |
  | Hard (Bohr) bugs | deterministic replay re-fails | not recoverable by replay; needs a fix |
- **Two buffer-policy bits decide the recovery work** (Härder–Reuter):
  steal (uncommitted pages may reach disk ⇒ undo needed) and force (all of a
  txn's pages written at commit ⇒ no redo needed). Industrial engines run
  **steal/no-force + update-in-place**, so restart needs both redo and undo.
- **ARIES** is the reference algorithm: physiological log records, an LSN in
  every page header, a dirty page table (DPT) with recLSN, a transaction
  table (TT), fuzzy checkpoints, three passes (analysis, redo by
  **repeating history**, undo with **CLRs**). See `references/aries-deep-dive.md`.
- **Durability is end-to-end.** Commit means "log forced", not "page
  written"; a replica, a backup, and a client retry each extend or break that
  chain (`references/backup-pitr-and-disaster-recovery.md`,
  `references/application-recovery-and-exactly-once.md`).

## Core invariants

1. **WAL rule:** a page with pageLSN = L is written to the permanent DB only
   if flushedLSN ≥ L. Assert in the page-write path.
2. **Commit rule:** a commit is acknowledged only after the commit record (and
   therefore all the txn's redo records) is at or below flushedLSN.
3. **Truncation rule:** the online log is never truncated past
   min(min recLSN over DPT, firstLSN of the oldest active/in-doubt txn,
   oldest LSN still needed by archiving, backup or replicas).
4. **Per-page LSN monotonicity:** every update to page P assigns LSN > pageLSN(P),
   generated while P is X-latched; log order equals per-page apply order.
5. **Redo test:** a logged action is applied to P iff LSN > pageLSN(P);
   applying it sets pageLSN := LSN. Redo is thereby idempotent even for
   non-idempotent physiological operations.
6. **Repeating history:** after the redo pass, the database equals the state
   at the crash instant (winners and losers alike) for every page in the DPT.
7. **CLRs are redo-only and each update is undone at most once:** undo of
   record r writes a CLR whose undoNextLSN = r.prevLSN; restart work stays
   bounded under any number of crashes during recovery.
8. **Logical undo is applied only to operation-consistent state:** a
   high-level inverse (delete key k) runs only after all incomplete page-level
   operations below it are undone (multilevel recovery).
9. **recLSN ≤ LSN of the oldest update to P not yet on disk**, for every P in
   the DPT; the checkpointed DPT may over-approximate but never under-approximate.
10. **Prepared (in-doubt) state survives restart:** a participant that voted
    yes keeps its locks and redo/undo information until the outcome arrives.
11. **No half-trusted bytes:** every page and log block is checksum-verified
    before its contents (including pageLSN) steer recovery decisions; the log
    end is the last record with a valid checksum and contiguous LSN.
12. **A backup is usable only with its log:** restoring a fuzzy copy requires
    log from the copy's redo start point through a consistency point.

## Design space & trade-offs

| Buffer policy | Restart needs | When it wins | Cost / risk |
|---|---|---|---|
| steal / no-force (ARIES) | undo + redo | general OLTP, large buffers, record locks | most complex code; restart bounded by checkpoints |
| steal / force | undo only | tiny buffers, slow logs (historical) | synchronous page I/O on commit; hot pages rewritten constantly |
| no-steal / no-force | redo only | MVCC engines that never write uncommitted data in place; main-memory DBs | buffer pressure from long txns; needs version store or shadowing |
| no-steal / force | nothing | shadow paging, LMDB-style COW B-trees | atomic multi-page propagation, page-level locking, write amplification |

| Logging granularity | Redo idempotent? | Needs at restart | Use |
|---|---|---|---|
| Physical (byte range / full image) | yes | nothing | torn-page repair, first-touch images |
| Physiological (page-addressed, logical inside page) | via pageLSN | page internally consistent | default record/index changes |
| Logical (operation / SQL / command) | no; must be testable | operation-consistent DB | undo of multi-page ops; command logging in deterministic MMDBs |

| Checkpoint | Pause | Restart redo span | Notes |
|---|---|---|---|
| Transaction-consistent (quiesce) | long | from checkpoint | only for tiny DBs / tests |
| Action-consistent (flush all dirty) | medium | from checkpoint | buffer-size proportional stall |
| Fuzzy (ARIES) | latch TT+DPT copy | from min recLSN | needs background flusher to advance min recLSN |
| Consistent snapshot (MMDB, COW/fork) | near zero | from snapshot LSN | memory overhead for COW; redo-only log |

| Durability across sites | Lost on failover | Commit latency |
|---|---|---|
| 1-safe (async log shipping) | last un-shipped txns (RPO > 0) | local fsync |
| 2-safe (sync, 2PC/consensus) | none (RPO = 0) | + network RTT + remote durable write |
| Quorum log (Aurora/Raft) | none if quorum intact | + RTT to quorum |

## Algorithms that matter

- **Log append + group commit:** reserve LSN range under a short latch, copy
  record into the log buffer, release; a single flusher forces the buffer and
  advances flushedLSN; committers wait on flushedLSN ≥ commitLSN. Amortises
  one fsync over N commits; latency ≈ one flush interval.
- **ARIES restart** (full pseudo-code in `aries-deep-dive.md`):
  - *Analysis* — from the last checkpoint's begin record: rebuild TT
    (status, lastLSN, undoNextLSN) and DPT (recLSN); losers = TT entries not
    committed/prepared; redoLSN = min recLSN. O(log since checkpoint).
  - *Redo* — scan forward from redoLSN; skip if P ∉ DPT or LSN < recLSN(P)
    (no I/O); else fetch P and apply iff pageLSN < LSN. I/O-bound; parallelise
    by page.
  - *Undo* — process max LSN across all losers; update ⇒ apply inverse,
    write CLR(undoNext = prevLSN); CLR ⇒ jump to its undoNextLSN; write END
    when chain reaches null.
- **Nested top action:** an SMO inside a txn ends with a dummy CLR whose
  undoNextLSN skips it: survives the txn's rollback, undone if incomplete.
- **Fuzzy checkpoint:** BEGIN_CKPT; copy TT, DPT; END_CKPT; force; master record.
- **Media recovery:** fuzzy image copy + redo from its redo point + undo losers.
- **2PC restart:** prepared, no outcome ⇒ reacquire locks, ask; never decide alone.

## Failure modes & classic bugs

- **pageLSN updated after latch release** ⇒ another thread's update gets a
  smaller LSN on the same page; redo skips it. Detect: assert LSN > pageLSN
  under latch.
- **Selective redo (winners only) with record locking** ⇒ loser undo hits a
  page that never got its update; pageLSN lies. Repeat history instead.
- **Page-level undo after a split** removes a committed txn's key that moved
  onto the split page. Use logical undo for index keys.
- **Missing CLR on rollback** ⇒ repeated crashes re-undo already undone work
  (non-idempotent) or unbounded log growth.
- **Torn page + physiological redo** ⇒ redo on a half-old page; need
  full-page images, doublewrite, or checksum + page repair.
- **fsync error retried** ⇒ OS may have dropped the dirty pages; make it fatal.
- **Log tail garbage accepted** (recycled segment) ⇒ check CRC + embedded LSN.
- **Log full during rollback** ⇒ no room for CLRs; reserve undo space up front.
- **Forgotten prepared txn / replication slot** pins truncation; disk fills.
- **Backup without its log range**, or data/log snapshots not atomic ⇒
  unrestorable copy, discovered at restore time.
- **Client retry after ambiguous commit** ⇒ duplicates; need outcome inquiry.

## Implementation checklist (C/C++/Rust)

- LSN = u64 byte offset in an infinite logical log (segment = LSN >> k);
  never reuse; compare as integers. Record header: len, type, txnId,
  prevLSN, pageId, CRC32C; CLRs add undoNextLSN.
- Log buffer: lock-free or latch-protected reservation (fetch_add on an
  insert pointer), copy outside the latch, a "filled up to" watermark before
  flushing; O_DIRECT/O_DSYNC or fdatasync; pre-allocate segments.
- Buffer manager hook: before write-back, `log.flush_to(page.lsn)`;
  maintain per-frame recLSN set on first dirtying (clean→dirty transition).
- Page header carries pageLSN and checksum; compute checksum on write-back
  after the final pageLSN is set; verify on every read before trusting it.
- Rust: make "holding an X-latch" a guard type that is the only way to obtain
  `&mut Page` and the only place `log_and_apply()` is callable; it sets
  pageLSN before drop.
- Resource-manager plug-in interface: `redo(rec, &mut Page)`,
  `undo(rec, txn) -> CLR`; the log manager treats payloads as opaque bytes.
- Recovery structures: TT `HashMap<TxnId, {state, lastLSN, undoNextLSN}>`,
  DPT `HashMap<PageId, recLSN>`, undo set as max-heap of LSNs.
- Track truncation reasons explicitly (DPT, oldest txn, archiver, backup,
  replica) and expose them as metrics.

## How to test it

Read `references/crash-testing-recovery-code.md` before writing tests. Core:
- **Crash-point enumeration:** crash at every log flush, page write and fsync
  boundary in a deterministic workload; restart; compare with an oracle that
  holds exactly the acknowledged-committed transactions.
- **Crash during recovery:** inject crashes inside analysis, redo, and after
  each CLR; recovery must converge and total log written must stay bounded.
- **Torn and lost writes:** write a prefix of sectors, drop the last N writes
  after the last fsync, reorder un-fsynced writes; expect detection or repair.
- **Idempotence property:** redo(redo(S)) == redo(S) for random log prefixes.
- **Backup/PITR round trip:** online backup under load, restore to random
  target LSNs/timestamps, verify against oracle snapshots.

## Expert review questions

1. Where exactly is flushedLSN ≥ pageLSN enforced, and can any writer
   (checkpointer, evictor, backup reader) bypass it?
2. Is pageLSN assigned under the same X-latch as the change, for every
   resource manager including free-space maps and catalogs?
3. Which operations use logical undo, and what guarantees they are applied to
   an operation-consistent state?
4. How are structure modifications isolated from the owning txn's rollback
   (nested top actions, system transactions)?
5. What is restart time as a function of checkpoint interval, dirty-page
   count and log bandwidth, and is it measured, not guessed?
6. How are torn pages detected and repaired, and is the answer still true
   with checksums disabled or on 4K-atomic devices?
7. What pins log truncation today, and what happens when the log volume is
   100% full during rollback?
8. Is the restart available before undo completes (instant restart), and if
   so, how are loser locks held?
9. Can a backup be restored without any external state, and has a restore
   been tested from the oldest retained generation?
10. Do data and log snapshots come from one consistency group?
11. What does a client see when the connection drops after COMMIT was sent,
    and how does it learn the outcome?
12. How long can a prepared transaction stay in doubt, and who can resolve it?
13. On failover with async shipping, which committed txns are lost, and is
    that RPO documented and monitored?
14. How does a re-joining replica get a consistent state without a global
    pause?

## Go deeper

- `references/wal-and-logging-taxonomy.md` — failure model, Härder–Reuter
  taxonomy, the three rules, logging kinds, record format, group commit, log
  space, checksums, torn pages. Read first when building or reviewing a log manager.
- `references/aries-deep-dive.md` — ARIES structures and passes in pseudo-code,
  CLRs, nested top actions, multilevel B-tree example, savepoints, media,
  parallel/instant restart. Read when implementing restart or index logging.
- `references/checkpointing-and-main-memory-recovery.md` — checkpoint kinds,
  restart-time model, MMDB snapshot + redo-only/command logging, NVM. Read
  when restart is slow or the engine is in-memory.
- `references/backup-pitr-and-disaster-recovery.md` — archive recovery, backup
  types, PITR, COW/ROW snapshots, CDP, WORM, RPO/RTO, replica re-join, 2PC
  restart and in-doubt txns. Read for anything beyond one node's crash.
- `references/application-recovery-and-exactly-once.md` — interaction
  contracts, x-ability, outcome inquiry. Read when "exactly once" is promised.
- `references/crash-testing-recovery-code.md` — fault injection, oracle, assertions.
- `references/edbs-entries.md` — every EDBS entry in this cluster with page.

## Related skills

- `transactions-and-recovery` — single-node CC + WAL overview; this is the expert recovery half.
- `concurrency-control-theory` — recoverability classes (RC/ACA/ST); here: what undo needs from locking.
- `page-and-file-format` / `storage-devices-and-io` — page layout, fsync, write atomicity, NVM.
- `index-structures-catalog` — B-tree latching and SMOs; here: their logging and logical undo.
- `distributed-transactions` — 2PC/3PC protocols; here: their logging and restart.
- `replication-protocols` / `replication-and-consistency` — replica control; here: re-join, 1-/2-safe.
- `distributed-dbms-design`, `parallel-database-systems`, `dbms-architecture` — where recovery sits.
- `stream-processing-engines` — checkpoint/replay exactly-once in streams.
- `database-security-internals` — audit logs, WORM retention, tamper evidence.
- `tuning-and-benchmarking` — checkpoint/log tuning, recovery-time SLOs.
- `lsm-storage` — WAL + memtable flush as a no-steal/no-force special case.
- `temporal-databases` — historical queries used for replica catch-up.

## Grounding

EDBS (2nd ed., 2018): Crash Recovery p.660; Logging and Recovery p.2133;
Logging/Recovery Subsystem p.2135; Multilevel Recovery and the ARIES Algorithm
p.2344; Atomicity p.186; Application Recovery p.123; Middleware Support for
Precise Failure Semantics p.2264; Distributed Recovery p.1212; Online Recovery
in Parallel Database Systems p.2564; Replication for Availability and Fault
Tolerance p.3187; Main Memory DBMS p.2164; Backup and Restore p.251;
Point-in-Time Copy p.2769; Continuous Data Protection p.613; Disaster Recovery
p.1121; Checksum and CRC Mechanism p.423; Write Once Read Many p.4732.
Papers: Härder & Reuter, CSUR 1983; Gray et al., System R recovery, CSUR 1981;
Mohan et al., ARIES, TODS 1992; Weikum et al., multi-level recovery, PODS 1990;
Lomet, MLR, SIGMOD 1992; Kuo, TODS 1996; Weikum & Vossen 2002; Graefe & Kuno,
PVLDB 2012; Mohan, Lindsay & Obermarck, R*, TODS 1986; Barga et al., TOIT 2004;
Frølund & Guerraoui, x-ability, 2001; Kemme et al., DSN 2001.
