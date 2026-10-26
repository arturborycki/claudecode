# EDBS entries in this skill's bundle

Pull any entry in full with the `edbs-reference` skill:
`python3 <edbs-reference>/scripts/edbs.py show "<Entry>"`.

| Entry | Printed page | What it gives an engine builder |
|---|---|---|
| Access Path | 22 | Scan vs matching-index-scan definition; access-path "selectivity" measured in pages touched; Selinger 1979 as the origin of access-path selection |
| B+-Tree | 247 | Node invariants (half-full, root >= 2 children, doubly linked leaves), copy-up vs push-up on split, redistribute-then-merge on delete, O(log_p n) and O(log_p n + t/p) bounds, comparison with ISAM and hashing |
| Bitmap Index | 311 | Value-list vs bit-sliced indexes, Chan-Ioannidis base x encoding design space, equality/range/interval encodings with their bitmap counts and scan costs, EBI/EVI, bitmapped join indexes, BSI aggregates and arithmetic, binning, multi-resolution, RID-list break-even (cardinality < 32, selectivity > 1/32) |
| Bitmap-Based Index Structures | 316 | Row-position mapping, query evaluation with AND/OR/complement, BBC vs WAH word formats and their trade-off, row reordering for compression (Gray code), update-conscious padding, approximate (Bloom-based) bitmaps, commercial implementations including PostgreSQL bitmap scans |
| Bloom Filters | 320 | FPR derivation, optimal k = (m/n) ln 2 and f ~ 0.6185^(m/n), Bloomjoin, semijoin size estimation, differential files, counting/spectral/count-min/Bloomier variants |
| B-Tree Locking | 345 | Locks vs latches, latch coupling, five strategies for split propagation, B-link two-step splits and their costs, key-range / next-key locking, instant locks for right-edge hotspots, ghost records; mostly owned by concurrency-control-theory, used here for B-link structure and fence keys |
| Covering Index | 659 | Index-only plans, when wide covering indexes hurt, extend-existing-index guideline, SQL Server index intersection as a dynamic hash-based covering structure |
| Dense Index | 1045 | Dense definition; why secondary indexes must be dense; space and maintenance cost versus sparse |
| Extendible Hashing | 1429 | Directory with global depth, buckets with local depth, split with/without directory doubling, buddy merge and directory halving, repeated-doubling pathology and overflow-page mitigation |
| Hash-Based Indexing | 1683 | Static external hashing with overflow chains, expected O(1) vs linear worst case, equality-only limitation, pointers to dynamic schemes, Bloom filters and grid files |
| Index Creation and File Structures | 1842 | IR document-index pipeline (parse, extract features, sort and compile), posting lists plus lexicon with IDF and offsets, stop-word reduction; IR-centric rather than B-tree bulk build |
| Indexed Sequential Access Method | 1854 | Static multi-level sparse index over a sorted file, overflow chaining, I/O and space bounds, VSAM splits as the bridge to B+-trees, ISAM vs static hashing |
| Indexing Compressed Text | 1861 | Suffix tree/array costs, count/locate/extract, BWT and LF mapping, FM-index backward search with rank and SA sampling, Grossi-Vitter and Sadakane CSAs, LZ-index, compressed suffix trees, Pizza&Chili performance figures, String B-tree |
| Inverted Files | 2037 | Vocabulary + inverted lists, positional vs statistical postings, next-word index for phrases, three-phase sort/merge construction with perfect-hashed vocabulary, document-partitioned distribution, gap compression, static/dynamic pruning, update strategies, TAAT vs DAAT, caching layers |
| Join Index | 2051 | RID-pair definition (Valduriez), compact representation, pair-list vs value-based organisations; very short entry |
| Linear Hashing | 2093 | Split pointer and round state, hash family with the refinement property, addressing rule, controlled vs uncontrolled splits and resulting utilisation, merge thresholds |
| Primary Index | 2798 | Primary = index order equals file order, at most one per file, not necessarily on the primary key, clustering effect on range fetch cost |
| Secondary Index | 3337 | Secondary = non-ordering key, extra indirection, per-match page fetch cost example |
| Signature Files | 3491 | Superimposed block signatures, false drops and refinement, optimal bits-per-term formula, phrase and boundary limitations, negation queries, bit-sliced layout, S-tree with OR-propagated signatures and clustering criterion |
| Sparse Index | 3558 | Sparse definition; requires ordered file; primary indexes are sparse |
| Star Index | 3703 | Star index as the set of join indexes for each foreign-key join of a star/snowflake schema; very short entry |
| Suffix Tree | 3839 | Formal properties and O(n) size, Weiner/McCreight/Ukkonen/Farach construction, suffix links, DAWG/CDAWG, suffix arrays with LCP and linear-time construction references, index operations (membership, count, first position, list) |
| Text Index Compression | 4075 | Vocabulary vs postings, positional vs non-positional lists, self-delimiting codes (Rice/Golomb, Simple9/16, PForDelta), bit- vs byte/word-aligned speed trade-off, space figures, sampled skips and bitvectors for intersection, frequency-sorted lists, Block-Max, treaps |
| Tree-Based Indexing | 4217 | Overview: range queries need order, tree vs hash, primary vs secondary, the query/update/space cost triple |
| Trie | 4225 | Trie construction and search, node representations (table, lists, hashing, deep-shallow), compact tries, PATRICIA skip bits, applications (dictionaries, Burstsort, LZ) |
