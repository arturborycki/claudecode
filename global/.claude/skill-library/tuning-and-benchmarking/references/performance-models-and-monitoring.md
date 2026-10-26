# Performance models and monitoring

Two complementary tools for reasoning about a running engine: analytic models
(queueing, contention) that predict how performance responds to load and
configuration, and monitoring facilities that tell you where time actually
goes. Models are for capacity planning, what-if prediction inside a
self-tuning loop, and sanity-checking benchmark numbers; monitoring is for
diagnosis. Combine analytic models, simulation, and trace analysis — each
alone is either too idealised or too expensive.

## 1. Operational laws (assumption-light, always use first)

From measurements over an interval of length T with C completions:

| Law | Formula | Use |
|---|---|---|
| Utilization law | U_k = X_k · S_k | infer per-visit service time from utilisation and throughput |
| Forced flow | X_k = V_k · X | per-resource throughput from system throughput and visit count |
| Service demand | D_k = V_k · S_k = U_k / X | total time a transaction needs at resource k |
| Little's law | N = X · R (any stable system or subsystem) | concurrency (MPL), memory, connection-pool sizing |
| Interactive response time | R = N/X − Z (Z = think time) | closed systems with terminals |

Asymptotic bounds (closed system, N users, think time Z, D = Σ D_k,
D_max = max_k D_k):
- X(N) ≤ min(N / (D + Z), 1 / D_max)
- R(N) ≥ max(D, N · D_max − Z)
- Saturation knee N* ≈ (D + Z) / D_max.
The resource with D_max is the **bottleneck**; throughput can never exceed
1/D_max no matter how many clients are added. A benchmark result above that
bound is a measurement bug.

