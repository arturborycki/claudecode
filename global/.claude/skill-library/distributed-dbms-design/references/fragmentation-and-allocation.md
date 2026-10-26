# Fragmentation, allocation, architecture and transparency

The design half of a classical distributed DBMS: what the system promises to
hide (transparency), how the nodes relate (architecture and autonomy), how a
global relation is cut into fragments that can be put back together exactly
(fragmentation with correctness rules), and where each fragment lives
(allocation). Everything downstream — localization, semijoin reduction,
commit fan-out, deadlock scope — is a function of these choices.

---

## 1. Transparency: who is allowed to see distribution

Transparency is a contract about which *role* is shielded from distribution.
Keep the levels separate; engines routinely provide some and silently break
others.

| Level | Hidden from | Concretely means | Breaks when |
|---|---|---|---|
| Fragmentation (distribution) | application | SQL names the global relation; the engine substitutes fragment expressions | users must name `EMP_EU` to get a fast plan |
| Replication | application | one logical copy; the replica-control protocol picks copies and keeps them mutually consistent | stale reads observable without asking for them |
| Location | application | no site names in queries; follows from the two above | `table@site` syntax required |
| Naming | application | one global name per relation regardless of how many internal relations implement it | per-source names leak (mediators, multidatabases) |
| Query | application | a distributed optimizer turns one query into site subqueries plus transfers | hand-written cross-site plans |
| Update / transaction | application | a distributed transaction manager propagates writes and runs an atomic-commit protocol | partial commits visible after failures |
| Schema | DBA | the system decides placement itself; DBA writes a logical schema only | DBA must declare fragments and sites |

Rule of thumb from the entries: a *parallel* DBMS (cluster, fast interconnect)
gives all levels including schema transparency; a *regular* distributed DBMS
gives query/update/naming transparency but makes the DBA design fragments and
placement (because WAN latency makes placement a business decision — e.g.
keep EU employee rows in the EU); heterogeneous systems progressively give up
transparency in exchange for autonomy.

Gray's 1989 Tandem note ("transparency in its place") is the standing
counter-argument: hiding remote access entirely encourages chatty, per-row
remote calls and fragile modules. Engineering consequence: expose
*observability* of distribution (EXPLAIN shows sites, bytes shipped, message
counts) even when the language hides it.

## 2. Architectures along three axes

The Özsu–Valduriez classification uses three orthogonal axes:

- **Autonomy**: tight integration (one DBMS image, no local autonomy) →
  semi-autonomous (federated: local systems run their own workloads, export
  part of their data) → full isolation (multidatabase: components are unaware
  of each other).
- **Distribution**: none / client–server / peer-to-peer (every node runs full
  DBMS functionality).
- **Heterogeneity**: data model, query language, transaction manager,
  concurrency control, commit protocol may differ.

