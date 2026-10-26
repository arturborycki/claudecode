# Buffer management in depth

The buffer manager caches disk pages in memory frames, makes them
addressable by pointer while pinned, and decides what to keep, what to
prefetch and when to write. It is simultaneously a **performance component**
(fault rate) and a **correctness component** (write ordering for recovery,
pinning for in-place access). Read this when implementing, tuning or
reviewing a buffer pool.

## 1. Why the DBMS owns its cache

EDBS (Sacco; Graefe) and Stonebraker (CACM 1981) give the classic reasons
for not using OS virtual memory or the file-system cache:

| Concern | OS VM / FS cache | DBMS buffer pool |
|---|---|---|
| Write ordering for WAL | kernel may write any dirty page at any time | page written only after its log is durable |
| Write-through / write-behind control | kernel policy | DBMS decides, coordinated with checkpoints |
| Read-ahead / prefetch | heuristic, file-offset based | driven by the plan (exact page lists, index leaf order) |
| Replacement knowledge | sees only an address trace | knows the operator and its reference string |
| Pinning | none (any page can be evicted) | pinned pages cannot move, so records are accessed in place |
| Sharing | little sharing across processes | heavy sharing of pages among sessions |
| Page table | sized to the address space | inverted table sized to the pool |
| Frequency of interaction | per memory access (hardware) | per page request (software) — so "smart" policies like LRU are affordable |

Two more rules:
- **No double paging:** the pool itself must not be paged by the OS
  (otherwise a "hit" can fault). One historical remedy: shrink/grow the pool in
  response to OS paging rates; today: lock or size memory explicitly, use huge
  pages, and avoid overcommit.
- **No double caching:** with buffered file I/O every page lives twice (pool +
  kernel cache). Use direct I/O, or accept it knowingly (PostgreSQL
  historically relied on the kernel cache as a second-level cache).

> **Beyond EDBS: mmap.** Crotty, Leis & Pavlo (CIDR 2022, "Are You Sure You
> Want to Use MMAP in Your Database Management System?") catalogue why
> mmap-based engines get into trouble: (1) transactional safety — the kernel
> can write back a dirty mapped page before its log record, so engines need
> shadow copies (`MAP_PRIVATE` copy-on-write, user-space copies, or shadow
> paging as in LMDB) — `mlock` keeps pages resident but does not stop
> write-back; (2) I/O stalls — a page fault blocks the
> thread synchronously, no async prefetch control; (3) error handling — I/O
> errors arrive as `SIGBUS` at arbitrary instructions; (4) performance — page
> table contention, single-threaded kernel eviction, and TLB shootdowns on
> eviction limit scalability with fast NVMe. Several systems (MongoDB's
> MMAPv1, InfluxDB, SingleStore) moved away from mmap.

## 2. Interface contract

From EDBS *Buffer Manager* (Graefe), the methods a pool must provide:

```
fix(page_id, latch_mode ∈ {none, S, X}, intent) -> FrameRef   // a.k.a. pin
unfix(FrameRef, dirtied: bool, new_pageLSN?)                  // unpin (+ unlatch)
fix_new(page_id)        // just allocated: no read from disk
discard(page_id)        // just deallocated: never write back
force(page_id)          // synchronous write (non-logged ops, careful writes)
order(before=A, after=B)// retain/hold B until A has been written
hint_prefetch(list<page_id>), hint_readahead(range), hint_writebehind(page_id)
alloc_memory(bytes) / free_memory   // if the pool also serves other layers
```
and the primitives it needs below: synchronous and **asynchronous** read and
write, scheduling primitives for latches, memory allocation if the pool is
resizable, and fast page copy if multiple page sizes are supported.

Pinning protects a page from **replacement and from relocation**, which is
what lets operators hold raw pointers into frames. Latching (usually a
parameter of `fix`) protects page *contents* among threads. **Transaction
concurrency control is not the pool's job** (except when MVCC keeps page
versions in the pool).

## 3. Frames, descriptors and states

