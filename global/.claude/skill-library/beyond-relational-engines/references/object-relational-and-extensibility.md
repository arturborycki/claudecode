# Object, object-relational and array data models; extensibility in the engine

Read this when designing or reviewing object identity, references and
path expressions, inheritance storage, pointer swizzling, user-defined
types/functions/access methods and how the optimizer costs them, or
array (raster) support — i.e., the places where the relational engine was
stretched to hold richer types and behavior.

---

## 1. The model differences that matter to an engine

| Concept | Relational | OODB (ODMG) | ORDB (SQL:1999/2003) |
|---|---|---|---|
| Identity | Value-based (keys) | Immutable system OID, independent of state | REF values of typed-table rows (system-generated, user-generated, or derived from attributes) |
| Relationships | Foreign keys on values | Object references; ODL relationships are bidirectional with system-maintained inverses | `REF(type) SCOPE table` attributes, arrays/multisets of REFs; `REFERENCES ARE CHECKED` gives referential integrity |
| Types | Flat atomic domains | Classes with state + methods, encapsulation | Structured UDTs (attributes + methods), distinct types, collections (ARRAY, MULTISET) |
| Inheritance | none | Class hierarchies, substitutability | `UNDER` for types and for typed tables (subtables); `NOT FINAL`, `NOT INSTANTIABLE` |
| Extents | Tables | Named class extents (deep: include subclass instances) | Typed tables; queries on a supertable include subtable rows unless `ONLY` |
| Query | SQL | OQL (select-from-where over extents, dot navigation, method calls, structured results) | SQL with `->`/dot on REFs (implicit join), `DEREF`, method invocation, `TREAT`, collection unnesting |
| Language integration | Impedance mismatch: set-oriented SQL vs record-at-a-time host code | One language for app and DB (C++/Java/Smalltalk bindings); persistence of program objects | Server-side UDFs/methods; still a client mismatch |

History in one line: OODBs (mid-1980s; 1989 OODB Manifesto; ODMG 3.0
standard) answered CAD/CASE/GIS needs for complex objects and
navigation; the relational camp answered with the Third-Generation
Manifesto (1990) and Postgres as the first ORDB, folding UDTs, REFs and
inheritance into SQL:1999. Products today: all major RDBMSs carry some ORDB
features; OODBs survive in niches.

**Why identity matters operationally**: with value keys, renaming a
publisher must update every referencing book (or use a surrogate key —
which is just a user-managed OID). OIDs make relationships stable under
state change, enable sharing (two objects reference one component without
copying) and cycles, and distinguish *identical* (same OID), *shallow
equal* (same state, same referenced OIDs) and *deep equal* (recursively
equal state) — three different equality operators the engine must define
for duplicate elimination, grouping and set operations.

---

## 2. Implementing OIDs and references

| OID form | Contents | Deref cost | Reorganization | Notes |
|---|---|---|---|---|
| Physical | (volume, page, slot) | One page access | Moving an object needs a forwarding stub left behind → two accesses thereafter; compaction requires stub chains or global rewrite | Like a RID; fastest when stable |
| Logical (surrogate) | Unique number; mapping table (hash or B+-tree) OID → physical address | Extra lookup (often cached) | Free: update the map | Map is a hot structure; needs its own logging/recovery |
| Physical-logical hybrid | Page id + logical slot within page | One page access; slot directory indirection | Move within page free; across pages via stub | Common compromise (slotted pages are already this) |
| Typed/structured | Class/type id + key | Type known without fetch → static dispatch, partition pruning | — | Larger references |

Invariants:
1. An OID is never reused while any reference to it may exist (dangling
   reference detection otherwise becomes impossible); deletion either
   cascades, nulls references, is forbidden while referenced, or leaves a
   tombstone for later detection.
2. Bidirectional relationships: inverse maintenance happens in the same
   transaction as the forward update (both or neither).
3. `SCOPE` restricts a REF to one table; without scope, deref needs a
   global OID → table resolution step.

---

## 3. Pointer swizzling

Converting stored OIDs into direct virtual-memory pointers when objects are
loaded, so navigation costs a pointer dereference instead of a hash lookup
in a resident-object table.

| Dimension | Options |
|---|---|
| When | **Eager** (swizzle all references in an object/page on load; may load transitively) vs **lazy** (swizzle on first dereference) |
| Target | **Direct** (pointer to the object) vs **indirect** (pointer to a descriptor/handle that points to the object; descriptor survives eviction) |
| Where | **In-place** (overwrite OID field in the buffered page) vs **copy** (objects copied into a separate object cache in language format) |
| Mechanism | **Software** checks (tag bit test on every dereference) vs **hardware/page-fault** (reserve virtual address ranges for not-yet-loaded pages; access-protection fault loads and swizzles the page — ObjectStore, Texas persistent store) |

