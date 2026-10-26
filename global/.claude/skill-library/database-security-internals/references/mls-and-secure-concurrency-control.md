# MAC, multilevel secure DBMSs, covert channels and secure transaction processing

Scope: lattice-based mandatory access control (Bell–LaPadula and its database
interpretation), MLS/DBMS architectures, the multilevel relational model and
polyinstantiation, the inference and aggregation problems, covert channels
created by concurrency control and commit protocols, the secure CC/commit
protocols that close them, and repair after malicious transactions. Even if
you never build a classified-data DBMS, this material is the clearest
treatment of *how engine mechanisms (locks, timestamps, aborts, unique
constraints) leak information*, which is directly relevant to multi-tenant
engines.

---

## 1. Lattice model

- Security classes `L` with a **dominance** partial order `⪯` (reflexive,
  antisymmetric, transitive). A class is typically `(level, compartments)` with
  level from a total order (U < C < S < TS) and compartments a set;
  `(l1, C1) ⪯ (l2, C2)` iff `l1 ≤ l2 ∧ C1 ⊆ C2`. Join = (max level, union),
  meet = (min level, intersection), so `L` is a lattice. `S{A}` and `S{B}` are
  incomparable.
- Each object `o` has a classification `λ(o)`; each user a clearance `λ(u)`; a
  user may log in at any level `l ⪯ λ(u)` and every subject (session,
  transaction, process) inherits the login level.
- Legal flows go only upward (from dominated to dominating class). All other
  flows are violations, whether through data (direct) or through system
  resources (covert).

### 1.1 Bell–LaPadula (MITRE, 1973/1975)

- **Simple security (no read up)**: subject `s` may read `o` only if
  `λ(o) ⪯ λ(s)`.
- **★-property (no write down)**: `s` may write `o` only if `λ(s) ⪯ λ(o)`.
- **Restricted ★-property** (used by virtually all MLS DBMSs): write only at
  your own level, `λ(s) = λ(o)`. Rationale: plain ★ lets a low subject
  *blind-write* (overwrite) high data — an integrity attack the confidentiality
  model does not forbid.
- BLP constrains direct flows only. A high subject can still signal a low one
  through lock state, timing, aborts, resource exhaustion, or the visible
  failure of a low operation. **Noninterference** (Goguen & Meseguer, IEEE S&P
  1982) is the stronger semantic goal: the outputs observed by low subjects must
  be identical whether or not any high subject acted. Secure CC (§5) is
  noninterference applied to the scheduler.

### 1.2 What changes for a DBMS vs an OS

- Objects are fine-grained and heterogeneous: database, relation, tuple,
  attribute, element (cell). Labels may be attached at any of these.
- Many logical objects map onto the same physical object (a page holds tuples
  of several levels; a view mixes levels), so OS file-level MAC cannot enforce
  tuple-level policy — this is why the DBMS needs its own trusted mediation.
- Derived data has a computed label: the label of a query result element is at
  least the join (least upper bound) of the labels of everything that
  influenced it, including tuples used only in predicates.

---

## 2. MLS/DBMS architectures

| Architecture | Idea | Trust placed in DBMS | Weak spots |
|---|---|---|---|
| Integrity lock (MITRE; prototypes on MISTRESS and INGRES) | Untrusted DBMS backend; a trusted filter stamps each tuple with its label and a cryptographic checksum (seal) over data+label, and verifies seals on retrieval | None in the DBMS | Untrusted DBMS sees all data and can encode high data into what it returns to low users (choice/order of tuples); performance cost of sealing |
| Kernelized / TCB subset (Hinke–Schaefer on Multics; SeaView by SRI) | Decompose each multilevel relation into single-level fragments stored in OS objects at their own level; the trusted OS kernel enforces MAC; one untrusted DBMS instance per level recombines fragments | Small: MAC is enforced by the OS; DBMS instances are single-level | Recombination cost (joins/unions of fragments); read-down requires reading lower-level fragments, which drives the secure-CC problem |
| Trusted subject (TRW ASD on ASOS; most commercial MLS products, e.g. Oracle Label Security, Trusted RUBIX) | One DBMS process is a trusted subject allowed to violate ★ internally and enforces tuple/element MAC itself | Large: the whole DBMS is in the TCB and must be evaluated (Trusted Database Interpretation, 1991) | Assurance of a large code base; every engine mechanism is a potential channel |
| Distributed / replicated (Air Force Summer Study 1982; SINTRA at NRL; Unisys SDDBMS) | One single-level backend per level; the backend at level l stores replicas of all data with class ⪯ l; a trusted front end routes queries | Front end only | Update propagation to dominating replicas must preserve serializability without downward signals (§5.3); storage blow-up |

