# Distributed query processing, optimization and semijoin programs

How a query over global relations becomes an executable multi-site plan:
localization against fragment definitions, global (inter-site) optimization
with a communication-aware cost model, distributed join strategies, semijoin
and Bloom reduction, full reducers for acyclic queries, and the three
reference optimizers (SDD-1, Distributed INGRES, R*).

---

## 1. Layered pipeline

```
SQL on global relations
  │ 1. decomposition       (parse, normalize, unnest, simplify; no distribution)
  ▼
algebra on global relations
  │ 2. data localization   (substitute fragment reconstruction; reduce)     ← uses fragment schema
  ▼
algebra on fragments ("fragment query")
  │ 3. global optimization (join order + shape, join sites, transfer method,  ← uses fragment stats,
  │                         semijoin/Bloom reducers, replica choice)            network model
  ▼
distributed plan with send/receive operators
  │ 4. local optimization  (access paths, local join algorithms, at each site) ← uses local catalog
  ▼
execution
```

Steps 1–3 run at the control (coordinator) site; step 4 runs at each site
holding fragments. Global optimization usually ignores local access paths and
lets sites choose them (R* "master/apprentice" split). The boundary matters
for testing: localization must be testable without statistics, and global
optimization must be testable with synthetic fragment statistics.

## 2. Data localization and reduction

Substitute each global relation by its reconstruction expression (union of
horizontal fragments, key-join of vertical fragments, the fragmentation tree
for hybrids), push operators down, then delete subexpressions that are
provably empty or redundant. Reduction reasons only over **fragment
predicates and query predicates**, never over data.

**Horizontal, selection.** σ_q(Ri) = ∅ if q ∧ p_i is unsatisfiable, where p_i
is Ri's fragment predicate. Example: R1 = σ_{A<100}, R2 = σ_{100≤A≤200},
R3 = σ_{A>200}; σ_{A>150}(R) localizes to σ_{A>150}(R2) ∪ R3 (the R3 selection
is implied and can be dropped too).

**Horizontal, join.** Distribute ⋈ over ∪: (∪Ri) ⋈ (∪Sj) = ∪_{i,j}(Ri ⋈ Sj),
then drop Ri ⋈ Sj when p_i ∧ p_j ∧ join-predicate is unsatisfiable. For range
fragments on the join attribute this is interval overlap; the surviving pairs
form the **fragment join graph**. If the graph is a perfect matching (each
fragment joins exactly one partner — the DHF case, or co-partitioned range/
hash), the join is fully local. If it is complete bipartite, distributing the
join gained nothing and the optimizer should instead consider reconstructing
one side or repartitioning.

**Derived fragmentation.** Si = S ⋉ Ri, so Ri ⋈ Sj = ∅ for i ≠ j by
construction — prune without predicate reasoning (record the DHF link in the
catalog so the rule can fire).

**Vertical.** π_{K,B'}(Ri) is useless if B' ∩ attrs(Ri) = ∅ (only the key
would be read). A query touching attributes of one vertical fragment reads
only that fragment and skips the reconstruction join. Note this produces a
*redundant*, not empty, subexpression.

**Hybrid.** Apply both: drop horizontal branches by predicate contradiction,
then drop vertical leaves by attribute coverage.

Engineering notes:
- Implement satisfiability for conjunctions of `attr θ const` with interval
  and set arithmetic per attribute (plus NULL handling); fall back to "may be
  non-empty" for anything else. Unsound pruning (dropping a non-empty
  fragment) is a correctness bug; incomplete pruning is only a performance bug.
- Parameterized queries: prune at bind time, not compile time, or keep a
  pruning program in the plan (run-time partition pruning).
- The reconstruction union is a bag union over disjoint fragments; if
  fragments overlap (replicas mistakenly treated as fragments) the union
  double counts.

## 3. Cost models

**Total cost** (resource consumption, throughput-oriented):
```
C_total = C_cpu·#instr + C_io·#ios + C_comm
C_comm  = (C_send_msg + C_recv_msg)·#msgs + C_byte·#bytes
```
Communication is assumed linear in bytes with a fixed per-message cost. In a
WAN the comm term dominates (SDD-1 used it alone); in a LAN/cluster local
processing is comparable and must be included (R*). Costs are better read as
resource units (money) than time, because the total ignores overlap.

**Response time** (latency-oriented): sum along the critical path, max over
parallel branches. For R at site 1, S at site 2, query at site 3 that ships
both to site 3:
```
total    = 2·T_msg + T_byte·(size(R) + size(S))
response = max(T_msg + T_byte·size(R),  T_msg + T_byte·size(S))
```
Response-time optimization prefers bushy trees and plans that overlap
transfers; total-cost optimization prefers fewer bytes. Distributed INGRES
optimized a weighted combination. Make the objective explicit in the
optimizer interface; mixing them implicitly yields plans that are neither.

