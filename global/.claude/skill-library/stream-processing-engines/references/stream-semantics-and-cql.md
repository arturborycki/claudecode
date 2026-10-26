# Stream data models, continuous-query semantics, and DSMS architecture

Read this when you are defining what a "stream" *is* inside the engine (tuple
shape, timestamps, insert vs. retract), what a continuous query *means*
(so two implementations can be checked against each other), or how the
runtime is laid out (queues, scheduler, stream manager, storage manager).

---

## 1. What a stream is, precisely

A data stream is an ordered, potentially unbounded sequence of items that
(a) is produced by sources outside the engine's control and (b) arrives in an
order the engine cannot choose. Two consequences drive every design decision:

- The engine sees each item once, in arrival order, and must decide on the
  spot what to retain (see `stream-synopses.md` for the one-pass model).
- "Done" never happens. Any operator that needs the end of its input
  (sort, aggregate, difference, NOT EXISTS) must be bounded by a window,
  unblocked by a punctuation/watermark, or it never emits.

**Base vs. derived streams.** A base stream comes straight from a source; a
derived stream is the output of some (sub)query. Derived streams inherit the
ordering and timestamp properties of the operator that produced them, which is
why the engine must track *ordering properties* per edge in the plan, exactly
as an optimizer tracks interesting orders.

**Two clocks per item.** Each item can carry a *generation* (event,
application) timestamp set by the source and an *arrival* (system,
processing) timestamp set by the engine. Network delay and multiplexing make
the two orders differ. Semantics defined on generation time are reproducible
(replay gives the same answer); semantics defined on arrival time are cheap
but non-deterministic across runs and replicas. This single choice decides
whether active replication and exact replay are even possible
(`fault-tolerance-and-exactly-once.md`).

**Payload types.** Relational tuples are the default, but streams of raw
packets, text, XML fragments, graph edge insert/delete events, and moving-object
positions are all studied (EDBS "Nonrelational Streams"). They mostly reuse the
same window/time machinery with domain-specific operators (continuous k-NN,
XPath filtering, graph sketches).

### 1.1 Stream models: how items reconstruct the underlying signal

Think of a stream as describing a signal `A : [1..N] → ℝ` (e.g., bytes per
(src, dst) pair). The model says how an item updates `A`:

| Model | Item means | Example | What it breaks |
|---|---|---|---|
| Aggregate (time series) | the full value `A[i]` | per-5-min totals per key | nothing; easiest |
| Cash register | `A[i] += r`, `r ≥ 0` | packets adding bytes to a flow | no deletions |
| Turnstile | `A[i] += r`, any sign | connection open (+1) / close (−1) | samples can be emptied by deletes; many geometric problems hard |
| Strict turnstile | turnstile, but `A[i] ≥ 0` always | open-connection counts | some sketches require strictness |
| Reset | `A[i] := v` (replace) | latest position of a truck | most general alongside turnstile; algorithms harder |

Each has an *ordered* variant (items arrive in domain order), an *unordered*
one, and a *contiguous unordered* one (all updates for one key arrive together,
e.g., the output of a GROUP BY that is not ORDER BY but emits groups whole).
Ordered implies contiguous.

Engine consequences:
- A sliding window turns a cash-register stream into a turnstile one: expiry is
  a negative update. That is why *negative tuples* exist (Section 3).
- Pick synopses by model: reservoir sampling and counter-based heavy hitters
  assume cash register; linear sketches (Count-Min, AMS, Count sketch) survive
  turnstile because updates are reversible.
- Expressiveness order: turnstile ⊇ cash register ⊇ aggregate. Algorithms are
  hardest for turnstile.

### 1.2 Update patterns of derived results

A useful refinement (Golab & Özsu, SIGMOD 2005, in the Stream Models reading
list) classifies operator outputs by how their results expire:
- *monotonic*: results never retract (selection over an unbounded stream);
- *weakest non-monotonic*: results expire in arrival (FIFO) order (selection
  over a time window);
- *weak non-monotonic*: expiry time is known when the result is produced
  (window join: `min(expiry(r), expiry(s))`);
- *strict non-monotonic*: results can retract at unpredictable times
  (negation, aggregation over windows, difference).

Why you care: the first three can be maintained by timestamp-ordered expiry
(priority queue or FIFO keyed by expiry), with no explicit retraction
messages. Only strictly non-monotonic edges need negative/revision tuples. A
planner that annotates every edge with its pattern can choose cheaper state
structures and avoid shipping retractions where none are needed.

---

## 2. Continuous-query semantics

A continuous (standing) query is registered once and logically re-evaluated
forever. The data is transient and the query is persistent, the reverse of
one-shot SQL. Tapestry (email filtering) was the first system to make this a
DBMS feature. Materialized views and ECA triggers are the classical ancestors:
a view is a continuous query whose answer is maintained incrementally, and a
trigger is a continuous query whose answer is an action.

