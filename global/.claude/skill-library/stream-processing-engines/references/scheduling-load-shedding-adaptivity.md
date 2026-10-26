# Operator scheduling, memory minimization, load shedding, adaptivity, and hardware mapping

Read this when you are choosing what runs next in a push-based engine, keeping
queue memory bounded under bursts, deciding where and how to drop load during
overload, re-ordering operators at runtime as selectivities drift, or mapping
a dataflow onto cores, GPUs or FPGAs.

---

## 1. Cost model vocabulary

The query plan is a dataflow DAG with a queue in front of each operator.
Common sub-expressions across registered queries are merged into one global
plan. For operator `O_x` in query `Q_k`:

- `c_x`: cost (time) to process one input tuple.
- `s_x`: selectivity/productivity. Tuples out per tuple in. ≤ 1 for filters,
  possibly > 1 for joins.
- Operator segment `E_x^k`: the path from `O_x` to the root of `Q_k`.
- Global selectivity `S_x^k = s_x · s_y · … · s_root` along the segment.
- Global average cost `C̄_x^k = c_x + c_y·s_x + c_z·s_x·s_y + …`, the expected
  time to push one tuple from `O_x` through the segment (each downstream cost
  weighted by the fraction that survives to reach it).
- Ideal tuple processing time `T_k = c_leaf + … + c_root`, the total cost if
  the tuple survives every filter. That is the minimum latency for an output
  of `Q_k`.

Metrics (per output tuple `t_i`, arrival `A_i`, departure `D_i`):
- response time `R_i = D_i − A_i`;
- slowdown (stretch) `H_i = R_i / T_k`;
- worst case: max R, max H;
- ℓ2 norm `sqrt((1/N) Σ R_i²)`. This balances average and tail because squaring
  penalizes outliers.

## 2. Scheduling policies

| Policy | Priority of operator `O_x` | Optimizes | Notes |
|---|---|---|---|
| FIFO / FCFS | arrival order | max response time (optimal) | ignores cost; high memory under bursts |
| Round-robin (RR) | cyclic | fairness | Nile; Aurora uses RR across queries |
| Rate-based (RB) (Urhan & Franklin 2001) | `s/c` along the path | avg response time, single query | |
| Highest Rate (HR) | `S_x^k / C̄_x^k` (global output rate) | avg response time, many queries | static priority, computed at registration |
| Highest Normalized Rate (HNR) | `S_x^k / (C̄_x^k · T_k)` | avg slowdown | favours cheap queries even if unproductive |
| Longest Stretch First (LSF) | current max slowdown | max slowdown (optimal) | dynamic |
| Balance Slowdown (BSD) | `HNR · (W_x^k / T_k)`, with `W` the wait of the oldest pending tuple | ℓ2 of slowdown | avoids starvation; dynamic |
| Balance Response Time (BRT) | analogous with response time | ℓ2 of response time | dynamic |
| Aurora QoS-aware | utility = slope of the query's latency-QoS graph at the expected output time; ties broken by urgency (distance to a QoS cliff) | application utility | bucketing + precomputation to make it cheap |
| Chain (Babcock et al. 2003) | slope of the lower envelope of the progress chart (§3) | queue memory | can starve; near-optimal memory |
| Mixed / Chain-Flush | Chain with a latency constraint; a parameter slides it toward FIFO | memory vs. latency | |
| Freshness-aware | maximizes output freshness (QoD) | data quality | |
| AMoS | learns which of several policies performs best online | multi-objective | meta-scheduler |

Implementation notes:
- **Static policies** (HR, HNR, Chain) compute priorities once per plan change.
  Keep operators in a priority queue keyed by priority, filtered to those with
  non-empty input queues. Use a bitmap of runnable operators per priority
  bucket for O(1) selection.
- **Dynamic policies** (LSF, BSD, QoS-aware) depend on waiting time. Naive
  recomputation at every scheduling point is too slow. Approximate with
  priority buckets, precomputation, search-space pruning, and clustering
  queries with similar parameters.
- **Batching amortizes scheduling.** Aurora's *train scheduling* processes a
  train of queued tuples per operator invocation. *Superbox scheduling* runs
  a whole chain of boxes as one unit, which is the same thing as operator
  *fusion* (§6). Engines that precompute the next operator and call it
  directly from the current one remove both scheduler and queue overhead
  (EDBS "Stream Processing").
