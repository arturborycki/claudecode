# Atomic commit protocols, termination, and distributed recovery

The classical atomic-commitment design space at implementation depth: the
correctness conditions, 2PC state machines and exactly which log writes are
forced, presumed-nothing / presumed-abort / presumed-commit and their cost
accounting, termination protocols and in-doubt resolution, 3PC and the
assumptions that make it non-blocking, the optimization catalog (read-only,
last agent, group commit, flattening, linear/decentralized), heuristic
decisions and protocol interoperability, and site recovery.

The existing `distributed-transactions` skill covers the 2PC/3PC outline and
modern systems (Spanner, Calvin, Percolator); this file is the classical
engineering detail underneath.

---

## 1. The atomic commitment problem

Each site guarantees local atomicity; the protocol must guarantee a unanimous
binary outcome. Correctness conditions (Bernstein–Hadzilacos–Goodman style):

- **AC1 Agreement**: all processes that reach a decision reach the same one.
- **AC2 Irrevocability**: a process cannot reverse its decision.
- **AC3 Validity (commit)**: commit can be decided only if all processes voted
  YES.
- **AC4 Non-triviality**: if there are no failures and all vote YES, the
  decision is commit.
- **AC5 Termination**: after all failures are repaired and no new ones occur
  for long enough, every process eventually decides.

Assumptions under which ACPs are proved (stated in the 2PC entry): **fail-stop
sites** (no Byzantine behavior), **eventual recovery** of every failure, and a
**binary** outcome. Failures are detected only by timeouts, so a slow site and
a crashed site are indistinguishable.

Blocking is inherent: an ACP is *non-blocking* if operational sites never
have to wait for a failed site to recover. Skeen & Stonebraker (TSE 1983):
no ACP is non-blocking in the presence of both site failures and network
partitions (more precisely, with message loss/partitions that are
indistinguishable from site failures). 2PC blocks under coordinator failure;
3PC is non-blocking only for site failures with a reliable network.

Performance metrics (Al-Houmaily & Samaras):
- **message complexity**: messages per transaction;
- **log complexity**: log records written, and above all **forced** writes;
- **time complexity**: sequential message rounds before the decision is known;
- plus **resilience** (which failures block) and **independent recovery**
  (can a site recover from its own log without asking anyone).

## 2. 2PC: state machines and log discipline

Coordinator states: INITIAL → (WAIT/collecting) → COMMIT | ABORT → (forgotten).
Participant states: INITIAL → READY (prepared, in doubt) → COMMIT | ABORT;
or INITIAL → ABORT on a NO vote.

Presumed-nothing (basic) 2PC, commit path:

```
Coordinator                                   Participant i
-----------                                   -------------
[force] begin/collecting record {T, participants}        (variant-dependent, see §3)
send PREPARE ───────────────────────────────▶
                                              validate (constraints, deferred checks, SSI/OCC)
                                              [force] all undo/redo of T, then PREPARED record
                                ◀─────────────── vote YES
(all YES)
[force] COMMIT record {T, participants}
send COMMIT ────────────────────────────────▶
                                              [force] COMMIT record; release locks
                                ◀─────────────── ACK
(all ACKs)
[lazy] END record; forget T
```

