# EDBS entries behind this skill

Pull any entry in full with the `edbs-reference` skill:
`python3 <edbs-reference>/scripts/edbs.py show "<Entry>"` (add
`--section Foundations` or `--section "Recommended Reading"` as needed).

| Entry | Printed page | What it gives an engine builder |
|---|---|---|
| Adaptive Stream Processing | p.63 | Eddies with SteMs and routing tables; lottery, batched rank-ordering and content-based routing; A-Greedy with its 4-approximation; Aurora and STREAM load shedding; Chain memory scheduling; adaptive precision filters for communication |
| Big Stream Systems | p.273 | How HOP, S4, Storm and Spark Streaming split keyed work, handle windows, order and recovery; the lesson that key partitioning loses order and static placement cannot absorb skew |
| Complex Event Processing | p.530 | Short taxonomy of CEP solution segments and how derived, composite and complex events and situations relate |
| Continuous Query | p.630 | Standing-query definition and its lineage (Tapestry; materialized views and triggers as continuous queries) |
| Data Stream | p.853 | Definition of a stream; base vs derived streams; generation vs arrival timestamps and the two orders they induce |
| Data Stream Management Architectures and Prototypes | p.854 | Continuous, inbound, single-process SPE architecture; executor, queue, storage and stream managers and scheduler; contributions of Aurora/Borealis, STREAM, TelegraphCQ, Gigascope, Nile, System S, Spark Streaming, S-Store |
| Distributed Data Streams | p.1162 | One-shot vs continuous distributed queries; tree, multipath (ODI sketches) and gossip aggregation; local-filter slack allocation, top-k monitoring, prediction-based tracking, distributed triggers; DSPE systems |
| Event and Pattern Detection over Streams | p.1354 | Event-pattern model as regex over relational events with time; Cayuga NEXT/FOLD algebra and predicate-annotated NFAs; SASE negation and predicate push-in; MQO by automaton prefix merging and predicate indexing |
| Event Pattern Detection | p.1373 | Formal pattern tuple (context, inputs, pattern type, predicates, policies, derived events); pattern-type catalogue; policies for multiple candidate instances; event lineage |
| Fault Tolerance and High Availability in Data Stream Management Systems | p.1448 | Active replicas (process pairs, Flux, DPC), passive standby with Δ-checkpoints, upstream backup; failover vs repair; partition handling with tentative results; distributed checkpointing; trade-off analysis |
| Frequent Items on Streams | p.1524 | Problem variants (ε-deficient, hot items); Sticky Sampling, Lossy Counting, Frequent/Misra–Gries, SpaceSaving; GroupTest, multistage filters, hCount; windowed, decayed, weighted and mergeable extensions; empirical comparisons |
| Histograms on Streams | p.1715 | V-optimal DP; streaming (1+ε)-optimal histograms via top Haar coefficients and robust refinement; L2 count-sketch tracking in the turnstile model |
| Load Shedding | p.2111 | When/where/how much/which framework; Aurora loss/gain and random, semantic and window drops; STREAM relative-error shedding; join shedding (PROB, LIFE, age-based); data triage; Kalman suppression; FIT distributed shedding; closed-loop control |
| Nonrelational Streams | p.2505 | Pointer entry: graph, spatial, text and XML streams and their typical queries |
| One-Pass Algorithm | p.2556 | Streaming model (space, per-item time), communication-complexity lower bounds, randomized sublinear approximation, multi-pass trade-off |
| Publish/Subscribe Over Streams | p.2937 | Pub/sub design space (subject, predicate, XML; stateless vs stateful; centralized vs distributed); Le Subscribe predicate indexing; NiagaraCQ expression signatures; ONYX/Gryphon/Siena content routing; XPORT; stateful pub/sub via DB/network split |
| Punctuations | p.2943 | Punctuation definition and pattern format; grammatical streams; pass/keep/propagate behaviours; faithfulness of stream operators to relational ones |
| Quantiles on Streams | p.2965 | ε-approximate quantile summaries; sampling, Count-Min, MRL, GK, q-digest with space bounds; distributed, sliding-window, biased and duplicate-insensitive variants; practical throughput data |
| Scheduling Strategies for Data Stream Processing | p.3282 | Operator global selectivity and cost; response time, slowdown and ℓ2 metrics; RB, HR, HNR, FCFS, LSF, BSD/BRT, Aurora QoS, Chain, Mixed, freshness, AMoS; static vs dynamic priority implementation |
| Stream Models | p.3768 | Aggregate, cash-register, turnstile (strict/non-strict) and reset models; ordered/unordered/contiguous variants; why sliding windows imply negative tuples |
| Stream Processing | p.3771 | Custom code vs stream SQL vs rule engines; compile-to-machine-code and scheduler elimination; why external DBMS state stores are slow |
| Stream Processing on Modern Hardware | p.3772 | SDF vs asynchronous models; pipeline, task and data parallelism; fusion and fission, elasticity with consistent hashing; GPU batching and divergence limits; FPGA query compilation |
| Stream Sampling | p.3782 | Reservoir sampling with skips; AMS sample-and-count for moments and entropy; distinct sampling; sliding-window and time-decayed sampling; sampling under deletions |
| Streaming Analytics | p.3793 | Survey of streaming mining primitives (descriptive stats, sampling, sketches, quantization, dimensionality reduction, online classification, clustering, regression, frequent patterns, anomaly detection); requirements list |
| Stream-Oriented Query Languages and Operators | p.3802 | Language design axes (closure, first-class windows, window kinds, correlation, pattern matching); CQL ISTREAM/DSTREAM/RSTREAM; comparison of CQL, SQuAl, ESL, StreamSQL, CCL, EQL, StreaQuel |
| Transactional Stream Processing | p.4205 | Correctness beyond ACID (order, exactly-once); CQL batches, window-serializability, low-water-mark scheduling, UTM, S-Store atomic batches; precise/rollback/gap recovery and duplicate kinds; Storm, Spark, MillWheel, Kafka guarantees |
| Wavelets on Streams | p.4588 | Haar transform and error tree; exact top-B maintenance in the ordered model; turnstile lower bound; AMS-sketch-based GKMS and the Group-Count Sketch with polylog update and query |
| Window-Based Query Processing | p.4695 | Window kinds (stream vs operation based, count vs time, sliding vs predicate); re-evaluation vs incremental; revision tuples, punctuations, heartbeats (query vs operator level); negative tuples and W-expire; shared window joins; out-of-order handling |
