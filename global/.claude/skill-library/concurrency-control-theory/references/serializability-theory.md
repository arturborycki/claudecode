# Serializability theory, recoverability, and non-locking schedulers

The page (read/write) model is the lingua franca of concurrency control: every
higher-level operation eventually becomes indivisible reads and writes of
items (pages, records, keys). Everything in this file is stated in that model;
`semantic-and-extended-transaction-models.md` lifts it to operations with
richer conflict relations.

## 1. Objects of the theory

**Transaction.** A finite partial order `t = (op, <)` of steps `r(x)`/`w(x)`
over items `D = {x, y, ...}`; any two steps of `t` on the same item where at
least one writes must be ordered. Common simplifications: each item read and
written at most once per transaction, no read after own write. Blind writes
(write without prior read) remain allowed and are exactly what separates view
from conflict serializability.

**Herbrand semantics.** With no knowledge of program logic, assume each write
of `t` stores an unknown function of *everything `t` has read so far*. Two
histories are "equivalent" only if they are equivalent under every
interpretation. This is the conservative assumption that makes the theory
syntactic and implementation-agnostic.

**History** over `T = {t1..tn}`: contains all steps of all `ti`, exactly one
terminal `ci` or `ai` per transaction placed after all its steps, preserves
each `<i`, and totally orders every pair of conflicting steps from different
transactions. A **schedule** is a prefix of a history (what a running
scheduler has emitted so far). **Serial**: transactions do not interleave.
**Committed projection** `CP(s)`: drop all operations of non-committed
transactions; correctness classes are normally defined on `CP(s)` and then
required to be *prefix-closed* (every prefix's committed projection is in the
class) so that an online scheduler can enforce them.

**Conflict.** `p` in `ti`, `q` in `tj`, `i != j`, same item, at least one is a
write. Three kinds, which later become the three edge types of every
dependency graph:

| Pair | Name (Adya) | Edge `ti -> tj` meaning |
|---|---|---|
| `wi(x) ... rj(x)` | wr / read-dependency | tj observed ti's effect |
| `wi(x) ... wj(x)` | ww / write-dependency | tj overwrote ti's version |
| `ri(x) ... wj(x)` | rw / anti-dependency | ti did *not* observe tj's effect |

## 2. The serializability hierarchy

```
 FSR  (final-state)    same final state under Herbrand semantics
  ⊃ VSR (view)         same reads-from relation + same final writers
   ⊃ CSR (conflict)    same order of every conflicting pair
    ⊃ OCSR (order-preserving CSR)  + non-overlapping txns keep real-time order
     ⊃ COCSR (commit-order CSR)    serialization order = commit order
```

**View serializability (Papadimitriou 1979; Yannakakis 1984).** Two histories are view
equivalent iff (i) every read reads from the same write in both and (ii) the
last write on every item is the same. Then every write computes the same
value and the final state matches. Testing VSR is NP-complete (Papadimitriou
1979); the polygraph test generalises the precedence graph with "either/or"
edge pairs. Classic VSR-but-not-CSR history (blind writes):

```
r1(x) w2(x) w1(x) w3(x)   c1 c2 c3
conflict graph: t1->t2 (r1 x < w2 x), t2->t1 (w2 x < w1 x): cycle -> not CSR
view: t1 reads initial x, final writer t3; serial t1 t2 t3 has same views -> VSR
```

Without blind writes, VSR = CSR. Engines never test VSR; it matters only as
the justification for the **Thomas write rule** (below).

**Conflict serializability.** `s` is CSR iff its conflict (serialization,
precedence) graph `SG(s)` over committed transactions is acyclic; any
topological order is an equivalent serial order. Test cost: `O(|ops|^2)`
naive edge construction, `O(V+E)` cycle check. Equivalent characterisation by
commutativity: adjacent steps of different transactions may be swapped when
they do not conflict (`ri(x) rj(y)`, `ri(x) wj(y)` for `x != y`, `wi(x)
wj(y)` for `x != y`); `s` is CSR iff a finite sequence of such swaps yields a
serial history. The swap formulation is the one that generalises: replace
"conflict" by "does not commute" and the whole theory transfers to arbitrary
operation types (counters, sets, queues, index keys).

Worked reduction:
```
w1(x) r2(x) w1(y) w1(z) r3(z) w2(y) w3(y) w3(z)
swap r2(x) right past w1(y), w1(z)   (different items)
swap r3(z) right past w2(y)          (different items)
=> w1(x) w1(y) w1(z) r2(x) w2(y) r3(z) w3(y) w3(z)  = t1 t2 t3
```