```
 page table (hash, partitioned)          descriptor array (cache-aligned)      frames
 ┌─────────┬──────────┐                 ┌───────────────────────────────┐   ┌──────┐
 │ page id │ frame #  │───────────────▶ │ page_id  pin_cnt  dirty       │──▶│ 8 KB │
 └─────────┴──────────┘                 │ pageLSN  io_state  waiters    │   └──────┘
                                        │ latch    repl_meta (ref bit,  │
                                        │          usage, K-history)    │
                                        └───────────────────────────────┘
```
Frame states: free; resident clean/dirty; **pinned** (count); **latched**
(S/X); **in transit** (read or write in progress). A miss must publish the
in-transit state in the page table *before* releasing the partition latch,
so concurrent requesters wait on it instead of reading the page again.

Multiple versions of one page may coexist in the pool for:
transaction isolation (versioned pages), compression (compressed +
uncompressed image), **write-behind** (copy-then-write so updates can continue
during the I/O; a single copy blocks updaters until the write completes; the
copy step can also compact free space between variable-length records), and
protection against partial (torn) writes.

Variable page sizes (multiples of a base size, typically powers of two) make
space management hard; a common commercial approach is **one pool per page
size**, each with fixed-size frames.

### fix() pseudo-code

```
fix(pid, mode):
  part = page_table.partition(pid); part.latch_S()
  if (f = part.lookup(pid)):
      f.pin++ ; part.unlatch()
      if f.io_state == READING: wait(f.io_done)
      touch_replacement(f)                 // must be cheap & mostly latch-free
      f.latch(mode); return f
  part.upgrade_X()                         // or re-lookup after X
  if (f = part.lookup(pid)): goto hit      // lost the race
  v = choose_victim()                      // skips pin>0, io_state!=NONE
  if v.dirty:
      log.flush_up_to(v.pageLSN)           // WAL rule
      write(v)                             // or take a clean victim instead
  part.remove(v.pid); part.insert(pid, v)
  v.pid = pid; v.pin = 1; v.io_state = READING
  part.unlatch()                           // never hold across I/O
  read(pid, v.data); verify_checksum(v)
  v.io_state = NONE; signal(v.io_done)
  v.latch(mode); return v
```
Production refinements: keep a free list replenished by a background writer
so foreground misses rarely write; handle the victim's own page-table
partition (ordered latching across two partitions, or a two-step remove).

## 4. Replacement policies

### 4.1 The two schools (EDBS *Buffer Management*, Sacco)

- **VM approach** — the pool is a black box with a smart replacement policy
  learned from the reference trace (LRU, CLOCK, GCLOCK, LRD, LRU-K, 2Q,
  LRFU, ARC). General, handles page sharing naturally, but scans and loops
  defeat it.
- **Predictive approach** — the optimizer knows each plan's reference pattern
  (scan, nested loop, index probe) before execution, so buffer needs and the
  best policy per pattern can be computed (hot set model, QLSM/DBMIN, OLRU).
  Accurate for queries in isolation; needs run-time correction for sharing.

The two are dual: VM handles sharing and fails on simple/loop reuse; the
predictive approach detects scans and loop sizes trivially but must be
corrected for sharing. Combine them: VM-style policy as the default, plan
hints for scans, loops and index levels.

### 4.2 Recency and frequency policies

**LRU.** Doubly linked list; pin removes from list, unpin inserts at MRU head;
victim = tail. Weakness: no frequency notion — a page touched once stays for
at least B−1 further faults (B = frames), so many frames hold one-shot pages.
Also a global list latch on every hit.

**CLOCK / second chance.** Frames in a circle with a reference bit; hit sets
the bit; the hand clears set bits and evicts the first clear, unpinned frame.
**GCLOCK** replaces the bit by a counter (incremented on hit, decremented by
the hand), giving a frequency flavour. Hits are a single store — the reason
CLOCK variants dominate highly concurrent engines.

**LFU.** Evict least frequently used; does not age, so formerly hot pages
squat forever.