Element-level labels plus a trusted subject is the dominant commercial design;
it is also what "row-level security with labels" in multi-tenant SaaS engines
reinvents.

---

## 3. The multilevel relational model and polyinstantiation

### 3.1 Labels in the schema

A multilevel relation scheme `R(A1, C1, ..., An, Cn, TC)`: each data attribute
`Ai` has a classification attribute `Ci`; `TC` is the tuple class, the join of
the `Ci` (SeaView: Denning, Lunt et al.; Jajodia & Sandhu, SIGMOD 1991). A user
at level `c` sees the *instance at c*: element values with `Ci ⪯ c`, other
elements shown as null (or the tuple filtered if its key is not visible).

Integrity properties of the model:
- **Entity integrity**: the apparent key attributes are non-null and uniformly
  classified, and all non-key classifications dominate the key classification.
- **Null integrity**: nulls are classified at the key's level; a tuple
  subsumed by another (same values, fewer non-nulls) is dropped.
- **Interinstance integrity**: the instance at `c` is derived from higher
  instances by filtering — the views at different levels are consistent.
- **Polyinstantiation integrity**: the functional dependency
  `AK, C_AK, Ci → Ai` — for a given apparent key and attribute classification,
  there is one value.

### 3.2 Why polyinstantiation exists

Scenario: a high (S) tuple with key `k` exists; a low (U) user inserts key `k`.
- If the engine rejects with a unique-key violation, it has told U that a
  hidden tuple with key `k` exists: a **signaling channel** (one bit per probe).
- If it accepts, two tuples with apparent key `k` now exist at different
  classes: **entity polyinstantiation**.

Symmetric case: a high user updates an attribute of a low tuple. Overwriting is
a write-down (forbidden); refusing leaks nothing but loses the update; storing
a second version of that element classified high gives **element
polyinstantiation** (a "cover story" for low users is the military use).

Trade-off stated in EDBS: multiple values for one real-world entity weaken
integrity; refusing them opens a channel. There is no resolution that keeps
both; engines choose per relation. Engineering consequences for any engine with
hidden rows (including RLS multi-tenant engines):
- Unique indexes must be scoped by label (or tenant) or they become existence
  oracles. Global uniqueness across tenants is a cross-tenant channel.
- Foreign keys from a low relation to a high relation are illegal (the check
  reads up); from high to low are fine.
- Upserts (`ON CONFLICT`, `MERGE`) are existence oracles unless conflict
  detection is restricted to visible rows.

### 3.3 Inference and aggregation

- **Inference problem**: deducing high information from low answers plus
  external knowledge or integrity constraints. In general undecidable
  (Thuraisingham, 1990, recursion-theoretic argument), so engines handle
  restricted classes via *security constraints* evaluated at design time
  (classify attributes so that dangerous combinations are high) or at query
  time (a constraint processor in the query path raises result labels).
- **Aggregation problem**: individual items are low, the collection is high
  (e.g. one supply depot vs the full list). Requires history-dependent
  enforcement — per-subject accounting of what has been released, the same
  machinery as Chinese-wall policies and statistical auditing (see
  `auditing-intrusion-and-compliance.md`).

---

## 4. Covert channels created by transaction processing

A covert channel uses a shared resource not intended for communication. In a
DBMS the shared resources are locks, timestamps, version stores, buffer frames,
the log, and abort decisions.

Two-level example, `low ⪯ high`, data item `x` at low. `T_h` (high) may read
`x` (read-down allowed); `T_l` (low) writes `x`.

**Lock-based (2PL)**: `T_h` takes a shared lock on `x` to send bit 1, or
abstains to send 0. `T_l` requests an exclusive lock and measures whether it
waits. Bandwidth = one bit per lock round; amplified with many items.

**Timestamp ordering**: with `ts(T_l) < ts(T_h)`, if `T_h` reads `x` first,
`rts(x)` advances and `T_l`'s later write is rejected and `T_l` aborts. `T_h`
signals by choosing whether to read. Optimistic validation has the same
problem whenever a low transaction can fail validation because of a high read.

Condition for a secure scheduler (informal noninterference): **the schedule,
delays and abort decisions observed by transactions at level l must be
independent of the actions of transactions at levels not dominated by l.**
Concretely:
1. A high transaction must never delay a low transaction.
2. A high transaction must never cause a low transaction to abort or restart.
3. Resource-allocation decisions visible to low (buffer eviction, lock table
   capacity, log space) must not depend on high activity — in practice
   partitioned or quota'd per level.