**Plan shape.** Centralized optimizers often restrict to left-deep trees;
distributed optimizers must consider **bushy** trees because sibling subtrees
at different sites run in parallel. Search: DP over subsets (R*), greedy hill
climbing (SDD-1), randomized (simulated annealing / iterative improvement) for
large queries.

**Static vs dynamic.** Static: optimize at compile time with estimated
intermediate sizes (R*, SDD-1). Dynamic: decide each step at run time with
actual sizes (Distributed INGRES). Middle grounds: compile several plans and
choose at start-up; compile a plan and defer site allocation; **query
scrambling** (Urhan, Franklin, Amsaleg SIGMOD 1998) reschedules or
re-materializes parts of the plan when a remote source stalls.

**Autonomy.** Global optimization needs local cost parameters and selectivities
that autonomous sites may not export. Options: calibrate with probe queries,
learn from execution feedback, or delegate via an economic protocol — Mariposa
brokers solicit bids from sites against a budget that decreases with
response time.

## 4. Join strategies between two sites

R at site 1, S at site 2, join R.A = S.C. Choose (a) join site (R's, S's, or
the result site), (b) transfer method, (c) local algorithm.

| Strategy | Bytes moved | Messages | Notes |
|---|---|---|---|
| Ship whole S to site 1 | size(S) (+ result if needed elsewhere) | 1–2 (row-blocked: size/blocksize) | shipped relation can be stored and indexed temporarily; best when join selectivity is high |
| Fetch matches (fetch-as-needed): scan R, request S tuples per distinct A value | card(π_A R)·w_A + card(S ⋉ R)·w_S | ≈ 2 × distinct A values in R | few bytes, many round trips; sort/dedupe R on A first; the bind join is this strategy against a wrapper that only accepts parameterized selections |
| Semijoin: ship π_A(R) once, return S ⋉ R | size(π_A R) + size(S ⋉ R) | 2 (+blocking) | wins iff S ⋉ R is much smaller than S |
| Bloom (hash-filter) join: ship bit vector of h(A) | m bits + size(S ⋉~ R) (with false positives) | 2 | cheapest reducer; false positives filtered at site 1 |
| Ship both to a third site | size(R)+size(S) | 2 | when the result site is elsewhere and both are small |

Worked example (own numbers). |R| = 10,000 rows × 200 B at site 1, |S| =
50,000 × 100 B at site 2, 8-byte join key, FK R.A → S.C so the join has
10,000 rows; result wanted at site 1.
- Ship S to site 1: 5.0 MB.
- Ship R to site 2, ship 10,000 × 300 B result back: 2.0 + 3.0 = 5.0 MB.
- Semijoin: π_A(R) 10,000 × 8 B = 80 KB; S ⋉ R = 10,000 × 100 B = 1.0 MB;
  total ≈ 1.08 MB in two bulk messages.
- Bloom with 10 bits/key (12.5 KB, k = 7, false-positive rate ≈ 0.8 %): S'
  ≈ 10,000 + 0.008 × 40,000 ≈ 10,320 rows ≈ 1.03 MB; total ≈ 1.05 MB.
- Fetch matches without blocking: same ≈ 1.08 MB but ~20,000 messages; with
  per-message latency 0.5 ms that alone is 10 s.
Lesson: bytes and messages are separate axes; row blocking and batching
(send keys in blocks) turn fetch-matches into a sequence of small semijoins.

Execution-side join operators for unreliable/remote inputs:
- **Pipelined vs materialized**: shipping the outer of a nested-loop or the
  probe side of a hash join can pipeline; shipping the build side or a
  sort-merge input materializes.
- **Symmetric (double-pipelined) hash join**: build a hash table per input,
  insert each arriving tuple into its own table and probe the other; produces
  results as soon as matches exist on both sides, immune to one slow source.
- **XJoin** (Urhan & Franklin 2000): symmetric hash join that spills hash
  partitions to disk under memory pressure and uses idle time (both sources
  stalled) to join disk-resident with memory-resident partitions; needs
  timestamps/bookkeeping to avoid emitting duplicates across phases.

R* join methods (Selinger & Adiba 1980; validated by Mackert & Lohman SIGMOD
1986) for outer R at site 1, inner S at site 2: (1) ship outer to the inner
site and pipeline into a local join there; (2) ship inner to the outer site,
store it (temporary relation, optionally indexed), then join; (3) fetch inner
tuples as needed per outer value; (4) ship both to a third site. Mackert and
Lohman found hash-filter (Bloom) joins beat plain semijoins in most cases;
semijoins only won when the inner fit in buffer.

## 5. Semijoin algebra

