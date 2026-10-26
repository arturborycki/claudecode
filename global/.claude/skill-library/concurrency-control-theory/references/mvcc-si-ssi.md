# Multiversion theory, MVTO/MV2PL, snapshot isolation, SSI

Multiversion CC keeps several versions per item so that a read can be served
from an older version instead of conflicting with a newer write. Correctness
is no longer "equivalent to a serial execution" but "equivalent to a serial
execution *on a single-version database*" (one-copy serializability, 1SR).

## 1. Multiversion schedules

A multiversion schedule is `(ops, h, <)` where `h` is the **version function**
mapping each read `rj(x)` to the write `wi(x)` whose version it returns, with
`wi(x) < rj(x)`. Add a virtual initial transaction `t0` (writes every item)
and a final transaction `tf` (reads every item).

- Only one kind of conflict survives at the physical level: a read of a
  version depends on that version's writer. ww and rw "conflicts" do not
  constrain execution order directly (writes create new versions); they
  re-enter through the **version order**.
- **View equivalence** of MV schedules: same `h`.
- **Monoversion (standard) serial schedule**: serial, and every read returns
  the version of the most recent preceding write. An MV schedule is **MVSR
  (1SR)** iff it is view equivalent to some monoversion serial schedule.
- Testing MVSR is NP-complete in general (Papadimitriou and Kanellakis, TODS
  1984). With a *given* version order `<<` per item it is polynomial.

**MVSG for a version order `<<`** (BHG formulation): nodes = committed
transactions; edges
1. `ti -> tj` for every `rj(xi)` (reads-from, wr);
2. for every read `rk(xj)` and every other write `wi(xi)` of the same item:
   if `xi << xj` add `ti -> tj` (ti's version is older than the one read, so
   ti precedes the writer of the read version); otherwise (`xj << xi`) add
   `tk -> ti` (rk read a version older than ti's: anti-dependency, tk must
   serialise before ti because it did not see ti).

Weikum-Vossen (used in the EDBS SI/SSI entries) phrase the same thing as
three edge kinds: wr (`rj(xi)`), ww between consecutive versions whose later
version is read, and rw (`ri(xk)` with `xk << xj` gives `ti -> tj`). Adya's
DSG (see `isolation-levels-and-anomalies.md`) uses all ww edges directly.

Theorem: the schedule is MVSR iff there exists a version order whose MVSG is
acyclic. Engines fix `<<` = commit order (SI, SSI) or = timestamp order
(MVTO), which makes the check polynomial and implementable.

**k-version databases.** Bounding versions to `k` means a read may find its
needed version already reclaimed; the scheduler must then abort or delay.
Two-version systems (current + before-image) are the oldest practical form.

> EDBS (2018) still describes MVCC as rarely adopted except for two-version
> schemes; that is long obsolete. MVCC with snapshot reads is the default in
> PostgreSQL, Oracle, SQL Server (RCSI/SNAPSHOT), MySQL InnoDB, SAP HANA,
> HyPer/Umbra, CockroachDB, Spanner, and essentially every LSM-based engine
> (sequence numbers as versions; see `lsm-storage`).

## 2. MVTO (Reed 1978/1983)

Each txn has `ts(t)`; each version `xk` carries `wts(xk) = ts(writer)` and
`rts(xk)` = max ts of readers.

```
read(t, x):  pick version xk with largest wts(xk) <= ts(t); rts(xk) = max(rts, ts(t))
             (never rejected)
write(t, x): let xk = version with largest wts(xk) <= ts(t)
             if rts(xk) > ts(t): abort t   # a younger txn already read xk and
                                           # would have needed t's version
             else create version x_t with wts = ts(t)
commit(t):   wait until every writer of a version t read has committed (RC);
             abort t if any of them aborted
```

Reads never block or abort; writes abort when "too late". Read-only
transactions never abort. The commit-wait rule is easy to forget and is
required for recoverability.

## 3. MV2PL and certify locks (2V2PL; Bernstein and Goodman, TODS 1983)

Lock modes R, W, and **Certify (C)**. W locks are compatible with R (a
writer prepares an uncertified version in its workspace while readers keep
reading the last certified version); W conflicts with W, and C is
incompatible with R, W and C. At
commit the writer converts W to C, which waits for current readers of the
certified version to finish; then the new version becomes the certified one.

