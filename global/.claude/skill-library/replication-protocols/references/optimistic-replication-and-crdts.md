# Optimistic replication, conflict detection/resolution, and replicated data types (CRDTs)

Read this when replicas accept writes without coordination (multi-master,
geo, mobile/offline, collaborative editing) and you must detect concurrent
updates, resolve them deterministically, and prove convergence.

---

## 1. Optimistic (lazy, update-anywhere) replication

Any site may read or update its local replica at any time; the update
commits locally and is **tentative** because a concurrent remote update
may conflict. Propagation happens in the background, *after* local
commitment and off the client's critical path. Replicas may diverge
temporarily and must converge eventually.

Contrast the two uses of "optimistic":

| | Optimistic replication | Optimistic concurrency control |
|---|---|---|
| Ordering | No a-priori total order; order converged a posteriori | Serialized at the latest at validation |
| Common state | No instant when all sites are guaranteed equivalent | Single committed state |
| Aborts | Tentative effects may already be visible; cascading aborts/rollbacks possible | Validation precedes visibility; no cascading aborts |

Lineage: Johnson & Thomas LWW replicated DB (RFC 677, 1975/76); Usenet;
Wuu & Bernstein (1984) replicated log/dictionary with log-tail
anti-entropy; Lotus Notes (state-based LWW, tombstones); Coda (version
vectors, type-specific resolvers); OT for group editors (1989); Golding's
timestamped anti-entropy (1992); Bayou (1994–97); Dynamo multi-value
register (2007); CRDTs (2009–2011).

---

## 2. Transfer: state-based vs operation-based

| | State-based | Operation-based |
|---|---|---|
| Ships | The (after-)state of the object, or a delta | The operation (or the effector it generated) |
| Receiver | `merge(local, received)` | Replays the operation on its replica |
| Channel requirements | None: tolerates loss, duplication, reordering (if merge is idempotent/commutative/associative); membership may be unknown | Reliable, exactly-once (or idempotent ops), causal-order delivery |
| Cost | Large objects are expensive to ship; LWW on whole objects yields false conflicts | Cheap messages; logical ops commute more often than raw writes → fewer conflicts |
| Typical anti-entropy | Periodic pairwise exchange, Merkle trees to find differing ranges | Log-tail exchange: send peers only the suffix they have not seen (vector of per-origin sequence numbers) |

---

## 3. Classifying concurrent transactions

Each transaction alone is assumed to preserve invariants (ACID "C").
For a pair of concurrent transactions:

- **Commuting**: `T1;T2` and `T2;T1` return the same results and the same
  state. Need no synchronization. (Two deposits to one account; deposit
  to A and withdrawal from B.)
- **Non-commuting**: both orders are legal but differ (transfer balance to
  savings vs deposit €100). All sites must agree on one order — requires
  consensus, i.e., gives up availability for that pair.
- **Antagonistic**: no combination preserves an invariant (two meetings
  overlapping in my calendar). One must abort.

Conflict = non-commuting or antagonistic. If the system does not know the
invariants, it must conservatively treat any concurrent read-write or
write-write access to the same item as antagonistic (abort one).

---

## 4. Detecting concurrency: version vectors

A **version vector** `VV: replica → counter` attached to each object
version. Replica `i` increments `VV[i]` on a local update.

```
VV_a ≤ VV_b  iff  ∀i: VV_a[i] ≤ VV_b[i]
a happened-before b       iff VV_a ≤ VV_b and VV_a ≠ VV_b
a, b concurrent (conflict) iff neither ≤
merge (join)               = pointwise max
```

Pitfalls:

- **Per-client vs per-server entries**: entries per client grow without
  bound; entries per server (coordinator) lose the ability to distinguish
  two concurrent writes coordinated by the same server unless you track
  "dots". Dotted version vectors (Preguiça et al.) attach the exact event
  `(replica, counter)` of each value so siblings are tracked precisely
  with server-sized vectors.
- **Pruning**: removing entries for retired replicas must be coordinated or
  causality information is lost (false concurrency or, worse, false
  dominance).
