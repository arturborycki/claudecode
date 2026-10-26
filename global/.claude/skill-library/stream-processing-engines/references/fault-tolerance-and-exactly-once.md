# Fault tolerance, high availability, and transactional (exactly-once) stream processing

Read this when you are designing recovery for stateful continuous queries,
choosing between active replicas, checkpoints and upstream backup, defining
what "exactly once" means for your engine, handling network partitions, or
mixing streams with transactional shared state.

---

## 1. Failure model and vocabulary

- Unit of failure: a **processing node** (one process hosting several
  operators). Failures are *crash* (visible halt or unresponsiveness) and
  *network partition* (nodes split into groups that cannot communicate).
  Byzantine failures and source/client failures are out of scope for the
  classical work.
- **k-fault tolerance**: survive k simultaneous node failures, typically with
  k+1 replicas of each piece of state. Examples below use k = 1.
- **Availability** for a DSMS includes *latency*. A query that is up but
  stalled for minutes is unavailable to a trading or intrusion-detection
  client.
- **Determinism assumption**: both classical approaches model each operator
  as a deterministic state machine, so the same input in the same order gives
  the same output in the same order. Two runs are *consistent* if they produce
  the same output sequence. Every technique below fails silently when this
  assumption fails (§6).

Two general families:

| Family | Mechanism | Runtime overhead | Recovery time |
|---|---|---|---|
| State-machine replication | k+1 replicas receive the same input in the same order | (k+1)× resources | near-zero failover |
| Rollback recovery | periodic checkpoints to another node (or disk) + log of input since checkpoint; on failure restore and replay | low | proportional to checkpoint interval + replay |

For partitions, a system either **stalls** to stay consistent or **proceeds**
on partial input for availability and reconciles later. The reconciliation
options are (a) propagate all updates and resolve conflicts by rules, or
(b) undo partition-time work and redo it on complete input.

---

## 2. Crash-failure techniques for continuous queries

### 2.1 Active replicas

- *Process pairs*: the primary forwards every input, in order, to a lockstep
  secondary (Tandem heritage).
- *Loose dataflow coordination* (Flux, Borealis DPC). Replicate both producer
  and consumer operators. There is no primary or secondary. Each producer
  logs its output and sends it to its current consumer(s). Each consumer
  periodically acknowledges, to *all* producer replicas, the input position it
  has received up to. Producers truncate their output logs below the minimum
  acknowledged position. With reliable in-order transport (TCP) or
  checkpoints, consumers need to acknowledge only a subset of producers.
- Benefits: a symmetric design with few cases, so it is easy to verify; with
  enough buffering each replica pipeline runs at its own pace.
- Failover: consumers and producers reconnect to the surviving copy. It is
  safe to fail over *before* group-membership consensus finishes, which
  avoids output stalls.
- Flux and DPC both guarantee strict consistency under crash failures: no
  lost and no duplicate output.

**Replica divergence is the real enemy.** Multi-input operators (union,
join) see interleavings that depend on network timing, so replicas diverge.
Borealis inserts a deterministic serializing union (SUnion) ahead of such
operators, so replicas agree on the input order. Any equivalent scheme works:
merge by (event timestamp, source id, sequence number) behind a heartbeat
gate.

> **Note (wide area):** Hwang, Çetintemel & Zdonik (ICDE 2008) let each consumer replica merge
> the output streams of *all* producer replicas into one duplicate-free
> stream, always using the fastest one. Operators are redesigned to process
> out-of-order input where possible while preserving failure-free results.
> Replication level and placement are tuned online.

### 2.2 Passive standby

The primary periodically checkpoints its state to a backup: operator state
plus inter-operator queue contents. In practice it sends a **Δ-checkpoint**
(the difference since the last checkpoint). Primaries log their output
tuples. On failure the backup restores the last checkpoint, and every upstream
primary resends logged output from that point. A producer may discard logged
output only when **all** downstream backups have acknowledged a checkpoint
that covers it, because outputs can fan out to several consumers.

Refinement: cooperative distributed checkpointing (Hwang et al., ICDE 2007).
Nodes form logical clusters that back each other up. A node's operators are
checkpointed to *different* peers, so they recover in parallel. Backup
assignment and checkpoint scheduling are optimized for recovery speed, and
checkpoints cover a few operators at a time, started in idle periods, to limit
disruption.

### 2.3 Upstream backup