Properties: readers are blocked only during the short certify window, not
for the writer's whole lifetime; deadlocks remain possible (R holders waiting
on each other's certifies); serialisation order = certification order.

**Mixed method for read-only transactions** (Chan et al., SIGMOD 1982;
Bober and Carey): update transactions use strict 2PL on the latest version;
read-only transactions read a transaction-consistent snapshot as of their
start and take no locks. Serializable, because a snapshot of committed state
at a point in the 2PL commit order is a prefix of the serial order. This is
the precursor of SI and remains the cleanest way to give long analytical
readers non-blocking serializable reads in a locking engine.

## 4. Snapshot isolation (Berenson et al., SIGMOD 1995)

Two rules:
1. **Snapshot read**: `t` reads, for each item, the version of the most
   recent transaction that committed *before `t` started* (plus `t`'s own
   writes).
2. **First-committer-wins (FCW)**: two concurrent transactions (lifetimes
   overlap) that both write the same item cannot both commit. Implementations
   usually enforce **first-updater-wins** with a write lock: the second
   writer blocks on the first; if the first commits, the second aborts; if the
   first aborts, the second proceeds.

Version order = commit order. What SI prevents: dirty read/write, lost
update (FCW), inconsistent/read skew (atomic snapshot), the strict phantom
anomaly (re-reading a predicate returns the same snapshot). What it allows:

**Write skew (A5B).** Disjoint write sets, overlapping read sets.
```
x = 100, y = 200, invariant x + y > 0
T1: r(x=100) r(y=200)  -> withdraw 150 from x
T2: r(x=100) r(y=200)  -> withdraw 175 from y
w1(x=-50) w2(y=25) c1 c2      final x + y = -25: invariant broken
MVSG: T1 -rw-> T2 (T1 read y0, T2 wrote y2), T2 -rw-> T1: 2-cycle of rw edges
```
Classic forms: on-call doctors, meeting-room double booking via "check then
insert" (a predicate-level write skew: both check that no conflicting row
exists, both insert), uniqueness enforced in application code.

**Read-only transaction anomaly (Fekete, O'Neil, O'Neil, SIGMOD Record 2004).**
Even when the update transactions alone are serializable, a read-only
transaction can observe a state that no serial order explains.
```
checking x = 0, savings y = 0
T2 (withdraw 10 from x; charge 1 penalty if x + y would go negative)
T1 (deposit 20 into y)
T3 (read-only report)

r2(x0=0) r2(y0=0)               T2 snapshot: x+y = 0, will charge penalty
r1(y0=0) w1(y1=20) c1
r3(x0=0) r3(y1=20) c3           T3 sees deposit but not withdrawal
w2(x2=-11) c2
```
Without T3: serial order T2, T1 (T2 did not see the deposit) — fine. With
T3: T3 saw T1 but not T2, so T1 < T3 < T2, but T2 -rw-> T1 (T2 read y0,
T1 wrote y1) forces T2 < T1: cycle `T1 -wr-> T3 -rw-> T2 -rw-> T1`. The
penalty is inexplicable to anyone holding T3's report. Consequence for
engines: "read-only transactions are always safe under SI" is false; SSI's
read-only optimisations must be careful (see 6.4).

**Static analysis: SDG and dangerous structures (Fekete et al., TODS 2005).**
Theorem: every cycle in the MVSG of an SI history contains two consecutive
*vulnerable* edges `Ti -rw-> Tj -rw-> Tk` where each pair is concurrent
(vulnerable = rw edge between concurrent transactions; wr edges and ww edges
cannot be vulnerable under SI because of the snapshot and FCW rules). For a
fixed application program set, build the **static dependency graph** (edges
that some interleaving could produce, vulnerable if some interleaving makes
them concurrent rw edges). If the SDG has no cycle containing two consecutive
vulnerable edges, every execution under SI is serializable (TPC-C is the
standard example). Repairs for a dangerous edge `Ti -rw-> Tj`:
- **Materialise the conflict**: both programs update a shared row (e.g. a
  per-doctor-group counter), turning the rw edge into a ww conflict that FCW
  catches.
- **Promotion**: add an identity write (`UPDATE ... SET x = x`) or `SELECT
  ... FOR UPDATE` in `Ti` on the item `Tj` writes.
