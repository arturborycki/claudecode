# ARIES and multilevel recovery, in full

ARIES (Mohan, Haderle, Lindsay, Pirahesh, Schwarz, TODS 1992) is the
reference crash/media recovery method for steal/no-force, update-in-place,
fine-grained-locking engines. Weikum's multilevel recovery framework (PODS
1990; Weikum & Vossen 2002) explains *why* it is shaped that way; Lomet's MLR
(SIGMOD 1992) is a parallel formulation. A correctness model and proof is in
Kuo (TODS 1996). This file gives the data structures, the normal-processing
protocol, the three restart passes in pseudo-code, the multilevel argument
with a B-tree split example, and the extensions (media, parallel, instant).

## 1. Why page-level redo/undo is not enough

Classic three-pass recovery with page-granularity logging is correct when
concurrency control is also page-granular: then every loser update that
conflicts with a winner update follows it in the log, and undoing pages
cannot destroy winner work. With record or key locking (or semantic,
commutativity-based CC on hot spots) that ordering invariant is gone. A
single logical operation (insert a record) touches several pages (data page,
leaf, possibly a split creating a new leaf and changing the parent), and two
transactions' operations interleave on the same pages without a lock
conflict. Three problems follow:

1. **Redo of a winner can be wrong** if it depends on an earlier loser page
   change (e.g., a split) whose page write never reached disk and is not redone.
2. **Page-level undo of a loser can erase a winner**: restoring a leaf's
   before-image removes a key a committed transaction put there after the
   loser's split.
3. **Pure operation-level logging is not restartable**: a crash in the middle
   of a multi-page operation leaves partial effects that no logged operation
   can interpret.

Multilevel recovery requirements (Weikum, EDBS p.2344):
- **Operation atomicity** — each high-level operation appears all-or-nothing.
- **High-level undo** — losers' completed operations are undone by inverse
  operations at the same abstraction level (insert key ⇒ delete key).
- **Testability** — before redoing or undoing, recovery can tell whether the
  effect is present (it may be lost, or already undone by an interrupted
  recovery). Essential for non-idempotent operations.
- **Efficient redo** — redo dominates restart time, so redo must be page
  oriented, enabling DPT bookkeeping, I/O scheduling, parallel and
  selective redo.

Resulting template: analysis; redo by repeating history at page level;
undo of losers — page-oriented for operations cut short by the crash,
logical (inverse operation) for operations that finished; full logging (page
records plus a CLR) during undo.

## 2. Data structures

| Structure | Where | Fields | Purpose |
|---|---|---|---|
| Log record | stable log | LSN, type, txnId, prevLSN, pageId, redo info, undo info | the authority |
| CLR | stable log | as above + undoNextLSN; redo info only | records an undo step; never undone |
| pageLSN | every page header | LSN of last applied record | testability for redo |
| Transaction table (TT) | memory, checkpointed | txnId → {state ∈ U, P, C; lastLSN; undoNextLSN} | rollback, analysis |
| Dirty page table (DPT) | memory, checkpointed | pageId → recLSN | redo start point, redo skipping |
| flushedLSN | memory | durable log horizon | WAL check |
| Master record | fixed location | LSN of last complete BEGIN_CKPT | where analysis starts |

**recLSN(P)**: the LSN of (or a lower bound on) the first log record that
dirtied P since P was last clean, i.e. the earliest change to P that may be
missing on disk. Set when a clean frame becomes dirty: recLSN := current end
of log (next LSN to be assigned). Removed when P is written and clean.

## 3. Normal processing

```
update(txn, P, op):
  latch_X(P)
  rec = make_record(txn.id, prev=txn.lastLSN, page=P.id, redo=op, undo=inverse(op))
  rec.lsn = log.append(rec)            // reserves CLR space too
  apply(op, P); P.pageLSN = rec.lsn
  if DPT[P] absent: DPT[P] = rec.lsn   // or end-of-log before append
  txn.lastLSN = rec.lsn; txn.undoNextLSN = rec.lsn
  unlatch(P)

write_back(P):                          // evictor, flusher, checkpointer
  log.flush_to(P.pageLSN)              // WAL
  write P (checksum computed now); on completion: DPT.remove(P) if still clean

commit(txn):
  c = log.append(COMMIT, txn, prev=txn.lastLSN)
  log.flush_to(c)                      // commit rule; group commit here
  release locks; log.append(END, txn) (not forced); TT.remove(txn)
```

