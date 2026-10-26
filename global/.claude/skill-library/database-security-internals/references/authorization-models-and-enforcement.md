# Authorization models and their enforcement points in the engine

Scope: DAC (SQL GRANT/REVOKE, grant option, revocation semantics), RBAC
(RBAC96 / ANSI INCITS 359), temporal and context-aware authorization,
fine-grained (row/column/cell) control via views, query modification and
row-level policies, purpose-based access, and where each check lives in a
real engine (parser/binder, rewriter, optimizer, executor, catalog, plan
cache). MAC/MLS is in `mls-and-secure-concurrency-control.md`.

---

## 1. The abstract model and the reference monitor

An authorization is a triple `(s, o, p)` — subject `s` may exercise privilege
`p` on object `o` — optionally extended with a sign (+/-), a grantor, a
timestamp, a validity condition (time, context, predicate) and a "with grant
option" flag. The authorization state is a set of such tuples; in a relational
engine it is itself relational data in the catalog (e.g. `pg_class.relacl` as
an array of `aclitem{grantee, grantor, privs, grant_opts}`, System R's
`SYSAUTH`/`SYSCOLAUTH`).

The **reference monitor** is the trusted module that mediates every request.
Three properties, all of which translate to concrete engine invariants:

| Property | Engine meaning | How it breaks in practice |
|---|---|---|
| Complete mediation | Every path that touches an object checks it: SQL DML, COPY/bulk load, utility commands, catalog functions, FDW/external tables, replication slots, `EXPLAIN`, statistics views, large-object APIs | A new access path (bulk loader, system function returning rows) added without a check |
| Non-bypassable | No API reaches storage below the monitor | Internal "fast path" executors, extension hooks, plugin APIs that open relations directly |
| Tamper-proof | The policy store and the monitor code cannot be altered by the subjects it controls | DBA can rewrite the catalog / disable auditing; see insider section in `auditing-intrusion-and-compliance.md` |

Subject hierarchy: users, groups, roles, and *processes acting on behalf of a
user* (stored procedures, triggers, views with definer rights, background
workers). Object hierarchy: database > schema > table > column > row > cell,
plus non-data objects (functions, sequences, types, large objects).
Privilege hierarchy: a subsumption order (e.g. `ALL` ⊇ `UPDATE`; in some
systems `UPDATE` implies the read needed for a `WHERE` clause — it must not,
see §6.4).

Policy defaults:
- **Closed policy** (default deny): access only if a positive authorization
  exists. All SQL engines.
- **Open policy** (default allow): access unless a negative authorization
  exists. Rare in DBMSs; appears in some content-management systems.
- **Mixed** (positive + negative): needs a conflict-resolution rule —
  denials-take-precedence (most common), most-specific-takes-precedence,
  explicit priorities, or strong/weak authorizations (strong cannot be
  overridden; weak can be overridden by more specific ones). SQL Server's
  `DENY` is the mainstream example of signed authorizations.

---

## 2. Discretionary access control in SQL

### 2.1 Ownership and privileges

- The creator of an object is its owner and holds all privileges with grant
  option implicitly. Ownership is not a grantable privilege in standard SQL
  (it can be transferred by `ALTER ... OWNER`).
- SQL object privileges: `SELECT`, `INSERT`, `UPDATE`, `DELETE`, `REFERENCES`,
  `USAGE`, `TRIGGER`, `EXECUTE`, `UNDER`; `INSERT`/`UPDATE`/`REFERENCES`/`SELECT`
  can be column-scoped.
- `REFERENCES` exists because a foreign key is itself an information channel:
  the referencing user can probe existence of parent keys (insert fails ⇔ key
  absent) and can block deletes on the parent. Treat FK creation as a read of
  the parent key column.
- Creating a view requires `SELECT` on every relation in its definition; the
  view creator gets on the view only those privileges it holds on all
  underlying objects, and gets grant option on the view only if it has grant
  option on all of them (System R rule).

### 2.2 Administration policies: who may change the authorization state