**LRU-K** (O'Neil, O'Neil & Weikum, SIGMOD 1993). Track the times of the last
K references of each page. Backward K-distance `b_t(p,K)` = time since the
K-th most recent reference (∞ if fewer than K references). Evict the page with
the **largest** `b_t(p,K)`; LRU-1 = LRU. Larger K estimates inter-reference
time better but reacts slower and costs more state; **K = 2 is the practical
choice**. Two parameters matter:
- *Correlated reference period* — references within a short window after
  admission (e.g. reading all tuples of a page during a scan, or
  read-then-update by one transaction) count as one; a freshly admitted page is
  protected during that window. Correct length is workload-dependent and
  hard to set.
- *Retained information period* — keep history for evicted pages so a quick
  re-reference is recognised as the second reference.

**2Q** (Johnson & Shasha, VLDB 1994) — constant-time approximation of LRU-2:
```
A1in : FIFO of resident pages seen once (probation)
A1out: FIFO of page ids (no frames) recently evicted from A1in  ("ghosts")
Am   : LRU of resident pages re-referenced
on access(p):
  if p in Am:   move p to Am head
  elif p in A1in: (correlated re-reference) do nothing
  elif p in A1out: reclaim frame; insert p at Am head
  else:         reclaim frame; insert p at A1in head
reclaim: if |A1in| > Kin: evict A1in tail, push its id onto A1out (trim to Kout)
         else evict Am tail
```
A one-pass scan only ever cycles through A1in, so the Am working set
survives.

**LRFU** (Lee et al., SIGMETRICS 1999) — a continuum between LRU and LFU.
Each page has a Combined Recency and Frequency value
`CRF(p) = Σ_i F(now − t_i)` with `F(x) = (1/2)^(λx)`, `0 ≤ λ ≤ 1`; evict min
CRF. `λ = 0` → LFU, `λ = 1` → LRU. Updatable incrementally:
`CRF_new = F(0) + F(Δt)·CRF_old`. λ can be self-tuned; it was reported to beat
LRU-K at small buffer sizes.

**ARC / CAR** (Megiddo & Modha FAST 2003; Bansal & Modha FAST 2004, cited in
EDBS). Lists T1 (seen once recently), T2 (seen at least twice), ghost lists B1,
B2, adaptive target `p` for |T1|. Hit in ghost B1 → grow p (favour recency);
hit in B2 → shrink p (favour frequency). Scan-resistant, self-tuning. CAR is
its CLOCK-based variant (cheap hits).

> **Beyond EDBS (production policies):**
> - PostgreSQL used ARC in 8.0, replaced it (patent concerns) with 2Q in 8.0.x
>   and then **clock-sweep** in 8.1: per-buffer `usage_count` capped at 5,
>   incremented on pin, decremented by the sweeping hand; and **ring buffers**
>   (`BufferAccessStrategy`) so large sequential scans, VACUUM and bulk writes
>   recycle a small private ring instead of polluting shared buffers.
> - InnoDB uses **midpoint insertion LRU**: new pages enter the head of the
>   "old" sublist (~3/8 of the list by default); they are promoted to the
>   "young" part only if touched again after `innodb_old_blocks_time` (1 s
>   default) — a correlated-reference period in all but name.
> - LeanStore (Leis et al., ICDE 2018) replaces per-hit bookkeeping entirely:
>   **pointer swizzling** makes hits plain pointer dereferences; eviction
>   picks random swizzled pages, unswizzles them into a FIFO "cooling" stage,
>   and evicts from the cooling tail unless re-accessed.

### 4.3 The scan problem

During a sequential scan the current page is touched many times in quick
succession (once per tuple) and then never again. Recency-based policies read
those bursts as reuse and keep the page, flushing other workloads' hot pages
(Sacco & Schkolnick). Remedies, in increasing reliance on the plan:
1. Count correlated references once (LRU-K correlated period, 2Q A1in,
   InnoDB old-blocks time).
