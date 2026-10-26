# Semantics-based CC, escrow, multilevel/nested/open-nested transactions, sagas, ACTA, STM, real-time CC

Read/write conflicts are the most conservative conflict relation possible.
Whenever the engine knows more about an operation (it is an increment, a set
insert, an index-key insert) it can declare fewer conflicts and accept more
schedules, provided it also knows how to undo the operation *logically*.
Concurrency and recovery must be designed together at each level.

## 1. Commutativity-based conflict relations

Replace "same item, one writes" by "do not commute". The commutativity
reduction argument from `serializability-theory.md` carries over unchanged:
a history is serializable if adjacent commuting operations of different
transactions can be swapped into a serial order.

Flavours (Weihl, IEEE Trans. Computers 1988; Badrinath and Ramamritham,
TODS 1992):

| Notion | `p`, `q` commute when | Example |
|---|---|---|
| State-independent | for every state, `pq` and `qp` yield the same state and return values | `insert(S,a)` vs `insert(S,b)`, `a != b` |
| Argument-dependent | commute for these specific arguments | inserts of distinct keys; deposit to different accounts |
| Return-value commutativity | commute given the values actually returned | `incr()` vs `incr()` if neither returns the counter; `withdraw` that succeeded on ample balance |
| Forward commutativity | both orders defined and equivalent whenever both are defined in the current state | used with update-in-place + intentions lists (deferred update) |
| Backward commutativity | `q` after `p` can be moved before `p` | used with update-in-place + undo (immediate update) |
| Recoverability (Badrinath-Ramamritham) | `q` is recoverable relative to `p` if `q`'s return value does not depend on whether `p` executed | two `push` operations: do not commute, but each is recoverable relative to the other |

Recoverability-based CC lets non-commuting but recoverable operations run
concurrently and records a **commit dependency**: if `q` (by `tj`) is
executed after `p` (by `ti`) and is recoverable relative to it, then `ti`
must commit before `tj` if both commit; if `ti` aborts `tj` may still commit.
Operations that are neither commutative nor recoverable relative to an
uncommitted operation wait. Deriving compatibility tables: from an ADT's
specification build the conflict table per (operation, operation, return
value); Chrysanthis, Raghuram, Ramamritham (SIGMOD 1991) give a methodology
including the ordering among component objects.

Engine-level instances: index key insert/delete on distinct keys (the
reason key-value locking exists); increment locks on aggregate rows of
materialised summary views (increments commute with increments, not with
reads); append to a log or queue with relaxed order (enqueue/enqueue commute
if FIFO order across transactions is not required).

## 2. Escrow (O'Neil, TODS 1986)

Hot aggregate quantities (stock on hand, account balance, seat count)
updated only by bounded increments and decrements. Increments commute, but
a decrement must not drive the value below a floor; escrow reserves the
amount instead of locking the value.

Per escrow item: `val` (value if all pending transactions abort), `inf`
(lowest reachable value: all pending decrements commit, all pending
increments abort), `sup` (highest reachable value), and bounds `[Min, Max]`.

```
escrow_inc(x, t, d):
  if d < 0: require x.inf + d >= Min   else: require x.sup + d <= Max
            (otherwise wait, back-order, or reject)
  if d < 0: x.inf += d  else: x.sup += d
  log escrow record (t, x, d)
commit(t): for each escrow record (t, x, d):
           x.val += d; if d < 0: x.sup += d  else: x.inf += d
abort(t):  for each escrow record (t, x, d):
           if d < 0: x.inf -= d  else: x.sup -= d
invariant: Min <= inf <= val <= sup <= Max ; once no txn pending, inf = val = sup
```

Worked example (Min 0, Max 2000, start `val=inf=sup=1000`):

| Step | val | inf | sup |
|---|---|---|---|
| T1 inc -500 (order) | 1000 | 500 | 1000 |
| T2 inc +500 (return) | 1000 | 500 | 1500 |
| T2 commits | 1500 | 1000 | 1500 |
| T1 aborts | 1500 | 1500 | 1500 |

Any order of commits and aborts lands on the same final `val`. Escrow
operations commute with each other but **not with reads or writes**: a plain
read of an item with pending escrow has no single value; offer a range read
`[inf, sup]` or make reads wait. Recovery is special-purpose: escrow items
are excluded from before/after-image logging and recovered from the escrow
log (each pending reservation must be resumable as commit or abort).
Distribution: an escrow reservation can act as the participant's "prepare"
for the reserved amount, so a slow phase 2 of 2PC does not block other
escrow updaters of the same item. Ancestors: IMS Fast Path field calls
(verify-and-change at commit).