| Policy | Rule | Fits | Drawback |
|---|---|---|---|
| Security-administrator (SA) only | Only the SA grants/revokes (the norm under MAC, where only the SA relabels subjects/objects) | Small or high-assurance systems | Centralized bottleneck; rare in general DBMSs |
| Object-owner | The creator owns the object and alone administers it | Default in DBMSs and OSs | Owner may not be the real data custodian (the organization) |
| Owner + delegation | Owner passes administration on, optionally per privilege (e.g. read only); SQL `WITH GRANT OPTION` for privileges, `WITH ADMIN OPTION` for role membership (grantee may grant the role onward) | What SQL engines implement | Same privilege reachable via several grantors ⇒ revocation semantics (below) |
| Joint | A grant takes effect only when all designated administrators of the object issue it (e.g. two job functions) | Collaborative / four-eyes settings | Needs a pending-grant state and quorum tracking in the catalog |

Delegation is why each authorization tuple must record its **grantor** (the
same privilege can arrive from several sources) and, for System R-style
recursive revocation, its **grant timestamp**: without the timestamp the engine
cannot decide whether a later grant by the revokee was supported by a
surviving authorization. `ADMIN OPTION` needs exactly the same treatment for
role-membership edges (revoking a role from an admin must cascade or restrict
over memberships that admin granted).

### 2.3 Grant option and the grant graph

Represent the authorization state for one (object, privilege) as a directed
multigraph: nodes are subjects, an edge `g → r` labelled `(t, go)` records
that grantor `g` granted to grantee `r` at time `t`, with grant option flag
`go`. The owner is the root. A subject holds the privilege iff it has at least
one incoming edge whose grantor *validly* held the privilege with grant option
at the time of the grant.

```
   owner A --(t=5, go)--> David
      |                     |
   (t=10, go)            (t=30, go)
      v                     |
     Bob <------------------+
      |
   (t=20)
      v
    Chris
```

Two classic semantics for `REVOKE`:

**(a) Timestamp-based recursive revocation (Griffiths & Wade, TODS 1976;
corrected by Fagin, TODS 1978).** When `g` revokes from `r`, delete the edge
and then recursively delete every grant `r → x` made at time `t_x` for which
`r` no longer has a supporting incoming grant-option edge with timestamp
`< t_x`. The resulting state equals the state that would exist had the revoked
grant never been made. In the figure: if A revokes Bob's t=10 grant, Bob still
holds via David (t=30), but Chris's grant (t=20) was made before t=30, so it
was supported only by the revoked edge and is removed. If David's grant to Bob
had been at t=15, Chris would keep the privilege.

**(b) Graph-reachability ("abandoned privilege") semantics — SQL standard.**
After removing the revoked edge, a privilege descriptor is *abandoned* if it is
no longer reachable from the owner through grant-option edges. `REVOKE ...
RESTRICT` fails if any descriptor would be abandoned; `REVOKE ... CASCADE`
removes all abandoned descriptors (and dependent objects such as views whose
creator loses `SELECT`, and constraints whose creator loses `REFERENCES`). No
timestamps: in the figure Chris keeps the privilege because Bob is still
reachable via David regardless of order.