**Rollback (total or to savepoint S)** — same code as restart undo,
restricted to one transaction:

```
rollback(txn, upto = 0 or savepointLSN):
  n = txn.undoNextLSN
  while n > upto:
    r = log.read(n)
    if r.type == UPDATE:
       if r.undoable:
         clr_lsn = undo(r)             // performs inverse, logs CLR(undoNext = r.prevLSN)
       n = r.prevLSN
    elif r.type == CLR:
       n = r.undoNextLSN               // skip already-undone work
    txn.undoNextLSN = n
  if upto == 0: log.append(ABORT/END)
```

Partial rollback leaves the transaction running; a later total rollback
follows the CLR's undoNextLSN and never re-undoes the savepoint-rolled-back
records. This is the "partial rollbacks" in the ARIES title.

## 4. Fuzzy checkpoint

```
checkpoint():
  b = log.append(BEGIN_CKPT)
  latch TT, DPT (short); copy both; unlatch
  e = log.append(END_CKPT{TT copy, DPT copy})
  log.flush_to(e)
  master.write(b)                       // atomically, after END is durable
```

No data page is written by the checkpoint itself. A background writer keeps
the DPT short and advances min recLSN; without it, fuzzy checkpoints bound
analysis but not redo. Restart redo start = min(recLSN in DPT), which can be
earlier than BEGIN_CKPT. Some engines log page write completions to shrink
the DPT reconstructed by analysis.

## 5. Restart

### Analysis (forward, from master record)

```
analysis():
  TT, DPT = from END_CKPT following master.BEGIN_CKPT
  for r in log.scan(from = master.BEGIN_CKPT):
    if r.txn and r.txn not in TT: TT[r.txn] = {state: U}
    match r.type:
      UPDATE | CLR:
        TT[r.txn].lastLSN = r.lsn
        TT[r.txn].undoNextLSN = (r.type == CLR) ? r.undoNextLSN : r.lsn
        if r.page not in DPT: DPT[r.page] = r.lsn
      PREPARE: TT[r.txn].state = P      // in-doubt; keeps locks
      COMMIT:  TT[r.txn].state = C
      END:     TT.remove(r.txn)
  for t in TT where state == C: log.append(END, t); TT.remove(t)
  redoLSN = min(DPT.values())
  losers  = { t in TT | state == U }
  reacquire locks for P-state txns (from PREPARE record lock list)
```

Cost: one sequential scan from the checkpoint to the end of log, no page I/O.

### Redo (forward from redoLSN, repeating history)

```
redo():
  for r in log.scan(from = redoLSN) where r.type in {UPDATE, CLR} and r.redoable:
    if r.page not in DPT:            continue      // page was flushed and clean
    if r.lsn < DPT[r.page]:          continue      // older than first missing change
    P = fetch(r.page)                              // I/O only now
    verify_checksum(P) or repair_page(P)
    if P.pageLSN >= r.lsn: DPT[r.page] = P.pageLSN + 1; continue
    redo_apply(r, P); P.pageLSN = r.lsn            // no new log records
```

All updates are redone — winners, losers, and CLRs. No locks needed (no
concurrent transactions). Redo writes no log records.

### Undo (backward, all losers merged)

```
undo():
  heap = max-heap of TT[t].undoNextLSN for t in losers
  while heap not empty:
    n = heap.pop_max(); r = log.read(n); t = r.txn
    if r.type == CLR:
      nxt = r.undoNextLSN
    else:                                         // UPDATE
      undo(r)                                     // logs CLR(undoNext = r.prevLSN)
      nxt = r.prevLSN
    if nxt == 0: log.append(END, t) else heap.push(nxt)
  checkpoint()
```

Processing in global reverse LSN order lets one backward sweep of the log
serve all losers; reading records via prevLSN chains is random I/O if the log
tail is not cached.

### Why repeating history is required for correctness

After redo, every page in the DPT reflects exactly the crash-time state, so
every loser update whose record is in the log is present on its page exactly
once. Undo — physiological or logical — is therefore always applied to a
state that contains the effect it reverses; and pageLSN semantics ("all
records ≤ pageLSN applied") remain true. Selective redo (only winners) breaks
both: a loser's physiological "delete slot 3" or logical "delete key k"
would be applied to a page where the insert was never reinstalled, and a
pageLSN raised by a redone winner record would falsely claim the earlier,
unredone loser record is present. The pre-ARIES order "undo backward first,
then redo winners forward" (the sequence described in the Logging/Recovery
Subsystem entry) is sound only with page-granularity locking.

