---
name: stream-processing-engines
description: "Use when designing, implementing or reviewing a data stream management system or a streaming operator: continuous-query semantics, windows, watermarks and punctuations, out-of-order data, window joins and aggregation sharing, operator scheduling, load shedding, adaptive routing, streaming fault tolerance and exactly-once, stream synopses, CEP pattern matching, or pub/sub matching. Triggers on DSMS, CQL, ISTREAM/DSTREAM/RSTREAM, tumbling/sliding/session window, panes, watermark, heartbeat, punctuation, late data, retraction, negative tuple, symmetric hash join, Chain scheduling, load shedding, eddies, upstream backup, checkpoint barrier, exactly-once, reservoir sampling, Count-Min, SpaceSaving, GK quantiles, MATCH_RECOGNIZE, NFA, publish/subscribe. Apply even when phrased as 'make this Flink/Kafka job correct after failover', 'why are my window results wrong', or 'keep latency bounded during bursts'."
---

# Stream Processing Engines

This skill owns the engine where queries stay resident and data flows past them. It covers the
stream data model, continuous-query semantics, windowed state, time progress, runtime scheduling
and overload control, streaming recovery, and the synopses and automata that make unbounded input
tractable. The single most important idea: **every stateful streaming operator is correct only
relative to an explicit contract for time progress.** Watermarks, heartbeats or punctuations say
when a window or key is complete and which state may be purged. Without that contract, results
come out wrong, are never emitted, or sit in unbounded state.

## Mental model

- A stream is an append-only sequence whose arrival order the engine does not control. Each item
  has an *event* timestamp (from the source) and an *arrival* timestamp (from the engine).
  Determinism, replay and replica agreement all require semantics defined on event time.
- CQL is the reference semantics. Windows turn streams into time-varying relations (S2R), plain
  SQL runs on those relations (R2R), and Istream/Dstream/Rstream turn relations back into streams
  (R2S). Non-monotone queries need retractions: Istream+Dstream, negative tuples or revision tuples.
- The runtime is a push dataflow. Operators are connected by bounded queues. A scheduler picks
  who runs, a queue manager bounds memory, and runtime optimizers (load shedder, adaptive
  re-optimizer) consume live statistics. Storage stays off the critical path (inbound processing).
- Windows bound state and punctuations/watermarks purge it. Where exact state cannot be bounded,
  a synopsis with explicit (ε, δ) replaces it.
- Recovery = replication + deterministic replay. Exactly-once has two parts: *state* (consistent
  snapshot + replay) and *delivery* (idempotent or transactional sinks).

## Core invariants

1. **Watermark monotonicity.** Each operator's output watermark never decreases and is ≤ the min
   of its input watermarks, adjusted for any timestamp transformation the operator applies.
2. **No final emission ahead of time.** A window, group or negation result is final only once the
   watermark or a covering punctuation has passed its end. Anything emitted earlier is marked
   tentative and corrected by retraction.
3. **Faithfulness.** On any finite input prefix, a streaming operator's output is consistent with
   its relational counterpart's output on every extension of that prefix.
4. **Purge safety.** State for a key or window is dropped only when no future input can join,
   aggregate or cancel with it. In a time-window join, purge `r` only once `wm > r.ts + |W_R|`.
5. **Retraction pairing.** Each negative or revision tuple cancels exactly one prior positive tuple
   (bag semantics). The planner never routes retractions to an operator that cannot consume them.
6. **Join results exactly once.** In symmetric or eddy joins, exactly one probe emits each pair:
   the newer tuple's. A sequence-number tie-break handles simultaneous arrivals.
7. **Deterministic replay.** The same input, merged deterministically at multi-input operators,
   yields identical state and output. Wall-clock reads, RNG seeds and external lookups are logged
   or derived from input.
8. **Snapshot consistency.** A checkpoint is a consistent cut. Producers truncate output logs only
   below positions that every downstream consumer or snapshot covers.