The price is borne by high transactions: they may read stale low data, wait,
or be aborted.

---

## 5. Secure concurrency control protocols

### 5.1 Kernelized architecture (single-level schedulers per level)

| Protocol | Idea | Correctness | Cost |
|---|---|---|---|
| Validation schemes (Schaefer 1974; Lamport 1977; Reed & Kanodia 1979 eventcounts/sequencers) | Let high read-down proceed; at commit, if a low transaction overwrote something the high one read, the *high* transaction aborts | Serializable, no downward signal | Starvation of high transactions under steady low update traffic |
| Multiversion TO (Keefe & Tsai, IEEE S&P 1990) | Low writes create new versions; a high transaction reads the version consistent with its timestamp, which is assigned so it is ordered *before* concurrent low writers | Serializable; high never blocks low | Unbounded versions; high reads stale data; garbage collection must not depend on high readers in a way low can observe |
| Two-snapshot (Ammann, Jaeckle, Jajodia, IEEE S&P 1992; Ammann & Jajodia, CCS 1994) | Keep at most two versions: reads at dominated levels go to a periodically advanced snapshot; writes at own level go to the current state | Serializable (with a snapshot-advance protocol); bounded storage | Staleness of read-down bounded by snapshot period |
| Conflict resolution in favor of low (George & Haritsa, real-time; Kang, Son, Stankovic STAR, RTSS 2002; multiversion locking with freezing, Park, Park, Son TKDE 2002) | In lock conflicts across levels, the lower-level transaction always wins (high is aborted or its lock is broken) | Secure; may trade deadline misses at high levels | Real-time guarantees only for low levels unless capacity is partitioned |

Implementation recipe for a multiversion engine (this maps directly onto an
MVCC engine you already have):
```
on read(T, x) where level(x) ≺ level(T):     # read-down
    take NO lock that a writer at level(x) could wait on
    v := latest version of x committed before snapshot(T, level(x))
    return v                                   # stale is acceptable; blocking is not
on read(T, x) where level(x) = level(T):     # same level: ordinary CC
    ordinary MVCC/2PL at that level
on write(T, x): require level(x) = level(T)  # restricted *-property
on commit(T): validation only against same-level conflicts;
    cross-level rw-antidependencies are resolved by ordering T before the
    low writers (its snapshot), never by aborting the low writer.
version GC: may reclaim a low version only when no snapshot that a level
    l' ⪰ level(x) could still be assigned needs it; the GC decision must not
    be observable at low as a function of high activity (fixed horizon).
```
Note the parallel with SSI: in a plain SI engine, a high reader that is a
pivot could cause a *low* writer to be the abort victim. A secure variant must
always pick the higher-level transaction as victim.

### 5.2 Correctness criteria weaker than one-copy serializability

