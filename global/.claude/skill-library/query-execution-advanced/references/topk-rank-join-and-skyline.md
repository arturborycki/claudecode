# Top-k processing, rank joins, preference and skyline queries

Scope: making the engine *rank-aware* instead of materialize-then-sort:
threshold algorithms over sorted/random access (FA, TA, NRA, CA), pipelined
rank-join operators (HRJN, J*, PBRJ), rank-relational algebra and rank-aware
optimization, rank-join indexes, top-k in ordinary SQL plans (LIMIT
pushdown, STOP AFTER, filter/restart), and preference queries: winnow and
skyline algorithms (BNL, SFS, LESS, divide and conquer, BBS).

---

## 1. Problem definitions

- **Top-k query:** return up to k answers with the highest score under a
  scoring function F; ties broken arbitrarily. Formally S ⊆ Q(D), |S| ≤ k,
  and no answer outside S scores strictly higher than an answer inside S.
- **Top-k selection / score aggregation:** objects have m attribute grades
  f₁(x)…f_m(x) (typically in [0,1]); overall score F(f₁(x), …, f_m(x)).
- **Top-k join:** `SELECT … FROM R1,…,Rn WHERE join-preds ORDER BY
  F(p1,…,pm) LIMIT k`, where the pᵢ are scoring predicates over the inputs.
- **Top-k aggregate:** `GROUP BY g ORDER BY agg LIMIT k` — the k groups with
  the highest aggregate.
- **Monotonicity** — the property everything rests on: F is monotone if
  xᵢ ≤ yᵢ for all i implies F(x) ≤ F(y). MIN (fuzzy conjunction), weighted
  sums with non-negative weights, averages are monotone; anything with a
  negative weight or a non-monotone transform (|x − c|) is not, unless the
  input is re-expressed (e.g., sort by distance to c).

Naive evaluation computes every answer's score and sorts; cost is
proportional to |Q(D)|, which rank-aware processing avoids by **early
termination** with a provable bound on unseen answers.

---

## 2. Threshold algorithms (Fagin and colleagues)

Access model (from middleware over subsystems, IBM Garlic): each attribute i
is a list Lᵢ sorted by descending grade. **Sorted access** reads the next
entry of Lᵢ (cheap, sequential, cost c_S); **random access** fetches the grade
of a given object in Lᵢ (cost c_R, often ≫ c_S).

### FA — Fagin's Algorithm (PODS 1996)

1. Sorted access in parallel to all m lists until at least k objects have
   been seen in *every* list.
2. Random access for every object seen so far to obtain missing grades.
3. Compute F for each seen object; return the k best.

Correct for monotone F; for independent random list orders it touches
O(N^((m−1)/m) · k^(1/m)) objects with high probability. Buffer is unbounded
(all seen objects).

### TA — Threshold Algorithm (Fagin, Lotem & Naor, PODS 2001 / JCSS 2003)

```
top = bounded min-heap of size k (by overall score)
loop (round-robin sorted access, depth d = 1, 2, …):
    for each list i:
        (x, g) = next sorted entry of L_i;  last[i] = g
        if x not seen: random-access x in all other lists; s = F(grades of x)
                       offer (x, s) to top
    tau = F(last[1], …, last[m])          # best possible score of any unseen object
    if |top| == k and min score in top >= tau: return top
```

- Correctness: any object not yet seen under sorted access has grade ≤
  last[i] in every list, so its score ≤ τ by monotonicity.
- Buffer bounded by k (plus a seen-set, which can be avoided by recomputation).
- **Instance optimal** over all correct algorithms that make no "wild guesses"
  (random access only to objects already seen under sorted access): for every
  database, its cost is within a constant factor of the best such algorithm's
  cost on *that* database, with optimality ratio m + m(m−1)·c_R/c_S.
- Stops much earlier than FA on correlated or skewed lists.

### NRA — No Random Access