9. **Synopsis contract.** Each approximate operator declares its update model (cash register or
   turnstile), its error bound and its mergeability. Retractions never reach cash-register-only
   summaries.
10. **Shedding contract.** Drops happen only at inputs or immediately after shared (split)
    operators. Each query reports its approximation kind: subset, scaled unbiased sample, or
    value-preferential.
11. **Explicit pattern semantics.** Every pattern query defines its selection, consumption and skip
    policy and a WITHIN bound. Composite events carry interval timestamps.

## Design space & trade-offs

| Decision | Option | Wins when | Cost / risk |
|---|---|---|---|
| Time domain | event time + watermarks | replay, replicas, late data | watermark lag adds latency; idle sources stall |
| | arrival time | cheap approximate monitoring | non-deterministic; breaks exactly-once |
| Disorder | sort buffer (bound δ) | order-sensitive ops (count windows, sequences) | +δ latency, O(rate·δ) memory |
| | window ids + watermark close | time windows, aggregates | open-window state |
| | speculative + retraction | lowest latency | every consumer must handle retractions |
| Window eval | re-evaluate per window | tumbling, holistic aggregates | O(range/slide) work per tuple |
| | shared slices (panes/pairs) | many overlapping windows/queries | partials must be mergeable |
| | add/subtract; two-stacks / FlatFAT | invertible; non-invertible associative | float drift; O(1) amortized / O(log n) |
| Retractions | timestamp-driven expiry | monotone / weak non-monotone edges | not for difference, distinct, nested aggregates |
| | negative tuples | strict non-monotone plans | 2× traffic; minus rule in every operator |
| Scheduling | FIFO / Chain / HR, HNR, BSD | max latency / queue memory / avg latency, slowdown, tails | memory spikes / starvation / stale stats |
| Overload | random / window / semantic drop; triage | proportional loss / exact subsets / high-value data / summarize all | biased aggregates / needs QoS / shadow plan |
| Adaptivity | eddy routing vs periodic re-opt (A-Greedy) | volatile vs phase-stable selectivities | per-tuple overhead vs live-state migration |
| HA | active replicas | latency-critical | (k+1)× resources; deterministic input order needed |
| | passive Δ-checkpoints / upstream backup | large state / small windows | restore + replay / recovery ∝ window history |
| | global barrier snapshots (Flink) | large keyed state on DAGs | alignment stalls; global rollback |
| Delivery | idempotent vs transactional (2PC) sink | keyed upserts vs append-only/Kafka sinks | deterministic ids vs latency = checkpoint interval |

## Algorithms that matter

- **CQL R2S**: `Istream(R)=⋃τ(R(τ)−R(τ−1))×{τ}`, Dstream the reverse, `Rstream=⋃τ R(τ)×{τ}`. Emit
  results for τ only after time has advanced past τ.
- **Window ids** (hopping, range r, slide s): a tuple at t belongs to windows
  `k ∈ [⌊(t−r)/s⌋+1, ⌊t/s⌋]`. Close k when `wm ≥ k·s+r`. **Panes** use slice length gcd(r,s);
  **pairs** use ≤ 2 slices per slide. Many queries share the union of their slice edges.
- **Symmetric window join**: purge the other side, probe it, insert into your own. Either merge
  inputs by timestamp or gate purges on the watermark.
- **Punctuation behaviours**: pass, keep and propagate per operator. Union propagates only what both
  inputs have punctuated. A join purges the other side's state for punctuated join values.
- **Chain**: build the lower envelope of the progress chart and run the tuple on the steepest
  segment. Memory stays within one tuple per path of optimal (selectivity ≤ 1).
- **Aurora shedding**: rank drop points by loss/gain, where gain = `R·(p·L − D)`. Precompute a road
  map of plans that shed progressively more.
- **Eddy + SteMs**: route by tuple signature, using a lottery (tickets ∝ 1−selectivity) or batched
  ascending rank `c/(1−p)`. **A-Greedy** maintains the conditional-rank invariant and is within 4×
  of optimal at convergence.
