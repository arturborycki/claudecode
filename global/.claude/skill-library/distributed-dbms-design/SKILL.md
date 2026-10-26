---
name: distributed-dbms-design
description: "Use when designing, implementing or reviewing a classical distributed DBMS (Ozsu-Valduriez lineage): distribution transparency, federated/multidatabase architecture, fragmentation and allocation, fragment-query localization, communication-aware distributed optimization, semijoin/Bloom reducers, distributed 2PL/timestamp CC, distributed deadlock, 2PC variants, 3PC termination, in-doubt recovery, multitenancy, DHT peer data management. Triggers on horizontal fragmentation, vertical fragmentation, derived fragmentation, minterm, bond energy algorithm, allocation problem, data localization, query shipping, R*, SDD-1, semijoin program, full reducer, global serializability, primary copy locking, wait-for graph, Chandy-Misra-Haas, presumed abort, presumed commit, termination protocol, in-doubt transaction, XA, shared-table multitenancy, consistent hashing. Apply even when phrased as 'shard this schema across regions', 'why is the cross-site join slow' or 'participants stuck prepared'."
---

# Distributed DBMS Design

Owns the classical distributed DBMS: what distribution is hidden from whom,
how global relations are fragmented and placed, how queries become fragment
subqueries plus transfers, and how CC, deadlock handling, commit and recovery
span sites. Key idea: **every distributed mechanism is downstream of
fragmentation and allocation** — pruning, local joins, commit fan-out,
deadlock scope and recovery dependencies all follow the sites a query touches.

## Mental model

- A **global relation** is a view: reconstruction(fragments), with fragments
  defined by σ (horizontal), π (vertical) or ⋉ (derived). Replicas are an
  allocation decision, never part of a fragment definition.
- Query processing = decomposition → **localization** (substitute
  reconstruction, prune provably empty pieces) → **global optimization** (join
  order/shape, sites, transfer method, reducers, replica choice; cost = local +
  communication) → **local optimization** per site.
- Cross-site correctness = local correctness + **agreement**: one
  serialization order at every site (global serializability / 1SR), one commit
  decision (atomic commitment), cycles found in the union of local WFGs.
- Autonomy is the dial: parallel DBMS → regular distributed DBMS (DBA designs
  fragments) → federated / mediator / multidatabase → P2P/PDMS. Each step
  removes a transparency and a global mechanism (CC, commit, catalog).
- Cost axes are separate — bytes, messages, forced log writes, critical path —
  and must each be optimized explicitly.

## Core invariants

1. **Completeness**: every tuple/attribute of R is in some fragment (DHF needs
   FK enforcement, list needs a default, ranges need sentinels, NULL has an owner).
2. **Reconstruction**: the catalog stores R = ∇(fragments) — ∪ for horizontal,
   ⋈ on the replicated key for vertical — and localization uses exactly it.
3. **Disjointness**: horizontal fragments never overlap; DHF member fragments
   are disjoint only if the link attribute is a key of the owner.
4. **Sound pruning**: drop a fragment subquery only if query ∧ fragment
   predicate is unsatisfiable (or the vertical fragment adds no needed column).
5. **Version-bound plans**: a plan runs only against the allocation version it
   was compiled for; a mismatch recompiles, never reads a moved fragment as empty.
6. **Global serializability**: conflicting global transactions are ordered the
   same at every common site; replicas apply updates in one total order (1SR).
7. **Global two-phase rule**: no subtransaction releases a write lock before
   the global commit decision is known locally (strict 2PL + 2PC).
8. **Force before send**: a participant forces its prepared record (and T's
   log) before voting YES, then never decides unilaterally except by a reported
   heuristic decision; the coordinator forces the decision before sending it
   and forgets T only after every ACK its variant requires.
9. **Presumption consistency**: an inquiry about a forgotten transaction gets
   the presumption of the inquirer's protocol variant; never "unknown".
10. **Prepared is untouchable**: a recovering participant rebuilds write locks
    of in-doubt transactions before admitting work; no deadlock resolution or
    wound ever aborts a subtransaction that has voted YES.
11. **Tenant isolation**: in shared-table multitenancy every base-table access
    carries the tenant predicate, injected by the binder, not the application.

