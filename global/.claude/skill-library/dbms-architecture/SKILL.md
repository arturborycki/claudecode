---
name: dbms-architecture
description: "Use when designing or reviewing the whole-system structure of a relational engine: component boundaries (query processor, storage manager, buffer/lock/log/transaction managers, catalog), process and thread models, connections and sessions, client-server and multitier deployment, buffer pool policy and its coupling to WAL, cache-conscious and main-memory design, and shared-memory/shared-disk/shared-nothing choices. Triggers on buffer pool, page replacement, LRU-K, 2Q, ARC, CLOCK sweep, scan resistance, pin/unpin, read-ahead, write-behind, steal/no-force, process-per-connection, thread pool, admission control, SEDA, staged DBMS, connection pool, session state, system catalog, NSM/DSM/PAX, cache miss, TLB, NUMA, branch misprediction, prefetching, in-memory DBMS, shared-nothing, shared-disk, database machine, data independence. Apply even when phrased as 'the server falls over at 2000 connections', 'can we just mmap the file', or 'which module should own this'."
---

# DBMS Architecture

This skill owns the *box diagram* of a relational engine: which component
owns which state, which interfaces separate them, how work is mapped onto OS
processes/threads, and how the engine exploits every level of the memory
hierarchy. The single most important idea: **a DBMS is a stack of contracts**
(data independence above, the buffer-pool/WAL contract below, the process
model against the OS), and almost every architectural bug is a component
violating one of those contracts for speed.

## Mental model

```
 client ──(wire protocol: connection, auth, session)──┐
 ┌──────────────── process / thread manager ─────────┴──── admission control
 │ query processor:  parse+authorize → rewrite → [plan cache] → optimize → execute
 │                                   (catalog manager: schema, stats, privileges)
 ├──────────────── record / index interface (keys, RIDs, scans) ────────────
 │ storage manager:  access methods (heap, B-tree, column segments)
 │                   lock manager | log manager | transaction manager
 │                   buffer manager (frames, page table, replacement, I/O)
 ├──────────────── page / block interface ──────────────────────────────────
 │ OS: async I/O, synchronization, memory; devices
 └──────────────────────────────────────────────────────────────────────────
```
- Upward contract: **data independence** — physical design (indexes, layout,
  partitioning, compression) may change plans and speed, never answers.
- Downward contract: the buffer pool is the only path between volatile and
  durable state, so it enforces **write ordering for recovery** (WAL) and is
  where pinning/latching meet transactions.
- Sideways contract: the **process model** decides scheduling, isolation of
  failures, memory sharing and how many concurrent requests the engine can
  hold without collapsing.
- Every level is a small fast cache over a large slow one (pages, cache
  lines, TLB entries); the engine knows its reference string, the OS does not.

## Core invariants

1. A frame with `pin_count > 0` is never evicted, moved, or reused; at
   quiescence all pin counts are 0.
2. Each page id maps to at most one frame; a page being read is marked
   in-transit and concurrent requesters wait instead of issuing a second read.
3. WAL: a dirty frame with `pageLSN = L` is written only if `flushedLSN >= L`;
   commit is acknowledged only once its commit record (no-force) or all its
   pages (force) are durable.
4. Latches are short, level-ordered, never held across I/O or lock waits, and
   invisible to deadlock detection; locks are transaction-scoped and visible.
5. Recovery units are never coarser than lock units: row/key locking needs
   record-level logging, not page images from a file system or SAN.
6. The pool is never paged by the OS and, with direct I/O, never double-cached.
7. A compiled plan carries the catalog version it was built on; a newer
   version forces re-validation or re-planning.
8. Granted work memory never exceeds the budget; a query starts only if its
   minimum grant is available.
9. Session state (settings, temp tables, prepared statements, cursors) dies
   with its session; transaction identity is decoupled from connection
   identity once a middle tier exists.
10. Physical-design changes (index, layout, partitioning) never change results.
11. Shared-disk: no node reads a page older than the latest version owned
    elsewhere; ownership is serialized by a global lock/ownership protocol.

## Design space & trade-offs