For sources that allow only sorted access. For each seen object keep:
W(x) = F with missing grades replaced by the minimum (e.g., 0) — a lower
bound; B(x) = F with missing grade i replaced by last[i] — an upper bound.
Keep the k objects with the largest W as the candidate answer; stop when
every other object — including the virtual unseen object with bound
F(last[1..m]) — has B ≤ the k-th largest W. Output is the correct top-k
*set*, possibly without exact scores. Instance optimal among no-random-access
algorithms; bookkeeping (updating bounds of all candidates) is the CPU cost.

### Variants

- **CA (combined):** sorted access as in NRA plus a random access every
  ⌊c_R/c_S⌋ rounds for the most promising incomplete object; balances the two
  costs.
- **TA_Z:** some sources allow only random access.
- **Expensive predicates/probes:** Upper (Marian, Bruno & Gravano) chooses the
  next (object, attribute) probe adaptively from current bounds; MPro (Chang &
  Hwang, SIGMOD 2002) probes only *necessary* predicates in a fixed order;
  Güntzer et al. and Nepal & Ramakrishna refine TA's stopping tests.
- **Filter/restart:** translate the top-k request into a range selection with
  an estimated score cutoff (from histograms or probabilistic models:
  Chaudhuri & Gravano, VLDB 1999; Donjerkovic & Ramakrishnan, VLDB 1999), run
  it with ordinary operators, and **restart** with a lower cutoff if fewer
  than k results come back. Cheap to integrate, but a misestimate costs a
  re-execution.

Scoring functions in practice come from similarity measures (cosine, Jaccard,
Dice, overlap over term vectors; probabilistic relevance in IR) — all
monotone in their per-term contributions, which is why TA-style processing
over inverted lists (sorted by term weight) works for text ranking.

---

## 3. Rank-join operators

Rank join generalises score aggregation from one object to combinations of
joinable tuples. Requirements: each input delivered in descending order of its
scoring predicate (index scan or an upstream rank operator), F monotone.
Algorithms differ in how they **bound the score of unseen join results**.

### HRJN / HRJN* (Ilyas, Aref & Elmagarmid, VLDB 2003, VLDBJ 2004)

- Built on the symmetric hash join: a hash table per input; `next()` reads a
  tuple from one input, inserts it into that input's table, probes the other
  table, and pushes new join results into a **priority queue** ordered by
  score.
- **Threshold (corner bound)** for two inputs:
  `T = max(F(p1_top, p2_last), F(p1_last, p2_top))` where `_top` is the first
  (highest) score of each input and `_last` the last score read. Any join
  result not yet produced must use at least one unread tuple, so its score
  ≤ T.
- Emit the queue head while its score ≥ T; otherwise read more input.
- **HRJN\*** pulls adaptively instead of alternating: if
  F(p1_top, p2_last) is the larger term, read from input 2 (lowering p2_last)
  — the input whose depth currently dominates the bound.
- m-way: chain binary rank joins (each emits in score order, so it is a
  valid ranked input for the next) or generalise the bound to
  max_i F(top_1, …, last_i, …, top_m).
- Implements the standard iterator interface, so it composes with ordinary
  operators and can be placed anywhere a ranked input is available.

### J* (Natsev et al., VLDB 2001)

A* search over partial join combinations in a priority queue keyed by score
upper bound (actual scores for joined inputs, last-seen scores for the rest);
at each step extend the head combination with the next tuple from a chosen
input; report a combination when the head is complete.

### PBRJ and optimality (Schnaitter & Polyzotis, PODS 2008; Finger & Polyzotis, SIGMOD 2009)

- **Pull/Bound Rank Join** template: a *pulling strategy* (which input next)
  plus a *bounding scheme* (upper bound on unseen results). HRJN = round-robin
  pull + corner bound.
