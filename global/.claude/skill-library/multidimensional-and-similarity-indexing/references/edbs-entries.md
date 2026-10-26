# EDBS entries behind this skill

Pull any entry in full with the `edbs-reference` skill:
`python3 <edbs-reference>/scripts/edbs.py show "<Entry>"`
(add `--section Foundations` or `--section "Recommended Reading"`).

| Entry | Printed page | What it gives an engine builder |
|---|---|---|
| Bitemporal Indexing | 304 | Why one R-tree over (transaction × valid) rectangles overlaps badly (the UC edge); the front/back two-R-tree design; GR-tree for now-relative growing regions; partial persistence vs overlapping as ways to add transaction time to an interval index. |
| Closest-Pair Query | 469 | MINMINDIST / MINMAXDIST / MAXMAXDIST between MBR pairs, the k-CPQ pruning rule, best-first vs depth-first trade-offs (heap size vs node accesses, LRU friendliness), plane-sweep pair generation inside node pairs. |
| Curse of Dimensionality | 717 | Short statement of distance concentration and the ~12-dimension point where hierarchical indexes lose to scans; motivation for reducing dimensions before indexing. |
| Dimensionality Reduction Techniques for Nearest-Neighbor Computations | 1108 | SVD/PCA/KLT maths and NMSE; clustered SVD (CSVD) and LDR; exact kNN on reduced data via the lower-bounding property; branch-and-bound over clusters; OP-tree and SDI-tree layouts. |
| Generalized Search Tree | 1581 | The GiST contract (consistent, union, penalty, pickSplit), what the engine vs the extension owns, concurrency/recovery references, SP-GiST, theory of indexability, amdb, PostgreSQL/PostGIS adoption. |
| Grid File (and Family) | 1671 | Linear scales + directory, two-access exact match, split/merge mechanics, directory blow-up and correlation weaknesses, BANG/twin/multilevel/parallel variants. |
| High-Dimensional Indexing | 1706 | Taxonomy of high-d tricks; TV-, SS-, SR-, X-tree; cost-model-based page-size optimisation and tree striping; Pyramid technique; VA-file; IQ-tree with fast index scan; iDistance; main-memory and cloud designs. |
| Indexing and Similarity Search | 1857 | Overview: index = space partitioning + simplified object representations; R-tree kNN with MINDIST and a priority queue; VP-tree ball partitioning; why reduction precedes indexing. |
| Indexing Historical Spatiotemporal Data | 1868 | Three families for trajectory history: 3-D structures (RT, 3D R, STR), overlapping/multiversion 2-D (MR, HR, HR+, MV3R), trajectory-oriented (TB-tree, SETI, SEB-tree), with their query trade-offs. |
| Indexing Metric Spaces | 1876 | Metric indexing history (BK-tree to M-tree, Slim-tree, D-index); ball vs generalised-hyperplane partitioning; triangle-inequality bounds; approximate and P2P metric search; distance-distribution effect on cost. |
| Indexing of the Current and Near-Future Positions of Moving Objects | 1884 | Linear-motion model and query types; TPR-tree structure, tightening, integrated-over-horizon heuristics; dual transformation; Bx-tree label timestamps; family members and benchmark pointer. |
| Indexing Uncertain Data | 1900 | Uncertainty-region/pdf model; probabilistic threshold range queries with PTI x-bounds and U-tree; probabilistic NN pruning; UV-diagram/UV-index as Voronoi for uncertain objects. |
| Metric Space | 2253 | The metric postulates and the pseudo-, quasi- and ultra-metric relaxations, with the symmetrisation trick for quasi-metrics. |
| Multi step Query Processing | 2435 | The filter/refine framework: conservative vs progressive approximations, lower/upper bounding filter distances, ε-range and the optimal multi-step kNN algorithms; time series, road network and point-in-polygon applications. |
| Nearest Neighbor Query | 2478 | kNN definition over L_p norms; multi-step NN framework for high-d; reverse and aggregate NN variants. The recovered tail (from the adjoining *Nearest Neighbor Query in Spatiotemporal Databases*) adds a worked R-tree example of depth-first search with backtracking and k-list maintenance, the optimal-region argument (visit only nodes meeting the NN circle), and best-first with a mindist heap as the I/O-optimal algorithm. |
| Quadtrees (and Family) | 2946 | Point, region, PR, MX, MX-CIF, PMR quadtrees; linear quadtree locational codes (FL/FD) in B-trees; XBR tree; skip quadtree; temporal quadtrees; space-driven vs data-driven framing. |
| Range Query | 3079 | One-paragraph definition of (open/closed/one-sided) range predicates; stub entry. |
| Reverse Nearest Neighbor Query | 3234 | RNN/RkNN definitions and variants (bichromatic, continuous, stream); KM, RdNN-tree, SAA, SFT, TPL algorithms with a capability comparison; half-plane pruning. |
| R-Tree (and Family) | 3258 | R-tree structure and invariants, Guttman's linear/quadratic/exponential splits, deletion by reinsertion, range search walk-through, R+-tree, R*-tree, Hilbert R-tree, packing/bulk loading, high-d descendants, distributed R-trees. |
| Space-Filling Curves | 3547 | Definition of SFCs, locality preservation as the quality criterion, recursive vs non-recursive curves and their fractal nature. |
| Space-Filling Curves for Query Processing | 3548 | Sweep, scan, Z-order (called Peano), Gray, Hilbert constructions; segment-type and irregularity metrics; SFCs as a preprocessing step to reuse 1-D structures; SFC-based disk/NASD scheduling. |
| Spatial Indexing Techniques | 3592 | Point vs region access methods (LSD-tree, grid file, hB, buddy, BV; R-tree, quadtree); R-tree formal properties and insertion; packed, R+, R*, Hilbert R-trees; region quadtree and linear implementations; filter/refine role of MBRs. |
| Spatial Join | 3598 | Join classification by index availability; R-tree join with search-space restriction and plane sweep; z-value join; spatial hash join, PBSM, S³J, SSSJ; INLJ, seeded tree, build/sort-and-match, slot index join; comparative guidance. |
| Transaction-Time Indexing | 4211 | Transaction-time model, copy vs log baselines and the linear-space lower bound; MVBT (weak version condition, time splits, root*) and overlapping B-tree with costs; WOBT/TSB lineage. |
| Valid-Time Indexing | 4360 | Valid-time model as dynamic interval management; external interval/segment/priority-search trees; RI-tree; interval-as-point mapping; MAP21; Segment R-tree and Skeleton SR-tree; now-relative intervals. |
| Voronoi Diagrams | 4580 | Voronoi cells, edges, neighbours; uniqueness, NN-among-Voronoi-neighbours and ≤6 average neighbours properties; Voronoi-based NN structures (os-tree, D-tree, VoR-tree), validity regions, network and MapReduce uses. |

Adjacent fragment also used: *Dimension-Extended Topological
Relationships* (Clementini; pages adjoining p.1108) — 4IM, 9IM and
dimension-extended intersection matrices that define exact topological
refinement predicates (DE-9IM behind `ST_Relate`); used in the spatial-join
reference.

Weak or fragmentary in the bundle: *Range Query* (definition only),
*Space-Filling Curves* and *Curse of Dimensionality* (short key-point
entries); *Nearest Neighbor Query* is short itself, its algorithmic content
comes from the recovered spatiotemporal-NN tail, *Indexing and Similarity
Search*, *Closest-Pair Query* and *Multi step Query Processing*. The
supplement's tails for *Grid File*, *Space-Filling Curves for Query
Processing* and *Indexing Uncertain Data* turned out to be pages of
neighbouring entries (web-data-extraction GUIs, SPARQL, structured-text
indexing units) and added nothing to this skill.