> Little's law and the bottleneck asymptote are in the EDBS entry; the full
> set of operational laws is standard (Denning & Buzen 1978; Lazowska,
> Zahorjan, Graham, Sevcik, *Quantitative System Performance*, 1984 — the
> entry's main QNM reference).

## 2. Single-queue results

M/G/1 (Poisson arrivals rate λ, general service with moments x̄, x̄²,
utilisation ρ = λ x̄ < 1):
- mean wait W = λ · x̄² / (2(1 − ρ))  (Pollaczek–Khinchine)
- mean response R = W + x̄
- M/M/1 (x̄² = 2x̄²): R = x̄ / (1 − ρ). Response time explodes as ρ → 1;
  variability of service (x̄²) multiplies the wait.

Capacity arrangement, same total capacity, arrival rate 2λ:
- two separate M/M/1 queues with random routing: R1 = x̄/(1−ρ)
- one shared queue, two servers (M/M/2): R2 = x̄/(1−ρ²)
- one server twice as fast: R3 = (x̄/2)/(1−ρ)
R1 > R2 > R3: a shared queue beats partitioned queues (pooling), and one fast
server beats several slow ones when service times are not highly variable.
Engineering reading: per-core run queues without stealing behave like R1;
work stealing moves you toward R2.

Priorities (two classes, class 1 urgent):
- preemptive (negligible overhead): class 1 unaffected by class 2 — fits CPU
  scheduling.
- non-preemptive (fits disk / non-interruptible steps): W1 = W0/(1−ρ1),
  W2 = W0/((1−ρ1)(1−ρ)), with W0 = Σ_j λ_j x̄²_j / 2 the mean residual work.
  W1 depends only on class-1 load ρ1, not total ρ.
- Kleinrock's conservation law: Σ_j ρ_j W_j = ρ W0/(1−ρ) is invariant under
  work-conserving scheduling — favouring one class costs another exactly.
  Workload-management priority settings redistribute delay; they do not
  create capacity.

Fork-join and skew:
- K parallel M/M/1 sub-requests, each with mean response R, join at the max:
  E[max] ≈ H_K · R, H_K = Σ_{k=1..K} 1/k (≈ ln K + 0.577). With 4 nodes the
  max is ≈ 2.08× a single node's mean even for identical, independent work.
  Correlated components do somewhat better (for K = 2, R_F/J = (1.5 − ρ/8)R).
- Consequence for shared-nothing engines: response time of a parallel step is
  governed by its slowest participant; skew metrics (max/mean per node) matter
  more than averages, and grow with node count even without data skew.

## 3. Queueing network models (QNMs)

Open QNM: external arrivals rate Λ. Closed QNM: fixed population N (each
completion immediately replaced) — models a fixed MPL or terminal
population. Central server model: CPU as the hub, disks as peripheral
servers; with exit probability p1 from the CPU and branch probabilities p_k,
visit counts are v1 = 1/p1, v_k = p_k/p1.

Product-form (BCMP) networks — FCFS exponential single/multi-server nodes,
infinite-server delay nodes, etc. — have efficiently computable steady-state
metrics. Open product-form: λ_k = v_k Λ, ρ_k = Λ D_k / m_k,
residence per visit r_k = x̄_k/(1 − ρ_k) (single server), R = Σ v_k r_k,
N = Λ R (Little) → estimate MPL and memory requirement.

**Mean Value Analysis (closed, single-server + delay nodes)**
```
input: N (population), service demands D_k, node types
Q_k := 0 for all k
for n in 1..N:
    for k: R_k := D_k                       if k is a delay (infinite-server) node
           R_k := D_k * (1 + Q_k)           otherwise   # arrival theorem: sees Q_k(n-1)
    R := Σ_k R_k
    X := n / (R + Z)                         # Little; Z = think time (0 for batch)
    for k: Q_k := X * R_k                    # Little per node
return X(N), R(N), Q_k(N)
```
O(N·K). Arrival theorem: an arriving customer in a closed network with n
customers sees the time-average state of the network with n − 1. Convolution
is the alternative (G(n) recurrence, X(N) = G(N−1)/G(N)).

Balanced system: for fixed Σ D_k, throughput is maximised when all D_k are
equal; with per-node demand D an arrival sees (N−1)/K customers at each
node, so R(N) = K·D·(1 + (N−1)/K) = (N + K − 1)·D.
Physical design and data placement that equalise device demands are buying
throughput, not just "spreading load".

**Memory-constrained MPL (hierarchical model)**: with at most M transactions
admitted (memory/AWT/thread limit) and Poisson arrivals Λ:
1. Solve the closed QNM for X(n), n = 1..M; set X(n) = X(M) for n > M.
2. Birth–death chain on n (in system): P_n = Λ P_{n−1} / X(n); normalise.
3. N̄ = Σ n P_n; queued N̄_B = Σ_{n>M} (n−M) P_n; active N̄_A = Σ min(n,M) P_n.
4. R = N̄/Λ = W_mem + R_A where W_mem = N̄_B/Λ is admission-queue wait.
This is the analytic model of a throttle/delay queue: it predicts delay-queue
time as a separate SLA component.

The throughput curve X(n) without an MPL cap rises toward min_k m_k/D_k —
unless thrashing intervenes: virtual-memory thrashing, or data-contention
thrashing under standard locking (§6). Then X(n) peaks and declines; the
MPL cap should sit at or below the peak.

## 4. Buffer miss rate (BMR)

- Determined by buffer size, replacement policy and reference string.
- Markov analyses of FIFO, LRU, CLOCK assume the Independent Reference Model
  (IRM: each reference independently hits page i with fixed probability p_i)
  — good for steady state, blind to sequential scans and phase changes.
- Alternatives: stack-depth distributions, hierarchical-reuse / fractal
  models; trace-driven simulation to calibrate empirical formulas.
- Tay & Zou (Perform. Eval. 2006) derive a closed-form page-fault-vs-memory
  equation parameterised by cold misses and the min/max memory sizes over
  which faults vary — useful as a smooth curve to fit measurements to.

> **Beyond EDBS:** for stack algorithms (LRU, LRU-K for fixed K, OPT) the
> inclusion property means one pass over a trace with Mattson's stack
> algorithm yields the miss ratio for *every* cache size; that miss-ratio
> curve is the right input for memory brokering and for sizing decisions.
> Approximate MRC construction (e.g., SHARDS sampling, FAST 2015) makes it
> cheap enough to run online.

## 5. Storage service times

Disk access ≈ seek + rotational latency (≈ half a rotation for small blocks)
+ transfer (negligible for small blocks); seek ≈ a + b√distance. FCFS disk
response from M/G/1 with those moments. Shortest-Access-Time-First
scheduling with n outstanding requests reduces mean access time roughly as
n^(−1/5) — 32 queued requests about halve it vs FCFS — which is why deep
queues help throughput (at a latency cost). RAID-level effects (small-write
penalty, degraded mode, rebuild) are in `application-schema-and-layer-tuning.md`
§4.3.

## 6. Lock contention and thrashing (strict 2PL)

Model (Thomasian; Tay): closed system of M transactions; a transaction of
size k has k+1 steps of mean duration s, requests one exclusive lock at the
end of each of the first k steps, releases all at commit. Uniform access over
D lockable items.

| Quantity | Approximation |
|---|---|
| mean locks held | L ≈ k/2 |
| conflict probability per request | P_c ≈ (M−1) L / D ≈ (M−1) k / (2D) |
| shared locks, fraction f_S | use D_eff = D / (1 − f_S²) |
| P[txn waits at least once] | P_w ≈ k · P_c ≈ (M−1) k² / (2D) |
| two-way deadlock probability | P_D2 ≈ (M−1) k⁴ / (4D²) (multi-way much rarer) |
| response time | R_k ≈ (k+1) s + k · P_c · W |
| wait per conflict with an active holder | W1 ≈ ((k−1)/3)(s + u) + residual step; normalised A = W1/R ≈ 1/3 |
| variable sizes (moments K1, K2, K3) | L = K2/(2K1); A = (K3 − K1)/(3K1(K2 + K1)) |

Blocking chains: let β = fraction of blocked transactions. A conflict with an
active holder costs W1; with a holder that is itself blocked (level 2) costs
≈ 1.5 W1; level i ≈ (i − 0.5) W1. Define

```
α = K1 · P_c · W1 / R  = A · K1 · P_c      # conflicts per txn × normalised wait
β = α (1 + 0.5β + 1.5β² + 2.5β³ + …)
⇒ f(β) = β³ − (1.5α + 2)β² + (1.5α + 1)β − α = 0
```
For α ≤ α* ≈ 0.226 there is a root β1 < 1 (stable); above α* no admissible
root — **thrashing**. Active transactions M_A = M(1 − β1) rise with M, peak,
then fall (blocked transactions block others: snowball). Throughput with
contention = X(M_A) interpolated on the contention-free X(n) curve.

Rule of thumb derived from the table (fixed k): α ≈ (M−1)k²/(6D), so
thrashing onset ≈ (M−1)·k²/D ≈ 1.4. Implications:
- Contention scales with k² (more locks × longer holding), so long
  transactions dominate; variability in size increases P_c (≈2× for a
  truncated geometric size distribution) and deadlocks (≈10×).
- Doubling the database (finer granularity, more rows) halves contention;
  doubling MPL doubles it. Admission control at the knee is the cheapest fix.
- The critical α corresponds to the COMFORT conflict-ratio threshold (ratio
  of locks held by all vs. active transactions), the basis of model-free
  load control (see `online-and-self-tuning.md` §8).

**Restart-oriented locking** (strict 2PL, but conflicts may abort someone to
keep concurrency high; needs spare CPU — counterproductive when
hardware-bound):
- No-waiting / cautious waiting: abort on conflict with an active / blocked
  holder. Little benefit — the restarted transaction tends to hit the same
  conflict.
- Running Priority (RP): in T_A → T_B → T_C, abort the blocked T_B that is
  blocking T_A.
- Wait-Depth Limited (WDL, Franaszek, Robinson, Thomasian TODS 1992): limit
  waits-for depth to 1; choose the victim by progress (e.g., locks held),
  sparing near-complete transactions. Beats RP and standard locking in
  simulation and trace-driven studies.
- Avoid cyclic restarts (livelock): restart-waiting — delay restart until the
  conflicting transactions finish; random back-off is weaker.

**OCC model** (Morris & Wong 1985; Ryu & Thomasian 1987): conflict
probability between two transactions of size k ≈ k²/D; with commit rate λ
and data-conflict rate γ, validation failure probability 1 − e^{−γ·t}
grows with execution time t; executions per commit are geometric with mean
e^{γ·t}; wasted work is concentrated in long transactions (quadratic
effect: k objects accessed × execution time ∝ k).
- Die (silent: run to end, then fail validation) vs kill (broadcast: abort
  at conflict). Kill wastes less CPU, but with disk I/O, die primes the buffer
  pool, so the re-execution runs from memory — **two-phase processing**,
  valid under access invariance (a restart touches the same objects). The
  second phase can use kill-OCC or lock preclaiming (cannot restart).
- WDL and RP outperform two-phase methods in the cited studies.

Modelling pitfall: resampling a restarted transaction's size or processing
time biases toward short transactions and overestimates performance.

## 7. Monitoring tools

| Tool | Answers | Overhead | Use for |
|---|---|---|---|
| Event monitor | resources consumed per event (statement, transaction, deadlock, session), reported at event end | low: counters updated as side effects, read once | finding the top resource consumers |
| Query plan explainer | chosen plan tree, annotated with estimated cardinality/cost (and actuals in "analyze" modes) | none / one execution | stale statistics, unused indexes, unexpected operators |
| Time-based profiler | where time goes: service vs each kind of wait | can be high (logs many actions) | critical statements; response-time decomposition |
| Counter-based profiler | how resources are used: system/database-wide aggregate counters | low | capacity, trend, utilisation |

Engine-builder requirements: counters must be cheap enough to be always on
(per-thread, aggregated lazily, no global atomics on hot paths); every wait
must be attributed to a named wait class; per-statement statistics keyed by
a normalised statement fingerprint; plan identity (hash) recorded with
execution statistics so plan changes are visible.

## 8. Which metrics matter (and which mislead)

1. **Response-time decomposition per workload class** — the primary metric.
   R = CPU service + Σ waits (I/O read, log write/fsync, lock, latch/mutex,
   network/client, admission/delay queue). Optimise the largest component of
   the class whose SLA is violated. This is the time-based profiler's job
   (method popularised for Oracle by Millsap & Holt, *Optimizing Oracle
   Performance*, 2003 — cited in the entry).
2. **Throughput and quantiles** (p50/p95/p99), not means; means hide the
   M/M/1 blow-up and fork-join skew.
3. **Utilisation per resource and service demand D_k** → bottleneck
   identification via §1 bounds.
4. **Lock metrics**: lock wait time per transaction, blocked fraction β,
   conflict ratio, deadlock rate, escalations. Rising β with flat
   utilisation = data contention, not capacity.
5. **Latch/mutex contention** (short-term physical synchronisation: buffer
   chains, log buffer, B-tree root/right edge, sequence, plan cache) — shows
   as CPU busy-wait or a latch wait class; fixed by partitioning the
   structure, not by isolation-level changes.
6. **Buffer metrics done right**: the hit *ratio* is a weak signal. A query
   doing 10⁹ needless logical reads of cached pages raises the hit ratio
   while getting slower. Use physical reads per second and per transaction,
   logical reads per execution per statement (efficiency), read wait time,
   and the miss-ratio curve (marginal benefit of more memory).
7. **Skew** (shared-nothing): max/mean CPU and I/O per node per step; hot
   AMPs/partitions dominate elapsed time (fork-join).
8. **Plan regressions**: same fingerprint, new plan hash, worse latency.

> **Beyond EDBS:** product facilities that implement these: Oracle ASH/AWR
> wait-event sampling; PostgreSQL `pg_stat_activity.wait_event`,
> `pg_stat_statements`, `EXPLAIN (ANALYZE, BUFFERS)`; SQL Server wait stats
> and Query Store; Teradata DBQL (per-query CPU, I/O, spool, skew, step
> detail), ResUsage (per-node/AMP resource usage), and TASM event history.
> Sampling-based wait profiling (ASH-style, e.g., once per second per
> active session) gives time-based profiles at counter-like overhead.

Diagnosis loop: (1) pick the class with the SLA violation; (2) decompose its
response time; (3) map the dominant wait to a resource; (4) use the bounds
or model to estimate the gain of the fix; (5) change one thing; (6) re-
measure with the same workload and compare distributions.

Sources: Performance Analysis of Transaction Processing Systems (p.2732);
Performance Monitoring Tools (p.2741); Self-Management Technology in
Databases (p.3374); Tuning Concurrency Control (p.4252).
