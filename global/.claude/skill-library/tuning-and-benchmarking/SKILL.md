---
name: tuning-and-benchmarking
description: "Use when designing, implementing or reviewing DBMS performance engineering: physical design advisors (index/MV/partition selection, what-if hypothetical indexes), online and self-tuning (feedback histograms, LEO, memory brokering, cache replacement), workload management and admission control, application/schema/lock/physical-layer tuning, queueing models, monitoring metrics, or benchmark design and methodology. Triggers on index advisor, DTA, AutoAdmin, hypothetical index, HypoPG, candidate generation, index merging, knapsack, autonomic, self-driving, knob tuning, MPL, admission control, throttle, TASM, wait events, buffer hit ratio, Little's law, MVA, lock thrashing, hot spot, denormalization, N+1 queries, connection pool, RAID, TPC-C, TPC-H, TPC-DS, YCSB, data generator, Zipf, warmup, steady state, p99. Apply even when phrased as 'why is it slow', 'which indexes should we add', 'can the engine tune itself', or 'is this benchmark fair'."
---

# Tuning and Benchmarking

This skill owns performance as an engine *feature* (advisors, self-tuning
loops, workload management) and as an engineering *discipline* (models,
monitoring, benchmarks). The single most important idea: **every tuning
decision must be evaluated by the same oracle that will execute it** — the
optimizer's own cost model for physical design, measured response-time
decomposition for diagnosis, and a controlled, validated benchmark for
claims. Tools with a private model of the engine drift out of sync with it.

## Mental model

```
             observe                  predict                    react
 workload ──► counters, wait events ─► what-if (optimizer, ──► search config space,
 (classes,    per-statement stats,     queueing model,         enact safely (online DDL,
  rates,      plan hashes, feedback    simulation)             throttles, memory grants),
  params)     cardinalities                                    verify, revert on regression
                     ▲                                                    │
                     └───────────────── closed loop ◄─────────────────────┘
 perf = F(configuration, workload); self-management solves the inverse problem:
 cheapest configuration meeting per-class SLAs (p95, throughput, availability).
```
Time scales separate the mechanisms: memory and admission (seconds, inside
the engine), statistics and online indexes (minutes–days), physical design
and capacity (weeks, advisor tools). Benchmarks are the controlled
experiment that validates any of them.

## Core invariants

1. A physical-design recommendation's benefit is computed with the engine's
   optimizer under a configuration overlay; no separate cost model.
2. Hypothetical structures are invisible to normal compilation and never
   enter an executable plan cache.
3. Cost of DML in what-if includes maintenance of every (hypothetical)
   index/view on the touched tables.
4. Adding a structure never raises the estimated cost of a read-only
   statement (the optimizer may ignore it); violations mean non-deterministic
   costing.
5. Every deployed recommendation is used by ≥1 executed plan within the
   observation window, or it is flagged (oracle divergence or drift).
6. Online tuning has hysteresis: create and drop thresholds include
   transition cost; a structure cannot flap faster than its build cost is
   amortised.
7. Automatic tuning actions are reversible and verified against a measured
   baseline per statement.
8. Feedback statistics stay consistent: sel(a∧b) ≤ min(sel(a), sel(b));
   feedback from early-terminated operators is not treated as full counts.
9. Admission control keeps MPL at or below the throughput peak; queued
   requests wait outside the engine holding no locks/memory/worker threads.
10. Measured throughput never exceeds 1/D_max (bottleneck bound); if it does,
    the measurement is wrong.
11. Every benchmark run is reproducible (seeds, configuration, data,
    scripts) and correctness-checked before its performance counts.
12. Latency is reported as distributions over a steady-state interval that
    excludes warm-up and spans background cycles.

## Design space & trade-offs

