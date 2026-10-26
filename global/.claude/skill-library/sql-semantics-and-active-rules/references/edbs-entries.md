# EDBS entries in this skill's bundle

Pull any full entry with the `edbs-reference` skill:
`python3 <edbs-reference>/scripts/edbs.py show "<Entry>"`.

| Entry | Printed page | What it gives an engine builder |
|---|---|---|
| Active Database Coupling Modes | p.25 | The HiPAC 3×3 E–C/C–A coupling matrix (7 valid, 2 invalid with reasons) and REACH's sequential/exclusive causally dependent detached modes — the hooks a TM must expose for rules |
| Active Database Execution Model | p.27 | The questions every rule engine must answer (scheduling, multiple triggered rules, cascades, condition invalidation, cycles) plus Snoop's four consumption contexts |
| Active Database Knowledge Model | p.28 | Dimensions of events, conditions and actions; the database states a condition (3) or action (4) may be bound to; parameter passing; rules as first-class objects |
| Active Database Management System Architecture | p.29 | Service decomposition (event monitoring, rule evaluation, scheduling, monitored TP), filtered event log, layered-vs-integrated trade-offs, implicit vs explicit invocation, real-time and distributed variants |
| Active Database Rulebase | p.35 | Rulebase as an evolving set (add/drop/enable/disable) and the definitions of termination and confluence |
| Active Database, Active Database (Management) System | p.35 | Why polling and application-embedded checks fail; knowledge vs execution model; history (HiPAC → ACT-NET manifesto → CEP) |
| Bag Semantics | p.252 | Multiplicity definitions of every algebra operator, SQL's ALL vs set forms, identities that fail, and bag/bag-set containment and equivalence complexity results |
| Composite Event | p.531 | Composite events, initiator/terminator/constituents, and the recent/chronicle/continuous/cumulative contexts with use cases |
| Data Definition Language (DDL) | p.748 | Short definition of DDL as schema-construct creation; GUI/API substitutes (thin) |
| Data Dictionary | p.749 | The two meanings (documentation vs system catalog) and the catalog's minimum contents; INFORMATION_SCHEMA as the queryable dictionary |
| Data Manipulation Language (DML) | p.792 | DML as retrieval+manipulation in interactive and embedded modes; expressiveness vs efficiency (thin) |
| Database Schema | p.973 | Schema as types, relationships and constraints declared once; catalog storage of the schema; schema-less contrast |
| Database Trigger | p.985 | Triggers as code fired by INSERT/UPDATE/DELETE events, before/after (pre/post) variants; pointers to the SQL3 active-features literature (mostly a fragment) |
| ECA Rule Action | p.1262 | Actions as arbitrary code run in or as a transaction per coupling mode; concurrent conflicting actions and cascading triggering |
| ECA Rule Condition | p.1263 | Condition forms (query non-empty = true, boolean expression, procedure); need to pass event parameters in and results on to the action |
| ECA Rules | p.1263 | The ECA semantics and the four reasons for separating event, condition and action (roles, coupling, optimisation, modelling) |
| Event in Active Databases | p.1371 | Atomic/instantaneous events, primitive categories, system- vs application-level parameters, explicit vs implicit events |
| Event Specification | p.1389 | Event algebras: operator vs functional grammars, non-occurrence intervals, disjunction and instantaneity pitfalls, parameterised detection as a join, BEAST performance finding |
| Java Database Connectivity | p.2045 | JDBC's role, history (JSR 54/114/221), driver manager, statement kinds including stored-procedure calls |
| Key | p.2057 | Superkey/candidate/primary key definitions via functional dependencies; key as a schema (not instance) property; BCNF |
| Null Values | p.2522 | Kinds of nulls, SQL's single NULL, possible-worlds semantics, and the admission that SQL nulls lack a complete formal semantics |
| Open Database Connectivity | p.2596 | ODBC's origin (SQL Access Group, 1992), driver-manager/driver architecture, language/DBMS/OS independence, non-relational drivers |
| QUEL | p.2975 | INGRES's tuple-relational-calculus language, predecessor of PostQUEL (historical only) |
| Query Language | p.2994 | Scope of a modern query language (DDL, DML, constraints, procedures, authorisation, triggers); relational completeness |
| SQL | p.3666 | SQL's design goals, history and standard revisions to SQL:2006, core query/DML/DDL semantics, constraints and triggers, advanced features, criticisms (NULLs, duplicates, impedance mismatch), embedded vs call interfaces |
| SQL Isolation Levels | p.3681 | P1–P3 phenomena and the four levels as the standard defines them; per-transaction mixing caveat; RC vs serializable throughput figure; pointer to the Berenson et al. critique |
| Stored Procedure | p.3764 | Procedures as server-side query-language programs with side effects, CALL-only invocation, SQL/PSM, UDFs as side-effect-free routines, pros/cons |
| Unicode | p.4335 | Unicode goals and the UTF-8/16/32 encodings (thin; collation consequences added as Beyond-EDBS) |
| Window Operator in RDBMS | p.4693 | Window clause anatomy with a moving-average example, standard history (SQL:1999/2003/2011), evaluation techniques (sort sharing, rank pushdown, parallelism, segment trees, WinMagic) |

Weak/thin entries (used only for definitions): QUEL, DDL, DML, Database
Trigger (largely a fragment plus reading list), Unicode. The bundle's
supplement of recovered tails added only the ECA Rule Condition reading list
(Dayal 1995) and the SQL/Temporal Part 7 history from a neighbouring entry; the
remaining recovered text belonged to unrelated neighbouring entries.
