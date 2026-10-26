# EDBS entries in the materialized-views-ivm cluster

Pull the full text of any entry with the `edbs-reference` skill:
`python3 <edbs-reference>/scripts/edbs.py show "<Entry>"`.

| Entry | Printed page | What it gives an engine builder |
|---|---|---|
| Answering Queries Using Views | 114 | Formal problem family (equivalent vs maximally-contained, LAV/GAV), containment mappings, rewriting size bounds and complexity, bucket / inverse-rules / MiniCon / chase-and-backchase, and the link to optimizer view usability. |
| Data Warehouse Maintenance, Evolution, and Versioning | 884 | Schema- and instance-level warehouse change (dimensions, hierarchies, members), evolution vs versioning trade-off, slowly changing dimensions; context for MV adaptation and re-aggregation after structure changes. Mostly warehouse modelling; only tangential to IVM proper. |
| Incremental Computation of Queries | 1830 | Insert/delete delta rules for every relational-algebra operator with minimality, auxiliary relations, and first-order maintenance of transitive closure (DAG insert/delete formulas, undirected and shortest-path variants). |
| Incremental Maintenance of Views with Aggregates | 1838 | Insertion/deletion propagation through aggregates vs the change-table technique with a REFRESH operator; shows why stacked aggregate views should propagate summary changes rather than row deltas. |
| Maintenance of Materialized Views with Outer-Joins | 2165 | Join-disjunctive normal form, subsumption graph, direct/indirect term classification, and the Larson-Zhou primary/secondary delta procedure. |
| Maintenance of Recursive Views | 2170 | Datalog/SQL recursive view semantics and stratification, semi-naive and memoing evaluation, DRed and PF algorithms compared on a transitive-closure deletion. |
| Ranking Views | 3092 | Top-k materialised views (non-self-maintainable under deletes, k..kmax buffering) and answering new ranking functions from stored ranked views (Onion, PREFER, LP-based). |
| Rewriting Queries Using Views | 3241 | Expansion-based definitions of contained/equivalent rewritings with SQL examples, bucket algorithm walk-through, binding-pattern limits, closed vs open world, pointers to CoreCover and MiniCon. |
| Self-Maintenance of Views | 3372 | Compile-time vs run-time self-maintainability, SPJ results, Huyn's view-only tests and the reduction of self-maintenance to query containment. |
| Side-Effect-Free View Updates | 3487 | Definition of side effects in view update translation, join-view examples, Keller criteria, Dayal-Bernstein graphs, constant complement, run-and-check and decoupled-instance approaches. |
| Updates Through Views | 4349 | The view update problem (translation W with Q_V(W(I)) = U(Q_V(I))), ambiguity and minimal-change translations, NP-hardness of minimal deletion propagation, CSP-based translation, applications. |
| View Adaptation | 4443 | Maintaining an MV across definition changes (SELECT/FROM/WHERE/GROUP BY/HAVING, UNION/EXCEPT), in-place vs query-answering adaptation. Short entry. |
| View Definition | 4444 | What a view definition is (name + query), CREATE VIEW basics and uses. Short; partly truncated in the bundle. |
| View Maintenance | 4445 | Taxonomy recompute/incremental, immediate/deferred, online/offline; SPJ join delta; deferred maintenance machinery (alerters, irrelevant updates, AD table + Bloom filter, state bug); online maintenance via horizontal/vertical versioning. |
| View Maintenance Aspects | 4448 | View-dependency graph and five classification dimensions (timing incl. snapshot views, view language, available information, modifications, applicability); applications in warehousing, streams (chronicles), caching, mobile. |
| Views | 4461 | Umbrella definitions: virtual vs materialised, materialised as detached data vs maintained derived data, view maintenance vs update-through-views duality. Very short. |
| Web Views | 4682 | Materialising DB-generated web fragments outside the DBMS; view selection under freshness, and ordering of update propagation as an online scheduling problem. |

Judged weak or tangential (used only lightly): "Data Warehouse Maintenance,
Evolution, and Versioning" (warehouse modelling rather than view
maintenance), "Views" and "View Definition" (very short, definitional),
"Web Views" (application-level). No entry was skipped entirely.