| Process model | Wins when | Cost / risk |
|---|---|---|
| Process per connection (PostgreSQL) | crash isolation, simple code, OS scheduling | heavy per-connection memory, fork cost, context switches; needs external pooler |
| Thread per connection (classic MySQL) | cheap creation, shared address space | oversubscription and latch convoys at high connection counts; one bad thread kills all |
| Worker pool / async (SQL Server SQLOS, Oracle shared server, MySQL thread pool) | thousands of mostly idle sessions | must never block a worker on I/O/locks without yielding; session-to-worker affinity bugs |
| Staged / SEDA (QPipe, Cordoba) | instruction/data locality, cross-query work sharing | queueing latency, scheduling complexity; sharing can serialize work on many-cores |

| Replacement | Wins when | Cost / risk |
|---|---|---|
| LRU list | simple, small pools | list latch hotspot; flooded by scans |
| CLOCK / clock-sweep + usage counter | high concurrency, cheap hits | approximate; still needs scan handling |
| LRU-K (K=2) / 2Q | mixed OLTP + scans | history for evicted pages; correlated-reference period tuning |
| ARC / CAR | shifting recency-vs-frequency mix | ghost lists; patent history on ARC |
| Hints: ring buffers, keep/toss, hot set, MRU for loops | the plan knows the reference string | needs optimizer↔buffer interface |

| Data path to storage | Wins when | Cost / risk |
|---|---|---|
| Own buffer pool + direct I/O | full control of eviction, write order, prefetch | must implement read-ahead/async I/O yourself |
| Own pool over buffered I/O | portability | double caching; kernel write-back reorders I/O |
| mmap the files | prototyping, read-mostly | OS may write dirty pages before log; page-fault stalls; SIGBUS on I/O error; TLB shootdowns |

| Layout | Wins when | Cost / risk |
|---|---|---|
| NSM (row/slotted page) | point access, whole-row updates (OLTP) | scans drag unneeded columns through cache and I/O |
| DSM (column) | few columns of many rows (OLAP), compression | tuple reconstruction, update cost |
| PAX (per-column minipages inside a page) | keep page-level I/O and recovery, gain column cache locality | no I/O savings; page split complexity |

| Architecture | Wins when | Cost / risk |
|---|---|---|
| Shared-memory (SMP) | fits one box; simplest; best per-box throughput | limited scale, memory faults hit all |
| Shared-disk | load balancing, migration from centralized, availability | distributed lock / cache coherence; hot pages ping-pong |
| Shared-nothing (MPP) | scale-out, hot spots stay put ("move the operation to the data") | partitioning drives load balance; skew; repartitioning on growth |

## Algorithms that matter

- **Fix/unfix:** hash page id (partitioned table, per-bucket latch) → hit:
  pin, update replacement metadata cheaply → miss: pick victim (skip pinned),
  if dirty ensure log flushed to its pageLSN then write, mark frame
  "in-transit", release latch during I/O, wake waiters. O(1) expected.
- **Clock sweep:** hand advances; `usage>0 → usage--`, else evict if unpinned.
  Hit sets `usage = min(usage+1, cap)`. Amortized O(1); cap bounds sweep.
- **2Q / LRU-2:** first touch enters a FIFO probation queue (A1in); only a
  re-reference after eviction-to-ghost (A1out) or after the correlated period
  promotes to the main LRU (Am). Sequential scans never reach Am.
- **Read-ahead depth** ≈ min(I/O, consumer bandwidth) × I/O latency, async,
  triggered by plan hints as well as pattern detection.
- **Hot set:** for nested loops with inner S, faults drop from
  `|R|·(1+pages(S))` to `pages(R)+pages(S)` once frames ≥ `1+pages(S)`; admit
  queries so the sum of hot-set sizes ≤ pool; use MRU for loop reuse.
- **Radix partitioning:** fan-out per pass ≤ min(TLB entries, cache lines
  available); passes = ⌈bits / bits_per_pass⌉; buffer one cache line per
  partition and flush with non-temporal stores.
- **Branch-free selection:** `out[j] = i; j += (v[i] < c);` — cost flat in
  selectivity; branching code peaks at selectivity 0.5.