## 3. Multilevel transactions (Weikum TODS 1991; Moss, Griffeth, Graham 1986; Beeri, Bernstein, Goodman JACM 1989)

Transaction trees whose levels match engine layers, e.g. L2 transaction ->
L1 record/key operations (`fetch`, `store`, `search`, `modify`) -> L0 page
reads/writes. Leaves are totally ordered where they conflict.

**Order on composite operations**: `o1 < o2` iff all leaf descendants of
`o1` precede all of `o2`. A subtree is **isolated** if its leaves are totally
ordered and its root is ordered with respect to every operation outside it.

**Tree reduction rules** (a schedule is *tree-reducible* = multilevel
serializable if they reduce it to a serial order of roots):
1. *Commutativity rule*: swap adjacent ordered leaves `p < q` of different
   transactions if both are isolated, commute, and have no ordered
   non-commuting ancestors `p' < q'`.
2. *Ordering rule*: unordered commuting leaves may be ordered arbitrarily.
3. *Pruning rule*: replace an isolated subtree by its root.

A schedule can be non-serializable at the page level (two record operations
on the same page interleave in both orders) yet multilevel serializable,
because page-level effects are encapsulated inside record operations whose
L1 semantics commute.

**Protocol: layered 2PL** (enforce order-preserving CSR per adjacent level
pair):
- before executing `f(x)`, acquire an `f`-mode lock on `x` at that level;
- after any lock acquired on behalf of a child of `o` is released, `o` may
  acquire no more child locks (2PL per subtransaction);
- when `o` completes, release all locks of its descendants but keep the lock
  on `o` itself until `o`'s parent completes.

Releasing lower-level locks at subtransaction end is what makes the model
"open". In engines: page **latches** for the L0 subtransaction, **key
locks** at L1 held to commit. Consequence for recovery: after the L0 locks
are released, other transactions may change the page, so undo must be by
**inverse L1 operations** (logical undo: delete the inserted key wherever it
now lives), not by restoring page images. This is multilevel recovery
(Lomet's MLR, SIGMOD 1992; ARIES's logical undo with CLRs). See
`recovery-and-durability`.

**Object-model (open nested) transactions** drop the balanced-tree/layering
constraint: arbitrary method invocation trees across ADT objects. The same
reduction ideas apply with extra difficulties (no strict level-by-level
proof order). Relevant to middleware, composite services and transactional
memory with open nesting (Ni et al., PPoPP 2007).

## 4. Closed nested transactions (Moss 1981/1985)

Tree of subtransactions; leaves do the work. Commit/abort rules:
1. A subtransaction commits only after all children are resolved.
2. Its commit is *relative to its parent*: effects become permanent only when
   the top-level transaction commits (subtransactions are not durable).
3. Aborting a subtransaction aborts its whole subtree, even locally
   committed children; the parent may retry, try an alternative, or ignore.

Locking (Moss): a transaction *holds* a lock while active and *retains* it
after its subtransaction commits (inherited by the parent).
- Write lock grantable if no other transaction holds it in any mode and all
  retainers are ancestors of the requester.
- Read lock grantable if no other transaction holds a write lock on it and
  every transaction retaining a write lock is an ancestor of the requester.
- On commit, the parent inherits all held/retained locks in the same modes.
- On abort, locks held/retained by the aborted transaction are released;
  ancestors that were retaining keep retaining.

Savepoints emulate the recovery behaviour of nesting (partial rollback) but
not the intra-transaction concurrency or lock inheritance. Systems: Argus,
Camelot/Encina, Berkeley DB.

## 5. Open nested models, sagas, compensation, semantic atomicity

**Open nested**: subtransactions commit independently and externalise
results before the top level commits; aborting the parent requires
**compensation**. Component types: vital (must commit for parent to commit),
non-vital (failure tolerated), contingency (alternative executed if primary
aborts; commits only if primary aborted), compensating, and triggered
(immediate, deferred to before commit, or detached).

**Compensating transaction** `C` for `T`: for any concurrent set `H`, the
state after `T H C` is *equivalent* (satisfies the same constraints), not
necessarily identical, to that after `H` alone. Not always possible (external
effects like sending money or a missile), and not always safe: compensating
"transfer $75 into account 3" may overdraw account 3 if a concurrent
withdrawal used the money; the compensation then has to be different
(semantic, application-chosen) or the transactions must be classified as
incompatible and run with ordinary isolation.