### 2.1 CQL abstract semantics (Arasu, Babu, Widom, VLDB J 2006)

Two types, three operator classes:

```
Stream   S : bag of <tuple, τ>          (τ from an ordered time domain T)
Relation R : T → finite bag of tuples   (a time-varying relation)

stream-to-relation (S2R):  windows
relation-to-relation (R2R): ordinary SQL (σ, π, ⋈, γ, ∪, −, ...)
relation-to-stream (R2S):   Istream, Dstream, Rstream
```

Windows (S2R):
- `S [Range T]` contains the elements with timestamp in `[τ−T, τ]` at instant τ.
- `S [Now]` is `Range 0`: only elements stamped exactly τ.
- `S [Range Unbounded]` contains everything up to τ.
- `S [Rows N]` contains the last N elements by timestamp. **Ties at equal
  timestamps make this non-deterministic.** Specify a tie-break or reject it.
- `S [Partition By A1..Ak Rows N]` keeps the last N per key (a per-key
  count window, i.e., GROUP BY-scoped retention).
- Later CQL variants add `Slide L` for hopping windows.

R2S operators, with `R(τ−1)` the relation at the previous instant:
```
Istream(R) = ⋃τ ( R(τ) − R(τ−1) ) × {τ}     -- inserts
Dstream(R) = ⋃τ ( R(τ−1) − R(τ) ) × {τ}     -- deletes
Rstream(R) = ⋃τ   R(τ)            × {τ}     -- full snapshot every instant
```
(bag difference). `Istream` plus `Dstream` together is a change log. `Rstream`
of a `[Now]` window plus a relation join is how CQL expresses "look up each
arriving tuple against a table".

Semantic facts an implementer must preserve:
1. **Time advances only after an instant is complete.** The answer at τ is
   defined over all input with timestamp ≤ τ. The engine may emit results for τ
   only after it knows no further τ-stamped input will arrive (heartbeat,
   watermark, or ordered input). STREAM processes all tuples with the same
   timestamp as one batch through the plan. That is an implicit atomic,
   isolated unit (see `fault-tolerance-and-exactly-once.md` §5).
2. **Monotone queries make Istream redundant.** `SELECT * FROM S WHERE p` is
   sugar for windowing S, filtering, and taking `Istream`. For a selection,
   `Istream(σ(S[Unbounded]))` and `Rstream(σ(S[Now]))` both equal the filtered
   stream (`Istream` over `[Now]` would drop a tuple identical to one stamped
   at the previous instant, by bag difference). Engines special-case this as stream-to-stream evaluation.
3. **Non-monotone R2R needs retractions.** An aggregate over `[Range 10 min]`
   changes value as tuples expire. `Istream` of it emits the new value and
   `Dstream` the old one. Rstream emits every value at every instant, which is
   correct but very costly. Pick explicitly.
4. **Simultaneity.** Several elements can share τ. Joins and aggregates must
   treat them as simultaneous (all visible at τ), not in arbitrary arrival
   order. Bugs show up as off-by-one results at window edges.

### 2.2 Language design axes (EDBS "Stream-Oriented Query Languages and Operators")

| Axis | Option A | Option B | Engine impact |
|---|---|---|---|
| Closure | Closed under streams only (Aurora SQuAl, Esper EQL, ESL): windows are internal to stateful operators | Streams + relations (CQL, StreamSQL, CCL, StreaQuel) with explicit S2R/R2S | B lets you reuse the relational optimizer and share windows. A has simpler types. |
| Windows first-class? | Named, shareable, queryable windows (CQL, StreamSQL, CCL, StreaQuel) | Window is a parameter of an operator (SQuAl, EQL, ESL) | First-class windows enable cross-query state sharing |
| Window extent | rows, time, value-based (over an attribute known to be ascending; SQuAl, StreamSQL) | predicate windows; top-k windows (KEEP LARGEST); sampled windows (CQL SAMPLE); landmark windows (CCL, StreaQuel) | each extent needs its own expiry structure |
| Correlation with history | one unwindowed stream joined to tables, evaluated per arrival or periodically | Aurora READSQL/WRITESQL boxes | needs snapshot semantics for the table side (§2.3) |
| Stream-stream correlation | window one (most languages) or both (CQL) inputs | StreamSQL GATHER key-matching | windowed symmetric joins (see `windows-and-punctuations.md`) |
| Pattern matching | multi-stream (absence/presence across streams within a time bound) | single-stream regex over rows (MATCH_RECOGNIZE family) | NFA operator (`complex-event-processing.md`) |

