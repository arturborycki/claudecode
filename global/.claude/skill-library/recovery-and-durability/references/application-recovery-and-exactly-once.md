# Application recovery and exactly-once semantics

Database atomicity guarantees all-or-nothing for state *inside* the DBMS.
It does not mask failures from the application: a client whose connection
drops after sending COMMIT does not know whether the transaction committed,
and effects outside the database (a message sent, a ticket printed) are not
covered. Application recovery strengthens all-or-nothing into **exactly-once
execution**: the observable result equals one failure-free execution
(Lomet, Application Recovery; Weikum, Atomicity). This file covers the
classic and implicit approaches, the contracts between components, the
x-ability correctness criterion for replicated services, and engine-level
recipes.

## 1. The ambiguity every client faces

Outcomes the client can observe for a transaction it submitted:

| Observation | Committed? | Safe action |
|---|---|---|
| Error before COMMIT sent | no | retry whole txn |
| COMMIT acknowledged | yes | none |
| Connection lost / timeout after COMMIT sent | unknown | **inquire outcome**; blind retry may duplicate |
| Abort/serialization error on COMMIT | no | retry |

Blind retry is correct only for idempotent work. Everything else needs
either an outcome inquiry or a server-side duplicate check keyed by a
client-chosen request id.

## 2. Failure classes for applications

- **Hard failures (Bohrbugs)**: deterministic; every re-execution fails the
  same way. Recovery cannot help; detect repeated failure on the same input
  and divert it (dead-letter queue) instead of looping.
- **Soft failures (Heisenbugs)**: non-deterministic software paths (timing,
  event order), transient hardware faults (bit flips), operator errors.
  Re-execution usually avoids them; this is why replay-based recovery works.

## 3. Explicit state management: TP monitors and queued transactions

IBM CICS and TP monitors (now application servers) decompose an application
into **steps, each a transaction**: read input state from the DB or a
transactional queue, run business logic, write output and the next step's
input state to the DB or queue, commit. A failed step aborts and is re-run
from the stably stored output of the previous step (Bernstein, Hsu & Mann,
SIGMOD 1990; Bernstein & Newcomer 1997; Gray & Reuter 1993).

Recoverable request/reply pattern:

```
client: rid = new_request_id(); enqueue(requestQ, {rid, payload}) durable
server txn: dequeue(requestQ) → process → enqueue(replyQ, {rid, result}) → commit
client: on restart, look up replyQ by rid before resubmitting
```

The dequeue, the work, and the reply enqueue are one transaction, so a crash
leaves either the request still queued or the reply present. Cost: the
programmer must structure state explicitly as queue elements/rows.

## 4. Implicit state management: persistent applications

The infrastructure captures application state "under the covers", letting
programs be written naturally. Requirement: the application is
**piecewise deterministic** — execution between explicitly identified
non-deterministic events (message receipt, user input, reading the clock,
thread scheduling choices) is deterministic, so replaying the same events
regenerates the same state.

Two families, closer than they look:

| | Recovery-based | Replication-based |
|---|---|---|
| Mechanism | periodic checkpoint of state + stable log of non-deterministic events in arrival order; recover by reinstalling the checkpoint and feeding the log | keep a replica in sync by delivering the same events in the same order: primary relays to secondaries, or atomic broadcast to all |
| Downtime | restart + replay | short (failover) |
| Normal cost | log forces | replica execution + messaging |
| Example | Phoenix/App (Barga, Chen & Lomet, ICDE 2004) | fault-tolerant CORBA |

Logging discipline (Elnozahy, Alvisi, Wang & Johnson, ACM CSUR 2002):
- **Pessimistic**: make each event stable before it can affect anything
  visible; guarantees exactly-once; costs a force per interaction unless
  optimised.
- **Optimistic**: defer stability; cheaper but can lose events and orphan
  dependent state unless constrained.
Intermediate setups blur the line: a recovery system can ship its log to a
second node (using it as stable storage, later the failover target); a
replica can merely log events and only execute them on failover (cold), lag
lazily (warm), or execute immediately (hot).

**Checkpoint at quiescent points**: component state = variables + execution
stack. Checkpoint when no call is executing inside the component (e.g., on
return from a call), so only variable values need capturing. Frequency
trades runtime cost against replay time.

## 5. Distributed persistent components and interaction contracts