- **Recovery**: upstream backup trims logs on downstream "no longer needed" notices; passive standby
  ships Δ-checkpoints; DPC is delay → tentative → correct. **Barrier snapshot** (Beyond EDBS):
  inject, align, snapshot asynchronously, forward, ack, complete.
- **Synopses**: reservoir (accept with prob `n/t`); Misra–Gries (error ≤ N/(k+1)); SpaceSaving
  (replace the min, error ≤ N/m); Count-Min (`⌈e/ε⌉×⌈ln 1/δ⌉`, error ≤ ε‖f‖₁); GK
  (`g+Δ ≤ 2εn`, O((1/ε) log εn)); q-digest (O((1/ε) log U), mergeable); exact top-B Haar
  coefficients in O(B + log N) for ordered input.
- **CEP NFA**: predicate edges, instances carrying bindings, self-loops for Kleene/FOLD, lazy match
  construction from per-state stacks, negation confirmed at window close. **Pub/sub**: per-attribute
  predicate indexes with counting, and the NiagaraCQ constant-table join.

## Failure modes & classic bugs

- **An idle partition stalls the watermark**, so windows never close. Watch per-input watermark lag
  and add idleness timeouts.
- **Late data dropped silently**, or folded into an already-emitted window without a retraction.
  Count late tuples and route them to a side output.
- **Join purges ahead of the watermark** lose matches only under network jitter. Reproduce by
  permuting input within δ.
- **Arrival-time windows in replicated or replayed jobs**: replicas diverge and recovery produces
  divergent duplicates.
- **Istream over a non-monotone aggregate**: downstream double counts. **Float SUM maintained by
  subtract-on-evict** drifts. **Rows windows with timestamp ties** are non-deterministic.
- **Unbounded state** from group keys that no punctuation covers (GROUP BY bidder when only auctions
  are punctuated).
- **A drop placed above a shared operator** degrades every query that shares the subplan. **Chain
  starves** expensive, unselective tails.
- **Eddy duplicates**: one join result produced along two routing paths.
- **Log-truncation races**: a producer trims tuples a backup still needs after a reordered ack.
- **Nondeterministic merge at union/join** (no SUnion-style serialization): active replicas diverge.
- **Seeds left out of the checkpoint**: sketches differ after recovery. **Retractions fed into
  SpaceSaving or a reservoir** corrupt the estimates.
- **CEP explosion** under skip-till-any-match with Kleene+ and no WITHIN. **Trailing negation**
  never fires without time progress. **Point timestamps on composite events** produce wrong nested
  sequences.

## Implementation checklist (C/C++/Rust)

- Batches: columnar (Arrow-compatible) with an event-time column and a row-kind column
  (+I/−D/−U/+U). Watermarks and punctuations travel in-band as control records so ordering holds.
- Channels: bounded SPSC rings between fused regions, credit-based back-pressure across threads and
  nodes, no unbounded queues. C++: cache-line-padded ring with acquire/release indices.
- Operator trait: `process(batch)`, `on_watermark`, `on_punctuation`, `snapshot/restore`, plus
  capability flags (`accepts_retractions`, `emits_retractions`, `order_sensitive`,
  `partition_key`) that the planner checks.
- Keyed state: open-addressing maps per partition (no cross-thread sharing), key groups for
  rescaling, an LSM backend for large state (`lsm-storage`), and an event-time timer wheel per
  partition.
- Windows: a slice store keyed by (key, slice id) holding mergeable partials, evicted by watermark.
  Two-stacks or FlatFAT for non-invertible aggregates. Joins: a hash table plus an expiry FIFO or
  heap per side.
- Determinism: merge on (ts, source, seq) at multi-input operators, an injected clock, seeded RNGs
  stored in state.
- Checkpoints: barrier alignment buffers, asynchronous copy-on-write snapshots, source offsets
  inside the snapshot, two-phase-commit sink hooks.
