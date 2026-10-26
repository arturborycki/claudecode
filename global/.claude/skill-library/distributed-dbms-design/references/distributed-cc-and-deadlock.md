# Distributed concurrency control and distributed deadlock

Global serializability over sites that each run a local scheduler; the lock-,
timestamp- and graph-based families extended to distribution; heterogeneous
(multidatabase) serializability; and distributed deadlock handling — global
wait-for graphs, centralized/hierarchical/distributed detection, path pushing,
edge chasing (Chandy–Misra–Haas), prevention, phantom deadlocks and victim
selection.

---

## 1. The correctness target

A distributed transaction T is a set of subtransactions, one per site it
touches. Each site produces a local history; the union is the global history.

- **Local serializability is not enough.** Sites can serialize the same pair
  in opposite orders: x at site 1, y at site 2, invariant x + y = const;
  site 1 executes w1(x) before w2(x) (T1 → T2), site 2 executes w2(y) before
  w1(y) (T2 → T1). Both local serialization graphs are acyclic; their union
  has the cycle T1 → T2 → T1, and neither site can see it.
- **Global serializability condition**: the global history is
  conflict-serializable iff every local history is serializable *and* every
  pair of conflicting global transactions is ordered the same way at every
  site where both appear — equivalently, the union of local serialization
  graphs is acyclic.
- **With replication** the target is **one-copy serializability (1SR)**:
  equivalent to a serial execution on a single-copy database. Requires a
  replica-control protocol (ROWA/ROWAA, quorum) in addition to concurrency
  control; mutual consistency of copies is part of the correctness claim.
  Commercial systems mostly use ROWAA (read one copy, write all *available*
  copies), which needs care around site recovery so a recovered copy is not
  read before it catches up. One-copy semantics also requires that updates be
  applied at every copy in a single total order consistent with commit order.

Distributed CC families: lock-based, timestamp-based, optimistic, and
serialization-graph testing (SGT); hybrids combine locks and timestamps.

## 2. Distributed two-phase locking

Locking alone does not decide *when a subtransaction may release*: the
two-phase rule is global — no subtransaction of T may release any lock until
no subtransaction of T will acquire another. A site cannot know that locally.
The standard fix couples release with atomic commit: on receiving PREPARE, a
participant knows T will acquire no more locks at any site; locks are
released at COMMIT/ABORT. In practice this is **strict 2PL + 2PC**, which also
gives recoverability and avoids cascading aborts. Read locks *may* be released
at PREPARE (a participant that has voted needs no more reads), but write locks
must be held until the decision.

Placement of the lock manager:

| Variant | Lock manager | Messages per remote lock | Wins | Risks |
|---|---|---|---|---|
| Centralized (primary-site) 2PL | one site for all data | request + grant to central site, then data access at the data site | simple; centralized deadlock detection falls out naturally | bottleneck, single point of failure |
| Primary-copy 2PL | per item, the site of its primary copy | to the primary-copy site | locks distributed with data; lock once per item regardless of replica count | primary site availability; readers of secondaries must still lock at the primary for 1SR |
| Distributed 2PL (with ROWA) | every site locks its own copies | read: lock one copy; write: lock all copies | no central component; reads local | write fan-out = number of copies; more distributed deadlocks |

Systems: System R* and Tandem NonStop SQL used distributed 2PL with 2PC;
Distributed INGRES used primary-copy 2PL with 2PC.

Lock waits are longer in distributed systems (remote round trips inside the
critical section, plus the 2PC window during which locks are held), so
deadlock and abort rates rise relative to centralized execution.

## 3. Timestamp ordering

Every transaction gets a globally unique timestamp; conflicting operations
must execute in timestamp order.

- **Timestamp generation**: Lamport clock per site (on message receipt set
  clock := max(clock, msg_ts) + 1) concatenated with the site id as the
  low-order tie-breaker: ts = (counter, site_id). Uniqueness comes from the
  site id; rough agreement with real time comes from clock exchange. A site
  whose counter lags gets its transactions rejected more often — piggyback
  clocks on all messages.
