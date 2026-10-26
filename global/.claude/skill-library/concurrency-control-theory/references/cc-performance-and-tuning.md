# CC performance: data contention models, thrashing, restart policies, hot spots, chopping, tuning

Two kinds of contention degrade a transaction system: **resource contention**
(CPU, I/O, memory; modelled by queueing networks) and **data contention**
(blocking and restarts caused by CC). Data contention is self-amplifying:
blocked transactions hold locks, which block more transactions. This file
gives the models that predict it and the engineering levers that relieve it.

## 1. Resource-side background (brief)

- M/G/1 for a CPU or disk: utilisation `ρ = λ·x̄`, waiting time
  `W = λ·E[x²] / (2(1-ρ))`; M/M/1 response `R = x̄/(1-ρ)`.
- Closed queueing networks with fixed multiprogramming level (MPL) `N`:
  Mean Value Analysis computes throughput `X(n)` iteratively; `X(n)` is
  concave and saturates at `min_k m_k/D_k` (the bottleneck device).
- Memory-constrained admission (an MPL cap `M`) is solved hierarchically:
  the closed model gives `X(n)` for `n <= M`, a birth-death model on top
  handles the queue for admission.

These give the *no-data-contention* throughput curve `X(n)` that the
locking models below scale down.

## 2. Standard (strict 2PL) locking model (Tay; Thomasian)

Closed system, `M` transactions, database of `D` uniformly accessed items,
fixed-size transactions with `k` lock requests spread uniformly over `k+1`
steps of mean duration `s`, all locks exclusive, held to commit.

| Quantity | Approximation | Meaning |
|---|---|---|
| Mean locks held | `L ≈ k/2` | locks accumulate linearly over the txn |
| Conflict probability per request | `Pc ≈ (M-1)·L/D ≈ (M-1)k/(2D)` | hitting one of the others' locks |
| Prob. txn blocks at least once | `Pw ≈ k·Pc ≈ (M-1)k²/(2D)` | quadratic in transaction size |
| Two-way deadlock prob. per txn | `PD ≈ Pw²/(M-1) ≈ (M-1)k⁴/(4D²)` | fourth power in `k`, rare |
| Shared locks fraction `fS` | use `Deff = D/(1 - fS²)` | reads dilute conflicts |
| Blocking time vs holder | `W1 ≈ R/3` for fixed-size txns | holder is on average ~2/3 done |
| Waiting behind a blocked txn | `W2 ≈ 1.5·W1`, level `i`: `≈ (i - 0.5)·W1` | wait chains lengthen waits |

Variable transaction sizes (moments `K1 = E[k]`, `K2 = E[k²]`, ...) raise
both `Pc` and `PD` substantially (Thomasian reports ~2x and ~10x for a
truncated geometric size distribution versus fixed size): long transactions
dominate contention because they hold more locks for longer (a quadratic
effect).

**Thrashing.** Let `β` = fraction of blocked transactions and
`α = K1·Pc·W1/R` (mean conflicts per transaction times normalised wait).
Accounting for wait chains gives
`β = α(1 + 0.5β + 1.5β² + 2.5β³ + ...)`, i.e. the cubic
`β³ - (1.5α + 2)β² + (1.5α + 1)β - α = 0`.
A feasible root `β < 1` exists only for `α <= α* ≈ 0.226`; beyond that the
number of *active* transactions `M_A = M(1-β)` falls as `M` grows: adding
transactions reduces throughput (the snowball of blocked transactions
blocking others). The critical point corresponds to the **conflict ratio**
(locks held by all transactions / locks held by active transactions) used by
Mönkeberg and Weikum (ICDE 1991, VLDB 1992; later the COMFORT project) as an
online load-control signal; their empirically derived, roughly
workload-independent threshold is a conflict ratio of about 1.3. Tay's
mean-value analysis gives a comparable rule of thumb in terms of the workload
parameter `k²M/D` (trouble once it exceeds roughly 1.5; verify against Tay 1987).

Engineering consequences:
1. Data-contention thrashing is a function of `M·k²/D` (more precisely of
   `α`), so it can strike with idle CPUs. Monitoring CPU alone will not see
   it.
2. **Admission control on the conflict ratio** (or blocked fraction),
   not on CPU utilisation, is the right MPL controller for locking systems.
3. Halving transaction length (in locks or time) cuts `Pw` by ~4x; this is
   the quantitative case for chopping and for moving hot accesses late.
4. Deadlock handling is a secondary concern for throughput; blocking is the
   primary one.

## 3. Restart-oriented locking policies

Idea: abort selectively to keep wait chains short ("essential blocking": a
transaction may wait only for active, not blocked, transactions).

| Policy | Rule | Notes |
|---|---|---|
| No-waiting (immediate restart) | abort on any conflict | no benefit if restarted immediately: same conflict recurs |
| Cautious waiting | wait only if the holder is active (not blocked); else abort requester | bounds chain depth to 1, deadlock-free |
| Running Priority (RP) | if `TA` waits on `TB` and `TB` is itself blocked, abort `TB`; also abort a blocked txn that is blocking others when it blocks | raises active-transaction count |
| Wait-Depth Limited (WDL; Franaszek, Robinson, Thomasian TODS 1992) | limit wait depth to 1; when a chain would form, abort the txn with *less progress* (fewer locks held / less work) | best of the family in their simulations and in trace-driven studies; needs progress estimate |
| Restart waiting | delay restart of an aborted txn until the conflicting txns complete | prevents cyclic restarts (livelock) |
| Random backoff | delay restart randomly | weaker livelock prevention |

