# Benchmark design, data generation and benchmarking methodology

A benchmark is a reproducible experiment for characterising and comparing
performance (time, memory, energy, cost, or result quality) of database
systems or of algorithms inside them. It is an engineering artefact with its
own correctness requirements: a broken generator, an unconstrained client, or
an unreported warm cache invalidates every number it produces. This file is
about designing and running benchmarks; harness mechanics (Criterion,
Google Benchmark, sqllogictest) live in `query-engine-testing`.

## 1. Anatomy of a benchmark

| Component | Must specify | Typical failure |
|---|---|---|
| System under test (SUT) | DBMS + OS + hardware; constraints so results are comparable (e.g., priced configuration, durability on, no result caching) | comparing a durable system to one with fsync off |
| Workload: data | schema, generator or explicit files, value distributions, scale factor | uniform independent data that hides estimator bugs |
| Workload: operations | statements/transactions, mix weights, parameter generation, concurrency, client constraints (think time, keying time, arrival rate) | unbounded clients turning a latency benchmark into a saturation test |
| Metrics | throughput, latency quantiles, price/performance, energy (throughput per joule), quality | reporting mean latency only |
| Experiments | what is varied, what is held fixed, repetitions, run rules, warm-up, measurement interval | single run, no variance |

Gray's criteria (*The Benchmark Handbook*, 1991/1993) for a domain-specific
benchmark:
1. **Relevance** — workload and metrics reflect typical operations of the
   target domain.
2. **Simplicity** — understandable, so results are interpretable.
3. **Portability** — no dependence on one system's features; reproducible
   across systems of the same class.
4. **Scalability** — applies to small and large systems (a scale factor).

Benchmarks are deliberately *not* absolute measures: each targets a class of
systems (relational, XML, graph, stream, cloud serving) and an application
domain (OLTP, decision support, data integration, publishing).

## 2. Taxonomy

| Kind | Purpose | Unit of design | Example |
|---|---|---|---|
| Application benchmark | "which system for this domain?" — exercise most components with weighted tasks | weighted task mix; results meaningful only with the weights | TPC-C/E (OLTP), TPC-H/DS (DSS), OO1/OO7 (OODB), XMark/XBench/TPoX (XML) |
| Microbenchmark | "how does feature F respond to parameter p?" — isolate one aspect (the *target*) | parametric measure + guidance on which data/operation parameters matter and their value ranges | OO7 sub-tests, Michigan XML benchmark, MemBeR repository |
| Benchmark family | loosely related benchmarks sharing tools | shared generator | XBench (DC/SD, DC/MD, TC/SD, TC/MD) |
| Benchmark framework | ecosystem of benchmarks derived from each other by explicit mappings | parent→child derivations with validation | τBench |
| Benchmark framework (tooling sense) | software to generate data and drive workloads | drivers, generators, metrics collection | HammerDB, YCSB |

Microbenchmarks serve engine developers (assess modules, algorithms); they do
not by themselves tell a customer which system to buy. Application
benchmarks do the reverse. An engine team needs both: microbenchmarks for
every hot path (gated in CI), and at least one application benchmark for
end-to-end regression.

### Benchmark frameworks done right (τBench principles)
Thomas, Snodgrass, Zhang (Softw. Pract. Exp. 2014) require:
1. an explicit **organizing insight** tying the constituent benchmarks
   together (for τBench: temporal statement modifiers, commutativity
   validation, temporal upward compatibility);
2. **automation** — child components (data, schema, workload) produced by
   running mapping programs on the parent's components;
3. **reuse** of data, schema, workloads and tools across benchmarks;
4. **organizational clarity** (a benchmark-relationship diagram stating what
   changes between parent and child: model, DDL, DML, data, workload);
5. **consistency and validation checking** within and *across* benchmarks.

