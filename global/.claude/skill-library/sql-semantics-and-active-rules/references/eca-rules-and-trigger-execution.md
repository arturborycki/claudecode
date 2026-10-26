# Active databases: ECA rules, composite events, coupling modes, and SQL trigger execution

An active DBMS reacts on its own to events — data changes, transaction
boundaries, clock ticks, external signals — through **event–condition–action
(ECA) rules**: when the event is detected, evaluate the condition, and if it
holds, run the action. The research systems of 1988–1997 (HiPAC, Starburst,
POSTGRES, Ariel, ODE, SAMOS, Sentinel/Snoop, REACH, DeeDS, Chimera) worked out the
semantics; SQL:1999 triggers standardised a narrow, immediate-coupled subset;
the rest reappears today as constraint triggers, notification queues, outbox/CDC
pipelines and complex event processing. This file gives the full model and then
the exact SQL trigger execution semantics an engine must implement.

---

## 1. Why put reactive behaviour in the DBMS

The alternatives are both broken:
- **Polling**: query periodically. Too frequent overloads the server; too
  infrequent misses or delays the event; neither sees transient states.
- **Embedding checks in every application**: every writer must carry the
  check; changing the rule means changing and redeploying all writers; a forgotten
  writer silently violates it.

Moving the rule into the schema centralises it, guarantees it sees every
change, and lets the DBMS optimise condition evaluation. The separation into
three parts is deliberate: the **event** says *when* to look (so conditions are
not evaluated continuously), the **condition** says *what* to check (a pure
query the optimizer can handle), the **action** says *what to do*; and only with
the parts separated can each have its own coupling mode. A fourth reason
(Dayal's 1995 retrospective "Ten years of activity in active database
systems"): a matching notion of events in the application domain and in the
DBMS makes reactive applications easier to model.

An active database is described by its **knowledge model** (static: what rules
can say) and its **execution model** (dynamic: how rules behave at run time).

## 2. Knowledge model

| Rule part | Dimensions |
|---|---|
| Event | type (primitive / composite); source (DML on a table or class, method invocation, transaction begin/commit/abort, clock — absolute, relative, periodic — external/user-defined signal); granularity (every instance of a set, a subset, the whole set); composite operators and consumption context; parameters carried |
| Condition | form: a query (non-empty result = true, empty = false), a boolean expression, or a call returning a boolean; database state it is evaluated against: (i) start of transaction, (ii) when the event occurred, (iii) when the condition is evaluated |
| Action | DB updates, rule-base changes, abort/rollback, notification, external program (irreversible: e-mail, actuator), "instead" (replace the triggering operation); state it sees: (i)–(iii) as above or (iv) just before the action runs |
| Parameters | event → condition → action bindings: system-level (txn id, user, timestamps) and application-level (affected rows/objects, method arguments); condition results should flow to the action so it need not recompute |
| Representation | rules as first-class catalog objects that can be created, dropped, altered, enabled and disabled independently of the objects they watch |

The **rulebase** evolves: every add/drop/enable/disable can change
termination and confluence (§7) — re-run static analysis on rulebase DDL, not
only at design time.

## 3. Events

Events are classically **atomic and instantaneous** — they happen at a time
point or not at all. Primitive events are categorised by source: transactional
(begin/commit/abort), temporal (absolute, relative to another event, periodic),
data-manipulation (insert/update/delete of tuples in a relational system; method
calls in an OO one; both in object-relational), and user-defined/abstract
signals. An event is **explicit** if the rule names it, **implicit** if the
system derives it from the rule (e.g., "whenever the condition's tables
change").

### 3.1 Composite events and event algebras

A composite event is a set of constituent events matching an event
expression. Operators shared by essentially all languages:

| Operator | Snoop-style | Occurs when |
|---|---|---|
| disjunction | `E1 ∨ E2` | either occurs |
| conjunction | `E1 ∧ E2` | both have occurred, any order |
| sequence | `E1 ; E2` | E2 occurs after E1 |
| negation / non-occurrence | `¬E2 [E1, E3]` | E3 occurs after E1 with no E2 in between (always bounded by an interval) |
| aperiodic | `A(E1, E2, E3)` | each E2 inside the interval opened by E1 and closed by E3 |
| periodic | `P(E1, [t], E3)` | every t time units between E1 and E3 |
| cumulative variants | `A*`, `P*` | one occurrence at E3 accumulating all inner occurrences |

The **initiator** starts a partial match, the **terminator** completes it.
Non-occurrence intervals are delimited by arbitrary events in Snoop, REACH and
SAMOS; by transaction begin and commit in ODE.

**Operator vs functional grammars.** Infix (`E1;E2;E3`) has associativity and
precedence ambiguity (`(E1;E2);E3` vs `E1;(E2;E3)`; how does `;` bind relative
to `∧`, `∨`?). Functional forms `SEQ(E1,E2,E3)` (Motakis & Zaniolo's EPL,
XChangeEQ) avoid both and generalise to n-ary operators. A parser for an event
language should use the functional form internally.

### 3.2 Consumption contexts (which constituents pair up)

History: `e1a e1b e2a e2b` (E1 initiators, E2 terminators) for `E1 ; E2`:

| Context | Rule | Detected occurrences |
|---|---|---|
| unrestricted | every combination | (e1a,e2a) (e1b,e2a) (e1a,e2b) (e1b,e2b) |
| recent | only the most recent initiator is kept; it is reused until replaced | (e1b,e2a) (e1b,e2b) |
| chronicle | oldest unused initiator pairs with the terminator; both consumed | (e1a,e2a) (e1b,e2b) |
| continuous | each initiator opens a match; one terminator closes all open matches | (e1a,e2a) (e1b,e2a) |
| cumulative | all initiators accumulate into one occurrence at the terminator; all consumed | ({e1a,e1b}, e2a) |

Use cases: recent for "latest temperature and pressure"; chronicle for
"sensor 1 then sensor 2 for the same item on a conveyor" (FIFO pairing).
Unrestricted is exponential in history length and needs a window; the
algorithmic cost of detection is driven by the **context**, not the operators.

### 3.3 Detection
Mechanisms: event graphs with per-node buffers (Snoop/Sentinel), coloured Petri
nets (SAMOS), finite automata (ODE/COMPOSE). The BEAST benchmark found the
mechanism matters less than bookkeeping — indexing event types so an incoming
event reaches only interested detector nodes, and pruning partial matches.
Engine rules:
- Every partial-match buffer needs a **garbage-collection bound** (time window,
  transaction scope, or context consumption); otherwise memory grows without
  limit.
- Abort handling: constituent events from an aborted transaction must be
  pruned unless the design explicitly allows inter-transaction events — and
  then rules have read dirty data.
- Parameterised detection (`E1;E2 where E1.p = E2.p`) is a join over event
  streams; implement with hash-indexed buffers per parameter value.

### 3.4 Pitfalls in event semantics
- **Disjunction** in many languages is neither inclusive nor exclusive: two
  simultaneous constituents yield *two* occurrences with the same end time.
  Explicit (batched) invocation of the detector — evaluate after all
  simultaneous events are delivered — fixes it.
- **Instantaneous composite events** lose information: with only end
  timestamps, `E1;(E2;E3)` and `E2;(E1;E3)` can be indistinguishable (Galton &
  Augusto 2002). Give composite occurrences an **interval** [start, end] and
  define sequence on intervals (interval-based Snoop).
- Distributed detection: local clocks are finer than global; detect locally,
  compose globally on a coarser granularity, in a moving time window.

> Boundary: continuous-query/CEP engines (windows, punctuation, MATCH_RECOGNIZE)
> are `stream-processing-engines`; this file covers events *inside* a
> transactional DBMS.

## 4. Coupling modes

Coupling specifies where, relative to the triggering event and transaction,
the condition is evaluated (E–C coupling) and the action executed (C–A
coupling). HiPAC's matrix — seven valid combinations:

| E–C \ C–A | immediate | deferred | decoupled (detached) |
|---|---|---|---|
| **immediate** | C and A right after the event | C now, A at end of txn (before commit) | C now, A in a separate txn |
| **deferred** | **invalid** — A cannot precede its C | C and A at end of txn | C at end of txn, A in a separate txn |
| **decoupled** | C then A immediately, both in one separate txn | **invalid** — the separate txn's timing is unknown, A could be due before C has run | C in one separate txn, A in another |

Detached execution is **independent** or **causally dependent** on the
triggering transaction. REACH added two dependent variants for actions with
irreversible side effects:
- **sequential causally dependent**: the rule transaction may start only
  after the triggering transaction commits;
- **exclusive causally dependent**: the rule transaction runs in parallel but
  may commit only if the triggering transaction aborts (contingency/compensation).

What each mode demands from the engine:

| Mode | Engine hook |
|---|---|
| immediate | call-out from the DML executor (per row or end of statement); no queue needed |
| deferred | a per-transaction queue drained in a **pre-commit phase**; rules may queue more work; commit fails (and rolls back) if a deferred rule raises |
| detached independent | an asynchronous queue + a new transaction; survives triggering rollback |
| detached sequential dependent | enqueue in the triggering txn, deliver **after its commit** (transactional outbox) |
| detached exclusive dependent | run speculatively, gate commit on the triggering txn's outcome — needs inter-transaction commit dependencies |

Nested transactions are the natural substrate: deferred or immediate actions
run as subtransactions that can abort without killing the parent.

> **Beyond EDBS — where the modes live in today's engines:**
> | Mode | Production mechanism |
> |---|---|
> | immediate, immediate | SQL BEFORE/AFTER triggers (row and statement) |
> | deferred, deferred | PostgreSQL `CREATE CONSTRAINT TRIGGER … DEFERRABLE INITIALLY DEFERRED`; deferred FK/UNIQUE checks |
> | detached sequential dependent | PostgreSQL `NOTIFY` (delivered only on commit); transactional outbox table + CDC (logical decoding, Debezium) |
> | detached independent | Oracle autonomous transactions (`PRAGMA AUTONOMOUS_TRANSACTION`) for audit logging that survives rollback; job queues (`DBMS_SCHEDULER`, `pg_cron`) |
> | exclusive dependent | rarely native; built as saga compensation outside the DBMS |

## 5. Execution model

Any ECA engine must answer, explicitly:
1. When are C and A run relative to the event and the transaction? (coupling)
2. If an event triggers several rules: are all, some, or one considered?
3. Are triggered rules run sequentially (in what order) or concurrently?
4. When a rule's action triggers further rules: depth-first (recursive,
   immediately) or breadth-first (iterative, after the current rule set)?
5. If one rule's action falsifies the condition of an already-triggered rule,
   is the condition re-evaluated before that rule's action runs?
6. May rules trigger themselves or form cycles; what bounds them?
7. Tuple-level or set-oriented: does a rule fire per affected row or once per
   statement/transition with the set of changes?

Leaving any of these implicit makes rule behaviour unpredictable.

### 5.1 Set-oriented rules and net effects (Starburst)
Widom & Finkelstein's set-oriented production rules (SIGMOD 1990) fire on the
**net effect** of a transition since the rule was last considered:

| Sequence on one row within the transition | Net effect |
|---|---|
| insert, then update(s) | insert of the final value |
| insert, then delete | nothing |
| update(s), then delete | delete of the original value |
| update, update | one update, original → final |

Rules see transition tables (inserted, deleted, old-updated, new-updated);
priorities form a partial order declared with `PRECEDES/FOLLOWS`; rules are
considered at rule assertion points (end of transaction by default, or
user-requested).

### 5.2 Rule processing loop (generic, set-oriented, deferred point)

```
process_rules(txn):
  loop:
    T := { r ∈ enabled_rules : net_delta(r.since) intersects r.events }
    if T = ∅: return
    r := choose(T)                    // priority order; ties by creation order
    Δ := net_delta(r.since); r.since := now()
    if eval(r.condition, Δ, db):      // condition binding: state at evaluation
      exec(r.action, Δ)               // may change db → new deltas
    if ++steps > MAX_STEPS: raise "rule processing did not terminate"
```

Cost: each iteration recomputes net deltas per rule; keep a per-rule cursor
into a shared change log rather than per-rule copies.

### 5.3 Conflict resolution
Choices for picking among simultaneously triggered rules: explicit priorities
(total numeric, or partial PRECEDES/FOLLOWS), creation order, name order,
recency of triggering data, specificity (OPS5-style), or non-deterministic.
Non-deterministic choice is only acceptable for a **confluent** rule set.

## 6. SQL triggers — the standard's model and what engines actually do

### 6.1 Definition elements
- Event: `INSERT`, `DELETE`, `UPDATE [OF column-list]` on one table (TRUNCATE
  and DDL "event triggers" are vendor extensions).
- Timing: `BEFORE`, `AFTER`, `INSTEAD OF` (views; SQL:2008).
- Granularity: `FOR EACH ROW` or `FOR EACH STATEMENT` (statement triggers fire
  once even when zero rows are affected — vector I1).
- `REFERENCING OLD ROW AS o NEW ROW AS n OLD TABLE AS ot NEW TABLE AS nt`:
  transition variables (row triggers) and transition tables (AFTER triggers),
  giving the trigger the before/after images of the change.
- Optional `WHEN (condition)` evaluated at the triggering event; only TRUE fires.
- Body: one or more SQL statements (or a PSM block / routine call).

Constraints versus triggers: express a rule as a constraint when possible —
constraints apply to every kind of change and are optimisable; triggers are
needed for **transition constraints** ("salaries never decrease") and for
derived side effects.

### 6.2 Execution order for one triggering statement (SQL:1999 / Cochrane–Pirahesh–Mattos model)

```
execute_dml(stmt):
  fire BEFORE STATEMENT triggers
  for each target row (from the pre-statement snapshot):
     fire BEFORE ROW triggers (may rewrite NEW, or skip the row — I3, I4)
     apply the change to the table (and indexes), capture transition rows
  apply referential actions (CASCADE/SET NULL/SET DEFAULT) — each is itself a
     data change on the child table and runs this same procedure recursively
  check immediate constraints (end-of-statement semantics; deferred ones queued)
  fire AFTER triggers (row triggers once per transition row, statement triggers
     once), seeing the complete post-statement state and transition tables
  any statement inside a trigger body starts a nested execution context
```

Rules that follow:
- BEFORE triggers are for validating/deriving the new row; the standard bars
  them from changing the database (vendors relax this). The standard model
  computes the whole transition before applying it; engines that interleave
  "BEFORE ROW, apply row" (PostgreSQL) can let a BEFORE trigger's queries observe
  earlier rows of the same statement — do not let tests depend on it. They run *before*
  constraint checks, so they can fix values that would otherwise violate a CHECK
  (I3).
- AFTER triggers observe a state in which the triggering statement and its
  cascades are complete and immediate constraints hold.
- Transition tables are set-oriented and the efficient way to write
  maintenance logic (one join over `nt` instead of n row firings; I2 shows one
  statement firing seeing all 3 rows).
- All trigger effects belong to the triggering statement's atomic unit:
  an exception anywhere undoes the statement, triggers and cascades together.

### 6.3 Ordering, mutation and recursion across engines

| Concern | Standard | PostgreSQL | Oracle | SQL Server | MySQL |
|---|---|---|---|---|---|
| order of triggers on the same event/timing | creation order | alphabetical by name | unspecified; `FOLLOWS` (11g+) | `sp_settriggerorder` first/last only | creation order; `FOLLOWS/PRECEDES` (5.7+) |
| AFTER ROW firing time | after the statement | queued to end of statement | after each row | (no row triggers; statement triggers with `inserted`/`deleted` tables) | after each row |
| reading the mutating table from a row trigger | consistent post-statement state | allowed | `ORA-04091` mutating table | n/a | allowed to read |
| modifying the triggering table in its trigger | allowed (may recurse) | allowed | restricted | allowed; direct recursion off unless `RECURSIVE_TRIGGERS` | forbidden (error 1442) |
| recursion limit | none specified | stack depth (`max_stack_depth`); `pg_trigger_depth()` for guards | implementation limit | 32 nesting levels | n/a |

Engine requirements that fall out:
1. A per-statement **after-trigger event queue** (stack of queues for nested
   statements), plus a per-transaction **deferred queue** drained at commit or by
   `SET CONSTRAINTS … IMMEDIATE`.
2. **Transition capture** that records final images once per row per statement
   even when cascades touch a row more than once — or raise triggered data
   change violation (27000) if the standard's conflict rule applies.
3. A **nesting depth counter** with a configurable cap and a clear error; expose
   the depth to trigger bodies so users can write guards.
4. Deterministic, documented ordering; never order by OID/hash.
5. Row triggers defeat vectorised/bulk DML; the executor must switch to
   row-at-a-time only on tables with row triggers and must still honour
   statement-snapshot reads inside trigger bodies.
6. Replication apply and bulk load paths need an explicit policy (fire or not:
   PostgreSQL `session_replication_role`, `ENABLE REPLICA/ALWAYS TRIGGER`).

> **Beyond EDBS:** the POSTGRES rules system (Stonebraker et al.) took the other
> path — rules as **query rewrites** applied before planning (`CREATE RULE … DO
> INSTEAD`), which is how PostgreSQL still implements views. Rewrite rules are
> set-oriented by construction but interact badly with volatile functions and
> multiple evaluation; modern guidance is to prefer triggers.

## 7. Termination and confluence analysis

- **Termination**: rule processing ends for every initial transition.
  Non-termination arises from cycles (R1's action triggers R2, R2's triggers R1).
- **Confluence**: the final database state does not depend on the order in
  which simultaneously triggered, unordered rules are chosen.
- **Observable determinism**: additionally, the sequence of externally visible
  actions (notifications, rollbacks) is order-independent.

### 7.1 Triggering graph (Aiken, Widom & Hellerstein, SIGMOD 1992)

```
nodes: rules
edge ri → rj  iff  some operation in ri's action can produce an event in rj's event set
               (e.g. ri updates T.c and rj is ON UPDATE OF c ON T)
Theorem: acyclic triggering graph ⇒ rule processing terminates.
```
Build it at rulebase DDL time from the action's write set (table, columns, op
type) and each rule's event set; report cycles to the user. Cycles are not
proof of non-termination — the analysis is conservative.

