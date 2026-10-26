# Iterator model, pipelining, pipeline breakers and memory budgets

Scope: the runtime contract between physical operators, how a plan decomposes
into pipelines, which operators block and why, how memory budgets decide
one-pass vs two-pass vs multi-pass algorithms, and how modern engines
(vectorized, compiled, morsel-driven) re-implement the same contract.

---

## 1. The iterator (Volcano) contract

Every physical operator — including access methods (heap scan, index scan) —
exposes one uniform interface, so any producer can be plugged under any
consumer and the plan becomes a composable dataflow graph:

| Call | Responsibility | Typical work |
|---|---|---|
| `open(params)` | Allocate state and buffers, receive arguments (predicates, correlation bindings, scan ranges), call `open()` on children | Build hash table (if the operator chooses to block here), position index cursor |
| `next()` | Pull from children until one output unit (tuple or batch) can be returned, update consumption state | Probe, merge, filter, compute expressions |
| `close()` | Release state (memory, spill files, pins, latches), call `close()` on children | Free hash tables, delete temp runs |
| `rescan(params)` (practical extension) | Restart output, possibly with new parameter bindings, without a full close/open | Inner of nested-loop join, correlated subplan |

Properties the model buys you: a single thread can run the whole plan (no
inter-operator IPC, no synchronization between operators), only the
in-flight items occupy memory, evaluation is lazy (nothing beyond what the
root demanded is computed), and data copies are minimised because a parent
reads the child's output in place. Parallelism and networking are hidden
inside special *exchange* iterators (section 6), so ordinary operators stay
single-threaded code.

### Contract invariants (make them assertions)

1. **State machine.** Legal sequences: `open (next)* close`, with `rescan`
   only between `open` and `close`. A debug build should track state per
   operator and abort on `next` before `open` or after `close`.
2. **Sticky end-of-stream.** After `next` returns EOF, every further `next`
   returns EOF and does no I/O. Parents (merge join, NLJ, UNION) rely on this.
3. **Close exactly once, always.** `close` runs on normal completion, on
   early termination (LIMIT satisfied, EXISTS found a row, semijoin matched,
   client cancelled) and on error unwinding. Leaked spill files and pinned
   buffer pages are the symptom of violations.
4. **Output lifetime.** A returned tuple/batch is valid until the next call
   on that operator (or until `close`). A parent that needs it longer (sort,
   hash build, window buffer) must copy or take a reference count. Returning
   a pointer into a pinned page and unpinning on the next call is the classic
   source of use-after-unpin bugs.
5. **Rescan equivalence.** `rescan(p)` followed by draining yields exactly the
   multiset `open(p)` would; cached state that depends on parameters must be
   invalidated when bindings change, and may be reused when they do not.
6. **Batch variant.** If `next` returns batches, decide and document whether
   an empty non-EOF batch is legal. Either forbid it (producer loops until it
   has at least one row) or require every consumer to loop; mixing the two
   conventions produces premature-EOF bugs after highly selective filters.
7. **Schema stability.** Every unit returned by an operator conforms to the
   schema the planner computed (types, nullability, column order).

### Where does the blocking work happen?

A blocking operator may consume its input inside `open` (classic Volcano
sort) or on the first `next`. Doing it lazily on first `next` is preferable:
`open` stays cheap, a plan that is cancelled before producing rows does no
work, and the parent controls when memory is first committed (important for
memory brokering across simultaneously open operators).

---

## 2. Materialization vs pipelining; demand-pull vs producer-push

**Materialized evaluation** writes each operator's full result (to memory or
disk) before the consumer starts. **Pipelined evaluation** hands rows to the
consumer while the producer is still running, avoiding temporaries.

| Dimension | Demand-driven (pull) | Producer-driven (push) |
|---|---|---|
| Control | Parent calls child `next` | Child calls parent `consume(row)` or writes into a bounded buffer |
| Threads | Natural single-thread execution | Natural for one thread per pipeline, or task-based schedulers |
| Early termination | Trivial: stop pulling | Must propagate a "stop" signal upstream |
| Multi-consumer (DAG plans, shared subexpressions) | Awkward: one parent drives, others need spooling | Natural: producer pushes to several consumers |
| Code generation | Each `next` is a call boundary | Pipelines fuse into tight loops (see 7.2) |
| Back-pressure | Implicit | Buffer-full blocks producer |