- **Selectivity estimates drift.** Static priorities must be refreshed from the
  same statistics the adaptive optimizer uses (§5), or the scheduler optimizes
  a stale plan.

## 3. Memory minimization: the Chain algorithm

Goal: minimize the total number of tuples buffered in queues during bursts
(Babcock, Babu, Datar, Motwani, SIGMOD 2003; VLDB J 2004).

**Progress chart** for an operator path. Start at point `(0, 1)`: time 0, size
1 (one input tuple). After operator i, plot `(t_i, s_i)`, with `t_i` the
cumulative processing time and `s_i` the cumulative relative size (product
of selectivities). Memory falls as a tuple moves right and down.

**Lower envelope.** From the current point, draw the steepest descending line
to any later point. Repeat from that point. Each segment groups consecutive
operators into a *chain*, and its slope is the memory released per unit of
CPU time.

**Rule.** At each tick, among all tuples queued anywhere, run the one whose
next operator lies on the steepest segment (ties: earliest arrival). Operators
in a chain run back to back.

```
build:   for each path, compute lower envelope; priority(op) = slope(segment(op))
run:     loop: pick runnable op with max priority (tie: oldest tuple); process one tuple
```
Guarantee: for selectivities ≤ 1, Chain's memory is within one tuple per
operator path of the optimal clairvoyant schedule. Failure mode: a
low-priority segment (expensive, unselective tail) can starve. Use Mixed or
Chain-Flush when latency matters.

## 4. Load shedding

When the offered load exceeds capacity C on some resource (CPU, memory,
bandwidth, disk), queues grow without bound and latency explodes. Load
shedding drops (or summarizes) data to keep load ≤ C while minimizing loss of
answer quality. Every scheme answers four questions: **when** (load > C,
detected by monitoring), **where** in the plan, **how much**, and **which
tuples**. The shedder itself must be cheap.

### 4.1 Where to drop

Dropping early saves the most work. But dropping before a *shared* operator
hurts every query downstream of it. Both Aurora and STREAM therefore restrict
drop points to **plan inputs** and **just after split points** (outputs of
shared operators where paths diverge). STREAM also notes that when all
children of a node shed, a common fraction can be pulled up into the parent
and the children shed only the remaining relative fraction.

### 4.2 Aurora / Borealis (Tatbul et al., VLDB 2003; VLDB 2006; VLDB 2007)

- **Utility model**: per-query QoS graphs. The *loss-tolerance* graph maps
  percentage of tuples delivered to utility. The *value-based* graph maps
  output attribute values to utility.
- **Loss/gain ratio** for a candidate drop point: utility lost per CPU
  cycle saved. Gain = `R · (p·L − D)`, with R the input rate at the point,
  p the drop fraction, L the downstream processing cost per tuple from that
  point, and D the drop operator's own per-tuple cost. Insert drops in order of
  increasing loss/gain (smallest utility loss per cycle first).
- **Load Shedding Road Map (LSRM)**: a precomputed sequence of plans, each
  shedding more load. At runtime the shedder moves along the map according to
  measured excess load, with no optimization on the critical path.
- **Drop types**: *random drop* (Bernoulli with probability p; preserves
  proportions; matches the loss-tolerance QoS) and *semantic drop* (a filter
  that removes the lowest-utility values first; matches the value QoS).
- **Window drop** (window-aware shedding for aggregation): drop whole windows,
  not tuples. Mark window starts upstream so that the downstream aggregate
  either sees a full window or none of it. Answers are a *subset* of the exact
  answer, never wrong values. This matters when consumers cannot tolerate
  biased aggregates.
- **Distributed (Borealis)**: upstream shedding changes downstream load, so
  plans must be computed jointly. Two options. (1) A centralized
  coordinator with an LP solver produces a global plan. (2) In the
  distributed option, each node publishes a *Feasible Input Table* (FIT) of
  input-rate combinations it can sustain, neighbours compose FITs, and each
  node plans locally. Precomputed plans are stored in a quadtree index over
  rate space. The FIT approach is faster to compute and updates incrementally.

### 4.3 STREAM (Babcock, Datar, Motwani, ICDE 2004)