Restart policies need **spare hardware capacity**: aborted work is redone. In
resource-bound systems they lose to standard locking.

## 4. Optimistic CC performance

- Conflict probability between two transactions each touching `k` of `D`
  items: `≈ k²/D`. Validation failure grows with both `k` and the
  transaction's duration (itself ∝ `k`), again quadratic; wasted work is
  dominated by long transactions.
- Analyses (Morris and Wong 1985; Ryu and Thomasian 1987) distinguish
  static vs dynamic (on-demand) access and **die** (run to validation, then
  restart) vs **kill** (abort at first conflicting commit). Resampling
  transaction lengths on restart overestimates OCC performance (short
  transactions survive preferentially); model restarts as re-executing the
  *same* transaction.
- **Two-phase (multiphase) processing**: first execution with OCC-die primes
  the buffer pool; if it fails, re-execute (now disk-free and short) with OCC
  kill or with **lock preclaiming** (access invariance: the rerun touches the
  same items, so they can be locked up front and the second run cannot
  fail). Generalises to escalating CC strength per attempt.
- For in-memory engines (no I/O), OCC wins at low contention and loses
  badly on hot items; production OCC designs add fallback to locking or
  queueing for repeated aborts (e.g. contention regulation in Cicada).

## 5. Hot spots

A hot spot is a small set of items updated by a large fraction of
transactions (counters, sequence generators, warehouse YTD totals, right
edge of a time-ordered index, a "last updated" timestamp row).

| Lever | Mechanism | Caveat |
|---|---|---|
| System sequences / identity | latch held only during increment, not a lock to commit | gaps on abort; unsuitable where gap-free numbering is legally required (invoices) |
| Move hot access to the end of the txn | lock held for the shortest time before commit | does not help if the hot read drives later logic |
| Commutative / delta updates | increment locks, escrow, field calls | reads of the hot value become expensive or ranged |
| Split the item | N sub-counters, sum on read; per-core/partitioned aggregates | read cost, reconciliation |
| Transaction chopping | commit the hot-item update as its own piece | correctness by SC-cycle analysis (below) |
| Lower isolation for specific txns | RC/SI for reads that tolerate it | prove invariant safety |
| Key design for indexes | hash prefix, reverse keys, partitioned sequences | range scans on the key get harder |
| Group commit / log tuning | shorten the commit critical path so locks are released sooner | durability latency trade-off |
| Early lock release (commit before log flush, hold dependents) | release locks when the commit record is in the log buffer; dependents may not commit before it is durable | must track commit dependencies; see `recovery-and-durability` |

## 6. Transaction chopping (Shasha, Simon, Valduriez, TODS 1995)