- **I/O model:** scan Θ(N/B), search Θ(log_B N), sort Θ((N/B)·log_{M/B}(N/B)).

## Failure modes & classic bugs

- **Pin leak** on an error path: pool fills with unevictable frames; audit
  pin counts at statement end.
- **Dirty page written ahead of its log** (custom flusher, mmap, kernel
  write-back): unrecoverable after crash; assert in the write path.
- **Concurrent miss without in-transit state:** two frames for one page, lost
  update.
- **Scan flooding** evicts the OLTP working set; use rings/probation queues.
- **Global LRU latch or page-table mutex:** flat throughput beyond a few
  cores. **Latch held across I/O:** convoys; latch-order violation: silent
  deadlock (watchdog with stack dump).
- **Connection storm:** per-connection workers without admission control
  exhaust memory and thrash the scheduler.
- **Stale plan after DDL;** **pooler breaks session semantics** (transaction
  pooling loses temp tables, SET, prepared statements, advisory locks).
- **Memory-wall symptoms:** IPC < 1 on scans, TLB storms on wide partitioning,
  false sharing on per-thread counters, remote-NUMA memory from first-touch by
  one loader thread.
- **Shared-disk** hot block ping-pong and page-lock false conflicts;
  **shared-nothing** partition skew bounding speedup.

## Implementation checklist (C/C++/Rust)

- Frame descriptor (separate cache-aligned array from page bytes): page id,
  atomic pin count, dirty bit, pageLSN, I/O-in-progress + waiters,
  replacement metadata, RW latch.
- Page table: partitioned hash or lock-free map, never one mutex; consider
  pointer swizzling for hot inner B-tree nodes.
- RAII page guard (C++) / `Drop` guard (Rust) that unpins and unlatches;
  shared vs exclusive guards as distinct types.
- Background writer + checkpointer; write a page only after
  `log.flush(pageLSN)`.
- `O_DIRECT` + async submission (io_uring/AIO), buffers aligned to device
  block size; torn-write detection (checksums, doublewrite or full-page logging).
- Work-memory broker: sort/hash grants per query, spill on shortfall, feed
  admission control.
- Fixed worker pool sized to cores, cooperative yield at I/O and lock waits,
  session object decoupled from worker, hard connection cap.
- Catalog cache with version numbers, DDL invalidation, metadata locks that
  conflict with in-flight plans.
- NUMA-partitioned pools and worker pinning; cache-line-sized index nodes,
  software prefetch, SIMD-friendly key arrays.

## How to test it

- **Model-based buffer test:** random fix/unfix/dirty/flush/crash sequences
  vs a reference map; assert invariants 1-3 after each step.
- **WAL-order oracle:** intercept page writes; fail if `pageLSN > flushedLSN`.
- **Concurrent miss:** N threads fix one cold page; exactly one I/O.
- **Scan resistance:** OLTP hit ratio during a scan of a table 10x the pool.
- **Fault injection:** EIO, short reads, torn writes, ENOSPC during flush.
- **Connection soak** at 10x expected sessions: bounded memory, graceful latency.
- **DDL race** (no stale plans) and **physical-design invariance**
  (differential results with/without each index or layout).
- **Hardware counters:** `perf stat` cache/TLB/branch misses and IPC per
  operator; a regression here is an architecture bug even if tests pass.

## Expert review questions

1. Which component owns this state, and under which latch/lock is it mutated?
2. On a miss whose victim is dirty with unflushed log, what exactly happens?
3. How is a large sequential scan kept from evicting the working set?
4. Is any latch held across I/O, a lock wait, or a network call?
5. What bounds session count, memory per session, and memory per query?
6. Does the durability path depend on the OS page cache or mmap anywhere?
7. How are cached plans invalidated on DDL and statistics refresh?
8. What breaks when a pooler multiplexes sessions per transaction?
9. Where are the LLC and TLB misses in the hottest operator; does the layout
   match the access pattern? Is the hot loop branch-predictable, NUMA-local?
10. Shared-disk or shared-nothing: what happens to one row updated 100k/s?
11. Which utilities (index build, check, backup) reuse the executor and run
    online?