Targets sliding-window aggregate (SUM/COUNT/AVG) queries. Objective: minimize
the **maximum relative error** across queries. A statistics manager tracks
per-operator selectivity and cost and per-query mean and standard deviation of
the aggregated value. The required sampling rate for query i with allowed
relative error ε_i is derived from a Hoeffding-style bound. Sampled SUMs are
scaled by 1/p (Horvitz–Thompson). Drops sit at inputs or the heads of
shared segments. One "first" sampler per path sets the base rate, and the
others are expressed relative to it. The optimizer iterates over paths to
meet the load constraint and then sets the remaining rates.

### 4.4 Shedding for joins and memory

- **Max-subset under memory limits** (Das, Gehrke, Riedewald, SIGMOD 2003).
  PROB evicts the window tuple whose join value has been least frequent on the
  *other* stream. LIFE evicts the tuple minimizing (partner frequency ×
  remaining lifetime).
- **Age-based** (Srivastava & Widom, VLDB 2004). If a tuple's join
  productivity depends on its age (an *age curve*), keep the ages that produce
  the most matches. A second mode instead produces a *uniform random sample*
  of the join result, for when a downstream aggregate needs unbiased input.
  The two objectives conflict: max-subset biases the sample.
- **Selective processing** (Gedik et al.): process only part of each join
  window to maximize output rate or utility, exploiting time correlation
  between the inputs.

### 4.5 Summarize instead of drop

- **Data triage** (Reiss & Hellerstein, ICDE 2005). Tuples that cannot be
  processed go into synopses. At window end a *shadow plan* runs over the
  synopses, and its approximate result is merged with the exact result for the
  processed portion.
- **Multi-resolution archives** (Chandrasekaran & Franklin, VLDB 2004). For
  live-plus-history queries where disk is the bottleneck, keep archives at
  several summary resolutions and pick the resolution the current live rate
  allows.
- **Model-based suppression** (Jain, Chang, Wang, SIGMOD 2004). A Kalman
  filter at the source predicts the server's view. Send a tuple only when the
  prediction misses the precision bound. This sheds network load.

### 4.6 Optimizer-integrated and closed-loop shedding

- NiagaraCQ-style (Kang, Naughton, Viglas; Ayad & Naughton, SIGMOD 2004):
  treat shedding as part of plan choice. With enough resources all plans have
  equal throughput but different utilization. Under overload, the
  lowest-utilization plan is **not** necessarily the highest-throughput plan
  once drops are placed. Choose plan and drop placement jointly.
- **Closed-loop control** (Tu et al., VLDB 2006; Amini et al., ICDCS 2006):
  a feedback controller adjusts drop rates from measured queue lengths and
  delay. It handles high-frequency rate fluctuation better than open-loop
  periodic triggering.
- Mining workloads (Loadstar): accuracy impact is non-monotone, so shed the
  streams whose predicted class labels are most certain.

### 4.7 Shedding design checklist

1. Declare the approximation contract per query: subset (window drop,
   max-subset), unbiased sample (random drop + scaling), or value-preferential
   (semantic drop). The contract dictates the drop type.
2. Drop points are restricted to inputs and post-split edges. Verify that no
   drop sits upstream of a shared operator unless every sharing query accepts it.
3. Precompute plans and switch them on the hot path in O(1).
4. Propagate a "sampled at rate p" annotation downstream so aggregates scale
   and so results can report error bounds.
5. Account for the drop operator's own cost (the D term). Shedding that costs
   more than it saves makes overload worse.

## 5. Adaptive stream processing

Streams live long. Selectivities, rates and correlations drift, so a plan
optimized once goes stale. Sliding windows bound operator state, which makes
stream join ordering behave like *filter* ordering. Each windowed join input
acts as a filter against bounded state from the other side, and that is why
theoretical guarantees are attainable here (EDBS "Adaptive Stream Processing").

### 5.1 Eddies (Avnur & Hellerstein, SIGMOD 2000) and SteMs

An eddy is a tuple router plus a set of commutative operators, each with an
input queue. With **State Modules** (SteMs; Raman, Deshpande, Hellerstein,
ICDE 2003; Madden et al., SIGMOD 2002 for CACQ), each base stream has a SteM.
A SteM is one hash table of a symmetric join, keyed on the join attribute (a
stream joined on two attributes needs two SteMs).

