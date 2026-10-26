# Windows, window aggregation and joins, punctuations, heartbeats, watermarks, disorder

Read this when you are implementing a windowed operator (aggregate, join,
top-k), choosing between re-evaluation and incremental maintenance, sharing
windows across queries, or deciding how the engine learns that "time has
passed" when input is out of order.

---

## 1. Window taxonomy

Window kinds are orthogonal axes that combine freely:

| Axis | Values | Notes |
|---|---|---|
| Extent measure | count (rows), time, value (ascending attribute), predicate | Value windows are time windows over a user attribute that must be ascending (or made so) |
| Movement | tumbling (slide = range, each tuple in exactly one window), hopping/sliding (slide < range, tuple in ⌈range/slide⌉ windows), landmark (fixed start, growing end), per-tuple sliding (slide = 1 tuple / 1 tick) | landmark = running aggregate since an epoch |
| Scope | stream-based (window defined once on the stream, shared) vs. operation-based (window is a parameter of one operator, e.g., join window) | stream-based windows allow sharing |
| Partitioning | global vs. partitioned (`PARTITION BY k ROWS N`) | partitioned count windows need per-key FIFOs |
| Content filter | top-k / bottom-k (KEEP LARGEST), sampled (SAMPLE x%), interpolated (RESAMPLE) | top-k windows are not FIFO; need heap + expiry |
| Data-driven | session (gap-based, merging), predicate windows (membership defined by a condition, with insert/update/delete tuples) | session windows merge when a tuple bridges two gaps |

> **Beyond EDBS:** Session windows (per-key activity periods closed by an
> inactivity gap) became a first-class kind in the Dataflow model (Akidau et
> al., VLDB 2015), with *window merging* as a core operation: each tuple
> starts a proto-window `[t, t+gap)` and overlapping proto-windows of the same
> key merge. Merging means window state must be mergeable (associative
> partial aggregates) and window identity is not known until the watermark
> passes.

Predicate windows (EDBS "Window-Based Query Processing") hold the tuples that
currently satisfy a condition, e.g., rooms hotter than a threshold. A tuple
enters with an insert, changes with an update (revision) tuple, and leaves
with a delete. This makes a predicate window a materialized view over the
stream and links stream processing to IVM (`materialized-views-ivm`).

### 1.1 Window identity (WID) and assignment

Li, Maier, Tufte, Papadimos, Tucker (SIGMOD 2005), in the Punctuations reading
list, separate *window assignment* from *window evaluation*. Each window
gets an id. A tuple maps to the set of ids whose extent contains it. State is
keyed by (group key, window id). A window is finished when a
punctuation/watermark guarantees no more tuples for that id.

For a hopping time window with range r, slide s, and origin 0:
```
ids(t) = { k : k·s ≤ t < k·s + r }  =  [ ⌊(t − r)/s⌋ + 1 , ⌊t/s⌋ ]
close window k when watermark ≥ k·s + r      (end-exclusive)
```
This makes out-of-order input correct by construction. A late tuple is simply
routed to its (still open) window id. No sort-before-window is needed.

---

## 2. Evaluation strategies

**Re-evaluation.** Treat each window instance as a table and rerun the query on
it when it closes or slides. Operator semantics stay purely relational.
Overlapping windows (s < r) mean each tuple is processed r/s times, so cost is
O(r/s) per tuple per query.

**Incremental evaluation.** Treat the result as a materialized view. Process
only the delta: arrivals (+) and expirations (−). Report only result changes.
The mechanics are in `stream-semantics-and-cql.md` §3 (I/D streams,
positive/negative tuples, revision tuples, timestamp-driven expiry).

| Strategy | Wins when | Cost / risk |
|---|---|---|
| Re-evaluate per window | tumbling windows; holistic aggregates; tiny windows | redundant work with overlap |
| Invertible incremental (add/subtract) | SUM/COUNT/AVG, sliding by 1 | float cancellation drift; not for MIN/MAX |
| Partial aggregates per slice (panes/pairs) | many overlapping windows; distributive/algebraic aggregates | slice bookkeeping; holistic aggregates need mergeable sketches |
| Aggregation tree / two-stacks | non-invertible associative ops (MIN/MAX/argmax) over FIFO windows | O(log n) per update (tree) or amortized O(1) with O(n) spikes (two-stacks) |
| Negative tuples end to end | strict non-monotone plans (difference, distinct, nested aggregates) | 2× traffic; every operator needs a minus rule |

### 2.1 Slicing: panes and pairs (aggregation sharing)

