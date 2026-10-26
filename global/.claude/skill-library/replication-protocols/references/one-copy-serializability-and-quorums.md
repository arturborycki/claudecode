# One-copy serializability, ROWA/ROWAA/available copies, and quorum systems

Read this when you must prove (or break) that a replicated execution is
equivalent to a single-copy one, when designing behaviour under site
failures and partitions, or when sizing quorums (majority, weighted, grid,
tree) for load and availability.

---

## 1. Replicated histories

- Database of logical items `x, y, ...`; sites `A, B, ...`; copies `x^A`.
- A transaction `T_i` issues `r_i(x)`, `w_i(x)`, then `c_i` or `a_i`.
- Replica control translates each logical op into physical ops on copies.
- **Local history** `RH^A`: total order of physical ops executed at `A`.
- **Replicated history** `RH`: union of local histories plus program order
  across sites (if `T_i` does `o_i(x)` before `o_i(y)` and these map to
  `o_i(x^A)` and `o_i(y^B)`, then `o_i(x^A) <_RH o_i(y^B)`).
- Physical ops **conflict** iff different transactions, same copy, at
  least one write.

Worked example (ROWA, sites A and B both hold `x` and `y`; T1 reads its
copy at A, T2 reads its copy at B):

```
T1 = r1(x) w1(x)          T2 = r2(x) w2(y)
RH^A: r1(x^A) w1(x^A) w2(y^A) c1 c2
RH^B: w1(x^B) r2(x^B) w2(y^B) c1 c2
```

The only cross-transaction conflict is `w1(x^B)` before `r2(x^B)` at B, so
every site orders T1 before T2 and the history matches the one-copy serial
execution T1 T2 (T2 reads the x that T1 wrote).

---

## 2. 1SR: definitions and testable criteria

**Definition (1SR).** Call a replicated history (committed transactions
only) 1SR when some serial history of those same transactions, run against
one unreplicated logical copy, is equivalent to it.

The subtlety is the word "equivalent", because the two histories are over
different objects (copies vs logical items).

### 2.1 ROWA, no failures: conflict equivalence suffices

When every write goes to *all* copies and every read to *one* copy:

- Build `SG(RH^A)` per site (edge `T_i -> T_j` if conflicting ops on a copy
  at `A` are ordered `i` before `j`), and `SG(RH)` = union over sites.
- **Theorem.** Under ROWA, `RH` is 1SR iff `SG(RH)` is acyclic.

Why it works: because every write touches every copy, any two writers of
`x` conflict on every copy, and any reader of `x` conflicts with every
writer of `x` on the copy it read. So all logical conflicts surface as
physical conflicts somewhere.

### 2.2 Failures or quorums: conflict equivalence is NOT enough

Once writes may skip copies (ROWAA, quorums), two transactions may
logically conflict without ever touching a common copy. Classic example
(`x` at A,B; `y` at C,D):

```
T1 = r1(x) w1(y)          T2 = r2(y) w2(x)
r1(x^A)  r2(y^D)          -- each reads a different copy
   A fails, D fails
w1(y^C)                   -- T1 writes only the available copy of y
w2(x^B)                   -- T2 writes only the available copy of x
c1 c2
```

No physical conflict anywhere (T1 touched x^A, y^C; T2 touched y^D, x^B),
so the physical SG is empty — yet logically T1 read x before T2 wrote it
(T1 -> T2) and T2 read y before T1 wrote it (T2 -> T1). Not 1SR.

The fix in the theory (Bernstein, Hadzilacos, Goodman 1987) is
**1-view equivalence** to a **1-serial** history: same reads-from relation
over logical items and same final writes. Testable form:

**1-copy serialization graph (1-SG):** take the replicated SG and add
- *write-order edges*: for each logical `x`, a total order `<<_x` on the
  transactions that write `x` (any copy), with an edge for each consecutive
  pair; and
- *read-order edges*: if `T_j` reads `x` from `T_i` and `T_k` writes `x`
  with `T_i <<_x T_k`, add `T_j -> T_k`.

