# Locking: 2PL variants, lock manager, deadlocks, granularity, B-tree concurrency

Locks separate *transactions* and protect *logical database contents*;
latches separate *threads* and protect *in-memory physical structures*. Every
correctness bug in this area starts with conflating the two. Locks: modes,
queues, deadlock detection, transaction duration, thousands of cycles per
acquire (hash lookup, cache misses). Latches: shared/exclusive, embedded in
the protected structure, tens of instructions, deadlock *avoided* by coding
discipline (ordering, no-wait try-latch), never held across I/O waits for
another transaction.

## 1. Two-phase locking and its variants

Locked transaction: every `r(x)`/`w(x)` is bracketed by `L(x) ... U(x)`. The
lock table enforces LUL (no two incompatible holders). **2PL rule**: no lock
after the first unlock. Proof sketch of safety: define the *lock point* of `t`
as its last lock acquisition; every conflict edge `ti -> tj` implies `Ui(x) <
Lj(x)` hence `lockpoint(ti) < lockpoint(tj)`; a cycle would order a lock point
before itself. So lock-point order is an equivalent serial order.

| Variant | Rule | Gives | Cost / risk |
|---|---|---|---|
| Basic 2PL | growing then shrinking phase | CSR | early release lets others read uncommitted data: cascading aborts, not recoverable |
| Strict 2PL (S2PL, Weikum-Vossen sense) | write locks held to commit/abort | CSR ∩ ST | read locks may be released after lock point; still needs to know the lock point |
| Strong strict / rigorous 2PL (SS2PL) | all locks held to termination | CSR ∩ RG, COCSR | what "strict 2PL" means in most textbooks and products |
| Conservative (static) 2PL | acquire the full predeclared lock set before the first step | deadlock-free | needs read/write sets up front; over-locking; low concurrency on hot items |
| Ordered sharing | incompatible locks may be shared if operations execute in lock-acquisition order; releases ordered | more concurrency than 2PL | commit dependencies, more complex bookkeeping |
| Altruistic locking (Salem, Garcia-Molina, Shands, TODS 1994) | a long transaction "donates" items it will not touch again; recipients must stay in its wake | long + short txn mixes | donation bookkeeping, wake rules |

Terminology warning for design reviews: "strict 2PL" is ambiguous between
"write locks to end" and "all locks to end". Products implement the latter
for SERIALIZABLE. Ask which one a design means.

**Lock conversion (upgrade).** `S -> X` upgrades are a classic deadlock
source: two S holders both request X. Use an **update (U) mode**: a reader
that may later write takes U; U is compatible with S holders but not with
another U or X, so only one potential upgrader exists per item. Some products
make U asymmetric (no new S granted while U is held) so the upgrader is not
starved. Conversions should be queued ahead of new requests (FIFO-with-
conversion-priority) or they starve behind incompatible newcomers.

## 2. Lock manager data structures

```
lock table: hash(resource_id) -> bucket (latched) -> lock head
lock head: { resource_id, granted_group_mode, granted list, wait queue,
             conversion queue }
request:   { txn, mode, status(granted|waiting|converting), duration,
             next_in_txn_list }
txn entry: { list of requests (for release-all at commit), wait-for edge(s),
             timestamp/priority, isolation level }
```

- Group mode = supremum of granted modes; a new request is granted if it is
  compatible with the group mode *and* the wait queue is empty (fairness; no
  barging) unless it is a conversion.
- Release at commit walks the transaction's list; each release may wake a
  prefix of the wait queue (all compatible requests).
- Latch per hash bucket (or per lock head); never hold a bucket latch while
  waiting for the lock itself; waiting happens on a per-transaction event.
- Lock duration classes: instant (test-and-release, used for next-key insert
  checks), short/statement (cursor stability, read committed with locking),
  commit (long). Durations encode the isolation level (see
  `isolation-levels-and-anomalies.md`).
- Intra-transaction parallelism: threads of one transaction share its locks
  but still need latches against each other.

> **Beyond EDBS.** Main-memory engines remove the central hash table:
> co-locate lock state with the record (a lock word or reader count in the
> tuple header), or use VLL (Ren, Thomson, Abadi, VLDB 2012), which keeps two
> counters per record and orders transactions by a queue instead of
> per-request lists. Hekaton, Silo and HyPer avoid record locks for reads
> entirely (validation or MVCC).

## 3. Deadlock handling