### Why CLRs bound work under repeated crashes

A CLR is redone (it is part of history) but never undone. Its undoNextLSN
points to the next record of that transaction still to undo. If the system
crashes during undo, the next restart redoes the CLRs and resumes undo at the
CLR's undoNextLSN: each original update is undone at most once regardless of
how many nested crashes occur, and log growth during recovery is bounded by
the number of loser updates. For media recovery from a long archive log this
matters even more: rollbacks long ago appear as ordinary redo of CLRs rather
than undo work.

## 6. Multilevel undo and nested top actions: a worked example

Setup (own example): heap page H, B+-tree leaf L, parent R. T1 inserts row
a; its key ka does not fit in L, so L splits into L and new leaf L2, and ka
lands in L2. T2 then inserts row b, key kb also lands in L2; T2 commits. T1 is
still active at the crash.

```
LSN  txn  page  record                                       prev  notes
10   T1   H     insert tuple a in slot 3 (undo: delete slot)  0
20   T1   L     SMO: move upper keys out of L                 10    nested top action begins
30   T1   L2    SMO: format L2, receive keys                  20
40   T1   R     SMO: add separator for L2                     30
50   T1   -     dummy CLR, undoNext = 10                      40    NTA ends
60   T1   L2    insert ka→(H,3) (redo physiological;          50
                undo LOGICAL: delete ka from index)
70   T2   H     insert tuple b in slot 4                      0
80   T2   L2    insert kb→(H,4)                               70
90   T2   -     COMMIT (forced)                               80
--- crash ---
```

Analysis: T2 committed (END written), T1 loser with undoNextLSN 60. Redo
repeats 10..80 subject to DPT/pageLSN tests. Undo of T1:

```
110  T1   L2    CLR for 60: delete ka (found by traversal;     undoNext = 50
                may now be on any leaf)
     T1         read 50: dummy CLR ⇒ jump to 10 (split is NOT undone)
120  T1   H     CLR for 10: delete slot 3                      undoNext = 0
130  T1   -     END
```

What would go wrong otherwise:
- Undoing 20..40 by before-images would put L back to its pre-split shape and
  discard L2, losing committed kb.
- Undoing 60 by restoring L2's pre-60 image would also discard kb (80 came
  later on the same page).
- If ka had migrated to another leaf because of a later split by someone
  else, page-oriented undo of 60 would modify the wrong page; logical undo
  re-traverses the tree.

Crash variants:
- **Crash after 30, before 50** (SMO incomplete): T1's lastLSN is 30; undo
  rolls back 30 and 20 *page-oriented* (page-level undo for incomplete
  operations). Safe because the tree latch / SMO protocol prevented other
  transactions from using the half-built L2.
- **Crash after 110**: redo repeats through 110; undo starts at T1's
  undoNextLSN = 50 (from CLR 110), jumps to 10, writes the CLR for 10, END.
  Work done before the crash is not redone as undo.