**Theorem.** If some choice of write orders makes the 1-SG acyclic, the
history is 1SR. Protocols are proven correct by exhibiting how they
induce such write orders (e.g., via version numbers, total-order
broadcast sequence numbers, or timestamps).

Engineering corollary: **any protocol whose writes can miss copies must
carry a version/timestamp/epoch on each copy and must ensure reads choose
the latest version among a set guaranteed to intersect every write** —
that is exactly what quorums do and what naive ROWAA fails to do.

### 2.3 The real-time / session gap in 1SR

1SR (like serializability) only demands that *some* serial order exists.
A lazy primary-copy system can be 1SR while a client sees its own committed
transfer "undone" by its next read-only transaction served from a stale
secondary (serialized *before* the transfer). Stronger variants:

| Variant | Extra constraint on the equivalent serial order |
|---|---|
| Strict 1SR / external consistency | If `T_i` commits before `T_j` begins (real time), `T_i` precedes `T_j`. |
| Strong session 1SR / session consistency | Same constraint, but only for transactions of the same client session. |

These matter for lazy replication and for read-only routing to
secondaries; they are free in a single-site 2PL engine, which is why users
assume them.

---

## 3. Mapping strategies under failures

| Strategy | Reads | Writes | Tolerates | Problem |
|---|---|---|---|---|
| ROWA | any one copy | all copies | nothing for writes | one dead copy blocks all writes to the item → write availability *lower* than unreplicated |
| ROWAA (naive) | any available copy | all available copies | site crashes | not 1SR under failures (example above); under partitions, both sides keep writing → divergence |
| Available copies (BHG) | any available copy | all available copies, plus validation | site crashes with accurate failure detection | still unsafe under network partitions |
| Primary copy | primary (or stale secondaries) | primary, propagated | backup failures; primary failure needs election | election must be quorum-based under partitions |
| Quorum consensus | read quorum | write quorum | site failures and partitions (minority side blocks) | read cost; collection queries |
| Consensus log (Paxos/Raft) | leader (or quorum/lease) | majority accept | minority failures, partitions | leader bottleneck; ≥1 RTT per commit |

### 3.1 The available-copies algorithm (why naive ROWAA needs validation)

To restore 1SR under (non-partition) site failures:

