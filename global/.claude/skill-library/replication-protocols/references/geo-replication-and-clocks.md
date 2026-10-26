# Multi-datacenter replication protocols, coordination avoidance, and clocks

Read this when replicas are in different datacenters/regions, when
deciding what must be coordinated across the WAN, or when using physical
or hybrid clocks (commit wait, uncertainty intervals, HLC) for ordering.

---

## 1. The physics and the four design questions

- Light needs ~133 ms for a round trip between antipodes over ~40,000 km;
  real WAN RTTs are tens to hundreds of ms and spike to seconds under
  congestion, versus tens to hundreds of microseconds inside a DC.
- Consequence for strongly consistent writes on one contended item: if two
  replicas on opposite sides of the planet must exchange a message per
  conflicting transaction (~67 ms one way), the item sustains at most on
  the order of ~15 such transactions per second. Coordination cost is
  bounded below by geography, not by engineering.

Design questions for any geo protocol:

1. **How many WAN round trips per update** (0, 1, 2+)? Reads?
2. **When is the client acknowledged** — before remote replicas have the
   update (asynchronous: fast, risks loss on DC disaster and conflicts) or
   after (synchronous)?
3. **How are conflicting concurrent updates handled** — prevented
   (primary, consensus, locking), merged (commutative ops, CRDTs, merge
   functions), or reordered after the fact?
4. **Who coordinates** — a replica (adds a hop if remote), or the client
   library itself (saves a hop, avoids replica bottlenecks)?

---

## 2. Protocol classification (synchrony x storage service)

