# Online tuning, self-management and workload management

Offline advisors assume the captured workload repeats and that there is an
idle window to run them. Neither holds for multi-tenant, cloud, or shifting
workloads. Self-management closes the loop inside (or beside) the engine.
This file covers the general framework, the five paradigms that actually
work, the concrete algorithms (memory brokering, online index tuning,
feedback histograms, learning optimizers, cache replacement), and workload
management / admission control.

## 1. The framework: configuration × workload → performance

Model each component (buffer manager, lock manager, optimizer statistics,
physical design, scheduler) as a function

```
perf = F(configuration, workload)
```

- configuration: hardware, boot-time knobs (lock-escalation threshold,
  memory-pressure policy), physical design, backup/replication settings,
  run-time policies (scheduling, class priorities, memory allocation,
  load shedding).
- workload: statement/transaction classes, frequencies, arrival rates by
  period, arrival sequences, co-occurrence (OLTP + batch), parameter
  distributions.
- performance: throughput and response-time *distribution* per class
  (quantiles, not means), reliability, availability, performability
  (performance in degraded mode), robustness to attack.

Self-management solves the **inverse problem**: given goals (e.g., class A
p95 ≤ 1 s; ≤ 10 min downtime/yr) and the observed workload, find the
cheapest configuration that meets them; re-solve when the workload shifts.
Goals expressed this way are SLAs / QoS contracts.

Design rule: model per component, then compose. System-wide prediction needs
composable workload models and composable performance models; a monolithic
model of the whole engine is not maintainable or testable.

## 2. Observe – predict – react

| Step | What it needs in the engine | Typical time scale |
|---|---|---|
| Observe | low-overhead introspection: counters, per-statement stats, event tracing, drift/anomaly detection | continuous |
| Predict | what-if evaluation of current and alternative configs (optimizer what-if, queueing model, simulation) | seconds to hours |
| React | search for a better configuration, triggered by goal violation (or predicted violation) or by objective loss beyond a threshold; enact safely | seconds (memory) to weeks (capacity) |

Short time scales (memory pressure, admission) demand integration inside the
engine; long-horizon decisions (capacity, physical design) can live in
external advisors. Trigger designs: (a) threshold on estimated profit of a
new configuration vs current, net of transition cost; (b) continuous
observe/predict/react modules.

## 3. The five paradigms

| Paradigm | Use when | Examples | Main risk |
|---|---|---|---|
| Trade-off elimination | a knob exists only because no single algorithm was robust | LRU-K/2Q/ARC replace replacement-policy knobs; B+-tree only; ~1 MB stripe unit; track-sized pages | introduced second-order knobs must be robust |
| Static optimization | inputs known, offline | physical design, backup planning | cost oracle divergence; search blow-up |
| Stochastic optimization | inputs are distributions | capacity planning (disks, cache size for a response-time goal) via queueing | model assumptions (Poisson, exponential) |
| Online optimization | inputs arrive over time, need fast incremental answers | work-area memory, feedback histograms, online index tuning | thrashing between configurations |
| Feedback control | no causal model, only measurements | MPL/admission control, load shedding | instability, oscillation under bursts |
| Statistical learning | rich event logs, unknown functional form | diagnosis, root cause, knob tuning, learned estimates | feature design; extrapolation outside training distribution |

(Trade-off elimination is a design-time thinking tool, not an algorithm; the
others are run-time mechanisms.)

## 4. Trade-off elimination, worked through

Questions to ask of every knob: why do alternatives exist? Is workload
variance really large enough to justify the knob? Do options differ a lot?
Is any option catastrophic somewhere? Is there an option near-optimal
everywhere?