- Synopses: a common `update/merge/query/serialize/error_bound` interface with multiply-shift or
  tabulation hashes and per-row seeds.
- Scheduler: priority buckets with a runnable bitmap, priorities recomputed when statistics refresh,
  train (batch) execution per invocation.
- Metrics per operator: watermark lag, queue depth, state size, late count, shed fraction, checkpoint time.

## How to test it

- **Re-evaluation oracle**: materialize each window id's tuples, run plain SQL, and diff against the
  incremental output.
- **Disorder invariance**: permutations within the declared bound give identical per-window output,
  and tuples beyond it take the late path deterministically.
- **Faithfulness and eagerness**: over random prefixes and extensions, no emitted result is ever
  contradicted, and everything the punctuations allow is emitted.
- **State soak**: run 10^8+ tuples with a covering punctuation scheme and require a flat state
  high-water mark.
- **Kill-anywhere recovery**: crash mid-alignment, mid-commit or mid-truncation. Output must equal
  the failure-free run, and duplicates are classified as repeating, convergent or divergent.
- **Replica agreement**: active replicas fed jittered input produce byte-identical output.
- **Synopses**: check bounds against an exact oracle, a failure rate ≤ δ across seeds, merge
  equivalence, and turnstile insert-then-delete returning to zero.
- **CEP**: a brute-force subsequence enumerator for each selection/consumption policy.
- **Overload drill** at 2–5× capacity: bounded latency, planned shed fraction and error. Linear Road.

## Expert review questions

1. What is the time domain of each edge, where is the watermark generated, and what happens when a
   partition goes idle?
2. Which operators are order-sensitive, and how is order restored after each data-parallel region?
3. Which retraction protocol leaves each non-monotone operator, and can every consumer accept it?
4. What is the late-data policy (drop, side output, retract-and-revise), and is it set per query?
5. Which punctuation or watermark scheme bounds each blocking operator's state? Show key coverage.
6. How are overlapping windows shared across queries, and are holistic partials mergeable?
7. Under 3× overload, where do drops occur, and what approximation contract does each query get?
8. What makes replay deterministic: merge order, clocks, seeds, external lookups?
9. Exactly-once for state, for delivery, or both? Which sink protocol, and at what latency?
10. What is MTTR as a function of state size and checkpoint interval? Is repair local or a global
    rollback?
11. How is keyed state rescaled without rehashing every key?
12. Which synopses, with what (ε, δ)? Are their seeds in the checkpoint?
13. For CEP: which selection, consumption and skip policy, what WITHIN bound, and what explosion
    guard?
14. How do scheduler priorities and shedding plans track drifting selectivities?

## Go deeper

- `references/stream-semantics-and-cql.md`: stream models, CQL semantics, retraction protocols, DSMS architecture.
- `references/windows-and-punctuations.md`: windows, slicing, window joins, punctuations, watermarks, disorder.
- `references/scheduling-load-shedding-adaptivity.md`: scheduling, Chain, load shedding, eddies, hardware mapping.
- `references/fault-tolerance-and-exactly-once.md`: HA techniques, recovery guarantees, Flink/Kafka, S-Store.
- `references/stream-synopses.md`: sampling, heavy hitters, quantiles, histograms, wavelets, distributed monitoring.
- `references/complex-event-processing.md`: pattern algebras, policies, NFA execution, MQO, pub/sub.
- `references/edbs-entries.md`: all 28 source entries with printed pages.

## Related skills

- `query-plan-design`: the operator contract, which this skill extends with watermark, punctuation,
  retraction and snapshot hooks.
- `parallel-distributed-execution` / `parallel-database-systems` / `distributed-dbms-design`: batch
  exchange, partitioning and placement. Streaming fission, ordered merge, key-group rescaling and
  distributed shedding live here.