Single-level transactions (read at many levels, write at one) cannot maintain
integrity constraints spanning levels, and full serializability forces costly
protocols. Jajodia & Atluri (IEEE S&P 1992) defined **level-wise
serializability** (each level's projection is serializable), **one-item read
serializability**, and **pairwise serializability**. Use when cross-level
constraints are absent by design.

### 5.3 Replicated architecture

Each level-l backend holds replicas of all data dominated by l; updates at
level l must be propagated as *update projections* to every dominating
backend, in an order consistent with all lower serialization orders.
- Jajodia & Kogan (1990): totally ordered levels; a global transaction
  manager forwards conflicting transactions to dominating levels in commit
  order. Kang & Keefe showed non-conflicting transactions forwarded in
  arbitrary order can yield non-serializable histories.
- Costich (1992): less trusted GTM, partial orders allowed.
- McDermott, Jajodia & Sandhu (1991) showed some posets deadlock or produce
  non-serializable executions. Example: levels A, B, C incomparable; AB, BC, AC
  above pairs; ABC on top. If `T_A <_AB T_B`, `T_B <_BC T_C`, `T_C <_AC T_A`, the
  ABC replica cannot honour all three orders (a cycle).
- Fix: order update projections by a timestamp assigned at first commit and
  apply them with a conservative TO scheduler that never aborts a projection
  (Ammann & Jajodia, distributed timestamp generation in planar lattices,
  TOCS 1993).

Lesson for any replicated engine with one-way trust flows (e.g. replicas that
may receive but never send back to a primary): if ordering metadata cannot
flow downward, ordering must be fixed at the source by timestamps.

### 5.4 Multilevel transactions and atomicity

A multilevel transaction has subtransactions at several levels, each obeying
simple security and restricted ★. Full atomicity can itself be a channel: if a
high subtransaction's failure forces the low subtransaction to abort, low sees
high's outcome. Blaustein et al. (IEEE S&P 1993) defined graded degrees of
atomicity achievable without such flows; Ray, Ammann & Jajodia (JCS 1998) use
**semantic atomicity** with compensation, verified by analysing the
application, instead of serializability.

### 5.5 Distributed commit: secure early prepare (Atluri, Bertino, Jajodia 1995)

Problem with early prepare in MLS: subtransaction `T_ij` at site j has read a
low item `x` and voted prepared; a low writer at site j needs `x`; to avoid
a covert channel, `T_ij` must release its read lock — but then another
subtransaction `T_ik` at site k may still acquire locks, violating 2PL globally.

SEP:
1. Participants vote YES and set a **read-low bit** if they read data at a
   dominated level.
2. If no read-low bits: commit as in early prepare.
3. Otherwise the coordinator sends CONFIRM to read-low participants; each
   replies CONFIRMED if it has not had to release any read-down lock, else
   NOT-CONFIRMED.
4. Commit iff all CONFIRMED; else abort.
Ray, Bertino, Jajodia & Mancini (CCS 1996) roll the subtransaction back to a
savepoint and re-execute instead of aborting.

---

## 6. Survivability: damage assessment and repair after malicious transactions

Classical recovery undoes uncommitted work; it cannot remove a committed
malicious transaction and everything that read from it.

- **Model** (Ammann, Jajodia, McCollum, Blaustein, IEEE S&P 1997): data items
  are marked (colours) by damage severity; clean data satisfy the integrity
  constraints, damaged data satisfy relaxed ones; transactions are attack,
  normal, or countermeasure (detection changes marks, repair changes values;
  both trusted).
- **Static repair** (Ammann, Jajodia, Liu, TKDE 2002): forward log scan
  builds the set of malicious and *suspect* transactions (those that read from
  a damaged item, transitively); backward scan undoes them all; affected good
  transactions can then be re-executed. Requires **read logging** — ordinary
  WAL records only writes, so read-from dependencies are invisible without it.
- **Dynamic repair** keeps accepting transactions during repair.
- **Dependency structures** kept outside the log (Lala & Panda 2001; Ray et al.
  2004 dependency graph + DFS) cut assessment latency.
- **Data-dependency** (Panda & Haque 2002) rather than transaction-dependency
  undoes only affected operations.
- **Confinement** (Liu & Jajodia 2001): immediately confine all items written
  after the bad transaction, then unconfine as assessment proves them clean;
  naive unconfining leaks damage, so unconfinement order matters.
- **Distributed**: peer-to-peer multicast of affected global transaction ids,
  or a coordinator that merges local dependency graphs (Zuo & Panda 2004).
- Lomet, Vagena & Barga (SIGMOD 2006) study recovery from "bad" user
  transactions in a conventional log-based engine.

Engine-builder takeaways: (1) if you want surgical repair, you must log reads
or at least read sets per transaction id; (2) transaction-time versioning
(`temporal-databases`) gives the pre-attack state cheaply; (3) repair
transactions need a privileged, audited path.

---

## 7. Tests for MLS / tenant isolation in engines

- **Noninterference harness**: run a low workload twice — once alone, once
  with an adversarial high workload (reads-down, lock storms, aborts). Assert
  that low observes identical results, identical abort decisions, and
  statistically indistinguishable latency distributions (bound the channel
  capacity rather than claim zero: timing channels are rarely zero).
- **Existence-oracle probes**: low inserts keys present only at high; expect
  success (polyinstantiation) or a label-scoped unique index, never a
  violation. Same for FK checks and upserts.
- **Victim selection**: construct a deadlock / SSI dangerous structure across
  levels; assert the high transaction is chosen as victim.
- **Replica ordering**: model-check update-projection propagation over the A/B/C
  lattice of §5.3 and assert no ordering cycle or deadlock.
- **Label of derived data**: property test — result label ⪰ join of labels of
  every tuple that influenced it (including predicate-only inputs).

---

Sources: Mandatory Access Control (p.2192); Multilevel Secure Database
Management System (p.2349); Secure Transaction Processing (p.3358); Access
Control (p.9); Secure Database Development (p.3346) for MLS requirements on
concurrency control; Auditing and Forensic Analysis (p.218) for recovery from
malicious transactions.