For *bounded-history* operators (windowed joins and aggregates over short
windows) there is no need to checkpoint at all. Primaries keep output logs.
Backups stay **idle**. Downstream operators tell their upstreams (one or more
levels up) which logged tuples their state no longer depends on. A tuple that
has expired from every window that could contain it is no longer needed. On
failure, an empty backup rebuilds state by replaying the upstream logs.

Upstream backup has the lowest runtime overhead. Recovery time is
proportional to the retained history, so it only fits small windows. Repair
completes once the new replica's own output log holds enough history to
rebuild *its* downstream consumers.

### 2.4 Recovery phases and granularity

1. **Detection**: timeouts plus a group-membership service.
2. **Masking / failover**: switch to the surviving replica (active), or
   restore + replay (passive, upstream).
3. **Repair**: recreate the lost replica and return to k-tolerance.

Coordination granularity matters. If replicas coordinate only at the
query's inputs and outputs, repair must stop the whole query, checkpoint it,
copy state (possibly tens of GB, which takes minutes), and restart, because
in-flight data inside the network is uncontrolled. Coordinate at node,
operator or finer boundaries so you can repair piece by piece while the rest
keeps running. That lowers mean time to recovery (MTTR) and improves
reliability. With more than two replicas, use the spares to smooth repair
stalls.

### 2.5 Trade-off summary

| Technique | Normal-case cost | Failover | Best for |
|---|---|---|---|
| Active replicas (Flux, DPC, active standby) | ∝ replication degree | instant | latency-critical monitoring |
| Passive standby (Δ-checkpoints) | tunable by checkpoint interval | restore + replay | large state, moderate latency tolerance |
| Upstream backup | lowest (logs only) | ∝ window history | small-window operators |
| Cooperative distributed checkpointing | spread over cluster | parallel recovery | clusters with spare capacity |

Flux also integrates **load balancing with fault tolerance**. Partitioned
operator state can move online between machines, and the same state-movement
mechanism serves both rebalancing and repair, under a global controller. Short
imbalances are absorbed by allowing out-of-order processing of partition
input.

---

## 3. Network partitions: Borealis DPC (Delay, Process, Correct)

- **Delay**: when an input becomes unavailable, wait up to an
  application-specified maximum tolerable latency, hoping the partition heals.
- **Process**: past that bound, process available input and emit outputs
  marked **tentative**.
- **Correct**: after healing, the node reconciles its diverged state. Either
  restore a checkpoint and replay the now-complete input, or undo/redo the
  work done since the partition. It then emits corrections to its tentative
  outputs so that downstream nodes and clients converge.
- Never reconcile all replicas of a node at once, or the output stalls.
  Reconcile one replica while another keeps serving (tentatively).
- The guarantee is **eventual consistency** of the output stream, with
  latency bounded by the user's threshold. Flux, designed for LANs, instead
  favours consistency and stalls.

Correction messages are revision tuples (`windows-and-punctuations.md` §6).
Downstream operators must accept "retract tentative t, insert stable t′".

---

## 4. Recovery guarantees and what "exactly once" means

Hwang et al. (ICDE 2005) define three recovery semantics:

| Guarantee | Output after failure | Modern name |
|---|---|---|
| Precise recovery | identical to failure-free output | exactly-once |
| Rollback recovery | nothing lost, but reprocessing may duplicate | at-least-once |
| Gap recovery | some output may be lost | at-most-once |

Under rollback recovery the duplicates are of three kinds:
- *repeating*: identical to pre-failure outputs, so they can be deduplicated
  to reach precise recovery;
- *convergent*: different at first but converging (e.g., a re-opened window
  re-emits a slightly different early result and then the same final one).
  Precise recovery is achievable with care;
- *divergent*: permanently different (non-deterministic operators). Precise
  recovery is impossible without logging non-deterministic choices.

**Distinguish the two senses of exactly-once.**
1. *Exactly-once state*: each input affects internal operator state exactly
   once (checkpoint + replay from a consistent cut gives this).
2. *Exactly-once delivery*: each external output is observed exactly once by
   the consumer. This needs either idempotent sinks (deterministic output ids
   + upsert/dedup) or transactional sinks committed atomically with the
   checkpoint. MillWheel provides both: deduplication by record id makes
   delivery exactly once, which is stronger than state-only exactly-once.

### 4.1 Mechanisms in big-stream systems (from the bundle)