- **Basic TO** (per item x: R-ts(x), W-ts(x)): read by T rejected if
  ts(T) < W-ts(x); write rejected if ts(T) < R-ts(x) or ts(T) < W-ts(x)
  (Thomas write rule: if only ts(T) < W-ts(x), skip the obsolete write).
  Rejected transactions restart with a *new, larger* timestamp. Deadlock-free,
  but needs a mechanism (buffering uncommitted writes, or strictness) to avoid
  reading uncommitted data, and can starve long transactions.
- **Conservative TO**: each scheduler buffers operations and executes the
  smallest-timestamp one only when it has received at least one operation from
  every transaction manager (so nothing older can still arrive). No restarts,
  but needs a message stream from every TM (send null/heartbeat operations),
  and degrades toward serial execution.
- **Multiversion TO**: reads never rejected (read the version with the
  largest W-ts ≤ ts(T)); a write is rejected if a younger transaction has
  already read the version it would supersede. Snapshot-style reads for
  read-only transactions with no locks and no coordination beyond the
  timestamp — the pattern modern systems use with synchronized clocks.

## 4. Optimistic / validation-based

Execute without synchronization, validate at commit. Distributed validation
requires each site to validate its subtransaction *and* the sites to agree on
a common serialization order — so validation folds into the prepare phase and
uses a global timestamp or validation order. Wins at low contention, and
with high message latency it avoids holding locks across round trips; loses
at high contention because work is discarded after an expensive distributed
execution.

## 5. Heterogeneous federations (multidatabases)

A global transaction manager (GTM) submits subtransactions to autonomous local
DBMSs that also run local transactions the GTM never sees.

- **Indirect conflicts**: global G1 and G2 may not conflict directly at any
  site, yet a local transaction L1 at site 1 conflicts with both (G1 → L1 →
  G2) and L2 at site 2 creates G2 → L2 → G1. The global order is cyclic and
  invisible to the GTM.
- **Local guarantees that suffice**: if every local DBMS produces
  *rigorous* histories (no item read or written until the last writer and
  readers that conflict have committed — strict 2PL behaves this way), the GTM
  can achieve global serializability by controlling only the *commit order*
  of global subtransactions. The general property is **commitment ordering**
  (Raz 1992): the commit order of conflicting transactions matches their
  serialization order; if all sites guarantee it, global serializability
  follows from atomic commitment.
- **Forced local conflicts (tickets)** (Georgakopoulos, Rusinkiewicz, Sheth
  ICDE 1991): every global subtransaction first reads and increments a ticket
  item at that site, forcing a direct conflict between any two global
  subtransactions there; the local scheduler orders them, and the ticket
  values expose that order to the GTM.
  - *Optimistic ticket method*: unrestricted ticket taking; the GTM keeps a
    global ticket graph (edge Gi → Gj when Gi's ticket < Gj's at some common
    site) and aborts at commit if the graph has a cycle. Good at low
    contention.
  - *Conservative ticket method*: the GTM only allows a ticket take that keeps
    the ticket graph acyclic. Fewer aborts, more run-time checking; better at
    high contention.
  Cost: the ticket is a hot spot at every site — every global subtransaction
  conflicts with every other.

## 6. Deadlock models and the global wait-for graph

WFG: vertex per active transaction, edge Ti → Tj when Ti waits for a lock Tj
holds. A **local WFG** covers waits at one site; the **global WFG** is the
union including inter-site waits (a subtransaction waiting for its own remote
sibling, or a remote transaction holding a lock).

Request models determine what "deadlock" means:
- *Single-resource* (out-degree ≤ 1) and *AND* model (a transaction needs all
  requested resources): deadlock ⇔ cycle in the WFG. Database lock waits are
  AND-model.
- *OR* model (any one of several resources suffices — e.g. read any replica):
  deadlock ⇔ a **knot** (every vertex reachable from the set leads back into
  it); detection needs a diffusing computation, not cycle search.