- Cost metric **sumDepths** = total tuples read from all inputs (proxy for
  I/O). Instance optimality: cost(A, I) ≤ c₁·cost(A′, I) + c₂ for all
  algorithms A′ in the class and all instances I.
- The corner bound is cheap but can be loose, so HRJN may keep reading after
  the top-k is already certified and is not instance optimal in general; a
  tight (feasible-region) bound restores instance optimality (computing it is
  NP-hard in general, tractable for limited query shapes) but costs more CPU
  per step. Finger & Polyzotis (FRPA) adaptively control how much work to
  spend on bounding, getting near-tight depths at modest CPU.

### Depth intuition for costing

With join selectivity s between two ranked inputs read to depth d each, about
s·d² join results exist among the read prefixes, so producing k results needs
d ≥ sqrt(k/s) per input, and certifying them (results ≥ T) needs more. Rank-
aware optimizers estimate depths with probabilistic or sampling-based models
because ordinary cardinality estimation does not capture "how far into the
input must we read".

---

## 4. Rank-relational algebra and rank-aware optimization (RankSQL)

Li, Chang, Ilyas & Song (SIGMOD 2005) treat ranking as a first-class logical
property alongside membership:

- A **rank relation** R_P is R whose tuples are ordered by the upper bound
  F_P, where already-evaluated predicates P take their actual values and the
  rest take their maximum possible value.
- **Rank operator** μ_p evaluates one more scoring predicate p and re-orders
  by the tightened bound.
- Selection, projection, join, union, intersection, difference are extended
  to consume and emit rank relations (binary operators output in the
  aggregate order of their inputs).
- **Splitting law:** a scoring function over p₁…p_n can be evaluated as a
  chain μ_p1(…μ_pn(R)…) — ranking in stages instead of a monolithic sort.
- **Interleaving laws:** μ commutes with σ and with ⋈ (when p references one
  input), so ranking can be pushed below joins and interleaved with filters.
- RankSQL's optimizer extends System R dynamic programming with the ranking
  property (plans are comparable only if they have evaluated the same set of
  ranking predicates) and estimates rank-join input cardinalities with
  sampling.

---

## 5. Rank-join indices (Tsaparas et al., ICDE 2003)

When relations and the join predicate are fixed but the (linear) scoring
function f(s₁, s₂) = p₁s₁ + p₂s₂ arrives at query time:

1. Materialise the join's score pairs; keep only **D_K**, tuples dominated by
   fewer than K others (anything dominated by ≥ K tuples can never be in a
   top-k answer for k ≤ K under any monotone f).
2. A preference vector e (unit length, angle a(e) in [0, π/2]) ranks tuples by
   projection onto e. Two tuples swap order exactly when e crosses the vector
   orthogonal to their difference (their *separating vector*), if that vector
   lies in the positive quadrant.
3. Sweep e from the x-axis to the y-axis; record the separating points where
   the top-K set changes (a swap between positions K and K+1). Each tuple can
   enter position K at most K times.
4. Index the separating angles in a B-tree; each leaf interval stores its
   top-K set. Query: compute a(e), look up the interval, return the first k.

Bounds: construction O(|D_K|² log |D_K|) time, O(|D_K|·K²) space, query
O(log |D_K| + k log k). Related precomputation approaches: the Onion
technique (convex layers; Chang et al., SIGMOD 2000) and PREFER (materialised
ranked views; Hristidis, Koudas & Papakonstantinou, SIGMOD 2001). Limits:
two relations, linear functions, static data.

---

## 6. Top-k inside an ordinary SQL engine

- **Top-N sort:** ORDER BY … LIMIT k uses a bounded heap (see
  `sort-aggregate-setops.md`); never full sort + cut.
- **LIMIT pushdown** is legal only through operators that neither filter nor
  duplicate rows and preserve the order needed: projections; UNION ALL
  (push the ORDER BY … LIMIT k into each branch, keep the outer one); a left
  outer join
  whose right side matches at most one row per left row (unique key) and
  whose ORDER BY uses only left columns. Not through inner joins, filters,
  or aggregations.