- Run `Ti` or `Tj` under strict 2PL (mixed isolation; needs platform support).
Automated detection: Jorwekar et al., VLDB 2007. Performance of the repairs
differs materially (Alomari, Fekete, Röhm, Inf. Sys. 2014): promotion via
FOR UPDATE can serialise readers.

## 5. Serializable snapshot isolation (Cahill, Röhm, Fekete, SIGMOD 2008 / TODS 2009)

Run SI, plus detect at runtime the structure from the theorem and abort a
participant.

**Tracking rw-antidependencies.** Two temporal cases for `Ti -rw-> Tj`
(`Ti` reads an older version than the one `Tj` writes):
1. `Tj` wrote first, `Ti` reads later: visible during the read, because the
   version-visibility check skips `Tj`'s newer (invisible) version — record
   the edge right there.
2. `Ti` read first, `Tj` writes later: requires remembering reads. Readers
   take **SIREAD** locks, which block nothing; a writer checks for SIREAD
   locks on the item (and on covering index ranges/pages/relations for
   predicates) and records edges from each concurrent holder.

SIREAD locks must **outlive the reader's commit** until every transaction
concurrent with it has finished, since a later writer can still create an
edge from the committed reader.

**Abort rule (basic).** Each transaction keeps flags (Cahill) or lists
(PostgreSQL) of inbound and outbound rw edges. A transaction with both an
inbound and an outbound rw edge from/to concurrent transactions is a
**pivot**; abort it (or another member) before the structure can complete a
cycle. This is conservative: it ignores whether the rest of the cycle exists.

**False positives.** A pivot with in and out rw edges is necessary for a
cycle, not sufficient. Sources: no closing path back from `Tk` to `Ti`;
coarse SIREAD granularity (page/relation locks after promotion produce edges
for rows never actually read); flags instead of lists (cannot apply
commit-order tests); summarised committed transactions. Every false positive
is a serialization failure the application must retry, so the abort rate,
not the overhead of tracking, is usually what users notice.

## 6. PostgreSQL SSI (Ports and Grittner, VLDB 2012; PostgreSQL 9.1+)

REPEATABLE READ = SI; SERIALIZABLE = SSI. Design points worth copying:

1. **Lists, not flags.** Each `SERIALIZABLEXACT` keeps lists of in and out
   conflicts, enabling precise ordering tests.
2. **Commit-ordering optimisation.** In the dangerous structure
   `T1 -rw-> T2 -rw-> T3`, a real cycle requires `T3` to commit first among
   the three. So the structure is only dangerous if `T3` committed before
   `T1` and `T2` (and, when `T1` is read-only, before `T1` took its
   snapshot). Many potential pivots are thereby cleared.
3. **Read-only optimisations.** A read-only `T1` can only be part of an
   anomaly if `T3` committed before `T1`'s snapshot. A read-only transaction
   whose snapshot has no concurrent read-write transactions that could
   become `T3` is on a **safe snapshot** and can drop SIREAD tracking.
   `SERIALIZABLE READ ONLY DEFERRABLE` waits for such a snapshot, then runs
   with zero abort risk and no tracking: the right mode for long reports and
   `pg_dump`.
4. **Granularity and promotion.** SIREAD locks are tuple-, page- or
   relation-level; many tuple locks on one page are promoted to a page lock,
   many page locks to a relation lock (bounded shared memory). Index scans
   lock the index pages/ranges they visited, giving phantom detection (an
   insert into a locked B-tree leaf page conflicts); a sequential scan takes
   a relation-level SIREAD lock. Coarser locks mean more false positives.
5. **Summarisation.** When memory for committed-transaction state runs out,
   old committed transactions are summarised (keeping only conservative
   information such as earliest out-conflict commit), trading precision for
   bounded memory.
6. **Victim choice ("safe retry").** Prefer aborting a transaction such that
   an immediate retry will not hit the same structure: typically abort the
   pivot unless it already committed; never abort a committed transaction;
   reports SQLSTATE 40001 (`serialization_failure`).
7. **Interaction with 2PC.** Prepared transactions must persist enough SIREAD
   and conflict state to survive a crash between PREPARE and COMMIT.
8. **Not on hot standby.** Serializable mode is rejected on read replicas,
   because the replica does not see the primary's rw-dependency tracking (a
   standby query could be the read-only `T1` of an anomaly).