- **Page size**: larger pages amortise positioning, smaller pages waste less
  memory. With large memories and controllers that read whole tracks, a
  page around a track (~100 KB in the entry's era) is near-optimal for both.
- **Striping unit**: small units maximise parallelism of a single large read
  but burn arm time on every disk; large units raise throughput. For the DB
  mix (single-block random + large scans), ~1 MB units give near-optimal
  throughput while still parallelising scans.
- **B+-tree vs hash**: hashing gives one access and randomisation against
  skew; B+-trees give ranges. With high fanout and inner levels always
  cached, the descent overhead is negligible and randomisation is available
  by hashing the key before inserting into the tree. A lean self-managing
  engine needs only B+-tree indexes (and hash-based join/aggregation).
- **Cache replacement** (the canonical case):
  - LFU optimal under stationary access probabilities; adapts badly to drift.
  - LRU adapts but cannot separate hot index pages from colder data pages
    (alternating PK lookups over many data pages and few index pages: LRU
    keeps equal numbers, optimal keeps index pages), and is polluted by
    read-once scan pages (fixed with optimizer hints in practice).
  - LRFU blends recency/frequency but adds weighting and aging knobs.
  - Multiple named caches per tablespace: excellent in expert hands, not
    automatable for hundreds of tables.
  - **LRU-K** (O'Neil, O'Neil, Weikum SIGMOD 1993): track timestamps of the
    last K references per page; evict the page with the largest backward
    K-distance (time since K-th most recent reference; ∞ if fewer than K).
    Equivalent to an estimate of reference probability with built-in aging;
    optimal among policies with the same history information. K=1 is LRU;
    K=2 already handles scans and frequency classes. Costs: history for
    pages not resident (retained-information period, set via the five-minute
    rule) and a priority queue (O(log n) per access).
  - **2Q** (Johnson & Shasha VLDB 1994), **ARC** (Megiddo & Modha 2004):
    two LRU lists (seen once vs seen ≥ 2 times) with migration rules; LRU-K-
    like hit ratios at O(1) cost. ARC adapts the split between lists online,
    so it has no tuning knob.
  - Lessons: analyse the trade-off; unify the modelling of access classes;
    bookkeeping that consumes the very resource being optimised can pay off,
    but bound it; any new second-order parameter must have a setting that is
    robust across workloads.

**Five-minute rule** (Gray & Putzolu 1987; Gray & Graefe 1997): keep a page
cached if it is re-referenced more often than every T seconds, with
T = (pages per MB of RAM / random accesses per second per disk) ×
(price per disk / price per MB of RAM). Use it both for sizing the cache and
for bounding LRU-K history retention. Recompute T for flash and current
prices — the ratio, not the "5 minutes", is the rule.

## 5. Online memory brokering

Problem: a fixed memory budget shared by competing work areas (hash join,
sort, group-by) of concurrently running and continuously arriving queries,
plus the buffer pool.

Mechanism (Oracle9i automatic PGA management, Dageville & Zait VLDB 2002, is
the reference design):
1. Every memory-intensive operator registers a work area with min (one-pass
   lower bound), one-pass, and optimal (in-memory) sizes, and can grow or
   shrink at run time (requires resource-adaptive operators: spill/merge
   paths that tolerate a shrinking grant).
2. A background controller periodically recomputes a global per-operator
   bound from the target total and the current set of registered work areas
   (feedback: measured total vs target).
3. Operators adopt the new bound at their next checkpoint.

Invariants: Σ granted ≤ target + bounded overshoot; no operator granted less
than its minimum (else admission must wait); shrinking must not violate
operator correctness (test spill paths under adversarial shrink schedules).
Earlier work: per-class goal-driven allocation (Brown, Mehta, Carey, Livny
VLDB 1994) and self-tuning memory for data servers (Weikum et al. 1999).

## 6. Online physical design

Offline advisors assume the representative workload repeats. Online tuning
(Bruno & Chaudhuri ICDE 2007) observes queries as they are optimized,
maintains running cost/benefit for current *and hypothetical* structures, and
creates/drops structures when the accumulated evidence justifies the
transition cost.

**Competitive analysis — the right yardstick.** An online algorithm ALG is
c-competitive if for every request sequence σ, cost_ALG(σ) ≤ c · cost_OPT(σ)
+ a, where OPT knows σ in advance.

Single index = rent-or-buy (ski rental):
```
state: no index; acc := 0
on each query q:
    acc += max(0, cost(q, without I) − cost(q, with I))   # what-if, from optimizer
    if acc ≥ create_cost(I): build I                     # deterministic 2-competitive
on each update u while I exists:
    pen += maint_cost(I, u) − benefit since last check
    if pen ≥ drop_threshold (e.g. create_cost): drop I    # symmetric rule avoids oscillation
```
Deterministic 2-competitiveness for rent-or-buy is tight; randomisation
gives e/(e−1). Many indexes with interactions = a metrical task system over
configurations (states) with transition costs; the work function algorithm
is (2N−1)-competitive in the number of states. WFIT (Schnaitter & Polyzotis
VLDB 2012) applies it after partitioning candidates into weakly-interacting
groups to keep N small; COLT (Schnaitter et al. 2006) does continuous
on-line tuning with a budget of what-if calls per epoch.

Engineering rules:
- Hysteresis is mandatory: separate create and drop thresholds, and charge
  the transition cost (build I/O, lock/latch impact, plan-cache
  invalidation) into the decision.
- Build online (non-blocking index build) and at low priority, or the
  tuning action becomes the outage.
- **Alerter** (Bruno & Chaudhuri VLDB 2006): a lightweight check that bounds
  the improvement a full tuning session could achieve from information
  already gathered during normal optimization, so the expensive advisor runs
  only when worthwhile.
- **Verify and revert** (production lesson): after creating an index, compare
  measured per-query performance against the pre-change baseline and revert
  on regression.

> **Beyond EDBS:** Azure SQL Database's automatic indexing (Das et al.
> SIGMOD 2019) runs recommendation from missing-index signals and DTA-style
> what-if, implements at low priority, then validates with measured execution
> statistics and reverts regressions — the verify/revert step at fleet scale.
> Oracle's automatic indexing (19c) follows the same pattern of creating
> invisible candidate indexes and validating before making them visible.
> Database cracking (Idreos, Kersten, Manegold CIDR 2007) is the extreme
> online design: each range query partially sorts the column it touches, so
> the index emerges as a side effect of query processing.