| Strategy | Mechanism | When it wins | Risk |
|---|---|---|---|
| Detection, continuous | add edge on every wait; search for cycle from new edge | low deadlock rate, need precise victims | per-wait graph search cost; latch on WFG |
| Detection, periodic | scan WFG every `Δ` (PostgreSQL: after `deadlock_timeout`, default 1 s) | waits usually short | deadlocked txns hold locks for up to `Δ` |
| Timeout | abort a waiter after `τ` | distributed / heterogeneous lock managers | false positives under load; tuning `τ` |
| Wait-die | requester older than holder waits; younger requester aborts ("dies") | no WFG needed, non-preemptive | younger txns restart repeatedly |
| Wound-wait | older requester aborts ("wounds") younger holder; younger requester waits | fewer restarts than wait-die typically | preempts work in progress |
| No-wait | abort on any conflict | very short txns, partitioned in-memory | restart storms |
| Cautious waiting (Hsu and Zhang 1992) | wait only if the holder is not itself blocked | bounds wait chains, deadlock-free | aborts under chained contention |
| Conservative 2PL / ordered acquisition | acquire in a global order | predeclared sets (Calvin, latch protocols) | needs lock set knowledge |

Wait-die and wound-wait are deadlock-free because waits only go in one
timestamp direction; they are starvation-free only if a restarted transaction
**keeps its original timestamp**. Both abort transactions that would never
have deadlocked (they prevent the possibility, not the event).

Victim selection: youngest, fewest locks held, least log written (cheapest
undo), or lowest priority; record victim counts to prevent repeated
victimisation. Gray's estimate: two-way deadlock probability per transaction
grows roughly with `k^4/D^2` (k locks per txn, D items), so deadlocks are rare
compared with plain blocking; blocking, not deadlock, is what limits locking
throughput (see `cc-performance-and-tuning.md`). Multi-way cycles are rarer
still. Conversion deadlocks and index/heap ordering deadlocks (one txn locks
heap row then index key, another the reverse) dominate in real traces.

Distributed deadlocks: global WFG is expensive; use edge-chasing probes
(Chandy-Misra-Haas) or timeouts; timestamp-based prevention works unchanged
across sites. See `distributed-transactions`.

## 4. Multi-granularity locking (Gray, Lorie, Putzolu, Traiger 1975)

Granule hierarchy (database > table/tablespace > page > row, or a DAG with
indexes). Coarse locks reduce lock count; fine locks increase concurrency.
Intention modes make coarse and fine locks mutually visible without scanning
descendants.

Compatibility (requested mode down, granted mode across; `+` = compatible):

|        | IS | IX | S | SIX | X |
|--------|----|----|---|-----|---|
| **IS** | +  | +  | + | +   | - |
| **IX** | +  | +  | - | -   | - |
| **S**  | +  | -  | + | -   | - |
| **SIX**| +  | -  | - | -   | - |
| **X**  | -  | -  | - | -   | - |

Protocol:
1. Lock root-to-leaf; release leaf-to-root (or all at end).
2. To take S or IS on a node, hold IS or IX (or stronger) on its parent.
3. To take X, IX or SIX on a node, hold IX or SIX on its parent.
4. In a DAG (e.g. row reachable via table and via index), an S request needs
   an intention lock on at least one parent; an X request needs IX on *all*
   parents.

SIX = S + IX: "read everything, update a few", e.g. a scan with
`UPDATE ... WHERE` on a fraction of rows. Conversions follow the mode lattice
(`IX ∨ S = SIX`, `S ∨ IX = SIX`, anything `∨ X = X`).

**Escalation.** When a transaction's fine locks under one parent exceed a
threshold (count or memory), convert the parent's IS/IX to S/X (may wait),
then release the children. Escalation is a classic source of surprise
deadlocks and blocking (an escalated table X lock blocks everyone); engines
expose per-table disable switches and partition-level escalation. De-
escalation is generally not supported. A good design decides granularity
from the plan (optimizer knows a scan will touch most of a table) instead of
discovering it at runtime.

## 5. Phantoms and predicate-level protection

Item locks cannot protect "the set of rows satisfying P": an insert of a new
qualifying row conflicts with no existing lock. Options:

| Technique | Idea | Trade-off |
|---|---|---|
| Predicate locks (Eswaran et al. 1976) | lock the predicate; conflict = predicates jointly satisfiable and one writes | satisfiability test is expensive in general; rarely implemented |
| Precision locks (Jordan, Banerjee, Batman 1981) | readers register predicates; writers test each written tuple against registered predicates | cost proportional to active predicates; good for in-memory (HyPer validates against undo buffers in this spirit) |
| Table / partition lock | coarse S | kills concurrency |
| Key-range / next-key locking | use the index's sort order: lock existing keys *and the gaps* between them | needs an index on the predicate column; the standard answer |
| Index-node versions (Silo) | validate that scanned leaves did not change | OCC-only |

## 6. B-tree concurrency: the physical layer (latching)

Assume a B+-tree (records only in leaves; interior separators are not
content). Four problems: (a) page read/write exclusion, (b) pointer
validity while descending parent->child, (c) pointer validity along sibling
links during scans, (d) splits/merges propagating upward.

**Latch coupling (crabbing).** Latch child, then release parent. Readers use
S latches. Writers:

| Approach | Description | Issue |
|---|---|---|
| X-latch the whole path | trivially correct | root becomes a serial bottleneck |
| S-descend, upgrade on need | upgrade S->X at the leaf/parents | upgrade can fail or deadlock; must restart |
| Update latches | U latches on the path, upgrade where needed | fewer conflicts than X, still blocks other writers near root |
| "Safe node" release (Bayer and Schkolnick 1977) | keep latches on ancestors only until a node that will not split (not full) / not merge (more than half full) is reached | standard; most inserts hold one or two latches |
| Pre-emptive split | split full nodes on the way down | no upward propagation; wastes some space |
| Optimistic descent + restart | S/optimistic descent; if the leaf must split, restart with X latches on the path | cheap common case |

Scans along leaf chains in opposite directions can deadlock on latches;
sibling latch acquisition must use try-latch (no-wait) and restart.

**B-link trees (Lehman and Yao, TODS 1981).** Every node has a high key
(fence) and a right-link. A split is two independent steps: (1) create the
right sibling, move half the entries, set the high key and right-link,
release; (2) later, post the separator in the parent. Between the steps, a
searcher whose key exceeds the node's high key simply follows the right-link
("move right"). Consequences: writers latch one node at a time during the
split step, readers never block on structure modification, and step (2) can
be deferred even across a crash (it is a structural, not logical, change).
Costs: searches may take extra hops; under heavy insert bursts right-chains
can grow (Jaluta, Sippu, Soisalon-Soininen, VLDB J 2005, bound them);
structural verification is harder. Deletion/merging needs extra care (Lanin
and Shasha 1986).

**Fence keys** (low and high keys stored in every node, Graefe) make each
node self-describing, enable cheap consistency checking (child fences must
equal parent separators), and replace physical sibling pointers for
verification.

