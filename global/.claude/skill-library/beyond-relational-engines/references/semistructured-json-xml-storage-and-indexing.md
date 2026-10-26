# Semi-structured data: JSON/XML storage, structural encodings, indexes, XQuery processors

Read this when designing or reviewing how a relational (or native) engine
stores, labels, indexes and queries tree-shaped data: shredding vs native
storage, Dewey/ORDPATH/region encodings, path and value indexes, structural
joins and holistic twig joins, the three XQuery processor architectures,
and the modern JSON-in-RDBMS techniques that descend from them.

---

## 1. Data model facts that drive the engine

- **Semi-structured** = labeled trees (sometimes graphs via ids/references),
  self-describing (labels stored with the data), schema optional and
  tolerant. Origins: OEM/Lore (Stanford) and UnQL (Penn) in the mid-1990s,
  then XML; JSON is the dominant successor.
- **XML (XDM)**: ordered, node-labeled tree; node kinds (document, element,
  attribute, text, comment, PI, namespace); **stable node identity**;
  **document order** is part of the semantics (XPath results come back in
  document order, duplicate-free); optional typing via DTD/XML Schema; mixed
  content (text interleaved with elements). Exact round-tripping may require
  whitespace, attribute order, namespace prefixes, entity references.
- **JSON**: objects (unordered key → value, duplicate keys ill-defined),
  ordered arrays, scalars (string, number, true/false, null); no node
  identity, no attributes, no mixed content. Arrays introduce *multi-valued
  paths*, which is where index and predicate semantics get subtle.
- Three distinct absences an engine must keep apart: key missing, key
  present with JSON null, key present with empty array/object. SQL NULL
  collapses them unless the API is careful.
- Tree models subsume relational rows (flat object) and nested relations; a
  DTD/XSD or JSON Schema is a regular tree grammar, so validation is tree
  automaton membership.

---

## 2. Storage design space

| Approach | How | Wins | Costs |
|---|---|---|---|
| Text/CLOB | Serialized document as a large string | Exact fidelity, cheap insert | Every query reparses; no indexing beyond full text |
| Binary blob of the whole document | Pre-parsed tree in one LOB | No reparsing; fidelity | Update rewrites the LOB; whole-document I/O for a small fragment |
| **Native paginated tree** (Natix, DB2 pureXML) | Partition the tree into subtrees smaller than a page; each partition a record; proxy/aux nodes link partitions; large text and long child lists chunked | Local navigation within a page; subtree reconstruction without loading everything; supports fine-grained update, locking, logging | New storage manager code (record layout, node ids, split algorithm); bulk analytic queries need indexes |
| **Generic edge/node table** (schema-oblivious) | `node(id, parent, kind, tag, value, order…)` or edge table, with a structural label | Any document, no schema needed; reuses relational engine | Many self-joins; subtree reconstruction expensive unless the label is range-based and clustered |
| **Schema-driven shredding** | Map element types to tables using the DTD/XSD (inlining); FK to parent + order column | Relational-style queries over regular data are fast; column statistics meaningful | Mapping explosion for irregular schemas; recursion and choice types awkward; reconstruction requires outer-union/sorted outer joins |
| **Cost-based mapping** (LegoDB-style) | Search over schema transformations (inline/outline, split unions, merge types), cost each with the RDBMS optimizer on a workload | Better than any fixed rule set | Large search space; needs statistics on structure and values |
| **Hybrid** | Regular parts shredded, irregular subtrees kept native or serialized; possibly redundant copies | Best of both for mixed documents | Needs a declarative storage description and query rewriting using views (MARS/XAM-style) to keep physical data independence |

### Shredding mechanics (inlining)
- A child that occurs at most once per parent (`?` or exactly one) is
  **inlined** as columns of the parent's table.
- A child that can repeat (`*`, `+`) becomes its own table with a foreign
  key to the parent and an **ordinal** column for sibling order.
- Recursive types and elements reachable from several parents get their own
  tables (basic/shared/hybrid inlining in Shanmugasundaram et al. 1999 vary
  how aggressively shared types are inlined).