2. Insert scan pages at the LRU end or a midpoint instead of the MRU end.
3. Private ring buffers for scans larger than a fraction of the pool.
4. Explicit hints: **love/hate** or **keep/toss** flags from the executor
   (catalog pages and B-tree roots = love/keep; scan pages = hate/toss).
5. Shared/cooperative scans (see `components-and-process-models.md` §8) so
   concurrent scans consume each page once.

### 4.4 The predictive approach: hot sets and locality sets

**Hot set model** (Sacco & Schkolnick, VLDB 1982, TODS 1986). Given a plan and
a policy, the fault count as a function of buffer size is predictable and,
unlike VM fault curves, **discontinuous**. Example: tuple-wise nested loops,
outer R (40 pages), inner S (30 pages). With LRU:
- below `1 + pages(S)` frames there is no reuse at all — the fault count is
  the same as with one frame: `|R| · (1 + pages(S))`-ish (one inner scan per
  outer tuple);
- at `1 + pages(S)` frames the inner stays resident:
  faults = `pages(R) + pages(S)`.
These breakpoints are **hot points**; the **hot set size** of a plan is the
largest hot point not exceeding the available buffer. The loop length is
known exactly at the DBMS level but practically undiscoverable by a VM.

Reuse types:
| Type | Pattern | Hot points | Best policy |
|---|---|---|---|
| Simple reuse | sequential scan (page touched for all its tuples, then never) | one, at 1 frame | anything; LRU gives nothing |
| Loop reuse | repeated scan of an inner (NLJ inner, rescans) | one per loop | **MRU** (= OPT for a cyclic loop) |
| Index reuse | clustered/unclustered index probes, shared index | depends on fan-out; unclustered data pages estimated with Yao's function | level-based fixing (OLRU) / LRU |

**Optimal policies under IRM.** Under the Independent Reference Model
(stationary, known per-page reaccess probabilities) the optimal B-frame policy
fixes the B−1 most probable pages and cycles the rest through one frame.
- Loops: all pages equally likely → fix any B−1 loop pages; fixing the first
  B−1 is exactly MRU, which is also Belady's OPT for that string.
- B+-trees of order m with uniform leaf access: probability of reaccessing a
  level-j page ∝ `1/m^j` → **allocate by level** (pin root, then level 1, …).
  LRU allocates by traversal paths and is suboptimal unless access is very
  skewed. This is **OLRU** (Sacco VLDB 1987); LRU-K can be viewed as a
  run-time approximation of OLRU because it also assumes IRM.

**QLSM / DBMIN** (Chou & DeWitt, VLDB 1985). Determine a *locality set* per
file instance opened by a query (not per primitive), each with its own size and
local policy: NLJ R⋈S with S inner = simple reuse on R (1 frame, any policy) +
loop reuse on S (1..pages(S) frames, MRU). Global admission: a query runs only
if its locality sets fit.

**OPT is not the end.** Belady's OPT minimises faults *for a given reference
string*; a different algorithm generates a different string. Kim's nested
scans beat nested loops even when nested loops get OPT at small buffers. When
the largest hot point exceeds memory, **change the algorithm to increase
locality**: sort, semijoin, or partition (Sacco's *fragmentation* = recursive
hash partitioning until the smaller fragment fits in B−1 frames; with K join
values spread over N partitions each holds ≈ K/N values).

Why optimizers need this: cost curves of alternatives **cross** as memory
varies (in the example, R-inner is cheaper up to 30 frames, S-inner from 31),
and plans that do not manage memory explicitly (nested loops) must be
compared with plans that do (hash partitioning) on a common, buffer-aware
cost basis.

### 4.5 Thrashing and buffer-aware scheduling

Thrashing: active queries' combined needs exceed the pool, they steal each
other's pages, and throughput collapses. VM fixes (monitor the paging device,
working-set estimation) do not transfer: there is no single paging device and
working-set tracking is too expensive per reference. Predictive fixes:
- **Hot-set scheduling:** admit queries while Σ hot-set sizes ≤ pool; each runs
  in its own partition — thrash-free by construction. Corrections: a global
  LRU chain of free/shared pages and a scan for pages already resident for
  another query (a shared page needs one frame, not two); a buffer-consumption
  measure so small queries do not queue behind inflated hot sets.
