# View definition, expansion, and updates through views

Scope: what a view is in the catalog and how it is expanded into queries;
then the view update problem -- translating INSERT/UPDATE/DELETE on a view
into base-table changes -- from theory (side effects, complements,
complexity) to the SQL rules (updatable views, key preservation, WITH CHECK
OPTION, INSTEAD OF triggers) and an implementation recipe.

## 1. View definition and expansion

A view definition is a name plus a query; the result is normally not
stored and is re-derived whenever the view is referenced. Uses that shape
the implementation:

- shorthand for complex expressions and analytic formulas (OLAP);
- logical data independence -- applications keep working when tables are
  split, merged or renamed behind the view;
- access control -- grant on the view, not on the base tables;
- integration -- unified schema over remote sources (global-as-view).

### 1.1 Catalog representation

- Store the original text (for display/dump) **and** the bound tree with
  resolved object and column identifiers. Re-parsing text at use time
  breaks under search-path or name changes.
- `SELECT *` is expanded to an explicit column list at CREATE time (SQL
  standard behaviour; PostgreSQL does this): columns added to the base table
  later do not appear in the view. Tests should assert this.
- Record dependency edges (view -> table/column/function/type). DROP of a
  referenced object is RESTRICT by default; CASCADE drops dependents. Some
  engines instead mark dependents invalid and recompile lazily on next use
  (Oracle's model); then a failing recompile surfaces as an error at query
  time, not DDL time.
- `CREATE OR REPLACE VIEW` must keep the existing output columns' names and
  types (it may append columns) or dependents break.

### 1.2 Expansion = query modification

Stonebraker (SIGMOD 1975) introduced *query modification*: substitute the
view's definition into the referencing query (the same mechanism adds
integrity-constraint and authorisation qualifications). In a modern engine:

1. Binder replaces the view reference with a derived-table node holding
   the view's bound tree (with fresh range-variable identities per
   reference -- two references to one view are two independent subtrees).
2. The optimizer **merges** the derived table into the outer block when
   legal (pure SPJ view). Merging is blocked or restricted when the view
   has GROUP BY/aggregates, DISTINCT, LIMIT/OFFSET, window functions, set
   operations, volatile functions, or row-numbering pseudo-columns; then
   predicates are pushed into the view selectively (e.g. only on grouping
   columns for an aggregate view).
3. **Security-barrier views**: when a view is used for row-level filtering,
   a user predicate containing a leaky function (one that can raise an
   error or emit output revealing its argument) must not be evaluated
   before the view's own filter, or hidden rows leak. PostgreSQL models this
   with `security_barrier` views and LEAKPROOF function marking.
4. Privileges: base-table access through a view is classically checked
   as the view owner (definer rights).

> **Beyond EDBS:** PostgreSQL 15 added `security_invoker` views, which
> check base-table privileges (and row-level security) as the querying user.

## 2. The view update problem

Let `Q_V` be the view query, I the base instance, U an update on the view.
Applying U directly to `Q_V(I)` gives the desired view state `U(Q_V(I))`.
A **translation** is a base update W with

```
            Q_V
     I  ----------->  Q_V(I)
     |                  |
   W |                  | U
     v       Q_V        v
   W(I) ----------> Q_V(W(I))   =?=   U(Q_V(I))
```

W is **side-effect free** if the square commutes exactly. Insert U
requires adding the base tuples needed to derive the new view tuples;
delete U requires removing enough of the contributing base tuples (found
via lineage) to kill each derivation. Updates are usually modelled as
delete + insert, though replacements matter for some criteria.

Contrast with view maintenance: maintenance goes base -> view and always
has an answer (the question is cost); updates go view -> base and the
question is whether a correct, unique translation exists at all.

Two interpretations of "view" diverge here: if the view is *only* a query,
its possible states are exactly the images of `Q_V`, and some requested
view states are unreachable (the update must be rejected). If the view
instance may be decoupled from `Q_V(I)` -- e.g. storing view-level
exceptions -- more updates become translatable (Kotidis, Srivastava and
Velegrakis, ICDE 2006).

### 2.1 Where ambiguity and side effects come from

Example base (own): `Emp(eid PK, name, dept)`, `Dept(dept PK, floor)`.

| View shape | Insert | Delete | Typical issue |
|---|---|---|---|
| Selection `σ dept='R&D' (Emp)` | insert into Emp | delete from Emp | inserted row may fail the predicate (vanishes from view); UPDATE can move rows out |
| Projection dropping a column | missing column needs default/NULL; NOT NULL without default -> impossible | delete all base rows with that projection | projecting out the key: a view row may stand for several base rows (delete removes all) |
| Projection with DISTINCT | ambiguous | delete every witness | no 1:1 row correspondence |
| Join `Emp ⋈ Dept` | may need to insert Dept row; if dept exists, other attributes must agree | delete Emp row, Dept row, or both | deleting the Dept side removes every employee of that dept (side effect); inserting an Emp row with an existing dept may be fine, inserting a new Dept row whose key joins existing rows adds extra view rows |
| Union | which branch? | delete from all branches | branch choice is policy |
| Aggregate | no meaningful translation in general | -- | reject |