| Decision | Option | Wins when | Cost / risk |
|---|---|---|---|
| Advisor search | bottom-up greedy(m,k) | small storage budget | blind to pairwise-only benefits; many what-if calls |
| | knapsack by benefit/size + swap (DB2 Advisor) | need speed; optimizer emits candidates | non-additive benefits misattributed |
| | top-down relaxation | large budget; want a lower bound | relaxation set must cover merges/prefixes |
| | integer programming (CoPhy) | want optimality gap | needs decomposable costs (INUM-style) |
| Scope | integrated (indexes+MVs+partitioning) | always preferred | larger space; needs alignment constraints |
| | staged | never by design | redundant, suboptimal, arbitrary budget split |
| Tuning mode | offline advisor | stable workload, idle window | stale between runs |
| | online (rent-or-buy, work function) | shifting workload | transition cost, flapping, needs online DDL |
| Knob strategy | trade-off elimination (LRU-K/ARC, B+-tree only) | robust algorithm exists | second-order parameters must be robust |
| | feedback control (MPL) | no causal model | instability under bursts |
| | learned (GP/RL/bandits) | rich telemetry | extrapolation; safe exploration |
| Load control | per-class throttles + delay queue | mixed workloads | delay time becomes SLA component |
| | conflict-ratio admission | data-contention thrashing | needs lock-table introspection |
| Isolation tuning | SI/RC snapshot reads | long readers | write skew; know actual anomaly set |
| | chopping / split interactive txns | known conflict graph | correctness depends on workload knowledge |
| Load generator | closed loop | terminal models, TPC-C style | hides overload latency |
| | open loop | latency SLOs | must handle unbounded queues |
| Data | synthetic (Zipf, correlated) | controlled sweeps, scale | unrealistic unless calibrated |
| | real (JOB, traces) | estimator/optimizer realism | representativeness, privacy |

## Algorithms that matter

**What-if candidate pipeline** (details: `references/physical-design-advisors.md`)
```
for q in compress(W): C_q := best config for {q} via what-if        # per-query candidates
cand := ∪ C_q ∪ merge/prefix(∪ C_q)                                  # workload-level candidates
memo cost(q, C ∩ relevant(q))                                        # atomic/relevant-subset caching
C := greedy(m,k) | knapsack+swap | relax-from-ideal under budget B
validate: build on clone, replay, compare predicted vs measured
```
Optimizer calls dominate: O(k·|cand|·|W|) naive; caching and plan reuse are
as important as the search.

**Online index (rent-or-buy)**: accumulate per-query what-if benefit of
missing index I; build when Σbenefit ≥ create_cost (deterministic
2-competitive); drop when accumulated maintenance penalty ≥ threshold. Many
interacting indexes → metrical task system; work-function algorithm on
weakly interacting groups (WFIT).

**LRU-K**: evict max backward K-distance (∞ if < K refs); K=2 resists
scans and separates frequency classes; O(log n) heap — or 2Q/ARC at O(1).

**MVA** for closed QNMs (O(N·K)): R_k(n) = D_k(1 + Q_k(n−1)); X = n/(ΣR_k + Z);
Q_k = X·R_k. Operational bounds: X ≤ min(N/(D+Z), 1/D_max).

**Lock thrashing**: P_conflict ≈ (M−1)k/(2D); α ≈ A·k·P_c with A ≈ 1/3;
thrashing at α* ≈ 0.226 ⇒ (M−1)k²/D ≈ 1.4. Contention ∝ k²: shorten
transactions first, then cap MPL.

**Self-tuning histogram (STHoles)**: intercept result stream, count tuples
per bucket, drill holes for query regions, merge similar buckets to budget;
ISOMER replaces counting by max-entropy consistency.

**Zipf generator**: precompute generalised harmonic normaliser, sample by
inversion/rejection, permute ranks with a bijective hash; seeds per
(table, chunk) for parallel deterministic generation.

## Failure modes & classic bugs