How the named architectures differ (restated as "who owns the global
schema"):

| Architecture | Global schema | Design direction | Node autonomy | Typical gaps |
|---|---|---|---|---|
| Parallel DBMS (shared-nothing cluster) | yes, single | top-down | none | — |
| Regular distributed DBMS | yes, single | top-down, DBA fragments and allocates | none | schema transparency |
| Federated DBMS | one integration schema mapped onto component schemas | bottom-up | yes | update transparency limited (view updatability), global CC/commit hard |
| Mediator–wrapper | many mediated views over wrapped sources | bottom-up | yes | naming transparency; limited source capabilities (bind joins) |
| Multidatabase | none; multidatabase query language names sources | none | full | query/update transparency |
| P2P / PDMS | none; pairwise mappings | emergent | full | correctness of answers (hop limits), consistency |

Client–server variants matter for execution: **data shipping** (server ships
pages/objects, client executes — object DBMS style), **query shipping**
(client ships SQL, server executes), **hybrid shipping** (optimizer decides per
operator; Franklin, Jonsson, Kossmann SIGMOD 1996).

Component model of a homogeneous DDBMS site (useful as a module map):
local DBMS (storage, local CC, local recovery) + data communication layer +
**global data dictionary** (fragment definitions, allocation map, replica
sets, statistics per fragment) + distributed DB component (global query
decomposition, localization, global optimization, global CC, commit
coordination, deadlock detection, recovery coordination).

### Catalog / directory management

The global directory maps logical relation → fragments → sites/replicas, plus
per-fragment statistics. Design facts:

- It is read on every query compile and changes rarely: replicate it
  (at least at every coordinator site) and version it.
- Compiled plans embed fragment/site bindings; invalidate plans by catalog
  version, not by time. A plan compiled against an old allocation that still
  executes after a move must fail loudly (stale-routing error + recompile),
  never read a now-empty fragment and return a silently short answer.
- In autonomous settings (mediators, multidatabases, P2P) the catalog cannot be
  fully replicated; nodes *cache* remote metadata. Cached entries need a
  validation token (schema version / epoch) checked at execution.
- R* used system-wide names that embed the object's birth site, so name
  resolution never needs a global lookup; the birth site keeps forwarding
  information after migration.

## 3. Fragmentation: definitions and correctness rules

A fragmentation of R is a set F = {R1..Rn} plus a **reconstruction
operator**. Three correctness rules must hold for every scheme — they are the
invariants your DDL validator checks:

1. **Completeness** — every data item of R (tuple for horizontal, attribute
   for vertical) appears in at least one fragment. Loss here is silent data
   loss.
2. **Reconstruction** — there is a relational operator ∇ with R = ∇(R1..Rn):
   union for horizontal, natural join on the key for vertical, a nested
   expression for hybrid. This is what localization substitutes into queries.
3. **Disjointness** — a tuple is in at most one horizontal fragment; a
   non-key attribute is in at most one vertical fragment. Disjointness is
   kept at the *fragmentation* stage so that replication is an explicit,
   separate *allocation* decision (otherwise update propagation and
   duplicate-elimination costs hide inside the fragment definitions).

### 3.1 Primary horizontal fragmentation (PHF)

Ri = σ_{pi}(R). Inputs: **simple predicates** `attr θ const`, θ ∈ {=, <, ≤,
>, ≥, ≠}, gathered from the workload's selection predicates.

**Minterm predicates.** For simple predicates P = {p1..pm}, a minterm is
∧ pk* where each pk* is pk or ¬pk. There are 2^m syntactic minterms; most are
contradictory and are pruned with implications between predicates on the same
attribute.

Implementation insight: do not enumerate 2^m conjunctions. Predicates on one
attribute cut that attribute's domain into intervals (or value sets); the
non-contradictory minterms are exactly the cartesian product of per-attribute
cells. Example: predicates {amount ≥ 1000, region = 'EU', region = 'US'} with
region ∈ {EU, US, APAC} give 2 amount cells × 3 region cells = 6 minterms
(the ¬EU ∧ ¬US cell is APAC). Cost becomes Π(cells per attribute), and
contradiction pruning becomes interval arithmetic.

Minterm fragments are disjoint and complete by construction, and union
reconstructs R — so PHF built from minterms satisfies all three rules
automatically. The design question is which simple predicates to keep:

- **Completeness of a predicate set** (in the workload sense, distinct from
  fragmentation completeness): P is complete if any two tuples in the same
  minterm fragment are accessed with the same probability by every
  application. An incomplete set leaves fragments that some application
  accesses only partially.
- **Minimality**: every predicate is *relevant* — it splits some fragment f
  into f1, f2 that are accessed differently, i.e. acc(m1)/|f1| ≠ acc(m2)/|f2|.
  Irrelevant predicates multiply fragments for no access-locality benefit.
- **COM_MIN** (Özsu–Valduriez): start from a predicate that splits R relevantly;
  add predicates that are relevant with respect to the current set; drop any
  predicate made irrelevant by later additions; stop when complete.
- **PHORIZONTAL**: run COM_MIN, form minterms, prune contradictions with
  implication rules, emit σ_m(R) for surviving m.

Empty fragments: keep the definition (it is part of the reconstruction
predicate set and of localization reasoning) even if the instance is empty.

### 3.2 Derived horizontal fragmentation (DHF)

A **member** relation S is fragmented according to an **owner** R's
fragments via an equi-join link: Si = S ⋉_{S.k = R.k} Ri.

- Correctness: completeness requires **referential integrity** (every S.k
  value appears in R, otherwise S tuples with dangling keys fall into no
  fragment). Disjointness requires the join attribute to be a **key of the
  owner** (so each member tuple matches exactly one owner tuple and therefore
  one owner fragment).
- Payoff: Ri ⋈ Si is local; the cross terms Ri ⋈ Sj (i ≠ j) are empty by
  construction, so localization prunes them without inspecting predicates. In
  join-graph terms the fragment join graph is *partitioned* (simple): each Si
  joins exactly one Ri.
- Link graph: owners → members along PK→FK edges. When a member has two
  candidate owners (e.g. ORDER_LINE references both ORDER and PRODUCT), pick
  the one that makes the frequent join local, or the one whose fragmentation
  is more used by applications. You cannot co-partition along both unless the
  two owners are themselves co-fragmented.
- Engine view: DHF is co-location. Enforce it with a hidden routing column
  (the owner's partition key carried in the member) or with key-prefix
  interleaving; validate on insert (an S row whose owner is missing violates
  completeness — reject or route to a quarantine fragment, never drop).

### 3.3 Vertical fragmentation (VF)

Ri = π_{K ∪ Ti}(R). Correctness: ∪Ti = attrs(R) (completeness); the key K is
replicated in every fragment so ⋈_K reconstructs losslessly; non-key
attribute sets are pairwise disjoint (disjointness modulo K). Alternative to
replicating K: replicate a system tuple id (TID) — cheaper but couples the
fragments to physical identity.

The search space is the number of set partitions of n attributes (the Bell
number B(n); B(10)=115,975, B(15)≈1.4e9), so heuristics are mandatory.

**Affinity measures.**
- use(q, A) ∈ {0,1}: does query q reference attribute A.
- acc_l(q): frequency of q at site l; ref_l(q): accesses per execution.
- Attribute affinity: aff(Ai, Aj) = Σ over queries q using both Ai and Aj of
  Σ_l ref_l(q)·acc_l(q).

**Bond energy algorithm (BEA)** (McCormick, Schweitzer, White 1972; applied
to VF by Hoffer/Severance and Navathe et al. TODS 1984). Goal: permute the
affinity matrix AA into a clustered matrix CA maximizing the global affinity
measure
  AM = Σ_i Σ_j aff(Ai,Aj)·[aff(Ai,Aj−1) + aff(Ai,Aj+1)]
(boundary terms zero). Greedy placement:

```
bond(Ax, Ay) = Σ_z aff(Az, Ax) * aff(Az, Ay)
cont(Ai, Ak, Aj) = 2*bond(Ai,Ak) + 2*bond(Ak,Aj) - 2*bond(Ai,Aj)   # Ak inserted between Ai and Aj
place columns A1, A2
for k in 3..n:
    try every gap (i, j) including both ends (bond with a phantom column = 0)
    insert Ak at the gap with max cont
reorder rows to match column order
```
Precompute the n×n bond matrix (O(n³) naively, or O(n²·q) from usage); the
placement loop is then O(n²). The result is order-sensitive in ties; make it
deterministic (stable tie-break by attribute id) so DDL advice is
reproducible.

**Splitting the clustered matrix.** For a split point x along the diagonal,
attributes TA = {A1..Ax}, BA = {Ax+1..An}; queries partition into TQ (touch
only TA), BQ (only BA), OQ (both). With CTQ, CBQ, COQ the summed access
frequencies of each class:
  z = CTQ · CBQ − COQ²
Choose x maximizing z (rewards balanced, locally-satisfied query classes,
penalizes queries that must join both halves). Because a cohesive block may
sit in the middle of CA, also evaluate cyclic **shifts** of the order (n
shifts × n split points = O(n²) evaluations). For m-way splits either recurse
on each half or search m split points (exponential in m).

Alternatives: *grouping* (start with one attribute per fragment and merge
by affinity) vs *splitting* (start from R and split, as above); splitting
tends to yield non-overlapping fragments directly and fits BEA.

Engine reality: column stores take VF to its limit (one fragment per column,
positional reconstruction instead of key joins). In a distributed setting,
VF is rarely used for placement across WAN sites because nearly every
non-trivial query pays the reconstruction join remotely; it survives as
column-group placement inside a node and as hot/cold column splitting.

### 3.4 Hybrid fragmentation

Nest the operators: e.g. horizontally fragment EMP by region, then vertically
split the EU fragment into {id, name, dept} and {id, salary}. Represent it as
a **fragmentation tree**: leaves are stored fragments, inner nodes are
reconstruction operators (∪ for horizontal, ⋈_K for vertical). Correctness is
checked per inner node with that node's rule. Localization substitutes the
tree for the relation and reduces bottom-up.

### 3.5 Practical horizontal partitioning methods

The classical predicate-based PHF generalizes the methods engines actually
expose (Abadi's Data Partitioning entry):

| Method | Fragment predicate | Wins | Risk |
|---|---|---|---|
| Range | lo ≤ key < hi | range scans, pruning, rolling windows (drop/attach a partition) | skew; monotone-key insert hot spot on last range |
| List | key ∈ {v1..vk} | geography/tenant/business-unit placement | uneven sizes; unknown values need a default fragment (completeness) |
| Hash | h(key) mod n (or into buckets) | uniform spread, equi-join co-location | no range pruning; resharding cost unless buckets ≫ nodes |
| Round-robin | i mod n | perfect balance for scans | no pruning, no co-location |
| Composite | e.g. range then hash | pruning + spread | two-level metadata |

Completeness pitfalls: list partitioning without a default fragment, range
partitioning without −∞/+∞ sentinels, NULL keys (decide which fragment owns
NULL and encode it in the predicate so localization reasons correctly).

## 4. Allocation

Given fragments F, sites S, workload Q: choose x_fj ∈ {0,1} (fragment f stored
at site j) minimizing cost or response time subject to constraints (storage
per site, processing capacity, response-time bounds, availability = minimum
copies, placement policy such as data residency). This is the file allocation
problem (Chu, IEEE ToC 1969); it is NP-hard even in simplified forms (Apers
TODS 1988; Bell 1984; Chang & Shieh).

Simplified per-fragment cost model (communication only, unit costs C_ij from
site i to site j, C_ii = 0):

```
read(f)    = Σ_i  t_i · min_{j : x_fj = 1} C_ij        # each read goes to nearest copy
update(f)  = Σ_i  Σ_j  x_fj · u_i · C_ij               # every write reaches every copy (ROWA)
storage(f) = Σ_j  x_fj · d_j
total(f)   = read + update + storage
```
t_i, u_i are read/write traffic originating at site i. The model makes the
replication trade-off explicit: adding a copy can only decrease read cost and
can only increase update and storage cost.

Heuristics, cheapest first:
- **Best fit (no replication)**: put each fragment at the site minimizing its
  own total cost. Ignores interactions (two fragments always joined together
  may land apart).
- **All beneficial sites (replication)**: place a copy at site j if the read
  benefit of a local copy exceeds the update-propagation cost it adds; then
  add copies for availability until the minimum copy count holds.
- **Randomized search** (iterative improvement, simulated annealing) or ILP
  solvers over the full model, including join co-location terms
  (cost of Ri ⋈ Sj across sites).
- **Dynamic allocation**: keep per-fragment access statistics per origin site;
  migrate or replicate when the observed pattern drifts. Distinguish a
  *replica* (long-lived, maintained by update propagation) from a *cache*
  (short-lived, invalidated on change). Mariposa (Stonebraker et al.
  VLDB J 1996) priced data and let sites buy/sell fragments.

Fragmentation and allocation are classically solved in two phases (first
fragment, then allocate), which is suboptimal because the best fragmentation
depends on the achievable placement; integrated formulations exist
(Saccà & Wiederhold TODS 1985 for processor clusters).

## 5. Design checklist (what a DDL/advisor component must enforce)

- Reject or warn on fragmentation definitions that fail completeness
  (missing default list fragment, gap in ranges, DHF without FK enforcement).
- Prove disjointness at DDL time for range/list (interval overlap test) and
  for DHF (owner join attribute is a declared key).
- Store the reconstruction expression in the catalog; localization must use
  it, not re-derive it.
- Version fragment definitions and allocation; every plan records the version
  it was compiled against.
- Keep replication out of fragment definitions; express it as allocation
  (replica sets per fragment) so update propagation and 1SR logic have one
  source of truth.
- Expose a "why is this fragment here" explanation (cost terms per site) from
  the allocator so DBAs can override placement for residency or latency.

> **Beyond EDBS:** Modern scale-out SQL systems automate PHF + allocation at
> fine grain. Spanner, CockroachDB and YugabyteDB split tables into
> contiguous key ranges (splits/ranges/tablets) that are split and merged by
> size and load and rebalanced across nodes, each range replicated by its own
> Paxos/Raft group — allocation becomes a continuous background process
> rather than a design-time decision. Spanner's interleaved tables (child
> rows stored under the parent's primary-key prefix) are derived horizontal
> fragmentation expressed in the key encoding; CockroachDB's REGIONAL BY ROW
> tables are list fragmentation on a hidden region column plus placement
> constraints, and its GLOBAL tables are full replication of read-mostly
> data. YugabyteDB defaults to hash sharding on the leading primary-key
> column and offers range sharding on request. Citus exposes DHF directly as
> co-located distribution columns and full replication as reference tables.
> Teradata hashes the primary index to hash buckets mapped to AMPs (hash PHF
> with buckets ≫ nodes so reconfiguration moves buckets, not rows by
> predicate) and layers range/case partitioning inside each AMP (PPI), i.e.
> composite partitioning. Monotonically increasing keys under range
> partitioning concentrate all inserts on the last range; the standard
> mitigations are hash-prefixed ("hash-sharded") keys or bit-reversed /
> UUID keys. Workload-driven partitioners replace affinity matrices with
> graph partitioning of co-accessed tuples: Schism (Curino et al. VLDB 2010)
> and Horticulture (Pavlo et al. SIGMOD 2012).

Sources: Distributed Database Design (p.1170); Distributed Architecture
(p.1152); Distributed Database Systems (p.1174); Distributed DBMS (p.1177);
Data Partitioning (p.802); Distributed Query Optimization (p.1201) for
fragmentation independence.