- **Storm**: every tuple gets a message id. Each output's lineage tree is acked
  back through the topology. The spout holds a tuple until its tree is fully
  acked and replays it on timeout. This is at-least-once, and it is
  structurally upstream backup. With acking disabled it is at-most-once.
  Trident adds exactly-once via an external persistent state store.
  > **Beyond EDBS:** Storm's acker tracks each tuple tree with a single
  > 64-bit XOR of random edge ids. Each edge id is XORed in when the edge is
  > created and again when it is acked, so the value returns to zero exactly
  > when the tree is complete. That is O(1) memory per spout tuple.
- **Spark Streaming (D-Streams)**: each micro-batch is a deterministic
  computation over immutable, replicated input. Lost partitions are recomputed
  from lineage, in parallel across the cluster, with periodic checkpoints to
  truncate lineage. Exactly-once state comes from determinism plus
  recomputation.
- **MillWheel**: persistent per-key state in a store, record ids, and
  deduplication, plus checkpointing of produced records before they are
  acknowledged.
- **S4**: periodic checkpoints to remote storage. State since the last
  checkpoint is lost (gap recovery), there is no failover without a spare
  node, and placement is static.
- **Kafka** (as the plumbing): per-partition order and retention-based
  durability. Default delivery is at-least-once, and at-most-once if retries
  are disabled. Exactly-once is possible with consumer-side cooperation.

> **Beyond EDBS: asynchronous barrier snapshots (Flink).** Carbone et al.
> ("Lightweight asynchronous snapshots for distributed dataflows", 2015;
> "State management in Apache Flink", VLDB 2017) adapt Chandy–Lamport to
> acyclic dataflows:
> 1. The coordinator tells sources to inject barrier n into every output
>    channel and to record their read offsets (e.g., Kafka offsets) as part of
>    snapshot n.
> 2. An operator with several inputs *aligns*: once barrier n arrives on a
>    channel it buffers (stops consuming) that channel until barrier n has
>    arrived on all channels. Records before the barrier belong to snapshot n,
>    records after it to n+1.
> 3. With all barriers in, it snapshots its state asynchronously
>    (copy-on-write or incremental RocksDB SST upload), forwards barrier n
>    downstream, and acknowledges to the coordinator.
> 4. Snapshot n is complete when every task (sinks included) has acked. Recovery resets *all* tasks to
>    snapshot n and rewinds sources to the recorded offsets.
>
> This gives exactly-once *state* without logging in-flight records (for DAGs;
> cycles must log in-loop records). Alignment adds latency under
> back-pressure. *Unaligned checkpoints* (Flink 1.11+) let barriers overtake
> buffered data and store the overtaken in-flight buffers in the snapshot.
> Recovery is global rollback, unlike Borealis's local repair. End-to-end
> exactly-once needs a transactional sink: pre-commit at the barrier and
> commit on checkpoint-complete notification (a two-phase-commit sink).
> Otherwise use an idempotent sink.

> **Beyond EDBS: Kafka exactly-once (KIP-98, Kafka 0.11, 2017).**
> *Idempotent producer*: a producer id + epoch + per-partition sequence numbers
> let brokers drop retried duplicates. *Transactions*: a `transactional.id` maps
> to a coordinator and a transaction log, and a producer can atomically write to
> many partitions *and* commit consumer offsets (`sendOffsetsToTransaction`).
> Commit/abort markers are written to every partition. Consumers with
> `isolation.level=read_committed` read only up to the last stable offset.
> Epoch bumps fence zombie producers. Kafka Streams' exactly-once mode is the
> consume-transform-produce loop inside one such transaction, with state
> changelogs also written transactionally. The guarantee holds only inside
> Kafka. External side effects still need idempotence.

---

## 5. Transactional stream processing

Correctness for streaming covers more than ACID: **order** (time order of
events and topological order of dataflow steps), **exactly-once** processing
and delivery, and ACID when computations share **mutable state** (e.g., a table
updated by streaming transactions and read by ordinary OLTP).

Why plain ACID is not enough:
- ACID serializability allows *any* serial order. Streams need the serial
  order to respect timestamps and dataflow precedence.
- OLTP aborts and leaves re-submission to the client. A stream engine must
  re-invoke a failed step itself or the dataflow loses data. It must also
  ensure that redoing a committed step does not re-trigger its downstream
  steps a second time.

Progression of models (each defines a different atomic unit):

