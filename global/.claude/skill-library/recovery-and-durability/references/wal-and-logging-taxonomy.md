# WAL and logging taxonomy

How to reason about *what* must be logged, *when* it must be durable, and
*what form* it takes. Everything ARIES does (see `aries-deep-dive.md`) is one
point in the design space laid out here.

## 1. Failure model

Recovery is defined relative to a failure model. State each assumption in
the design doc, because each one maps to a mechanism and a test.

| Failure | What survives | What is lost | Mechanism | Typical frequency / budget |
|---|---|---|---|---|
| Transaction failure (abort, deadlock victim, constraint violation, savepoint rollback) | everything | the txn's own uncommitted effects | undo using the in-memory log tail and log file, backward along prevLSN | constant; must be cheap |
| System failure (process crash, OS panic, power loss) | stable log, permanent DB pages as last written | buffer pool, log buffer, lock table, TT, cursors, in-flight 2PC state | restart = analysis + redo + undo | rare; restart in seconds to minutes |
| Single-page failure (checksum mismatch, torn write, lost write, firmware bug) | rest of the device | one page's correct contents | page repair: restore page from backup copy, replay the page's log chain | Graefe & Kuno (PVLDB 2012) argue this is a 4th failure class that should not escalate to media failure |
| Media failure (device loss, multi-disk RAID loss) | archive copies, archive log, other devices | the device | restore archive copy + redo archive log; RAID shortens but does not remove the need | rare; hours acceptable historically |
| Site failure / disaster (fire, flood, grid) | remote copies | the site, including log | remote replica kept current by log shipping; failover | very rare; governed by RPO/RTO |
| Communication failure (partition, lost/delayed message) | all sites | agreement | commit protocol logging + termination protocol | distributed only |

Two failure classes are outside what replay can fix:
- **Hard ("Bohr") failures** — deterministic bugs: re-executing the same
  input reproduces the crash. Only fixing code or skipping the poison input
  helps. A restart loop that crashes on the same log record is this class;
  build an operator escape hatch (e.g., mark the page/object offline, skip
  and quarantine) rather than looping forever.
- **Soft ("Heisen") failures** — races, transient hardware faults, operator
  mistakes: re-execution almost always avoids them. This is why recovery by
  replay works in practice (Lomet, Application Recovery entry).

**Forward recovery is not an option for crashes.** Rolling forward an
interrupted transaction would require its lost in-memory local state
(program counter, variables, cursors). Crash recovery therefore always rolls
back incomplete transactions; the client or TP monitor reissues them. The only
legitimate "forward" completion is for *redundant* structure changes whose
completion does not alter logical content, e.g. finishing a B-tree split
(Härder, Crash Recovery entry). Persistent-application techniques
(`application-recovery-and-exactly-once.md`) recover the program state too,
which is what makes forward progress possible there.

## 2. The Härder–Reuter taxonomy

Härder & Reuter (ACM CSUR 1983) classify recovery schemes by how modified
pages reach the permanent database. The axes are buffer-manager policies,
and they determine which recovery steps exist.

- **Propagation: ATOMIC vs ¬ATOMIC.** ATOMIC means a set of page changes
  becomes visible in the permanent DB as one indivisible step (shadow pages,
  differential files, COW tree root swap). ¬ATOMIC is update-in-place: each
  page write is independent, so the permanent DB can hold any mixture.
- **STEAL vs ¬STEAL.** STEAL lets the buffer manager evict a page carrying
  uncommitted changes. ⇒ the permanent DB can contain loser data ⇒ undo
  information must be on stable storage first (WAL) and restart must undo.
- **FORCE vs ¬FORCE.** FORCE writes all pages a txn modified before its
  commit completes. ⇒ committed data is always in the permanent DB ⇒ no
  redo at restart. ¬FORCE ⇒ committed updates may exist only in the log ⇒
  redo needed.

| | FORCE | ¬FORCE |
|---|---|---|
| **STEAL** | Undo / No-redo | Undo / Redo (ARIES, every major disk RDBMS) |
| **¬STEAL** | No-undo / No-redo (needs ATOMIC propagation) | No-undo / Redo |

Why steal/no-force + ¬ATOMIC won:
- FORCE puts synchronous random page writes on the commit path and makes hot
  pages be rewritten on every commit; commit latency becomes I/O latency.
- ¬STEAL caps a transaction's write set at buffer size and, at page
  granularity, prevents two transactions from sharing a dirty page unless
  both commit together ⇒ in effect page-level locking.
- ATOMIC propagation (shadowing) destroys physical clustering, needs page
  table indirection, and makes checkpoints expensive (System R experience).