> **Beyond EDBS.** *Optimistic lock coupling* (Leis et al., "The ART of
> Practical Synchronization", DaMoN 2016): each node carries a version
> counter; readers record versions, read, and re-validate instead of taking
> shared latches; writers lock and bump the version. No cache-line writes on
> the read path. Used in LeanStore/Umbra-style engines. *Bw-tree*
> (Levandoski, Lomet, Sengupta, ICDE 2013): latch-free via a mapping table
> and CAS-installed delta records with consolidation. *Masstree* (Mao,
> Kohler, Morris, EuroSys 2012): trie of B+-trees with version-validated
> optimistic reads; underlies Silo. Epoch-based reclamation is mandatory for
> any optimistic reader scheme (a node cannot be freed while a reader may
> still dereference it).

## 7. B-tree concurrency: the logical layer (key locking)

**Key-value locking (ARIES/KVL, Mohan VLDB 1990; ARIES/IM, Mohan and Levine
SIGMOD 1992).** A lock on key `k` covers `k` *and the gap below it* up to the
previous key (half-open interval `(prev, k]`). Rules (next-key locking):

```
fetch/scan [a, b]:   S-lock each key returned, and S-lock the first key > b
                     (or an end-of-index sentinel) -> protects the whole range
insert k:            find next key k' > k; request X on k' for *instant*
                     duration (verify no reader holds the gap), then X-lock k
                     for commit duration
delete k:            X-lock k (commit) and X-lock next key k' (commit), so the
                     gap (prev, k'] stays protected and rollback can re-insert k
update non-key cols: X-lock k only
```

The instant lock on the next key during insert violates 2PL formally but is
correct because the page latch is held across "check lock on k'" and
"insert k into the page", so no reader can slip into the gap in between.

**Ghost (pseudo-deleted) records.** Delete marks the record as a ghost under
its X lock instead of physically removing it; the key stays in the index, so
key-range locks remain anchored on it and rollback is a flag flip (no space
allocation or split during undo). A system transaction (not user-visible,
no locks beyond the latch, logged) purges ghosts once no lock covers them.
Inserts can be done as "create ghost via system transaction, then turn into
valid record under user lock", which separates structural change from
logical change (multilevel transaction structure). Ghosts participate in
range locking exactly like valid keys and must be skipped by scans.

**Range lock modes (Lomet VLDB 1993).** Split a key lock into a range
component and a key component, e.g. SQL Server's `RangeS-S`, `RangeS-U`,
`RangeI-N` (insert-intent on gap, nothing on key), `RangeX-X`. Insert
intentions on the same gap are mutually compatible, so concurrent inserts
into one gap do not serialise.

**Hierarchical key-range locking (Graefe).** Treat *key*, *gap* (open
interval to the neighbour) and *key+gap* as a small hierarchy and apply
multi-granularity modes to it; combined modes let one lock-manager call
cover both components. Orthogonal key-value locking (Graefe and Kimura,
2015) generalises to separate modes for key and gap with partitioned gaps.

**Non-unique indexes.** Lock `(key, rowid)` pairs (unique lock names, no
special cases) or lock the key value with an intention mode so that separate
rows with the same key do not conflict.

**Right-edge hot spot.** Monotonic keys (timestamps, sequences) send every
insert to the last leaf: latch and next-key-lock contention on one page.
Mitigations: instant next-key locks (above), hash-prefixed or reversed keys,
partitioning by a hash bucket, or append-optimised structures.

> **Beyond EDBS: InnoDB.** A *next-key lock* is a record lock plus a lock on
> the gap before the record; *gap locks* are purely inhibitive (gap locks of
> any mode do not conflict with each other); inserts take an *insert
> intention* gap lock that conflicts only with real gap locks. Locking reads
> (`SELECT ... FOR UPDATE`, `UPDATE`, `DELETE`) under REPEATABLE READ use
> next-key locks; plain `SELECT` is a snapshot read with no locks. Because
> locking reads see the latest committed version while plain reads see the
> snapshot, a transaction can observe two different "current" states.

## 8. Multilevel view of B-tree locking

Index operations are subtransactions: page latches (level 0) are released at
the end of each key operation; key locks (level 1) are held to commit. Undo
of a key insert is a *logical* delete (the page may have split since), so
recovery must log logically at level 1 (ARIES CLRs, see
`recovery-and-durability`). This is the multilevel transaction model in
practice; see `semantic-and-extended-transaction-models.md`.

## 9. Pitfalls checklist

- Holding a page latch while waiting for a lock: deadlock between the latch
  hierarchy and the lock WFG (invisible to the detector). Rule: request lock
  conditionally under the latch; if not immediately grantable, release the
  latch, wait unconditionally, then re-latch and revalidate (the page LSN
  may have changed).
- Forgetting the end-of-index sentinel: a range scan to the last key leaves
  the tail gap unprotected.
- Purging a ghost that a range lock still covers: re-opens a phantom window.
- Lock-name instability across page splits when locks name `(page, slot)`:
  use logical key-based lock names.
- Escalation under SIX/IX mixes producing conversion deadlocks.
- Sibling scans in two directions with blocking latch waits.

## Key papers
- Gray, Lorie, Putzolu, Traiger, VLDB 1975 and IFIP 1976 (granularity, degrees
  of consistency).
- Bayer and Schkolnick, Acta Informatica 1977 (safe-node latching).
- Lehman and Yao, TODS 1981 (B-link); Srinivasan and Carey, SIGMOD 1991
  (performance of B-tree CC); Jaluta et al., VLDB J 2005.
- Mohan, VLDB 1990 (ARIES/KVL); Mohan and Levine, SIGMOD 1992 (ARIES/IM);
  Lomet, VLDB 1993 (key-range locking).
- Graefe, "A survey of B-tree locking techniques", TODS 2010; Graefe,
  "Hierarchical locking in B-tree indexes", BTW 2007.

Sources: EDBS "B-Tree Locking" (p.345), "Locking Granularity and Lock Types"
(p.2131), "Two-Phase Locking" (p.4270), "Concurrency Control Manager"
(p.574), "Multilevel Transactions and Object-Model Transactions" (p.2353),
"Performance Analysis of Transaction Processing Systems" (p.2732, deadlock
probability), "Tuning Concurrency Control" (p.4252).