**Saga** (Garcia-Molina and Salem, SIGMOD 1987): sequence `T1..Tn` of ACID
transactions with compensations `C1..Cn-1`. Guarantee: either `T1 ... Tn` or
`T1 ... Tj Cj ... C1` for some `j < n`. Isolation is given up between steps
(others see intermediate states); atomicity is semantic. Requirements:
compensations must not fail logically and must survive crashes (log the
saga's progress and the compensation's internal state; on restart continue
compensations forward rather than aborting them, like ARIES CLRs never being
undone). Modern microservice "saga orchestration" is the same model;
countermeasures for lost isolation (semantic locks/"pending" flags,
commutative updates, re-reading values, version checks) are exactly the
semantic-consistency tools of the 1980s.

**Semantic atomicity** (Garcia-Molina TODS 1983): a transaction of
subtransactions `Si` with compensations `Ci` is semantically atomic iff all
`Si` committed, or every committed `Si` has its `Ci` committed. Benefits:
subtransactions release resources early, no cascading aborts, no long waits.
Differs from savepoints: savepoint rollback does not externalise and does
cascade to readers.

**O2PC (Levy, Korth, Silberschatz, SIGMOD 1991)**: participants commit
locally right after voting yes (releasing locks); if the global decision is
abort, they run compensations. Trades blocking for compensation complexity.

**Split / join transactions (Pu, Kaiser, Hutchinson, VLDB 1988)**: `split`
divides a running transaction into two serializable transactions with
declared read/write sets that commit or abort independently (commit part of
the work early, hand work to a colleague); `join` merges a transaction's
results into another. Targets open-ended design activities.

**Flex transactions** (multidatabases): sub-transactions with alternatives,
internal (ordering) and external (time/event) dependencies, success even if
some sub-transactions fail.

**Generalised ACID**: Recovery, Consistency, Visibility, Permanence replace
A/C/I/D so that models can relax each axis separately (e.g. visibility of
partial results without permanence).

## 6. ACTA (Chrysanthis and Ramamritham, TODS 1994)

First-order formalism to specify and compare transaction models. Building
blocks: history of significant events (begin, commit, abort, split, join,
delegate); per-object effects; **dependencies** between transactions; the
**view** (which object states a transaction may see); the **conflict set**
(operations against which conflicts are checked); **delegation** (transfer
responsibility for committing/aborting an operation to another transaction).

Dependencies used across models:
- Commit dependency `tj CD ti`: if both commit, `ti` commits first.
- Abort dependency `tj AD ti`: if `ti` aborts, `tj` aborts.
- Weak-abort, termination, exclusion, compensation, begin-on-commit, etc.

Examples: closed nesting = child-to-parent commit dependency plus
parent-abort-implies-child-abort; saga = compensation dependencies along the
chain; semantic atomicity in ACTA:
`(∀ Si ∈ T: commit(Si) ∈ H → commit(Ci) ∈ H) ∨ (∀ Sj ∈ T: commit(Sj) ∈ H)`.
Delegation explains lock inheritance (child delegates to parent at commit)
and split transactions. Practical use: when designing a new transactional
feature (autonomous transactions, detached triggers, "fire and forget"
writes, speculative reads), write its dependencies in ACTA terms and check
that the recovery manager enforces each one.

## 7. Correctness criteria beyond serializability

| Criterion | Idea | Domain |
|---|---|---|
| Multiversion serializability (1SR) | reads may use older versions | MVCC (see `mvcc-si-ssi.md`) |
| Semantic consistency (Garcia-Molina 1983) | user-declared transaction types, compatibility sets, steps, countersteps; sensitive transactions must see consistent data | distributed apps with semantic knowledge |
| Predicatewise serializability (Korth and Speegle 1988) | integrity constraints in CNF; schedule must be serializable when projected onto each conjunct's items; needs fixed-structure txns, delayed reads, or ordered conjuncts | CAD, office systems |
| Epsilon serializability (Ramamritham and Pu 1995) | each transaction bounds imported/exported inconsistency; update ETs serializable among themselves; ε = 0 gives SR | read-mostly with tolerance |
| Quasi-serializability (Du and Elmagarmid 1989) | global transactions serial, local schedules serializable, accounting for indirect conflicts through local transactions | multidatabases |
| Two-level serializability (Mehrotra et al. TODS 1998) | local schedules serializable and projection on global transactions serializable | multidatabases with constraint structure |
| Eventual consistency | replicas may diverge but converge | replicated data (see `replication-protocols`) |