- **Version vectors vs vector clocks**: version vectors track updates to
  one object (only update events tick); vector clocks track all events of
  processes. Using a vector clock where a version vector is needed
  over-reports concurrency.

---

## 5. Resolution strategies

### 5.1 Last-writer-wins (Thomas write rule)

Each write gets a timestamp; replicas keep the value with the largest
`(timestamp, replica_id)`; a write with a smaller timestamp than the
stored one is ignored.

Pitfalls (each one is a real production incident class):

1. **Silent lost updates**: the concurrent write with the smaller
   timestamp vanishes. LWW violates durability for that write by design.
2. **Clock skew**: a node with a fast clock wins every conflict and can
   make later (in real time) writes from correct nodes disappear; a clock
   that jumps forward can "poison" an item until real time catches up.
   Use hybrid logical clocks (`geo-replication-and-clocks.md`) or at least
   `ts = max(local_clock, max_ts_seen + 1)`.
3. **Equal timestamps**: must tie-break deterministically (replica id),
   identically on every node.
4. **Deletes**: need tombstones with timestamps, kept until every replica
   has seen them; GC'ing a tombstone too early resurrects the deleted
   value from a stale replica.
5. **Granularity**: whole-row LWW loses concurrent updates to *different*
   columns; per-column LWW (Cassandra-style cells) fixes that but can
   produce rows no single writer ever wrote (a cross-column invariant is
   violated).
6. **Read-modify-write**: `x := x + 1` under LWW loses increments; use a
   counter type.

### 5.2 Multi-value register / siblings

Keep all concurrent versions (the version-vector antichain) and return
them to the application, which writes back a merged value whose vector
dominates them all (Dynamo shopping cart: union). Correct but pushes merge
logic into every application; removing an item from a union-merged cart
reappears unless removal is modelled (OR-set).

### 5.3 Semantic resolvers and Bayou

A resolver is an application-specific deterministic merge program.
State-based resolvers typically decompose the item into independent
sub-items, apply LWW to updated/tombstoned sub-items and union to new
ones. Bayou's write = (dependency check query, update, merge procedure):
on replay, if the dependency check fails, the merge procedure (arbitrary
but deterministic code) gets a chance to adjust; in practice general
merge procedures are very hard to write correctly, and application-level
invariant enforcement is empirically error-prone (Bailis et al.,
"feral concurrency control", SIGMOD 2015).

### 5.4 Ordering a posteriori

- **Bayou**: each site executes writes tentatively in arrival order; a
  designated primary assigns the final commit order (its execution
  order); other sites roll back tentative state (undo log) and re-execute
  committed writes in commit order, then re-apply tentative ones.
  Clients may observe effects change when reordering happens.
- **IceCube**: applications annotate operation pairs (commute, conflict,
  antagonistic, dependent, semantic order); a scheduler optimizes a batch
  to minimize aborted operations and proposes alternative schedules.
- **Bounded divergence** (TACT): limit order error (number of uncommitted
  tentative ops), numerical error (quotas), staleness — see
  `consistency-models-and-session-guarantees.md`.

### 5.5 Reconciliation cost limits multi-master scale

Detecting and reconciling out-of-order updates (undo with inverse
operations, re-apply in agreed order) is the cost that Gray et al. showed
grows ~N^3 with full-replication update-anywhere. Reducing it requires
operations that commute — which is exactly what CRDTs package.

---

## 6. Operational transformation (OT)

Concurrent operations are rewritten (their arguments transformed) so that
executing them in different orders at different sites yields the same
state. Example on text `"abc"`: user 1 does `insert('X', 2)` → `"aXbc"`;
user 2 does `delete(3)` → `"ab"`. At user 1, the remote `delete(3)` must
be transformed to `delete(4)` (positions after the insert shift right)
to give `"aXb"`; at user 2, the insert applies unchanged.

Correctness conditions on the transformation function `T(a, b)` (a
transformed against concurrent b):