12. Can a storage structure (row/column, new index type) be swapped without
    touching the SQL layer?

## Go deeper

- `references/components-and-process-models.md` — module split, process and
  thread models, admission control, connections/sessions, catalog, multitier
  transaction identity, data independence as a contract.
- `references/buffer-management.md` — pool interfaces, LRU-K/2Q/LRFU/ARC/CAR/
  clock, hot set and DBMIN, prefetch/read-ahead/write-behind, WAL coupling,
  OS VM and mmap, modern pool designs.
- `references/cache-conscious-and-main-memory.md` — hierarchy parameters,
  miss taxonomy, I/O and cache models, layouts, cache-conscious indexes and
  joins, prefetching, branches, SIMD, multicore, in-memory DBMS design.
- `references/architectures-shared-x-and-column-stores.md` — shared-memory/
  disk/nothing, database-machine history and lessons, distribution
  transparency, row vs column stores.
- `references/edbs-entries.md` — every EDBS entry in this cluster.

## Related skills

- `storage-and-indexing` (B-tree/hash mechanics), `page-and-file-format`
  (page bytes), `columnar-arrow-layout` (Arrow format) — this skill owns pool
  policy, layout *choice* and system placement around them.
- `query-plan-design`, `query-execution-advanced` — operator interfaces,
  vectorized vs compiled execution; here only cache-level principles.
- `transactions-and-recovery`, `recovery-and-durability`,
  `concurrency-control-theory` — WAL/ARIES and lock protocols; here the
  buffer-log coupling, lock manager as component, latch discipline.
- `storage-devices-and-io` (devices, five-minute rule), `tuning-and-benchmarking`
  (pool sizing, self-tuning memory), `index-structures-catalog` (CSS/CSB+ trees).
- `parallel-database-systems`, `distributed-dbms-design`,
  `parallel-distributed-execution`, `replication-protocols` — partitioning,
  parallel operators, HA beyond the shared-x choice.
- `olap-and-warehouse-engines` (column-store compression, late
  materialization), `stream-processing-engines` (multicore/GPU/FPGA streams),
  `database-security-internals` (authentication at connect, authorization in
  the parser).
- Consumers of this skeleton: `relational-theory`, `beyond-relational-engines`,
  `sql-semantics-and-active-rules`, `temporal-databases`,
  `materialized-views-ivm`, `cardinality-and-statistics`,
  `multidimensional-and-similarity-indexing`.

## Grounding

EDBS: Buffer Management (p.350), Buffer Manager (p.357), Buffer Pool (p.360),
Storage Manager (p.3736), DBMS Component / DBMS Interface (p.1005), Query
Processor (p.3058), Process Structure of a DBMS (p.2867), Staged DBMS
(p.3696), Connection (p.581), Session (p.3484), Client-Server Architecture
(p.439), Multitier Architecture (p.2443), Data Dictionary (p.749),
Transaction Manager (p.4194), Logical and Physical Data Independence
(p.2136), Architecture-Conscious Database System (p.155), Cache-Conscious
Query Processing (p.389), Memory Hierarchy (p.2222), Processor Cache
(p.2887), Main Memory DBMS (p.2164), I/O Model of Computation (p.1741),
Column Stores (p.518), Shared-Memory/-Disk/-Nothing (pp.3484-3486), Database
Machine (p.956), Distributed Architecture (p.1152); full list in
`references/edbs-entries.md`. Papers: Hellerstein, Stonebraker & Hamilton
(FnT DB 2007); Effelsberg & Härder (TODS 1984); Sacco & Schkolnick (TODS
1986); Chou & DeWitt (VLDB 1985); O'Neil et al. LRU-K (SIGMOD 1993); Johnson &
Shasha 2Q (VLDB 1994); Megiddo & Modha ARC (FAST 2003); Stonebraker (CACM
1981); Ailamaki et al. (VLDB 1999, 2001); Boncz et al. (VLDB 1999);
Harizopoulos & Ailamaki (CIDR 2003); DeWitt & Gray (CACM 1992); Aggarwal &
Vitter (CACM 1988).