- *AND-OR*, *k-out-of-n*, unrestricted: generalizations with more expensive
  detection (Knapp, Computing Surveys 1987).

Three strategies: **prevention** (never allow a wait that could close a
cycle), **avoidance** (schedule so cycles cannot form, e.g. ordered resource
acquisition), **detection and resolution** (allow waits, find cycles, abort a
victim). Timeouts are a degenerate detector.

## 7. Prevention with timestamps

Assign each transaction a timestamp at birth and keep it across restarts
(that is what prevents starvation). When Ti requests a lock held by Tj:

| Scheme | ts(Ti) < ts(Tj) (Ti older) | ts(Ti) > ts(Tj) (Ti younger) |
|---|---|---|
| Wait-die (non-preemptive) | Ti waits | Ti aborts ("dies"), restarts later with same ts |
| Wound-wait (preemptive) | Ti wounds Tj (Tj aborts unless already committing) | Ti waits |

Both admit only edges in one timestamp direction, so no cycle is possible and
no cross-site detection is needed. Cost: unnecessary aborts. Wound-wait
generally aborts less, since a young requester waits instead of dying; a
wounded transaction in the 2PC prepared state cannot be aborted, so the wound
must be ignored once the victim has voted YES.

## 8. Detection architectures

**Centralized**: every site ships its local WFG (initially) and then deltas
(edge add/remove) to a designated detector, which runs cycle detection on the
global graph. Simple; detector is a bottleneck and single point of failure;
message volume grows with lock churn. Natural partner of centralized 2PL;
used by Distributed INGRES.

**Hierarchical** (Menascé & Muntz 1979; Ho & Ramamoorthy 1982): sites form a
tree; each inner detector merges children's WFGs and finds cycles confined
to its subtree; only cross-subtree dependencies propagate upward. Cycles among
nearby sites (the common case under geographic clustering of access) are found
early and cheaply. Must coordinate so two levels do not resolve the same cycle.

**Distributed**: every site runs a detector; potential-deadlock information
moves between sites. Two main families (Krivokapić, Kemper, Gudes VLDB J
1999 compare them):

### 8.1 Path pushing (Obermarck, R*)

Each site augments its local WFG with a special node **EX** standing for
"external": an edge Ti → EX when Ti waits on a remote site, EX → Tj when a
remote transaction waits on local Tj.
```
on each detection round at site s:
    add received path strings to local WFG
    find cycles; a cycle without EX is a real local deadlock → resolve
    for each path EX → T1 → ... → Tn → EX:
        if id(T1) > id(Tn):                # an ordering rule on endpoint ids (direction is a convention) so only one site pushes a given potential cycle
            send the path to the site(s) where Tn waits
```
The ordering rule roughly halves message traffic. Weakness: sites build
their view from paths captured at different times, so the combined graph is
not a consistent snapshot; the original algorithm can report **phantom
(false) deadlocks**.

### 8.2 Edge chasing — Chandy–Misra–Haas (AND model)

No graph is shipped; a fixed-size probe follows wait edges.
```
probe(i, j, k): initiated on behalf of blocked Ti, sent by Pj to Pk (Pj waits for Pk)

when Pi becomes blocked (or a wait has lasted > threshold):
    for each Pk that Pi waits for: send probe(i, i, k)

on receiving probe(i, j, k) at Pk:
    if Pk is blocked and has not already forwarded a probe for initiator i:
        if k == i: declare deadlock (Pi is on a cycle)
        else: mark forwarded(i); for each Pm that Pk waits for: send probe(i, k, m)
    # an active (non-blocked) Pk discards the probe
```
Properties: message size O(1); a cycle is detected by at least one
initiator on it; no deadlock is reported unless a cycle existed while the
probe traversed it, because in the AND model a transaction on a cycle cannot
unblock. Spontaneous aborts (application abort, lock timeout) break that
assumption — a probe may return over an edge that has since disappeared, so
the victim chooser should re-verify that the waits still exist. Engineering:
initiate probes only after a wait exceeds a small threshold (most waits end
quickly), and attach a priority to probes (e.g. only forward probes whose
initiator is younger than the holder) so that exactly one transaction per
cycle initiates resolution. The OR-model version uses query/reply diffusion
and counts replies (knot detection).