## 7. Feedback-driven statistics (self-tuning histograms)

Observation: histogram construction usually ignores how the histogram will
be used, implicitly assuming all queries equally likely; real workloads
concentrate on regions. Query feedback (actual cardinalities observed at run
time) can refine buckets where queries actually go.

| Method | Partitioning | Refinement | Trade-off |
|---|---|---|---|
| Adaptive selectivity via feedback (Chen & Roussopoulos SIGMOD 1994) | curve fitting | adjust model coefficients from observed selectivities | 1-D |
| STGrid (Aboulnaga & Chaudhuri SIGMOD 1999) | multi-D grid | adjust bucket frequencies by observed error; periodically split/merge whole grid rows | cheap; distant buckets disturbed by local restructuring |
| STHoles (Bruno, Chaudhuri, Gravano SIGMOD 2001) | nested buckets ("holes" are first-class child buckets) | count result tuples per bucket by intercepting the plan's output stream; drill holes for query regions; merge similar buckets to respect budget | accurate, models non-rectangular shapes; needs tuple counting |
| ISOMER (Srivastava et al. ICDE 2006) | STHoles-like | maximum-entropy fit consistent with all observed cardinalities, no tuple counting | assumes uniformity only where nothing is known |
| Consistent selectivity via max-entropy (Markl et al. VLDBJ 2007) | — | combine overlapping multivariate knowledge into consistent estimates | avoids bias toward plans with least information |

**LEO** (DB2 LEarning Optimizer, Stillger, Lohman, Markl, Kandil VLDB 2001):
monitor actual vs estimated cardinalities per plan operator at run time,
compute adjustment factors, store them in the catalog, and apply them to
future estimates for matching predicates. Requirements: run-time counters on
operators, a stable predicate signature to key adjustments, and guards
against overcorrection (adjustments must be consistent with each other —
the max-entropy work addresses exactly that).

Engineering invariants for any feedback loop on statistics:
1. Feedback must not be biased by the plan that produced it (an index scan
   that stopped early under LIMIT under-reports cardinality).
2. Estimates must remain internally consistent (sel(a∧b) ≤ min(sel(a), sel(b))).
3. Changes to statistics invalidate cached plans — rate-limit to avoid plan
   flapping.

See `cardinality-and-statistics` for histogram construction itself.

## 8. Feedback control: admission and load control

Data-contention and memory thrashing cause throughput to *fall* as
concurrency rises (see `performance-models-and-monitoring.md` for the
analytic model). Load control:
- **Admission control**: cap the multiprogramming level (MPL); arrivals
  beyond the cap wait in a queue outside the engine (cheap) instead of
  inside it (where they hold locks/memory).
- **Cancellation control**: when goals can no longer be met, abort/shed
  work (lowest priority, youngest, or the transaction blocking most others).
- **Per-class MPL limits** to protect short/critical classes from bursts of
  long ones.
- The controller treats MPL as the control variable and measured
  performance as the output; adjust with simple control laws and use
  control theory for stability (Diao et al. 2005). Hard part: sudden bursts,
  which are not captured by steady-state models.
- **Conflict-ratio control** (COMFORT, Weikum et al. Inf. Syst. 1994;
  Moenkeberg & Weikum): conflict ratio = locks held by all transactions /
  locks held by non-blocked transactions; admit while it stays below a
  critical value (reported around 1.3) — a workload-independent thrashing
  indicator that needs no model of transaction sizes.

## 9. Workload management in practice