Correctness invariants:
- No swizzled pointer is ever written to disk: unswizzle on write-back
  (copy approach avoids this by translating on copy-out).
- A direct swizzled pointer to an object pins its page/frame or the target
  must be unswizzled in all referrers before eviction — hence indirect
  swizzling or "one incoming swizzled pointer per page" restrictions.
- With page-fault swizzling, the address-space reservation must be
  consistent across all pointers to a page within a process; address space
  exhaustion is a real limit for large databases on 32-bit machines (the
  original motivation for many designs).

Performance lore (White & DeWitt 1992 and later): swizzling pays off only
when references are dereferenced repeatedly (navigation-heavy workloads
like CAD traversals); for scan- or query-heavy access the swizzling and
unswizzling overhead dominates.

> **Beyond EDBS:** LeanStore (Leis et al., ICDE 2018) brought swizzling to
> a general-purpose buffer manager: each page reference ("swip") is a
> tagged 64-bit word holding either a memory pointer (hot) or a page id
> (cold). Pages form a tree with exactly one parent swip, so eviction only
> has to unswizzle one place; a "cooling" FIFO stage gives replacement
> without per-access bookkeeping. Removes the hash-table page lookup that
> dominates in-memory B-tree traversal in classical buffer pools. See
> `dbms-architecture`.

---

## 4. Path expressions and complex-object query processing

`b.publishedBy.publisherName` (OQL) or `publishedBy->publisherName` (SQL)
is an **implicit (functional) join** along a reference.

### Evaluation strategies
| Strategy | How | Wins | Loses |
|---|---|---|---|
| Naive navigation | For each source object, dereference each reference immediately | Few sources, hot cache | Random I/O per reference (the "pointer chasing" disaster for large sets) |
| Translate to value join | Treat REF as a foreign key; let the optimizer choose hash/merge/INL join | Large sets; reuses relational machinery and join ordering | Loses the physical locality hint in physical OIDs |
| Pointer-based joins (Shekita & Carey 1990) | Partition/sort source tuples by the *target page* of their references, then fetch each target page once (pointer-based hash/sort join) | Large sets with physical OIDs: each target page read once | Needs physical OIDs or a cheap OID→page map |
| Assembly operator (Keller, Graefe, Maier 1991) | Build complex objects bottom-up using a sliding window of unresolved references sorted by disk address | Materializing whole object graphs (e.g., for an application cache) | Memory for the window |

### Path indexes
- **Nested index** (Bertino & Kim 1989): maps a value at the end of a path
  directly to the root objects (e.g., publisher name → books). Fast for the
  full path; updates in the middle of the path require recomputation.
- **Path index**: maps the end value to all OID tuples along the path —
  supports queries on any prefix-rooted subpath.
- **Multi-index**: one index per link; composes by joins.
- **Access support relations** (Kemper & Moerkotte 1990): materialized
  relations of OID paths (canonical / left-complete / right-complete / full
  extensions differ in whether partial paths with dangling ends are kept),
  decomposable into partitions to balance query vs update cost. These are
  the object-world ancestors of join indexes (Valduriez 1987) and of XML
  path indexes.

### Inheritance storage
| Mapping | Layout | Query over superclass extent | Query over leaf class | Update/insert |
|---|---|---|---|---|
| Horizontal (table per concrete class) | All attributes (inherited + own) in each class table | UNION ALL over subtree tables | One table | One table |
| Vertical (table per class, own attributes only, shared OID) | Joins to reassemble | One table for common attributes | k-way join along the hierarchy | k inserts |
| Single table with type discriminator | Superset of columns, NULLs | One scan | Scan + filter on type | One table; NULL-heavy, wide |

Polymorphic method calls (late binding) block optimizer reasoning: the
optimizer cannot inline, cost or push down a method whose implementation
depends on the runtime subtype — unless it partitions by type (subtable
by subtable) and binds statically per partition.

### Algebra
OQL and SQL with collections are compiled into algebras with nest/unnest,
map, and set/bag/list constructors (monoid comprehension calculus is a
clean basis); classical unnesting rewrites (decorrelating subqueries into
joins/outer joins plus grouping) carry over, but bag vs set vs list
semantics must be tracked per subexpression. Query processing phases are
the classical ones (parse/semantic check → logical rewrite using keys,
constraints and type information → cost-based physical optimization →
execution); what changes is the search space (path joins, method
placement, type-partitioned extents) and the cost model (method cost,
reference locality).

---

## 5. UDTs and UDFs in the optimizer (where extensibility bites)

### Type extensibility contract
A new type is usable in the engine only when it supplies:
- Storage: fixed or variable length, alignment, external/large-object
  handling (out-of-line storage for big values), send/receive
  (serialization) functions.
