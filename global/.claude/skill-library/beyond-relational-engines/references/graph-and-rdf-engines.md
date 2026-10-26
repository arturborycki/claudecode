# Graph and RDF engines

Read this when designing or reviewing storage and query evaluation for
graph-shaped data: property graphs vs RDF, adjacency representations,
traversal-based vs join-based evaluation, regular path queries and their
complexity, RDF triple stores (triple tables, vertical partitioning,
property tables, permutation indexes à la YARS/Hexastore/RDF-3X), and
distributed graph/RDF processing.

---

## 1. Two graph data models

| Aspect | Property graph | RDF |
|---|---|---|
| Atoms | Nodes and edges, each with identity, one or more labels/types, and a key-value property map | Triples (subject, predicate, object); terms are IRIs, blank nodes, literals |
| Edge identity / edge properties | First class; parallel edges distinguishable | Not native: reification, n-ary relation nodes, named graphs (quads), or RDF-star style quoted triples |
| Schema | Usually none or optional constraints | Vocabularies/ontologies (RDFS, OWL) stored as triples; enable **inference** of implicit triples |
| Identity | Internal ids | Global IRIs → data integration across sources (Linked Open Data) |
| Query languages | Cypher, Gremlin (imperative traversal), PGQL; ISO SQL/PGQ and GQL (Beyond EDBS, below) | SPARQL (BGPs, OPTIONAL, UNION, FILTER, aggregation, property paths in 1.1) |
| Pattern semantics | Cypher: homomorphism on nodes but no edge repeated within a match | SPARQL BGP: homomorphism (variables may bind to the same term) |
| Typical engines | Neo4j, Sparksee, TigerGraph, graph extensions of RDBMSs | Jena, Sesame/RDF4J, Virtuoso, RDF-3X, Hexastore, Blazegraph |

Both descend from older ideas: hierarchical and network (CODASYL) models
were graph-like but lacked path queries of unbounded length;
semi-structured data (OEM) is a rooted labeled graph; object databases are
graphs of OIDs. The defining requirement of a *graph database* is queries
over **paths whose length is not known in advance**, plus schema-level
queries ("how are A and C connected?").

Variants worth knowing: hypergraphs (edges over node sets), hypernodes
(nodes containing graphs), nested graphs for abstraction.

---

## 2. Query classes and their complexity

| Class | Example | Complexity / evaluation |
|---|---|---|
| Subgraph pattern matching (CQ over the edge relation) | triangle, star, path of fixed length | Homomorphism = conjunctive query evaluation (NP-complete combined, PTIME data complexity); isomorphism variant NP-hard |
| **Regular path queries (RPQ)** | `(knows|friendOf)+`, `x -[:KNOWS*1..5]-> y` | Arbitrary-path semantics: build product of graph and NFA, BFS/DFS from sources: O(\|V\|·\|Q\| + \|E\|·\|Q\|) per source. Simple-path semantics (no repeated node): NP-complete even for fixed expressions like `(aa)*` (Mendelzon & Wood 1995) |
| Conjunctive RPQs (CRPQ) | patterns whose edges are RPQs | CQ join of RPQ results; containment decidable (EXPSPACE) |
| Shortest / weighted paths | routing | Dijkstra / A*, bidirectional search; not expressible in plain RA |
| Reachability | `x ->* y` | Transitive closure; index with interval labels on spanning trees, 2-hop labels, GRIPP-style prefix-postfix tables |
| All paths | provenance, biology | Output exponential in \|E\|; most systems refuse or bound length |
| Analytics | PageRank, centrality, components, clustering | Iterative whole-graph computation (vertex-centric/Pregel, Giraph) — usually outside the query engine |
| Graph collections | chemical compound libraries | Filter-and-verify: feature/descriptor index (paths, cycles, frequent subgraphs) to prune, then subgraph isomorphism on candidates |

Implementation consequence of semantics choice: counting paths (bag
semantics over paths) makes `*` diverge on cycles; SPARQL 1.1 property paths
use existential (set) semantics for `*`/`+`; Cypher's no-repeated-edge rule
makes variable-length patterns terminate but costs per-path state.

Logical optimization of path queries: rewrite with **graph schemas** or
DataGuides to drop impossible label sequences, detect redundant query
components (only redundant under a given schema), and choose evaluation
direction (forward from the selective end).

---

## 3. Storage representations