EDBS notes that pull is the more common choice historically because it is
easier to implement and lets one process run the entire plan. Push buffers
are bounded: a producer stops when its output buffer fills, which is the push
model's back-pressure.

---

## 3. Pipeline breakers (stop-&-go operators)

A **stop-&-go** (non-pipelineable) operator cannot emit its first output row
until it has consumed all of (some) input. It splits the plan into
**pipelines**: maximal chains of operators through which a row flows without
being stored.

Be precise about *which input* blocks — this decides scheduling and memory:

| Operator | Blocking on | Streaming on | Notes |
|---|---|---|---|
| Sort | entire input | output (final merge can be pipelined into the parent) | Output side is a pipeline source |
| Hash join | build input | probe input | The probe side is fully pipelined; only the build is a breaker. EDBS classes the whole operator as stop-&-go because probing waits for build completion |
| Sort-merge join | inputs that need sorting | the merge itself | With pre-sorted inputs (clustered index, upstream sort) the join is fully pipelined |
| Hash aggregation (GROUP BY) | entire input | — | Unless the input is grouped/sorted on the keys |
| Stream (sorted) aggregation | one group | across groups | Memory bounded by one group's state |
| Hash DISTINCT | nothing | everything | A row is emitted when its key is first inserted — non-blocking, but memory grows with distinct count |
| UNION ALL | nothing | both | |
| INTERSECT / EXCEPT (hash) | one side (the build) | the other | EXCEPT must build the subtrahend |
| Window | one partition (sorted) | across partitions | After a global sort, partition-at-a-time; frame evaluation may need only a bounded buffer for ROWS frames |
| Top-N (heap) | entire input | — | Memory O(N) |
| NLJ with materialized inner | inner | outer | |
| Symmetric hash join | nothing | both | Pays with two hash tables; basis of adaptive processing |

Consequences an engine builder must act on:

- **Operator-level (pipeline) parallelism is capped by breakers.** Pipelines
  in relational plans are short and their stages unbalanced, so pipelined
  parallelism alone rarely gives large speed-ups; partitioned (intra-operator)
  parallelism does the heavy lifting (DeWitt & Gray, CACM 1992).
- An optimizer that prizes response time or operator parallelism may choose
  a more expensive but pipelineable operator (symmetric hash join instead of
  sort-merge; index NLJ instead of hash join for a LIMIT query).
- **Concurrent memory demand is a plan-shape property.** In a right-deep tree
  of hash joins, all build tables are alive at once while one long probe
  pipeline streams the fact input; in a left-deep tree at most two hash tables
  coexist (one being probed, one being built from the result). The
  scheduler must sum the budgets of all breakers that are simultaneously
  active, not just the most expensive one (Schneider & DeWitt, VLDB 1990).

### Pipeline throughput model

Model a pipeline of N stages for a job that takes T time units unpipelined.
Ideal: latency ~T, occupancy (time between accepting successive jobs) T/N,
so throughput rises N-fold. Real pipelines carry a per-stage overhead plus
imbalance k: occupancy becomes T/N + k and latency T + kN. Normalised
throughput is 1/((T/N + k)/T); the penalty grows with depth, which is why
deep, fine-grained operator pipelines (one thread per operator, queues
between them) underperform. EDBS's illustration: roughly 1% overhead or
imbalance per stage costs about 10% of the ideal throughput at depth 10. The
engineering lesson for executors: fuse stages (vectorization, compilation)
instead of putting a queue between every pair of operators, and size work
units so that per-handoff cost is amortised.

---

## 4. Memory budgets: one-pass, two-pass, multi-pass

Notation: B(R) pages of R, T(R) tuples, M pages of memory granted to the
operator. I/O counts exclude writing the final output.

| Operator | One-pass needs | One-pass I/O | Two-pass needs | Two-pass I/O |
|---|---|---|---|---|
| σ, π (no dedup) | 1 page | B | — | — |
| δ / γ (dedup, grouping) | M ≥ footprint of distinct groups | B | sort- or hash-based: B ≤ ~M² | ~3B |
| ∪, ∩, − (set semantics) | min(B(R),B(S)) ≤ M | B(R)+B(S) | sort: B(R)+B(S) ≤ ~M²; hash: min ≤ ~M² | ~3(B(R)+B(S)) |
| ⋈ (equi) | min(B(R),B(S)) ≤ M | B(R)+B(S) | sort-merge with merged run phases: B(R)+B(S) ≤ ~M²; hash: min ≤ ~M² | ~3(B(R)+B(S)) |
| ⋈ (block NLJ) | — | B(R) + ⌈B(R)/(M−2)⌉·B(S) | — | — |