- Ordering and equality: comparison function consistent with equality;
  **hash function consistent with equality** (a == b ⇒ hash(a) == hash(b)),
  or hash joins/aggregation silently produce wrong answers.
- Operator classes for access methods (which operators an index can
  answer), plus **selectivity estimators** for restriction and join
  operators (e.g., PostgreSQL's `RESTRICT`/`JOIN` estimator functions on
  operators) and optionally statistics collection functions.
- Casts and their implicitness (affects overload resolution and index
  eligibility).

### Function extensibility contract
- **Volatility/determinism**: immutable (same inputs → same output,
  forever: constant-foldable, indexable, cacheable), stable (constant
  within a statement), volatile (re-evaluate every call: no folding, no
  reordering across it, no duplicate elimination of calls).
- **Side effects / SQL access** (NO SQL, READS SQL DATA, MODIFIES SQL
  DATA): restricts where calls may be moved or parallelized.
- **Cost and cardinality**: per-call CPU cost, returned rows for table
  functions; better: a callback that estimates selectivity/rows given
  argument values (PostgreSQL planner "support functions", Oracle
  extensible optimizer interfaces).
- **Null handling**: RETURNS NULL ON NULL INPUT lets the executor skip
  calls.
- **Isolation**: in-process (unfenced; fast, but a crash or memory
  corruption takes down the server) vs out-of-process/sandboxed (fenced,
  protected mode; IPC per call or per batch). Teradata protected vs
  unprotected UDF modes and DB2 FENCED/NOT FENCED are this trade-off.
- **Parallelism**: whether the function is safe to run in parallel workers
  and, for table functions, how input is partitioned (PARTITION BY / HASH
  BY / ORDER BY clauses of table operators).

### Expensive predicate placement
Classical heuristic "push selections down" is wrong when a predicate costs
more than the join it precedes (image analysis UDF vs cheap equi-join).
- Order independent filters on one input by ascending **rank =
  (selectivity − 1) / cost-per-tuple** — optimal for a sequence of
  independent filters.
- **Predicate migration** (Hellerstein & Stonebraker 1993): treat joins as
  filters with their own rank and let expensive predicates migrate up or
  down the join tree within each stream; extended to full cost-based
  enumeration by Chaudhuri & Shim (1996), which keeps plans with
  different pending predicates as distinct (they are not comparable by
  cost alone).
- **Function result caching**: memoize by argument values within a query
  when deterministic; duplicates in the argument column make
  placement-after-distinct attractive.

> **Beyond EDBS:** scalar UDF **inlining** — translating procedural UDF
> bodies into relational algebra (Froid, Ramachandra et al. VLDB 2018, in
> SQL Server 2019) — removes the per-row interpretation and makes UDFs
> visible to the optimizer (decorrelation, parallelism). SQL-language
> functions in PostgreSQL are inlined when simple enough. Vectorized UDF
> interfaces (batch-at-a-time, Arrow-based) amortize call overhead for
> external languages.

### Extensible access methods
- Generalized frameworks: **GiST** (Hellerstein, Naughton, Pfeffer 1995)
  — supply `consistent`, `union`, `penalty`, `picksplit` (and
  compress/decompress) to get a balanced search tree for any key domain
  (R-tree, RD-tree, …); later SP-GiST (space-partitioned trees) and GIN
  (inverted).
- Vendor interfaces: Informix DataBlades, Oracle Data Cartridges (domain
  indexes via ODCIIndex callbacks for create/insert/delete/scan, and
  ODCIStats for cost/selectivity), DB2 Extenders.
- Requirements the core must keep: the custom index participates in WAL
  and recovery (or is rebuilt on recovery and marked invalid until then),
  in concurrency control (predicate/range locking or MVCC visibility
  checks on heap), and in cost-based selection (via its stats callbacks).

---

## 6. Array databases (a case study in "type constructor, not type")

### Model
An array is a function from a finite axis-parallel box X ⊂ ℤ^d (its
**domain**) to a cell type F; arrays are bulk collections alongside sets,
bags and lists, not an emulation of them. Query languages are declarative
(no explicit iteration order, all cells conceptually at once) and safe
(always terminate). Two primitives suffice for a large class of operations
(Array Algebra, basis of rasdaman, OGC WCPS and ISO SQL/MDA):
- **Array constructor** over a domain with a position variable and a cell
  expression: subsetting (*trim* keeps dimensionality; *slice* drops a
  dimension), cell-wise arithmetic, "induced" (lifted) operators like
  `a / 2`, `a + b`, case expressions for classification.
- **Condenser/aggregate** over a domain with a commutative, associative
  combiner: sums, counts, min/max, quantifiers; combined with the
  constructor it expresses histograms, convolutions, statistics.
