---
name: distributed-consensus
description: "Use when implementing or reasoning about agreement among distributed nodes: consensus algorithms (Paxos, Multi-Paxos, Raft), leader election, failure detection (heartbeats, phi-accrual, gossip), broadcast and atomic/total-order broadcast, replicated logs/state machines, and Byzantine fault tolerance. Triggers on consensus, Paxos, Raft, leader election, replicated log, state machine replication, atomic broadcast, total order broadcast, failure detector, heartbeat, quorum vote, term/epoch, Byzantine. Reach for this whenever nodes must agree on a single value or an ordered log; for data convergence use replication-and-consistency."
---

# Distributed Consensus

Consensus is getting a set of nodes to agree on a value (or an ordered
sequence of values) despite failures. It underlies replicated logs,
leader-based replication, and config/metadata stores. The theory bounds
what's possible; the algorithms make it practical.

## The impossibility you can't ignore

**FLP**: in a fully asynchronous system with even one crash failure, no
deterministic consensus algorithm can guarantee termination. Real systems
escape this with **partial synchrony** + timeouts (and randomization),
which is why every practical algorithm relies on timing assumptions for
*liveness* while keeping *safety* unconditional. The **Two Generals
Problem** shows agreement over a lossy link is impossible with certainty —
hence acknowledgements and retries, never a guarantee.

## Failure detection

Consensus needs to suspect failed nodes. Mechanisms:
- **Heartbeats / pings** — missed beats → suspicion; timeout tuning trades
  detection speed vs false positives.
- **Phi-accrual failure detector** — outputs a *continuous suspicion level*
  from the history of inter-arrival times instead of a binary up/down,
  letting callers pick their own threshold. Used in Cassandra/Akka.
- **Gossip-based** detection scales to large clusters.

A failure detector is fundamentally a *suspicion* service — it can be
wrong, so algorithms must stay safe under false suspicion.

## Leader election

Many systems funnel decisions through a leader. Classic algorithms: **bully**
(highest id wins), **ring**, **invitation**. In consensus protocols, leader
election is folded into the protocol itself (Raft terms, Paxos ballots) so a
stale leader can't violate safety.

## Atomic (total-order) broadcast == consensus

Delivering messages to all nodes in the *same total order* is equivalent to
consensus. A replicated log *is* total-order broadcast: agree on the order
of entries and every replica's **state machine** stays identical (**state
machine replication**).

## Paxos and Raft

- **Paxos**: roles are proposer, acceptor, learner. A two-phase protocol
  (prepare/promise then accept/accepted) with **ballot numbers** guarantees
  safety: once a value is chosen, no other value can be chosen. **Multi-Paxos**
  amortizes the prepare phase across a stable leader to agree on a log.
  Correct but notoriously subtle to implement.
- **Raft**: designed for understandability. Strong leader, **terms** as
  logical clock, **leader election** by randomized timeouts, **log
  replication** with a commit index, and a **safety rule** that only a
  candidate whose log is at least as up-to-date can win. Most new systems
  pick Raft for this reason. Get the corner cases right: log matching, leader
  completeness, commitment of entries from prior terms.

Both need a **majority quorum** (⌊N/2⌋+1) to tolerate ⌊(N-1)/2⌋ crash
failures — which is why consensus clusters are odd-sized (3, 5, 7).

## Byzantine consensus

If nodes can lie/behave arbitrarily (not just crash), you need **BFT** (e.g.,
PBFT), which tolerates f faults with **3f+1** nodes. Needed for adversarial/
trustless settings; overkill for a typical internal cluster.

## Language notes (C/C++/Rust)

- **Don't roll your own** for production: use **raft-rs** (Rust) or an
  established C++ Raft/Paxos library; consensus bugs are catastrophic and the
  edge cases are brutal. Implement from scratch only to learn or with
  exhaustive model checking.
- Drive the protocol as an explicit **state machine** with deterministic
  transitions; separate the protocol logic from I/O so you can unit-test it
  with simulated networks (deterministic simulation testing) and inject
  partitions, delays, and reorderings.
- Persist term/vote/log durably *before* responding — losing this on restart
  breaks safety.

## Grounding
Petrov Ch 8 (concurrent execution, Two Generals, FLP, synchrony, failure
models), Ch 9 (failure detection: heartbeats, phi-accrual, gossip), Ch 10
(leader election), Ch 14 (broadcast, atomic broadcast, Paxos, Raft,
Byzantine consensus).

## EDBS grounding & deeper skills
EDBS 2e entries (pull full text with `edbs-reference`: `python3 <edbs-reference>/scripts/edbs.py show "<Entry>"`):
*Replication Based on Paxos* (p.3184); *Replication Based on Group Communication* (p.3177); *Physical Clock* (p.2758).
Go deeper with: `replication-protocols`, `distributed-dbms-design`.