Lineage of commercial dialects: StreamSQL (StreamBase) came from SQuAl and CQL;
CCL (Coral8) from CQL; StreaQuel (Truviso) from TelegraphCQ. Several dialects
add INSERT/UPDATE/DELETE-from-stream into tables, which makes the
stream-table boundary transactional (see S-Store).

> **Beyond EDBS:** The Dataflow/Beam model (Akidau et al., VLDB 2015, which is in
> the Transactional Stream Processing reading list) reframes CQL's R2S choice
> as *triggers* (when to emit a window pane) plus *accumulation mode*
> (discarding, accumulating, or accumulating-and-retracting). Retracting mode
> is Istream+Dstream. Flink SQL and Spark Structured Streaming expose the same
> idea as append-only vs. updating/retracting result streams ("changelog"
> streams with +I/−U/+U/−D row kinds in Flink). The "stream–table duality"
> popularized by Kafka Streams is CQL's S2R/R2S pair under new names.

### 2.3 Correlating streams with stored tables

When a stream joins a mutable table, decide which table version each stream
tuple sees:
- *Processing-time lookup*: the current version when the tuple is processed.
  This is cheap and non-deterministic under replay.
- *Event-time (temporal) lookup*: the version valid at the tuple's timestamp.
  This is deterministic but needs a versioned table (see `temporal-databases`).
CQL's relation is time-varying by definition, so it implies the event-time
version. Many engines silently do processing time. Document the choice and
test replay equivalence.

---

## 3. Inserts, deletes, revisions: the tuple-kind protocol

Every incremental stream engine settles on a wire protocol for change:

| Mechanism | Representation | Used by | Cost |
|---|---|---|---|
| Separate I and D streams | two physical streams | STREAM | must keep them co-ordered |
| Positive/negative tuples | one stream, sign bit | Nile | negative tuples double traffic through the plan; every operator needs a minus rule |
| Revision (update) tuples | (old, new) or keyed replacement | Borealis | operators must keep enough state to recompute; can revise *upstream* (re-run from inputs) or *downstream* (patch outputs from old/new values) |
| Timestamp-driven expiry | no message; expiry computed from timestamps | joins and selections over time windows | only works for non-strict patterns (§1.2) |

Negative-tuple processing mirrors the positive path. A W-expire leaf operator
emits a `t−` when `t+` leaves the window, and each operator emits the negated
outputs `t+` produced. Selection and projection pass `t−` through. A join
probes with `t−` to produce negative join results. Aggregates apply the
inverse update (or recompute if not invertible). Distinct needs a per-value
count so that `t−` only emits a retraction when the count reaches 0. Difference
`R − S` is the hard case: a `t+` on S can retract outputs, and a `t−` on S can
resurrect them.

Engine rules:
1. Every operator declares (a) whether it can consume retractions and
   (b) whether it can emit them. The planner rejects plans that feed
   retractions into an operator that cannot take them.
2. Physical deletes must carry enough identity (full tuple or a row id) to find
   the matching insert. Bag semantics: a retraction removes one copy.
3. Negative-before-positive (a retraction arriving before its insert, possible
   across partitions) must be either impossible by construction (single
   ordered channel per key) or buffered.

---

## 4. DSMS architecture

Three properties distinguish a stream processing engine (SPE) from a DBMS
(EDBS "Data Stream Management Architectures and Prototypes"):
1. **Continuous query model**: queries are resident and data flows past them.
2. **Inbound (straight-through) processing**: tuples are processed *before*
   (or instead of) being stored. Storage is off the critical path, and writes
   are optional and asynchronous. A DBMS is outbound: insert, index, commit,
   then query.
3. **Single-process model**: ingestion, operators, state storage and custom
   logic share one address space. This avoids IPC and context switches
   between cooperating products. EDBS's "Stream Processing" entry adds that
   keeping real-time state in an external DBMS is a known performance dead end.

### 4.1 Components

```
 sources ──► Stream manager ──► [queue]─►op─►[queue]─►op─► ... ─► sinks
 (TCP/UDP,   (adapters,           ▲          ▲
  files)      format conv.,       │          │
              arrival notify)  Queue mgr  Storage mgr (async I/O, spill
                                  │       queues/state, table cursors,
                              Scheduler   approximate synopses)
                                  │
                   Optimizers: load shedder, adaptive re-optimizer
                   (fed by statistics/profiler)
```
- *Query executor*: plans are operator graphs connected by queues. Operators
  are non-blocking and emit per input tuple or per window.
- *Queue manager*: bounds buffer memory. When guarantees fail it invokes
  alternatives: spilling, shedding, or summarizing.
- *Storage manager*: asynchronous reads and writes for tables, spilled queues
  and spilled state. It can also hold synopses in place of raw state.
- *Stream manager*: network I/O, adapters, and arrival signals to the scheduler.
- *Scheduler*: chooses which operator runs next (see
  `scheduling-load-shedding-adaptivity.md`).
