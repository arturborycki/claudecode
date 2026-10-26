# EDBS entries in the relational-theory cluster

Pull any full entry with the `edbs-reference` skill:
`python3 <edbs-reference>/scripts/edbs.py show "<Entry>"`.
Page numbers are the printed pages of EDBS 2nd ed. (Liu & Özsu, Springer 2018).

| Entry | Printed page | What it gives an engine builder |
|---|---|---|
| Aggregation: Expressiveness and Containment | 74 | Why aggregation adds power yet stays local (no TC); per-aggregate equivalence results (`count` ⇔ isomorphism, `max` duplicate-insensitive); link between `count` and bag-set semantics; stratified aggregation in Datalog |
| Armstrong Axioms | 165 | The sound/complete FD inference rules behind closure-based implication |
| Bag Semantics | 252 | Multiplicity semantics of every RA operator; SQL ALL vs DISTINCT set ops; bag/bag-set containment and equivalence results; why minimization fails under bags; infinite multiplicities in recursive bag Datalog |
| Boyce-Codd Normal Form | 336 | BCNF definition, efficient test on given FDs, the `{AB→C, C→B}` impossibility of dependency-preserving BCNF |
| Cartesian Product | 399 | Product semantics in named vs unnamed perspectives (commutativity only with attribute names) |
| Certain (and Possible) Answers | 408 | Certain/possible answers as intersection/union over possible worlds; complexity map by representation, query class, OWA/CWA; data-integration and data-exchange variants |
| Chase | 418 | tgd/egd chase steps, failure, universality; standard/parallel/core chase; termination (weak acyclicity); uses: containment under constraints, implication, C&B view rewriting, data exchange |
| Comprehensions | 534 | Comprehension (calculus) notation as an IR for queries over sets, bags, lists; optimizations as transformations — background only |
| Computationally Complete Relational Query Languages | 547 | Genericity; why RA/While/LC are incomplete (TC, EVEN); QL and WhileNew completeness; cursor loops buy completeness at the cost of determinism |
| Conditional Tables | 578 | c-tables: nulls plus per-tuple conditions; closed under RA; algebra on c-tables; NP/coNP/Π2p costs |
| Conjunctive Query | 580 | CQ definition, range restriction, homomorphism view, CQ ≡ SPC algebra ≡ conjunctive SQL, CQ= vs CQ |
| Consistent Query Answering | 584 | Repairs and consistent answers; query rewriting approach (short entry) |
| Database Dependencies | 945 | Dependency history and unification (tgds/egds); finite vs unrestricted implication counterexample; axioms for FD+MVD and INDs; FD+IND undecidable; acyclic and k-cyclic JDs |
| Datalog | 1000 | Syntax, three equivalent semantics, immediate-consequence operator, naive/semi-naive, QSQ, magic sets, stratified negation |
| Difference | 1071 | Set difference as the sole non-monotone RA primitive (short) |
| Ehrenfeucht-Fraïssé Games | 1268 | Game characterization of FO quantifier rank; method for proving non-expressibility (parity, connectivity) |
| Equality-Generating Dependencies | 1331 | Formal egd definition and lineage |
| Expressive Power of Query Languages | 1415 | FO limits (TC, parity), locality and 0–1 laws, counting/aggregate extensions remain local, fixpoint logics and Immerman–Vardi, recursive SQL motivation |
| First-Order Logic: Semantics | 1482 | Structures, satisfaction, completeness vs Trakhtenbrot (finite validity undecidable) — background for why equivalence is undecidable |
| First-Order Logic: Syntax | 1484 | Terms, formulas, free/bound variables, proof systems — background |
| FOL Modeling of Integrity Constraints (Dependencies) | 1501 | Exact FO encodings of FD, key, JD, MVD, IND, FK; DED≠ for cardinality and domain constraints; representational constraints (XML-in-relations); constraints for optimization |
| Fourth Normal Form | 1514 | 4NF definition, strictness over BCNF, polynomial test |
| Functional Dependency | 1555 | FD, trivial FD, key dependency, linear-time implication via attribute closure |
| Implication of Constraints | 1808 | Finite vs unrestricted implication; complexity table for FD/MVD/JD/IND/full/tgd; axiomatizability; chase as decision procedure; constraint propagation to views |
| Incomplete Information | 1819 | Possible-worlds semantics; OWA/CWA; representation systems; Codd, naive, conditional tables; naive evaluation; view update and integration applications |
| Inconsistent Databases | 1825 | Constraint violation sources, repairs via minimal symmetric difference, consistent answers, FO rewriting example for keys |
| Join | 2049 | Natural, theta, equi, semi, outer joins as algebra operators |
| Join Dependency | 2050 | JD definition, link to lossless decomposition, no axiomatization, chase-based reasoning |
| Key | 2057 | Superkey/candidate/primary key terminology; keys as schema (not instance) property; keys via FD closure |
| Multivalued Dependency | 2447 | MVD definition, MVD as binary JD, FD+MVD axioms, polynomial implication |
| Naive Tables | 2459 | Marked nulls, naive evaluation (nulls as distinct constants), dropping null tuples for certain answers, exact answers for compositionality |
| Normal Forms and Normalization | 2509 | Anomalies, BCNF decomposition example, lossless join and dependency preservation, information capacity, catalog of NFs |
| Null Values | 2522 | Kinds of nulls; SQL's single NULL lacks a clean formal semantics (short) |
| Order Dependency | 2631 | OD definition and relation to FDs; inference co-NP-complete; uses in sort elimination, interesting orders, monotone expressions, warehouse join elimination |
| Parameterized Complexity of Queries | 2680 | W[1]-hardness of CQ evaluation by query size; Yannakakis' linear algorithm for acyclic CQs; hypertree width; Courcelle |
| Positive Relational Algebra | 2776 | SPJRU fragment, non-redundant operator set, equivalence to UCQ and nonrecursive Datalog |
| Projection | 2893 | Projection semantics, cardinality bounds (short) |
| Query Containment | 2981 | Chandra–Merlin homomorphism/canonical DB test; minimization; CQAC containment (Π2p); Datalog containment results; answering queries using views |
| Query Processing in Deductive Databases | 3046 | Bottom-up (INFER/fixpoint) vs top-down (SLD), Datalog→RA equations, optimization dimensions, magic sets/counting, semantic optimization, stratification via dependency graph |
| Relational Algebra | 3146 | Many-sorted RA definition, domain independence, Codd's theorem via active-domain translation, undecidable equivalence/satisfiability |
| Relational Calculus | 3147 | Domain and tuple RC, active domain, domain dependence examples, genericity, safe sublanguages |
| Relational Model | 3149 | Intuitive, conceptual, SQL DDL, and formal (FO interpretation, CWA) views of the model (introductory) |
| Safety and Domain Independence | 3269 | Finite vs domain-independent queries, undecidability, effective syntax results, safe/range-restricted classes, finiteness dependencies with arithmetic |
| Second Normal Form (2NF) | 3337 | 2NF definition via prime attributes |
| Selection | 3371 | Selection and generalized selection conditions |
| Third Normal Form | 4122 | 3NF definition, synthesis guarantees lossless + dependency-preserving, NP-complete test |
| Tuple-Generating Dependencies | 4256 | tgd definition; use as schema mappings in data exchange |
| Union | 4344 | Union semantics, commutativity/associativity, size bound (short) |
| Weak Equivalence | 4600 | Snapshot (weak) equivalence of temporal relations; notes the older Aho–Sagiv–Ullman use of "weak equivalence" for algebraic expressions — belongs mainly to `temporal-databases` |
| Zero-One Laws | 4859 | 0–1 law definition, use for non-expressibility (EVEN), which logics have it, limits of the technique |