R ⋉_{A=C} S = π_{attrs(R)}(R ⋈_{A=C} S). Properties: **reducing**
(R ⋉ S ⊆ R) and **asymmetric**. Join identities used to insert reducers:
```
R ⋈ S = (R ⋉ S) ⋈ S = R ⋈ (S ⋉ R) = (R ⋉ S) ⋈ (S ⋉ R)
```
Semijoin vs ship-whole of S (S smaller, communication only):
semijoin better iff size(π_A R) + size(S ⋉ R) < size(S), i.e. iff
card(S ⋉ R) is enough smaller than card(S) to pay for shipping π_A(R).

Selectivity estimate (Hevner & Yao 1979 style, uniformity + containment):
SF(S ⋉_C R) ≈ card(π_A R) / card(dom(C)) (the fraction of C's domain present
in R); card(S ⋉ R) ≈ SF · card(S). Treat it as a cardinality-estimation problem with all the
usual correlation pitfalls (see cardinality-and-statistics).

**Bloom filter reducer.** Insert each distinct A of R into an m-bit filter
with k hash functions; S tuples whose C hashes to all-ones bits are shipped.
False-positive rate for n keys: (1 − e^{−kn/m})^k, minimized at
k = (m/n)·ln 2, giving ≈ 0.6185^{m/n} (≈ 1 % at 9.6 bits/key). False
positives cost bytes, never correctness, because site 1 performs the real
join. Design choices: size the filter from the *estimated distinct count*
(not row count), cap it, and fall back to no filter if it would be saturated;
register-blocked or cache-line-blocked filters keep probe cost low.
(The EDBS entry describes k independent bit vectors ANDed together; the
standard single-array Bloom filter is equivalent in intent and more
space-efficient.)

Other uses of semijoin reduction: bind joins against capability-limited
wrappers; star-join processing in warehouses (semijoin each dimension with
a fact-table index, intersect row-id sets, then fetch facts).

## 6. Semijoin programs and full reducers

A **reducer** for R in query Q is a semijoin program whose result can replace
R without changing Q's answer. A **full reducer** removes every tuple that
does not participate in the final answer, for every database instance.

**Query hypergraph**: vertices = attributes, hyperedges = relations (natural
joins). An **ear** is a hyperedge E with a witness F such that every vertex
of E shared with any other hyperedge is contained in F. The informal test
"E has a vertex that occurs in no other edge" is not sufficient by itself: a
relation on a cycle that also carries a private attribute has such a vertex
but is not an ear, because its shared vertices are spread over two different
edges. **GYO reduction**: repeatedly delete vertices that occur in
exactly one hyperedge and hyperedges contained in another; Q is
**(α-)acyclic** iff this reduces the hypergraph to empty (Fagin JACM 1983;
Graham; Yu & Özsoyoğlu). Acyclic ⇔ a **join tree** exists (relations as
nodes, and for every attribute the nodes containing it form a connected
subtree).

Examples: R(A,B), S(A,C), U(C,D) is acyclic (chain R–S–U). R(A,B), S(A,C),
T(C,B) is cyclic (triangle; no ear).

**Full reducer for acyclic (tree) queries** (Bernstein & Chiu JACM 1981;
Yannakakis VLDB 1981):
```
root the join tree at any node
pass 1 (bottom-up, post-order):  for each node N with parent P:  P := P ⋉ N
pass 2 (top-down,  pre-order):   for each node N with parent P:  N := N ⋉ P
```
2(n−1) semijoins for n relations. After pass 1 the root is fully reduced;
after pass 2 every relation is. Joining the fully reduced relations along the
tree never produces a dangling intermediate tuple, so intermediate results are
bounded by the output size (Yannakakis: O(input + output) up to log factors
for the joins).