| Semantics | Pros | Cons |
|---|---|---|
| Timestamp recursive | "As if never granted" — strongest; prevents laundering a grant through a later re-grant | Must store per-edge timestamps; harder to explain; cycles need care (Fagin's correction) |
| Reachability (SQL) | No timestamps; simple BFS/DFS from owner; RESTRICT gives safe default | A privilege granted under a revoked authority survives if any path re-appears later |
| Non-cascading (Bertino, Samarati, Jajodia, CCS 1993) | Revoking a manager does not strip their reports; grants made by the revokee are re-attributed to the revoker | Revoker silently inherits responsibility for grants it never made; must be explicit in audit |

`REVOKE GRANT OPTION FOR p` removes only the `go` flag and cascades to grants
that depended on it.

Algorithm (reachability semantics), per (object, privilege):
```
revoke(g, r, cascade):
  E := E \ {edge g->r}
  live := BFS from owner over edges whose source is live and has go=true
          (owner is live; a node is live if it has an incoming edge from a
           live node with go, or is the owner)
  abandoned := {edges e=(x->y) | x not live}  ∪ dependent objects
  if abandoned != ∅ and not cascade: rollback; error "dependent privileges exist"
  delete abandoned; drop/invalidate dependent views, constraints, cached plans
```
Complexity O(|V|+|E|) per object-privilege pair. In a catalog stored as ACL
arrays per object this is cheap; the expensive part is dependent-object
discovery (`pg_depend`-style dependency graph) and plan-cache invalidation.

### 2.4 Inherent weakness of DAC

DAC controls access to *objects*, not *information flow*. Anyone who can read
can copy into a table they own and grant it onward; any program inherits the
invoking user's full rights, so a Trojan-horse procedure, UDF, or extension
can exfiltrate whatever the caller can read. Engine consequences:
- `SECURITY DEFINER` functions run with the owner's rights: they must pin
  `search_path` (or the equivalent name-resolution scope), or a caller can
  plant objects that the definer function resolves to (a privilege
  escalation class seen in several engines).
- Information-flow guarantees require MAC (labels on data) or provenance
  tracking — DAC alone cannot provide them.

---

## 3. Role-based access control

### 3.1 RBAC96 family (Sandhu, Coyne, Feinstein, Youman, IEEE Computer 1996)

| Model | Adds |
|---|---|
| RBAC0 | Users U, roles R, permissions P, sessions S; `UA ⊆ U×R`, `PA ⊆ P×R`; `user(s)`, `roles(s) ⊆ {r | (user(s), r) ∈ UA}` |
| RBAC1 | Role hierarchy `RH ⊆ R×R`, a partial order; senior inherits junior's permissions (and members of senior are implicitly members of junior) |
| RBAC2 | Constraints on UA, PA, session activation: mutual exclusion (SoD), cardinality, prerequisite roles |
| RBAC3 | RBAC1 + RBAC2, including constraints on the hierarchy itself |

The session is the RBAC "subject": a user may hold several concurrent sessions
with different active role subsets. Effective permissions of a session =
∪ over active roles r of `PA(r')` for all `r' ≤ r` (juniors of r, reflexive).
This is how least privilege is realised: activate only what the task needs.

Administrative cost: with `n_u` users, `n_p` permissions, `n_r` roles,
direct user-permission assignment needs up to `n_u·n_p` tuples; RBAC needs
`n_r·(n_u + n_p)`.

### 3.2 ANSI/INCITS 359-2004 (derived from the NIST proposal, Ferraiolo et al.
TISSEC 2001)

1. **Core RBAC**: UA, PA, sessions, plus review functions (users of a role,
   roles of a user).
2. **Hierarchical RBAC**: *general* (arbitrary partial order, multiple
   inheritance) or *limited* (tree or inverted tree).
3. **Static SoD (SSD)**: constraint on UA — for a role set RS and integer n≥2,
   no user is assigned to n or more roles of RS. Must hold over the
   hierarchy-closed assignment (inherited memberships count).
4. **Dynamic SoD (DSD)**: same shape but on the roles simultaneously active in
   one session.

Further SoD variants in the literature (not in the standard): history-based,
object-based (same user may not act on the same object in both roles),
operational, order-dependent; specified e.g. in RCL2000 (Ahn & Sandhu,
TISSEC 2000).

Administration: ARBAC97 (Sandhu et al., TISSEC 1999) uses administrative
roles with *ranges* of the hierarchy they may modify (can_assign, can_revoke,
can_modify); SARBAC (Crampton & Loizou, TISSEC 2003) uses administrative scope.
RBAC can encode both DAC and lattice-based MAC (Osborn, Sandhu, Munawer, TISSEC
2000), which is why it is called policy-neutral.

### 3.3 RBAC in SQL engines

SQL:1999 roles: `CREATE ROLE`, `GRANT role TO user|role [WITH ADMIN OPTION]`,
`SET ROLE`. Engine design points:

- **Effective-role computation**: the closure over role-membership edges.
  Cache per session; invalidate on any `GRANT/REVOKE role` (catalog
  invalidation message). Detect cycles at grant time (reject `GRANT a TO b`
  if `a` is reachable from `b`).
- **Inherit vs activate**: PostgreSQL distinguishes members who *inherit*
  privileges automatically from those who must `SET ROLE`. The latter is the
  RBAC session-activation model; the former is closer to groups. Make the
  distinction explicit; DSD only makes sense with activation.
