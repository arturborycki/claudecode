# Replication design space, the scaling argument, and replica-control architecture

Read this when choosing a replication architecture for a DBMS, when someone
claims "we'll just add replicas to scale writes", or when reviewing where the
replica-control logic lives (kernel vs middleware vs storage layer).

---

## 1. The vocabulary, made precise

| Term | Precise meaning (as used in this skill) |
|---|---|
| Logical item `x` | What the transaction names (row, key, page — the granularity the protocol reasons about). |
| Copy / replica `x^A` | The physical instance of `x` at site `A`. "Replica" is also used for a whole site holding a full copy. |
| Replica control | The mapping of each logical `r(x)` / `w(x)` to physical operations on copies, plus the rules that keep copies consistent. |
| Replicated CC | Concurrency control whose correctness criterion is defined over the logical database (1SR, 1-copy SI), not over each site separately. |
| Replication degree `r_x` | `|N_x|`, the number of copies of `x`. Full replication: `N_x = N` for all `x`; otherwise partial. |
| Eager (synchronous) | Replicas coordinate **before** the transaction commits. Note: "eager" fixes the *serialization decision* before commit; it does not require every copy to have *applied* the writes before commit (group-communication and Paxos protocols apply later). |
| Lazy (asynchronous) | The transaction commits at one site; propagation happens after commit (immediately, periodically, or freshness-triggered). Response is returned first, propagation second. |
| Primary copy (master) | Each item has one site where all its updates run first. May be per-item, per-partition, or one primary site for everything. |
| Update anywhere (group, multi-master) | Any replica may execute update transactions. |
| Symmetric update processing | Every replica fully executes each update transaction (statement / active replication / function shipping). |
| Asymmetric update processing | One replica executes; others install the resulting writeset (passive replication / state or delta shipping). |
| 1-safe / 2-safe | Primary-backup terms: 1-safe commits at the primary before the backup has the log; 2-safe commits only after the backup has it (and an agreement protocol makes the outcome atomic). |

Two orthogonal axes generate the classic 2x2 (Gray, Helland, O'Neil,
Shasha, SIGMOD 1996):

|                 | Primary copy (master)                                       | Update anywhere (group)                                        |
|-----------------|-------------------------------------------------------------|----------------------------------------------------------------|
| **Eager**       | One serialization point, synchronous push; simple; primary is the bottleneck and its loss stalls writes until failover. | Distributed locking + 2PC (textbook ROWA); or modern abcast/certification; deadlocks/aborts grow fast with N. |
| **Lazy**        | Classic log shipping / read replicas; no reconciliation; secondaries are stale; lost-commit window on failover (1-safe). | Multi-master async; conflicts detected after commit; needs reconciliation (LWW, merge, CRDT); divergence visible to clients. |

Add a third axis: **who executes** (symmetric vs asymmetric) and a fourth:
**granularity of a request** (single operation vs whole transaction vs
pre-declared stored procedure). Most real disagreements in design reviews
are about axes three and four, not the 2x2.

---

## 2. "The dangers of replication" — the scaling argument

Gray et al. built a simple analytic model (uniform access to a database of
`DB_size` items, transactions of `Actions` updates, `TPS` per node, `N`
nodes, every node holding every item) and derived how waits, deadlocks and
reconciliations scale. The exponents are what matter; consult the paper for
constants.