- *Optimizers at runtime*: the load shedder and the adaptive plan re-optimizer
  both consume live statistics (selectivities, costs, rates).

### 4.2 Prototype lineage (what each contributed)

| System | Key ideas worth reusing |
|---|---|
| Aurora (Brandeis/Brown/MIT) | boxes-and-arrows dataflow; QoS graphs drive scheduling and shedding; train and superbox scheduling; embedded tables (BerkeleyDB) for shared state |
| Borealis | distributed Aurora; revision tuples; DPC fault tolerance; distributed catalog/optimizer; distributed load shedding |
| STREAM (Stanford) | CQL; shared synopses (windows) across operators; Chain scheduling; k-constraints on arrival patterns to bound state; profiler + re-optimizer (A-greedy) |
| TelegraphCQ (Berkeley) | built inside PostgreSQL (reused catalog/parser/optimizer); eddies for per-tuple routing; Fjords queues; grouped filters and shared aggregate state; stream + archived data |
| Gigascope (AT&T) | GSQL compiled to C/C++; two-level plans with ultra-light low-level operators (possibly on the NIC) feeding high-level ones; heartbeats to unblock operators |
| Nile (Purdue) | streams as a datatype in the Predator ORDBMS; positive/negative tuples; shared window joins; round-robin scheduling |
| System S / SPADE (IBM) | distributed processing elements over a data fabric; fusion/fission compilation; content-based partitioning |
| NiagaraCQ | expression-signature grouping of many queries (`complex-event-processing.md` §6); selection pull-up for sharing |
| Spark Streaming | discretized streams (micro-batches of RDDs) with lineage-based recovery |
| S-Store | streaming on H-Store with ACID transactions over streams, windows and tables |

Big-stream systems (EDBS "Big Stream Systems") brought MapReduce-style key
partitioning to streaming. HOP pipelined map→reduce and had wall-clock windows
only. S4 creates one processing element per key with static placement, lossy
checkpoints and no load balancing. Storm has spouts and bolts, shuffle and
fields grouping, and acknowledgment-based replay. As of the EDBS writing,
Storm offered no native windows or order guarantees. Spark Streaming
micro-batches trade latency (no sub-second) for throughput and lineage
recovery. It keeps order and supports incremental sliding windows with an
inverse ("subtract the expiring batch") function. The recurring lessons:
(1) key partitioning gives scale but destroys global order, so a merge must
re-establish order wherever windows depend on it; (2) static placement cannot
absorb skew.

> **Beyond EDBS:** Production engines converged on Flink's model: a
> keyed-partitioned dataflow with event-time watermarks, embedded
> per-key state (heap or RocksDB LSM), and asynchronous barrier snapshots.
> Kafka Streams and ksqlDB fold the log into the engine. Materialize and
> RisingWave run incremental view maintenance over streams (differential
> dataflow lineage for Materialize). Flink SQL and Spark Structured Streaming
> implement CQL-like semantics with explicit append and changelog result
> modes.

---

## 5. Requirements checklist (from "The 8 requirements of real-time stream processing")

Stonebraker, Çetintemel, Zdonik (SIGMOD Record 2005), referenced in several
entries, list requirements that work well as a design-review checklist. In
paraphrase: keep data moving (no mandatory storage on the path); offer a
SQL-like stream language; handle stream imperfections (late, missing,
out-of-order data); produce predictable, repeatable outcomes; integrate stored
and streaming data; guarantee safety and availability; partition and scale
automatically; process and respond with minimal latency.

---

## 6. Pitfalls specific to semantics

- **Implicit arrival-time semantics.** A planner that stamps tuples at ingress
  and windows on that stamp gives answers that change across replays and
  differ between replicas. Make the time domain an explicit property of every
  stream.
- **Rows windows with ties.** `[Rows N]` over equal timestamps is
  non-deterministic. Either define a total order (timestamp, sequence
  number) or forbid the construct.
- **Rstream misuse.** Rstream over a large relation re-emits everything every
  instant. Lint for it.
- **Silent Istream on non-monotone queries.** Emitting only inserts from an
  aggregate over a sliding window loses the "old value is gone" information.
  Downstream consumers then double count.
- **Table-lookup version drift.** Stream ⋈ table under processing time
  breaks exactly-once replay (`fault-tolerance-and-exactly-once.md`).

Sources: EDBS "Data Stream" (p.853), "Stream Models" (p.3768), "Continuous
Query" (p.630), "Stream-Oriented Query Languages and Operators" (p.3802),
"Data Stream Management Architectures and Prototypes" (p.854), "Stream
Processing" (p.3771), "Big Stream Systems" (p.273), "Nonrelational Streams"
(p.2505), "Window-Based Query Processing" (p.4695), "Transactional Stream
Processing" (p.4205).