```
tuple t arrives from stream X:
    insert t into SteM_X
    loop:
        dests = routing_table[signature(t)]      # valid next ops given what t contains/visited
        if dests empty: emit t; break
        op = policy.choose(dests)
        results = op.process(t)                  # filter or probe a SteM
        for r in results: mark r visited(op); route r (recursively/queue)
```
- *Tuple signature*: which base streams the tuple contains plus which
  operators it has passed. The routing table maps signature → legal
  destinations, encoding semantic constraints (e.g., a predicate needs columns
  from both R and S).
- *Exactly-once results*: with several SteMs and arbitrary routing, the same
  join result can be produced along two paths. Prevent this with an ordering
  rule (e.g., a probe only matches SteM entries that arrived earlier, by
  sequence number) and test with a duplicate-detecting oracle.

Routing policies:
| Policy | Mechanism | Overhead |
|---|---|---|
| Tickets / lottery (original eddy) | an operator gains a ticket per tuple received and returns one per tuple emitted, so tickets ∝ (1 − selectivity); lottery among valid destinations weighted by tickets; a full input queue removes the operator from the lottery (back-pressure) | per-tuple decision; high |
| Deterministic with batching (Deshpande, SIGMOD Rec 2004) | monitor selectivities, assume independence, periodically order by rank `c_i/(1 − p_i)` (ascending: cheap, selective first), route batches | low |
| Content-based routing (Bizarro et al., VLDB 2005) | sample to find, per operator, the *classifier attribute* most correlated with its selectivity; keep a table of selectivity per attribute value; route each tuple probabilistically, favouring low selectivity for its values | moderate; wins with correlated data |

Per-tuple routing costs real CPU. Batching and fixing routes for runs of
tuples recover most of it.

### 5.2 A-Greedy (Babu, Motwani, Munagala, Nishizawa, Widom, SIGMOD 2004)

Adaptive ordering of pipelined filters without per-tuple routing:
- **Profile**: a sliding window of sampled tuples, each evaluated against
  *all* predicates and stored as a bit vector.
- **Matrix view** `V[i,j]`: the number of profiled tuples that pass the first
  i−1 chosen filters but fail filter j.
- **Greedy invariant**: the i-th filter is the one with minimum
  `c_j / (1 − p(j | filters 1..i−1 pass))`, the conditional rank. Re-order
  when the invariant is violated.
- Guarantee: if statistics converge, cost is within 4× of optimal. This is
  one of the few hard guarantees in adaptive QP. It handles correlated
  predicates because it uses conditional selectivities.

### 5.3 Minimizing communication (distributed adaptivity)

Adaptive filters (Olston, Jiang, Widom, SIGMOD 2003): a remote object O
reports only when its value leaves `[v − w_O/2, v + w_O/2]`. The coordinator
caches the last value and width. For AVERAGE queries with precision δ_j, the
widths of the query's objects must sum to at most δ_j × (number of objects).
Periodically, shrink all widths; objects that violate report. Then grow the
widths of objects with the highest *burden score* `c_O / (p_O · w_O)` (cost
to send ÷ (update frequency × width)) as far as every query's constraint
allows. See `stream-synopses.md` §8 for the general distributed monitoring
framework.

### 5.4 Adaptivity checklist

- Statistics: maintain per-operator selectivity and cost over a decaying window.
  Selectivity estimates need a minimum sample, or they oscillate.
- Plan migration: moving from plan P to P' with live windowed state needs a
  migration strategy. Options: (a) run P and P' in parallel until P's windows
  drain ("parallel track"); (b) move state (recompute P' state from P's base
  windows); (c) eddies avoid migration by construction since the routing
  changes and the state does not.
- Hysteresis: re-optimize only when the predicted gain exceeds a threshold, to
  avoid flapping.

## 6. Parallelism and modern hardware

### 6.1 Programming models

| | Synchronous dataflow (SDF) | Asynchronous stream processing |
|---|---|---|
| Rates | each operator declares fixed tokens in/out per firing | selectivity data-dependent, runtime-varying |
| State | stateless, arbitrary, or limited (read-only window) | includes *partitioned stateful* operators (independent state per key) |
| Schedule | static, computed at compile time; buffers sized statically | dynamic; bounded buffers with **back-pressure** throttling upstream |
| Typical home | embedded/DSP; maps cleanly to FPGA/GPU | data-intensive DSMS |

### 6.2 Kinds of parallelism and the two transforms