**Cyclic queries** have no full reducer that is a fixed semijoin program
independent of the instance; reduction requires iterating semijoins around
the cycle to a fixpoint, and the number of rounds depends on the data (in the
triangle example the iteration can shrink R to empty only after several
rounds). Practical options: break the cycle by joining two relations first
(the result covers the cycle's attributes) and reduce the remaining tree, or
apply a bounded number of reduction rounds as a heuristic.

Why full reduction is rarely used verbatim: each semijoin ships a projection,
so 2(n−1) shipped projections can exceed the bytes saved; the semijoin with
low reduction power is pure overhead. Choose reducers by benefit/cost and
integrate the choice into join enumeration (Stocker, Kossmann, Braumandl,
Kemper ICDE 2001) rather than running reduction as a separate phase.

## 7. The reference optimizers

**SDD-1** (Bernstein, Goodman, Wong, Reeve, Rothnie TODS 1981; built on
Wong's 1977 hill-climbing): objective = total communication; no fragmentation
or replication; static.
```
initial strategy: ship every needed relation to one site (all local processing)
repeat:
    for each candidate semijoin  Ri ⋉_A Rj  (different sites):
        cost    = C_msg + C_byte · size(π_A Rj)
        benefit = (1 − SF(Rj.A)) · size(Ri) · C_byte
    pick the semijoin with max (benefit − cost) > 0; apply it to the size estimates
until no beneficial semijoin remains
assembly site := site holding the most data after reductions
post-optimize: drop semijoins that reduce relations already stored at the assembly site
ship reduced relations to the assembly site and join there
```
Greedy, local optimum; estimates degrade with each applied semijoin because
SF assumes independence.

**Distributed INGRES** (Epstein, Stonebraker, Wong SIGMOD 1978): supports
horizontal fragmentation; dynamic; objective a weighted mix of total time and
response time; assumes a broadcast-capable network. Decomposes the query into
one-variable subqueries (detachment) and, for multi-relation steps, uses
**fragment-and-replicate**: keep one relation fragmented where it lies and
replicate (broadcast) the others to all sites holding its fragments, choosing
which relation stays fragmented to minimize cost; each step's actual output
size feeds the next decision.

**R\*** (Selinger & Adiba 1980; Lohman et al.): exhaustive System-R DP
extended with join site and transfer method (ship whole vs fetch matches) as
plan properties; objective = total cost including local CPU/IO and
communication; static; no fragmentation or replication in the implementation.
Intersite decisions at the master site, local access paths at apprentice
sites. Mackert & Lohman showed the local cost terms cannot be dropped on a
fast LAN.

## 8. Execution mechanics

- **Send/receive (exchange) operators** at site boundaries; the plan fragment
  per site is a normal local plan rooted at a send.
- **Row blocking**: batch tuples per message; tune block size to bandwidth-
  delay product. Without it, per-tuple latency dominates everything above.
- **Result caching / cache investment** (Kossmann, Franklin, Drasch TODS
  2000): caching remote results requires describing cached chunks
  semantically (predicate descriptors) so containment can be checked, and
  costing cache population against future benefit.
- **Data / query / hybrid shipping**: data shipping exploits client CPU and
  avoids server hot spots; query shipping avoids moving large inputs; hybrid
  lets the optimizer place each operator (Franklin, Jonsson, Kossmann 1996).

## 9. Spatial semijoins (filter-and-refine across sites)

Projecting on the join attribute does not shrink spatial data (the polygon
*is* the attribute) and exact predicates are expensive, so distributed spatial
joins ship **approximations**:
- R-tree based: site R ships MBRs from leaf level (many, precise) or level 1
  (few, coarse); site S runs window queries and returns candidate polygons;
  site R refines with exact geometry. Leaf-level MBRs ship more but return
  fewer false candidates — choose by average polygon size of S.
- Space-filling-curve based (Orenstein's z-order): each object approximated by
  a few z-cells; ship sorted cell keys; merge-join on cell *containment*
  (prefix), deduplicate object pairs, return candidates, refine. Tan, Ooi,
  Abel (TKDE 2000) found it usually beat the R-tree method on response time.
- Non-cooperating sources that only answer window/count queries: the client
  recursively requests per-cell counts on a grid, prunes cells empty on either
  side, and stops refining when expected pruning gain is below the statistics
  cost; then joins per cell (hash-based if counts are similar, index-nested
  loop via window queries if very skewed) (Mamoulis et al. SSTD 2003).
- Distributed index structures (SD-Rtree, du Mouza, Litwin, Rigaux ICDE 2007):
  clients cache a possibly stale *image* of routing nodes and contact data
  servers directly; a mis-addressed server forwards and returns an image
  adjustment — the same pattern as stale-route correction in range-sharded
  KV stores.

> **Beyond EDBS:** Semijoin reduction returned in MPP and lakehouse engines
> as *runtime filters*: the hash-join build side produces a Bloom or min/max
> filter that is pushed to the probe-side scan, possibly on other nodes
> (Impala runtime filters, Spark dynamic partition pruning, Trino dynamic
> filtering). Lookahead information passing (Zhu et al. VLDB 2017) and
> Predicate Transfer (Yang et al. CIDR 2024) generalize this toward
> Yannakakis-style multi-relation pre-filtering with Bloom filters passed
> along a join graph, trading exactness for cheap transfer. The classical
> analysis still governs whether a filter pays: build cost + transfer of the
> filter vs bytes eliminated on the probe side. When a filter's observed
> selectivity is poor, disable it adaptively at run time.

Sources: Distributed Query Processing (p.1206); Distributed Query Optimization
(p.1201); Distributed Join (p.1191); Semijoin (p.3436); Semijoin Program
(p.3440); Distributed Spatial Databases (p.1215); Distributed DBMS (p.1177).
