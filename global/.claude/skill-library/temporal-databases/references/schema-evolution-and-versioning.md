# Schema evolution and schema versioning in temporal databases

A temporal database keeps data for years; schemas change in months. Once
history is retained (especially transaction time, which promises "the
database exactly as it was"), the engine must also answer: *under which
schema* is old data stored, read and updated? This file covers the
definitions, the information-capacity limits, the mechanisms (completed
schema, view functions, instance amendment strategies) and how they map to
catalog and storage design.

---

## 1. Definitions

| Term | Requirement | Strength |
|---|---|---|
| Schema modification | the schema can be changed | weakest; data may be lost |
| **Schema evolution** | schema can be modified **without loss of existing data**; only one (current) schema remains, old data is coerced to it | data preserved, old shape not |
| **Partial schema versioning** | data stored under any version can be **viewed** through any version, but **updated** only through one designated version (normally the current one) | practical target |
| **(Full) schema versioning** | data can be queried *and updated* retrospectively and prospectively through user-definable version interfaces | theoretically unattainable across non-equivalent versions |

The literature often conflates the two terms; keep them distinct in design
documents. Reasons multiple schema versions exist: historical succession
(the shape changed but history must keep its shape), future versions under
development/testing, and parallel alternative schemas over the same data
(object-oriented systems such as Encore, GemStone and Orion introduced this;
polymorphism was proposed to stabilise clients against change).

Temporal databases are hit hardest: historical tuples were recorded under
the schema of their time, and transaction-time support dictates that the old
schema remain accessible.

---

## 2. Kinds of change and their hazards

| Class | Examples | Hazard |
|---|---|---|
| Attribute evolution | add, drop, rename an attribute | what value do tuples stored under a version without the attribute show? "missing because undefined" must be distinguishable from NULL |
| Domain evolution | INTEGER → REAL, shorten CHAR(n) | false precision (old integers look like measured reals); truncation |
| Relation evolution | create, drop, split (vertical/horizontal), merge relations | almost always irreversible without active transformation functions |
| Key evolution | change PK membership, add/drop FKs | removing an attribute from a PK may keep **current** data unique yet violate uniqueness in **history** (a temporal-only failure); adding an FK may be violated by historical rows |

One change can span several classes (changing the domain of a key
attribute). Changes also propagate from the conceptual model (adding an EER
entity adds a relation; deleting a 1:N relationship removes an FK).
Empirical studies (Sjøberg 1993; de Vries & Roddick 2007) show schemas keep
changing throughout a system's life, not just during development.

For versioning, every transformation needs an **inverse** (or an active
transformation function): a vertical split is fine for evolution, but if the
old schema must remain usable the engine needs functions that recombine the
pieces on read and split writes.

---

## 3. Information capacity limits

Let `I(S)` be the set of all valid instances of schema `S`.

- **Non-loss evolution** requires `I(S_new) ⊇ I(S_old)` (the new schema can
  hold everything the old one could).
- **Updating through either of two schemas** requires equivalent
  information capacity: `I(S1) → I(S2)` must be a bijection. Hence full
  versioning across non-equivalent versions is impossible, which is why
  research settles for partial versioning.
- **Practical equivalence**: `S1 ≡ₚ S2` for database `D` if
  `I'(D|S1) → I'(D|S2)` is bijective, where `I'(D|S)` is the set of instances
  of `S` inferable from `D` under `S`'s constraints. Many capacity-changing
  edits lose nothing *for the data actually stored*: a domain declared far
  wider than used, a timestamp column that only ever held dates, a subclass
  table split where the discriminating attribute already exists. Whether a
  change is safe then depends on the data, so validate it against stored data
  (including history) rather than the schema alone.

Related theory: view update (Bancilhon & Spyratos), relative information
capacity (Hull; Miller, Ioannidis & Ramakrishnan), schema integration.
An alternative to changing the shared base schema is to apply a user's
schema change to a personal view (Ra & Rundensteiner).

---

## 4. Mechanisms

### 4.1 Completed schema

To query all data of a relation in one statement regardless of the version
it was stored under, define the **completed schema** `C`: the union of every
attribute ever defined for the relation, each with a domain general enough to
hold values from every version, and an implicit key equal to the maximal set
of key attributes over time. Then:

- `W_t : S_t → C` maps data stored under version `S_t` into `C`;
- `V_t : C → S_t` projects/converts `C` into the shape of version `S_t`;
- data stored at `t2` is read through version `t5` as `V_t5(W_t2(S_t2))`.

Catalog design consequence: keep versioned schema metadata (per relation:
list of versions with transaction-time validity, each with attribute ids,
domains and keys), plus a completed schema maintained incrementally. Use
**stable attribute identifiers** rather than names so renames do not break
`W`/`V` mappings.

### 4.2 Instance amendment strategies

When a schema change is accepted while old versions remain valuable:

| Strategy | Cost | Information | Notes |
|---|---|---|---|
| Eager coercion: rewrite all instances into the new structure | one big rewrite; simple reads | may lose information; change not reversible | the only option under plain schema evolution |
| Keep each tuple in its original format; translate on read | no rewrite; slower, more complex reads | preserved | each page/tuple must record its schema version |
| Keep original format; convert a tuple when it is next amended | rewrite spread over updates | preserved | most complex; bonus: identifies data not touched since the change |

Physical requirement for the lazy strategies: a schema-version id per tuple
or per page (or per file/segment), and decoders for every live version.

### 4.3 Query language support

No commercial query language supports schema versioning (as of the entry);
TSQL2 and SQL/SE (Roddick 1992) sketched it:

- reference to the completed schema for "all data";
- choosing the schema version via a global **schema time** (TSQL2: useful
  for embedded SQL with schema time fixed at compile time) or explicitly per
  query;
- a test distinguishing "value missing because the attribute was not defined
  then" from NULL;
- metadata queries: which schema version does this datum adhere to?

### 4.4 Operational concerns

- **Schema-level transactions**: composite schema changes need
  schema-level commit/rollback above data-level transactions.
- **Access rights**: in OO systems, changing a superclass changes inherited
  attributes of subclasses the modifier may not own.
- **Vacuuming schema versions**: delete an obsolete schema definition only
  when no stored data adheres to it and no transaction time refers to the
  period it was active; combining schema versioning with data vacuuming is
  open (see `transaction-time-implementation.md` §6).
- **Bitemporal schema versioning**: schema changes can themselves carry
  transaction time (when the change was made) and valid time (when it is
  effective); TSQL2's minimal support is transaction-time schema versioning.

---

## 5. Engine checklist

1. Catalog: relation → ordered schema versions with TT validity; attributes
   with stable ids, domain, nullability, key membership; completed schema.
2. Storage: schema-version id in tuple header, page header or file metadata;
   decoders for all live versions; `NULL` vs "not defined" distinction.
3. DDL: classify each change (attribute/domain/relation/key); run
   information-capacity checks against *all* versions of the data, including
   history (key evolution can fail only on history).
4. Time travel: an `AS OF t` query uses the schema version current at `t`
   by default, or the completed schema if requested; document which.
5. Constraints: decide whether new constraints apply to history (sequenced)
   or only to current data (as SQL:2011 does for system-versioned tables).

> **Beyond EDBS:** Production patterns map directly onto the instance
> amendment options. PostgreSQL (11+) adds a column with a constant default
> as a metadata-only change, storing the default in the catalog and
> materialising it lazily — "translate on read". Online schema change in F1
> (Rae et al., VLDB 2013) moves through intermediate schema states
> (delete-only, write-only) so that at most two adjacent versions are live
> at any time, a disciplined form of partial versioning. Apache Iceberg
> tracks columns by field id (renames and reorders are metadata-only, and
> each snapshot records the schema id it was written with); Delta Lake's
> column-mapping mode decouples logical names from physical column names
> for the same reason. Both make "read old snapshot under its own schema"
> possible, i.e., transaction-time schema versioning at table-snapshot
> granularity.

Sources: EDBS entries Schema Evolution (p.3287), Schema Versioning
(p.3311), TSQL2 (p.4246), Temporal Vacuuming (p.4040), Temporal Database
(p.3945).