- Choice/union types: either one table with nullable columns or
  partitioned tables per alternative.
- Physical design that works well empirically: B-trees (range predicates
  appear in translated structural conditions), **index-organized tables
  clustered on the order/label column** so index scans return document
  order, and a path index over root-to-node paths.

### Correctness of a mapping
- **Lossless**: original documents reconstructible from the relational
  instance (needs order and parent info).
- **Validating**: every legal relational instance corresponds to a valid
  document. Most published mappings are lossless but not validating; add
  constraints so updates through the relational side cannot produce
  invalid XML. Both properties are undecidable for general mapping
  languages, so constructions guarantee them by design rather than by
  checking.

---

## 3. Structural labeling (the core trick)

Goal: each XPath axis between two nodes becomes a cheap predicate on their
labels, so structure can be tested without navigation.

### Region / interval encodings
Assign `start` (pre-order rank) and `end` (post-order rank, or a second
counter on exit) in one DFS; store `level` (and often parent's start).

| Axis (u → v) | Predicate |
|---|---|
| v descendant of u | `u.start < v.start AND v.end < u.end` (equivalently `v.start ≤ u.end` with interval end) |
| v child of u | descendant AND `v.level = u.level + 1` (or `v.parentStart = u.start`) |
| v following of u | `v.start > u.end` |
| v preceding of u | `v.end < u.start` |
| v following-sibling of u | following AND same parent |
| v ancestor of u | inverse of descendant |

Variants: `(pre, post, level)` — the **XPath accelerator** plane, where
each axis is a rectangular region of the pre/post plane (Grust 2002); `(pre,
size, level)` with `post` derived; Timber's `⟨doc, start, end, level⟩`.
Because axis regions are 2-D/3-D ranges, any B-tree on `pre` plus range
predicates, or an R-tree on `(pre, post, ...)`, answers axis steps.

**Staircase join** (Grust, van Keulen, Teubner 2003): an axis step from a
*set* of context nodes, evaluated by one pass over the pre-sorted node
table. Prune context nodes whose regions are covered by others (for
descendant, a context node inside another context node's subtree adds
nothing), then scan each remaining region once, skipping provably empty
ranges. Output is duplicate-free and in document order without a sort —
which a naive per-context-node B-tree probe does not give you.

### Prefix encodings
- **Dewey**: label = parent's label + local sibling ordinal (`1.6.7.8`).
  Descendant = proper prefix; child = prefix plus exactly one component;
  document order = lexicographic order on component sequences;
  lowest common ancestor = longest common prefix (very useful for keyword
  search and twig joins).
- Cost: label length grows with depth; compare and store as variable-length
  byte strings with order-preserving component encoding (so `memcmp` order =
  document order), and prefix-compress in B-tree leaves.
- **ORDPATH** (O'Neil et al. 2004, used by SQL Server's hierarchy
  support): Dewey-like, but initial labels use only odd ordinals; an insert
  between two siblings uses an even "caret" component followed by odd ones,
  so **no existing label changes on insertion**. Components are prefix-free
  variable-length bit strings so labels compare by bit string.
- **Extended Dewey** (TJFast): encode tag names into the ordinals given a
  schema, so a leaf's label alone reveals its root-to-leaf tag path.

### Update handling
Region encodings with dense numbers must relabel on insert (O(n) worst
case). Remedies: leave gaps, use floating-point or rational labels (gap
exhaustion still possible), relabel lazily in bulk, or use insert-friendly
prefix schemes (ORDPATH). Trade-off: insert-friendly labels are longer and
slower to compare; region labels are compact and give O(1) ancestry tests.

---

## 4. Indexes for tree data

Twig (tree-pattern) queries are the core of XPath/XQuery; an index answers
a *fragment* of the twig, and query processing stitches fragment matches.

### Node indexes
Inverted list per tag name / attribute name / value → sorted list of node
labels. Sorted-by-start lists are exactly the input format structural joins
need.

### Edge/axis indexes
Precomputing (label1, label2, axis) → pairs is quadratic for descendant /
following axes; positional labels (above) replace it with predicates.

### Path indexes
A unifying framework (Chen et al. 2007): represent every path as a 4-tuple
`(HeadId, SchemaPath, LeafValue, IdList)` — start node, dictionary-encoded
tag sequence, leaf value if the path ends at text, ids along the path. An
index chooses (i) which schema paths to store (length-1, root-to-node
prefixes, all subpaths), (ii) which part of IdList to return (last id, first
id, full list), (iii) which columns form the search key (often the
**reversed** SchemaPath so that `//a/b/c` becomes a prefix lookup on
`c/b/a`).

| Index | Paths stored | Returns | Key |
|---|---|---|---|
| Value / forward-link (Lore) | length 1 | last id | (path, value) / (head, path) |
| DataGuide | root-to-node prefixes | last id | schema path |
| Index Fabric | root-to-leaf | first or last id | reversed path + value |
| ROOTPATHS | root-to-node prefixes | full IdList | value + reversed path |
| DATAPATHS | all subpaths | full IdList | value + head + reversed path — answers "matches of this path rooted at node n" in one B+-tree probe |

**Structural summaries.** A *strong DataGuide* lists every distinct label
path exactly once (a deterministic automaton over the data; for tree data
its size is bounded by the number of nodes, for graph data determinization
can blow up exponentially). The **1-index** groups nodes by
(backward) bisimulation — nodes with the same set of incoming label paths
— and is exact for all path queries; **A(k)-indexes** use k-bisimilarity,
exact for paths up to length k and smaller. Summaries also feed
cardinality estimation and query formulation.

### Twig indexes
Encode each document as a sequence (ViST: structure-encoded sequences;
PRIX: Prüfer sequences) and reduce twig matching to (non-contiguous)
subsequence matching, with post-filtering for false positives.

### Industrial example (DB2 pureXML)
An XML index is declared by an XPath pattern (wildcards, `//`, kind tests)
and a target SQL type. Implementation: (1) a path dictionary/B+-tree
mapping distinct **reverse paths** to path ids, and (2) a value B+-tree of
`(path id, typed value, node id, row id)` entries for every node matching
the pattern. Index eligibility for a query predicate is decided by an XPath
**containment** test between the query path and the index pattern; type
mismatches (string index, numeric predicate) make the index ineligible —
values that fail to cast are simply not indexed, so the index must never be
used to answer a predicate whose semantics include those nodes.

---

## 5. Structural joins and twig joins

### Binary structural join
Input: list A of candidate ancestors and list D of candidate descendants,
each sorted by `start`; output: all (a, d) with a an ancestor (or parent)
of d.

**Stack-Tree-Desc** (Al-Khalifa et al. 2002):
```
stack := []
merge A and D in start order:
  next := node with smaller start (ties: A first)
  pop from stack every a with a.end < next.start       // regions closed
  if next ∈ A: push next                                // stack = nested chain
  else (next ∈ D): for each a in stack: emit (a, next)  // all are ancestors
```
Stack holds a chain of nested ancestors, so each emitted pair is correct
and every pair is found. Cost O(|A| + |D| + |output|) time, O(depth) space;
output sorted by descendant. **Stack-Tree-Anc** produces ancestor order by
buffering per-stack-entry self/inherit lists. For parent-child, check
`level` before emitting. Earlier MPMGJN (multi-predicate merge join) could
re-scan descendant lists and is not linear in the worst case.

Structural joins compose: a twig with k nodes is k−1 binary structural
joins; **join order** matters enormously (intermediate results may be
large even when the final result is tiny), so native optimizers enumerate
orders with dynamic programming fed by **position histograms** (2-D
histograms over (start, end) that bound structural-join cardinalities).

### Holistic twig join (TwigStack, Bruno, Koudas, Srivastava 2002)
Process all twig nodes at once, one sorted stream per query node, one
stack per query node with pointers from each stack entry to its parent
query node's stack entry (compactly encoding partial matches).

```
while not end(root stream):
  q := getNext(root)        // returns a query node whose current stream
                            // head has, in every child subtwig, a
                            // descendant extension (recursively)
  if q ≠ root: clean parent stack; else clean own stack (pop closed regions)
  if q is root or parent stack non-empty:
     clean stack(q); push head(q) with pointer to top of parent stack
     advance stream(q)
     if q is a leaf: emit all root-to-leaf path solutions encoded by stacks
  else advance stream(q)
merge path solutions on common prefixes → twig matches
```
- For twigs with only ancestor-descendant edges, every path solution
  emitted participates in some final answer: I/O and CPU are
  O(input + output) — optimal, independent of intermediate sizes.
- With **parent-child edges** TwigStack can emit path solutions that later
  fail to merge; no algorithm reading sorted streams with bounded memory is
  optimal for arbitrary PC/AD mixes. Successors: TwigStackList (look-ahead
  buffers for PC edges), TJFast (extended Dewey: read only leaf streams;
  ancestors are derived from labels), index-assisted skipping
  (XB-trees).

### Navigation vs joins
Native engines often evaluate selective paths by **navigation** (XNAV-like
operators traversing parent/child pointers in the paginated store, many
XPath branches at once) and fall back to label-based structural joins over
inverted lists for unselective `//` steps. Cost-based choice between them
is the XML analogue of index-nested-loop vs merge join.

---

## 6. XQuery processor architectures

| Architecture | Exemplar | Storage | Plan language | Key techniques |
|---|---|---|---|---|
| **Purely relational** | Pathfinder (MonetDB/XQuery; SQL:1999 back-end) | Any node-level encoding preserving identity and order (pre/size/level, ORDPATH) | Relational algebra, emitted as SQL or MIL | **Loop lifting**: compile each subexpression to a table `(iter, pos, item)` holding its results for *all* iterations of enclosing `for` loops at once, so the back-end runs set-at-a-time; order kept in `pos` (via `DENSE_RANK`-style numbering); staircase join for axes; plan simplification from inferred keys/dependencies and order indifference |
| **Native** | Timber | Nodes stored in start-key order with ⟨doc, start, end, level⟩ labels | TLC / TAX tree algebra over sets/sequences of ordered labeled trees (select, project, join, group, construct, flatten, shadow/illuminate) | Pattern-tree matching reduces heterogeneous trees to homogeneous bulk sets; physical layer works on *nodes*, so explicit **node materialization** operator; stack-based structural joins; DP join ordering with position histograms |
| **Hybrid relational + native** | DB2 pureXML ("System RX") | XML column type storing pre-parsed, type-annotated XDM trees in paginated native format, alongside relational columns | Extended Query Graph Model; XQuery not translated to SQL; a navigational XPath is **one operator** rather than nested FLWOR blocks | XNAV multi-path navigation over the native store, XML path/value indexes chosen by containment, schema-per-document flexibility (no static typing so schema evolution never invalidates plans), SQL/XML integration |
| In-memory native | Saxon | Tree in memory | Expression tree with rewrites | Completeness/conformance; streaming for subsets |

Design lessons:
- The **logical/physical gap** is larger than in relational engines:
  logical operators manipulate trees, physical operators manipulate node
  ids. Deciding *when* to materialize subtrees is a first-class optimizer
  decision (late materialization of trees).
- Sequence order and node identity must be preserved through every
  rewrite: a join reordering that is valid relationally may change output
  order; set-based duplicate elimination must use node identity, not value.
- Static typing helps pruning (Pathfinder infers types to avoid
  polymorphic columns) but hurts schema evolution (DB2 deliberately does
  not use it for compilation).
- Text and uncertainty extensions (TIX scoring algebra; ProTDB
  probabilistic XML with child probabilities conditioned on the parent)
  show the algebra must carry annotations through operators — the same
  pattern as provenance (`provenance.md`).

---

## 7. JSON in relational engines

> **Beyond EDBS:** what production engines do today.
> - **Binary decomposed documents.** PostgreSQL `jsonb` stores a parsed
>   binary tree: object keys deduplicated and sorted (by length then bytes),
>   with an offset/length header per container so a key lookup is a binary
>   search, not a reparse. `json` (text) preserves formatting and duplicate
>   keys; `jsonb` does not. Oracle OSON and MongoDB BSON are analogous
>   binary formats (BSON keeps key order and is optimized for traversal,
>   not lookup).
> - **Indexes.** Expression B-trees on extracted paths (`(doc->>'sku')`);
>   inverted indexes over all keys/values (PostgreSQL GIN `jsonb_ops`) or
>   over hashes of full path+value pairs (`jsonb_path_ops`: smaller, only
>   supports containment). Multikey semantics: an array-valued path yields
>   one index entry per element; MongoDB forbids compound indexes over two
>   array-valued fields because the cross product would explode.
> - **SQL/JSON.** SQL:2016 added `JSON_VALUE`, `JSON_QUERY`,
>   `JSON_EXISTS`, `JSON_TABLE` (the shredding operator: JSON → relational
>   rows, with nested paths producing outer-joined row sets) and the
>   SQL/JSON path language with lax vs strict modes (lax auto-unwraps arrays
>   and suppresses structural errors); SQL:2023 added a JSON data type.
> - **Columnar shredding of nested data.** Dremel (2010) and Parquet store
>   each leaf path as a column with **repetition levels** (at which repeated
>   ancestor a new value starts a new list entry) and **definition levels**
>   (how many optional/repeated ancestors are actually present — encodes
>   missing vs null), allowing lossless record reassembly from columns.
> - **Automatic sub-columnarization.** Snowflake's VARIANT extracts
>   frequently occurring paths into typed hidden columns per micro-partition
>   with min/max metadata for pruning; Sinew (2014) materializes "virtual
>   columns" for common keys in an RDBMS; JSON Tiles (SIGMOD 2021) detects
>   per-block frequent structures and stores them columnar with
>   statistics. The relational optimizer then sees real columns and real
>   statistics.
> - Cardinality estimation for JSON predicates is usually naive (fixed
>   selectivities); path-level statistics (per-path NDV, null/missing
>   fractions, array length histograms) are the obvious gap — see
>   `cardinality-and-statistics`.

### Choosing a JSON storage strategy (engine view)
| Workload | Choice |
|---|---|
| Store and return whole documents; rare predicates | Binary document column + a few expression indexes |
| Ad-hoc predicates on many paths, containment queries | Binary column + inverted (GIN-like) index |
| Analytics over a stable core of fields | Promote hot paths to typed columns (manual or automatic sub-columnarization); keep remainder as binary |
| Deep nesting, columnar engine | Dremel-style repetition/definition levels |
| Fine-grained updates to large documents | Native paginated tree or document split into per-subtree rows; avoid whole-LOB rewrite |

---

## 8. Pitfalls and tests
- Document order: any operator that reorders (hash join, parallel
  exchange) must re-establish order before serialization or the plan must
  prove order indifference (`unordered{}` / aggregates).
- Duplicate elimination by node identity, not by deep equality.
- Label overflow / gap exhaustion under adversarial insert patterns
  (always inserting before the first child) — test it.
- Index eligibility: a value index typed as `DOUBLE` must not answer a
  string comparison; lax/strict path semantics must match between index
  and query.
- Missing vs null vs empty array in predicates and indexes (`IS NULL` on a
  path vs key-exists operator).
- Oracles: compare relational/indexed plans against a straightforward
  in-memory DOM evaluator (or Saxon for XQuery) on random documents and
  random XPath/twig queries; property: for every axis, label predicate ⇔
  navigational definition on random trees with random inserts.

Sources: Semi-structured Data (p.3444); XML Storage (p.4796); XML Indexing
(p.4749); XQuery Processors (p.4846); Document Databases (p.1237);
NoSQL Stores (p.2513).