1. **Missing-writes validation**: when `T` writes `x` and some copies of
   `x` are unavailable, at commit `T` must confirm those copies are *still*
   unavailable (they have not recovered and possibly been read by someone
   without `T`'s write).
2. **Access validation**: every copy `T` read or wrote must still be
   available at commit.
3. **Recovering copies are unreadable until refreshed**: a copy coming back
   must be marked "write-only" and brought up to date (copier transactions
   or log replay) before it serves reads.

In the example, T1 at commit discovers A (which it read) has failed → abort.

Directory-oriented variants maintain a replicated directory of which
copies are available and include directory reads in the transaction, so
"available" itself is serialized.

None of this survives a partition: "unavailable" and "on the other side of
a partition" are indistinguishable. For partitions you need intersecting
quorums (or a primary chosen by a quorum).

---

## 4. Quorum consensus

### 4.1 Definitions

- **Quorum system** over sites `N`: a collection `S` of subsets such that
  every two members intersect (`∀ S_i, S_j ∈ S: S_i ∩ S_j ≠ ∅`).
- **Read/write quorum system** `(R, W)`: `W` is a quorum system (writes
  pairwise intersect) and every read quorum intersects every write quorum.
- Two styles of use:
  1. *Exclusive-access quorums*: a write asks only the members of one
     quorum for permission, executes there, and tags the copies with a new
     version greater than any version seen in the quorum.
  2. *Send-to-all, wait-for-quorum*: the write is sent to every replica but
     completes once a quorum confirms (the Paxos/Raft/Dynamo style). Write
     work is not reduced versus ROWA, but latency and availability are.

### 4.2 Version-number protocol (Gifford weighted voting / Thomas majority)

```
votes v_i per site, V = Σ v_i;  read threshold r, write threshold w
constraints: r + w > V   (read-write intersection)
             2w > V      (write-write intersection)

read(x):  collect copies from sites with ≥ r votes;
          return value with the max version
write(x): collect versions from a quorum (≥ w votes, or a read quorum);
          vnew = max + 1; install (value, vnew) at sites with ≥ w votes
```

Invariants to assert in tests:
- Q1: every read quorum contains at least one copy with the latest
  committed version.
- Q2: no two concurrent writes can both obtain a write quorum (requires
  locking or ballots at the intersecting site; versions alone do not
  serialize *concurrent* writers — two writers can both compute `max+1`).
- Q3: version numbers per item are strictly increasing in commit order.

Q2 is the frequently missed one: in exclusive-access designs the
intersecting site grants permission to only one writer at a time; in
send-to-all designs a consensus ballot or a single leader per item does
the serialization. A "quorum write" that just stamps `max+1` without
either is a lost-update generator.

### 4.3 Quorum families

| Family | Construction | Quorum size | Fair (equal participation)? | Notes |
|---|---|---|---|---|
| Majority | any `⌊n/2⌋+1` | `wq = ⌊n/2⌋+1`, `rq = ⌈n/2⌉` | yes | ROWA is the degenerate `rq=1, wq=n` |
| Weighted majority | sites get votes; quorum = more than half of total votes (reads: at least half) | depends on votes | tunable | lets strong/reliable sites count more |
| Rectangular grid `r x c` | read = one element per column (`c`); write = one full column + one element per other column (`r+c-1`) | square: `rq = √n`, `wq = 2√n-1` | yes | |
| Hierarchical grid | recursive grids; quorum = full row + recursive row cover | same orders as square grid | yes | more resilient than flat grid |
| Triangular grid | row i has i elements; write = full row + one from each lower row | `d` (number of rows) | no | top rows are hot |
| Tree `⟨l, b⟩` over height `h`, degree `d` | root + `b` children recursively to depth `l`; a failed node is replaced by `b` subtrees under it | varies | no (root hot) | intersection needs `l_r + l_w > h` and `b_r + b_w > d`; write-write needs `2l_w > h`, `2b_w > d` |
| ReadRoot tree | write = majority at every level; read = root (or a majority of the next level if root down) | read 1 in failure-free case | no | writes blocked when root down |
| MajorityTree | majority in both height and degree for reads and writes | larger reads | no | writes possible without the root |
| Byzantine quorums | every intersection has ≥ `f+1` nodes (dissemination: at least one correct) or ≥ `2f+1` nodes (masking: correct members outvote faulty ones) | larger | — | Malkhi, Reiter, Wool |

Maekawa's `√n` construction (finite projective planes) started the line of
small-quorum systems for mutual exclusion.

### 4.4 Load, capacity, availability

- **Load** of a quorum system = the access probability of the busiest node
  under the best access strategy. Naor and Wool's lower bound: for smallest
  quorum size `c`, `load ≥ max(1/c, c/n)`, hence `load ≥ 1/√n`. Majority
  has load ≈ 1/2 (every op touches half the nodes) — it does *not* scale
  throughput; grids achieve `O(1/√n)`.
- **Availability** (probability some quorum is fully alive), independent
  failures, per-node up-probability `p`:
  - homogeneous, `p > 1/2`: majority is the most available;
  - homogeneous, `p < 1/2`: a monarchy (single designated node) is the most
    available;
  - heterogeneous: weighted majority with appropriately computed weights is
    optimal.
- Small quorums (grid/tree) trade availability for load: a grid with one
  entirely failed column has no write quorum.

### 4.5 Quorums in practice

- Paxos/Raft-based systems use send-to-all-wait-for-majority for writes
  and either read at the leader (with a lease or a read-index round) or a
  majority read for linearizable reads; reads at an arbitrary replica are
  stale-possible.
- Dynamo-style stores expose per-request `R`/`W` (ONE, QUORUM, ALL...).
  `R + W > N` gives intersection *only for a fixed replica set*; "sloppy
  quorums" with hinted handoff write to substitute nodes and break the
  intersection guarantee. Even strict `R + W > N` without a serialization
  mechanism for concurrent writers (Q2) is not linearizable: concurrent
  writes resolved by timestamps can lose updates, and a read concurrent
  with a partially applied write can return the new value to one reader
  and the old value to a later one unless reads write back (read repair
  completing before return, as in the ABD register protocol).
- Reconfiguration (changing the replica set) must itself be agreed: the
  old and new configurations' quorums must intersect during the
  transition (joint consensus in Raft, or an epoch change committed by the
  old configuration).

---

## 5. Replicated concurrency control

### 5.1 Strict 2PL

- **Centralized** (one lock manager, e.g., in middleware): locks per
  logical item; textbook S2PL; single point of failure and an extra hop.
  Middleware sees only SQL text → table-level or conflict-class locks.
- **Distributed** (lock per copy, ROWA): a read locks one copy, a write
  locks all copies. Global deadlocks arise that no site sees locally, even
  on a *single* logical item: T1 locks `x^A` then asks for `x^B`; T2 locked
  `x^B` first and waits for `x^A`. Detection needs timeouts or a global
  wait-for graph.
- Lock duration now includes message delays → contention grows with N,
  matching the Gray et al. model.

### 5.2 Locking over total-order broadcast

If lock requests are delivered to all sites in the same total order, all
sites grant conflicting locks in the same order and the cross-site
deadlock above disappears (deadlocks between multi-operation transactions
remain possible unless whole transactions — e.g., stored procedures — are
broadcast as one request and executed deterministically).

### 5.3 Optimistic, certification-based

Execute locally; at commit, multicast (in total order) the readset and
writeset; every site validates in delivery order with the same
deterministic rule (Kung–Robinson backward validation against transactions
that committed after `T` started). One message per transaction; problem:
SQL readsets (predicates!) are large and hard to capture — the reason SI,
which needs only writesets, dominates. Details in
`si-and-group-communication-replication.md`.

### 5.4 Indirect dependencies — why update order must be global

Even non-conflicting update transactions must be applied in one global
order if read-only transactions are allowed at different sites:

```
T1: w(x)   T2: w(y)      (no conflict)
site A applies T1 then T2; site B applies T2 then T1
T3 at A reads x,y between T1 and T2   -> sees T1 not T2
T4 at B reads x,y between T2 and T1   -> sees T2 not T1
```

No single serial (or SI) order explains both T3 and T4. Total-order
protocols avoid this by applying all updates in the same order everywhere;
PSI (Walter) deliberately permits it ("long fork") to avoid global
ordering.

---

## 6. Checklist for a 1SR/quorum implementation review

- Every copy carries `(value, version)` and every version is assigned by a
  mechanism that totally orders writers of that item.
- Writers are serialized at quorum intersections (lock, ballot, leader) —
  not just by computing `max+1`.
- Reads that must be current touch a read quorum or a leader holding a
  valid lease; lease safety assumes bounded clock drift — document it.
- Recovering copies are write-only until refreshed; refresh completion is
  a logged, serialized event.
- Replica-set membership changes are committed through the same agreement
  mechanism, with overlapping old/new quorums.
- Available-copies style designs explicitly state "no partitions" as an
  assumption, with the failure detector's accuracy documented.
- Real-time/session constraints (strict 1SR, RYW) are stated, not assumed.

---

Sources: EDBS — One-Copy-Serializability (p.2555), Quorum Systems
(p.3064), Concurrency Control for Replicated Databases (p.566), Replicated
Database Concurrency Control (p.3175), Replica Control (p.3161),
Replication for Availability and Fault Tolerance (p.3187), Strong
Consistency Models for Replicated Data (p.3809); Bernstein, Hadzilacos,
Goodman 1987 (book); Bernstein & Goodman, TODS 1984 and JCSS 1985; Gifford,
SOSP 1979; Thomas, TODS 1979; Naor & Wool, SIAM J Comput 1998; Peleg &
Wool 1995; Agrawal & El Abbadi, TODS 1992; Cheung, Ahamad, Ammar, ICDE
1990; Kumar, IEEE TC 1991; Malkhi, Reiter, Wool 2000; Attiya, Bar-Noy,
Dolev, JACM 1995 (ABD); Carey & Livny, TODS 1991 (conflict-detection
trade-offs for replicated data); Wiesmann & Schiper, TKDE 2005
(total-order-broadcast replication techniques compared).