| | Read-write register | State machine (read-modify-write) | Transactions |
|---|---|---|---|
| **Synchronous** | Write-all (read nearest); write-quorum (majority write, majority read, highest timestamp) | State-machine approach over consensus (Paxos, Chandra–Toueg ◇S, Viewstamped Replication, PBFT) | 2PL+2PC over all copies; transaction total ordering (atomic broadcast deferred update; consensus log as in Megastore; Calvin's deterministic ordering); consensus+2PL+2PC (Spanner, MDCC) |
| **Asynchronous** | Primary copy; last-timestamp-wins; history merge (causal order + merge function: Dynamo vector clocks, COPS dependency lists) | Primary copy (PNUTS per-record master, Azure Table); commutative operations; history merge (Eiger); history reorder (Bayou) | Primary copy / primary DC (Calvin async mode); preferred copy (Walter → PSI); message futures (serializable, one fast DC); commutative ops over ADTs; history merge; transaction reorder |

### Synchronous read-write

- **Write-all**: writes to every replica, read from nearest. Concurrent
  writes must be applied in the same order: designate an ordering replica
  (bottleneck) or stamp unique timestamps and order by them. Write latency
  = slowest replica; one dead replica blocks writes.
- **Write-quorum**: send to all, wait for a majority; reads also go to a
  majority and take the highest timestamp. Majority intersection gives
  "reads see the latest completed write"; slow replicas are masked.
  (Linearizability additionally needs reads to write back what they return
  before returning — ABD.)

### Synchronous transactions

- **Copies as items**: the replicas of an item are treated as distinct
  items written in the same transaction (2PL + 2PC across DCs) — correct,
  ≥2 WAN RTTs, blocking on coordinator loss.
- **Transaction total ordering**: each transaction executes at one replica;
  update transactions are totally ordered by atomic broadcast or a
  consensus log; replicas validate deterministically in order ("order then
  validate") or validate for a candidate slot then try to claim it
  ("validate then order"). Megastore runs a Paxos log per entity group.
- **Deterministic ordering before execution** (Calvin): order first, then
  every DC executes deterministically with 2PL; partitioned state allowed;
  synchronous mode replicates the input log before execution.
- **Consensus + 2PL + 2PC** ("2PC over Paxos", Spanner): each partition is
  a Paxos group spanning DCs; lock acquire/release, prepare and commit are
  inputs to the partition's replicated state machine; a coordinator drives
  2PL/2PC across groups. Coordinator and participants are fault-tolerant,
  so 2PC no longer blocks on a single machine's failure. MDCC (Kraska et
  al. EuroSys 2013) uses the same structure but cuts WAN round trips with
  Fast/Generalized-Paxos-style per-record options so the common
  conflict-free commit takes one WAN round trip.
- **Replicated Commit** (Mahmoud et al. VLDB 2013) inverts the layering:
  run 2PC *inside* each DC and Paxos *across* DCs on the commit decision
  ("Paxos over 2PC"), so a commit needs a majority of DCs to vote, with
  fewer cross-DC round trips than Spanner-style layering for some
  workloads.

### Asynchronous protocols and their failure modes

- **Primary copy**: serializes writes per item at its primary; reads
  anywhere (stale off-primary). Writes pay a WAN RTT to a remote primary;
  the primary is a write bottleneck; acknowledged-but-unshipped writes are
  lost if the primary DC is destroyed — bound the loss window by throttling
  writes when the propagation backlog exceeds a time budget (e.g., 30 s).
- **Last-timestamp-wins**: simple, loses concurrent writes.
- **History merge**: apply writes in causal order (track causality with
  vector clocks or explicit dependency lists); merge concurrent writes
  with an application merge function that must guarantee convergence.
  Provides causal consistency; burden is writing a correct merge.
- **Commutative operations**: choose update functions that commute; each
  replica applies in arrival order; converges without merge or primary.
- **History reorder** (Bayou): tentative order on receipt, stable order
  later; replicas undo/redo when the order changes; effects seen by the
  client can change.
- **Preferred copy** (Walter): each object has a preferred site; updates
  to objects whose preferred site is local commit without WAN
  coordination; isolation weakens to PSI.
- **Message futures** (Nawab, Agrawal, El Abbadi CIDR 2013): replicas
  exchange logs periodically; a local transaction commits when every
  replica has acknowledged its log up to the point before the
  transaction started and its read items have not changed. Serializable;
  one chosen DC that sends its log rarely commits almost without waiting,
  at the expense of the others.

---

## 3. Specific designs worth knowing

### Spanner (Corbett et al. OSDI 2012 / TOCS 2013)

- Data sharded into Paxos groups (leaders hold time-based leases);
  read-write transactions use 2PL at leaders and 2PC across groups with a
  Paxos-replicated coordinator.
- External consistency (strict serializability) from **TrueTime** (§6):
  commit timestamp `s ≥ TT.now().latest` at commit time, then **commit
  wait** until `TT.after(s)` before releasing locks / acknowledging, so
  any transaction starting after the ack gets a larger timestamp.
- Snapshot reads at a timestamp at any sufficiently up-to-date replica
  (a replica can serve a read at `t` once its "safe time" ≥ `t`);
  read-only transactions are lock-free.
- Optimized for read-dominated workloads; read-write throughput on
  contended data is bounded by WAN commits.

> **Beyond EDBS:** The TrueTime mechanics above are from the Spanner
> papers, not from the EDBS entries (which cite Spanner only as
> "consensus + 2PL + 2PC"). The paper reports TrueTime uncertainty ε
> typically between about 1 and 7 ms, so commit wait is a few
> milliseconds on average.

### Walter and PSI (Sovran, Power, Aguilera, Li SOSP 2011)

- Preferred site per object; vector timestamps define site-local
  snapshots and causal dependencies.
- **Fast commit**: all written objects preferred locally → commit locally,
  propagate asynchronously in causal order.
- **Slow commit**: a 2PC-like validation among the preferred sites of the
  written objects; any "no" (write-write conflict with a committed
  transaction) aborts.
- **csets** (counting sets): a commutative set type whose updates never
  conflict, so they always fast-commit.
- PSI guarantees: site-local snapshot reads; no write-write conflicts
  between transactions concurrent at *any* site; if `T_j` started at a
  site after `T_i` committed there, `T_j` commits after `T_i` everywhere
  (causality). Allows **long fork**: two sites see two non-conflicting
  transactions in opposite orders.

### COPS and Eiger (Lloyd et al. SOSP 2011, NSDI 2013)

- **Causal+**: causal consistency plus convergent conflict handling (LWW
  or application handler).
- Client library tracks a **context** of dependencies (versions read or
  written). A put carries its *nearest* dependencies; the remote DC does
  not expose the write until a **dependency check** confirms each
  dependency is locally committed — checks go to the local partitions
  owning those keys, so the design scales across partitions without a
  global sequencer.
- COPS-GT adds read-only **get transactions**: a causally consistent
  snapshot in at most two rounds of local reads.
- Eiger extends to column families, write-only transactions, and
  operation-level dependency tracking.

### PNUTS, Dynamo, and others (for contrast)

- PNUTS: per-record master (can migrate to where writes originate),
  timeline consistency per record, reads may be stale or "latest".
- Dynamo: sloppy quorums, vector-clock siblings, application merge.
- G-Store: groups keys accessed together onto one node dynamically so
  multi-key transactions are single-node.

---

## 4. Coordination avoidance: what actually needs the WAN

Serializability is a conservative, application-agnostic way to preserve
integrity: if each transaction preserves invariants alone, a serializable
composition does too. Kung & Papadimitriou (1979): without semantic
knowledge, anything weaker than serializability can violate some
integrity constraint. So: the more semantics the engine knows, the more
coordination it can safely skip.

| Technique | Knowledge needed | Guarantee |
|---|---|---|
| Eventual consistency | none | convergence only; no safety |
| **Invariant confluence** (Bailis et al. VLDB 2015) | invariants + merge | Necessary and sufficient for coordination-free invariant preservation: the set of invariant-satisfying reachable states must be closed under merge. Example: assigning user ids is not confluent for "ids unique" but is for "ids non-negative". A study of open-source apps found most invariants (~87%) confluent. |
| Program analysis (Homeostasis, Sieve) | program text | automatically decide which operations need coordination |
| Annotations (SDD-1 lineage, RedBlue) | programmer marks conflicting op classes | coordinate only marked pairs |
| Commutativity | operations return the same results in any order | sufficient, not necessary; replicas execute in different orders |
| Monotonicity (CALM) | program without non-monotone constructs (negation, aggregation over incomplete inputs) | deterministic outcome despite reordering, without coordination; not the same as arbitrary invariants |
| Restricted APIs / ADTs | the data type (CRDTs, RAMP for atomic visibility of multi-key writes and some materialized views) | per-type guarantees, no lost updates for the type |
| Escrow / demarcation | numeric constraints | split slack among sites (e.g., a balance across five DCs); communicate only when a site exhausts its share |
| Compensation (sagas, apologies) | per-conflict repair actions | eventual repair; cannot retract external effects (a printed boarding pass) |
| WAN serializability + data modeling | access patterns | keep transactions within one partition/group (entity groups, G-Store) to shrink coordination scope |

Also: application consistency criteria (uniqueness, referential integrity,
non-negativity) are not the same thing as register-level consistency
models; CAP restricts linearizability, not arbitrary integrity criteria.

---

## 5. WAN caching and edge replication

- **Origin (primary) server** holds the authoritative database; edge
  servers hold full replicas, partial (per-table) replicas, content-aware
  caches (query-template based: a cached result for `price < 50` can
  answer `price < 20`), or content-blind result caches keyed by query
  text. No scheme dominates; systems need several.
- **Placement**: choose K of N candidate locations to minimize a weighted
  cost `Σ w_k · res_k` (latency, hops, bandwidth); exponential exact
  solutions → heuristics. Distinguish server placement (slow, global) from
  data placement (runtime, per object).
- **Propagation forms**: state shipping, delta shipping (passive,
  asymmetric) vs function shipping (active, symmetric); push (origin knows
  all replicas) vs pull (cache validates against origin on access).
- **Middleware caches**: parse cache and metadata cache keyed by
  prepared-statement skeletons; result cache with invalidation at
  database/table/column granularity; primary-key point lookups need no
  invalidation on insert; optional per-query staleness limits.

---

## 6. Clocks

### 6.1 Physical clocks (what EDBS gives)

A physical clock is a periodic physical process plus a way to count it
(Earth rotation, quartz oscillator, caesium transitions defining TAI).
Every concrete timestamp is a reading of some physical clock; a temporal
database's timeline may need several physical clocks spliced together.
For replication the relevant facts are: clocks drift (ppm-level for
quartz), synchronization (NTP/PTP) bounds offset only probabilistically
unless the bound is measured and enforced, and clocks can step backwards
or forwards on resynchronization.

### 6.2 Logical and vector clocks

- **Lamport clocks**: scalar `L`; `L := L+1` on local event; on receive
  `L := max(L, L_msg) + 1`. If `a → b` then `L(a) < L(b)`, not conversely.
- **Vector clocks**: exact characterization of happens-before; O(#nodes).

### 6.3 Bounded-uncertainty time (TrueTime-like)

> **Beyond EDBS:** `TT.now()` returns an interval `[earliest, latest]`
> guaranteed to contain absolute time; ε = half-width, derived from GPS
> and atomic-clock time masters plus a worst-case local drift assumption
> applied since the last sync. Two rules give external consistency:
> (a) *start*: pick commit timestamp `s ≥ TT.now().latest`;
> (b) *commit wait*: do not make the commit visible until
> `TT.now().earliest > s`. Cost ≈ 2ε per commit, overlapped with the
> Paxos round. If the drift assumption is violated (bad oscillator), the
> guarantee silently breaks — machines whose clocks misbehave must be
> evicted.

### 6.4 Hybrid logical clocks (HLC)

> **Beyond EDBS:** Kulkarni, Demirbas et al. (2014). Timestamp `(l, c)`:
> `l` tracks the maximum physical time seen, `c` is a bounded logical
> counter for events within the same `l`.
>
> ```
> send / local event (pt = physical clock):
>     l_old = l;  l = max(l_old, pt)
>     c = (l == l_old) ? c + 1 : 0
> receive message (l_m, c_m):
>     l_old = l;  l = max(l_old, l_m, pt)
>     if   l == l_old == l_m: c = max(c, c_m) + 1
>     elif l == l_old:        c = c + 1
>     elif l == l_m:          c = c_m + 1
>     else:                   c = 0
> ```
>
> Properties: respects happens-before like a Lamport clock; `l` stays
> within the clock-synchronization error of physical time; fits in 64 bits
> (e.g., 48-bit ms + 16-bit counter); usable as MVCC timestamps and for
> LWW tie-breaking without the "fast clock wins forever" pathology being
> unbounded. Used by CockroachDB and others (MongoDB uses a hybrid
> cluster time).

### 6.5 Uncertainty intervals without atomic clocks

> **Beyond EDBS:** CockroachDB-style: assume a configured maximum clock
> offset `max_offset`; a transaction reading at timestamp `t` treats any
> committed value with timestamp in `(t, t + max_offset]` as possibly in
> its past and restarts (or pushes its read timestamp) instead of
> ignoring it. Nodes whose measured offset exceeds the bound must
> self-terminate, otherwise serializability (and linearizability for
> single-key ops) can be violated. This trades commit wait for occasional
> read restarts and gives serializability, but not strict serializability
> across unrelated keys without additional measures.

### 6.6 Where clocks are safe and unsafe

| Use | Safe if | Unsafe when |
|---|---|---|
| Leader leases | bounded drift rate (not offset) between holder and grantors, lease shorter than election timeout margin | VM pauses / GC stalls longer than the lease (old leader keeps serving reads) — fence with epochs |
| LWW conflict resolution | you accept lost concurrent writes | clocks skew → later writes lost |
| Snapshot read timestamps | timestamps from HLC/TrueTime with closed-timestamp/safe-time tracking | reading at `t` at a replica that may still receive commits `< t` |
| Freshness bounds (staleness ≤ Δ) | clock offset ≪ Δ | Δ comparable to offset |
| Commit ordering for external consistency | measured, enforced uncertainty bound + commit wait | NTP-only "probably within 10 ms" |

---

## 7. Review checklist for a geo design

- Per operation type: number of WAN RTTs, acknowledgment point, behaviour
  under DC loss (data loss window) and under partition (which side
  serves which operations).
- Leader/primary placement policy and its effect on write latency for each
  region; follow-the-workload migration correctness.
- Conflict semantics stated per data type (LWW? merge? CRDT? abort?).
- Causality tracking metadata size, and false-dependency latency if
  compressed.
- Clock assumptions written down with the enforcement mechanism (offset
  monitoring, self-fencing).
- Which invariants require coordination; are they confined to
  single-partition or single-DC transactions by data modeling?

---

Sources: EDBS — Multi-data Center Replication Protocols (p.2314),
Multi-datacenter Consistency Properties (p.2320), WAN Data Replication
(p.4584), Physical Clock (p.2758), Replication with Snapshot Isolation
(p.3207), Concurrency Control for Replicated Databases (p.566),
Middleware Support for Database Replication and Caching (p.2257),
Causal Consistency (p.406); Corbett et al. OSDI 2012; Sovran et al. SOSP
2011; Lloyd et al. SOSP 2011, NSDI 2013; Kraska et al. EuroSys 2013;
Mahmoud et al. VLDB 2013; Nawab et al. CIDR 2013; Baker et al. CIDR 2011;
Thomson et al. SIGMOD 2012; Cooper et al. VLDB 2008; Bailis et al. VLDB
2015, SIGMOD 2014; O'Neil TODS 1986; Lamport CACM 1978; Kulkarni et al.
2014 (HLC).