- The price of steal/no-force: the permanent DB is in an arbitrary mix of
  stale, current and dirty pages ("chaotic" state), so restart must do
  both redo and undo, and checkpoints are needed to bound redo.

NoUndo variants require that dirty data never reaches the permanent DB:
either the buffer pins it, or it is displaced to a separate area (shadow
or version store). Modern MVCC engines get no-undo-at-restart differently:
they *do* write uncommitted versions to disk (steal) but make them invisible
by version metadata, so "undo" becomes a status flip in a commit log
(PostgreSQL) or is deferred to background cleanup (SQL Server ADR).

> **Beyond EDBS:** PostgreSQL writes uncommitted heap tuples in place but
> never undoes them physically; abort just records the xid as aborted in
> `pg_xact`, and visibility checks ignore the tuple. Restart is therefore
> redo-only from the checkpoint's redo pointer. The cost moved to VACUUM.
> SQL Server's Accelerated Database Recovery (Antonopoulos et al., VLDB 2019)
> keeps row versions in a persistent version store so that undo at restart
> is a logical revert driven by the version store and becomes roughly
> constant time; only non-versioned operations still go through a small
> secondary log (sLog).

## 3. The rules

Three rules are necessary and sufficient for recovery to the most recent
transaction-consistent state; the buffer policy only changes how much work
restart does (Härder, Crash Recovery entry).

1. **WAL (undo rule).** Before a page holding uncommitted changes overwrites
   its predecessor in the permanent DB, the undo information for those
   changes is in the stable log. Implementation: before writing page P,
   ensure `flushedLSN ≥ pageLSN(P)`. This is stronger than needed for undo
   alone (it also covers redo records), but it is the only cheap check.
2. **Commit (redo rule).** Before commit is acknowledged — at the latest in
   phase 1 of a commit protocol — all redo information of the transaction is
   in the stable log. Implementation: force log through the commit record's LSN.
3. **Retention (truncation rule).** A log record may be discarded from the
   online log only when no failure in the model can need it: the page it
   redoes is in the permanent DB *and* the txn it may undo is finished *and*
   it has been copied to the archive log if media recovery depends on it.

Derived corollaries that reviews should check:
- A page write and the log flush it depends on can be in the same I/O batch
  only if the device or the code orders them (log first). Never rely on
  queue order of an async I/O engine without an explicit barrier.
- Read-only transactions write no commit record and need no force.
- A distributed participant's "prepared" record is a commit-rule point: all
  redo and undo, plus the locks needed to resume, are forced before voting yes.

## 4. What a log record says: physical, logical, physiological

| Kind | Content | Restart precondition | Space | Idempotent |
|---|---|---|---|---|
| Physical, page image | before/after image of whole page | none | very large | yes |
| Physical, byte range (value logging) | (page, offset, old bytes, new bytes) | page layout unchanged since log time | medium | yes |
| Logical / operation | "insert key k into index I", "UPDATE ... WHERE ..." | **operation-consistent** DB: every logged operation is either fully present or fully absent | small | no |
| Physiological | "on page P: insert record r at slot s", "on page P: delete slot s" | page P internally consistent (not torn) | small | no; made safe by pageLSN test |

Key consequences:
- **Logical logging needs atomic propagation of all pages an operation
  touches.** Otherwise a crash between the two page writes of an index insert
  leaves a state the logged operation cannot interpret. Härder's levels:
  action logging needs action consistency, DML logging needs API consistency.
  That is why pure logical logging appears only with shadowing, snapshots,
  or main-memory checkpoints taken at operation-consistent points
  (command logging, `checkpointing-and-main-memory-recovery.md`).
- **Physiological = physical to a page, logical within it.** Each record
  names exactly one page and describes an operation that is atomic under that
  page's X-latch. Redo works with non-atomic propagation, records are compact
  (only the entry, not the page), and slot compaction does not invalidate
  records. This is the practical default.
- **Physiological redo cannot repair a torn page**: the operation is
  interpreted against page contents that may be half-old. A torn page needs a
  physical image (first-touch full-page image, doublewrite copy, or backup
  page + per-page log replay).
- **Undo can be at a different level than redo.** Multilevel recovery redoes
  physiologically but undoes logically (delete the key wherever it now lives),
  see `aries-deep-dive.md` §6.

> **Beyond EDBS:** PostgreSQL `full_page_writes`: the first modification of
> a page after each checkpoint logs a full page image (FPI); redo of later
> records for that page starts from the image, so a torn data page is
> overwritten wholesale. With data checksums (or `wal_log_hints`), hint-bit
> only changes also trigger an FPI, because a torn hint-bit write would
> otherwise fail checksum verification. FPIs dominate WAL volume right after
> a checkpoint, which is a reason to space checkpoints out and to compress
> WAL. InnoDB instead uses a **doublewrite buffer**: dirty pages are first
> written and synced to a doublewrite area, then to their home location; at
> restart a torn home page is replaced from the doublewrite copy before
> physiological redo runs.