| Representation | Layout | Per-hop cost | Strengths | Weaknesses |
|---|---|---|---|---|
| Node table + edge table in an RDBMS | `edge(src, dst, label, …)` with B-trees on (src,label,dst) and (dst,label,src) | O(log E) index probe per frontier node, or one hash/merge join per level for set-at-a-time | Reuse optimizer, transactions, bulk queries ("all edges owned by Bob") | Path queries become dynamic recursive SQL; generic optimizers poor at recursion and correlated statistics |
| Adjacency lists (per node vector of neighbor ids) | Usually grouped by edge type and direction | O(degree) scan after O(1) lookup | Fast expansion | Updates to vectors; supernodes |
| **CSR / CSC** | `offsets[V+1]`, `targets[E]` (+ edge property arrays), sorted by source | O(1) to find, contiguous neighbor scan | Cache- and SIMD-friendly; ideal for analytics and WCOJ; compressible (delta-encoded sorted targets) | Immutable; updates via delta stores / periodic rebuild |
| **Index-free adjacency** (Beyond EDBS: Neo4j-style native store) | Fixed-size node and relationship records; a node points to its first relationship; each relationship is in two doubly linked chains (one per endpoint); property chains | O(1) pointer chase per hop, independent of graph size | Deep traversals from a few start nodes; easy local updates | Random I/O when not cached; poor for scans and bulk joins; high-degree nodes need type-grouped chains |
| Triple/quad tables (RDF) | §5 | index probe or merge join | Uniform; permutation indexes cover all access patterns | Many self-joins |

Supernodes (celebrity vertices with millions of edges) dominate tail
latency in every representation: partition their adjacency by edge type
and/or neighbor id, keep per-node degree statistics, and let the planner
avoid expanding from them.

---

## 4. Traversal vs join-based evaluation

A traversal step "from frontier F follow label ℓ" is algebraically a
semi-join/join `F ⋈ E_ℓ`. The engines differ in *granularity*:

| Style | How | Wins | Loses |
|---|---|---|---|
| Traversal (tuple/node-at-a-time, pointer chasing) | DFS/BFS from bound start nodes using adjacency | Highly selective start, short-to-moderate depth, local updates; latency-oriented | Unselective patterns, scans, aggregates; hard to parallelize; plans fixed by the query writer (Gremlin) |
| Join-based (set-at-a-time) | Each step a hash/merge join of the frontier relation with the edge relation; recursion as semi-naive fixpoint (`WITH RECURSIVE`) | Unselective patterns, many start nodes, parallel/distributed execution, cost-based ordering | Per-step materialization; binary join plans can be asymptotically suboptimal on cyclic patterns |
| Graph exploration in distributed stores | Ship the partial match to the partition owning the next node | Avoids shipping whole edge partitions | Number of start nodes is the key cost factor; skew |

Semi-naive evaluation for transitive closure: Δ₀ = E; Δᵢ₊₁ = (Δᵢ ⋈ E) − T;
T ∪= Δᵢ₊₁; stop when Δ empty. Each derivation computed once; needs a
set-difference against the accumulated result (hash set or sorted run) —
the duplicate check is usually the dominant cost and memory consumer.

**Cyclic patterns.** For the triangle query R(a,b) ⋈ S(b,c) ⋈ T(c,a) with N
edges per relation, any pairwise join plan can produce Θ(N²) intermediate
tuples while the output is at most N^{3/2} (AGM bound).

> **Beyond EDBS:** worst-case optimal joins (Ngo, Porat, Ré, Rudra PODS
> 2012; Leapfrog Triejoin, Veldhuizen ICDT 2014) evaluate variable-at-a-
> time — intersect the sorted candidate sets for one variable across all
> atoms mentioning it, recurse — matching the AGM bound. They need
> trie-ordered (sorted, multi-level) indexes per atom for the chosen
> variable order, which is exactly what RDF permutation indexes or CSR
> provide. Hybrid optimizers (e.g., Umbra, Freitag et al. VLDB 2020) use
> binary hash joins for acyclic parts and WCOJ for cyclic, growing parts.
> ISO SQL:2023 Part 16 (SQL/PGQ) adds property-graph views and
> `GRAPH_TABLE(... MATCH ...)` over relational tables; ISO GQL
> (ISO/IEC 39075, 2024) standardizes a standalone property graph query
> language. Both make "graph engine inside the RDBMS" a mainstream design.

**Graph-at-a-time** algebras (He & Singh 2008) treat graphs/subgraphs as
first-class values and use neighborhood-signature indexes for pruning
before exact matching.

---

## 5. RDF stores

### 5.1 Dictionary encoding (universal)
Map every IRI/literal to a fixed-width integer id (hash or sequential);
store ids in all tables and indexes; decode only for output. Benefits:
compact fixed-width tuples, integer comparisons, compression. Pitfall:
FILTERs on literal values (ranges on numbers/dates, regex) need either
order-preserving ids per datatype, inlined literal values, or late decoding
— otherwise `FILTER(?price < 10)` decodes everything.