- **SoD enforcement**: SSD checked at `GRANT role` time against the
  hierarchy-closed membership (and re-checked when the hierarchy changes —
  adding an edge can create a violation for existing users). DSD checked at
  `SET ROLE`. Few engines implement SoD natively; it is commonly delegated to
  identity-governance tooling, so document the gap.
- **Ownership by roles**: objects owned by a role rather than a person avoid
  orphaned ownership when staff leave.

> **Beyond EDBS:** Attribute-based access control (ABAC; NIST SP 800-162,
> 2014) generalises roles to predicates over subject/object/environment
> attributes, and XACML expresses such policies. In engines, ABAC surfaces as
> row-level policies whose predicates reference session attributes
> (`current_setting(...)`, `SYS_CONTEXT(...)`), which is exactly the query
> modification mechanism of §5.

---

## 4. Temporal and context-aware authorization

| Model | Temporal element | Key mechanism |
|---|---|---|
| TAM (Bertino, Bettini, Ferrari, Samarati, TODS 1998) | Periodicity constraint `<[begin,end], P>` on each DAC authorization | Derivation rules `A op Φ` with op ∈ {WHENEVER, ASLONGAS, UPON}; denials-take-precedence; uniqueness of derived state checked via a critical-set analysis |
| TDAM (Atluri & Gal, TISSEC 2002) | Formula over time *and object timestamps*, e.g. `t ≥ t_written + 1 month` | Authorization validity is a predicate evaluated at access time |
| TRBAC (Bertino, Bonatti, Ferrari, TISSEC 2001) | Periodic enabling/disabling of roles | Role triggers (`enable doctor → enable nurse` after Δ); safety = unique execution model, checked by a dependency-graph analysis; conflicts resolved by priority + denials-take-precedence |
| GTRBAC (Joshi, Bertino, Latif, Ghafoor, TKDE 2005) | Periodicity and duration on UA, PA, enabling; duration/cardinality on activation | Separates *enabled* (activatable) from *active*; per-role and per-user activation limits; time-based SoD; three conflict types |

Derivation operators (TAM), with Φ a boolean formula over authorizations:
- `A WHENEVER Φ`: A holds at each instant where Φ holds.
- `A ASLONGAS Φ`: A holds at instant t if Φ held at every instant from the
  rule's begin up to t (history over an interval).
- `A UPON Φ`: A holds from the first instant at which Φ held (an event).

Engine implications:
- **Clock source**: authorization decisions that depend on time must use a
  single trusted clock; with distributed nodes, decisions at different nodes
  for the same transaction can diverge. Decide whether validity is evaluated
  at statement start, transaction start, or per-row access, and make it
  consistent with the snapshot (a long transaction that started while a role
  was enabled — does it keep it?). Prefer statement-start evaluation recorded
  in the plan's security context, and re-check at commit for writes if
  revocation must be prompt.
- **Scheduled state changes**: TRBAC-style enabling/disabling is a timer
  service that mutates catalog state; it must emit catalog invalidations
  exactly like a manual `REVOKE`.
- **Distributed/replicated policy**: with policies replicated lazily, a
  transaction may be authorized against a stale version at one node. Two-Phase
  Validation Commit (Iskander, Wilkinson, Lee, Chrysanthis, 2011) piggybacks a
  policy-and-credential re-validation and the policy version on the 2PC
  prepare vote; the coordinator commits only if versions agree (view
  consistency) or are all latest (global consistency).

---

## 5. Fine-grained access control: views, query modification, row policies

### 5.1 Two classic mechanisms

| Mechanism | Origin | How it works | Wins when | Cost / risk |
|---|---|---|---|---|
| Views as protection objects | System R | Grant `SELECT` on a view that projects/filters; user has no privilege on base table; view executes with definer's rights | Static, per-group policies; column hiding | View explosion (one per policy variant); updates through views need `WITH CHECK OPTION`; users can see view definitions unless hidden |
| Query modification | INGRES (Stonebraker & Wong, 1974) | Rewriter conjoins the user's permitted predicates into the query's qualification before optimization | Per-user/per-row policies, many users, policy as data | Optimizer must not reorder untrusted code before the policy predicate; policy predicates add cost; interacts with every rewrite rule |