τBench as a worked example: XBench DC/SD (single XML catalog document,
ToXgene-generated, 17 XQuery queries each probing one construct) → τXBench
(temporal data by simulating changes over time; 85 queries = for each
original query a current, a non-sequenced, and three sequenced variants
covering ~10%, 50%, 90% of the timeline) → PSM (relational shredding into six
tables, SQL/PSM routines as microbenchmarks) → τPSM (VALIDTIME modifiers;
three datasets of different volatility: weekly changes, Gaussian hot-spot
items, daily changes) → mapped variants via two source-to-source slicing
strategies (maximally fragmented vs per-statement), expressed in TXL, for
conventional engines (DB2 dialects). Lesson worth copying: derive variants
mechanically and cross-validate them (e.g., the sequenced query's result at
time t must equal the non-temporal query over the timeslice at t —
commutativity), instead of hand-writing variants that drift.

A second lesson from the same work: generators can impose **implicit
constraints not in the schema** (XBench's generator made every author belong
to exactly one item and every publisher to exactly one item). Tools that
transform the data must preserve them, and benchmark users must know them —
they change join cardinalities and therefore plans.

## 3. Lineage of standard benchmarks

| Benchmark | Domain | Notes |
|---|---|---|
| Wisconsin (Bitton, DeWitt, Turbyfill 1983) | relational query processing microbenchmarks | publication led to the "DeWitt clause" in licences forbidding named publication of results |
| Debit/Credit, "Anon et al." (Datamation 1985) | OLTP | introduced transactions per second as the throughput measure, with a response-time constraint |
| TPC-A, TPC-B | OLTP | TPC versions of Debit/Credit and TP1 |
| TPC-C (1992) | order-entry OLTP | long-lived standard |
| TPC-D → TPC-H (1999) | decision support | ad-hoc queries + refresh functions |
| TPC-DS (2011) | decision support | richer schema and query set, data maintenance |
| TPC-E | brokerage OLTP | more complex schema than TPC-C |
| TPC-DI, TPCx-HS (2014) | ETL; Hadoop | |
| OO1, OO7 (Carey, DeWitt, Naughton 1993) | object databases | |
| XMark, XBench, TPoX, Michigan | XML query/transaction processing | |
| YCSB (Cooper et al. SoCC 2010) | cloud serving (key-value CRUD + scans) | SQL and NoSQL |
| LDBC SPB, SNB (2015) | RDF publishing; social-network graph (interactive, BI) | |
| Linear Road | stream processing (variable tolling) | compares stream engines and relational alternatives |

Councils (TPC, LDBC) define run rules and certify/publish results; full
disclosure and audits are what make vendor numbers comparable.

> **Beyond EDBS — what the standard benchmarks actually stress:**
> - **TPC-C**: 9 tables scaled by warehouses; 5 transaction types with a
>   required minimum mix (Payment ≥ 43%, Order-Status, Delivery, Stock-Level
>   ≥ 4% each, New-Order the remainder ≈ 45%); metric tpmC = New-Order
>   transactions per minute under 90th-percentile response-time limits, with
>   keying and think times bounding each terminal's rate (so throughput
>   scales only by adding warehouses). Stresses: B-tree point access, hot
>   rows (district next-order-id, warehouse YTD), log write path, a fraction
>   of remote (multi-warehouse) transactions — a test of partitioning and
>   distributed commit.
> - **TPC-H**: 8 tables, 22 queries + 2 refresh functions, scale factors from
>   1 GB upward; power test (single stream) and throughput test (concurrent
>   streams) combined as QphH@Size (geometric-mean based). Data is uniform
>   and mostly independent — weak for cardinality-estimation stress. "TPC-H
>   analyzed" (Boncz, Neumann, Erling, TPCTC 2013) catalogues its choke
>   points (aggregation, join ordering, correlated subqueries, data locality).
> - **TPC-DS**: snowflake schema with multiple fact tables, 99 query
>   templates, skewed data, data-maintenance phase; stresses optimizers far
>   more than TPC-H.
> - **YCSB**: core workloads A (50% read / 50% update), B (95/5), C (read
>   only), D (read latest, 5% insert), E (short range scans, 5% insert),
>   F (read-modify-write); request distributions uniform, zipfian (default
>   constant 0.99), latest. Two modes the EDBS entry names: latency vs
>   offered load (target throughput) and throughput vs number of servers
>   (scale-out).
> - **JOB** (Leis et al. VLDB 2015, "How good are query optimizers, really?"):
>   113 join queries on real IMDB data with correlations and skew; shows
>   that estimates which look fine on TPC-H fail by orders of magnitude on
>   real data. Use it alongside TPC-H when the change touches estimation or
>   join ordering.
> - Drivers: HammerDB (TPC-C/H-derived workloads, GUI + CLI; the derived
>   kits are not certified TPC results), BenchBase/OLTPBench (Difallah et al.
>   VLDB 2013) for many OLTP workloads with rate control.