## 7. Alternatives in the SSI family

| Design | Idea | Trade-off |
|---|---|---|
| Cahill SSI | flags per txn, abort on pivot | simplest, most false positives |
| PostgreSQL SSI | lists + commit ordering + read-only rules | fewer aborts, more state |
| PSSI (Revilak, O'Neil, O'Neil, ICDE 2011) | maintain full MVSG, certify cycles at commit | precise; graph maintenance cost |
| Serial Safety Net (Wang, Johnson, Fekete, Pandis, DaMoN 2015) | per-txn high/low watermark timestamps from dependencies; commit if `pstamp < sstamp` | cheap, generic certifier over several CC schemes |
| Lomet et al. ICDE 2012 (timestamp range conflict management) | assign commit timestamps from a range consistent with the serialisation order | serializable with snapshot property; order ≠ commit order |
| Han et al. ICDE 2014 | latch-free/partitioned SSI structures for multicore | engineering of the tracking structures |

## 8. In-memory MVCC engines

> **Beyond EDBS: Hekaton (Larson et al., VLDB 2011; Diaconu et al., SIGMOD
> 2013).** Versions carry `[begin, end)` timestamps; a transaction's commit
> timestamp is taken at precommit. Optimistic MVCC: for SERIALIZABLE it
> validates at commit that every version it read is still visible as of its
> end timestamp (read stability) and rescans its ranges to detect phantoms;
> REPEATABLE READ skips the rescan, SNAPSHOT skips validation. Transactions
> may read versions of transactions that are still validating (speculative
> reads) and take a **commit dependency** on them (cascading abort only
> within that window). No lock manager, no latches on the data path.

> **Beyond EDBS: HyPer MVCC (Neumann, Mühlbauer, Kemper, SIGMOD 2015).**
> In-place updates; the before-images in the transaction's undo buffer form a
> newest-to-oldest version chain, so scans of unmodified data run at full
> speed. Serializability by precision-locking-style validation: at commit,
> check the transaction's read predicates against the undo buffers of
> transactions that committed during its lifetime.

> **Beyond EDBS: Cicada (Lim, Kaminsky, Andersen, SIGMOD 2017).** Multi-
> version OCC with loosely synchronised per-thread clocks (no shared
> counter), best-effort inlining of the newest version in the record head,
> early aborts and contention regulation (backoff), and rapid garbage
> collection. Representative of the "OCC + MVCC + decentralised timestamps"
> design that wins on many-core OLTP benchmarks.

## 9. Engineering MVCC: things that go wrong

- **Garbage collection horizon.** The oldest active snapshot pins every newer
  version; a forgotten idle-in-transaction session bloats storage without
  bound. Track the horizon explicitly; expose it; cap snapshot age.
- **Version chain direction.** Newest-to-oldest (Oracle/InnoDB undo, HyPer)
  favours current readers; oldest-to-newest (PostgreSQL heap tuples with
  `xmin/xmax`, append-only) makes old-snapshot reads cheap and current reads
  potentially long. Delta vs full-copy versions trade write amplification
  for read reconstruction cost.
- **Visibility check correctness.** Commit status must be published
  atomically with (or before) the commit timestamp becoming visible;
  otherwise a reader can see "committed at ts <= my snapshot" for a
  transaction whose writes it has already skipped. PostgreSQL's snapshot is
  `(xmin, xmax, in-progress list)`, not a single number, for this reason.
- **Index entries vs versions.** Secondary indexes point to versions or to a
  version chain head; with in-place updates of indexed columns an index scan
  must recheck visibility and key equality on the heap version.
- **SI is not serializable**, and "REPEATABLE READ" in a product may be SI
  (PostgreSQL), may be snapshot reads plus non-FCW locking writes (InnoDB),
  or may be lock-based RR (DB2, SQL Server). Document which.
- **Long writers under FCW** abort late and repeatedly against short
  writers on hot rows; consider locking (first-updater-wins with wait) or
  escrow for counters.

Sources: EDBS "Multiversion Serializability and Concurrency Control"
(p.2454), "Snapshot Isolation" (p.3513), "Serializable Snapshot Isolation"
(p.3476), "Correctness Criteria Beyond Serializability" (p.640), "Tuning
Concurrency Control" (p.4252, SI in the value-of-serializability experiment),
"SQL Isolation Levels" (p.3681).