Modern engines implement query modification as **row-level security (RLS)**:
Oracle VPD (`DBMS_RLS` policy functions returning a predicate string),
PostgreSQL `CREATE POLICY ... USING (...) WITH CHECK (...)`, SQL Server
security predicates (filter + block predicates). DB2 RCAC adds column masks.

### 5.2 Truman vs non-Truman semantics (Rizvi, Mendelzon, Sudarshan, Roy,
SIGMOD 2004)

- **Truman model** (what RLS implements): the query is silently evaluated over
  the user's authorized view of each table. Answers can be *misleading* —
  `SELECT avg(salary) FROM emp` returns the average over the visible rows, not
  the true average, with no signal.
- **Non-Truman model**: the query is accepted only if it is *conditionally
  valid* — answerable exactly from the authorized views for the current
  database state — otherwise rejected. Answers are never wrong, but validity
  checking is query-containment-hard in general; inference rules give a sound
  approximation.

Choose consciously and document it; analysts often assume non-Truman
semantics from a Truman system.

### 5.3 Where policy predicates go in the pipeline

```
parse -> bind/resolve names -> [privilege check on objects]
      -> rewrite (view expansion, RLS predicate injection, column masks)
      -> optimize (must respect security barriers)
      -> plan cache (keyed by role/policy version!)
      -> execute (per-row WITH CHECK on INSERT/UPDATE; masks applied at output)
```

Invariants an implementation must state and test:

1. **Object privilege check before any data-dependent work.** Name resolution
   errors must not distinguish "does not exist" from "exists but no privilege"
   for objects the user cannot see (otherwise catalog probing works).
2. **Policy predicate injected at the scan of every protected relation
   instance**, including those reached through views, CTEs, subqueries,
   `MERGE` sources, FK-check queries, and set operations. RI checks that
   bypass RLS (needed for correctness) must not return row contents.
3. **Security barrier**: a user-supplied predicate or function that could leak
   data (side effects, error messages, timing) must not be evaluated on rows
   before the policy predicate has filtered them. PostgreSQL: quals from
   `security_barrier` views and RLS are placed below user quals unless the user
   qual's functions are marked `LEAKPROOF`. Test with a UDF that `RAISE`s the
   argument value: it must never see a hidden row.
4. **Writes**: `INSERT/UPDATE` rows must satisfy the policy's check predicate
   *after* modification (block predicate), otherwise a user can update a
   visible row into an invisible state or insert rows for other tenants.
   `UPDATE ... RETURNING` and `ON CONFLICT` paths need both read and write
   policies.
5. **Plan cache**: a plan built with policy predicates for role A must not be
   reused by role B. Key cached plans on (user or role set, policy catalog
   version, relevant session context variables) or re-run the rewriter on
   reuse. Invalidate on `ALTER POLICY`, `GRANT/REVOKE`, role membership change.
6. **Owner/bypass**: table owners and superusers bypass RLS by default in
   several engines (PostgreSQL needs `FORCE ROW LEVEL SECURITY` to apply to
   the owner; `BYPASSRLS` attribute). Make bypass explicit and audited.
7. **Aggregates and statistics**: optimizer statistics (histograms, MCVs,
   n_distinct), `EXPLAIN` row estimates and `ANALYZE` timings reveal hidden
   rows. Restrict statistics views to users who can read the whole column
   (PostgreSQL `pg_stats` filters by column privilege); consider whether
   `EXPLAIN` should be allowed on RLS tables.
8. **Materialized views, caches, result caches, replicas**: derived storage
   computed with definer rights must not be readable more broadly than its
   sources; a result cache must key on the security context.

### 5.4 Column- and cell-level control

- Column privileges (`GRANT SELECT (a,b)`): enforce at bind time against the
  *referenced* column set, including columns referenced only in `WHERE`,
  `ORDER BY`, `GROUP BY` and join conditions — a predicate on a hidden column
  is a read (binary search on `salary > x` recovers the value).