Rules engine code must enforce:
- A participant forces its PREPARED record (and all of T's log before it)
  *before* sending YES. After YES it has surrendered autonomy: it may neither
  commit nor abort unilaterally.
- A participant voting NO may abort immediately and need not wait for the
  decision (the coordinator sends ABORT only to YES voters).
- The coordinator forces the decision record *before* sending the decision.
- The coordinator may forget T only after every participant that needs to
  acknowledge has done so; END is non-forced because losing it only causes a
  harmless resend.
- The decision record lists participants so a recovering coordinator knows
  whom to re-inform.
- Locks: write locks held through the decision; read locks may be released at
  PREPARE (strict 2PL needs them only until the vote).

Timeout actions (the four places a wait can happen):

| Who, waiting for | Action |
|---|---|
| Participant in INITIAL, waiting for PREPARE | unilaterally abort (it has not voted) |
| Coordinator in WAIT, waiting for votes | decide ABORT (re-send PREPARE a few times first) |
| Participant in READY, waiting for decision | **blocked**: run the termination protocol; cannot decide alone |
| Coordinator in COMMIT/ABORT, waiting for ACKs | re-send the decision until ACKed |

**Cooperative termination protocol** (2PC): a READY participant that cannot
reach the coordinator asks the other participants (the PREPARE message
carries the participant list for this purpose):
- if any participant knows COMMIT or ABORT → adopt it;
- if any participant is still INITIAL (has not voted) → it can abort
  unilaterally, so everyone may abort;
- if every reachable participant is READY → still blocked; the coordinator
  might have decided either way.
This narrows but does not close the blocking window.

**Hierarchical vs flat 2PC.** In the tree-of-processes model a participant
that spawned remote work becomes a sub-coordinator: PREPARE is forwarded down,
an inner node votes YES only after all children vote YES and after forcing
its own prepared record; decisions flow down, ACKs up. **Flattening** at
commit initiation (root talks directly to every node) removes per-level
forced writes and propagation delay; RCT-UP flattens only update participants
and leaves read-only ones in the tree.

## 3. Presumption variants

The idea: write and send less in a systematic way, and answer inquiries about
transactions the coordinator has no record of with a fixed presumption.

**Presumed abort (PrA)** (Mohan, Lindsay, Obermarck TODS 1986):
- No coordinator begin record. Abort decisions are not logged by the
  coordinator; participants do not force abort records and do not ACK aborts.
- An inquiry about an unknown transaction is answered ABORT. This is safe
  because the coordinator only "forgets" a commit after all ACKs, and an
  unremembered transaction either aborted or never reached a commit decision.
- Commit path is identical to basic 2PC.

**Presumed commit (PrC)** (same paper):
- The coordinator **forces an initiation (collecting) record** listing the
  participants before sending PREPARE — otherwise a crash between PREPARE and
  decision would leave in-doubt participants whose inquiry would be answered
  "commit" by presumption.
- Commit: coordinator forces COMMIT (which logically cancels the initiation
  record), sends COMMIT, forgets immediately; participants write a non-forced
  commit record and send no ACK.
- Abort: coordinator sends ABORT and waits for ACKs (it must remember aborts),
  participants force ABORT and ACK.
- Recovery: initiation record without decision → abort and inform the listed
  participants.

Per-transaction costs for an update transaction with one YES-voting
participant, flat model (log records written / of which forced / messages
sent) — derived from the protocol rules above:

| Variant, outcome | Coordinator | Participant | Msgs coord→part | Msgs part→coord |
|---|---|---|---|---|
| Basic, commit | 2 / 1 (decision forced, end lazy) | 2 / 2 (prepared, commit) | 2 | 2 (vote, ack) |
| Basic, abort | 2 / 1 | 2 / 2 | 2 | 2 |
| PrA, commit | 2 / 1 | 2 / 2 | 2 | 2 |
| PrA, abort | 0 / 0 | 2 / 1 (abort lazy) | 2 | 1 (no ack) |
| PrC, commit | 2 / 2 (initiation, commit) | 2 / 1 (commit lazy) | 2 | 1 (no ack) |
| PrC, abort | 2 / 1 | 2 / 2 | 2 | 2 |

(If basic 2PC also forces a begin record, as in the presumed-nothing
description of Weikum & Vossen, its coordinator column becomes 3 / 2.)

Why industry standardized on PrA (X/Open DTP / XA, ISO OSI-TP): PrC's commit
savings are offset by the forced initiation record, so PrC is not the mirror
image of PrA; and PrA combines cleanly with the **read-only optimization**.
PrC refinements: **New PrC** (Lampson & Lomet VLDB 1993) avoids the
per-transaction initiation force by keeping coarse-grained information about
possibly in-flight transaction ids on stable storage, at the price of slower
recovery; **Rooted PrC** removes initiation records at cascaded coordinators
in tree executions.

## 4. Optimization catalog

| Optimization | Mechanism | Saves | Caveat |
|---|---|---|---|
| Read-only | participant with no updates votes READ-ONLY, releases locks, writes nothing, leaves the protocol | phase 2 messages and all log writes at that site; whole-transaction read-only ⇒ coordinator writes nothing | releasing read locks at prepare breaks serializability only if the site could later receive more work for T — forbid that |
| Unsolicited update-vote (UUV) | participants announce "I updated" with the first update so read-only status is known early | cost parity between PrA and PrC for read-only sites | protocol support on both sides |
| Last agent | coordinator prepares itself and nearby participants, then delegates the decision to the single remote participant by sending its own YES | one round trip to the remote site | the last agent becomes the de-facto coordinator; recovery must know who decided |
| Group commit | batch many transactions' commit forces into one log flush | forced I/Os | adds latency per transaction up to the batch window |
| Lazy commit | force participant commit (and other) records in groups during commit processing | more forced I/Os | same |
| Shared log | TM and data managers at a site share one log, so a DM's records are forced by the TM's force | DM forces | coupling of components |
| Flattening / RCT-UP | two-level commit tree at commit time | sequential forces and hop latency in deep trees | needs full participant list at root |
| Unsolicited vote (UV) | participant votes on its own when it knows it executed T's last operation | the voting round | requires knowing "last operation" |
| Early prepare (EP) | treat every operation ACK as an implicit YES (with PrC) | voting round entirely | a forced log write per operation at participants |
| Coordinator log (CL) / Implicit yes-vote (IYV) | replicate participants' redo (IYV: only redo; CL: whole log) at the coordinator, so operation ACKs are implicit votes without per-operation forces | voting round and participant forces | slower participant recovery (must contact coordinators); CL even needs coordinator contact for WAL/undo |
| Optimistic (OPT) | let transactions read data written by a *prepared* lender; abort borrowers if the lender aborts | lock-wait time on prepared data | cascading aborts bounded to borrowers |

Message/round trade-offs among topologies (n participants):
- centralized 2PC: ~3 rounds to decision (prepare, vote, decision), 4n
  messages including ACKs;
- **linear 2PC** (token-ring order, last participant decides): 2n messages
  instead of ~3n, but 2n sequential rounds;
- **decentralized 2PC** (everyone broadcasts votes, everyone decides): 2
  rounds but n² + n messages; shorter window in which a coordinator crash can
  block.

## 5. Heuristic decisions and interoperability

Blocking for hours on a coordinator outage is unacceptable for some
resources, so practical protocols allow **heuristic completion**: an operator
or timeout forces a READY participant to commit or abort unilaterally,
knowingly risking atomicity.
- IBM **Presumed Nothing (PrN)** permits heuristic decisions and *detects and
  reports* atomicity damage (which participants decided which way), so it can
  be repaired. Generalized PrA behaves like PrN when heuristic recognition is
  required and like PrA otherwise.
- XA models this explicitly: a resource manager that completed a branch
  heuristically reports XA_HEURCOM / XA_HEURRB / XA_HEURMIX / XA_HEURHAZ
  from commit/rollback and must remember the branch until the TM calls
  xa_forget. `xa_recover` returns the XIDs of prepared (in-doubt) branches
  after restart — the hook the TM uses for in-doubt resolution.

Variants are **mutually incompatible**: they differ in message meanings and in
presumptions. A PrA coordinator answering a PrC participant's inquiry about a
forgotten committed transaction would say ABORT — atomicity violation.
**Presumed Any** (Al-Houmaily & Chrysanthis PODS 1999) lets one coordinator
drive basic, PrA and PrC participants: it forgets a commit only after all
basic and PrA participants ACK (PrC ones don't), forgets an abort only after
all basic and PrC participants ACK, and answers an inquiry about a forgotten
transaction with the *inquirer's* presumption (only a PrC participant can be
asking about a forgotten commit; only a PrA participant about a forgotten
abort). It introduced *operational correctness* (sites must be able to
forget outcomes, not just agree) and the *safe state* notion. Engineering
rule: put the protocol variant in every participant registration and inquiry
message.

## 6. 3PC: structure, termination, assumptions

**Skeen's conditions** (SIGMOD 1981) for a non-blocking protocol whose sites
stay within one state transition of each other ("synchronous within one
transition"): no local state may lead directly to both COMMIT and ABORT,
and no *non-committable* state is adjacent to a commit state. A state is
**committable** if being in it implies all sites voted YES. In 2PC, READY is
non-committable yet adjacent to COMMIT, and adjacent to ABORT — both
conditions fail.

3PC inserts a buffer state:
```
Coordinator:  INITIAL → WAIT → PRE-COMMIT → COMMIT        (or WAIT → ABORT)
Participant:  INITIAL → READY → PRE-COMMIT → COMMIT       (or READY → ABORT, INITIAL → ABORT)
phase 1: PREPARE / votes           (participants force prepared)
phase 2: PRE-COMMIT / ACK          (record pre-commit; may be non-forced)
phase 3: COMMIT                    (force commit)
```
PRE-COMMIT is committable; COMMIT is reachable only from PRE-COMMIT, ABORT
only from states before it.

**Termination protocol** (coordinator failure, reliable network):
1. Elect a new coordinator among operational participants (e.g. highest or
   lowest site id).
2. It collects every participant's state.
3. Decide:
   - any COMMIT → commit;
   - any ABORT → abort;
   - any PRE-COMMIT (and none aborted) → first move every READY participant
     to PRE-COMMIT, then commit (moving them first keeps the invariant if the
     new coordinator also fails mid-way);
   - otherwise (all READY or INITIAL) → abort (the old coordinator cannot have
     committed, because no one reached PRE-COMMIT).
4. If the new coordinator fails, repeat the election.

**Participant recovery** in 3PC is *not* independent: a site recovering in
READY or even PRE-COMMIT must ask the others, because operational sites may
have aborted after it failed (if no operational site was in PRE-COMMIT).
A site failed in INITIAL aborts.

**Total failure**: the outcome can be decided only by the *last* site to fail
(or after all recover). Keeping an UP list (sites believed operational) on
each site's log, written lazily, lets a recovering group determine whether it
contains the last site to fail.

**Why it is not used**: an extra round and extra log write on every commit,
a complex termination protocol, and it still blocks or — worse — violates
atomicity under partitions: one partition containing a PRE-COMMIT site
commits while another containing only READY sites aborts. Quorum-based
variants (Skeen) trade blocking in minority partitions for safety. The modern
answer is to make the coordinator and participants replicated state machines
(see distributed-consensus and distributed-transactions).

## 7. Distributed recovery and in-doubt resolution

Failure types beyond centralized ones: remote site crash, link failure,
partition, lost/delayed messages; timeouts conflate them. Local WAL recovery
(redo committed, undo uncommitted) is extended with the commit protocol's
records so each site knows the protocol state of every transaction at crash
time.

Coordinator restart (scan log, rebuild protocol table):

| Last record for T | Action |
|---|---|
| none (T active, no protocol record) | abort T (PrA: nothing to tell anyone; presumption covers inquiries) |
| begin/initiation, no decision | basic/PrC: decide ABORT and inform listed participants (or restart voting in basic 2PC) |
| decision, no END | re-send decision to participants listed in the decision record that have not ACKed; participants that already applied it reply with a **blind ACK** |
| END | nothing |

Participant restart:

| Last record for T | Action |
|---|---|
| no PREPARED | abort locally (it never voted YES; the coordinator cannot have committed) |
| PREPARED, no decision | **in doubt**: redo T's updates, re-acquire its write locks (from the log), then inquire the coordinator (or peers); hold locks until answered |
| COMMIT / ABORT | finish locally (redo/undo as WAL dictates) |

Implementation consequences:
- Prepared transactions must survive restart *with their locks*: log enough to
  rebuild the lock set (write locks at least) before accepting new work, or
  the recovered site will let new transactions read in-doubt data.
- Inquiry handling at the coordinator must be possible even when the
  coordinator has forgotten T — that is exactly where the presumption
  applies; never answer "unknown".
- Expose in-doubt transactions operationally (age, coordinator, locks held)
  and provide a heuristic-resolution command with damage reporting.
- Checkpoints: take them with the protocol table included so recovery does
  not have to scan back to the oldest in-doubt transaction; consistent
  distributed checkpointing reduces roll-back scope but is rarely worth its
  coordination in DBMSs.

Recovery acceleration from the entries:
- **Clustra** (Hvasshovd et al. VLDB 1995): log to main memory locally and
  to a remote node instead of forcing to disk; durability comes from the
  second copy on another node.
- **HARBOR** (Lau & Madden VLDB 2006): no recovery log in an updatable
  distributed warehouse; a crashed site recovers by querying replicas for
  updates since its last checkpoint (timestamped tuples).
- Recovery by streaming from multiple replica sources in parallel shortens
  catch-up time (Distributed DBMS entry); agent-based recovery buffers new
  operations for the recovering site and replays them over the recovered
  state.

> **Beyond EDBS:** Paxos Commit (Gray & Lamport, TODS 2006) runs one Paxos
> instance per participant's vote with 2F+1 acceptors, so the decision
> survives F acceptor failures without a blocking coordinator; with F = 0 it
> degenerates to 2PC. Spanner makes each participant a Paxos group and the
> coordinator one of them, so "coordinator crash" means leader change, not
> blocking. CockroachDB's *parallel commits* write a STAGING transaction
> record listing in-flight writes and treats the transaction as implicitly
> committed once all those writes are durably replicated, removing one
> consensus round from the commit latency; recovery checks whether all
> listed writes succeeded. PostgreSQL exposes 2PC participant mechanics
> directly: PREPARE TRANSACTION persists the transaction and its locks across
> restart, pg_prepared_xacts lists in-doubt transactions, and
> COMMIT PREPARED / ROLLBACK PREPARED resolve them; an external TM must do
> in-doubt resolution, and forgotten prepared transactions hold locks and
> block vacuum indefinitely.

Sources: Two-Phase Commit (p.4259); Two-Phase Commit Protocol (p.4266);
Three-Phase Commit (p.4127); Distributed Recovery (p.1212); Distributed
Transaction Management (p.1222); Distributed DBMS (p.1177).