- Advisor recommends indexes never used: external cost model, or what-if stats built differently from real ones.
- What-if plan leaks into the plan cache and runs against a nonexistent index.
- DML maintenance not costed → "free" indexes; batch loads slow by 10× after deployment.
- Staged selection: index chosen, then a view that makes it redundant.
- Online tuner flapping (create/drop cycles): thresholds ignore build cost, or periodic workload.
- Statistics feedback overcorrects; plans oscillate; plan-cache invalidation storms.
- Memory broker shrinks a work area below operator minimum → spill-path bugs.
- Admission queue inside the engine (waiters already hold latches/memory/threads).
- Hit ratio "improves" while performance drops (excess logical reads).
- Hot counter row / B-tree right edge serialises inserts; sequence gaps break no-gap rules.
- Benchmarks: coordinated omission, warm-up in the interval, single run, fsync off on one
  side, uniform data hiding estimator bugs, unvalidated results, benchmark-specific paths.

## Implementation checklist (C/C++/Rust)

- Catalog overlay for hypothetical objects: session-scoped, copy-on-write
  map from object id → metadata with `is_hypothetical` bit checked by plan
  cache admission; what-if statistics produced by the same stats builder on a
  sample.
- Optimizer API: `optimize(stmt, ConfigView) -> (cost, used_structures,
  access_path_requests)`; deterministic for identical inputs (seeded tie
  breaks) so memoisation is sound.
- Advisor memo keyed on (stmt fingerprint, sorted ids of relevant
  structures); bounded LRU; parallelise per statement with work stealing.
- Telemetry: per-thread counter blocks aggregated lazily (no global
  atomics); every blocking point tagged with a wait-class enum; per-statement
  stats keyed by normalised fingerprint + plan hash; histograms (HDR-style)
  for latency.
- Resource-adaptive operators: work-area grant object with
  `min/one_pass/optimal`, `on_shrink()` callback, spill paths fuzzed under
  random shrink schedules.
- Admission controller: per-class token pools (throttles) checked before
  thread/memory allocation; FIFO delay queue with per-class limits;
  exceptions evaluated at step boundaries with demote/abort actions.
- Online DDL for tuning actions at low I/O priority; action log with
  before/after metrics and one-step revert.
- Cache replacement: LRU-K history table bounded by retained-information
  period (five-minute rule); or ARC with ghost lists.
- Benchmark driver: open-loop scheduler using intended send times;
  per-(chunk) seeded generators; result validators; config and environment
  capture written next to results.

## How to test it

- Advisor oracles: B → ∞ converges to union of per-query optima; B = 0
  returns required structures; brute force on tiny schemas/workloads must
  match or bound the heuristic; monotonicity of read-only costs.
- Recommend-then-measure on a clone: predicted vs actual improvement per
  query; flag regressions (cardinality misestimates surface here).
- Online tuner: adversarial periodic workloads to detect flapping; check
  competitive bound empirically against offline OPT on recorded traces.
- Feedback stats: property tests for consistency; inject biased feedback
  (LIMIT, early-out) and assert it is discounted.
- Load control: simulate bursts; assert throughput never falls below the
  capped-MPL plateau; verify delay-queue accounting.
- Models: MVA vs discrete-event simulation on the same parameters; bounds
  vs measured throughput.
- Benchmarks: rerun with different seeds; perturb constants/names to catch
  benchmark-specific paths; validate generator output distributions.

## Expert review questions

1. Is benefit computed by the production optimizer, with the same
   statistics path, or by a side model?
2. How many optimizer calls does a tuning session make for |W| statements
   and |cand| candidates, and what caches cut that?
3. How are index interactions (substitutes, complements) handled — is
   greedy's lack of guarantee acknowledged?
4. Are indexes, MVs and partitioning searched jointly, with alignment
   constraints?
5. What stops the online tuner from flapping, and what is the revert path?
6. Which per-class SLA metric (quantile) does the self-tuning loop
   optimise, and how is it measured?
7. Where do throttled requests wait, and what resources do they hold?
8. Is the dominant wait for the violated class identified before any knob
   is touched?
9. What is D_max and does the claimed throughput respect 1/D_max?
10. What is (M−1)k²/D for the hot path, and would chopping or shortening
    beat raising concurrency?
11. Is the hit ratio being used as a goal? What replaces it?
12. Is the load generator open or closed, and is coordinated omission
    handled?
13. How was steady state detected, how many runs, what variance?
14. Does the data generator model skew and correlation, and was its output
    validated (including implicit constraints)?