- `SELECT *` must expand to permitted columns only or fail; choose and test.
- Dynamic masking (SQL Server Dynamic Data Masking, DB2 column masks) replaces
  values in the output but leaves them usable in predicates: it is a
  presentation feature, not a confidentiality boundary, because predicates on
  masked columns leak the value. Say so in docs.
- Cell-level labels (Oracle Label Security, MLS element labels) are MAC
  mechanisms; see the MLS reference.

> **Beyond EDBS:** PostgreSQL (9.5+) policies are *permissive* (OR-combined)
> by default; since v10, *restrictive* policies are AND-combined with the OR of
> permissives. A common bug is adding a permissive "admin" policy that
> unintentionally widens a tenant policy. Test the combined predicate.

---

## 6. Purpose-based and privacy-aware access

The Hippocratic database (Agrawal, Kiernan, Srikant, Xu, VLDB 2002) derives
ten principles from the OECD guidelines: purpose specification, consent,
limited collection, limited use, limited disclosure, limited retention,
accuracy, safety, openness, compliance. Engine-visible pieces of its strawman
architecture: privacy-metadata store (purposes, recipients, retention per
attribute), attribute- and record-level access control keyed on *purpose*,
a query intrusion detector, an audit trail, a retention manager, and an
encryption layer.

Limiting disclosure (LeFevre et al., VLDB 2004): queries carry a purpose and
recipient; the rewriter replaces each protected cell with `NULL` (cell-level
granularity) or removes the row, according to per-row consent choices stored
in side tables — query modification with a per-cell `CASE WHEN consent ...`.
IBM's implementation over DB2 (Agrawal et al., ICDE 2005) shows the overhead is
dominated by the joins against choice tables.

Purpose-based access control (Byun & Li; Colombo & Ferrari, TKDE 2014):
purposes form a hierarchy (tree); an *intended purpose* (allowed/prohibited
sets) is attached to data and an *access purpose* to the request; access is
allowed if the access purpose is compliant (allowed and not prohibited,
respecting the hierarchy). Hard part: the engine cannot verify the claimed
access purpose; it is bound to roles or applications, and audited.

Engine checklist for purpose/consent enforcement:
- purpose is part of the session security context (and of the plan-cache key);
- rewriting is per-cell, so it must happen after view expansion and before
  aggregation pushdown;
- retention is enforced by a background deleter whose actions are themselves
  audited and which must also reach indexes, MVs, logs and backups (see the
  compliance reference for why "delete" is rarely complete).

---

## 7. Authorization-related failure modes (checklist)

| Bug class | Symptom | Detection |
|---|---|---|
| Missing mediation on a new path | COPY/bulk export, `TABLESAMPLE`, system function, or FDW reads rows without RLS | Enumerate all relation-open call sites; assert a security context is attached; fuzz with a low-privilege role |
| Leaky pushdown | UDF/operator evaluated before policy predicate leaks hidden values via error or side effect | Leak-test UDF that raises its argument; property test: any query under role R produces no side effects referencing rows invisible to R |
| Existence oracle | Different errors/timings for "no such object" vs "no permission"; unique-constraint violation reveals hidden key | Differential testing of error codes across privilege levels |
| Stale cache | Plan or role cache used after REVOKE | Revoke mid-session, re-execute prepared statement, expect failure |
| Definer-rights hijack | `SECURITY DEFINER` function resolves unqualified names via caller's path | Static check: definer functions must have fixed search path |
| Cascade surprise | REVOKE CASCADE drops views/constraints silently | RESTRICT default; report dependent objects |
| Grant-option cycle | A→B→A grant-option cycle keeps privilege alive after owner revokes | Reachability from owner, not "has any incoming edge" |
| Write-into-invisible | UPDATE moves a row out of the user's policy | WITH CHECK / block predicate tests |
| Statistics leak | `pg_stats`-like views, EXPLAIN estimates expose hidden values | Restrict stats by column privilege; test |

---

Sources: Access Control (p.9, including its recovered tail on administration
policies); Database Security (p.974); Discretionary Access
Control (p.1140); Role-Based Access Control (p.3252); Temporal Access Control
(p.3894); Privacy-Preserving DBMSs (p.2822); Secure Database Development
(p.3346) for query modification vs views; Secure Transaction Processing
(p.3358) for policy consistency in cloud transactions.