## Design space & trade-offs

| Fragmentation | When it wins | Cost / risk |
|---|---|---|
| Primary horizontal (range/list/hash by predicate) | queries select by the fragmenting attribute; geographic or tenant locality | skew; hot last range for monotone keys; cross-fragment scans |
| Derived horizontal (co-locate member with owner by FK) | frequent owner–member joins become local; cross pairs pruned by construction | only one owner per member can be co-located; FK must be enforced |
| Vertical (BEA + split) | disjoint attribute-access clusters, wide rows | reconstruction join for every query spanning clusters; rare across WAN |
| Full replication | small, read-mostly tables (dimensions, reference data) | update fan-out to all sites |

| Execution choice | When it wins | Cost / risk |
|---|---|---|
| Query vs data shipping (hybrid per operator) | query: large inputs, selective remote predicates; data: hot shared data, spare client CPU | server hot spots vs bytes and cache consistency |
| Ship whole | join keeps most rows; few round trips | bytes |
| Fetch matches / bind join | small outer, selective lookups, capability-limited sources | messages; needs blocking and sort/dedupe |
| Semijoin | card(S ⋉ R) ≪ card(S) and the projection is small | extra round trip; useless when selectivity is high |
| Bloom filter reducer | almost always cheaper than semijoin to ship | false positives cost bytes only |

| Concurrency / commit | When it wins | Cost / risk |
|---|---|---|
| Primary-copy 2PL | replicated data, one lock per item | primary availability |
| Distributed 2PL + ROWA | local reads | write fan-out, more global deadlocks |
| Timestamp ordering (Lamport + site id) | no deadlocks; MVTO for snapshot reads | restarts, starvation of long txns |
| Wound-wait / wait-die | no global detector needed | unnecessary aborts |
| Detection (central WFG, path pushing, CMH probes) | AND-model locks; aborts only real (or phantom) cycles | messages; phantom deadlocks |
| Presumed abort / presumed commit | PrA: XA standard, cheap aborts and read-only; PrC: commit-heavy | PrC forces an initiation record; variants incompatible |
| 3PC | site failures only, reliable network | extra round; unsafe under partitions; never productized |
| Consensus-replicated coordinator/participants | production non-blocking | consensus latency per commit (see distributed-transactions) |

## Algorithms that matter

- **Minterm PHF**: complete + minimal simple-predicate set (COM_MIN); minterms
  as the product of per-attribute domain cells, not 2^m enumeration.
- **DHF**: Si = S ⋉ Ri along a PK→FK link; validate owner key and FK.
- **Vertical (BEA)**: aff from usage × frequency; greedy placement maximizing
  cont = 2bond(i,k)+2bond(k,j)−2bond(i,j), O(n²) with precomputed bonds; split
  maximizing CTQ·CBQ − COQ² over split points × cyclic shifts.
- **Allocation**: Σ t_i·min_j C_ij + Σ x_j·u_i·C_ij + storage; NP-hard;
  best-fit, all-beneficial-sites, randomized search.
- **Localization**: distribute ⋈ over ∪; drop contradictory pairs (interval
  overlap), DHF cross pairs, vertical fragments with no needed attribute.
- **Reducers**: semijoin beats ship-whole iff size(π_A R) + size(S ⋉ R) <
  size(S); Bloom FP ≈ (1−e^{−kn/m})^k; full reducer for acyclic queries =
  bottom-up then top-down semijoin pass on a join tree (2(n−1) semijoins);
  cyclic queries need data-dependent fixpoints.
- **Optimizers**: SDD-1 greedy semijoins by benefit − cost then assembly site;
  R* DP with join site and ship-whole/fetch-matches as plan properties;
  Distributed INGRES dynamic fragment-and-replicate.
- **Deadlock**: WFG merging (central/hierarchical), path pushing with an EX
  node, Chandy–Misra–Haas probes (i, j, k) returning to the initiator.
- **Commit**: 2PC/PrA/PrC/3PC state machines, termination and restart tables
  in `references/commit-protocols-and-recovery.md`.

## Failure modes & classic bugs

- Localization prunes a fragment that is not provably empty (NULL semantics,
  type coercion, collation-sensitive ranges) → silently missing rows.