Refinements that remove false cycles:
- **Activation (condition) analysis** (Baralis, Ceri & Paraboschi, mid-1990s):
  an edge matters only if ri's action can make rj's condition *true*; e.g. a
  rule whose action sets `status='done'` cannot re-activate a rule conditioned on
  `status='new'`.
- **Monotone progress arguments**: a cycle in which some rule only deletes,
  or only moves a bounded value monotonically, terminates on finite data.
- Static termination is undecidable for general (Turing-complete) actions, so
  production engines pair conservative static checks with a **runtime cascade
  limit**.

### 7.2 Confluence
Sufficient condition (Aiken et al.): for every pair of rules ri, rj not ordered
by priority, they **commute** — neither can trigger or untrigger the other,
neither's action can change the other's condition result, and their actions
commute on the database (disjoint write sets, or both pure inserts into a bag,
etc.). Non-commuting unordered pairs are reported; the user adds a priority.
Priorities must form a partial order over every non-commuting pair for the
guarantee to hold.

## 8. Active DBMS architecture

Services (Paton & Diaz's reference view):

| Service | Responsibility |
|---|---|
| event monitoring | collect primitive events, detect composite ones, deliver to subscribed rules; maintain a **filtered event log** (keeps detected composites for reuse, prunes stale and aborted-transaction events) |
| rule evaluation | find triggered rules, evaluate conditions (queries, expressions or code), submit actions |
| scheduling | order *all* schedulable work — user transactions and rule actions together, since they compete for the same resources |
| monitored transaction processing | the passive DBMS (TM, lock, log, query engine) instrumented to signal events |

Flow: transactions → scheduler/dispatch table → monitored TP → events →
event monitor → triggered rules → rule evaluation → actions → scheduler (in the
transaction dictated by coupling). With only immediate coupling the queues
collapse into direct calls — cheaper, much less expressive.

Design issues:
1. **Layered vs integrated.** Building on top of an unmodified DBMS fails for
   deferred coupling (needs a pre-commit hook in the TM) and detached dependent
   coupling (needs commit-dependency tracking).
2. **Implicit events need schema-compiler instrumentation**; wrapping objects in
   instrumented subclasses cannot force every writer to use them.
3. **Implicit vs explicit invocation** of the event monitor: implicit (on every
   event) is the research norm but makes results timing-dependent; explicit
   (after a batch of events is delivered) gives determinism and fixes
   disjunction semantics — preferred in real-time and distributed settings.
4. **Real-time trade-offs**: REACH bans composite detection in real-time
   transactions because constituent events are locked; DeeDS composes from an
   unlocked event log, gaining timeliness and paying with isolation.
5. **Distributed**: event detection in a moving time window; local vs global
   detectors at different time granularities; heterogeneous event formats.
6. Open problems the entries flag: optimising arbitrary-query conditions together
   with the triggering statement, grouping actions, and **recovery** of
   detached-but-dependent work after a crash (solve it with a durable, logged
   queue — the outbox pattern).

Concrete component list for a modern engine adding active features:
- trigger/rule catalog + per-table descriptor cache (invalidated by DDL);
- DML executor hooks: before-row, after-row capture, statement begin/end;
- transition-table store per (statement, trigger set), spillable;
- after-trigger queue stack, deferred queue, pre-commit drain;
- post-commit durable notification/outbox queue;
- cascade/nesting counter; triggering-graph analyzer run on rule DDL.

## 9. Failure modes and tests

| Failure | Test |
|---|---|
| statement trigger skipped when 0 rows affected | I1 |
| AFTER ROW trigger sees partial statement state | AFTER ROW trigger that counts rows of its own table during a multi-row UPDATE; must see the final count |
| BEFORE ROW return-NULL not honoured / constraint checked before BEFORE trigger | I3, I4 |
| trigger effects survive a failing statement | trigger inserts into a log; statement then violates a constraint; log must be empty |
| deferred rule failing at commit leaves partial commit | constraint trigger raising at COMMIT; verify full rollback (H9 pattern) |
| infinite recursion crashes the server | self-updating trigger without guard must raise a clean depth error |
| nondeterministic firing order | two triggers on one event appending to a log; order must equal the documented rule across restarts |
| composite event buffers grow without bound | soak test with initiators that never terminate; memory must plateau |
| NOTIFY/outbox delivered for an aborted transaction | abort after enqueue; consumer must receive nothing |

---

Sources: Active Database Coupling Modes (p.25); Active Database Execution Model
(p.27); Active Database Knowledge Model (p.28); Active Database Management
System Architecture (p.29); Active Database Rulebase (p.35); Active Database,
Active Database (Management) System (p.35); ECA Rules (p.1263); ECA Rule
Condition (p.1263); ECA Rule Action (p.1262); Event in Active Databases
(p.1371); Event Specification (p.1389); Composite Event (p.531); Database
Trigger (p.985); SQL (p.3666) — constraints and triggers.
