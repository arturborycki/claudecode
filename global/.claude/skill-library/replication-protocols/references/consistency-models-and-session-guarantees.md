# Consistency models for replicated data: hierarchy, session guarantees, CAP/PACELC, freshness

Read this when you must state precisely what a replicated store promises,
compare two models, pick the cheapest model that keeps an application
correct, or implement session guarantees and bounded staleness.

---

## 1. Two families of models

- **Non-transactional (register / object) models** speak about single
  reads and writes on objects: linearizability, sequential, causal, PRAM,
  eventual. They come from shared-memory and distributed-systems work.
- **Transactional models** speak about multi-item transactions:
  1SR, strict 1SR, 1-copy SI, GSI, PSI, causal+ transactional, read
  atomic. They come from database work.
- **Strong** = clients cannot tell the data is replicated (the illusion of
  one copy under some single-site isolation level). **Weak** = clients can
  observe divergence; each weak model specifies *which* divergences.

A useful test: if the client cannot distinguish two system designs by the
values returned and the operations allowed, they provide the same model,
whatever their internals.

---

## 2. Non-transactional hierarchy (strongest to weakest)

```
          linearizability
                |
      sequential consistency
                |
             causal  ------------ (+ convergence) = causal+
          /     |     \
       PRAM   (session guarantees RYW, MR, MW, WFR — their conjunction ≈ causal)
          \     |
        eventual consistency (convergence only)
```