Split each transaction into **pieces** that run as separate transactions
(each piece itself serializable under the engine's CC), so locks are held
for a piece's duration, while guaranteeing the overall execution is
equivalent to a serial execution of the *original* transactions.

Assumptions: all transactions that may run concurrently are known (possibly
parameterised); rollbacks occur only in a transaction's first piece
(**rollback-safe**), which runs before any other piece.

**Chopping graph**: undirected; nodes = pieces; **C edge** between pieces of
different transactions that conflict (same item, one writes); **S edge**
between sibling pieces of the same transaction. An **SC-cycle** is a simple
cycle with at least one S and at least one C edge.

**Theorem.** Any chopping that is rollback-safe and whose chopping graph
contains no SC-cycle is correct.

```
T1 (purchase): r(cash) w(cash) ; r(stock) w(stock)
T2 (payment):  r(cash) w(cash)
T3 (restock):  r(stock) w(stock)

Chop T1 into T1a = {cash}, T1b = {stock}.
C edges: T1a - T2 (cash), T1b - T3 (stock)
S edges: T1a - T1b
No cycle -> correct: cash is locked only for T1a, not for all of T1.

Add T4 (audit): r(cash) r(stock)
New C edges: T4 - T1a (T1a writes cash), T4 - T1b (T1b writes stock)
Cycle T1a -S- T1b -C- T4 -C- T1a  -> SC-cycle: chopping now incorrect
(T4 could see the cash debit without the stock decrement; a snapshot does
not help, since a snapshot can fall between T1a's and T1b's commits). Fix:
do not chop T1 while audits can run, or schedule audits separately.
```

Finest chopping: for each transaction `Ti`, find its finest chopping assuming
the others are unchopped (merge any two pieces of `Ti` connected through a
path of C edges via other transactions); the union of these per-transaction
finest choppings is the finest correct chopping overall. Extensions to
SI-family piece execution exist (e.g. Cerone, Gotsman, Yang, DISC 2015 for
SI/PSI); re-derive the criterion before chopping under a weaker level.

Practical value: a principled justification for "commit the inventory
update separately" or "do the logging insert in its own transaction";
without the analysis such splits are where integrity bugs come from.

## 7. Living with less than full isolation

- **User think time inside a transaction** (hold seat locks while the agent
  talks to the customer) is fatal for throughput; restructure so the
  interactive read runs as one transaction and the final "secure seat" as
  another that re-checks (optimistic at application level). Accept that a
  seat displayed as free may be gone at confirmation.
- **Value of serializability experiment** (Shasha and Bonnet): a summing
  transaction concurrent with value-swapping transactions. On SI/statement-
  snapshot engines (MySQL InnoDB, Oracle) the sum is always correct even at
  READ COMMITTED (it reads one snapshot); on locking engines at RC most sums
  were wrong (around 40% correct in their runs). SERIALIZABLE throughput was
  lower because the scan took next-key locks. The lesson: the cost and the
  correctness of a level are engine-specific; measure on the target engine.
- **System counters** beat ad hoc counter tables increasingly with thread
  count (latch to statement end vs lock to transaction end).

## 8. Diagnosis and tuning loop

1. Observe: lock wait time per statement, blocked-session graphs, deadlock
   and timeout counts, abort reasons (serialization failures, validation
   failures), conflict ratio, escalation events.
2. Identify the hot resource (top waited-on lock names) and the transaction
   types holding it longest.
3. Choose, in order of preference: shorten hold time (reorder, chop, move
   work outside), reduce scope (finer granularity, better index so fewer
   keys/gaps are locked, avoid scans under SERIALIZABLE), change semantics
   (commutative updates, escrow, sequences), lower isolation where provably
   safe, partition the hot item, and only then admission control.
4. Re-measure throughput *and* invariant violations.

Index choice is a CC tuning knob: without an index on the predicate column,
a SERIALIZABLE (locking) scan must lock a whole table or every key/gap, and an
SSI engine falls back to relation-level SIREAD locks (more false positives).

## 9. Architectural alternatives that remove CC overhead

> **Beyond EDBS: partitioned serial execution (H-Store/VoltDB).** Partition
> data; run each partition's transactions serially on one thread with no
> locks or latches; single-partition stored procedures need no CC at all.
> Multi-partition transactions are the expensive case (coordination, lock
> whole partitions). Wins when the workload partitions cleanly.

> **Beyond EDBS: deterministic CC (Calvin; Thomson et al., SIGMOD 2012).**
> A sequencer batches requests into epochs (on the order of 10 ms) and
> replicates the batch order via Paxos; every replica's scheduler acquires
> locks in exactly that global order (deterministic 2PL with ordered
> acquisition, hence no deadlocks), and execution is deterministic, so
> replicas need no commit protocol and a failure needs no 2PC abort path.
> Requires read/write sets before execution; dependent transactions (whose
> keys depend on reads) use OLLP: a reconnaissance read to predict the set,
> then validation on execution and restart on mismatch. Costs: batching
> latency, no interactive transactions. Multi-version deterministic designs
> (BOHM, Faleiro and Abadi, VLDB 2015) remove read-write blocking. See
> `distributed-transactions` for the replication and sharding side.

> **Beyond EDBS: many-core evaluation.** Yu, Bezerra, Pavlo, Devadas,
> Stonebraker ("Staring into the Abyss", VLDB 2014) ran 2PL variants
> (no-wait, wait-die, deadlock detection), TO, MVCC, OCC and H-Store-style
> partitioning on a simulated 1000-core machine: every scheme hit a wall;
> bottlenecks were lock thrashing, timestamp allocation, abort rates and
> memory allocation rather than the theory. Practical takeaways: avoid
> global counters, avoid shared writes on the read path, and keep a
> contention fallback.

## Key papers
- Tay, *Locking Performance in Centralized Databases*, 1987.
- Thomasian, "Two-phase locking performance and its thrashing behavior", TODS 1993;
  "Concurrency control: methods, performance, and analysis", ACM CSUR 1998.
- Franaszek, Robinson, Thomasian, "Concurrency control for high contention
  environments", TODS 1992.
- Morris and Wong, Perf. Eval. 1985; Ryu and Thomasian, Perf. Eval. 1987.
- Mönkeberg and Weikum, "Conflict-driven load control for the avoidance of
  data-contention thrashing", ICDE 1991; VLDB 1992 follow-up evaluation.
- Weikum, Hasse, Mönkeberg, Zabback, "The COMFORT automatic tuning project",
  Inf. Sys. 1994.
- Shasha, Simon, Valduriez, TODS 1995 (chopping); Shasha and Bonnet,
  *Database Tuning*, 2002.
- O'Neil, TODS 1986 (escrow); Gawlick 1985 (IMS Fast Path hot spots).

Sources: EDBS "Performance Analysis of Transaction Processing Systems"
(p.2732), "Tuning Concurrency Control" (p.4252), "Transaction Chopping"
(p.4187), "Escrow Transactions" (p.1332), "SQL Isolation Levels" (p.3681,
RC vs serializable throughput), "Two-Phase Locking" (p.4270), "Concurrency
Control: Traditional Approaches" (p.575).
