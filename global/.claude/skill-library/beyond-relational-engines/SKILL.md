---
name: beyond-relational-engines
description: "Use when an RDBMS engineer must design, integrate or review an adjacent engine family as a design choice relative to the relational engine: NoSQL key-value/wide-column/document stores, JSON/XML storage and indexing, XQuery processing, graph and RDF stores, array databases, object-relational types, main-memory DBMS, probabilistic databases, provenance, crowd DBs, multitenant/elastic DBaaS. Triggers on NoSQL, Bigtable, Dynamo, Cassandra, MongoDB, CAP, PACELC, eventual consistency, entity group, JSONB, shredding, Dewey ID, ORDPATH, pre/post encoding, structural join, TwigStack, DataGuide, property graph, SPARQL, triple store, Hexastore, RDF-3X, vertical partitioning, regular path query, OID, pointer swizzling, UDT, UDF cost, possible worlds, safe plan, lineage, provenance semiring, multitenancy, live migration. Apply even when phrased as 'should we add a JSON column or a document store', 'why is our triple store slow', or 'can we explain where this row came from'."
---

# Beyond-Relational Engines

This skill owns the boundary between the relational engine and its
neighbors: stores that dropped parts of the relational contract (NoSQL),
data models that are trees or graphs rather than sets of flat tuples
(JSON/XML, graphs, RDF, arrays, objects), and semantics that annotate
tuples with more than presence (probabilities, provenance, crowd answers).
The single most important idea: **every adjacent family is a relational
engine with one assumption changed** — atomicity scoped to one key, order
and nesting made first-class, joins replaced by pointer chasing, or the
Boolean semiring replaced by another — so the right question is always
"which assumption, what does it buy, and which relational machinery can I
still reuse?"

## Mental model

```
 relational core:  flat tuples · set/bag semantics · multi-key ACID · declarative SQL · cost-based optimizer
   │ shrink atomicity to one key ──────────► KV / wide-column / document (Dynamo, Bigtable, MongoDB)
   │ relax replica agreement ──────────────► eventual / timeline / session consistency (CAP, PACELC)
   │ make nesting + order first-class ─────► JSON/XML: labels (Dewey, pre/post), path indexes, twig joins
   │ make paths of unknown length central ─► graph/RDF: adjacency, RPQs, permutation indexes, WCOJ
   │ make n-D neighborhoods the unit ──────► arrays: tiles/chunks, tile streaming, cell algebra
   │ make identity + behavior first-class ─► objects/ORDB: OIDs, REFs, swizzling, UDT/UDF contracts
   │ remove the I/O assumption ────────────► main-memory DBMS: CPU/cache-bound design
   │ annotate tuples with a semiring ──────► probabilistic DBs (events), provenance (ℕ[X]), crowd (cost/quality)
   └ share one engine across tenants ──────► multitenancy, elasticity, live migration
```
- Most were later **re-absorbed**: SQL and transactions returned to NoSQL
  (NewSQL, Spanner); JSON, graphs (SQL/PGQ) and arrays (SQL/MDA) became SQL
  types; probabilistic and provenance evaluation compile to relational
  plans. Integrate unless the changed assumption is load-bearing.
- LSM storage, B-trees on labels, merge/hash joins, semi-naive recursion,
  ⊕-aggregation and DP enumeration transfer; the *encoding* and the
  *statistics* are usually what must be new.

## Core invariants

1. Per-key atomicity: no partially applied write to one key is ever
   visible; a server stops serving a range before its lease expires
   (fencing); at most one owner commits writes for a key at any instant,
   including during migration.
2. Eventual consistency: each replica's committed prefix only grows; every
   update enters it exactly once (executed or aborted); equal committed
   prefixes imply equal state; tombstones outlive the last replica's
   acknowledgement, so repair never resurrects deletes.
3. Tree labels: for every node pair and axis (child, descendant,
   following, sibling), the label predicate equals the navigational
   definition before and after any insert sequence; label order = document
   order; XPath results are duplicate-free by node identity and in document
   order unless the plan proves order indifference.
4. A value/path index answers a predicate only if pattern containment and
   type/cast semantics (lax/strict, missing vs null, array unwrapping)
   match exactly.
5. Graph/RDF: path semantics (homomorphism, no repeated edge, simple path)
   is fixed and documented; recursion terminates on cycles; all physical
   layouts return identical answers.
6. OIDs are immutable and never reused while referenced; no swizzled
   pointer reaches disk; every UDT hash is consistent with its equality.
7. An immutable UDF yields the same result for the same arguments forever;
   volatile UDFs are never folded, cached, deduplicated or reordered across
   rows.
8. Probabilistic plans apply each extensional operator only where its
   independence/disjointness assumption holds for all instances; outputs
   lie in [0,1]; non-hierarchical self-join-free CQs never get an
   extensional plan.
