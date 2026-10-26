# EDBS entries in the temporal-databases bundle

Pull any full entry with the `edbs-reference` skill:
`python3 <edbs-reference>/scripts/edbs.py show "<Entry>"`.

| Entry | Printed page | What it gives an engine builder |
|---|---|---|
| Abstract Versus Concrete Temporal Query Languages | 2 | Point-based (abstract) vs interval-encoded (concrete) semantics; the compile-and-preserve-answers criterion `Q(‖E‖) = ‖eval(Q)(E)‖`; GAPS example showing coalescing of subexpressions is mandatory in concrete languages; TRC vs FOTL |
| Allen's Relations | 95 | The 13 interval relations as endpoint conjunctions and the 2^13−1 disjunctive relations; basis of period predicates (the extraction is short and interleaved with unrelated fragments) |
| Bitemporal Interval | 309 | A VT×TT rectangle; set of bitemporal chronons in a discrete domain |
| Bitemporal Relation | 310 | Exactly one VT and one TT aspect (strict) vs several (loose: multiple realities, migrated TT) |
| Chronon | 425 | Smallest indivisible fixed-duration time unit; size fixed by the implementation; granule at finest granularity |
| Current Semantics | 716 | Formal temporal upward compatibility equation with timeslice at now; modifications must persist into the future; which products support it |
| Nonsequenced Semantics | 2506 | Timestamps as ordinary attributes; `NSEQ VT` modifier; why it is needed for expressiveness and legacy code |
| Now in Temporal Databases | 2517 | Three uses of now (nullary functions, stored variable, now-relative); serialization-consistent CURRENT_DATE via commit-time windows; bind operator; indexing growing extents (two indexes, four R-trees, GR-tree) |
| Period-Stamped Temporal Models | 2742 | Why conventional DBMSs mishandle period data (insert duplicates, keys, delete/update splitting, projection needing coalescing); survey of period models (Ben-Zvi, TQuel, Navathe–Ahmed, Lorentzos, Sarda, Tansel, TSQL2, SQL:2011) |
| Point-Stamped Temporal Models | 2770 | Snapshot, timestamp and parametric views and their equivalence; fixed vs varying numbers of time dimensions; intervals as compact encodings; non-uniqueness of multi-dimensional coalescing |
| Schema Evolution | 3287 | Non-loss evolution via information capacity; four classes of change (attribute, domain, relation, key); key evolution failing only on history |
| Schema Versioning | 3311 | Full vs partial versioning; bijective capacity requirement; practical equivalence; completed schema with view functions; three instance-amendment strategies; schema-version vacuuming |
| Sequenced Semantics | 3467 | S-reducibility, extended S-reducibility, interval preservation; statement modifiers; why coalescing cannot be the default |
| Snapshot Equivalence | 3512 | Weak equivalence over n time dimensions; the equivalence point-based optimizations may use |
| SQL-Based Temporal Query Languages | 3683 | Six design approaches (ADT, fold/unfold, point timestamps, syntactic defaults, statement modifiers, temporal expressions) compared on five benchmark queries |
| Supporting Transaction Time Databases | 3857 | Layered vs built-in; start-only timestamps and delete stubs; version chains on slotted pages; TSB-tree time splits; backward-delta compression; XID vs time; commit-time and lazy timestamping; SI, backup and bad-transaction recovery uses |
| Temporal Aggregation | 3899 | ITA, MWTA, STA, MDTA definitions; algorithms (two-scan, aggregation tree, k-ordered tree, balanced tree, bucket, SB-tree, MVSB-tree, MDTA) with complexities |
| Temporal Algebras | 3905 | Snapshot vs traditional evaluation; pointwise definitions of basic operators; value equivalence; tuple vs attribute timestamping; slice vs rollback duality; bitemporal coalescing order |
| Temporal Coalescing | 3917 | Definition, why results change, why it costs more than duplicate elimination; single-statement SQL, fixpoint UPDATE, and one-tuple-buffer sorted-scan algorithms |
| Temporal Data Models | 3940 | VT/TT definitions and rationale; point, period, temporal-element and attribute-timestamped models; temporally grouped models; why a naive (key, start) PK fails |
| Temporal Database | 3945 | Overview and map of the area; product notes (Oracle, log-mining tools); argument for disallowing deletion except vacuuming |
| Temporal Element | 3962 | Finite unions of intervals; closure under union, intersection, complement |
| Temporal Extensions in the SQL Standard | 3963 | SQL:2011 period definitions, application-time tables, FOR PORTION OF, WITHOUT OVERLAPS, temporal FKs, period predicates, system-versioned DML and query syntax, bitemporal tables (preceded in the extraction by the Temporal Expression entry) |
| Temporal Granularity | 3970 | Formal granularity definition; groups-into, finer-than, periodic grouping; bottom granularity and calendars; calendar algebra operators |
| Temporal Integrity Constraints | 3980 | Static/transition/temporal constraints in FOTL; potential vs finite satisfaction and decidability; historyless checking via bounded history encoding; constraints on interval-stamped data |
| Temporal Joins | 3986 | Temporal product, θ, equi, natural and outer joins defined via overlap/coalesce/expand; snapshot reducibility theorem; taxonomy of prior join operators; index vs non-index algorithm families (no algorithm detail in this extraction) |
| Temporal Projection | 4016 | Pairing derived facts with times; implicit (intersection) vs explicit constructs; temporal assignment |
| Temporal Query Processing | 4028 | Layered, monolithic and extensible architectures; which temporal operators conventional engines handle well (selection, join) vs badly (difference, aggregation, coalescing, constraints) |
| Temporal Vacuuming | 4040 | Vacuuming specifications as self-maintainable views; faithful history encodings and expiration operators; space bounds; impossibility for valid time and ad hoc queries; delete/keep specs; TSQL2 VACUUM and tuple EXPIRES |
| Time Domain | 4139 | Instant vs interval ontologies; discrete/dense/continuous, bounded, linear/branching/circular; anchored vs unanchored; SQL datetime and INTERVAL types; telic processes needing true interval timestamps |
| Timeslice Operator | 4159 | Valid and transaction timeslice with instant/period/element parameters; result-type variants; Oracle flashback as timeslice |
| Transaction Time | 4200 | Definition, consistency with serialization order, append-only growth, naming across products (system time, history tables) |
| TSQL2 | 4246 | Design goals and language concepts of the consensus temporal SQL (time ontology, baseline clock, six table kinds, restructuring, aggregates, vacuuming, schema versioning); path into SQL/Temporal and Oracle |
| Temporal Logic in Database Query Languages (fragment only; not a bundle entry, recovered from the Temporal Joins tail) | 3992 | FOTL with `since`/`until`, evaluation-point semantics, history of temporal logic in databases |
| Valid Time | 4359 | Definition; decision/event time as valid time of related facts; naming across products (application time, business time) |