- **DBMIN:** per-locality-set policies plus the same admission rule.
- **Marginal gains** (Ng, Faloutsos & Sellis, SIGMOD 1991): allocate frames
  where the marginal fault reduction per frame is highest.
- Prefetch-aware scheduling (Cai et al.).

Modern equivalent: memory-grant admission control for sort/hash work areas
(see `components-and-process-models.md` §7), and buffer-pool-aware
optimization (Ramamurthy & DeWitt, CIDR 2005: cost plans by which pages are
already resident).

## 5. Dirty pages and asynchronous I/O

**Retention bias for dirty pages.** Replacing a dirty page costs a write plus a
read (twice a clean one) and may be blocked by write-ordering constraints, so
policies may keep dirty pages longer. Conversely, **non-logged operations**
(minimally logged index build, bulk load) must flush their dirty pages at
commit.

Three forms of async I/O (EDBS *Buffer Manager*):

| Form | Purpose | Trigger | Sizing / notes |
|---|---|---|---|
| **Write-behind** | clean dirty pages so (a) updates finish fast and (b) replacement rarely needs a write before a read | mostly checkpoints (intervals of minutes) and retention calculated from the five-minute rule (minutes to hours), not individual faults | piggyback on seeks forced by other I/O; or relocate data (log-structured file systems, write-optimized indexes) |
| **Read-ahead** | large scans (B-tree range scans, heap scans) | observed sequential pattern or plan hint (table scan) | depth = min(I/O bandwidth, processing bandwidth) × latency from issue to completion |
| **Prefetch** | load exactly the pages holding needed records | RID lists from indexes, sorted RID fetch | in B-trees, prefetch all levels or only leaves (interior via sync reads/large read-ahead); also speeds rollback and restart recovery |

Worked sizing: NVMe at 3 GB/s, 100 µs average completion latency, consumer
at 2 GB/s → `min(3, 2) GB/s × 100 µs = 200 KB` in flight ≈ 25 pages of 8 KB;
add headroom for latency variance (×2–4).

## 6. Coupling with recovery

| Policy | Meaning | Logging consequence |
|---|---|---|
| **No-steal** | uncommitted changes never written to the database | no undo information in the persistent log, but the pool must hold every page of every active transaction |
| **Steal** | uncommitted dirty pages may be evicted | undo log records must be durable before the page write (WAL) |
| **Force** | all pages of a transaction written at commit | no redo needed for committed work; slow commits; used for minimally logged index creation |
| **No-force** | only log forced at commit | redo needed; fast commits |

Most engines run **steal / no-force** by default (needs undo + redo, see
`recovery-and-durability`). Pool obligations:
- WAL check on every page write: `log.flushedLSN ≥ frame.pageLSN`.
- Track `recLSN` (first LSN that dirtied the frame since its last write) for
  the dirty page table and checkpointing.
- **Write ordering instead of logging:** on a B-tree split the records moved to
  the new page need not be logged if the new page is written *before* the
  modified old page — hence the `order(before, after)` interface. Similar
  careful-write tricks appear in shadow paging and in allocation maps.
- **Checkpoints:** record active transactions and either write or log all
  dirty pages (or, in fuzzy checkpoints, record the dirty page table and let
  the background writer progress). Continuous write-behind flattens the
  checkpoint I/O spike.
- Torn pages: checksums plus a repair source (full-page image in the log after
  each checkpoint, or a doublewrite area as in InnoDB).

## 7. Concurrency inside the pool

The pool's own metadata (lookup table, replacement structures, descriptors)
must sustain very high concurrency on many-core CPUs (EDBS foresaw hardware
transactional memory as one aid).
- Partition the page table (PostgreSQL: 128 buffer-mapping partitions) or
  use a lock-free hash; multiple pool instances (InnoDB) shard everything.
- Make hits cheap: CLOCK bits/counters, sampled or batched LRU updates; never
  take a global list latch per hit.