9. Provenance: DISTINCT and aggregation combine annotations with ⊕, never
   drop them; only rewrites sound for the annotation semiring are applied;
   ℕ[X] provenance mapped by a homomorphism equals direct evaluation in the
   target semiring.
10. Shared-table multitenancy: tenant id leads every partitioning and index
    key; statistics and plan caches do not mix tenants.

## Design space & trade-offs

| Need | Option | When it wins | Cost / risk |
|---|---|---|---|
| Scale-out serving | KV / wide-column with single-key ops | Transactions naturally confined to one row/partition; predictable latency | Cross-key invariants move into application code |
| Multi-key transactions at scale | Co-located granule (entity group, tree schema) | Workload has a natural root key | Schema constrained; cross-granule ops need 2PC/async |
| " | Distributed MVCC + Paxos-replicated 2PC (Spanner-like) | Arbitrary footprints, global strong consistency | WAN commit latency, clock infrastructure |
| Replica consistency | AP/EL (quorums, hinted handoff, LWW/CRDT) | Availability and latency dominate; mergeable data | Anomalies visible; repair machinery mandatory |
| Semi-structured data | Binary document column + expression/inverted indexes | Whole-document access, ad-hoc paths | Weak statistics; large-document updates |
| " | Shredding (inlining) / sub-columnarization | Regular, stable structure; analytics | Mapping complexity; reconstruction cost |
| " | Native paginated tree + structural labels | Deep/irregular XML, fine-grained updates, XQuery | New storage manager and operators |
| Tree labels | Region (pre/post/level) | Compact, O(1) ancestry, range-index friendly | Relabel on insert |
| " | Prefix (Dewey/ORDPATH) | Insert-friendly (ORDPATH), LCA, ancestor ids from label | Length grows with depth |
| Graph traversal | Index-free adjacency / CSR | Selective seeds, deep traversals, analytics | Poor bulk/attribute queries; updates (CSR) |
| " | Relational edge table + recursion / WCOJ | Unselective patterns, cyclic patterns, mixing with relational data | Recursive SQL ergonomics; needs trie-ordered indexes for WCOJ |
| RDF layout | Triple table + permutation indexes (RDF-3X) | Heterogeneous data, any bound pattern | k-fold index maintenance |
| " | Vertical partitioning / property tables | Few predicates / regular entities | Unbound predicates, many tables, NULLs |
| Arrays | Array-as-attribute with n-D tiling | Dense rasters, millions of arrays | Deep engine integration |
| Rich types | UDT/UDF + extensible indexes (GiST, cartridges) | Domain types inside the RDBMS | Opaque costs; crash risk if unfenced |
| Uncertainty | Safe plans (extensional) | Tractable queries; near-relational speed | Restricted plan space |
| " | Lineage + compilation / Monte Carlo | Hard queries; bounds or approximations | Exponential worst case / slow on easy queries |
| Provenance | Query rewriting (Perm/GProM) | No kernel changes, queryable provenance | Result-width explosion |
| " | Eager annotations / instrumented operators | Always-on lineage, interactive debugging | Overhead on every query |
| Multitenancy | VM / shared process / shared table | Isolation ↔ consolidation as listed | Engine governance work grows rightward |

## Algorithms that matter

| Algorithm | Essence | Cost / property |
|---|---|---|
| Consistent hashing + vnodes | Many ring tokens per node; key → next token clockwise; replicas = next N distinct nodes | Join/leave moves ~K/N keys; R + W > N overlaps only without stand-ins |
| Stack-Tree-Desc structural join | Merge start-sorted A, D; pop closed regions; push ancestors; emit stack × descendant | O(\|A\| + \|D\| + \|out\|), O(depth) space |
| TwigStack | Stream + stack per query node; getNext pushes only nodes with full subtwig extensions; merge path solutions | O(in + out) for ancestor-descendant-only twigs |
| Staircase join | Prune covered context nodes; scan each pre/post region once | Duplicate-free, document order, no sort |
| RPQ evaluation | BFS over graph × NFA states with visited set; semi-naive for set-at-a-time | O((\|V\| + \|E\|)·\|Q\|) per source; simple paths NP-complete |
| Leapfrog Triejoin (Beyond EDBS) | Per variable, intersect sorted iterators of all atoms by leapfrog seeks; recurse | AGM-bound optimal on cyclic patterns |
| RDF-3X access | Permutation whose prefix = bound positions; merge joins on leading variables; aggregated indexes when a variable is projected away | Every pattern is a range scan |
| Expensive predicate order | Ascending rank = (selectivity − 1)/cost; migrate across joins | Optimal for independent filters |
| Safe plan | Independent components → ⋈ᵖ; else root variable in all atoms → πᴵ; else #P-hard | PTIME iff it exists (SJF CQs) |
| Lineage probability | Independent/exclusive decomposition, else Shannon expansion; Karp–Luby FPRAS | Anytime bounds when stopped early |
| Semiring evaluation | ∪/π → ⊕, ⋈ → ⊗, σ → ⊗{0,1}; compute ℕ[X] once | Specialize to any semiring by homomorphism |