## 5. Log sequence numbers and the log record

- **LSN**: monotonically increasing identifier of a log record; most engines
  use the byte offset in a conceptually infinite log so that an LSN locates
  the record directly (segment = LSN / segmentSize).
- **pageLSN**: in every page header, the LSN of the last record whose effect
  is reflected in the page. Acts as a virtual timestamp comparing page state to
  the log.
- **flushedLSN**: highest LSN known durable. Owned by the log flusher.
- **prevLSN**: per-transaction backward chain; undo walks it.
- **Per-page chain (optional)**: each record also stores the previous LSN for
  the same page; enables single-page repair without scanning the log
  (Graefe & Kuno).

Minimal header (fixed width, little endian, checksummed):

```
struct LogRecHdr {
  u32 total_len;     // including header and trailer
  u16 type;          // UPDATE, CLR, COMMIT, ABORT, END, PREPARE, BEGIN_CKPT, END_CKPT, ...
  u16 rm_id;         // owning resource manager (heap, btree, fsm, catalog, ...)
  u64 lsn;           // self, so a stale record in a recycled segment is detectable
  u64 txn_id;
  u64 prev_lsn;      // same txn
  u64 page_id;       // 0 for non-page records
  u64 page_prev_lsn; // optional per-page chain
  u32 crc32c;        // over header + payload, crc field zeroed
}
// CLR adds: u64 undo_next_lsn
```

The log/recovery manager treats payloads as opaque. Resource managers create
records and implement `redo` and `undo`; the recovery manager feeds records
back to them (Reuter, Logging/Recovery Subsystem entry). This plug-in
boundary is what lets new access methods be recoverable.

## 6. Appending: latching, ordering, group commit

Per-page ordering requirement: if two updates to page P happen in order
u1, u2 then LSN(u1) < LSN(u2). Achieve it by generating the record and
assigning its LSN *while holding P's X-latch*, then setting pageLSN before
releasing the latch.

Append path (one design that scales):
1. `start = insert_ptr.fetch_add(len)` — the LSN is reserved.
2. Copy the record into the ring buffer at `start` (no global latch).
3. Publish "filled through" for that region (per-slot flag or a tracking
   array) so the flusher only writes contiguous filled prefixes.
4. Flusher: find longest contiguous filled prefix, write it, fsync/fdatasync,
   advance `flushedLSN`, wake waiters with commitLSN ≤ flushedLSN.

**Group commit**: many transactions' commit records are flushed by one I/O.
Throughput bound becomes `flushes/sec × txns per flush` rather than
`flushes/sec`. Variants:
- Timer/size-triggered flush (adds up to one interval of latency).
- Leader/follower: the first waiter becomes the flusher; others piggyback.
- **Early lock release / pre-commit**: release locks once the commit record
  is in the buffer, before it is durable; dependants cannot commit before the
  releaser because their own commit records come later in the same log. The
  client is still only acknowledged after the flush. DeWitt et al. (SIGMOD
  1984) discuss group commit and pre-commit for main-memory systems. Hazard:
  in a distributed or replicated setting, a dependant's *other* effects (a
  message, a read result returned to a client) can escape before durability.
- Asynchronous commit: acknowledge before flush; bounded window of lost
  commits on crash. Must be an explicit, per-transaction opt-in.

Flush cost model: with log device sync latency `s` and arrival rate `λ`,
an always-busy flusher gets ≈ `λ·s` commits per flush; latency ≈ `s` to `2s`.
NVM/battery-backed log buffers collapse `s` (Härder future directions;
Pelley et al., PVLDB 2013).

## 7. Log space management

- Online log is a ring of pre-allocated segments; archiving copies full
  segments to the archive log asynchronously (often duplexed); recycling
  needs both the truncation rule and "archived".
- **Truncation point** = min over: min recLSN in DPT (redo), firstLSN of
  the oldest active or prepared transaction (undo), archiver position,
  running backup start, slowest replica or logical-decoding consumer.
  Expose which term is binding.
- **Long transactions** pin undo; options: abort above a size/age, keep undo
  outside the redo log (Oracle-style undo segments, InnoDB undo tablespaces),
  or let MVCC versions replace log-based undo.
- **Reserve space for CLRs.** ARIES reserves, per update logged, enough log
  space to write its CLR, so a rollback can always complete even when the log
  is otherwise full. Without this, "log full" during rollback is a deadlock:
  space can only be freed by finishing the rollback.
- **Hot pages** that are never evicted keep recLSN old and pin redo. The
  checkpointer or flusher must periodically write pages whose recLSN is
  oldest, not merely least recently used.