Multi-tier applications (client, middle tier, back-end DB) add three needs:
the combined state must be **causal** (no component reflects receipt of a
message whose sender's state does not reflect sending it), every message
must be processed **exactly once**, and components must interoperate with
external parties (users) and transactional resources (databases) that do
not follow the same protocol (Barga, Lomet, Shegalov & Weikum, ACM TOIT 2004).

**Committed interaction contract (CIC)** between two persistent components:
- Sender obligations: (1) its state as of the send, and the message, become
  persistent no later than the receiver's state that depends on the message;
  (2) resend until the receiver acknowledges (unreliable network, crashed
  receiver). Usual implementation: force the sender's log of non-deterministic
  events at send time if it holds unforced received messages.
- Receiver obligations: (1) detect duplicates (table of received message ids,
  or a per-sender high-water mark); (2) for a duplicate, do not re-execute,
  return the original reply; (3) make the post-receipt state stable at an
  appropriate time.

Why not just "reliable messaging"? Delivery alone says nothing about what
happens to state after delivery; specifying state stability makes the
end-to-end guarantee explicit and avoids redundant log forces that
persistent message queues would add.

External and transactional parties:
- **External** (users, legacy services) cannot dedupe or replay. Some
  duplicate input or output is unavoidable if a crash hits between an event and
  its stable logging; minimise the window by logging and forcing immediately
  on each external interaction.
- **Transactional** components (a DBMS) sit at the edge and may abort at any
  time; the persistent component must tolerate that. Within a transaction it
  need not stabilise state per interaction (a crash aborts the transaction
  anyway), but the commit request is a send under CIC sender rules.

Optimisations exploiting programmer knowledge:
- **Read-only** callee: no logging; caller logs lazily because the read can
  be repeated.
- **Functional** callee (result depends only on arguments): no logging;
  calls replay idempotently.
- Callees that **remember prior calls and results** long enough: the caller
  need not force before each call; it relies on callees to return remembered
  results during its deterministic replay.
- **Single-client server**: the client captures the server's
  non-deterministic inputs (its calls and their order), so the server need
  not log; combined with the previous item this gives **logless** components
  that are rebuilt by client replay, can run anywhere and be freely
  replicated (Lomet, 2005; Frølund & Guerraoui e-transactions).

## 6. x-ability: a correctness criterion for replicated services

Frølund & Guerraoui (Distributed Computing 2001) define correctness of a
replicated service as the illusion of a single fault-tolerant entity whose
side effects happen **exactly once** (Quéma, Middleware Support for Precise
Failure Semantics). Unlike serializability and linearizability (safety-only
theories of concurrency), x-ability is a theory of partial failure with both
safety and liveness parts; it constrains concurrency among replicas *within*
one request and is silent about concurrency *between* requests. It is a local
property, so x-able services compose.

Model: replicas run copies of a state machine exporting actions; histories
are sequences of start events S(a, iv) and completion events C(a, ov).
Two action kinds make retried executions reducible:
- **Idempotent** action a^i: n executions have the same side effect as one;
  earlier attempts can be erased from a history once one succeeds.
- **Undoable** action a^u with a cancel action and a commit action (both
  idempotent): a cancelled execution can be erased; after commit the effect is
  permanent (transaction-like).

A history is **x-able** if a reduction (erase superseded idempotent attempts,
erase cancelled undoable attempts, collapse repeated commits) yields a
failure-free history of a single execution. A service is x-able for a client
issuing one request at a time if:

| Req | Property | Kind |
|---|---|---|
| R1 | the client's submit is idempotent (safe to resubmit) | safety |
| R2 | submit eventually succeeds (non-blocking) | liveness |
| R3 | the server-side history per request is empty or x-able | safety |
| R4 | the reply is consistent with the server-side history (no invented replies or requests) | safety |
| R5 | each reply is a possible reply given all earlier requests in order (state carries forward) | safety |

**e-Transactions** (Frølund & Guerraoui, TSE 2002; TPDS 2001) apply this to
three-tier systems: a request issued by a browser through replicated app
servers against back-end databases commits exactly once end-to-end, with the
app-server tier able to fail over mid-request.

## 7. Engine-level recipes

1. **Outcome inquiry by transaction identity.** Let the client attach a
   unique request id; persist `(request_id, outcome, result digest)` in the
   same transaction as the effects (unique constraint), retained at least for
   the client's maximum retry horizon. On reconnect the client asks
   "did request_id commit?"; the answer is authoritative because it is
   written atomically with the effects.
2. **Failover drivers.** On loss of the primary, a driver aborts transactions
   that had not sent COMMIT, and for an in-flight COMMIT asks the new primary
   for the outcome (Kemme, Replication for Availability). With 1-safe
   replication the new primary may honestly answer "never committed" for a
   transaction the old primary acknowledged: RPO > 0 surfaces here.
3. **Transactional outbox.** Write outbound messages to a table in the same
   transaction as the state change; a relay delivers at least once; consumers
   dedupe by message id (the CIC receiver rule).
4. **Idempotent DDL/DML scripts**: guard with existence checks or record
   applied migration ids in the same transaction.
5. **Session state**: temporary tables, session variables, prepared
   statements and open cursors are volatile; either make sessions
   reconstructible by replaying establishing commands, or declare them lost on
   failover and surface a distinct error class.

> **Beyond EDBS:** Oracle's Transaction Guard exposes a logical transaction
> id whose commit outcome can be queried after an outage, and Application
> Continuity replays in-flight work on a new session when the outcome is known
> to be uncommitted — a productised version of recipes 1 and 5.

## 8. Pitfalls

- Request-id table purged before clients stop retrying ⇒ duplicates.
- Request id generated server-side ⇒ useless for retries after a lost reply.
- Reading the clock or a random number inside replayed logic without logging
  it ⇒ divergent replay (violates piecewise determinism).
- "Exactly once" claimed for an external side effect (email, payment API)
  without an idempotency key accepted by that external party.
- Treating a timeout as abort and retrying a non-idempotent transaction.
- Reply returned to the client under early lock release / async commit
  before the commit record is durable: the client sees a result that a crash
  can erase.

Sources: EDBS Application Recovery p.123; Atomicity p.186; Middleware Support
for Precise Failure Semantics p.2264; Replication for Availability and Fault
Tolerance p.3187 (driver failover). Recommended-reading papers as cited.