- **TP1**: `a ; T(b, a) ≡ b ; T(a, b)` — the two paths from a common state
  converge. Sufficient when a central server serializes replay (Jupiter /
  Google-Docs-style).
- **TP2**: transforming a third operation along either path gives the same
  result — `T(T(c, a), T(b, a)) = T(T(c, b), T(a, b))`. Required for
  peer-to-peer replay in arbitrary order. Most published decentralized OT
  algorithms were shown to violate TP2.

Practical reading: OT is viable with a central sequencer; for
decentralized editing, sequence CRDTs are the safer foundation.

---

## 7. Conflict-free replicated data types

### 7.1 Definition and guarantee

A CRDT is an abstract data type (register, counter, set, map, graph,
sequence) whose replicated implementation guarantees that replicas which
have received the same set of updates are in equivalent states — **strong
eventual consistency (SEC)** — with no synchronization on updates.
Sequentially it behaves like its sequential counterpart; when two updates
commute sequentially, executing them concurrently has the same effect. The
design content of a CRDT is the **concurrent semantics** for updates that
do *not* commute sequentially (add vs remove of the same element:
add-wins, remove-wins, or timestamp-wins).

### 7.2 State-based (CvRDT) conditions

- The state space is a **join-semilattice** under a partial order `≤`.
- Every mutator is an **inflation**: `s ≤ m(s)`.
- `merge(s, t) = s ⊔ t` (least upper bound): associative, commutative,
  idempotent.
- Then, if every update eventually reaches every replica through any
  connected gossip graph, all replicas converge; duplication and
  reordering are harmless.

**δ-CRDTs** (Almeida, Shoker, Baquero 2015): mutators return a small
delta-state that is itself a lattice element; ship and join deltas instead
of full state, falling back to full state when delta history is
unavailable.

### 7.3 Operation-based (CmRDT) conditions

- A mutator is split into a **generator** (prepare/upstream: runs at the
  origin, reads local state, has no side effect) and an **effector**
  (downstream/shadow operation: a state transformation applied at every
  replica including the origin).
- Concurrent effectors must **commute**. Associativity is not required
  (but enables batching).
- Delivery must be **causal** and **exactly once** (or effectors must be
  idempotent). Pure op-based CRDTs push all ordering concerns into a
  causal broadcast layer.

### 7.4 Catalogue (what an engine builder actually implements)