- Log volume reduction: avoid logging index pages built in bulk (log the
  build as a logged-once allocation plus force the pages), compress FPIs,
  log deltas for updates, skip undo payload when the old version is
  retrievable from the version store.

## 8. Detecting corruption: checksums and CRC

A checksum is a fixed-width function of the protected bytes stored alongside
them; verification recomputes and compares. XOR of fixed-width chunks is the
cheapest checksum and misses many multi-bit patterns. A CRC treats data as a
binary polynomial M(x): append m zero bits (M(x)·x^m), divide by a generator
G(x) of degree m over GF(2), store the remainder R(x); the codeword
T(x) = M(x)·x^m + R(x) is divisible by G(x), and verification checks that
divisibility. A CRC with generator of degree m detects every burst error of
length ≤ m, which matches how storage and links fail (Fujimoto, Checksum and
CRC entry). Implemented as shift-register circuits in hardware or table-driven
/ carry-less-multiply code in software.

Worked mini-example (own numbers): G = x^3 + x + 1 (1011), M = 1101.
M·x^3 = 1101000; dividing by 1011 leaves 001, so T = 1101001; any single
burst of ≤3 flipped adjacent bits makes T non-divisible by 1011.

Engineering guidance:
- Use CRC32C (Castagnoli); x86 SSE4.2 and ARMv8 have instructions. It is an
  error-detecting code, not a MAC: an adversary can forge it.
- Page checksum covers the whole page with the checksum field treated as
  zero; compute it after pageLSN and all bytes are final; verify on every
  read from storage, before the page is used to decide redo.
- Include the page id (or mix it into the checksum seed) so a correctly
  checksummed page written to the *wrong* location is detected.
- Checksums do not catch **lost writes** (an old but internally valid page
  returned after the device acknowledged a newer write). Detect with
  pageLSN cross-checks: the DPT or per-page chain says the page should be
  at least LSN X; a page that reads older than the newest LSN known to have
  been written for it is stale. Some engines log the version observed on
  reads so a standby can detect the primary's lost write.
- Log records: per-record CRC plus the record's own LSN in its header. The
  end of log at restart is the first record whose CRC fails *or* whose
  stored LSN differs from its position, *or* whose segment generation is
  stale. Never "skip over" a bad record in the middle of the log: that is
  corruption, not the end.

**Torn pages.** Device write atomicity is typically a sector (512 B or 4 KiB),
smaller than a DB page. After power loss a page may mix new and old sectors.
Options: (a) checksum + first-touch full-page image in the log (PostgreSQL);
(b) doublewrite (InnoDB); (c) COW pages never overwritten in place
(shadow/LMDB-style); (d) per-sector LSN stamps checked on read (older
engines); (e) rely on device atomic-write guarantees only with documented
hardware support. Any of these must be present if redo is physiological.

## 9. Shadowing and differential files (ATOMIC propagation)

- **Shadow paging**: a page table maps logical to physical pages; updates go
  to fresh physical pages; commit atomically switches the root/page table
  pointer. Gives no-undo (old pages untouched) and, with force, no-redo.
  Costs: page table I/O, loss of clustering, garbage collection, and coarse
  concurrency unless combined with a log. System R used shadowing for
  action-consistent checkpoints plus a log; ARIES drops it.
- **Differential files**: changes accumulate in a separate file merged later;
  reads consult both. Ancestor of LSM trees (see `lsm-storage`).
- Modern COW B-trees (LMDB, Btrfs-like) are shadow paging with a single
  writer and a double-buffered root; durability = fsync data, then fsync root.

## 10. Review checklist for a log manager

- [ ] LSN assigned under page X-latch; pageLSN set before latch release.
- [ ] Page write path calls `flush_to(pageLSN)`; no path bypasses it
      (evictor, checkpointer, bulk loader, backup reader that writes back).
- [ ] Commit waits for flushedLSN ≥ commitLSN; async commit is opt-in.
- [ ] Log end detection uses CRC + embedded LSN + segment generation.
- [ ] Undo space reserved; "log full" tested during rollback.
- [ ] Truncation computes all pinning terms and exports the binding one.
- [ ] Torn-page strategy chosen and tested with sector-granular tearing.
- [ ] fsync/fdatasync errors are fatal for data and log files.

Sources: EDBS Crash Recovery p.660; Logging and Recovery p.2133;
Logging/Recovery Subsystem p.2135; Atomicity p.186; Checksum and Cyclic
Redundancy Check Mechanism p.423; Multilevel Recovery and the ARIES Algorithm
p.2344; Main Memory DBMS p.2164 (DeWitt et al. 1984 in its reading list).
