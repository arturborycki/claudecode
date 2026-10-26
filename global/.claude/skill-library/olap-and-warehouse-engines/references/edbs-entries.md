# EDBS entries in the olap-and-warehouse-engines cluster

Pull the full text of any entry with the `edbs-reference` skill:
`python3 <edbs-reference>/scripts/edbs.py show "<Entry>"`.

| Entry | Printed page | What it gives an engine builder |
|---|---|---|
| Active, Real-Time, and Intellective Data Warehousing | 41 | Definitions of active/real-time/right-time DW; analysis-rule components (events, analysis graph, decision steps, conflict table); catalogue of real-time loading options (trickle feed, trickle-and-flip, external cache, log shipping, streams, HTAP); RiTE memory-table catalyst |
| Array Databases | 165 | Array algebra (constructor, condenser, induced ops), array-as-attribute vs array-as-table, tiling strategies incl. overlap and two-level chunking, tile streaming, algebraic rewrites, parallel array architectures, SQL/MDA and WCPS |
| Bitmap Index | 311 | Full design space: value decomposition × equality/range/interval encoding, BSI, EBI, EVI, projection index, bitmapped join index, aggregation on bitmaps, BBC/WAH compression, binning and multi-resolution bitmaps, space/I-O break-evens |
| Column Stores | 518 | DSM vs NSM, lineage (KDB, Sybase IQ, MonetDB, X100, C-Store, Vertica, HANA), when column layout wins, RLE, sideways cracking, late materialization and invisible join pointers, RDF vertical partitioning |
| Cube | 709 | Cube vocabulary (cells, facts, sparsity, 4–12 dims typical), CUBE/ROLLUP with ALL, ROLAP/MOLAP/HOLAP split |
| Cube Implementations | 710 | Cube lifecycle: subcube selection (NP-complete, redundancy reduction, iceberg cubes), computation (sort/hash sharing methods, partitioning), ROLAP/MOLAP/graph/approximate algorithm families (CURE, ArrayCube, MM-Cubing, Dwarf), query processing over compressed cubes, propagate/refresh incremental maintenance |
| Data Mart | 793 | Mart vs EDW scope and grain, conformed dimensions for cross-mart consistency, ROLAP in EDW vs MOLAP in marts |
| Data Warehouse | 876 | Inmon's four properties, fact/dimension model basics, separation from OLTP; recovered tail carries adjacent life-cycle text: bottom-up bus delivery and the precise conformed-dimension test (identical or proper subset) |
| Data Warehousing in Cloud Environments | 908 | (Recovered tail adds adjacent non-conventional-data text: why summarizability blocks web/text data and the two integration styles.) Hive, HadoopDB, Shark (map pruning, partial DAG execution), Spark SQL, BlinkDB sampling, Presto, Redshift architecture; MapReduce vs parallel DBMS debate; ETL on MapReduce (ETLMR, CloudETL) |
| Data Warehousing Systems: Foundations and Architectures | 916 | OLTP vs DW workload contrast, star/snowflake, ROLAP/MOLAP/HOLAP, five-layer architecture, metadata kinds, seven EDW architectures (bus, hub-and-spoke, federated, virtual marts, …), HTAP examples |
| Dimension | 1099 | Dimension as hierarchically organized values; levels and level properties; ordering only by containment except time; star vs snowflake storage of a dimension |
| Extraction, Transformation, and Loading | 1432 | ETL as activity DAG with staging area; CDC methods (snapshot diff, triggers, log sniffing); transformation problem levels; bulk load vs row insert, MERGE; why ETL is not a query (black boxes, recoverability); ETL optimization lines; ELT and on-demand ETL |
| Hierarchy | 1705 | Hierarchy regularity: balanced (onto), non-covering (ragged), non-strict; multiple hierarchies; impact on summarizability |
| Indexing of Data Warehouses | 1880 | Projection, bitmap, compressed bitmap (BBC, word-aligned), hybrid B-tree/bitmap, bit-slice, aggregate-storing B-trees, summary indexes (min/max per partition — zone maps), join and star indexes |
| Join Index | 2051 | Join index as RID-pair set, compact representations, scan-based join evaluation (short entry) |
| Measure | 2217 | Additive / semi-additive / non-additive with flow/stock/value-per-unit types; distributive/algebraic/holistic aggregation; what to store in the cube |
| Multidimensional Data Formats | 2327 | HDF5/NetCDF as self-describing chunked array formats and their access/indexing challenges (short entry) |
| Multidimensional Modeling | 2328 | Canonical model, fact types (event, snapshot, cumulative), Kimball four-step process, SCD types 0–6 and minidimensions, summarizability = distributive + strict/onto/covering, irregular hierarchy examples, data vault, FASMI |
| Online Analytical Processing | 2558 | OLAP vs OLTP; minimal OLAP operator algebra (selection, roll-up, drill-down, ChangeBase, drill-across, projection, set ops); MDX structure and semantics |
| Optimization and Tuning in Data Warehouses | 2619 | Physical design problem formalization; redundant vs non-redundant techniques; view, index and horizontal-partitioning selection problems; derived partitioning via semijoins; vertical partitioning search space; advisors; self-tuning loops |
| Parallel and Distributed Data Warehouses | 2644 | Parallel DW design tuple (architecture, partitioning, allocation, replication, load balancing); derived fact partitioning with replicated dims; physical vs virtual vs adaptive virtual partitioning; skew; iterative vs conjoint design; Teradata AMP/BYNET experiment |
| Query Evaluation Techniques for Multidimensional Data | 2986 | Pointer entry: array algebras, array storage and indexing for scientific grids; gridfield algebra (short entry) |
| Query Processing in Data Warehouses | 3039 | DW query characteristics; robust-plan goal; star-specific rewrites (group-by pushdown, dimension Cartesian product); MQO; partition management; MV rewrite by coarser grouping; column storage, compression, bitmap and star indexes, MDC; online aggregation and AQP; GPU/FPGA |
| Snowflake Schema | 3520 | Formal snowflake definition (FK trees rooted at the fact); normalization trade-off vs star |
| Star Index | 3703 | Star index = one join index per fact–dimension FK; recovered tail is shared Star Schema text plus readings (Chaudhuri & Dayal 1997; Kimball & Ross 2002) — no new mechanism |
| Star Schema | 3703 | Formal star definition (compound key of FKs, no other FKs), surrogate keys, example schema |
| Storage of Large Scale Multidimensional Data | 3746 | HEAVEN: array DBMS on tertiary storage — tiles vs super-tiles, clustering, caching, online/nearline/offline placement, tape vs disk access characteristics |
| Summarizability | 3843 | The three summarizability conditions (disjointness, completeness, measure-type compatibility) with examples; temporal summarizability table by measure type and function |
| What-If Analysis | 4683 | What-if vs forecasting vs sensitivity analysis; source variables and scenario parameters; prediction cubes; system dynamics; seven-phase design method; disaggregation operator |

## Entries judged weak for engine builders

- Join Index (2051), Star Index (3703), Multidimensional Data Formats (2327),
  Query Evaluation Techniques for Multidimensional Data (2986): short
  definitional entries; content absorbed into the reference files.
- Data Warehouse (876), Data Mart (793), Cube (709), Dimension (1099):
  definitional; used for vocabulary only.
- Active, Real-Time, and Intellective Data Warehousing (41): the
  "intellective" part is visionary; only the active/real-time mechanisms are
  used.

## Supplement note

Recovered tails (`/home/claude/edbs/supplements/olap-and-warehouse-engines.txt`)
for Dimension, Query Processing in Data Warehouses, Indexing of Data
Warehouses, Array Databases and Query Evaluation Techniques for
Multidimensional Data contain only text of neighbouring, unrelated entries
(dimension reduction, deductive databases, moving-object indexing, stream
association rules, query expansion) and were not used.