## Failure modes & classic bugs

- **NoSQL**: tombstone GC before repair resurrects deletes; LWW with skewed
  clocks drops writes; pruned vector clocks fake dominance; stale routing
  caches or unfenced leases create two owners; monotonic keys make one hot
  tablet; async global indexes documented as consistent.
- **Trees**: label overflow or global relabel under adversarial inserts;
  ORDPATH compared as integers; hash join/exchange breaks document order;
  DISTINCT by value instead of node identity; JSON index with different
  missing/null/array semantics (wrong only on irregular documents).
- **Graph/RDF**: predicate independence underestimates star queries by
  orders of magnitude; unbound predicates union thousands of vertical
  partitions; simple-path semantics silently exponential; supernodes.
- **Objects/UDFs**: UDT hash inconsistent with equality (collations,
  −0/NaN); "immutable" UDF reading tables leaves functional indexes stale;
  unfenced UDF crashes the server; expensive predicate pushed below a join.
- **Uncertainty/provenance/tenancy**: unsafe plans give plausible wrong
  probabilities; log(0) at p = 1; DISTINCT drops annotations; self-join
  elimination changes ℕ[X]; unstable base tuple ids; global statistics in
  shared tenant tables cause plan regressions; noisy neighbors.

## Implementation checklist (C/C++/Rust)

- Partition map: immutable versioned snapshot (`Arc`/RCU); requests carry
  the epoch; servers reject stale epochs and unowned ranges; leases use
  monotonic clocks, drift margin, fencing tokens on shared-storage writes.
- Labels: order-preserving variable-length byte strings (`memcmp` =
  document order), prefix-compressed B-tree keys, explicit `level`. Binary
  JSON: sorted key-offset header; API type `Missing | Null | Value`.
- Twig joins over start-sorted iterators with vector stacks and batched
  output. Graphs: CSR with delta-encoded neighbors, per-label degree stats,
  visited set on (node, automaton state). RDF: two-way dictionary with
  inlined typed literals, delta-compressed permutation B+-trees,
  characteristic sets.
- OIDs: logical 64-bit + OID map, or (page, slot) + forwarding stubs;
  swizzled refs as tagged words with a one-parent eviction invariant.
- UDF registry: volatility, null behavior, parallel safety, cost/rows,
  selectivity callback; fenced execution in a subprocess with batched IPC.
- Probabilities in log space with range assertions; annotations generic
  over a `Semiring` trait (zero/one/add/mul) so tests instantiate ℕ, 𝔹,
  ℕ[X]. Tenant id prefixes every key; per-tenant resource counters.

## How to test it

- NoSQL: Jepsen-style histories under partitions and clock skew
  (linearizability per key, or convergence + session guarantees);
  tombstone/repair races; migration under load without lost/doubled writes.
- Trees: random documents and twig queries; label plans vs path indexes vs
  a DOM navigator; axis predicate ⇔ navigation after random inserts; JSON
  predicates over missing/null/empty/array variants.
- Graph/RDF: brute-force BGP and product-BFS RPQ oracles on tiny graphs;
  differential testing across layouts; WatDiv-style shape sweeps.
- UDT/UDF: hash–equality property tests; volatility-misuse detection.
- Probabilistic: possible-world enumeration oracle (≤ 20 tuples); planner
  rejects non-hierarchical queries. Provenance: brute-force minimal
  witnesses; random homomorphisms ℕ[X] → ℕ/𝔹 vs bag/set execution.
  Multitenancy: noisy-neighbor SLO tests with skewed tenant sizes.

## Expert review questions

1. Which relational assumption is dropped, and does the workload need it
   dropped — or would a typed column (JSON, graph view, array) suffice?
2. Where is the atomicity boundary, where do cross-boundary invariants
   live, and who repairs them after partial failure?
3. Under partition what fails and what diverges; without partition what
   does consistency cost in latency? How are leases fenced?
4. JSON/XML: which label scheme, worst-case insert behavior, and how are
   missing/null/empty distinguished in indexes?
5. Which path/twig patterns go to indexes, structural joins or navigation,
   and who decides?
6. Graphs: which path semantics, what happens at supernodes, binary joins
   or WCOJ on cyclic patterns?
7. RDF: which permutations exist, how are correlated predicates estimated,
   what does an unbound predicate cost?
8. Physical or logical OIDs — what happens on move, delete, reorganization?
9. Does every UDT/UDF declare volatility, cost and selectivity, and are the
   declarations verified?