> **Beyond EDBS:** EDBS covers the theory (MPL control, priorities,
> conservation law) but not the product layer. The common architecture across
> Teradata TASM/TIWM, DB2 WLM, SQL Server Resource Governor and Oracle Resource
> Manager:
>
> 1. **Classification**: each request is mapped to a workload (class) by
>    *who* (user, account, role, application, client address, query band /
>    session tags), *where* (target databases/tables/views), and *what*
>    (statement type, optimizer-estimated processing time or row counts,
>    join/scan characteristics). Classification uses optimizer estimates, so
>    estimate quality is a WLM dependency.
> 2. **Filters**: reject requests outright (e.g., unconstrained product joins,
>    estimated time above a ceiling).
> 3. **Throttles (concurrency limits)**: per system, per workload, per user or
>    object; requests over the limit are delayed in a delay queue (or rejected).
>    This is admission control with class-specific MPL.
> 4. **Priority / resource allocation**: CPU and I/O shares per workload.
>    Teradata's priority scheduler on SLES 11 uses a Tactical tier, SLG
>    (service-level-goal) tiers with reserved percentages, and Timeshare with
>    access levels whose access rates double per level (Low:Medium:High:Top
>    = 1:2:4:8); the rate applies per active request, so a Top request gets
>    8× the Timeshare share of a Low request, and a level's total share grows
>    with its concurrency.
> 5. **Exceptions**: run-time rules (CPU time, skew, I/O, spool) that demote,
>    reclassify, or abort a running request when it deviates from its class's
>    expected behaviour — the cancellation control of §8.
> 6. **States**: planned environments (time windows like batch vs business
>    hours) × health conditions (e.g., node down, AWT exhaustion) select which
>    rule set is active.
>
> Teradata-specific resource to monitor: AMP Worker Tasks (AWTs), the
> per-AMP thread pool that every step of every request needs; AWT exhaustion
> is the canonical symptom that throttles are too loose. Teradata's
> DBC.TDWM/DBQL tables and TASM event history give per-workload delay times,
> throttle hits and exception actions — use them as the "observe" step, and
> treat throttle limits as the control variable of §8.
>
> Tuning rules: throttle the long, low-priority classes first (that is where
> MPL control buys throughput); keep tactical classes unthrottled but
> filtered on estimated cost; measure delay-queue time separately from
> execution time (they are different SLA components); and re-validate
> classification whenever optimizer statistics change.

## 10. Statistical learning for tuning

The engine's event log (configuration changes, measurements, exceptions) is
training data for regression (predict response time from configuration) or
classification (diagnose root cause). Caveat from the entry, still true:
designing features and models is the hard part; learning is not a panacea.

> **Beyond EDBS:** OtterTune (Van Aken, Pavlo, Gordon, Zhang SIGMOD 2017)
> tunes knobs by mapping a new workload to similar past workloads via
> internal metrics and using Gaussian-process regression to propose
> configurations; reinforcement-learning tuners (e.g., CDBTune, SIGMOD 2019)
> followed. Bao (Marcus et al. SIGMOD 2021) learns which optimizer hint sets
> to apply per query with a bandit, keeping the native optimizer as the
> candidate generator. Self-driving DBMS proposals (Pavlo et al. CIDR 2017,
> Peloton/NoisePage) forecast workload and plan actions ahead. Practical
> requirements: safe exploration (never on the production primary without
> guard rails), rollback, and a fixed benchmark harness to measure the gain.

## 11. Infrastructure the engine must provide

- Resource-adaptive operators (work areas that can shrink/grow mid-flight).
- Low-overhead self-monitoring: counters updated as a side effect, event
  aggregation inside the server (SQLCM, Chaudhuri, König, Narasayya ICDE
  2004), per-statement statistics keyed by normalised statement text.
- What-if interfaces for the optimizer and for resource models.
- Safe enactment: online DDL, low-priority background work, transactional
  rollback of tuning actions, plan-regression detection.
- Self-healing: isolate failing components and reset them; the transactional
  model (abort sessions, restart components, fail over to replicas) makes
  this tractable.

Long-term direction argued in the entry: complexity of features is itself
the obstacle; componentised "RISC-style" engines with narrow interfaces and
few knobs (Chaudhuri & Weikum VLDB 2000) are easier to self-manage.

Sources: Self-Management Technology in Databases (p.3374); Database Tuning
Using Online Algorithms (p.989); Database Tuning Using Trade-Off Elimination
(p.993); Database Tuning Using Combinatorial Search (p.985); Optimization and
Tuning in Data Warehouses (p.2619); Performance Analysis of Transaction
Processing Systems (p.2732).