| Type | State / mechanism | Concurrent semantics | Cost |
|---|---|---|---|
| G-Counter | vector `P[i]` of per-replica increments; value `Σ P`; merge pointwise max | increments commute | O(#replicas) |
| PN-Counter | two G-Counters (incs, decs) | value = P − N | 2x |
| LWW-Register | `(value, ts)`; merge keeps max ts | highest timestamp wins (inherits §5.1 pitfalls) | O(1) |
| MV-Register | set of `(value, VV)` antichain | keeps all concurrent values | grows with concurrency |
| G-Set / 2P-Set | add-only set / add-set + remove-set (no re-add) | 2P: remove wins forever | tombstones forever |
| OR-Set (observed-remove) | elements tagged with unique ids; remove deletes only *observed* tags | add wins over concurrent remove | see below |
| LWW-element-set | per-element add/remove timestamps | timestamp wins | clock dependence |
| Maps | key → embedded CRDT; recursive merge; key removal semantics must be chosen (reset-wins / update-wins) | composite | |
| Sequences (RGA, Treedoc, Logoot, LSEQ, WOOT) | unique, densely ordered position identifiers; deletes as tombstones (or GC'd) | concurrent inserts at same position ordered deterministically by ids | identifier growth, tombstones |

### 7.5 OR-Set in detail

State-based with tombstones (sets of `(element, unique_tag)` pairs):

```
state: E (live pairs), T (tombstoned pairs)
contains(e):  ∃ n: (e, n) ∈ E
add(e):       E := E ∪ {(e, fresh_tag())}
remove(e):    R := {(e, n) ∈ E};  E := E \ R;  T := T ∪ R
merge(B):     E := (E \ B.T) ∪ (B.E \ T);  T := T ∪ B.T
```

Add-wins: a concurrent `add(e)` creates a tag the remover never observed,
so it survives. Space grows with every add/remove because tombstones are
never dropped; optimized OR-Set (Bieniusa et al. 2012) bounds space by the
number of live elements using per-replica version vectors to summarize
removed tags.

Operation-based without tombstones (assumes causal delivery):

```
state: E
add(e):    generator: n := fresh_tag();  effector: E := E ∪ {(e, n)}
remove(e): generator: R := {(e, n) ∈ E}  effector: E := E \ R
```

Causal delivery guarantees that an effector removing `(e, n)` arrives
after the effector that added `(e, n)`, so no tombstone is needed.

### 7.6 What CRDTs do not give you

- **Invariants**: a PN-Counter used as an account balance can go negative
  under concurrent decrements; uniqueness cannot be guaranteed by any
  coordination-free type. Need coordination for those operations, or
  escrow/bounded counters (pre-partition the slack: each replica may spend
  only its allocated rights, transferring rights by messages — O'Neil's
  escrow method, Barbará & Garcia-Molina's demarcation protocol, Balegas et
  al.'s Indigo/bounded counter).
- **Cross-object ordering**: each CRDT converges individually; application
  correctness often needs causal consistency across objects (Antidote's
  transactional causal consistency).
- **Bounded metadata**: tags, tombstones, vectors must be garbage collected
  with knowledge that every replica has seen an event — which is a
  (cheap, background) coordination step.

> **Beyond EDBS:** Production CRDT use: Riak data types (flags, registers,
> counters, sets, maps), Redis Enterprise active-active (CRDT-based
> geo-replication), Automerge and Yjs (sequence/JSON CRDTs for local-first
> collaborative apps), AntidoteDB (research geo-DB with TCC). Postgres-
> family "multi-master" extensions generally use LWW or custom conflict
> handlers rather than CRDTs.

---

## 8. Implementation checklist (C/C++/Rust)

- Represent `VV` as a small sorted vector of `(replica_id: u32, counter:
  u64)`; compare with a merge-walk; keep replica ids stable (never reuse a
  retired id).
- Encode merge laws as property tests: for random states `a, b, c`:
  `merge(a, merge(b, c)) == merge(merge(a, b), c)`,
  `merge(a, b) == merge(b, a)`, `merge(a, a) == a`, and every mutator is
  inflationary (`a ≤ m(a)`). For op-based types: random interleavings of
  concurrent effectors consistent with causality produce equal states.
- Make `fresh_tag()` globally unique without coordination: `(replica_id,
  local_counter)` — never random numbers without collision analysis,
  never wall-clock time alone.
- Tombstone GC only after a stability check (all replicas' vectors
  dominate the tombstone's dot); persist the stability frontier.
- LWW timestamps: `(hlc, replica_id)` lexicographic; reject or clamp
  remote timestamps too far in the future.
- Keep the conflict-resolution function a pure function of the conflicting
  versions (no local time, no local configuration), versioned so a rolling
  upgrade cannot have two replicas resolving differently.

---

Sources: EDBS — Optimistic Replication and Resolution (p.2612), Replicated
Data Types (p.3171), Eventual Consistency (p.1403), Multi-data Center
Replication Protocols (p.2314), Multi-datacenter Consistency Properties
(p.2320), Weak Consistency Models for Replicated Data (p.4595); Saito &
Shapiro CSUR 2005; Shapiro, Preguiça, Baquero, Zawirski SSS 2011 and INRIA
RR-7506; Terry et al. SOSP 1995; Preguiça et al. ICDCS 2009; Roh et al.
JPDC 2011; Bieniusa et al. 2012; Almeida et al. 2015; Baquero et al. DAIS
2014; Sun & Ellis CSCW 1998; Oster et al. 2005; DeCandia et al. SOSP 2007;
O'Neil TODS 1986; Barbará & Garcia-Molina VLDBJ 1994.