15. Would the result survive renaming columns and changing constants?

## Go deeper

- `references/physical-design-advisors.md` — advisor/what-if API, candidates, enumeration, partitioning, Teradata PI/PPI.
- `references/online-and-self-tuning.md` — self-management loop, online indexes, memory, feedback stats, LRU-K/ARC, WLM/TASM.
- `references/application-schema-and-layer-tuning.md` — set-oriented access, bulk load, pooling, denormalisation, hot spots, chopping, I/O, RAID.
- `references/performance-models-and-monitoring.md` — operational laws, MVA, MPL model, lock thrashing, OCC, metrics that matter.
- `references/benchmark-design-and-methodology.md` — benchmark/microbenchmark design, TPC/YCSB/JOB, generators, methodology.
- `references/edbs-entries.md` — every EDBS entry used, with pages.

## Related skills

- `query-engine-testing` — harness mechanics and CI gating; here benchmark design, methodology, tuning.
- `query-optimizer` — cost model and search; here used as what-if oracle (hooks required).
- `storage-and-indexing`, `index-structures-catalog` — how structures work; here which to build.
- `cardinality-and-statistics` — histogram construction; here feedback refinement as a tuning loop.
- `materialized-views-ivm` — maintenance and rewriting; here view selection under budget.
- `concurrency-control-theory`, `transactions-and-recovery`, `recovery-and-durability` — protocol correctness; here contention tuning, isolation choice, log placement.
- `storage-devices-and-io` — device/RAID internals; here provisioning choices.
- `parallel-database-systems`, `parallel-distributed-execution`, `distributed-dbms-design` — partitioning/skew mechanics; here partitioning as design decision, fork-join skew.
- `olap-and-warehouse-engines` — warehouse execution; here warehouse physical design.
- `dbms-architecture` — where monitor, advisor and WLM components sit.
- `temporal-databases`, `stream-processing-engines`, `beyond-relational-engines` — domain benchmarks (τBench, Linear Road, YCSB/LDBC).
- `edbs-reference` — pull full entries.

## Grounding

EDBS (2nd ed., 2018): Database Tuning Using Combinatorial Search (p.985);
Database Tuning Using Online Algorithms (p.989); Database Tuning Using
Trade-Off Elimination (p.993); Self-Management Technology in Databases
(p.3374); Physical Database Design for Relational Databases (p.2759);
Optimization and Tuning in Data Warehouses (p.2619); Index Tuning (p.1851);
Schema Tuning (p.3308); Application-Level Tuning (p.129); Tuning Concurrency
Control (p.4252); Physical Layer Tuning (p.2765); Performance Analysis of
Transaction Processing Systems (p.2732); Performance Monitoring Tools
(p.2741); Database Benchmarks (p.936); Application Benchmark (p.122);
Microbenchmark (p.2255); Benchmark Frameworks (p.267); Data Generation
(p.772); Real and Synthetic Test Datasets (p.3110); tBench (p.3877);
Administration Wizards (p.69); Database Administrator (p.935).

Papers/systems: Chaudhuri & Narasayya VLDB 1997, SIGMOD 1998 (AutoAdmin, what-if);
Valentin et al. ICDE 2000 (DB2 Advisor); Agrawal et al. VLDB 2004 (DTA); Zilio et al.
VLDB 2004 (DB2 Design Advisor); Bruno & Chaudhuri SIGMOD 2005, ICDE 2007; Stillger et
al. VLDB 2001 (LEO); Bruno, Chaudhuri, Gravano SIGMOD 2001 (STHoles); O'Neil, O'Neil,
Weikum SIGMOD 1993 (LRU-K); Dageville & Zait VLDB 2002; Weikum et al. 1994 (COMFORT);
Thomasian TODS 1993; Franaszek, Robinson, Thomasian TODS 1992 (WDL); Lazowska et al.
1984; Gray, *Benchmark Handbook* 1993; Cooper et al. SoCC 2010 (YCSB); Shasha & Bonnet 2002.