**Order-preserving CSR** forbids reordering transactions that did not overlap
in real time; this is the single-node analogue of strict serializability and
is what users silently expect ("my committed write is visible to a
transaction I start afterwards"). **Commit-order serializability (COCSR)**
requires the equivalent serial order to match commit order; it is what
strong strict 2PL produces and what composes across autonomous sites
(commitment ordering, Raz 1992), because each site's local order is visible
in its commit sequence.

> **Engine relevance.** The class you guarantee determines what you can test
> with an oracle. If you claim COCSR you can check histories by sorting
> committed transactions by commit timestamp and replaying serially; if you
> claim only CSR you need graph search (see `isolation-levels-and-anomalies.md`
> on Elle-style checkers).

## 3. Recoverability classes (orthogonal to serializability)

Serializability of the committed projection says nothing about aborts. Let
"`tj` reads `x` from `ti`" mean `rj(x)` returns `ti`'s version.

| Class | Rule | What breaks without it |
|---|---|---|
| RC (recoverable) | if `tj` reads from `ti`, then `ci < cj` | `tj` commits, then `ti` aborts: committed state depends on a value that never existed; durability violated |
| ACA (avoids cascading aborts) | `tj` reads `x` from `ti` only after `ci` | abort of `ti` forces abort of all readers, transitively; unbounded undo work |
| ST (strict) | no `rj(x)` or `wj(x)` after `wi(x)` until `ti` terminates | before-image undo is wrong: restoring `ti`'s before-image would wipe out `tj`'s write (or reinstate a stale value) |
| RG (rigorous) | ST + no `wj(x)` after `ri(x)` until `ti` terminates | serialization order may differ from commit order |

Inclusions: `RG ⊂ ST ⊂ ACA ⊂ RC`. RG histories are also COCSR. Strictness is
the property physical undo logging relies on: only under ST is "restore the
before-image" a correct inverse of a write, because nobody else has written
the item since. This is the precise reason dirty writes (P0) must be forbidden
at every isolation level, including READ UNCOMMITTED.

Unified theory (Alonso, Vingralek, Agrawal, Breitbart, El Abbadi, Schek,
Weikum 1994): model an abort as the sequence of inverse writes in reverse
order and require the *expanded* history to be serializable and reducible
(SOT, serializable with ordered termination). Its value for engine builders:
the same framework covers logical undo (compensation) in multilevel recovery.

## 4. Scheduler taxonomy

A scheduler receives steps one at a time and for each either **outputs** it,
**delays** it, or **rejects** it (aborting the issuer). Correctness: every
output schedule's committed projection is in the target class (prefix-closed).

```
                       concurrency control
            ┌────────────────┴─────────────────┐
       pessimistic                         optimistic
   ┌────────┴────────┐                (validate at commit)
 locking         non-locking
 ┌──┴───┐        (timestamp ordering,
2PL   non-2PL     serialization graph testing)
      (tree / DAG protocols, altruistic)
```

Hybrids split the problem into rw-synchronisation and ww-synchronisation and
solve each with a different protocol (BHG 1987); e.g., 2PL for rw and Thomas
write rule for ww. In practice the market converged on (strict) 2PL and on
MVCC variants; the other classes survive as validation layers (OCC in
in-memory engines, SGT in SSI-style certifiers).

## 5. Serialization graph testing (SGT)

Maintain `SG` over active and recently committed transactions; on each step
add its conflict edges; reject the step if it would close a cycle.

- Accepts exactly CSR (the most permissive conflict-based scheduler).
- Cost: cycle check per edge insertion; incremental reachability or
  dynamic topological order (Pearce-Kelly) keeps it near `O(affected)` in
  practice.
- **Node deletion problem**: a committed `ti` cannot be dropped from `SG`
  while it has an incoming path from an active transaction, because a future
  edge from it could still close a cycle. Safe rule: delete `ti` once it is
  committed and has no incoming edges (from active transactions). Long
  readers pin arbitrarily many committed nodes; memory must be bounded
  (summarise or abort).
- Recoverability is not implied; combine with commit ordering (delay `cj`
  until all transactions `tj` read from have committed) for RC, or withhold
  uncommitted writes from readers for ACA/ST.

Precise SSI implementations (PSSI, Revilak et al. 2011) are SGT on the
multiversion graph; Cahill-style SSI is a conservative approximation that
looks only at two adjacent rw edges (see `mvcc-si-ssi.md`).

## 6. Timestamp ordering (TO)

Each transaction gets a unique timestamp `ts(t)` at start; the TO rule: if
`pi(x)` and `qj(x)` conflict, `pi` must execute before `qj` iff `ts(ti) <
ts(tj)`. The serialization order is fixed in advance; conflicts arriving "too
late" abort the latecomer.

Basic TO bookkeeping per item: `RTS(x)` (max ts of readers), `WTS(x)` (ts of
last writer).

```
read(t, x):
  if ts(t) < WTS(x): abort t            # x already overwritten by a younger txn
  else: read; RTS(x) = max(RTS(x), ts(t))

write(t, x):
  if ts(t) < RTS(x): abort t            # a younger txn already read the old value
  if ts(t) < WTS(x):
      Thomas write rule: skip the write  # obsolete; a younger write supersedes it
      (or abort, for strict CSR)
  else: write; WTS(x) = ts(t)
```

Properties and pitfalls:
- Deadlock-free (no waiting), but starvation-prone for long transactions
  (restart with a *new* timestamp, otherwise they abort forever).
- Thomas write rule yields VSR, not CSR; correct only if the skipped write is
  truly dead (no later read by `t` of its own write; recovery must not
  "restore" around it).
- Basic TO is not recoverable: a reader may read an uncommitted version. Strict
  TO delays reads/writes on `x` until the writer of `WTS(x)` terminates
  (essentially a lock held by the last writer).
- Every read writes `RTS(x)`: a shared-cache-line write on read-mostly hot
  items. This is the scalability killer on many-core hardware.
- Timestamp allocation from a single counter is itself a bottleneck at high
  core counts (Yu et al., "Staring into the Abyss", VLDB 2014); batched or
  per-core clocks (Silo epochs, Cicada loosely synchronised clocks, TicToc's
  data-driven timestamps) avoid it.

Conservative TO (each scheduler waits until it has seen all older steps)
avoids aborts at the cost of blocking and of requiring predeclared or
pipelined arrival; deterministic engines (Calvin) are its modern descendant.

## 7. Optimistic concurrency control (OCC)

Kung and Robinson (TODS 1981). Three phases: **read** (execute against
private workspace, record read set `RS` and write set `WS`), **validate**,
**write** (install). Serialization order = validation order.

**Backward validation** (validator `tj` against every `ti` that committed
after `tj` started):

| Case | Condition for `ti` before `tj` |
|---|---|
| 1 | `ti` finished its write phase before `tj` started its read phase |
| 2 | `ti` finished writing before `tj` starts writing, and `WS(ti) ∩ RS(tj) = ∅` |
| 3 | `ti` finished its read phase before `tj` finishes its read phase, and `WS(ti) ∩ (RS(tj) ∪ WS(tj)) = ∅` |

Serial validation+write (a critical section) makes case 2 the standard test:
"did anyone who committed during my lifetime write something I read?"

**Forward validation** (Härder 1984): the validator checks its `WS` against
the *current* read sets of active transactions. Advantages: conflicts are
detected against transactions that have not wasted their full work yet, and
the scheduler may choose which side to abort (validator or the actives),
enabling priority-aware policies (real-time OCC, see
`semantic-and-extended-transaction-models.md`).

**Kill vs die.** "Die/silent" lets a doomed transaction run to completion and
fail validation; "kill/broadcast" aborts it as soon as a committer conflicts.
Kill wastes less CPU; die can be better when the first execution primes the
buffer pool so the rerun is disk-free (two-phase processing with *access
invariance*; see `cc-performance-and-tuning.md`).

**Zombie / opacity problem.** A transaction that will fail validation may
observe an inconsistent state during its read phase (`x` from before a
commit, `y` from after). In a database engine this can mean a division by
zero in an expression, an infinite loop in a stored procedure, a pointer
chase into a freed node, or an out-of-bounds index derived from two
inconsistent fields. Defences: validate incrementally on every read
(TL2-style version check against a read timestamp), sandbox evaluation, or
take snapshot reads (MVCC). STM research names the requirement *opacity*.

**Phantoms under OCC.** Item read sets miss inserts into scanned ranges.
Re-execute scans at validation (Hekaton), or record index-node versions in a
"node set" and validate that no scanned leaf changed (Silo); see
`locking-and-btree-concurrency.md` and `mvcc-si-ssi.md`.

> **Beyond EDBS: Silo (Tu, Zheng, Kohler, Liskov, Madden, SOSP 2013).**
> Single-version OCC for multicore. Commit: (1) lock all write-set records
> in a global order (address order) to avoid deadlock; (2) read the global
> epoch (fence); (3) validate that every read-set record's TID word is
> unchanged and not locked by another transaction, and that node-set
> versions are unchanged (phantoms); (4) choose a TID greater than every TID
> observed and than the worker's last TID, within the current epoch; install
> writes and release locks. No shared counter is written per transaction;
> durability is by epoch-based group commit. Serialization order is the TID
> order, not real time within an epoch, which is acceptable because results
> are released only after the epoch is durable.

> **Beyond EDBS: TicToc (Yu, Pavlo, Sanchez, Devadas, SIGMOD 2016).** Each
> record carries a valid interval `[wts, rts]`; the commit timestamp is
> computed lazily from the intervals of the records touched, and validation
> may *extend* a record's `rts` instead of aborting. It accepts schedules
> that Silo-style OCC rejects when the read set is old but still valid at
> some common timestamp.

## 8. Choosing the correctness target: summary table

| Target | Test / enforcement | Typical enforcer | Notes |
|---|---|---|---|
| CSR | acyclic SG | 2PL, SGT, OCC, TO | prefix-closed, polynomial |
| VSR | NP-complete | Thomas write rule only | do not build a VSR scheduler |
| OCSR | CSR + real-time | strict 2PL, OCC with serial validation | expected by users and Jepsen-style checks |
| COCSR | commit order = serial order | SS2PL (rigorous) | composes across sites |
| MVSR / 1SR | acyclic MVSG for some version order (NP-complete in general) | MVTO, MV2PL, SSI | see `mvcc-si-ssi.md` |
| ST / RG | lock-duration discipline | strict / strong 2PL | needed for before-image undo |

## 9. Classic theorems worth having at hand

1. CSR iff `SG` acyclic (and iff commutativity-reducible to serial).
2. If all transactions are two-phase, every legal history is CSR; 2PL is
   "optimal" in that any non-2PL locked transaction can be paired with a 2PL
   one to produce a non-serializable history. But 2PL accepts a strict subset
   of CSR: `r1(x) r2(x) w2(x) r3(y) w3(y) w1(y)` has edges `t1->t2` (on x)
   and `t3->t1` (on y), so it is CSR with serial order `t3 t1 t2`; yet no
   two-phase lock placement produces it: `t1` must release `x` before `t2`
   locks it, so (being two-phase) it must already hold `y`, which then
   overlaps `t3`'s use of `y`.
3. Strict 2PL produces ST ∩ CSR; strong strict 2PL produces RG ∩ COCSR.
4. Basic TO produces CSR in timestamp order; with Thomas write rule, VSR.
5. Under SI, every cycle in the MVSG contains two consecutive rw edges between
   concurrent transactions (Fekete et al. 2005).
6. MV-serializability testing is NP-complete (Papadimitriou and Kanellakis
   1984); with a fixed version order (e.g. commit order) it is polynomial
   (acyclicity of MVSG for that order).

## Key papers
- Eswaran, Gray, Lorie, Traiger, CACM 1976 (consistency, 2PL, predicate locks).
- Papadimitriou, JACM 1979 (serializability, complexity); *Theory of Database
  Concurrency Control*, 1986.
- Bernstein, Shipman, Wong, IEEE TSE 1979; Bernstein, Hadzilacos, Goodman,
  *Concurrency Control and Recovery in Database Systems*, 1987 (BHG).
- Yannakakis, JACM 1984 (view serializability, locking).
- Kung and Robinson, TODS 1981 (OCC).
- Weikum and Vossen, *Transactional Information Systems*, 2002 (unified page
  and object model; the most complete reference for this file).
- Alonso et al., Information Systems 1994 (unifying CC and recovery).

Sources: EDBS "Transaction Models: The Read/Write Approach" (p.4194),
"Serializability" (p.3475), "Two-Phase Locking" (p.4270), "Concurrency
Control: Traditional Approaches" (p.575), "Concurrency Control Manager"
(p.574), "Correctness Criteria Beyond Serializability" (p.640), "Transaction"
(p.4186), "Transaction Management" (p.4189), "ACID Properties" (p.23),
"Atomicity" (p.186), "Performance Analysis of Transaction Processing Systems"
(p.2732, OCC kill/die).