10. How are intractable probabilistic queries detected, and is safe-plan
    computation decoupled from answer computation?
11. Which provenance notion is needed, how large can it grow, and which
    optimizer rules are disabled to keep it correct?
12. Multitenancy: what is isolated (CPU, memory, I/O, log), how are tenants
    placed and migrated, and what is per-tenant recovery?

## Go deeper

| Reference | Read when |
|---|---|
| `references/nosql-design-space.md` | Scale-out store or DBaaS design: Bigtable/Dynamo/PNUTS/MongoDB, partitioning, leases, CAP/PACELC, formal EC, transactions' return, main-memory family, multitenancy/elasticity |
| `references/semistructured-json-xml-storage-and-indexing.md` | Adding a JSON/XML type, index or operator: shredding, labels, path indexes, twig joins, XQuery architectures, modern JSON |
| `references/graph-and-rdf-engines.md` | Graph/RDF features or slowness: RPQs, adjacency, traversal vs join vs WCOJ, RDF layouts, permutation indexes, distributed RDF |
| `references/object-relational-and-extensibility.md` | New types, functions, references: OIDs, swizzling, path expressions, UDT/UDF optimizer contracts, array databases |
| `references/uncertain-and-probabilistic-databases.md` | Confidence scores or uncertain data: representations, dichotomy, safe plans, lineage compilation, Monte Carlo, crowd DBMSs |
| `references/provenance.md` | Lineage/explanations: why/how/where, semirings and optimizer soundness, capture, storage and identity |
| `references/edbs-entries.md` | Pulling the source: all 27 EDBS entries with pages |

## Related skills

- `lsm-storage` (storage under wide-column stores); `replication-and-
  consistency`, `replication-protocols` (quorum/repair/CRDT mechanics);
  `distributed-transactions`, `distributed-consensus` (Spanner, Calvin,
  Paxos/Raft behind the transactional comeback).
- `distributed-dbms-design`, `parallel-database-systems` — fragmentation and
  distributed query processing reused by sharded and RDF stores.
- `columnar-arrow-layout`, `olap-and-warehouse-engines` — DSM/column stores
  behind RDF vertical partitioning and JSON sub-columnarization.
- `index-structures-catalog`, `multidimensional-and-similarity-indexing` —
  B-tree/inverted/R-tree internals for labels, paths, array tiles.
- `query-optimizer`, `cardinality-and-statistics`, `join-algorithms`,
  `query-execution-advanced`, `tuning-and-benchmarking` — reused machinery.
- `relational-theory`, `sql-semantics-and-active-rules` (CQs, NULLs,
  recursion); `materialized-views-ivm` (semiring/lineage maintenance);
  `temporal-databases` (time travel for reenactment provenance).
- `dbms-architecture`, `concurrency-control-theory`, `recovery-and-durability`
  (main-memory, swizzling); `database-security-internals` (tenant isolation).

## Grounding

EDBS (2nd ed., 2018): Array Databases (p.165); CAP Theorem (p.395); Cloud
Computing (p.475); Column Stores (p.518); Crowd Database Systems (p.689);
Data Management in Data Centers (p.786); Document Databases (p.1237);
Elasticity (p.1269); Eventual Consistency (p.1403); Graph Data Management
in Scientific Applications (p.1636); Graph Database (p.1639); Main Memory
DBMS (p.2164); Multitenancy (p.2440); NoSQL Stores (p.2513); Object Data
Models (p.2525); Probabilistic Databases (p.2830); Provenance in Databases
(p.2904); Provenance Storage (p.2923); Query Processing and Optimization in
Object Relational Databases (p.3032); Query Processing over Uncertain Data
(p.3052); RDF Stores (p.3100); Semi-structured Data (p.3444); SaaS
(p.3544); Uncertain Data Models (p.4297); XML Indexing (p.4749); XML
Storage (p.4796); XQuery Processors (p.4846).

Papers/systems: Bigtable (OSDI 2006); Dynamo (SOSP 2007); PNUTS (VLDB
2008); Gilbert & Lynch (2002); Spanner (OSDI 2012); ORDPATH (SIGMOD 2004);
XPath accelerator (SIGMOD 2002); structural joins (ICDE 2002); TwigStack
(SIGMOD 2002); Abadi et al. RDF vertical partitioning (VLDB 2007);
Hexastore (VLDB 2008); RDF-3X (VLDBJ 2010); predicate migration (SIGMOD
1993); c-tables (JACM 1984); Dalvi & Suciu (VLDB 2004, JACM 2012);
why/where provenance (ICDT 2001); provenance semirings (PODS 2007).
Beyond EDBS: WCOJ (PODS 2012), Leapfrog Triejoin (ICDT 2014), Dremel (VLDB
2010), LeanStore (ICDE 2018), Froid (VLDB 2018), SQL/PGQ, GQL (2024).