| Scheme | What grows | Growth in N (paper's model) | Why |
|---|---|---|---|
| Eager, update anywhere (distributed 2PL + 2PC) | Wait rate and deadlock rate | both ~N^3 (deadlocks also ∝ Actions^5/DB_size^2) | Total update work grows ~N (more nodes submitting) and each transaction becomes ~N times larger in physical actions and ~N times longer, so lock-hold time and collision probability both grow. |
| Eager, primary copy | Same deadlock formula as eager group (the model does not distinguish master from group), and the primary saturates | ~N^3 | The paper notes object-mastering would remove deadlocks only if each transaction updated a single item's master; the primary's capacity bounds update throughput. |
| Lazy, update anywhere | Reconciliation rate | ~N^3 | Same collision arithmetic, but collisions become post-commit conflicts that must be reconciled rather than waits. |
| Lazy, primary copy | Deadlocks at primary | quadratic, lower than eager group | No reconciliation, but stale reads; still a single write funnel. |
| Mobile / disconnected update anywhere | Reconciliation rate | ~N^2, and linear in disconnect time (`Disconnect_Time·(TPS·Actions·Nodes)^2/DB_size`) | Longer disconnects = more concurrent updates per item. |

Engineering conclusions that still hold:

1. **Update-anywhere replication does not scale writes.** Under full
   replication every update costs every replica something; conflict
   handling (waits, aborts, or reconciliations) grows super-linearly.
2. **Eager distributed locking is the worst combination**: lock-hold time
   includes WAN/LAN round trips to all copies, and the deadlock graph spans
   sites (a deadlock can involve a *single* logical item whose two copies
   were locked in different orders — impossible in a centralized lock
   manager).
3. The paper's proposed remedy was **two-tier replication**: base nodes run
   lazy-master (always-connected, 1SR among themselves); mobile nodes run
   *tentative* transactions locally, which are re-executed at the base with
   an application **acceptance criterion** (e.g., "price did not rise by
   more than X"). This is the ancestor of Bayou-style tentative/committed
   logs and of modern "local-first" designs.

What the 1996 model got "wrong" (why later work escaped it): it assumed
per-operation distributed locking and symmetric execution. The 2000s
cluster-replication work (Postgres-R, DBSM, Middle-R, Ganymed, Tashkent)
changed three fundamentals:

- **Order first, then decide locally**: a total-order broadcast fixes a
  global order of commit requests, so every replica runs a deterministic
  certification test and no distributed deadlock can form (see
  `si-and-group-communication-replication.md`).
- **One coordination round per transaction**, not per operation.
- **Asymmetric processing**: only one replica executes; others install a
  writeset that costs a fraction `wo` (write overhead) of execution.
- **Weaker isolation (SI)**: reads never conflict, so the conflict
  probability depends only on write-write overlap.

---

## 3. Scale-out arithmetic (use this in design reviews)

Model: `n` nodes, each with capacity `C` work units/s; a transaction costs 1
unit to execute; fraction `w` of transactions update; each data item has `r`
copies; load and data uniformly spread; communication and CC overhead
ignored (so these are *upper* bounds).

**Symmetric (every copy re-executes updates):**

```
n*C = (1-w)*L + r*w*L
scaleout = L/C = n / (1 + (r-1)*w)
```

**Asymmetric (one copy executes, r-1 copies install at cost wo):**

```
n*C = (1-w)*L + w*L*(1 + wo*(r-1))
scaleout = n / (1 + w*wo*(r-1))
```

Consequences:

- **Full replication (`r = n`) has a ceiling.** Symmetric: `scaleout -> 1/w`
  as `n -> inf` (w = 20% caps you at 5x, no matter how many nodes).
  Asymmetric: ceiling `1/(w*wo)`; with w = 0.2, wo = 0.15 the ceiling is
  ~33x, and you approach it slowly — "a few tens of nodes" is the
  practical limit the literature reports.
- **Constant replication degree (`r` fixed, partial replication) scales
  linearly** in `n`: `scaleout = n / const`. This is why every scalable
  system partitions first and replicates each partition 3–5 times.
- **Hybrid partial replication** (some nodes hold everything, others a
  fraction) still saturates: the full-copy nodes must install every update
  in the system.
- Symmetric vs asymmetric is the single biggest lever for update-heavy
  workloads; a writeset install (index maintenance + log write, no query
  execution, no predicate evaluation) is often 10–20% of execution cost.

**Quorums under the same model** (reads must touch `rq` copies, writes `wq`
copies, asymmetric install cost `wo`):

```
n*C = (1-w)*L*rq + w*L*(1 + wo*(wq-1))
```

With majority (`rq ≈ wq ≈ n/2`) and read-mostly load, the denominator is
dominated by `(1-w)*n/2`, so scale-out stays below ~2 regardless of `n`.
Quorums beat ROWAA only when the workload is overwhelmingly writes (the
literature's analytic study puts the crossover around 80–100% writes), and
predicate reads over collections (a `SELECT ... WHERE` over a table) are
disastrous: the coordinator must fetch the collection from a full read
quorum and reconcile versions per item before filtering.

---

## 4. Anatomy of a replica-control protocol (the five/six phases)

A protocol is characterized by which of these phases it uses and how often
(per operation vs per transaction):

```
1. client request      -> client proxy (JDBC/ODBC driver, client lib)
2. pre-processing      -> forward to 1/some/all replicas; distributed CC,
   coordination           ordering (e.g., abcast the request), load balancing
3. execution           -> 1 replica (asymmetric) or all (symmetric)
4. post-processing     -> certification/validation, writeset propagation,
   coordination           quorum aggregation, 2PC/Paxos/termination
5. result return       -> client
```

- **Lazy** protocols have no phase 2 and swap 4 and 5 (reply first).
- **Pessimistic eager** protocols act in phase 2 (order or lock before
  executing). **Optimistic eager** protocols act in phase 4 (certify after
  executing).
- **Constant vs linear message rounds**: distributed locking repeats 2–5 per
  write operation (linear); deferred-update/certification does one round
  per transaction (constant).
- **Voting vs non-voting termination**: 2PC-style agreement on the outcome
  (voting) vs every replica deciding the same outcome deterministically from
  the same totally ordered input (non-voting). Non-voting termination is
  what makes total-order protocols cheap.

### Where replica control lives

| Placement | Examples | Wins | Costs |
|---|---|---|---|
| Kernel / white box | Postgres-R, Postgres-R(SI), DBSM, Galera (as a patched engine) | Tuple-level writesets and readsets, fine-grained conflict detection, can hook commit order and group commit | Engine-specific, invasive, hard to maintain across versions |
| Middleware, black box | C-JDBC/Sequoia, Ganymed, conflict-aware schedulers | Works over unmodified (even heterogeneous) DBMSs | Sees only SQL text: must lock tables or conflict classes, cannot see which rows a statement touches; extra hop (4 messages per read instead of 2) |
| Middleware, gray box | Middle-R, Tashkent | Engine exports a small API (get writeset, apply writeset, commit in given order) | Needs vendor cooperation for that API |
| Storage layer (bottom-up) | Replicated block/log/storage services under a DBMS | Transparent availability for upper layers | Upper layers lose locality/semantic info; transactional semantics rebuilt on top |

### Statement vs writeset (transaction) replication

| | Statement (symmetric) | Writeset (asymmetric) |
|---|---|---|
| What is shipped | SQL statements, in a global order | Row images/deltas captured at the executing site |
| Determinism burden | Every statement must produce identical results everywhere: rewrite `NOW()`, `RAND()`, sequence calls, UDFs, non-deterministic `LIMIT` without `ORDER BY`, triggers, concurrency-dependent results | Only the apply must be deterministic |
| Covers | DDL, sequences, temp tables, session variables | Only what the capture mechanism sees (trigger-based capture misses sequence/auto-increment state, environment changes) |
| Mid-transaction failover | Easy: every replica holds the transaction context | The executing replica's failure aborts the transaction; client must retry |
| Performance | Every replica pays full execution | Usually better if capture and certification are cheap |

The non-determinism list for statement replication is a review checklist,
not trivia: a single `UPDATE ... WHERE r = 'Fred'` applied in different
orders relative to an `INSERT` of a Fred row produces permanently different
replicas ("system delusion"/split brain) and every later statement that
reads those rows amplifies the divergence.

> **Beyond EDBS:** Modern engines ship WAL/redo (physical or logical
> decoding) rather than either SQL or trigger-captured writesets — e.g.,
> PostgreSQL physical streaming replication and logical replication via
> logical decoding, MySQL row-based binlog. Row-based shipping removes the
> statement-determinism class of bugs but reintroduces the "what the
> capture misses" class (DDL, sequences, large objects in logical
> replication).

---

## 5. Primary-backup for availability

The dominant commercial HA pattern. Three sub-problems: normal-case
propagation, failover, and replica (re)integration.

**Propagation safety levels**

| Level | Commit acknowledged when | Lost on primary loss |
|---|---|---|
| 1-safe (lazy) | primary's local log is durable | the tail not yet shipped — both A and D are violated for those transactions |
| 2-safe (eager) | backup has received (and possibly hardened) the log; an agreement protocol (2PC or Paxos) ensures commit everywhere or nowhere | nothing, provided the backup that takes over has it |
| very safe / quorum | a majority (or all) hardened | nothing while a majority survives |

> **Beyond EDBS:** PostgreSQL exposes this spectrum per transaction through
> `synchronous_commit` (`off`, `local`, `remote_write`, `on`,
> `remote_apply`) combined with `synchronous_standby_names` (including
> `ANY k (...)` quorum form). `remote_apply` is the only level at which a
> read on the standby immediately after commit is guaranteed to see the
> write.

**Hot vs cold standby**: hot applies changes continuously (fast failover,
needs an equally powerful backup, and reads on it must cope with apply
conflicts); cold buffers and applies late (cheap hardware, long failover).

**Failover correctness checklist**

1. Exactly one new primary: requires agreement among backups (and, under
   partitions, a quorum or lease — otherwise both sides elect a primary).
2. The new primary must hold every transaction acknowledged to a client
   (2-safe), or the system must declare and report the lost window (1-safe).
3. In-flight transactions: if the client had not sent COMMIT, the driver
   raises an abort and the client retries. If COMMIT was sent and the reply
   lost, the outcome is **in doubt**: the driver must ask the new primary
   for the transaction's fate (requires a global transaction id that the
   backup learned) — never blindly retry a non-idempotent transaction.
4. Old primary must be fenced (epoch/term number checked on every write,
   STONITH, or lease expiry) before the new one accepts writes.

**Replica recovery / integration**: offline (stop processing, copy state,
resume) vs online (transfer state while processing continues). Transfer
choices: full copy; only items changed during downtime (needs change
tracking); or replay of the missed log suffix (only for a returning
replica; a brand-new replica needs a full copy). The invariant for online
recovery: **every transaction is reflected either in the transferred state
or in the stream delivered after the transfer — never neither, never
twice**. Group communication systems implement this with view changes:
the joiner's state transfer is defined relative to the view in which it
joins.

---

## 6. Partial replication

Full replication buys read locality and fault tolerance at the price of
the write ceiling in §3. Partial replication fixes the ceiling but makes
everything else harder:

- **Location**: a directory/catalog mapping items (or partitions) to sites;
  must itself be replicated and versioned.
- **Distributed queries**: a transaction needing items not held locally
  becomes a distributed query (data shipping, remote operators).
- **Concurrency control**: no site sees all updates, so you cannot rely on
  one global total order cheaply. A *genuine* partial replication protocol
  only involves sites holding copies of the items a transaction touches,
  and coordinates update transactions only (read-only transactions should
  be coordination-free) while keeping per-site metadata (clocks, vectors)
  small.
- **Practice**: co-locate data accessed together into partitions, replicate
  each partition 3–5x (odd, for majority), use consensus within a partition
  and a commit protocol across partitions (Spanner-style "2PC over Paxos";
  see `geo-replication-and-clocks.md`).

---

## 7. Autonomic replica provisioning

In shared clusters (multiple applications), a resource manager adds or
removes replicas per application to meet a latency SLA.

- **Adaptation delay**: a new replica must catch up (data migration), warm
  its buffer pool, and be folded into the load balancer. Latency stays high
  or even rises during this period.
- **Oscillation**: if the controller keeps sampling latency during the
  stabilization window it will add more replicas, then remove them later.
  Mitigate with smoothing, hysteresis, and freezing decisions until the
  previous adaptation stabilizes.
- **Disjoint vs fully overlapped allocation**: disjoint avoids buffer-pool
  interference but pays full adaptation delay; fully overlapped has no
  delay but interferes. **Partial overlap** keeps spare machines warm by
  applying batched updates for applications they do not currently serve.
- Proactive (model-based: queueing, utility, ML) vs reactive (thresholds)
  controllers; the database tier, with its long adaptation delay, needs
  prediction more than stateless tiers.
- Typical scheduler duties: track the replica set; route requests; sample
  metrics; provide 1SR across the set (often ROWA with a global order based
  on conservatively detected table-level conflicts — coarse, but fine for
  read-dominated e-commerce).

---

## 8. Multi-tier replication

Replicating only the database leaves the application server as a single
point of failure; replicating tiers independently breaks consistency at
failover (the app-server replica does not know which DB transactions its
dead peer committed).

- **Horizontal replication**: tiers replicated independently, then one tier
  is made replication-aware to handle failover consistently.
- **Vertical replication**: an (app server, DB server) pair is the unit;
  the app server encapsulates all replication logic and propagates both
  session state and persistent state at request end.
- **Correctness criteria**: *exactly-once* execution of each client
  request despite failover and re-execution (e-transactions, Frølund and
  Guerraoui; the related x-ability criterion defines correctness as
  equivalence to some failure-free history), and *1-copy correctness* of
  the whole multi-tier system. Application-server caches must be
  *cache-transparent* (allow exactly the executions the uncached system
  allows), which is non-trivial when the DB runs SI.
- **x-ability in practice** (Frølund & Guerraoui): model each replicated
  action by its start and completion events and require the observed
  history to be equivalent to a failure-free one. Equivalence is built
  from two action classes, so classify every side effect a failover may
  re-drive: *idempotent* actions (re-running n times = once, e.g., writing
  a fixed value keyed by request id) and *undoable* actions (cancellable
  up to a commit point, like a transaction; a cancelled run = no run).
  Anything neither idempotent nor undoable (sending an email, calling a
  non-transactional external service) cannot be made exactly-once by
  retry and needs deduplication at the receiver. x-ability is a safety
  *and* liveness property (bad partial histories never occur; the request
  eventually completes) and composes per service, but it does not
  constrain concurrency between different requests — pair it with an
  isolation criterion.
- State-machine replication of a multi-threaded server requires a
  deterministic thread scheduler; otherwise identical input orders still
  diverge.

---

## 9. Design-review decision table

| Requirement | Default architecture | Watch out for |
|---|---|---|
| HA for one OLTP database, LAN | Primary-backup, 2-safe (or quorum-sync) with fencing | Split brain without a quorum/lease; in-doubt commits at failover |
| Read scale-out, freshness tolerance | Lazy primary-copy with read replicas, session guarantees | Stale reads after own writes; replica apply lag under heavy writes |
| Read + moderate write scale-out, strong consistency, cluster | Certification over total-order broadcast, 1-copy SI, asymmetric | Write skew (SI), certifier/GCS throughput, ordered-commit kills group commit |
| Write scale-out | Partition + replicate each partition (consensus per partition) | Cross-partition transactions; hot partitions |
| Geo, low latency, always writable | Causal+ / PSI / CRDTs, with explicit conflict semantics | Lost updates under LWW; invariants needing coordination |
| Geo, strong consistency | Consensus across DCs per partition, commit protocol across partitions | ≥1 WAN round trip per write; leader placement |

---

Sources: EDBS — Data Replication (p.833), Replica Control (p.3161),
Replication for Scalability (p.3194), Partial Replication (p.2685),
Replication for Availability and Fault Tolerance (p.3187), Middleware
Support for Database Replication and Caching (p.2257), Replication in
Multitier Architectures (p.3200), Autonomous Replication (p.236),
Replication (p.3177), Concurrency Control for Replicated Databases (p.566);
Gray et al. SIGMOD 1996; Jiménez-Peris et al. TODS 2003 ("Are quorums an
alternative for data replication?"); Wiesmann et al. ICDCS 2000; Frølund &
Guerraoui (x-ability; e-transactions, IEEE TSE 2002); Middleware Support for
Precise Failure Semantics (EDBS, fragment, p.2264).