k passes extend the reach to B ≤ ~M^k. Practical rules:

- **Reserve buffers.** Block NLJ keeps M−2 pages of the outer, one input page
  for the inner, one output page; partitioning keeps one output buffer per
  partition plus input; merging keeps one buffer per run plus output.
  Double-buffering (two pages per run) trades fan-in for overlapped I/O.
- **Hash table overhead.** An in-memory hash table on R needs about F·B(R)
  pages with a fudge factor F > 1 for pointers, buckets and load factor
  (Shapiro, TODS 1986). Plan with F, measure F.
- **Two-pass hash needs about sqrt(F·B(build)) pages**; below that, partition
  recursively (multi-pass) with an independent hash function per level.
- **Grant vs actual.** The optimizer reserves a grant from estimates; the
  operator must handle actual > grant by spilling (never by OOM) and should
  report actual peak usage so the next execution (or a feedback loop) can
  correct the grant.
- **Brokering.** With several breakers active (section 3), divide memory by
  phase: an operator whose build phase is over can release its input buffers.
  Static per-operator grants are simple and predictable; dynamic brokering
  wins under concurrency but needs operators that can shrink mid-flight
  (hybrid hash join that can evict a resident partition is the canonical
  example).

### Streaming (one-pass) algorithms proper

In the theory sense (EDBS "One-Pass Algorithm"), a one-pass algorithm reads
items once, left to right, keeping a synopsis whose size and per-item time
should be sublinear — ideally polylogarithmic — in the input size. Many exact
problems provably need linear memory deterministically (lower bounds via
communication complexity), but randomized sketches and samples give
approximate answers in sublinear space. Engine uses: distinct-value and
self-join-size estimates maintained during loads/scans (Alon, Matias &
Szegedy, JCSS 1999 for frequency moments), memory-bounded approximate
aggregates, and "a few passes" algorithms when a small number P of sequential
passes is affordable.

> **Beyond EDBS:** HyperLogLog (Flajolet et al., 2007) is the de facto NDV
> sketch in production engines (mergeable registers, ~1–2% error at a few KB);
> Count-Min (Cormode & Muthukrishnan, 2005) for heavy hitters. Mergeability is
> the property that matters for parallel execution: partial sketches built per
> partition must combine losslessly.

---

## 5. Plan shape and the executor

Plans are trees of physical operators whose leaves are base relations (access
paths); edges are dataflow. With shared subexpressions the plan becomes a DAG,
which a pure pull model cannot drive without spooling (materialise once, read
many). Shape vocabulary: *left-deep* (every join has a base relation as its
inner/right input), *right-deep*, and *bushy* (joins of join results). Greedy
join enumerators tend to produce bushy trees, which can hurt pipelining for
OLTP-style queries with small intermediates; left-deep trees maximise
pipelining of the outer.

Interpretation vs generation: some systems interpret the plan tree directly
at runtime (EDBS cites Informix); System R generated code for a "database
machine" from the chosen plan, enabling compiler-style reductions in path
length and data copying. The modern descendants are section 7.

---

## 6. Exchange: encapsulating parallelism

Graefe's exchange operator (SIGMOD 1990; Volcano, TKDE 1994) is an iterator
whose `open` forks producer threads/processes for the subtree below it and
whose `next` reads from a flow-controlled queue. It provides:

- **Vertical (pipeline) parallelism:** producer and consumer run concurrently.
- **Horizontal (partitioned) parallelism:** N producer instances, each over a
  partition, with a routing function (hash, range, round-robin, broadcast) on
  the way out.
- **Encapsulation:** all other operators remain single-threaded and unaware.

Invariants: every producer must deliver an end-of-stream marker per consumer
(a consumer's EOF = all producers' EOF); flow control bounds memory; ordering
across producers is lost unless the exchange performs a merge (order-
preserving exchange). Partitioned parallelism detail belongs in
`parallel-distributed-execution` / `parallel-database-systems`.

---

## 7. Beyond EDBS: modern execution models

> **Beyond EDBS:** the tuple-at-a-time iterator pays an interpretation cost —
> one virtual call per operator per tuple plus per-tuple expression
> interpretation — that dominated once data fit in memory. Two families
> replaced it; both keep the logical iterator contract.