## 4. Data generation

Four sub-problems (Bonnet & Shasha):
1. **Define the space**: structural constraints (domains, keys, FDs,
   referential integrity, cross-table constraints) and instance
   characteristics (cardinalities, per-attribute distributions,
   correlations within and across tables).
2. **Generate values per domain**: RNG for numerics; dictionaries for
   strings; keys without repetition (permutation or counter-based); foreign
   keys drawn from the set of generated parent keys (not from an RNG over the
   domain); constraints spanning tables may need a post-processing pass.
3. **Shape distributions**: uniform; normal; Zipf (frequency ∝ 1/rank^θ);
   self-similar (80-20 recursively).
4. **Assemble and emit** tuples / documents / graphs.

Specification languages: DGL (Bruno & Chaudhuri VLDB 2005, composable
generator primitives); QAGen (Binnig et al. SIGMOD 2007, query-aware: data
generated so that given queries produce specified intermediate
cardinalities); declarative constraint-based generation (Arasu, Kaushik, Li
SIGMOD 2011: cardinality constraints → instance); example data for dataflow
programs (Olston, Chopra, Srivastava SIGMOD 2009). Graph generators target
properties (degree distribution, diameter, density).

Implementation rules for a generator an engine team can trust:
- **Deterministic and parallel**: derive each chunk's RNG seed from (global
  seed, table, chunk id) so any chunk can be regenerated independently and
  generation parallelises without coordination (the TPC dbgen/dsdgen design).