- **Pipeline**: consecutive operators on different tuples concurrently.
- **Task**: fan-out branches concurrently on copies of a tuple.
- **Data**: replicas of an operator on different tuples. This needs a split
  and, if order matters, an ordered merge. It applies only to stateless or
  partitioned-stateful operators. It scales with the number of partitions,
  not with pipeline depth.

**Fusion** (superbox): run a connected subgraph in one thread with direct
calls, with no queue, serialization or scheduling in between. It cuts per-tuple
overhead but forfeits pipeline/task parallelism inside the fused region.
Decide at compile time (SDF, StreamIt-style) or elastically at runtime
(auto-pipelining).

**Fission**: replicate a bottleneck operator or region across threads/nodes.
- Stateless: any distribution (round-robin, least-loaded).
- Partitioned stateful: hash on the partition key so each key always reaches
  the same replica.
- Arbitrarily stateful: not fissionable.
- Strict order: sequence numbers at the split, ordered merge after.
- *Elastic* fission changes the replica count at runtime. Keyed state must
  migrate. Use consistent hashing (or key groups, below) to bound movement.

> **Beyond EDBS:** Flink pre-shards keyed state into a fixed number of *key
> groups* (the max parallelism). Rescaling reassigns contiguous key-group
> ranges to tasks, so state moves as whole key groups without rehashing
> individual keys. The design is equivalent to consistent hashing with fixed
> virtual nodes, and it is the usual answer to elastic fission of partitioned
> state.

### 6.3 GPUs

The GPU is a coprocessor with its own memory behind PCIe. Kernels run SPMD,
and a warp executes in lockstep, so data-dependent branches serialize.
Consequences for streaming:
- Transfers have fixed overhead, so you must **mini-batch**. That trades latency
  for throughput, which conflicts with the low-latency mandate.
- Profitable for compute-dense per-item work (windowed joins with large
  windows, aggregation, pattern matching). It is poor for branchy filters over
  general relational streams.
- SDF-style programs fit GPUs better than asynchronous data-dependent ones.
- Published work accelerates single operators (stream joins such as
  HELLS-join, streaming aggregation, CEP matching), not whole pipelines.

> **Beyond EDBS:** Saber (Koliousis et al., SIGMOD 2016) runs window queries on
> CPU and GPU together, scheduling query tasks to whichever processor is
> currently faster. Window computation is decoupled from batch size (a
> micro-batch need not align with window boundaries), which addresses the
> batch-vs-window mismatch above.

### 6.4 FPGAs

Lookup tables, flip-flops and block RAM on a programmable interconnect, usually
programmed in VHDL/Verilog (soft processors trade speed for C/C++
programmability). Data arrives from host memory over PCIe or straight from an
FPGA-attached NIC, which suits wire-speed monitoring and trading.
- SDF programs can often be mapped completely to hardware.
- Asynchronous SQL streams map partially. Glacier ("Streams on wires",
  Müller, Teubner, Alonso, VLDB 2009) compiles select-project(-join) queries
  with windows into circuits, one circuit per operator plus synchronization
  and flow control. Multi-query FPGA stream processing has also been shown
  (Sadoghi et al., ICDE 2012).
- Reconfiguration is slow, so ad hoc query registration needs parameterized
  circuits (registers holding predicate constants), not resynthesis.

### 6.5 Multicore engine checklist

- Queues: SPSC ring buffers between fused regions. Size them in batches, not
  tuples. Use back-pressure (blocking or credit-based), never unbounded growth.
- Batch everything: tuple-at-a-time virtual calls dominate cost. Columnar
  micro-batches with punctuations flushing partial batches (as in Trill,
  Chandramouli et al., VLDB 2014, cited in the bundle) let the batch size tune
  latency against throughput.
- Per-key state: open-addressing hash maps per partition. No sharing across
  threads means no locks. Pad per-thread counters to cache lines.
- Timers/watermarks: a per-thread timer wheel keyed by event time, advanced by
  the watermark.
- NUMA: pin a partition's thread and memory to the same socket. Exchange
  across sockets in batches.

Sources: EDBS "Scheduling Strategies for Data Stream Processing" (p.3282),
"Adaptive Stream Processing" (p.63), "Load Shedding" (p.2111), "Data Stream
Management Architectures and Prototypes" (p.854), "Stream Processing"
(p.3771), "Stream Processing on Modern Hardware" (p.3772), "Distributed Data
Streams" (p.1162), "Big Stream Systems" (p.273).
