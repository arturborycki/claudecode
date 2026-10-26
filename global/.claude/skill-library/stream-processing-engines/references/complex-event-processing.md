# Complex event processing, pattern detection, and publish/subscribe over streams

Read this when you are adding sequence/pattern queries (SEQ, Kleene closure,
negation, MATCH_RECOGNIZE) to a stream engine, choosing event selection and
consumption semantics, scaling to thousands of concurrent patterns, or
building content-based pub/sub matching and routing.

---

## 1. Vocabulary and the CEP/stream-DB split

- **Event**: a timestamped unit of information. Its payload is a relational
  tuple in Cayuga/SASE-style systems.
- **Event pattern**: a combination of events correlated in time (and by
  attribute predicates). A match is a **complex (composite, derived) event**,
  which may represent a **situation** (a case requiring action).
- **CEP** detects patterns, derives events and triggers reactions. EDBS
  (Etzion) sorts application segments by motivation: real-time enterprise
  (react inside running business processes), active diagnostics (root cause
  from symptoms), information dissemination (subscribe to patterns, not raw
  events), business activity monitoring (KPI violations), and prediction
  (mitigate forecast events). Prediction has two parts: a predictor that
  estimates how likely a future event is *and* what its attribute values will
  be, taking causal links between event types into account (independent
  causes compound differently from a shared root cause), and a decision
  component that weighs the cost of actions meant to change that likelihood.
  Predictors split into explicit models (stated relationships) and implicit,
  learned ones (EDBS "Event Prediction", adjacent to p.1373).

Two system lineages converged (EDBS "Event and Pattern Detection over Streams"):

| | Pub/sub | Stream DBs (Aurora, STREAM, TelegraphCQ) | CEP engines (SNOOP, ODE → Cayuga, SASE) |
|---|---|---|---|
| Query power | predicates on single events | SQL + windows + grouping | sequencing, iteration, negation over many events |
| Scale target | millions of subscriptions, high rate | rich queries; little work on many concurrent complex queries | thousands of concurrent patterns |
| Physical model | predicate indexes | operator trees | NFAs (automata) |

Integration challenge: a unified algebra at the logical level and one engine
at the physical level, combining operator trees and automata. Modern answers
put an NFA-based pattern operator inside a relational dataflow, as in
MATCH_RECOGNIZE.

Approaches to stream processing per EDBS "Stream Processing": custom code,
stream-oriented SQL, and rule engines (descendants of 1970s/80s production
systems, with strong pattern matching but needing windows and aggregation
bolted on). SQL wins when history must be combined with live data, since it
stays in one paradigm. Rule engines win on intricate patterns.

---

## 2. Formal shape of an event pattern