> **Beyond EDBS (the bundle does not cover these, but they are standard):**
> *Panes* (Li, Maier, Tufte, Papadimos, Tucker, SIGMOD Record 2005, "No pane,
> no gain") cut the stream into non-overlapping slices of length
> `g = gcd(r, s)`. Each pane keeps one partial aggregate. A window answer is the
> combination of its `r/g` pane partials. Per-tuple cost drops from O(r/s) to
> O(1) plus O(r/g) per window emission. *Pairs* (Krishnamurthy, Wu, Franklin,
> SIGMOD 2006) avoid the gcd blow-up when r and s are nearly coprime. Each
> slide period is cut into at most two slices, of lengths `s − (r mod s)` and
> `r mod s`, so the number of slices per slide is ≤ 2 regardless of gcd. For
> **many queries with different (r, s)** over the same stream, take the union
> of all queries' slice edges. Every query's window is then a union of shared
> slices ("shared slicing"; generalized by Cutty, Carbone et al. CIKM 2016,
> and Scotty, Traub et al. ICDE 2018, which also handles out-of-order input
> and session windows).

Algorithm (shared slicing, distributive/algebraic aggregate `⊕` with partial
state type P):
```
on tuple t (event time ts):
    slice = slice_containing(ts)          # slice index from merged edge set
    P[slice] = P[slice] ⊕ lift(t)
on watermark w:
    for each query q, each window id k of q with end_k ≤ w:
        emit lower( ⊕_{slice ⊆ window_k} P[slice] )   # combine partials
    evict slices older than max over queries of (w − r_q)
```
Combining a window's slices can itself be shared with a two-stacks or FlatFAT
structure over the slice sequence (below). Holistic aggregates (median,
count-distinct) fit only if P is a mergeable sketch (q-digest, KLL, HLL; see
`stream-synopses.md`).

### 2.2 Non-invertible sliding aggregation

> **Beyond EDBS:** For associative but non-invertible `⊕` (MIN, MAX, argmax,
> bloom-OR, matrix product) over FIFO windows:
> - *Two-stacks*: a back stack holds the running aggregate of pushes. A front
>   stack holds suffix aggregates. Query = `agg(front.top) ⊕ agg(back)`.
>   Evict pops the front. When the front is empty, flip the back into the
>   front, recomputing suffixes. This is amortized O(1) with an O(n) worst
>   case on the flip. DABA (Tangwongsan, Hirzel, Schneider, DEBS 2017)
>   de-amortizes to worst-case O(1).
> - *FlatFAT* (Tangwongsan et al., VLDB 2015): a complete binary tree in an
>   array over a circular buffer. Update and query cost O(log n). It supports
>   non-FIFO updates (needed for out-of-order slices).
> - *Subtract-on-evict* for SUM over floats accumulates rounding error without
>   bound over long runs. Periodically recompute, or use compensated
>   summation, or use slices (bounded-length recomputation).

### 2.3 Spark-style incremental windows

Spark Streaming's incremental sliding aggregation keeps window state and
applies the newest micro-batch with `⊕` and the expired batch with an inverse
`⊖`. Each batch touches the window state twice instead of once per window it
belongs to. It requires an invertible aggregate. It is the micro-batch
analogue of negative tuples.

---

## 3. Window joins

The workhorse is the **symmetric (pipelined) hash join** over two windows.
For an arrival `s` on S with timestamp `ts`:
```
1. purge from W_R every r with r.ts < ts − |W_R|        (time windows)
2. probe H_R with s.key, emit (r, s) for matches
3. insert s into H_S (and the expiry structure of W_S)
```
Count windows replace step 1 with "if |W_R| > N, evict oldest". Each SteM in an
eddy (`scheduling-load-shedding-adaptivity.md` §5) is exactly one half of this
operator.

Correctness invariants:
1. **Inputs must be processed in global timestamp order** (or the join must
   tolerate disorder). If `s` with ts=100 is processed before `r` with ts=95
   arrives, then step 1 for later tuples may already have purged state that
   `r` should have matched, or `r` may match tuples it should not. Merge the
   inputs by timestamp using heartbeats/watermarks, or defer purging until the
   watermark (purge `r` only when `wm > r.ts + |W_R|`: a later S tuple still
   sees `r` inside R's window until then).
2. **Each result is produced exactly once.** The newer tuple of the pair
   produces it at its arrival. A probe must not match entries that arrive
   later in the same instant twice. Use a sequence-number rule.
3. **Result expiry is known at creation.** For `(r, s)` it is
   `min(r.exp, s.exp)` (weak non-monotonic, `stream-semantics-and-cql.md`
   §1.2), so downstream operators can expire join results by timestamp
   without negative tuples.

Variants and choices:
- *Asymmetric*: each direction may use a different structure (hash, tree,
  nested loop) based on rates and window sizes (Kang, Naughton, Viglas,
  ICDE 2003, in the Load Shedding reading list). The cost model is per unit
  time, split into the two probe directions.
- *Multi-way window joins*: a left-deep binary tree materializes
  intermediate windows. Alternatives are an n-ary symmetric join (MJoin
  style, no intermediate state, per-arrival probe order chosen adaptively) or
  an eddy with SteMs.
- *Band/temporal joins*: `|r.ts − s.ts| ≤ δ` with no key. Use a time-ordered
  buffer and range scan.

### 3.1 Sharing window joins across queries

Two queries with the same join predicate and windows `w_J < w_K` over the
same streams. J's results are a subset of K's (a pair within w_J is within
w_K, but not conversely). Hammad et al. (VLDB 2003) compare policies:

| Policy | How | Win | Lose |
|---|---|---|---|
| Largest-window-only | run the join with `w_K`, route outputs to both queries, filter J's by `|r.ts − s.ts| ≤ w_J` | simple; each arrival processed once | small-window queries wait for the big join; poor latency for J |
| Smallest-window-first | each arrival probes the smallest window region first (results go to all queries), then extends to larger windows | best latency for small windows | per-tuple progress bookkeeping (which window ring it has reached) |
| Hybrid/optimized | schedule window rings by output rate | balance | complexity |

**Selection pull-up** (NiagaraCQ): with many queries that differ only in
selections over a shared join, pushing selections below the join prevents
sharing it. Pull selections above the shared join, or split the shared state
so that each query's selection is a filter on the join output. This reverses
the classic push-down heuristic. The optimizer needs a multi-query cost model
(`query-optimizer` boundary).

---

## 4. Punctuations

**Definition.** A punctuation is a marker embedded in a stream. It denotes a
subset of the stream's domain and asserts that *no later item in this stream
belongs to that subset*. A stream that honours all its punctuations is
*grammatical*. The usual form is a tuple of per-attribute patterns: wildcard
`*`, literal, list `{a,b}`, range `[lo,hi]`. An item matches if every
attribute matches its pattern. Example: `<{105,106}, *, [0,100], *>` over
bids `<auction, bidder, price, ts>` says no more bids for auctions 105 or 106
with price in [0,100] will arrive.

**What they buy.** (1) They *unblock* blocking operators: an aggregate can
emit a group, and a sort can emit a prefix. (2) They *purge* state that can
no longer matter. (3) They bound disorder and define window closure.

A punctuation-aware operator defines three behaviours (Tucker, Maier, Sheard,
Fegaras, TKDE 2003):
- **pass**: which results can be emitted now;
- **keep**: which state must be retained (the complement is purged);
- **propagate**: which punctuations can be emitted downstream.

| Operator | pass | keep (purge rule) | propagate |
|---|---|---|---|
| select σ | always immediate | stateless | pass punctuation through |
| project π | immediate | stateless | punctuation projected; only if dropped attributes are `*` in it (otherwise the projected claim is too strong) |
| duplicate elim | immediate first occurrence | purge seen-values covered by a punctuation | as received |
| group-by/aggregate γ_G | emit group g once a punctuation covers all of g (patterns on G subsume g, others `*`) | drop g's state after emitting | punctuations restricted to G |
| join R ⋈_A S | immediate (pipelined) | punctuation on S covering A=v ⇒ purge R tuples with A=v (no future S partner); future R tuples with A=v join stored S tuples and are not stored | punctuation on A once both inputs have punctuated v |
| union | immediate | none | emit p only when *both* inputs have punctuated it (intersection of claims) |
| difference R − S | emit r only when S has punctuated r's value (absence is now certain) | purge S values covered by an R punctuation | from R, after S has caught up |
| sort | emit the prefix below the punctuated bound | pop emitted prefix | ordered bound |

**Faithfulness.** A stream operator s is *faithful* to its relational
counterpart r if, for every finite prefix x of the input, s's output on x is
consistent with r's output on every finite extension of x. In other words, s
never emits something a later input could invalidate. Use this as the
property test (§7). Pair it with an eagerness check: s should emit everything
the punctuations already permit, so a correct-but-stuck operator also fails.

**Punctuation schemes.** Which punctuations a source *can* produce determines
which queries become unblockable and state-bounded (Tucker et al., TKDE
2007). Example: with punctuations only on `auction_id`, a `GROUP BY bidder`
never unblocks. The planner should reject or warn on plans where a blocking
operator's keys are not covered by any available punctuation scheme.

---

## 5. Heartbeats, watermarks, and time progress

A **heartbeat** is a punctuation on the timestamp attribute: "no more items
with ts < h from this source". Gigascope and Srivastava–Widom (PODS 2004,
"Flexible time management in data stream systems") introduced them to order
out-of-order input and unblock operators. If a source cannot emit heartbeats,
the DSMS synthesizes them from environmental bounds (max network delay,
clock skew).

Granularity:
- *Query-level heartbeat*: `h_q = min_i h(s_i)` over all input streams.
  Release buffered tuples with ts < h_q. This is simple, but one stalled
  stream blocks the whole query.
- *Operator-level heartbeat*: each operator tracks min over *its* inputs.
  Tuples can flow through parts of the plan whose inputs are ready. This gives
  lower latency and memory at the cost of per-operator bookkeeping.

**Watermark = heartbeat generalized to dataflow.** Each operator's output
watermark is `min(input watermarks)` (adjusted for any timestamp
transformation it applies), and it must be monotone non-decreasing.

> **Beyond EDBS:** MillWheel (Akidau et al., VLDB 2013; cited in the bundle)
> defines a *low watermark* per computation: the min of the oldest pending
> work at the computation and the low watermarks of upstream computations.
> Late data (ts < watermark) is the application's problem. Dataflow/Beam adds
> *allowed lateness*, *triggers* (on watermark, early/speculative firings,
> late firings) and *accumulation modes*. Flink propagates watermarks per
> input channel and takes the min. A source partition with no data holds back
> the global watermark forever unless it is marked *idle*. That is a classic
> production stall. Watermarks are *heuristic* when generated by bounded
> out-of-orderness at the source (`max_ts_seen − δ`) and *perfect* only when
> the source can guarantee order (e.g., per-partition log offsets with
> in-order event time).

Punctuation vs. watermark: a watermark is a punctuation whose pattern is
`ts ≤ w` with every other attribute `*`. General punctuations are strictly more
expressive. They can close one auction or one key while others stay open,
which is what makes per-key state purgeable without waiting for global time.

---

## 6. Out-of-order (disordered) input

Disorder comes from multiplexed sources, network paths, partition merges
after data-parallel regions, and replica failover. Options:

| Technique | Mechanism | Latency | Memory | Correctness |
|---|---|---|---|---|
| Sort buffer (k-slack / bounded delay) | hold tuples until `ts < max_seen − δ` (or heartbeat), release in order | +δ | O(rate·δ) | tuples later than δ dropped or sent to side output |
| Out-of-order processing with WIDs | route by window id, close windows on watermark (§1.1) | close delay only | open windows' partials | exact if watermark is exact |
| Revision tuples (Borealis) | emit early answers; when a late tuple arrives, emit a revision of affected window outputs | lowest | must retain window state (upstream revision) or old outputs (downstream revision) | eventually exact |
| Speculative + retraction (Dataflow) | early firings, then retracting updates | lowest | as above | eventually exact; consumers must handle retractions |
| Arrival constraints | exploit known disorder bounds ("k-constraints": STREAM characterized memory needs under bounded arrival patterns) | low | bounded by k | exact if constraint holds; must detect violations |

Order-sensitive operators (count windows, "last N", running sequence
patterns) cannot be made disorder-tolerant by WIDs alone. They need an
explicit order (sort buffer) or a total sequence number assigned at a single
point.

Merging after data parallelism: when an operator is split into replicas
(fission), output order is lost. Re-establish it with per-tuple sequence
numbers assigned at the split and an ordered merge (min-heap over replica
heads gated by per-replica progress). Without per-replica progress
(heartbeat), the merge cannot advance past an idle replica.

---

## 7. Testing windows and punctuations

- **Oracle: re-evaluation.** For every window instance, materialize its
  tuples and run the relational query. Compare with the incremental operator's
  output for that window id. This catches slicing and edge bugs.
- **Disorder invariance.** Permute input within the declared disorder bound
  δ (and with correct heartbeats). The output multiset per window must not
  change. Tuples beyond δ must go to the late path deterministically.
- **Faithfulness property.** Feed random prefixes. Every emitted result must
  appear in the output of the relational operator on every random extension
  (sample a few extensions).
- **State boundedness.** With a punctuation scheme that covers the blocking
  keys, operator state size must stay bounded over a 10^8-tuple run. Assert a
  high-water mark.
- **Window edge cases.** Tuples exactly at `k·s`, `k·s + r`; equal timestamps
  across inputs; empty windows (does the aggregate emit 0, NULL or nothing?
  choose and test); r not a multiple of s; s > r (gapped windows: tuples
  belonging to no window).
- **Join expiry.** Generate pairs straddling `|r.ts − s.ts| = W`. Check the
  inclusive/exclusive convention on both inputs.
- **Watermark idleness.** Start one partition idle. The pipeline must make
  progress (idleness timeout) or deliberately stall, per configuration.

Sources: EDBS "Window-Based Query Processing" (p.4695), "Punctuations"
(p.2943), "Stream-Oriented Query Languages and Operators" (p.3802), "Big
Stream Systems" (p.273), "Stream Models" (p.3768), "Data Stream Management
Architectures and Prototypes" (p.854), "Adaptive Stream Processing" (p.63),
"Publish/Subscribe Over Streams" (p.2937, for NiagaraCQ sharing).