Expressive power of such array languages equals relational query
languages with ranking (Libkin, Machlin, Wong 1996).

### Why plain relational storage fails for dense arrays
`R(x, y, r, g, b)` stores coordinates explicitly (2–3× space), loses
n-D locality (a cutout along y touches tuples scattered across pages if
storage is x-major), and SQL cannot express imaging operations
conveniently; SS-DB measurements show array engines up to two orders of
magnitude faster. Exception: very **sparse** cubes, where storing only
non-null cells with coordinates *is* compression (ROLAP). BLOBs are no
better: opaque to the engine, and compression prevents computing cell
offsets without full decompression.

### Integration choices
| Choice | Systems | Pros | Cons |
|---|---|---|---|
| Array-as-attribute (an array column type in a table) | rasdaman, Teradata ARRAY/VARRAY, Oracle GeoRaster, PostGIS Raster, ISO SQL arrays/SQL-MDA | Millions of arrays per table; metadata in ordinary columns; schema stable under data growth | Needs array subtree evaluation inside the relational plan |
| Array-as-table (dimensions are key columns) | SciQL, SciDB | Familiar SQL syntax over cells | Each array is a schema object → catalog explosion with millions of arrays; schema changes on data ingest |

Arrays are **type constructors** (templates instantiated with
dimensionality, domain and cell type), not types; ORDB UDT mechanisms that
register one fixed type at a time end up limited (e.g., 2-D only,
fixed cell types, small size caps such as sub-64 KB arrays). Deep
integration (parser + dedicated array processor) gives better syntax and
optimization; UDF-based integration (SciDB operators as UDFs) is easier
but opaque to the optimizer. Nest/unnest operators convert between arrays
and tables.

### Storage
- Partition arrays into n-D **tiles/chunks** (the unit of I/O); tiling
  strategy determines how many tiles a query touches: regular tiling;
  **directional** tiling (edge-length ratios tuned for mixed workloads
  such as x/y time slices vs long time series); **area-of-interest**
  tiling (declared hot spots); SciDB two-level chunking and **overlapping
  chunks** (halo cells replicated so stencil/convolution operators avoid
  reading neighbors).
- A spatial index (R-tree) over tile bounding boxes resolves range
  queries; since tiles are boxes partitioning a known extent, almost any
  spatial index works well.
- Per-tile compression; hierarchical storage (tape) for petabyte archives;
  in-situ access to scientific file formats without import.

### Evaluation and optimization
- Relational set tree unchanged; array subexpressions in SELECT/WHERE are
  evaluated in **array subtrees** that stream tiles bottom-up (tile
  streaming); most array operators are non-blocking → tile-parallel and
  pipelined; blocking operators are natural cut points for shipping
  subplans to other cores/nodes/accelerators.
- Algebraic rewriting is effective (rasdaman applies on the order of 150
  rules), e.g., `avg(a + b) → avg(a) + avg(b)` for same-domain arrays,
  turning two tile streams plus a cell-wise add into two scalar
  aggregates.
- Array queries are typically **CPU-bound** (unlike I/O-bound SQL), so
  code shipping and vectorized/compiled cell kernels matter.

> **Beyond EDBS:** ISO SQL/MDA was published as ISO/IEC 9075-15 (2019).
> TileDB (Papadopoulos et al. VLDB 2016) handles dense and sparse arrays
> with immutable fragments (an LSM-like design) and is used for genomics;
> Zarr/HDF5 chunked formats on object storage dominate scientific
> pipelines; the ML push turns array engines toward tensor algebra and
> iterative computation with numerical termination criteria — still an open
> design problem for declarative safe iteration.

---

## 7. Review checklist
- Which equality (identity / shallow / deep) does DISTINCT, GROUP BY,
  UNION use on UDT and REF values? Is it documented and tested?
- Does every UDT used in hash joins have a hash function consistent with
  its equality, including collations and NaN/−0 edge cases?
- Are UDF volatility and cost declarations validated (e.g., an
  "immutable" UDF that reads a table makes index contents stale)?
- Does the optimizer have rank-based placement for expensive predicates,
  or does it blindly push them down?
- For references: physical or logical OIDs? What happens on object move,
  delete, and reorganization? Who detects dangling REFs?
- For arrays/large objects: what is the I/O unit, and does the tiling
  match the dominant access patterns?
- For extensible indexes: are they WAL-logged and crash-consistent, or
  rebuilt — and is that state visible to the planner?

Sources: Object Data Models (p.2525); Query Processing and Optimization in
Object Relational Databases (p.3032); Array Databases (p.165); XML Storage
(p.4796, object storage background); Semi-structured Data (p.3444).