| Work | Atomic unit | Guarantees | Notes |
|---|---|---|---|
| CQL/STREAM | all tuples with one logical timestamp | implicit A and I, ordered execution | single plan, single node, no failures |
| Golab, Bijay, Özsu (EDBT 2006) | sub-window | **window-serializable** (reads see a contiguous run of sub-windows) and **latest-window-serializable** (and the most recent one) | conflict serializability is too weak because it ignores write order of window slides; optimistic scheduler minimizes aborts |
| Wang, Rundensteiner, Ellison (VLDB 2011) | one input event's cascade of state changes | ordered writes in timestamp order; outputs not undoable | active CEP rules over a shared table; a low-water-mark scheduler (locking + multiversioning) performed best |
| Botan et al. UTM (EDBT 2012) | application-punctuated segment of stream ops | conflict serializability respecting arrival order; durability as "committed events never reprocessed or duplicated" | unifies event-oriented continuous queries with operation-oriented one-time queries |
| S-Store (Meehan et al., VLDB 2015) | **atomic batch** (tuples sharing a batch id) processed by a stored-procedure transaction | ACID per transaction + ordered batch execution + dataflow topological order + exactly-once recovery | built on H-Store; streams, windows and tables are all in-memory tables with access rules |

S-Store's state classes: *tables* are public to all transactions; *windows*
are private to the transaction that defines them; *streams* are private to
their producer and consumer. Windows have size and slide in units of batches.
Transactions chain into DAGs, and a group can be nested for stronger
isolation. A streaming scheduler enforces ascending batch-id order per stream
and topological order per dataflow. Integrating streams and OLTP in one engine
outperformed stitching a stream engine to a separate transactional store (the
Storm + external store pattern).

> **Beyond EDBS:** The S-Store papers describe two recovery modes. *Strong*
> recovery replays the command log of all transactions. *Weak* recovery
> replays only border (input) transactions and re-fires the dataflow, which is
> cheaper but yields only an equivalent, not necessarily identical, state when
> nondeterminism exists.

---

## 6. Sources of nondeterminism (audit list)

Every guarantee above assumes deterministic replay. Audit the engine for:
1. **Wall-clock reads** in operators (processing-time windows, `now()` in
   predicates, timers). Log them or derive time from input.
2. **Input interleaving** at union/join/co-process operators. Make it
   deterministic (SUnion-style merge on (ts, source, seq)) or log the order.
3. **Hash iteration order** feeding output order (unordered maps keyed by
   pointer, randomized hash seeds per process).
4. **Floating-point aggregation order** across parallel partials. The result
   depends on merge order. Fix the merge tree or accept convergent duplicates.
5. **External lookups** (stream ⋈ mutable table at processing time, RPCs to
   services). Version them by event time or log responses.
6. **Random sampling / load shedding**. Seed RNGs from checkpointed state.
7. **Thread-scheduling-dependent batching** where batch boundaries affect
   results (e.g., count-based triggers across partitions).

Divergent duplicates (§4) come from exactly these sources.

---

## 7. Testing fault tolerance

- **Kill-anywhere harness**: run a deterministic workload. Kill a random task
  at a random point (between barrier alignment and snapshot, during sink
  commit, during upstream log truncation). Restart. Compare the final output
  multiset (exactly-once) or set (at-least-once + idempotent sink) with a
  failure-free run.
- **Duplicate classifier**: tag outputs with (window id, key, version).
  Classify post-recovery differences as repeating, convergent or divergent.
  Any divergent difference is a nondeterminism bug.
- **Log-truncation safety**: property test that a producer never truncates
  output a downstream backup (or snapshot) still needs. Fuzz ack reordering
  and delayed acks.
- **Partition drill**: partition a node beyond the DPC delay bound. Check that
  tentative outputs are labelled, corrections arrive after healing, and the
  stable output equals the failure-free output.
- **Zombie fencing**: run two instances of the same transactional producer.
  The stale one must be fenced, with no interleaved committed output.
- **Recovery-time SLO**: measure MTTR vs. state size and checkpoint interval.
  Upstream backup recovery must scale with window length, not total history.

Sources: EDBS "Fault Tolerance and High Availability in Data Stream
Management Systems" (p.1448), "Transactional Stream Processing" (p.4205), "Big
Stream Systems" (p.273), "Data Stream Management Architectures and Prototypes"
(p.854), "Distributed Data Streams" (p.1162, for Borealis revision tuples and
Flux).
