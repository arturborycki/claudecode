# EDBS entries in the beyond-relational-engines cluster

Pull the full text of any entry with the `edbs-reference` skill:
`python3 <edbs-reference>/scripts/edbs.py show "<Entry>"`.

| Entry | Printed page | What it gives an engine builder |
|---|---|---|
| Array Databases | 165 | Array algebra (constructor + condenser, lifted cell operators), array-as-attribute vs array-as-table, why arrays are type constructors, tiling strategies (regular, directional, area-of-interest, overlapping chunks), tile-streaming evaluation embedded in a relational plan, algebraic rewrites, SQL/MDA and WCPS |
| CAP Theorem | 395 | Precise statement, Gilbert–Lynch proof sketch, why P is not a design choice, PACELC extension |
| Cloud Computing | 475 | IaaS/PaaS/SaaS layering, public vs private cloud provisioning, consolidation and migration for power savings; little engine-level content |
| Column Stores | 518 | DSM vs NSM, column families/super columns, column-store optimizations (compression, late materialization, cracking), use of column stores for RDF vertical partitioning |
| Crowd Database Systems | 689 | Architecture with HIT manager; CrowdDB, Qurk, Deco, CDAS language extensions and crowd operators; cost/latency/quality as optimization objectives |
| Data Management in Data Centers | 786 | Key-value store design dimensions (data model, single-key access, range/hash partitioning, routing, master+lease vs gossip, replication); single-node-granule vs distributed transactional designs; storage/ownership decoupling; multitenancy pointers |
| Document Databases | 1237 | Text/document repository framing (IR + DB + object-store heritage); thin on engine internals |
| Elasticity | 1269 | Definition distinguishing elasticity from scalability (online, self-managed, includes contraction); pointers to ElasTraS, RTP, E-Store |
| Eventual Consistency | 1403 | Formal definition via committed prefixes and state-equivalent schedules; worked reconciliation example |
| Graph Data Management in Scientific Applications | 1636 | Large-graph vs graph-collection regimes; thick node/edge attributes; path/neighborhood/structural-property queries; descriptor-space indexing for graph collections |
| Graph Database | 1639 | Graph data model variants, regular path queries, schema for graphs, index and optimization pointers (DataGuides, path indexes, reachability), hypergraph/hypernode extensions |
| Main Memory DBMS | 2164 | Shift from I/O to CPU/cache costs, cache-conscious structures, durability via logging/NVRAM/replication, historical systems |
| Multitenancy | 2440 | Shared hardware / shared process / shared table models and their isolation–consolidation trade-offs; Salesforce pivot-table design; placement, SLOs, SQLVM, live migration |
| NoSQL Stores | 2513 | Data models (KV, wide-column, document, graph), HBase architecture, DHT routing, single-key atomicity, motivation and arrival of NewSQL |
| Object Data Models | 2525 | OODB vs ORDB modeling: OIDs, classes, inheritance, ODL/OQL, SQL:1999 UDTs, typed tables, REF types, scope, deref and implicit joins |
| Probabilistic Databases | 2830 | Possible worlds over x-tuples, extensional operators (independent/disjoint project, independent join), safe vs unsafe plans, #P-hard queries, MLN connection, applications |
| Provenance in Databases | 2904 | Why/where/how provenance, semiring provenance, annotation propagation (DBNotes default vs default-all), Trio, Perm/GProM, ProQL, curated-database provenance, applications |
| Provenance Storage | 2923 | Identity via URIs vs content-bound hashes; storing provenance with data vs separately; relational vs graph storage trade-offs; standards (OPM, PROV) as exchange formats |
| Query Processing and Optimization in Object Relational Databases | 3032 | Phase model of query processing (check, rewrite, cost-based optimization, execution) and optimizer components; mostly generic relational, little object-specific content |
| Query Processing over Uncertain Data | 3052 | TI/BID/PC representations, dichotomies, safe plans, decoupled lineage computation, knowledge compilation (OBDD/d-DNNF), anytime bounds, Monte Carlo/FPRAS, in- vs out-of-database inference |
| RDF Stores | 3100 | Triple/quad tables with dictionary encoding and covering indexes, SPARQL-to-SQL translation, vertical partitioning, property tables, distributed RDF (hash/graph partitioning, DFS, KV stores, graph exploration), benchmarks |
| Semi-structured Data | 3444 | Labeled tree/graph model, self-describing data, OEM/UnQL origins, relationship to object databases and XML |
| Software-as-a-Service (SaaS) | 3544 | SaaS delivery model and multi-user isolation; context only |
| Uncertain Data Models | 4297 | Completeness and strength of representation systems, c-tables, naive tables, why SQL NULLs are not strong, U-relations, TI/BID tables, lineage as conditions |
| XML Indexing | 4749 | Twig queries; node indexes; Dewey and interval numbering with axis predicates; path-index framework (DataGuide, Index Fabric, ROOTPATHS, DATAPATHS); sequence-based twig indexes |
| XML Storage | 4796 | Instance-driven (tabular, native paginated) vs schema-driven (shredding, inlining, cost-based) vs hybrid storage; losslessness/validation; prefix vs range order encodings |
| XQuery Processors | 4846 | Purely relational (Pathfinder loop-lifting), native (Timber, TLC algebra, structural joins, DP ordering), hybrid (DB2 pureXML: native XML type, QGM, path/value indexes, XNAV) architectures |