### 8.3 Global-state detection

Take a consistent global snapshot (Chandy–Lamport TOCS 1985) of the wait
relations and run cycle detection on it (Bracha & Toueg 1985 for generalized
models). Correct by construction; costs a snapshot round.

### 8.4 Dynamic detection agents

Krivokapić et al. create deadlock-detection agents per group of transactions
that conflict on the same objects, merging agents as conflict sets merge —
detection effort scales with actual contention instead of a fixed topology.

## 9. Phantom deadlocks

A phantom deadlock is a cycle reported by the detector that does not exist in
the true global state: an edge was removed (transaction aborted for business
reasons, lock released, waiter timed out) but the removal had not reached the
detector when the cycle was evaluated. Centralized and hierarchical detectors
are prone to it because they work from asynchronously shipped deltas; path
pushing is prone because paths are snapshots from different moments.
Consequences are performance-only (an unnecessary abort), but under high
churn they can dominate abort counts. Mitigations: version WFG edges by
(transaction id, wait epoch) and re-validate a cycle's edges with their
owning sites before aborting; use snapshot-based detection; or accept and
measure.

## 10. Resolution and victim selection

- Pick a victim that minimizes cost: youngest transaction (least work lost),
  transaction on the most cycles (breaks more at once), fewest locks held,
  fewest sites touched (cheapest abort fan-out), never a transaction in the
  2PC prepared state.
- **Duplicate detection**: several sites (or several probe initiators) may
  find the same cycle and each abort a different victim. Elect a resolver
  (e.g. the site of the lowest-id transaction on the cycle) or use the probe
  priority rule so only one initiator survives.
- After aborting, purge the victim's WFG edges and in-flight probes/paths
  (otherwise they re-create phantoms).
- **Timeouts** as the resolution strategy: correct only as a liveness
  backstop; too short aborts innocent long waits, too long stalls throughput.
  Use adaptive timeouts keyed on observed lock-hold times, and always keep one
  as a safety net behind any detector (detectors have bugs and partitions).

## 11. Implementation checklist

- WFG edges carry (waiter txn, holder txn, site, lock id, epoch); a cycle
  report includes the edges, so the resolver can validate.
- Lock tables expose "who blocks me" cheaply (holder list per lock) — the
  detector's input.
- Global transaction ids: (coordinator site, sequence) so every site can name
  a transaction without a lookup; timestamps for wait-die/wound-wait must be
  assigned once at the root and propagated to every subtransaction.
- Abort of a victim is a distributed operation: route it to the root
  coordinator, which aborts all subtransactions; do not let a remote detector
  abort one subtransaction locally while siblings continue.
- Never abort or wound a prepared subtransaction; deadlock involving a
  prepared transaction resolves only when the commit decision arrives.

> **Beyond EDBS:** Spanner uses wound-wait for read-write transactions
> (prevention, no global detector), with timestamps from TrueTime.
> CockroachDB queues waiters on the lock holder's transaction record and
> detects dependency cycles among queued pushers, aborting one transaction
> per cycle — edge chasing over transaction records rather than over sites.
> TiDB's pessimistic mode runs a deadlock detector at a single designated
> TiKV leader (centralized detection). In all of them the 2PC prepared-state
> rule above still applies. For snapshot isolation at scale (Percolator,
> CockroachDB) the write-write conflict path replaces most lock waits; see
> distributed-transactions.

Sources: Distributed Concurrency Control (p.1157); Distributed Transaction
Management (p.1222); Distributed DBMS (p.1177); Distributed Deadlock
Management (p.1181); Distributed Database Systems (p.1174).