- **STOP AFTER** (Carey & Kossmann, SIGMOD 1997): an explicit stop operator
  the optimizer can place aggressively (deep in the plan, with a restart if
  too few rows survive) or conservatively (where no rows can be lost).
- **Index-driven top-k:** an index on the ORDER BY expression plus a
  pipelined plan (index NLJ) returns the first k without reading the rest;
  for a top-k join choose a rank-join when ranked access paths exist on both
  inputs.
- **Top-k per group:** `ROW_NUMBER() OVER (PARTITION BY g ORDER BY s) <= k`
  → per-partition bounded heaps (see `window-operators.md`).
- **Ties:** `FETCH FIRST k ROWS WITH TIES` (SQL:2008) must include all rows
  tied with the k-th; plain LIMIT is non-deterministic under ties — tests must
  compare score multisets, not row identities.
- **Top-k aggregates:** exact answers usually need all groups aggregated; with
  sorted access to per-group partial scores, TA/NRA-style bounds can prune
  groups, but the common implementation is full aggregation + top-N heap.

---

## 7. Preference queries and winnow

A preference query returns only the *best* answers under a user preference.
Chomicki's **winnow** operator (also called BMO, "best matches only", in
Kießling's Preference SQL and Best in Torlone & Ciaccia) over a preference
relation ≻:

ω_≻(r) = { t ∈ r | there is no t′ ∈ r with t′ ≻ t }

- Winnow tuples need not dominate anything; they are merely undominated.
- Semantically a self anti-join; expressible in relational algebra and
  non-monotone like set difference.
- **Skyline = winnow under Pareto dominance.** Hence skyline algorithms (BNL,
  SFS) evaluate winnow for any preference relation that is a **strict partial
  order** (irreflexive and transitive) — check this before reusing them for
  user-defined preferences.
- **Algebraic laws** hold conditionally. Selection σ_C commutes with winnow iff
  for all t₁, t₂: C(t₂) ∧ t₁ ≻ t₂ ⇒ C(t₁) (a preferred tuple of a selected
  tuple must also be selected). Example: with "same make, lower price is
  better", σ_{price<20K} commutes with winnow but σ_{price>20K} does not.
- **Semantic optimization:** winnow is redundant (returns its input) under
  integrity constraints implying that no two tuples are comparable — drop it.
- Language support: Preference SQL `PREFERRING LOWEST(price)` with
  `CASCADE` for prioritised composition and Pareto accumulation (Kießling &
  Köstler, VLDB 2002); FlexPref provides an extensible API for preference
  operators inside the engine (Levandoski et al., TODS 2013); PrefDB scores
  tuples with (condition, scoring function, confidence) preferences (Arvanitis
  & Koutrika, TKDE 2014) — scores cannot express Pareto dominance.
- Decoupled preferences: **regret-minimising sets** return a small set such
  that every user with an unknown linear utility gets at least x% of their
  best utility (Nanongkai et al., VLDB 2010); size bounded independently of
  the database.

---

## 8. Skyline algorithms

Point p **dominates** q (p ≺ q) if p is at least as good in every dimension
and strictly better in at least one. Skyline = points not dominated by any
other. Facts: the maximum of any monotone utility (e.g., positive linear
weights) lies in the skyline; skyline size for d independent dimensions is
about (ln n)^(d−1)/(d−1)! (Bentley et al., 1978) — tiny for correlated data,
huge for anti-correlated data and large d.