Etzion's definition, paraphrased: `EP = ⟨Context, InputEventTypes,
PatternType, Predicates, Policies, DerivedEvents⟩`.
- **Context**: the semantic dimensions that scope detection: temporal (a
  window or interval opened and closed by events), spatial, state-based
  (only while a condition holds), or segmentation by reference (e.g., per
  customer). Context-opening and closing events are implicit inputs.
- **Input event types**: the edges (streams) of the event processing network.
- **Pattern type**: a formula over event-type variables: event-oriented
  (`and(e1,e2)`, `seq`), set-oriented (`avg(temp) > 35` over the context),
  dimensional (temporal or spatial movement), context-termination (`absent(e1)`
  at context end), interval relations (overlap).
- **Predicates**: cross-event conditions, e.g., `e1.a > e2.b`.
- **Policies**: semantic fine-tuning. When three e1's precede five e2's, how
  many `and(e1,e2)` matches are there, and with which instances? (§4)
- **Derived events**: the output content, either a collection of participants
  or a computed event.

**Event lineage** (pedigree) records the processing-network path so you can
answer "what did event e cause?" and "what led to action a?". This is
provenance for event networks. Keep participant ids in derived events if you
need it.

---

## 3. Pattern languages and algebras

**Regular-expression analogy, with three extensions.** Matching a pattern over
an event stream is like matching a regex over characters, except (1) each
event has many attributes with infinite domains, not one symbol from a finite
alphabet, (2) patterns apply relational operations (filter, project, rename)
and compare attributes *across* events (parameterized predicates), and (3)
events carry timestamps and patterns reason about real time (durations,
WITHIN), not just order.

| Language | Core operators | Notes |
|---|---|---|
| SNOOP (Chakravarthy et al., VLDB 1994) | sequence, conjunction, disjunction, aperiodic/periodic, NOT | active-DB composite events; defines parameter *contexts* (§4) |
| ODE (Gehani, Jagadish, Shmueli, VLDB 1992) | composite events as regular-expression-like specs | compiled to automata |
| Cayuga algebra / CEL (Demers et al., EDBT 2006, CIDR 2007) | selection, projection, aggregates + binary **NEXT** (sequence with a join predicate that includes time) and **FOLD** (iterated NEXT with a stop condition) | designed for many concurrent patterns |
| SASE (Wu, Diao, Rizvi, SIGMOD 2006) | `EVENT SEQ(A a, B b, !(C c), D d) WHERE … WITHIN w` with sequence, negation, windowing | NFA plus relational post-processing |
| SEQ (Seshadri, Livny, Ramakrishnan, ICDE 1995), SQL-TS (Sadri et al., PODS 2001), SRQL | sequence queries over stored ordered data | offline; SQL-TS optimizes by exploiting dependencies between pattern elements (KMP-like skipping) |
| Commercial (StreamSQL MATCH/PATTERN, CCL MATCHING, Esper PATTERN, StreaQuel EVENT) | multi-stream presence/absence within time bounds; some single-stream regex | EDBS notes the academic CQL/SQuAl/ESL lacked pattern matching |

Example of the Cayuga style (paraphrasing EDBS's stock example): start on a
large trade, FOLD over subsequent events of the *same company* while the price
strictly decreases, require the FOLD to last more than 10 minutes, then NEXT
a same-company event with a price ≥ 5% above the last one.

> **Beyond EDBS:** The row-pattern proposal EDBS cites (StreamBase/Oracle/IBM,
> 2007) became **SQL:2016 row pattern recognition**, `MATCH_RECOGNIZE`:
> `PARTITION BY`, `ORDER BY`, `MEASURES`, `ONE ROW | ALL ROWS PER MATCH`,
> `AFTER MATCH SKIP {PAST LAST ROW | TO NEXT ROW | TO FIRST v | TO LAST v}`,
> `PATTERN (regex over row variables, with quantifiers *, +, ?, {n,m}, and
> reluctant forms)`, `DEFINE v AS <predicate, may reference prior rows via
> PREV/FIRST/LAST and aggregates over matched rows>`. Implemented in Oracle,
> Flink SQL (over event time, with the watermark closing matches), Trino and
> Snowflake. The AFTER MATCH SKIP clause *is* the consumption policy (§4).

> **Beyond EDBS:** SASE+ (Agrawal, Diao, Gyllstrom, Immerman, SIGMOD 2008) adds
> Kleene closure and makes **event selection strategies** explicit:
> *strict contiguity* (pattern events must be adjacent in the stream),
> *partition contiguity* (adjacent within a partition key), *skip-till-next-
> match* (irrelevant events skipped; each step takes the next matching event),
> and *skip-till-any-match* (any matching event, giving non-deterministic
> branching and potentially exponentially many matches with Kleene+). Its
> NFA^b model attaches a match buffer to the automaton.

---

## 4. Selection and consumption policies (the semantics bugs live here)

Given a pattern `SEQ(A, B)` and stream `a1 a2 b1 b2`, possible answers are
`{(a1,b1)}`, `{(a2,b1)}`, `{(a1,b1),(a2,b2)}`, or all four pairs. Engines must
pick explicitly:

| Policy dimension | Options | Classical names |
|---|---|---|
| Instance selection (which candidate initiator) | first, last (most recent), each | SNOOP contexts: *recent* (latest initiator), *chronicle* (oldest unconsumed, FIFO pairing), *continuous* (each initiator starts its own detection), *cumulative* (all initiators accumulated into one composite) |
| Consumption (can an event participate again?) | consume on match, reuse | SNOOP contexts imply consumption; MATCH_RECOGNIZE AFTER MATCH SKIP |
| Skipping (irrelevant events between pattern events) | strict, partition-contiguous, skip-till-next, skip-till-any | SASE+ strategies |
| Overlap of matches | allowed or not | MATCH_RECOGNIZE SKIP TO NEXT ROW vs PAST LAST ROW |

Engine rule: these are part of the query's **semantics**, not tuning. Expose
them in the language, give them a default, and test each combination against
a brute-force enumerator (§8).

**Time of composite events.** If a composite event is stamped with only its
detection (end) time, nested sequences can match wrongly. A composite B
detected after A may have *started* before A. Use **interval timestamps**
`[start, end]` for derived events, and define SEQ as `e1.end < e2.start`.

> **Beyond EDBS:** This anomaly of detection-time (point) semantics for
> composite events is a known result (Galton & Augusto 2002). Interval-based
> semantics fixes it and is what modern CEP algebras adopt.

---

## 5. Execution: automata

Pattern queries compile to (extensions of) NFAs. Cayuga's extensions:
1. **Edges carry predicates.** An edge fires only if the incoming event
   satisfies its predicate. Filter predicates sit on start edges.
   NEXT/FOLD join conditions sit on transition and self-loop edges.
2. **Instances carry bindings.** Each automaton *instance* stores the
   attributes of the events matched so far, to evaluate parameterized
   predicates and to build the output witness. Schema-transforming functions
   on edges map event and instance schemas.
3. **Self-loops implement iteration (FOLD / Kleene+).** One loop predicate
   decides whether the event extends the current run (e.g., same company).
   Another decides whether the run continues (e.g., price still falling).

```
on event e:
   for each instance I in active set (index by partition key / predicate):
       for each out-edge (I.state → q, pred, f):
           if pred(e, I.bindings):
               I' = (q, f(I.bindings, e))          # may clone I (nondeterminism)
               if q is final and duration/WITHIN ok: emit witness(I')
               else add I' to next active set
       if I no longer viable (window expired, consumption policy): drop I
   for each start edge with pred(e): create new instance
```

**SASE plan structure.** A sequence-scan-and-construction NFA operator finds
candidate matches. Selection, window, negation and transformation operators
follow it relationally. Optimizations:
- push selections *into* the NFA (discard irrelevant events before they
  create instances);
- push the WITHIN window into the scan (prune instances whose first event is
  too old);
- partition instance stacks by the equivalence-test attribute (e.g., same
  symbol), so an event touches only its partition's instances;
- *active instance stacks*: each NFA state keeps a stack of events with
  pointers to the most recent predecessor-state event at insertion time.
  Matches are constructed by walking pointers backward only when the final
  state is reached. That is lazy construction, which avoids materializing
  partial matches.

**Negation.** `SEQ(A, !C, D)` holds if no C occurs between the matched A and
D. Trailing negation `SEQ(A, !C) WITHIN w` can only be confirmed when the
window closes, so it needs time progress (watermark/heartbeat) to emit. A
negation over a stream that never punctuates never fires.

**Complexity and state explosion.** With skip-till-any-match and Kleene+,
active instances can grow exponentially in window length. Mitigations:
mandatory WITHIN, partitioning, skip-till-next-match defaults, lazy
construction with shared buffers (SASE+), instance caps with load-shedding
hooks.

> **Beyond EDBS:** ZStream (Mei & Madden, SIGMOD 2009) evaluates sequence
> patterns with tree-based join plans over buffered events instead of an NFA.
> A cost-based optimizer picks the tree shape (e.g., evaluate the rarest event
> type first), which beats NFAs when event-type frequencies are skewed. Flink
> CEP is NFA-based with shared versioned buffers for partial matches.

---

## 6. Multi-query optimization for thousands of patterns

Evaluating one pattern is easy. Evaluating tens of thousands concurrently is
the systems problem. Cayuga's MQO:
1. **Prefix merging**: translate each query into automata and merge them into
   the global automaton. States with identical prefixes (same predicates, same
   input) are shared, which is common-subexpression elimination for automata.
   Instances in shared states serve all queries that pass through them.
2. **Predicate indexing on edges**: index start-edge filter predicates
   (equality → hash, ranges → interval structures) so an event finds the
   satisfied edges without testing all of them. This is the pub/sub matching
   problem (§7). Index instances by their binding values for parameterized
   predicates (e.g., hash instances by company so an event probes one bucket).

EDBS reports thousands of events/s for tens of thousands of active patterns
(2007 hardware). Treat the number as directional. Share-ability depends on
query similarity.

---

## 7. Publish/subscribe over streams

**Model.** Publishers emit messages without knowing receivers. Subscribers
register interests. A broker stores subscriptions as continuous queries,
matches every message against all of them, and delivers results. This
decouples communication (no point-to-point bindings) and, with
self-describing formats such as XML, content (no shared schema dependency).

Design space:
- **Data model / language**: subject-based (topic hierarchy plus header
  filters), complex-predicate-based (attribute–value pairs with and/or of
  comparisons, e.g., `Symbol='ABC' AND (Change>1 OR Volume>50000)`), or XML
  filtering and transformation (XPath/XQuery; see `beyond-relational-engines`).
- **Processing**: stateless (per message) vs stateful (windows, joins,
  sequences across messages).
- **Architecture**: centralized broker vs a broker network with routing.

Requirements beyond plain streaming: **scalability in the number of
queries** (hundreds to millions), **robustness to query churn** (subscriptions
added and removed constantly without disturbing matching), and
**distribution** (route each message only to brokers with interested
subscribers).

### 7.1 Centralized, stateless: predicate indexing

Le Subscribe (Fabret et al., SIGMOD 2001) and Xyleme index predicates and
cluster subscriptions:
- index the *predicates* (attribute op constant) so one message evaluates all
  predicates on an attribute in one probe: hash for `=`, sorted structures
  for `<`/`>`;
- cluster subscriptions by number of predicates and by a common conjunction of
  equality predicates (the access predicate), using multi-attribute hashing to
  test several equalities at once;
- cost-based choice of clustering, adjusted dynamically.

Matching algorithm sketch (counting variant, a common baseline):
```
on message m:
    satisfied = ∪ over attributes a of m: predicate_index[a].probe(m.a)
    for each predicate p in satisfied: for each subscription s containing p: hits[s]++
    match = { s : hits[s] == |s.predicates| }        # conjunctive subscriptions
```
Clustering on an access predicate prunes the subscriptions examined to those
whose access predicate is satisfied.

### 7.2 Centralized, stateful

**NiagaraCQ** (Chen, DeWitt, Tian, Wang, SIGMOD 2000) groups query plans by
*expression signature*: same structure, different constants. Store the
constants of all queries in a **constant table**. Extract the attribute from
each message once and **equi-join** it with the constant table to find every
matching query. That replaces N predicate evaluations with one join (an index
probe). New queries merge incrementally, bottom-up, into an existing group
plan without disturbing other queries. This is robust to churn. NiagaraCQ also
showed that pulling selections above shared joins preserves sharing
(`windows-and-punctuations.md` §3.1).

General stream engines contribute shared window-query processing. SASE and
Cayuga (§3, §5) serve as expressive pub/sub over event sequences.

### 7.3 Distributed, stateless: content-based routing

- **ONYX** (Diao, Rizvi, Franklin, VLDB 2004): brokers form an overlay. Each
  broker has a broadcast tree reaching all others. On top, each broker routes
  a message to neighbours only if subscriptions reachable through them could
  match it. Effectiveness depends on (1) partitioning subscriptions across
  host brokers so their interests are mutually exclusive, and (2) aggregating
  (generalizing) downstream subscriptions into compact routing specs at
  intermediate brokers. Coarser generalization means less routing state and
  more false-positive forwarding.
- **Gryphon** (Aguilera et al., PODC 1999) and **Siena** (Carzaniga & Wolf,
  SIGCOMM 2003): compact in-network subscription structures with fast search
  (parallel search trees / forwarding tables using covering relations).
- **XPORT** (Papaemmanouil et al., SIGMOD 2006): cost-based construction and
  maintenance of the dissemination tree itself, using generic aggregation of
  local metrics and distributed iterative optimization.

### 7.4 Distributed, stateful

Chandramouli, Xie, Yang (SIGMOD 2006): subscriptions are SQL views over a
(possibly distributed) database and messages are updates. The work is split at
the database/network interface. The database side turns each update into
messages describing affected results (e.g., ΔR ⋈ S rows), which needs state.
The stateless pub/sub network then routes using a rewritten simple predicate
(the conjunction of the view's selection predicates evaluated on the
reformulated message). This reuses a stateless content-based network for
stateful subscriptions.

---

## 8. Implementation checklist and tests

Implementation:
- Instance store: per-state vectors of instances, partitioned by key, each
  instance a small struct with bindings in a fixed-layout arena. Bulk-free on
  window expiry (expiry-ordered ring per partition).
- Shared match buffers: store each event once with predecessor pointers
  (version vectors per run). Do not copy event payloads into every partial
  match.
- Predicate index per attribute: hash for equality, interval tree or sorted
  array with binary search for ranges. Rebuild incrementally on subscription
  churn (or buffer additions in a delta index merged periodically).
- Time: patterns need event time, a watermark to close WITHIN windows and
  confirm negation, and a late-event policy.
- Output: interval timestamps on derived events, plus participant ids for
  lineage.

Tests:
- **Brute-force oracle**: for small streams (≤ 12 events), enumerate all
  subsequences, filter by pattern, predicates, window and the declared
  selection/consumption policy. Compare match sets exactly, per policy.
- **Policy matrix**: run each of recent/chronicle/continuous/cumulative (or
  the SKIP variants) on adversarial streams (repeated initiators, interleaved
  keys).
- **Negation timing**: trailing negation must emit exactly when the watermark
  passes the window end, never earlier.
- **Explosion guard**: skip-till-any-match with Kleene+ over a long window.
  Assert the instance cap and the shedding behaviour engage.
- **Pub/sub churn**: add and remove subscriptions while streaming at full rate.
  Match results must equal those of a freshly built index at every point.
- **Routing completeness**: in a broker network, every subscriber receives
  every matching message (no false negatives under generalization). Measure
  false-positive forwarding.

Sources: EDBS "Complex Event Processing" (p.530), "Event and Pattern Detection
over Streams" (p.1354), "Event Pattern Detection" (p.1373), "Publish/Subscribe
Over Streams" (p.2937), "Stream-Oriented Query Languages and Operators"
(p.3802), "Stream Processing" (p.3771), "Stream Processing on Modern Hardware"
(p.3772, for CEP on GPUs/FPGAs).