Engine relevance: these are the formal names for things products do
informally (e.g. "statistics/heartbeat updates may be read dirty", "bounded
staleness reads"). Writing the criterion down makes the guarantee testable.

## 8. Software transactional memory and its relation to DB CC

STM groups shared-memory accesses into atomic, isolated transactions (ACI
without D). Same theory, different constraints: very short transactions, no
I/O, arbitrary code (so opacity: even doomed transactions must see consistent
state, since a zombie can segfault), and non-transactional accesses that
bypass the protocol (strong vs weak atomicity).

Design space mirrors DB CC: eager vs lazy versioning (undo log vs redo
buffer), eager vs lazy conflict detection (encounter-time locks vs commit-time
validation), visible vs invisible readers. TL2 (Dice, Shalev, Shavit, DISC
2006): global version clock, per-location versioned write locks, commit-time
locking of the write set, read-set validation against the read version — the
same structure as Silo-style OCC in in-memory databases.

> **Beyond EDBS.** Hardware TM (Intel TSX/RTM) has been used inside
> main-memory engines to replace latches for short critical sections, with
> timestamp-ordered fallbacks because of capacity aborts (Leis, Kemper,
> Neumann, ICDE 2014). Treat HTM as a latch-elision device, not a transaction
> mechanism: capacity limits, spurious aborts and vendor disablement make it
> unsuitable as the only path.

## 9. Real-time concurrency control

Correctness includes timeliness. Transactions have arrival `a`, release `r`,
worst-case execution `e`, deadline `d` (`a <= r < d`, `r + e <= d`);
deadlines are **hard** (miss = failure), **firm** (late result worthless:
abort tardy transactions), or **soft** (late result has reduced value). Data
has **temporal consistency**: absolute validity interval `avi` (`now - ts(x)
<= avi(x)`) and relative validity for derived data (timestamps of inputs
within `rvi` of each other). Metrics: deadline miss ratio, tardiness, value
lost, freshness violations — not throughput.

Plain 2PL suffers **priority inversion** (high-priority waits for a
low-priority holder, which is preempted by medium-priority work), unbounded
blocking, deadlocks.
- **2PL-HP (high priority)**: a requester with higher priority aborts the
  lower-priority holder; otherwise waits. Variants consider remaining
  execution time to avoid wasteful aborts.
- **Priority inheritance / priority ceiling** (Sha, Rajkumar, Lehoczky):
  holders inherit the priority of the highest waiter; ceiling protocols bound
  blocking to one critical section and prevent deadlock.
- **Real-time OCC with priority wait** (Haritsa, Carey, Livny 1992): a
  validating transaction that conflicts with higher-priority active
  transactions waits ("on the shelf") until they finish, then commits (or is
  restarted if one of them committed a conflicting write). Shown superior to
  locking for firm deadlines in their studies; forward validation is
  required to pick the victim side.
- **PROMPT** commit (Haritsa, Ramamritham, Gupta, TPDS 2000): prepared
  cohorts lend uncommitted data to new transactions (borrowers abort if the
  lender aborts; a borrower that finishes first waits on the shelf).
  Bounded cascading in exchange for not blocking on prepared data.
- Distributed RT-OCC: local validation may cause "wasteful" aborts if the
  validator later fails global validation.

## Sources

EDBS "Semantics-Based Concurrency Control" (p.3435), "Escrow Transactions"
(p.1332), "Multilevel Transactions and Object-Model Transactions" (p.2353),
"Nested Transaction Models" (p.2485), "Open Nested Transaction Models"
(p.2597), "Sagas" (p.3273), "Compensating Transactions" (p.528), "Semantic
Atomicity" (p.3381), "Split Transactions" (p.3665), "Extended Transaction
Models and the ACTA Framework" (p.1428), "Generalization of ACID Properties"
(p.1579), "Correctness Criteria Beyond Serializability" (p.640), "Software
Transactional Memory" (p.3543), "Real-Time Transaction Processing" (p.3114),
"Transaction Models: The Read/Write Approach" (p.4194), "B-Tree Locking"
(p.345, increment locks).