- Replicas registered as fragments → union double counts; DHF member row with
  a missing owner dropped instead of rejected.
- Stale catalog cache after a fragment move → plan reads an emptied fragment.
- Semijoin chosen on stale selectivity (ships the projection, then nearly all
  of S); Bloom filter sized by rows, not distinct keys, saturates.
- Fetch-matches without row blocking: per-tuple round trips dominate.
- Local serializability assumed sufficient; read locks released at statement
  end inside a distributed transaction.
- YES sent before the prepared record is durable; decision sent before forced;
  coordinator forgets before all ACKs; PrA and PrC participants mixed under one
  presumption; recovered participant ignores in-doubt locks.
- Phantom deadlocks from asynchronously shipped WFG deltas; two victims for
  one cycle; prepared transaction picked as victim.
- 3PC under a partition commits on one side and aborts on the other.
- Tenant predicate missing on one access path (view, function, CTE); optimizer
  statistics mixing tenants.

## Implementation checklist (C/C++/Rust)

- Catalog: fragment predicate ASTs + reconstruction tree, fragment → replica
  set, per-fragment stats, monotonic version; replicated to coordinators;
  plans invalidated by version.
- One predicate-satisfiability engine (per-attribute intervals/sets, NULLs,
  conservative "maybe") shared by DDL validation and localization.
- Plan IR: operators carry a site; explicit send/receive with row blocking;
  transfer method and reducers are plan properties DP can cost. Cost model
  returns (bytes, msgs, local, critical path) plus an explicit objective.
- Global txn id = (coordinator site, seq); birth timestamp assigned at the root
  and propagated (wound-wait, TO); aborts always route to the root.
- Commit protocol as an explicit per-(txn, role) state machine; one function
  decides forced vs lazy records per transition per variant; protocol table
  rebuilt from the log; in-doubt table persisted with lock sets plus an admin
  path to list, inquire and heuristically resolve with damage reporting.
- Lock manager exposes holder sets for WFG extraction; edges carry epochs.
- Bloom filters sized from distinct estimates, cache-line blocked, with a
  saturation cutoff.

## How to test it

- **Differential oracle**: unfragmented single node vs fragmented simulated
  sites on generated queries (NULLs, boundaries, empty fragments).
- **Fragment DDL / localization properties**: completeness and disjointness
  checks agree with brute-force tuple assignment; every pruned fragment
  subquery is empty on random instances satisfying the fragment predicates.
- **Optimizer**: plan-shape snapshots with synthetic stats (semijoin chosen
  iff its inequality holds); EXPLAIN bytes/messages equal executor counters.
- **Global serializability**: record cross-site histories, assert the union
  serialization graph is acyclic.
- **Commit**: deterministic simulation crashing every role at every
  transition and dropping/duplicating messages, with mixed PrA/PrC
  participants; assert AC1–AC5, eventual decision after repair, lock release.
- **Deadlock**: random cross-site wait patterns plus spontaneous aborts; one
  victim per real cycle; count phantoms.
- **Multitenancy**: fuzz SQL; no foreign-tenant row ever read or written.

## Expert review questions

1. Which transparencies do you promise, to which role, and what does EXPLAIN
   show about sites, bytes and messages?
2. Prove completeness, disjointness and reconstruction per fragmented table,
   including NULLs and out-of-range values.
3. Which joins are local by construction, and what is the fragment join graph
   of the top queries?
4. How does localization prove emptiness, including execution-time parameters,
   and how are plans invalidated when a fragment moves or splits?
5. Is the objective total cost or response time, and how are bytes, messages
   and local work weighted per link?
6. When semijoin vs Bloom vs ship-whole vs fetch-matches, and how is the
   reducer's selectivity estimated?
7. Where are write locks released relative to the decision, and how is 1SR
   argued with replication?
8. Which deadlock strategy, what phantom rate, and how is a second victim per
   cycle prevented?
9. Which 2PC variant, which records are forced, and what does a read-only vs an
   update transaction cost in forces and round trips?
10. Coordinator dies after PREPARE: who resolves in-doubt transactions, how long
    are locks held, is there a reported heuristic path?
11. Can participants with different presumptions (XA resources, foreign DBs)
    coexist safely?