- `join-algorithms`: hash-join internals. Window, symmetric and shared joins live here.
- `query-optimizer` / `query-execution-advanced`: one-shot and general adaptive QP. Stream eddies,
  A-Greedy and multi-query sharing live here.
- `cardinality-and-statistics`: synopses as optimizer statistics. This skill treats them as operator
  state (update model, mergeability, windows).
- `materialized-views-ivm`: IVM theory. Negative tuples and predicate windows are IVM on streams.
- `temporal-databases`: time and interval semantics, versioned tables for event-time lookups.
- `sql-semantics-and-active-rules`: ECA rules and active-DB composite events, the ancestors of CEP.
- `recovery-and-durability` / `transactions-and-recovery` / `concurrency-control-theory`: logging,
  checkpoints and serializability. Streaming recovery semantics and window-serializability live
  here.
- `replication-protocols` / `replication-and-consistency` / `distributed-consensus`: state-machine
  replication and membership, which underpin active replicas.
- `olap-and-warehouse-engines`: SQL window functions over stored data, which are not stream windows.
- `beyond-relational-engines` (XML/graph streams), `multidimensional-and-similarity-indexing`
  (continuous k-NN), `tuning-and-benchmarking` (Linear Road), `lsm-storage` (large operator state);
  `dbms-architecture`, `storage-devices-and-io`, `index-structures-catalog`, `relational-theory`,
  `database-security-internals` are background only.

## Grounding

EDBS 2e: Adaptive Stream Processing (p.63); Big Stream Systems (p.273); Complex Event Processing
(p.530); Continuous Query (p.630); Data Stream (p.853); Data Stream Management Architectures and
Prototypes (p.854); Distributed Data Streams (p.1162); Event and Pattern Detection over Streams
(p.1354); Event Pattern Detection (p.1373); Fault Tolerance and High Availability in DSMSs
(p.1448); Frequent Items on Streams (p.1524); Histograms on Streams (p.1715); Load Shedding
(p.2111); Nonrelational Streams (p.2505); One-Pass Algorithm (p.2556); Publish/Subscribe Over
Streams (p.2937); Punctuations (p.2943); Quantiles on Streams (p.2965); Scheduling Strategies for
Data Stream Processing (p.3282); Stream Models (p.3768); Stream Processing (p.3771); Stream
Processing on Modern Hardware (p.3772); Stream Sampling (p.3782); Streaming Analytics (p.3793);
Stream-Oriented Query Languages and Operators (p.3802); Transactional Stream Processing (p.4205);
Wavelets on Streams (p.4588); Window-Based Query Processing (p.4695).

Papers and systems: CQL (Arasu, Babu, Widom, VLDB J 2006); Aurora (VLDB J 2003), Borealis (CIDR
2005); TelegraphCQ (CIDR 2003); punctuations (Tucker, Maier et al., TKDE 2003); heartbeats
(Srivastava & Widom, PODS 2004); Chain (Babcock et al., SIGMOD 2003); load shedding (Tatbul et al.,
VLDB 2003); eddies (Avnur & Hellerstein, SIGMOD 2000); A-Greedy (Babu et al., SIGMOD 2004); HA
algorithms (Hwang et al., ICDE 2005); Borealis FT (Balazinska et al., SIGMOD 2005); Flux (Shah et
al., SIGMOD 2004); S-Store (VLDB 2015); MillWheel (VLDB 2013); Dataflow model (VLDB 2015);
D-Streams (SOSP 2013); SpaceSaving (ICDT 2005); Count-Min (2005); GK (SIGMOD 2001); SASE (SIGMOD
2006); Cayuga (CIDR 2007). Beyond EDBS (flagged where used): panes (Li et al. 2005), pairs
(Krishnamurthy et al., SIGMOD 2006), Flink asynchronous barrier snapshots (Carbone et al. 2015;
VLDB 2017), Kafka exactly-once (KIP-98, 2017), SQL:2016 MATCH_RECOGNIZE, SASE+ (SIGMOD 2008), KLL
(FOCS 2016).
