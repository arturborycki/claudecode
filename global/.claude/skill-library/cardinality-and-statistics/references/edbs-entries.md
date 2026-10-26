# EDBS entries behind this skill

Pull any entry in full with the `edbs-reference` skill:
`python3 <edbs-reference>/scripts/edbs.py show "<Entry>"`.

| Entry | Printed page | What it gives an engine builder |
|---|---|---|
| AMS Sketch | p.99 | Join and self-join size as a dot product of frequency vectors; +-1 projection with 4-wise independent hashing, variance bound, average-then-median boosting; behaviour under Zipf skew |
| Cost Estimation | p.647 | Logical / algorithmic / physical cost layers; temporal vs spatial cost factors; why only analytical models fit an optimizer; composition of operator costs in serial vs parallel plans |
| Count-Min Sketch | p.653 | Width/depth sizing from (eps, delta), point/range/quantile/heavy-hitter/inner-product queries, linearity for distributed merge, conservative update, skew-dependent space |
| Data Reduction | p.827 | Map of reduction techniques (histograms, clustering, SVD, Haar DWT) and their role in optimizer statistics and approximate answers |
| Data Sampling | p.840 | Sampling designs (with/without replacement, cluster, stratified), reservoir sampling, Markov/Chebyshev/Chernoff bounds for sizing samples |
| Data Sketch/Synopsis | p.848 | Short definition of synopsis vs sketch and their two uses (estimation, approximate answers); pointers only |
| Data Skew | p.849 | Zipf as the skew model; Walton et al. taxonomy (attribute value, tuple placement, selectivity, redistribution, join product skew) and its parallel-load consequence |
| Discrete Wavelet Transform and Wavelet Synopses | p.1132 | Haar error tree, point and range reconstruction from O(log N) coefficients, L2-optimal vs relative-error thresholding (probabilistic, deterministic DP, unrestricted), multi-measure and streaming wavelets |
| FM Synopsis | p.1487 | Flajolet-Martin distinct counting, PCSA, LogLog, bit-vector compression, deletions, sliding windows, OR-merge for distributed NDV; why sample-based NDV fails |
| Frequency Moments | p.1518 | Definitions of F0, F1, F2, F_inf and their database meaning; one-pass space bounds (cheap up to F2, polynomial beyond) |
| Hierarchical Data Summarization | p.1695 | B+-trees, quadtrees, R-trees and nested-bucket histograms (STHoles) as hierarchical summaries usable for range-count estimation; distributed summaries |
| Histogram | p.1714 | Data-distribution definition, partition classes (equi-width, equi-sum, MaxDiff, V-optimal), uniform-spread and average-frequency assumptions, relative accuracy and construction cost |
| Join Order | p.2051 | Why join order dominates cost; left-deep, right-deep and bushy shapes; DP plus heuristics as the standard approach (brief) |
| Karp-Luby Sampling | p.2054 | Polynomial-sample Monte Carlo estimation of DNF probability, for probabilistic-database query answers |
| Locality of Queries | p.2117 | Hanf/Gaifman locality from finite model theory (inexpressibility of transitive closure in FO); not used for estimation |
| Multi-query Optimization | p.2425 | Sharing common subexpressions and scans, failure of the principle of optimality, LQDAG, greedy CSE materialization, pipelining, applications (OLAP, CTEs, view maintenance, streams) |
| Nonparametric Data Reduction Techniques | p.2503 | Model-free synopses (histograms, clustering, indexes) and why they degrade gracefully |
| Parametric Data Reduction Techniques | p.2684 | Model-based synopses (regression, SVD, DWT): strong compression when the model fits, large error otherwise |
| Query Optimization | p.3008 | The three components of an optimizer: search space, cost estimation, enumeration; DP via optimal substructure |
| Query Optimization (in Relational Databases) | p.3009 | Transformative vs constructive optimizers; logical vs physical algebra; NP-hardness, Catalan/n! space sizes, query-graph connectivity, bushy DP with interesting orders and physical-property dominance; outer joins, aggregation movement, unnesting |
| Query Rewriting | p.3060 | Rewrite phase goals (standardization, simplification, amelioration) and typical rewrites (view expansion, predicate rewriting, redundant join elimination, flattening) |
| Sampling Techniques for Statistical Databases | p.3274 | Stub in the extraction; points to the Olken & Rotem survey of random sampling from databases |
| Selectivity Estimation | p.3371 | Reduction factors, uniformity and independence assumptions, histograms and multi-dimensional histograms as the fix, freshness of statistics |
| Spatiotemporal Selectivity Estimation | p.3650 | Spatial histogram estimate by overlap area, spatial sketches with guarantees, moving-object histograms in position-velocity space, sampling, distance-join selectivity under L-inf and L2 |
| Stable Distribution | p.3690 | alpha-stable random projections for l_alpha norms and distances, scale estimators, sample complexity, very sparse projections, Hamming norm as alpha -> 0 |
| Synopsis Structure | p.3864 | Formal definition (sublinear size) and the five evaluation criteria (coverage, quality, space, update time, query time) |
| System R (R*) Optimizer | p.3866 | Query blocks, RSS scans and SARGs, cost = page fetches + W * RSI calls, QCARD/RSICARD, NL and merge-scan cost formulas, left-deep DP with interesting orders, R* join sites and transfer strategies (ship, fetch, semijoin, Bloom) |

Judged weak or irrelevant for this skill: **Locality of Queries** (finite-model
theory, no estimation content); **Sampling Techniques for Statistical
Databases** and **Data Sketch/Synopsis** (near-empty stubs in the extraction;
content taken from Data Sampling and Synopsis Structure instead; the recovered
page tails added only Data Skew's references to Lynch 1988 and Walton et al.
1991 plus text from neighbouring sensor-network and heavy-hitter entries);
**Join Order**
and **Selectivity Estimation** are short overviews whose substance is covered by
the System R and Query Optimization entries.