### 7.1 Vectorized execution (MonetDB/X100, Boncz, Zukowski & Nes, CIDR 2005)

- `next()` returns a vector (typically ~1K values per column, sized to stay
  cache-resident) instead of a tuple.
- Work is done by *primitives*: type-specialised tight loops over arrays
  (`select_lt_int64_col_val`, `hash_int64`, `gather`), which the compiler can
  unroll and SIMD-ize. Interpretation overhead is paid once per vector.
- Filters produce **selection vectors** (indices of qualifying rows) rather
  than compacting data; later primitives iterate the selection vector.
- Used by Vectorwise/Actian, DuckDB, Velox, ClickHouse-style engines, and the
  batch-at-a-time Arrow engines (see `columnar-arrow-layout`).

### 7.2 Data-centric compilation (HyPer, Neumann, VLDB 2011)

- The plan is cut at pipeline breakers; each pipeline is compiled (LLVM) into
  one loop that starts at a source (scan or materialised breaker), applies
  every operator in the pipeline to a tuple held in CPU registers, and ends
  by materialising into the next breaker (hash table insert, sort buffer,
  aggregation slot).
- Code generation via a **produce/consume** protocol: `produce()` asks a
  subtree to generate the loop, `consume(attrs)` lets the parent inject the
  code to run per tuple. This is push execution at compile time.
- Compilation latency matters for short queries; systems use tiered/adaptive
  compilation (interpret first, compile hot pipelines).

### 7.3 Comparing them

Kersten et al. (VLDB 2018) implemented both in one testbed: neither dominates.
Compiled code wins on computation-heavy pipelines (fewer instructions, values
stay in registers); vectorized code wins when memory stalls dominate (e.g.,
large hash-join probes) because the loop over a vector exposes independent
misses the CPU can overlap, and it is easier to profile and to combine with
adaptive per-vector decisions. Both are far ahead of tuple-at-a-time.

### 7.4 Morsel-driven parallelism (Leis, Boncz, Kemper & Neumann, SIGMOD 2014)

- Input of each pipeline is split into small *morsels* (on the order of 10^4–
  10^5 tuples); a dispatcher hands morsels to worker threads pinned to cores.
- Workers run the whole pipeline on their morsel and write into shared or
  thread-local breaker state; when a pipeline's morsels are exhausted the next
  pipeline (which depends on the breaker) becomes runnable.
- Degree of parallelism is elastic at morsel granularity (no plan-time DOP),
  load balancing is automatic (skew → more morsels taken by idle threads),
  and morsels are dispatched NUMA-locally where possible.
- Contrast with exchange-based (plan-driven) parallelism: exchange fixes DOP
  at plan time and needs repartitioning between operators; morsel-driven
  parallelism shares data structures across threads instead.

> **Beyond EDBS:** DuckDB uses vectorized push-based pipelines with
> morsel-style task scheduling; Apache DataFusion exposes pull-based async
> streams of Arrow record batches per partition (`ExecutionPlan::execute` →
> `SendableRecordBatchStream`) with explicit repartition operators. Both still
> satisfy the invariants of section 1 at the batch level.

---

## 8. Testing the contract

- **State-machine fuzzer:** wrap every operator in a checking decorator that
  asserts legal call order, sticky EOF, close-once, and that returned memory
  is not touched after the next call (poison freed buffers in debug builds).
- **Early-termination matrix:** run each operator under LIMIT 0/1/k, EXISTS,
  semijoin and client cancellation; assert zero leaked spill files, pins and
  memory-tracker bytes after `close`.
- **Rescan tests:** NLJ with a correlated inner over each operator type; the
  inner's output must equal a fresh open for each binding.
- **Memory-limit sweeps:** for every operator with a spill path, run at grants
  of {just above one-pass need, exactly at it, just below it, ~sqrt(B), below
  sqrt(B)} and compare results with an unlimited-memory oracle.
- **Batch-size sweeps:** vector sizes 1, 2, prime numbers, and huge; empty
  batches injected between non-empty ones.

Sources: EDBS entries Iterator (p.2042), Pipelining (p.2768), Pipeline
(p.2767), Stop-&-Go Operator (p.3720), One-Pass Algorithm (p.2556), Query Plan
(p.3020), Query Processing (p.3026), Query Processing (in Relational
Databases) (p.3027), Evaluation of Relational Operators (p.1348).