| Algorithm | Idea | Cost / properties |
|---|---|---|
| Nested-loop anti-join (`NOT EXISTS (… dominates …)`) | Pure SQL fallback | O(n²) comparisons; fine only for small inputs |
| BNL — block nested loops (Börzsönyi, Kossmann & Stocker, ICDE 2001) | Keep a memory window of mutually incomparable points; each input point is dropped if dominated by a window point, evicts window points it dominates, and enters the window (or a temp file when the window is full). Timestamps decide which window points have been compared with everything: they are output after a pass; the temp file is the next pass's input | Best when the skyline fits in memory; worst case O(n²); not progressive in general |
| Divide and conquer (Kung, Luccio & Preparata, JACM 1975) | Split on the median of one dimension, compute skylines of halves recursively, remove points of the worse half dominated by the better half's skyline | O(n log n) for d = 2, 3; O(n·log^(d−2) n) for d ≥ 4; not progressive |
| SFS — sort-filter-skyline (Chomicki, Godfrey, Gryz & Liang, ICDE 2003) | Presort by a monotone score (e.g., entropy Σ ln(1+xᵢ) or sum); if p dominates q then score(p) < score(q), so no later point can dominate an earlier one. Window holds only skyline points; every point that survives the window is final | Progressive; window never holds false candidates; sort cost up front |
| LESS (Godfrey, Shipley & Gryz, VLDB 2005) | SFS with an elimination-filter window applied during the sort's run generation | Discards most dominated points before they are written |
| Bitmap, Index (Tan, Eng & Ooi, VLDB 2001); Nearest-neighbour (Kossmann, Ramsak & Rost, VLDB 2002) | Bit-sliced dominance tests; NN search partitions space recursively | Progressive |
| BBS — branch and bound skyline (Papadias, Tao, Fu & Seeger, SIGMOD 2003) | R*-tree; min-heap of entries keyed by mindist to the origin; pop entry; prune if dominated by a found skyline point; expand nodes; a popped data point not dominated is a skyline point | Progressive and I/O-optimal (visits only nodes that may contain skyline points) |

Engine notes:

- **Strict monotone sort key** for SFS: with sum, ties between a dominating
  and dominated point are impossible (strictly better in one dimension raises
  the sum) but ties among incomparable points are fine.
- **Direction normalisation:** convert MAX dimensions to MIN (negate or
  reverse) once, in the operator's input projection, so dominance code has
  one direction.
- **NULLs and categorical dimensions:** define dominance for missing values
  explicitly (incomplete data breaks transitivity); categorical attributes
  with per-user partial orders need stratified evaluation (Chan, Eng & Tan,
  SIGMOD 2005).
- **Parallel/distributed:** local skylines per partition, then a global
  skyline over their union (any global skyline point is a local skyline point
  of its partition).
- **Output reduction:** k-representative skylines — k skyline points that
  dominate the most points (Lin et al., ICDE 2007) or that are mutually far
  apart (Tao et al., ICDE 2009).

---

## 9. Tests

- Brute-force oracles: O(n²) dominance check for skyline/winnow; full
  materialise-and-sort for top-k and rank join. Compare score multisets (ties).
- Distributions: independent, correlated, anti-correlated (skyline blow-up),
  duplicate points (identical vectors are mutually non-dominating; all belong
  to the skyline if undominated).
- TA/NRA: lists with ties at the threshold, k > number of objects, monotone
  but non-strict F (MIN), random-access failures.
- Rank join: inputs with equal scores, join keys with no matches early in the
  inputs (deep reads), one input exhausted before the threshold drops.
- Early termination: assert the operator read strictly fewer tuples than the
  input size on favourable distributions (performance invariant), and that
  `close()` releases hash tables and queues when the parent stops after k.
- Algebra rewrites: property-test that σ/winnow commutation fires only when
  the commutation condition holds (random preferences, random predicates).

Sources: EDBS entries Top-k Queries (p.4168), Score Aggregation (p.3324),
Rank-Aware Query Processing (p.3080), Rank-Join (p.3093), Rank-Join Indices
(p.3096), Preference Queries (p.2784), Skyline Queries and Pareto Optimality
(p.3508), Similarity and Ranking Operations (p.3495).