- **Zipf without O(n) tables per draw**: precompute the normaliser
  (generalised harmonic number) once; use rejection-inversion or the method
  of Gray et al. (SIGMOD 1994, "Quickly generating billion-record synthetic
  databases"); scramble ranks with a bijective hash so hot keys are not
  clustered at the low end of the key space (unless clustering is the point).
- **Correlation**: generate dependent columns conditionally
  (b ~ F(· | a)), or via a copula over marginals; for cross-table
  correlation, generate child rows from parent attributes. Independence is
  itself a choice and must be stated.
- **Skew knobs as parameters** (θ, hot-set fraction, hot-spot drift over
  time) so the same benchmark can sweep from uniform to adversarial.
- **Validate the output**: check cardinalities, distinct counts, key
  uniqueness, RI, the target distribution (goodness of fit), and any
  implicit constraints — the generator is code and has bugs.

Real vs synthetic data:
- Synthetic: exact control, extremes, scalability sweeps; poor at predicting
  real application performance.
- Real: realism, but representativeness is hard to judge and data is tied to
  an application (city traffic differs from rural traffic).
- Hybrid/infrastructure-based generators: real structure + synthetic
  activity. Spatio-temporal examples: GSTD (parameterised random movement of
  points/rectangles), Oporto (fishing scenario with attraction/repulsion),
  G-TERD (evolving raster regions), Brinkhoff's network-based generator
  (objects move on a road network with edge speed limits and capacities,
  time-dependent trip generation, route recomputation), City Simulator (3-D
  city, up to a million objects), SUMO (validated traffic simulation); real
  datasets such as INFATI GPS traces.

> **Beyond EDBS:** a common hybrid for engine work is *scaling real data*:
> take a production or public dataset and scale it up preserving joint
> distributions and FK degree distributions, or generate a synthetic
> instance from production statistics only (histograms, NDVs, correlations)
> when the data itself cannot leave the customer.

## 5. Methodology: running experiments that mean something

**Before running**
- Write the question first ("does change X reduce p99 of New-Order at 80%
  of max throughput?"); derive the metric and the experiment from it.
- Fix and record the SUT: versions, configuration diff from defaults,
  hardware, firmware, OS settings (CPU governor, THP, NUMA), storage
  durability settings, data scale, statistics state.
- Correctness gate: results of the benchmark queries must be validated
  (reference answers or cross-engine comparison). A faster wrong answer is
  a regression.

**Load generation**
- Closed loop (fixed clients, think time): models terminals; throughput is
  self-limiting; latency under overload is underestimated because a stalled
  system stops receiving requests.
- Open loop (arrival process at offered rate λ): models internet traffic;
  exposes queueing explosion near saturation. For latency claims, use open
  loop or a closed loop with enough clients and measure from *intended*
  send time.
  > **Beyond EDBS:** measuring latency from actual send time in a closed
  > loop silently drops the samples that would have been slowest
  > ("coordinated omission", G. Tene); record full latency histograms
  > (e.g., HdrHistogram) rather than averages.
- Report a **throughput–latency curve** (sweep offered load), not one point;
  the interesting region is the knee predicted by the bounds in
  `performance-models-and-monitoring.md`.

**Warm-up and steady state**
- Discard ramp-up: buffer pool fill, JIT/plan-cache warm-up, connection pool
  ramp, LSM compaction backlog, checkpoint cycle phase.
- Detect steady state rather than guess: throughput over sliding windows
  within a tolerance; the measurement interval must span several periodic
  background cycles (checkpoints, compactions, vacuum, statistics refresh) or
  be explicitly aligned and reported.
- Report cold and warm separately when both matter (cold cache: first query
  after restart with OS cache dropped).

**Variance and statistics**
- Repeat runs (and re-generate/reload data for some repetitions); report
  median and spread or confidence intervals; for latency, quantiles per run
  and their variability across runs.
- Change one factor at a time; for factor interactions use a factorial
  design rather than intuition.
- Watch for environment noise: other tenants, thermal throttling, turbo,
  background OS tasks; pin and isolate where the question allows.

**Reporting**
- Configuration, dataset, scale, client setup, run rules, warm-up, interval,
  all metrics with dispersion, and the raw data. Make it rerunnable
  (scripts + seeds). The repository-of-experiments idea raised for physical
  design research (record the whole test chain) applies generally.
- Normalised metrics (per dollar, per joule, per core) must state the
  denominator's provenance.

**Avoiding benchmarketing**
Vendors invest heavily in tuning systems on hardware chosen to top a
standard benchmark. Engine-team antidotes: (1) default-configuration runs in
addition to tuned runs; (2) benchmark-specific code paths are forbidden
(detect by perturbing the benchmark: rename columns, change constants, use
different parameter distributions); (3) report on more than one benchmark,
including one with real data; (4) when comparing to other systems, tune each
comparably and disclose effort (legal note: many licences still contain
DeWitt-clause restrictions on naming products).

> **Beyond EDBS:** Raasveldt, Holanda, Gubner, Mühleisen (DBTest 2018, "Fair
> benchmarking considered difficult") list recurring pitfalls in published
> database comparisons: non-reproducible setups, comparing a tuned system
> with defaults, including or excluding data loading/result transfer
> inconsistently, cold vs hot runs mixed, and incorrect results going
> unchecked.

## 6. Microbenchmark design checklist (engine developers)

1. Name the target (operator, structure, path) and the parameter(s) that
   should drive it (input size, selectivity, key width, skew θ, thread
   count, memory grant).
2. Sweep each parameter over a range that crosses the regime boundaries you
   expect (cache sizes L1/L2/LLC/RAM, memory grant vs spill, fanout changes).
3. Hold everything else fixed; check that the measured quantity is what you
   think (perf counters: instructions, cache misses, branch misses).
4. Defeat dead-code elimination and constant folding (black_box/DoNotOptimize).
5. Compare against a model (expected O(n log n), bandwidth roofline); a
   result that beats the model is a bug until explained.
6. Keep it in CI with a regression threshold calibrated to measured noise.

Sources: Database Benchmarks (p.936); Application Benchmark (p.122);
Microbenchmark (p.2255); Benchmark Frameworks (p.267); tBench (p.3877); Data
Generation (p.772); Real and Synthetic Test Datasets (p.3110); Optimization
and Tuning in Data Warehouses (p.2619).