**Nested top action (NTA)**: a sequence of updates inside a transaction that
must persist even if the transaction rolls back (SMOs, file extension, space
allocation). Remember the transaction's lastLSN before the NTA (here 10);
perform and log the NTA's updates normally; then write a dummy CLR whose
undoNextLSN = that remembered LSN. An incomplete NTA (no dummy CLR) is
undone page-wise; a complete one is skipped. The dummy CLR need not be
forced: if it is lost, the NTA is undone, which is correct. An alternative
is a separate **system transaction** that commits the SMO on its own
(Graefe's terminology; widely used), which needs a commit record but no force.

In Weikum's general framework the same effect is achieved by writing a
high-level (L1) log record after an operation's page (L0) records with a
backward pointer to the transaction's previous L1 record, letting undo skip
the operation's L0 records once it is complete; during undo the inverse
operation itself is logged with L0 records plus a closing CLR for the whole
inverse. The framework generalises to deeper nesting (a stack of undo levels
embedded in the linear log), which EDBS suggests for composite services.

Idempotence summary:
- Page-level redo and undo-CLR redo: pageLSN test.
- High-level undo: no test needed, because repeating history guarantees every
  completed loser operation is present before undo, and CLRs prevent a
  second undo of the same operation.

## 7. Index-specific notes

- **ARIES/KVL** (Mohan, VLDB 1990) — key-value locking for B+-trees with next-key locking for phantoms.
- **ARIES/IM** (Mohan & Levine, SIGMOD 1992) — index management:
  key inserts/deletes logged physiologically for redo, logically for undo;
  SMOs as nested top actions; an SM bit / tree latch so traversals wait on
  in-progress SMOs.
- Delete of a key should keep a ghost/pseudo-deleted entry until commit so
  that undo (re-insert) cannot fail for lack of space and next-key locking
  keeps working; garbage-collect ghosts in a system transaction.
- Undo of an insert must never require a page split that could fail; with
  logical undo, space-consuming undo is possible (re-insert after delete), so
  reserve or use ghosts.

## 8. Media recovery and image copies

- Take a fuzzy image copy page by page while the system runs; record the
  redo point = min recLSN of the checkpoint preceding the copy start (pages
  copied may be any mix of old and new).
- Restore: copy device pages back; redo archive + online log from that redo
  point for pages of the device using the same pageLSN test; undo
  transactions in flight at the end of the replayed log. Because rollbacks
  that happened in the past are just redo of CLRs, the replay is a single
  forward pass.
- Single-page repair (Graefe & Kuno, PVLDB 2012): on checksum failure fetch
  that page's backup image and replay only its log records, found via a
  per-page prev-LSN chain or a page recovery index, while the rest of the
  database stays online.

## 9. Parallel, selective and instant restart

- **Parallel redo**: physiological records touch one page, so partition the
  redo stream by page id hash across workers; preserve per-page LSN order;
  prefetch pages listed in the DPT in recLSN order.
- **Selective / deferred redo**: redo high-priority page sets first, or defer
  pages on an unavailable device (mark offline, recover later).
- **New transactions during undo**: reacquire loser (and in-doubt) locks
  during analysis/redo from the log records; then admit new transactions
  while undo runs; conflicts with loser locks block until that loser is rolled back.
- **Instant restart / instant recovery** (Graefe, Guy & Sauer, Instant
  Recovery with Write-Ahead Logging, 2014/2016): admit transactions right
  after analysis; redo on demand when a page is first fixed (using the
  per-page log chain from its recLSN), undo on demand when a new
  transaction hits a loser's lock; background threads finish the rest.
  Restart availability becomes independent of the redo/undo backlog. The same
  idea gives instant media restore (restore pages on demand from backup +
  partitioned/sorted log archive).
- **Redo-only designs** (Sauer & Härder 2014, cited by EDBS Crash Recovery):
  keep the persistent state always committed (no steal of uncommitted data)
  so restart has no undo and redo can run concurrently with new work.
- **Shared-disk** (ARIES/SD, Mohan & Narang, VLDB 1991): each node has its own
  log; a page carries pageLSN across nodes; a node assigns a new LSN greater
  than both its log end and the page's pageLSN, so per-page order survives
  merging logs by LSN at recovery.

> **Beyond EDBS:** SQL Server's Accelerated Database Recovery (VLDB 2019)
> keeps ARIES analysis/redo but replaces most undo with logical revert from a
> persistent version store, so restart and rollback time stops depending on
> the longest transaction. Aurora (SIGMOD 2017) and Socrates (SIGMOD 2019)
> push redo into the storage tier, so database-instance restart does almost
> no redo; see `backup-pitr-and-disaster-recovery.md`.

## 10. Review checklist for an ARIES implementation

- [ ] Every page-touching record names exactly one page; multi-page ops emit
      one record per page.
- [ ] CLRs carry undoNextLSN and are never passed to undo.
- [ ] NTAs/system transactions for every SMO, allocation and catalog change
      that other transactions may depend on.
- [ ] Logical undo routines re-traverse and tolerate key migration.
- [ ] Analysis handles PREPARE, COMMIT-without-END, END-without-COMMIT (aborted).
- [ ] Redo never writes log; undo always does.
- [ ] Restart ends with a checkpoint so the next crash does not repeat work.
- [ ] Model-check or randomized-test crash during each pass (see
      `crash-testing-recovery-code.md`).

Sources: EDBS Multilevel Recovery and the ARIES Algorithm p.2344; Crash
Recovery p.660; Logging/Recovery Subsystem p.2135; Atomicity p.186. Papers as
named above; ARIES/KVL, ARIES/IM, ARIES/SD, instant recovery and ADR details
come from the cited papers, not from the EDBS entries.