- Separate pin (atomic counter, prevents eviction) from latch (RW lock on
  contents). Optimistic/versioned latches let readers proceed without
  writing shared cache lines and validate afterwards (LeanStore, optimistic
  lock coupling — Leis et al., DaMoN 2016).
- Keep descriptors in their own cache-line-aligned array; avoid false sharing
  between the pin count and frequently read fields.

## 8. Memory beyond page caching

- **Memory stealing:** the pool may lend frames to sort and hash join, to
  utilities (reorganization, consistency checks), and act as the general
  memory allocator. Then admission control must account for both.
- **Self-tuning memory:** DB2's STMM (Storm et al., VLDB 2006) moves memory
  among pools and heaps by cost-benefit; generalization of marginal gains.
- **Pool-resident structures:** with very large pools, temporary indexes on
  permanent tables could live only in the pool, built as a side effect of
  query execution and dropped under pressure (Graefe's suggestion; also partial
  indexes).
- **Compression and co-location** raise effective pool size: compressed
  frames, master-detail clustering so related records share a frame.

## 9. Cooperative and multi-level pools

- **Client-server:** pools form a hierarchy (client cache over server pool);
  coherence plus callback locks.
- **Shared-disk:** pools are peers; every node can cache any page, so a
  global lock/ownership protocol keeps them coherent (Oracle RAC's Cache
  Fusion ships current blocks over the interconnect instead of via disk).
  Optimize both data traffic and control messages.
- **Deep hierarchies** (RAM / flash / disk, or local NVMe over remote object
  storage): replacement techniques apply at every level; content descriptors
  of a persistent flash cache must themselves be persistent, while the
  replacement metadata can stay in RAM. A fast device can cache a slow one, or
  both can be permanent with policy-driven page migration (tiering).

**Five-minute rule** (Gray & Putzolu, SIGMOD 1987) for sizing which pages to
keep in RAM:
```
break-even reference interval (s) =
   (pages per MB of RAM / accesses per second per disk)
 × (price per disk drive / price per MB of RAM)
```
Pages referenced more often than this interval should stay cached. Graefe
(DaMoN 2007) re-derived it with flash as a middle tier; `storage-devices-and-io`
has current numbers.

> **Beyond EDBS:** Umbra (Neumann & Freitag, CIDR 2020) supports
> variable-size pages (size classes) by reserving virtual address ranges per
> class and releasing physical memory with `madvise`, keeping pointer
> swizzling. vmcache (Leis et al., SIGMOD 2023) uses an anonymous virtual
> memory region the size of the database with explicit page-state words and
> DBMS-controlled eviction, getting mmap-like translation without giving
> eviction control to the kernel.

## 10. Test and review checklist

- Model test: random sequences of fix/unfix/dirty/force/discard/crash vs a
  reference; check pin counts, single-frame-per-page, contents equality.
- WAL oracle on every write; `order(A,B)` honoured under crash injection.
- Concurrency: many threads missing on the same page → exactly one read;
  victim selection races with re-fix of the victim.
- Scan resistance: hit ratio of a skewed OLTP workload while a scan of 10×
  pool size runs; repeat with loop-reuse patterns (inner relation slightly
  larger than its share).
- Hint plumbing: are scan/keep/toss hints actually passed from the executor?
- Read-ahead depth vs device: throughput curve flat at the device limit.
- Checkpoint behaviour: dirty-page count over time, absence of write storms.
- Review: Who may write pages (writer, checkpointer, evicting foreground)?
  What happens when the log device stalls? How large can the pinned set get
  (long scans, cursors held open)? Can a query's memory grant starve the page
  cache?

Sources: EDBS *Buffer Management* (p.350), *Buffer Manager* (p.357), *Buffer
Pool* (p.360), *Storage Manager* (p.3736), *I/O Model of Computation*
(p.1741), *Memory Hierarchy* (p.2222), *Shared-Disk Architecture* (p.3484),
*Client-Server Architecture* (p.439), *Architecture-Conscious Database
System* (p.155).