| Model | Definition (in this skill's words) | Composable? | Available under partition? |
|---|---|---|---|
| Linearizability (Herlihy & Wing 1990) | Every operation appears to take effect atomically at a point between its invocation and response; one total order consistent with real time | Yes (local property: per-object linearizability ⇒ system linearizability) | No (CAP) |
| Sequential consistency (Lamport 1979) | One total order of all operations consistent with each process's program order; real time between processes ignored | No | No |
| Causal (Ahamad et al. 1995) | Writes are seen by every process in an order consistent with potential causality: program order, reads-from, transitive closure; concurrent writes may be seen in different orders | — | Yes (sticky to a replica) |
| Causal+ (Lloyd et al., COPS 2011) | Causal + convergent conflict handling so replicas end in the same state | — | Yes |
| PRAM / FIFO (Lipton & Sandberg 1988) | Writes of each single process are seen by everyone in that process's order; writes from different processes unordered | — | Yes |
| Eventual | If updates stop, all replicas eventually converge to the same value | — | Yes |

**Causal is the strongest model that needs no cross-replica
synchronization on the critical path** (Mahajan, Alvisi, Dahlin 2011
argued a real-time-causal variant is the strongest achievable with
availability and convergence; later formalized). This is the theoretical
justification for causal+ geo-stores.

### Potential causality, precisely

`u → v` (u causally precedes v) if any of:
1. same thread, `u` before `v`;
2. `u` is a write and `v` is a read returning `u`'s value;
3. transitivity via some `w`.

Concurrent = neither precedes. Requirement: if a party can see `v`, it
must also see every `u → v`.

Implementation consequence: **FIFO channels are not enough**, because `u`
may depend on updates that originated at *other* replicas. Each update
must carry dependency metadata:

| Metadata | Precision | Cost |
|---|---|---|
| Explicit dependency list (nearest deps) | exact | grows with fan-in; COPS prunes to "nearest" dependencies |
| Vector clock, one entry per master replica / DC | exact for replica-level causality | O(#replicas) per update |
| Scalar / compact summary (e.g., one timestamp per DC, or a global stable time) | introduces **false dependencies** | small; increases visibility latency because an update waits for unrelated ones |

---

## 3. Eventual consistency, formally

For a replicated object `x`, let `S_n^x` be node `n`'s schedule of
updates (executed, or marked as aborted by conflict resolution). Two
schedules are **state-equivalent** if they produce the same final state
from the same initial state (e.g., `w1 w2 ≡ w2 w1` if they commute;
`w1 w2 ≡ w2` if `w2` blindly overwrites). Eventual consistency (Saito &
Shapiro 2005) holds at all times iff:

1. Some prefix of each `S_n^x` is state-equivalent to a prefix of every
   other node's schedule — the **committed prefix**.
2. The committed prefix only grows (its operations and their order never
   change once committed).
3. Every submitted update eventually appears in the committed prefix
   exactly once, either executed or as an explicit abort.
4. Every executed update in the committed prefix satisfied its
   preconditions in the state just before it.

Everything beyond the committed prefix is **tentative** and may be
reordered or undone. This is the right formal spec to test against: assert
(2) and (3) in a model checker; (1) is the convergence property.

Note what eventual consistency does not say: anything about what a read
returns before convergence. It is a pure liveness property with no
safety; any value may be returned in the meantime. Measured staleness in
production can be tiny (one large operator reported 99.9996% of reads
returning the latest write), but the remaining fraction concentrates on
hot items.

---

## 4. Session (client-centric) guarantees

Terry et al. (Bayou, PDIS 1994). A session is a sequence of operations by
one client, possibly across replicas.

| Guarantee | Definition | Breaks without it |
|---|---|---|
| Read Your Writes (RYW) | A read reflects all earlier writes of the same session | Changed password, cannot log in with it |
| Monotonic Reads (MR) | Successive reads reflect a non-decreasing set of writes | Comment visible, refresh, comment gone |
| Monotonic Writes (MW) | A session's writes are applied everywhere in session order | Edit applied before the create it depends on |
| Writes Follow Reads (WFR) | A write is ordered after the writes whose effects the session read before issuing it | Reply visible before the post it answers |

The four together give causal consistency *for that session's view*.

**Implementation (the version-vector method):**

```
session state: read_vv, write_vv     (vectors indexed by origin replica / DC)

read(x) at replica R:
   need = (RYW ? write_vv : 0) ⊔ (MR ? read_vv : 0)
   if R.applied_vv ≥ need: serve; read_vv := read_vv ⊔ R.applied_vv
                            (or ⊔ the vector of the version returned)
   else: wait / redirect to a fresher replica

write(x) at replica R:
   need = (MW ? write_vv : 0) ⊔ (WFR ? read_vv : 0)
   require R.applied_vv ≥ need before accepting
   assign version; write_vv := write_vv ⊔ {R: seq}
```

Cheaper variants: a single commit sequence number when there is one
primary (log-sequence-number tokens), or a hybrid timestamp. Ladin et al.
(lazy replication, 1992) generalized this by letting the client name the
set of prior operations a request must observe.

**Transactional session properties**: for transactions, "strong session"
versions of 1SR/SI forbid inversions within one client's sequence of
transactions (§5).

---

## 5. Transactional strong models

| Model | Equivalent to | Real-time constraint |
|---|---|---|
| 1SR | serial execution on one copy | none — serial order may invert non-overlapping transactions |
| Strong session 1SR | 1SR | inversions forbidden within one session |
| Strict 1SR / external consistency | 1SR | if `T_i` commits before `T_j` begins anywhere, `T_i` precedes `T_j` (this is what Spanner calls external consistency) |
| 1-copy SI | centralized SI execution, snapshot = local site's latest at start | implicit external consistency at the local site only |
| Strong session SI | SI, snapshot may be old but not older than the session's previous commit | per session |
| GSI | SI with any older prefix snapshot | none |

The lazy-primary example that motivates session properties: a client
commits a transfer at the primary, then runs a read-only transaction on a
stale secondary and sees the original balances. That execution *is* 1SR
(serialize the read-only transaction first). It is legal and still wrong
for the user.

---

## 6. Transactional weak models

| Model | What may be observed | Typical system |
|---|---|---|
| Relaxed currency (Bernstein et al. 2006) | Equivalent to a serial **multiversion** execution: reads may return a version that is not the latest; often restricted so update transactions are 1SR at the master and only read-only transactions read stale versions | lazy master + read replicas, mid-tier caches |
| Quasi-copies (Alonso, Barbará, Garcia-Molina) | Cached copies with application-specified allowed deviation | caches |
| PSI (Walter) | Site-local snapshots; non-conflicting transactions may commit in different orders at different sites (long fork); no write-write conflicts between transactions concurrent at any site; causal ordering preserved | geo-replicated KV |
| Causal+ transactional (Eiger, Antidote TCC) | Read-only/write-only transactions see causally consistent snapshots; concurrent writes merged | geo stores |
| Read atomic / RAMP (Bailis et al. 2014) | All or none of a transaction's writes visible (no fractured reads); no ordering guarantees across transactions | secondary indexes, materialized views without coordination |
| Eventually consistent with agreed order | Final state = all update transactions applied in one agreed serial order (the database version of eventual) | multi-master with reconciliation |

**HATs (Highly Available Transactions, Bailis et al. VLDB 2014):** read
committed, read atomic (their "monotonic atomic view" family), MR, MW and
WFR can be provided with availability under partition; RYW and causal need
*sticky* availability (the client keeps talking to the same replica);
lost-update prevention, write-skew prevention, SI, 1SR, and recency
(bounded staleness) guarantees cannot be highly available.

---

## 7. CAP and PACELC, stated carefully

**CAP** (Brewer 1999/2000; Gilbert & Lynch 2002): no system can provide a
linearizable read/write register whose every request to a non-failed node
eventually gets a response, if the network can lose arbitrarily many
messages between partitions.

Proof idea: write `x = 1` on one side of a partition (succeeds by
availability); read `x` on the other (must succeed by availability); no
message can carry the write across, so the read returns 0 — violating
linearizability.

Common misstatements to correct in reviews:

1. "Pick two of three" — P is a property of the environment, not a design
   choice. The real choice is what to do *when* a partition happens:
   refuse some operations (stay C) or answer them (stay A).
2. CAP is about linearizability (single-object, real-time). It does not
   say that *application* invariants require coordination — many do not
   (invariant confluence, §8 of `geo-replication-and-clocks.md`) — nor
   that causal or session guarantees are impossible (they are not).
3. CAP availability is "every non-failed node answers"; most "CP" systems
   still serve the majority side, which is what users mean by available.

**PACELC** (Abadi 2012): if Partition, trade Availability vs Consistency;
Else (normal operation), trade Latency vs Consistency. The E-branch is
what users feel daily: every synchronous cross-replica round trip is
latency. Classification examples: Dynamo-style stores PA/EL; Spanner-style
PC/EC; PNUTS-like per-record master PC/EL (reads local, writes to the
master).

---

## 8. Freshness: quantitative divergence bounds

When the model is "stale but bounded", define the metric:

| Metric | Definition | Notes |
|---|---|---|
| Value divergence | `|true − replica|` for numeric items | two replicas each within δ of truth differ by at most 2δ |
| Delay / time staleness | how long ago the replica's value stopped being current | a replica usually only knows its value's *timestamp*; `now − ts ≤ Δ` implies staleness ≤ Δ but not conversely |
| Missed updates | number of updates applied at the master but not at the replica | natural for sensors / periodic updates |
| Inter-object drift | separation between the validity intervals `[T,U)` and `[V,W)` of two values read together; 0 if they overlap | drift 0 = snapshot condition |
| Order error (TACT) | number of tentative, not-yet-globally-ordered updates | bound by refusing new writes when exceeded |

Value-validity interval: a value is valid from the time of the update
that produced it until just before the next update to the item.

Mixed models: **epsilon-serializability** (Pu; Ramamritham & Pu) sums a
divergence measure over a query's reads and bounds the total. **TACT /
conits** (Yu & Vahdat 2002) bound numerical error, order error and
staleness per unit of consistency ("conit"); numerical error is enforced
by splitting a global bound into per-replica quotas (e.g., ±€50 over ten
replicas → each may accumulate €5 of unpropagated change before it must
push and pull). **Relaxed currency SQL** (Guo, Larson, Ramakrishnan,
Goldstein 2004) lets a query declare currency bounds per table group;
the optimizer picks between local stale copies and the master.

Freshness-aware routing (FAS, Leganet): the middleware routes a read-only
transaction to a replica whose staleness satisfies the transaction's
bound, refreshing replicas on demand.

> **Beyond EDBS:** cloud stores expose these as product knobs — e.g.,
> Azure Cosmos DB's bounded-staleness level (by versions or time) and
> session level; DynamoDB / many SQL replicas expose "strongly consistent
> read" vs default eventually consistent read; PostgreSQL standbys expose
> `pg_last_wal_replay_lsn()` so a client can implement RYW with LSN
> tokens.

---

## 9. Choosing a model (review procedure)

1. Write down the application invariants and user-visible expectations
   (RYW on profile edits, monotonic timelines, uniqueness, non-negative
   balances).
2. For each, ask: does it need a total order (uniqueness, non-negativity
   with decrements → coordination or escrow), only causality (replies
   after posts), only per-session guarantees, or only convergence?
3. Pick the weakest model that satisfies all of them, per operation type
   if the system allows mixing (RedBlue consistency: Li et al. OSDI 2012
   — "blue" operations commute and run locally, "red" ones are totally
   ordered).
4. Specify it with a checkable definition (history-based), and test with
   a checker: Knossos/Porcupine for linearizability, Elle for
   transactional isolation, custom checkers for session guarantees.

---

Sources: EDBS — Consistency Models for Replicated Data (p.582), Strong
Consistency Models for Replicated Data (p.3809), Weak Consistency Models
for Replicated Data (p.4595), Causal Consistency (p.406), Eventual
Consistency (p.1403), CAP Theorem (p.395), Replica Freshness (p.3168),
Multi-datacenter Consistency Properties (p.2320), Optimistic Replication
and Resolution (p.2612), Concurrency Control for Replicated Databases
(p.566); Terry et al. PDIS 1994; Ahamad et al. 1995; Herlihy & Wing TOPLAS
1990; Lamport 1978/1979; Gilbert & Lynch 2002; Abadi IEEE Computer 2012;
Bailis et al. VLDB 2014, SIGMOD 2014; Bernstein et al. SIGMOD 2006; Yu &
Vahdat TOCS 2002; Ladin et al. TOCS 1992.