### 5.2 Triple table
`triples(s, p, o)` (or `quads(s, p, o, g)` for named graphs).
SPARQL → SQL is mechanical: one copy of the table per triple pattern,
constants → equality predicates, shared variables → equality joins, FILTER →
WHERE, SPARQL 1.1 GROUP BY/aggregates → SQL aggregates (OPTIONAL → left
outer join with SPARQL's subtly different null/compatibility semantics).
Result: a query with k patterns is a k-way **self-join**. Generic
optimizers suffer because (i) statistics per column ignore the strong
**correlations** between predicates of the same subject (a subject with
`isbn` almost surely has `title`), (ii) multi-dimensional histograms are
too large for billions of triples, (iii) join graphs are large (10–30
patterns).

**Characteristic sets** (Neumann & Moerkotte ICDE 2011): group subjects by
the exact set of predicates they have; store counts per set (and
occurrence counts per predicate within the set). Star-pattern cardinality
= sum over characteristic sets that contain the query's predicates —
captures correlations that independence assumptions miss.

### 5.3 Vertical partitioning (Abadi et al. 2007, SW-Store)
One two-column table `(s, o)` per predicate, sorted by subject (often in a
column store); quad variant adds g.
- Wins: patterns with bound predicate (the common case) scan exactly one
  narrow table; subject-subject (star) joins are **merge joins** of
  subject-sorted tables; columns compress well; per-table statistics
  capture s–o correlation for that predicate.
- Loses: patterns with **unbound predicate** must union all tables;
  thousands of predicates → thousands of tables (catalog and plan
  overhead); subject-object joins are not merge joins unless a second
  object-sorted copy exists; inserts touch many tables.
- Counterpoint (Sidirourgos et al. VLDB 2008): much of the gain comes from
  the column store and sort order, not partitioning per predicate — a
  single triple table clustered on (p, s, o) in the same column store
  performs comparably and scales better in the number of predicates.

### 5.4 Property tables (Jena2)
Cluster subjects with similar predicate sets into one wide table (one row
per subject, one column per predicate, NULL where absent). Excellent for
regular data and star queries (no joins); poor for multi-valued predicates
(spill to a triple table), sparse/irregular data (NULL-heavy), and schema
drift (clustering must be recomputed). Essentially a materialized pivot —
the RDF analogue of schema-driven XML shredding.

### 5.5 Permutation indexes
Store the triple set redundantly in multiple sort orders so every triple
pattern (any combination of bound positions) is a **prefix range scan** of
one index, and many joins become merge joins.

- **YARS** (2005): first systematic use of covering indexes over all
  needed permutations of quads.
- **Hexastore** (Weiss, Karras, Bernstein 2008): all six orders spo, sop,
  pso, pos, osp, ops; each a two-level structure (first key → vector of
  second keys → sorted list of third keys). Terminal lists are shared
  between pairs (e.g., the o-list for (s,p) is the same in spo and pso),
  bounding space at five times a plain triple table rather than six; every
  first-step merge join between two patterns sharing a variable is
  available.
- **RDF-3X** (Neumann & Weikum 2008/2010):
  - Six clustered B+-trees over the full triples in all permutations,
    leaves **delta/gap-compressed** (consecutive triples differ in few
    bytes; byte-level variable-length deltas), making six copies smaller
    than one naive table.
  - **Aggregated indexes**: the six binary projections (sp, ps, so, os,
    po, op) with counts, and three unary projections with counts — used
    when a variable is not needed in the output (duplicate-insensitive
    patterns) and for selectivity estimation.
  - Optimizer: DP join enumeration over merge joins (exploiting the sort
    orders) and hash joins; statistics from aggregated indexes plus
    frequent-path / join statistics precomputed for common star and chain
    shapes.
  - Runtime **sideways information passing**: merge joins publish the
    current key ranges/filters so other scans in the plan skip index
    regions that cannot join (semi-join reduction applied at run time
    across the whole plan, not just between adjacent operators).
- Bitmap-matrix stores (BitMat, TripleBit) encode triples as compressed
  bit matrices per predicate for fast join pruning.
- **Virtuoso**: quads in a relational engine (later column-wise) with a
  small set of permutation indexes (e.g., PSOG, POGS plus partial ones) —
  a deliberate subset to trade update cost and space against coverage.

Update cost: every insert hits all k permutation indexes; most stores use
batch loading plus a differential (delta) index merged periodically — an
LSM pattern (`lsm-storage`).

### 5.6 Choosing a layout
| Data / workload | Layout |
|---|---|
| Heterogeneous, unknown schema, ad-hoc SPARQL | Dictionary-encoded triple/quad table + full or near-full permutation indexes + characteristic sets |
| Few predicates, star queries with bound predicates, column store available | Vertical partitioning or (p,s,o)-clustered triple table |
| Highly regular entity data | Property tables + triple table for leftovers |
| Mostly traversal from a few seeds | Graph-native adjacency with predicate-grouped neighbor lists |

### 5.7 Inference
Forward chaining (materialize the RDFS/OWL closure at load: fast queries,
large storage, costly deletes — need truth maintenance) vs backward
chaining (rewrite queries to include entailed patterns, e.g., subclass
hierarchies as unions or recursive closures: no storage overhead, slower
queries). Most stores support only fragments (RDFS, OWL 2 RL/QL) at scale.

### 5.8 Distributed RDF
- **Partitioned centralized stores + coordinator**: hash on subject (star
  queries local; chains need joins across nodes), graph partitioning
  (METIS) with n-hop replication so queries up to n hops run locally
  (Huang, Abadi, Ren 2011), workload-driven fragmentation and replication
  (WARP, Partout). Coordinator does classical distributed query
  optimization; the dominant cost is shipping intermediate results.
- **Distributed file system**: triples (or vertically partitioned files)
  in HDFS; each join a MapReduce job partitioned on the join variable;
  optimization = minimize the number of jobs by grouping joins on the same
  variable into one job (SHARD, HadoopRDF-style).
- **Key-value stores**: store each triple under several composite keys
  (e.g., SPO, POS, OSP orders as row keys in Accumulo/HBase — Rya,
  H2RDF) so each pattern is a key-range scan; joins done by the client or a
  MapReduce layer.
- **Distributed graph engines** (Trinity.RDF): keep adjacency in a
  distributed memory cloud and evaluate by exploration, starting from the
  most selective pattern.

### 5.9 Benchmarks
LUBM (with inference), BSBM (e-commerce), SP²Bench (DBLP-like),
DBpedia SPARQL Benchmark (real query logs), WatDiv (diverse shapes and
selectivities — good at exposing optimizer weaknesses), LDBC SNB
(social-network, property-graph and RDF variants).

---

## 6. Graphs in scientific and provenance applications
- Two regimes: one huge graph (protein interaction networks, metabolic
  pathways: neighborhood extraction, shortest paths, structural properties
  like strongly connected components and centrality) vs a large
  collection of small graphs (chemical structures: similarity search,
  frequent substructure mining, significance-ranked results).
- Life-science graph families (protein interaction, gene regulation with
  signed directed edges, signal transduction, metabolic networks with
  reversible reactions) are modest in size by engine standards: tens of
  thousands of nodes for experimentally supported networks, up to roughly
  a million nodes and a few million edges once predicted edges are added.
  They fit in memory; the hard part is rich per-node/edge evidence
  attributes and pattern/motif queries, not scale.
- Thick nodes/edges: graph queries mix structural conditions with
  relational predicates over attribute tables joined to node/edge tables —
  a strong argument for graph capability *inside* a relational engine.
- Provenance graphs are DAGs; queries are path-associative ("2–5 steps
  downstream of X"), which relational node/edge storage handles poorly and
  graph stores handle well, while bulk "all provenance owned by Bob"
  queries favor relational storage (`provenance.md` §5).

---

## 7. Engine-builder checklist
- Choose path semantics explicitly (homomorphism / no repeated edge /
  simple path / shortest only) and document it; test termination on cyclic
  graphs.
- Store adjacency in both directions with predicate/label as the leading
  component; keep per-label degree histograms and per-node degree for
  supernode detection.
- Recursive evaluation: semi-naive with a hash set of visited (node,
  automaton-state) pairs; memory-bounded spill; cycle detection when the
  semantics forbids revisits.
- For RDF: dictionary encode; build at least the permutations your
  workload needs (spo, pos, osp is a common minimal cover for bound-
  predicate patterns); compress sorted leaves; collect characteristic sets.
- Plan enumeration must handle 10–30-way joins (DP with connectivity-based
  pruning, or greedy/IKKBZ-style fallback) — see `query-optimizer`.
- Oracles: a reference evaluator that computes RPQs via product automaton
  BFS and BGPs via naive nested loops on small random graphs; differential
  testing across layouts (triple table vs VP vs permutation indexes must
  agree).

Sources: Graph Database (p.1639); Graph Data Management in Scientific
Applications (p.1636); RDF Stores (p.3100); Column Stores (p.518);
Provenance Storage (p.2923); Semi-structured Data (p.3444).