12. If you claim non-blocking, under which failure model, and what happens on a
    partition?
13. Which multitenancy model, what limits consolidation, how are noisy
    neighbors contained and tenants migrated?

## Go deeper

- `references/fragmentation-and-allocation.md` — transparency, architectures,
  catalog, PHF/DHF/VF rules, minterms, BEA, allocation, modern sharding; read
  when designing a schema's distribution or a partitioning advisor.
- `references/distributed-query-processing-and-semijoins.md` — localization,
  cost models, join strategies, semijoin/Bloom math, full reducers, SDD-1/
  INGRES/R*, spatial semijoins; read when building or debugging the optimizer.
- `references/distributed-cc-and-deadlock.md` — global serializability, 2PL/
  TO/OCC variants, tickets, wound-wait, path pushing, CMH, phantoms; read when
  building cross-node locking or deadlock detection.
- `references/commit-protocols-and-recovery.md` — 2PC log discipline, PrA/PrC
  costs, optimizations, heuristics, 3PC, in-doubt recovery; read when writing
  the commit coordinator or participant recovery.
- `references/multitenancy-and-cloud.md` — KV axes, ownership co-location,
  multitenancy and schema mapping, DHTs, PIER, PDMS; read for DBaaS/SaaS.
- `references/edbs-entries.md` — every bundle entry with page and use.

## Related skills

- `distributed-transactions` — modern protocols (Spanner, Calvin, Percolator);
  this skill is the classical CC/commit depth beneath them.
- `distributed-consensus` — Paxos/Raft to replicate coordinators/participants.
- `parallel-distributed-execution`, `parallel-database-systems` — exchange
  operators and intra-cluster parallelism; this skill owns site-level costing,
  localization and placement.
- `replication-protocols`, `replication-and-consistency` — ROWA/quorum,
  eager/lazy, consistency models (1SR is the interface).
- `concurrency-control-theory`, `recovery-and-durability` — single-site
  serializability and WAL/ARIES under the distributed layers.
- `query-optimizer`, `cardinality-and-statistics`, `join-algorithms`,
  `query-execution-advanced` — local search, semijoin selectivity, local join
  algorithms, adaptive execution; `relational-theory` — acyclicity, join trees.
- Also: `multidimensional-and-similarity-indexing` (spatial joins),
  `olap-and-warehouse-engines` (star semijoins), `stream-processing-engines`
  (symmetric hash join), `beyond-relational-engines` (KV stores),
  `database-security-internals` (tenant isolation), `dbms-architecture`,
  `tuning-and-benchmarking`, `index-structures-catalog`,
  `storage-devices-and-io`, `materialized-views-ivm`, `temporal-databases`,
  `sql-semantics-and-active-rules`.

## Grounding

EDBS (Liu & Özsu, 2nd ed., 2018), Distributed ...: Architecture p.1152,
Concurrency Control p.1157, Database Design p.1170, Database Systems p.1174,
DBMS p.1177, Deadlock Management p.1181, Hash Table p.1190, Join p.1191, Query
Optimization p.1201, Query Processing p.1206, Recovery p.1212, Spatial
Databases p.1215, Transaction Management p.1222. Also: Data Partitioning p.802;
Data Management in Data Centers p.786; Cloud Computing p.475; Multitenancy
p.2440; Peer Data Management System p.2696; Semijoin p.3436; Semijoin Program
p.3440; Three-Phase Commit p.4127; Two-Phase Commit p.4259; Two-Phase Commit
Protocol p.4266.

Seminal: Özsu & Valduriez, *Principles of Distributed Database Systems*; Ceri
& Pelagatti 1984; Bernstein & Goodman (Comp. Surveys 1981); SDD-1 (TODS 1981);
Distributed INGRES (SIGMOD 1978); R* (Selinger & Adiba 1980; Mohan, Lindsay,
Obermarck TODS 1986); Bernstein & Chiu (JACM 1981); Yannakakis (VLDB 1981);
Navathe et al. (TODS 1984); Skeen (SIGMOD 1981); Chandy, Misra, Haas (TOCS
1983); Obermarck (TODS 1982); Knapp (1987); Aulbach et al. (SIGMOD 2008);
Gray & Lamport Paxos Commit (TODS 2006).