Even for a pure selection view, a deletion has multiple translations
(delete the row; change the selected column so it falls outside the
predicate; change another column), with different costs and side effects;
the natural one (delete the base row) is the minimal change.

## 3. Theory

- **Dayal and Bernstein (TODS 1982)**: model attribute dependencies of the
  schema and view with view-trace / view-dependency graphs; from them decide
  whether a correct translation exists and is unique; if not, reject.
  Removes the administrator from the loop, but cannot express "side effects
  are acceptable here".
- **Keller (PODS 1985)**: enumerates translation choices for selection,
  projection, select-project and SPJ views and gives algorithms satisfying
  five correctness criteria, usually summarised as: no side effects in the
  view; each base tuple changed at most once (one-step changes); no
  unnecessary changes; replacements that cannot be simplified; and no
  delete-insert pairs where a replacement would do. A consequence is that
  base keys must be visible in the view. **Keller (VLDB 1986)** chooses the
  translator at view-definition time by a dialog with the administrator.
- **Bancilhon and Spyratos (TODS 1981), constant complement**: views V and
  C are complementary if `(V(I), C(I))` determines I. Translating U while
  holding C constant yields at most one base state, so the translation is
  unique when it exists. Choosing the complement is the catch: the whole
  database is a trivial complement (and admits no updates), while finding a
  minimal one is NP-complete even for simple view classes; different
  complements admit different sets of translatable updates.
- **Complexity of deletion propagation** (Buneman, Khanna and Tan, PODS
  2002): finding a deletion translation that minimises side effects on the
  view (or the number of base deletions) is NP-hard already for
  project-join and join-union views, and polynomial for select-project-union
  and select-join views.
- **Constraint satisfaction** (Shu, ICDE 2005): represent the view as a
  conditional table; a view update becomes a disjunction of CSPs whose
  solutions are the candidate translations; semantic preferences are extra
  constraints.
- **Run-and-check**: apply a candidate translation, then test for side
  effects and roll back if any (Wang et al. 2008 for XML views); side-effect
  estimation via summaries prunes candidates (Peng et al., TKDE 2014).
- **Lineage-based**: trace which base tuples produced a view tuple (Cui,
  Widom and Wiener, TODS 2000; Fegaras, ICDE 2010 for XML) and delete those.
- **Bidirectional languages**: relational lenses (Bohannon, Pierce and
  Vaughan, PODS 2006) define views by combinators with a `get` (view
  extraction) and `put` (update propagation) satisfying round-trip laws:
  `put(get(s), s) = s` (GetPut) and `get(put(v, s)) = v` (PutGet), with
  functional dependencies tracked in the types so every legal update has
  exactly one translation.
- **Data coordination** (Lawrence, Pottinger and Staub-French, PVLDB 2011):
  two instances related through a virtual mediating instance; propagation
  one way is view maintenance, the other way is update-through-views.

## 4. What SQL engines do

### 4.1 Updatable-view rules

SQL-92 made a view updatable only when, roughly: one table reference in
FROM (a base table or an updatable view); no DISTINCT; select list of plain
column references, each at most once; no GROUP BY, HAVING, aggregates or set
operators; and WHERE subqueries do not reference the target table. SQL:1999
broadened updatability using functional-dependency analysis so some joins
and UNION ALL views qualify when each view row identifies a unique base row;
products implement subsets.

> **Beyond EDBS (product behaviour):**
> - **PostgreSQL** (9.3+) auto-updates simple views: one FROM item, no
>   WITH/DISTINCT/GROUP BY/HAVING/LIMIT/OFFSET/set operations/aggregates/
>   window functions at top level; non-column output expressions are
>   read-only columns. Anything else needs INSTEAD OF triggers (or legacy
>   rules).
> - **Oracle** join views: DML may modify only one *key-preserved* table per
>   statement -- a table whose key is still a key of the join result, so each
>   of its rows appears at most once in the view. `USER_UPDATABLE_COLUMNS`
>   exposes the analysis.
> - **SQL Server**: a modification through a view may touch columns of only
>   one base table; partitioned views (UNION ALL over tables with CHECK
>   constraints on a partitioning column) are updatable; INSTEAD OF
>   triggers cover the rest.

Key preservation is the practical form of "no side effects": if the target
table is key-preserved, deleting or updating a view row maps to exactly one
base row and touches no other view row.

### 4.2 WITH CHECK OPTION

Without it, `UPDATE v SET dept='Ops' WHERE eid=7` on a view filtered to
`dept='R&D'` succeeds and the row disappears from the view; an INSERT
through the view can create a row the view cannot see. WITH CHECK OPTION
makes INSERT and UPDATE through the view fail if the resulting row would
not satisfy the view's predicate. (DELETE is unaffected.)

For views defined over views:

- **CASCADED** (the default when just `WITH CHECK OPTION` is written):
  check this view's condition and the conditions of *all* underlying views,
  whether or not they declare a check option.
- **LOCAL**: check this view's condition, plus the conditions of underlying
  views that themselves declare a check option (each per its own mode).

Example (own):

```
CREATE VIEW v1 AS SELECT * FROM t WHERE a > 0;                 -- no option
CREATE VIEW v2 AS SELECT * FROM v1 WHERE a < 10 WITH LOCAL CHECK OPTION;
CREATE VIEW v3 AS SELECT * FROM v1 WHERE a < 10 WITH CASCADED CHECK OPTION;

INSERT INTO v2 VALUES (-5);  -- accepted: only a < 10 checked; row invisible via v2
INSERT INTO v3 VALUES (-5);  -- rejected: a > 0 inherited from v1 is checked
```

Implementation detail that matters: evaluate the check against the *final*
row image -- after column defaults and after BEFORE-row triggers on the base
table -- otherwise a trigger can move the row out of the view unchecked.
Under READ COMMITTED with re-evaluation of updated rows (PostgreSQL's
EvalPlanQual-style re-check), the view's WHERE must be re-checked against the
latest version of a concurrently updated row, exactly like a base-table
UPDATE's predicate.

### 4.3 INSTEAD OF triggers and rules

INSTEAD OF triggers let the view author define the translation
procedurally (the "administrator specifies the translation" school,
cf. Rowe and Shoens 1979). They make any view writable, including joins and
aggregates, at the cost of moving correctness to user code: nothing checks
the commuting-square property. The engine's obligations: fire per row with
OLD/NEW in view column terms; support RETURNING by letting the trigger
return the row; reject DML on views with neither automatic updatability nor
a trigger, with a clear error naming the blocking construct.

### 4.4 Materialised views as DML targets

Usually disallowed: the MV's content is defined by its query. Exceptions are
replication-style updatable MVs (Oracle's updatable materialised views push
local changes back to the master), which are really multi-master
replication with conflict handling, not view-update translation.

## 5. Implementation recipe (auto-updatable view DML)

```
bind_dml(target_view, stmt):
    chain = flatten nested views down to one base table B (or fail with reason)
    colmap = view column -> base column (or read-only marker)
    reject if stmt writes a read-only column
    if view has INSTEAD OF trigger for stmt kind: route to trigger; return
    pred = conjunction of view predicates along chain
    case INSERT:
        row_B = map(stmt values, colmap) with view-level then base defaults
        plan: INSERT INTO B; after BEFORE triggers on B, evaluate check
              predicates per CHECK OPTION modes along chain on final row
    case UPDATE:
        plan: UPDATE B SET mapped WHERE pred AND mapped(stmt.where)
              (respect security-barrier ordering of quals)
              check option on new row image
    case DELETE:
        plan: DELETE FROM B WHERE pred AND mapped(stmt.where)
    RETURNING expressed over the view's output columns
```

Notes:

- Cache the updatability analysis in the catalog (per view: target base
  table, column map, reason if not updatable) and invalidate it on DDL.
- For key-preserved join views, identify the target base row by its row id
  carried through the join; ensure the join cannot duplicate it.
- Row-level security policies on B apply in addition to the view's
  predicates; with definer-rights views decide whose policies apply.
- Error messages should state *why* a view is not updatable (e.g. "contains
  GROUP BY"), as products do.

## 6. Testing

- **Commuting-square property**: for random updatable views, instances and
  view DML, assert `Q_V(W(I)) == U(Q_V(I))` (as bags) after the statement;
  any mismatch is a side effect.
- **Lens laws** for any bidirectional component: GetPut and PutGet.
- **CHECK OPTION matrix**: nest views with {none, LOCAL, CASCADED} at each
  level and enumerate rows satisfying each subset of predicates; compare
  accept/reject with the standard's rules.
- **Triggers**: BEFORE triggers that rewrite the row so it violates the view
  predicate must be caught by CHECK OPTION.
- **Concurrency**: concurrent UPDATE through a view and a base UPDATE that
  moves the row out of the view; the view DML must re-check and skip.
- **DDL**: altering base columns referenced by a view; `SELECT *` views do
  not gain new columns.

## Key papers

Codd's 1985 rules (rule 6: theoretically updatable views must be updatable
by the system); Stonebraker, SIGMOD 1975; Bancilhon and Spyratos, TODS 1981;
Dayal and Bernstein, TODS 1982; Keller, PODS 1985 and VLDB 1986; Buneman,
Khanna and Tan, PODS 2002; Cui, Widom and Wiener, TODS 2000; Shu, ICDE 2005;
Kotidis, Srivastava and Velegrakis, ICDE 2006; Bohannon, Pierce and Vaughan,
PODS 2006; Lawrence, Pottinger and Staub-French, PVLDB 2011.

Sources: EDBS "Updates Through Views" (p.4349), "Side-Effect-Free View
Updates" (p.3487), "Views" (p.4461), "View Definition" (p.4444).
