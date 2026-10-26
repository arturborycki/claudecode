# Cache-conscious and main-memory engine design

Once the working set is in RAM, the bottleneck moves from disk I/O to the
CPU's memory hierarchy and pipeline. This file gives the hardware model, the
cost models (I/O model and its cache generalization), the catalogue of
cache-conscious techniques, microarchitectural hazards (branches, SIMD,
multicore), and main-memory DBMS design. Read it when an operator is
CPU/memory-bound, when designing in-memory data structures, or when building
an in-memory engine.

## 1. Why it matters

- Between 1980 and 2005 CPU speed rose by roughly four orders of magnitude,
  DRAM latency by less than one; a DRAM access costs hundreds of cycles (the
  **memory wall**). Up to a third of instructions in typical programs are
  memory accesses.
- Ailamaki et al. (VLDB 1999) used hardware counters on four commercial
  DBMSs and found a large share of execution time in stalls, dominated by **L2
  data misses** and **L1 instruction misses** — i.e. both data layout and code
  footprint matter. Boncz, Manegold & Kersten (VLDB 1999) reported memory
  access dominating query time for in-memory workloads.
- System R already modelled hardware (I/O counts in its cost model);
  "architecture-conscious" design is the same discipline applied to caches,
  TLBs, branch predictors, SIMD units and many cores.

## 2. Hardware model

### 2.1 Levels and parameters
```
registers → L1d/L1i (per core) → L2 (per core or per pair) → L3/LLC (shared) → local DRAM → remote DRAM (NUMA) → SSD/disk
```
Each cache level i is described by (EDBS *Memory Hierarchy*, Manegold):

| Symbol | Meaning |
|---|---|
| `C_i` | capacity (bytes) |
| `Z_i` | line (block) size — unit of transfer to the next level; 64 B on x86-64, 128 B on some ARM cores |
| `#_i = C_i / Z_i` | number of lines |
| `A_i` | associativity: 1 = direct-mapped, `#_i` = fully associative, typically 4–16-way |
| `l_i^s`, `l_i^r` | miss latency for sequential / random access |
| `b_i^s`, `b_i^r` | miss bandwidth; `l_i = Z_i / b_i` |

- L1 is split into instruction (read-only) and data caches; lower levels are
  unified.
- **Inclusive** hierarchy: every line in L1 is also in L2 (evicting from L1 is
  free; total capacity = largest level). **Exclusive**: a line lives in exactly
  one level (capacity adds up, but misses swap lines between levels, costing
  bus traffic).
- SRAM caches use ~6 transistors per bit; DRAM uses one transistor + capacitor
  and needs refresh — hence dense, cheap, slow.

### 2.2 The four kinds of misses (Hill & Smith)
| Miss | Definition (diagnostic) | Remedy |
|---|---|---|
| Compulsory | first touch of a line; would miss in an infinite cache | fewer bytes touched (compression, columns), prefetch |
| Capacity | misses in a fully associative cache of the same size | blocking/partitioning to fit, better temporal locality |
| Conflict | hits in fully associative, misses in A-way | change addresses: padding, cache coloring, avoid power-of-two strides |
| Coherence | another core wrote the line (private caches) | partition writes per core, avoid false sharing, batch shared updates |

### 2.3 Latency, bandwidth, translation
- Total latency of a miss in every cache = `λ_Mem + λ_L2 + λ_L1`; L1 hits are
  usually folded into CPU cost.
- **Sequential vs random:** DRAM bursts and hardware prefetchers make
  sequential access far cheaper per line than random access. EDBS's example:
  without prefetch, bandwidth ≈ line size / latency = 64 B / 50 ns ≈ 1.3 GB/s;
  hardware prefetching on sequential scans reached about 4× that on 2008-era
  machines. Exploiting excess bandwidth needs **non-blocking caches** and
  multiple outstanding misses (memory-level parallelism).
- **TLB:** caches virtual→physical page translations; few entries (EDBS: ~64
  for 4 KB pages, so touching more than ~64 pages in quick succession thrashes
  it). TLB reach = entries × page size. A miss costs a page-table walk (or an
  OS trap if software-managed — up to 10× worse) and may itself miss in the
  caches. Treat the TLB as a fully associative cache with line size = page
  size; no sequential/random distinction. Remedy: huge pages (2 MB/1 GB on
  x86-64), fewer simultaneously active regions.
- **NUMA:** memory attached to another socket is slower; on-die memory
  controllers and per-socket memory buses made this the norm in SMPs.

### 2.4 Unified cost model
Manegold's generic model: memory time of an algorithm =
`T_mem = Σ_i ( M_i^s · l_i^s + M_i^r · l_i^r )`, where `M_i^{s,r}` are the
numbers of sequential/random misses at level i (TLB included as a level),
derived per access pattern (sequential traversal, random traversal, repeated
traversal, interleaved patterns). Parameters come from a calibration tool
(Manegold's *Calibrator*) when the OS does not expose them — a DBMS can run
such calibration at install time.

> **Beyond EDBS (order of magnitude on current x86 servers; measure yours):**
> L1 ~4–5 cycles, L2 ~12–16 cycles, LLC ~40–70 cycles, local DRAM ~80–100 ns,
> remote socket roughly 1.5–2× local.

## 3. Locality, the I/O model and its generalizations

**Locality** (Denning): programs reference a small, slowly changing subset —
**temporal** (re-reference soon) and **spatial** (neighbours referenced
together). Transfers between levels happen in blocks (pages, lines), so spatial
locality decides how much of each transfer is useful and temporal locality
decides how often it must be repeated. Database examples: partitioned joins
(temporal reuse of a small inner partition), clustered indexes, PAX, and the
row-store vs column-store choice for row-major (OLTP) vs column-major (OLAP)
access.

**I/O model of computation** (EDBS; Aggarwal & Vitter, CACM 1988): count
block transfers between a memory of size M and an unbounded disk with block
size B, ignore CPU. Disk access = seek + rotational delay + transfer, with
seek > rotation > transfer, so reading a few bytes costs about as much as
reading a block, and random I/O ≫ sequential. Three ways to cut I/O: buffer
pages already read; transfer runs of consecutive pages (read-ahead
"buckets"); use paginated (external) structures. Classic numbers: a binary
search tree on 10^6 records needs ≈20 I/Os, a B+-tree with 100 entries per
node needs 3.

| Problem | I/O complexity |
|---|---|
| Scan N items | Θ(N/B) |
| Search (B-tree) | Θ(log_B N) |
| Sort / permute (comparison) | Θ((N/B) · log_{M/B}(N/B)) |

The same model applies one level up with M = cache size and B = line size —
which is why "make nodes a line wide" and "partition to fit the cache" are the
same ideas as "make nodes a page wide" and "partition to fit memory".

- **Cache-oblivious** algorithms (Frigo et al., FOCS 1999) achieve the I/O
  bound at every level without knowing M or B (recursive divide and conquer,
  van Emde Boas layouts).
- **Cache-adaptive** algorithms (Bender et al., SODA 2014) stay efficient when
  the available cache changes during execution — relevant when co-running
  queries share the LLC.

## 4. Technique catalogue

Ross's taxonomy (EDBS *Cache-Conscious Query Processing*): improve spatial
locality; improve data temporal locality; improve instruction temporal
locality; hide latency; avoid cache pollution; avoid TLB thrashing; sample
the data to choose an algorithm.

### 4.1 Spatial locality: layouts and indexes
- **NSM / DSM / PAX.** If a query touches few columns, column-wise storage
  makes every fetched line useful; NSM lines carry unneeded columns. PAX
  (Ailamaki et al., VLDB 2001) keeps NSM's page contents and I/O but groups
  each attribute into a *minipage* inside the page — cache behaviour close to
  DSM with minimal engine change. Column systems: Sybase IQ, MonetDB, C-Store
  (see `architectures-shared-x-and-column-stores.md`).
- **Cache-conscious structure layout** (Chilimbi, Hill & Larus, PLDI 1999):
  put several levels of a binary tree in one line; **cache coloring** maps hot
  items to address ranges that cannot conflict.
- **CSS-trees** (Rao & Ross, VLDB 1999): pointer-free, line-sized,
  line-aligned nodes stored in an array; children found by arithmetic. Great
  for read-only decision support.
- **CSB+-trees** (Rao & Ross, SIGMOD 2000): one child pointer per node, all
  children of a node contiguous; nearly CSS-tree cache efficiency with
  reasonable update cost.
```
CSB+ node:  [nkeys | k1 k2 ... kn | first_child_ptr]   children: [c0][c1]...[cn] contiguous
child i = first_child_ptr + i * node_size
```
- **Key compression / prefix truncation** in B+-tree nodes raises fan-out per
  line (Graefe & Larson, ICDE 2001).
- **Wider nodes via prefetch:** if the memory system sustains n outstanding
  misses, an n-line node costs barely more than one line, so the optimal
  in-memory node is several lines wide (pB+-trees, Chen, Gibbons & Mowry,
  SIGMOD 2001). Fractal prefetching B+-trees (SIGMOD 2002) embed cache-sized
  subtrees inside disk pages to be good at both levels.

### 4.2 Temporal locality: blocking, buffering, partitioning
- **Blocking:** process cache-sized units, combine later. AlphaSort (Nyberg et
  al., VLDB J 1995): quicksort cache-sized runs, then merge. Block-oriented
  operator interfaces (Padmanabhan et al., ICDE 2001) pass batches between
  operators instead of single tuples.
- **Buffering index probes** (Zhou & Ross, VLDB 2003): push a batch of lookups
  through the tree one level at a time via per-node buffers, so each node is
  loaded once per batch instead of once per probe.
- **Buffering for the instruction cache** (Zhou & Ross, SIGMOD 2004): insert
  buffer operators so a group of operators whose combined code exceeds L1i is
  executed in phases, each over many tuples; the i-cache savings exceed the
  buffer copy cost.
- **Partitioning** (dual of blocking): split inputs into cache-sized pieces and
  process each — partitioned hash join (Shatdal, Kant & Naughton, VLDB 1994),
  radix join (Boncz et al. 1999; Manegold et al. 2000/2002).

### 4.3 Hiding latency
- Hardware prefetchers catch fixed strides; software prefetch instructions
  cover irregular but computable addresses (hash buckets, tree children).
- **Group prefetching / software-pipelined prefetching** for hash joins
  (Chen, Ailamaki, Gibbons & Mowry, ICDE 2004; TODS 2007): split per-tuple work
  into stages separated by a memory access, and interleave stages of many
  tuples so prefetches for tuple j overlap work on tuple j−d.
```
// group prefetching, G tuples per group
for g in groups:
  for t in g: h[t] = hash(key[t]); prefetch(&bucket[h[t]])
  for t in g: b = bucket[h[t]]; prefetch(b.first_node)
  for t in g: probe(b.first_node, key[t])
```
- **Helper threads** on SMT cores: one hardware thread only prefetches into the
  shared cache using a *work-ahead set* of (address, stage) entries, the other
  computes (Zhou et al., VLDB 2005).

> **Beyond EDBS:** later generalizations interleave many independent lookups
> without hand-written stages — asynchronous memory access chaining (AMAC,
> Kocberber et al., VLDB 2015) and coroutine-based interleaving (Psaropoulos et
> al., VLDB 2017).

### 4.4 Avoiding pollution and TLB thrashing
Partitioning itself can thrash: with fan-out F, every output partition is an
active page (TLB entry) and an active line. Remedies:
- Bound **fan-out per pass** by TLB entries and available lines; use multiple
  passes for more partitions (radix clustering on `bits` in
  `⌈bits / bits_per_pass⌉` passes).
- **Software write-combining:** keep one line-sized buffer per partition in
  cache; when full, flush the whole line to its partition with **non-temporal
  (streaming) stores**, which bypass caches and avoid read-for-ownership;
  TLB misses are amortized over a line of tuples (Wassenberg & Sanders,
  Euro-Par 2011; also Balkesen et al., ICDE 2013).
- In-place partitioning can also be cache-efficient (Polychroniou & Ross,
  SIGMOD 2014).
- Use non-temporal loads/stores for data that will not be reused soon.

Worked example: 64-entry L1 dTLB, 512 lines of L1d. Target 2^14 partitions
with ≤ 2^6 fan-out per pass → 3 passes (6 + 6 + 2 bits). With huge pages and
write-combining buffers, one pass of 2^9–2^11 often wins; calibrate rather
than guess.

### 4.5 Sampling to choose the algorithm
**Inspector joins** (Chen et al., VLDB 2005) collect statistics during the
partitioning pass and use them to drive a cache-optimized join of each
partition. **Adaptive aggregation** (Cieslewicz & Ross, VLDB 2007) samples the
input to estimate group-by locality and chooses among shared table,
per-thread tables, or partitioning.

## 5. Microarchitectural hazards

### 5.1 Branch misprediction
A conditional branch is a control dependency; deep pipelines must guess its
outcome; a wrong guess flushes the pipeline (penalty ∝ depth). Data-dependent
branches in selections, joins and comparisons are unpredictable when outcomes
are random. For a selection over uniform data, mispredictions peak at
selectivity 0.5. Convert control to data dependency:
```c
// branching: cost depends on selectivity, worst at 50%
for (i = 0; i < n; i++) if (v[i] < c) out[j++] = i;
// predicated: constant work per element
for (i = 0; i < n; i++) { out[j] = i; j += (v[i] < c); }
```
Ross (TODS 2004) added branch-misprediction cost to the optimizer's cost
model and showed that for conjunctions the best plan mixes `&&` (branch,
short-circuit) and `&` (no branch) per predicate depending on selectivities.

### 5.2 SIMD
Wide registers apply one instruction to several values (a 128-bit register
holds four 32-bit ints; AVX2/AVX-512 hold 8/16). Zhou & Ross (SIGMOD 2002)
SIMD-ized scans, aggregation, index search and joins. SIMD also removes
branches: a vector compare yields a mask; selection is mask → compress/
shuffle → store. Architectures built around SIMD (Cell BE) made SIMD-ization
mandatory (Héman et al., DaMoN 2007).

### 5.3 Instruction footprint
Generic interpreters (per-tuple virtual calls, type dispatch per value) blow
the L1i and the branch predictor. Remedies: process vectors per call
(amortize dispatch), buffer operator groups (§4.2), or generate specialized
code. The iterator model's per-tuple overhead on modern CPUs is the EDBS
*Query Processor* entry's critique, citing MonetDB/X100 ("a DBMS in the CPU
cache").

> **Beyond EDBS:** vectorized engines size vectors so that all vectors of a
> pipeline stay L1/L2-resident (on the order of 1K values); compiled engines
> (HyPer) keep tuples in registers across operators of a pipeline. See
> `query-execution-advanced`.

## 6. Multicore: CMP, SMT and shared caches

- **CMP vs SMP:** cores on one die exchange coherence traffic at chip speed
  and often share a cache level; separate-socket SMPs coordinate over a slower
  interconnect and have separate hierarchies. **SMT** shares one core's
  pipeline among hardware threads, hiding one thread's miss with another's
  work.
- Parallelism is easy to find (inter-query, intra-query, intra-operator); the
  hard part is using it without destroying cache behaviour. Even if every
  thread is cache-conscious, co-running threads can jointly thrash a shared
  cache. Cooperative designs let threads share one cache-conscious structure
  for a common task (multithreaded hash join — Garcia & Korth 2006; Zhou et
  al. 2005; aggregation — Cieslewicz & Ross 2007).
- **Locality vs contention:** a shared hash table with a few hot groups has
  excellent locality and terrible contention; adaptive aggregation balances
  parallelism, cache sharing and inter-thread communication.
- **Work sharing can hurt** on CMPs for in-memory workloads (Johnson et al.,
  VLDB 2007): the shared operator becomes a serialization bottleneck.
- Hardavellas et al. (CIDR 2007): as core counts grow and per-core cache
  shrinks, data-access stalls and on-chip communication become the limits.

> **Beyond EDBS:** morsel-driven scheduling (Leis et al., SIGMOD 2014)
> allocates work in small NUMA-local chunks to a fixed set of pinned workers;
> per-socket hash-table partitions and NUMA-aware data placement are standard
> in modern analytic engines. Avoid relying on Linux first-touch when a single
> thread initializes a shared structure.

## 7. Main-memory DBMS design

**Definition** (EDBS, Boncz): a DBMS whose primary data store is RAM. With
I/O gone, design targets CPU and cache cost: simple tuple representations,
cache-line-sized index nodes with lower fan-out, direct pointers.

**Durability on volatile memory** — the three classical mechanisms:
1. Transaction logging to a journal on stable storage, with recovery by
   checkpoint image + log replay.
2. Non-volatile RAM (historically battery-backed SRAM or EEPROM) holding the
   store or the log tail.
3. High availability by replication to a hot standby with automatic failover
   (ClustRa telecom DB, MySQL Cluster).

**History and uses:** real-time systems such as telecom switching (fast,
predictable latency); then OLTP; then decision support (MonetDB). Also as a
drop-in cache in front of a disk DBMS that answers read-only queries on cached
data (TimesTen-style). Examples cited: MonetDB, SolidDB, TimesTen, DataBlitz
(from Bell Labs' Dalí storage manager), MySQL heap tables and MySQL Cluster.
DeWitt et al. (SIGMOD 1984) laid out early implementation techniques (group
commit among them).

Design decisions for an in-memory engine:

| Decision | Options | Guidance |
|---|---|---|
| Addressing | page ids through a buffer pool vs direct pointers | direct pointers remove hash lookups and pins; keep a page abstraction only if you need larger-than-memory or page-based recovery |
| Indexes | T-tree (Lehman & Carey, VLDB 1986), CSB+-tree, hash, radix trees | cache-conscious B+-trees beat T-trees on modern CPUs (Rao & Ross) |
| Layout | row, column, hybrid | match the dominant access; OLTP rows, analytics columns |
| Logging | physiological, logical/command logging, redo-only | in-memory indexes can be rebuilt at recovery instead of logged |
| Concurrency | locks with latches, partition-serial execution, optimistic MVCC | lock/latch overhead dominates once I/O is gone |
| Checkpointing | fuzzy, copy-on-write snapshot | must not stall transactions |

> **Beyond EDBS:**
> - Harizopoulos et al. ("OLTP Through the Looking Glass", SIGMOD 2008)
>   instrumented the Shore storage manager on an in-memory TPC-C subset:
>   buffer management, locking, latching and logging each consumed a large
>   share of instructions; useful work was a small fraction. Removing all four
>   is the H-Store/VoltDB design (Kallman et al., VLDB 2008): single-threaded
>   execution per partition, stored procedures only, durability via
>   replication plus command logging.
> - Hekaton (Diaconu et al., SIGMOD 2013): latch-free hash and Bw-tree indexes,
>   optimistic MVCC, stored procedures compiled to native code, redo-only
>   logging of committed changes, indexes not logged but rebuilt on recovery.
> - Silo (Tu et al., SOSP 2013): epoch-based optimistic concurrency control
>   with no shared-memory writes for read-only records; Masstree (Mao et al.,
>   EuroSys 2012) and ART (Leis et al., ICDE 2013) as in-memory indexes.
> - HyPer (Kemper & Neumann, ICDE 2011) took consistent OLAP snapshots of an
>   OLTP in-memory database with `fork()` and OS copy-on-write.
> - Anti-caching (DeBrabant et al., VLDB 2013) inverts the buffer pool: memory
>   is primary, cold tuples are evicted to disk.

## 8. Measurement methodology

1. Profile with hardware counters (`perf stat -e cycles,instructions,
   L1-dcache-load-misses,LLC-load-misses,dTLB-load-misses,branch-misses`);
   compute IPC, misses per tuple, branch misses per tuple.
2. Identify the binding level (L1i? LLC? TLB? branch?) before optimizing —
   Ailamaki et al.'s method.
3. Microbenchmark against the analytic model (§2.4) with calibrated
   parameters; a large gap means an unmodelled effect (conflict misses,
   NUMA, prefetcher defeat).
4. Re-run across data sizes that cross each cache capacity; performance
   cliffs at C_L2, C_LLC and TLB reach locate the problem.
5. Test concurrency: per-thread scaling, LLC sharing, false sharing (perf c2c).

## 9. Checklist

- Hot structures sized/aligned to lines; no false sharing on per-thread state.
- Access patterns sequential where possible; random patterns batched and
  prefetched.
- Partition fan-out bounded by TLB reach and line budget; huge pages
  considered.
- Hot loops branch-free or predictable; SIMD-friendly data layout (struct of
  arrays, fixed-width, aligned).
- Code footprint of the inner pipeline fits L1i, or work is batched.
- NUMA-local allocation and scheduling.
- In-memory engine: durability story explicit (log, NVRAM, replication), and
  lock/latch/logging overhead measured, not assumed.

Sources: EDBS *Architecture-Conscious Database System* (p.155),
*Cache-Conscious Query Processing* (p.389), *Memory Hierarchy* (p.2222),
*Memory Locality* (p.2229), *Locality* (p.2117), *Processor Cache* (p.2887),
*Main Memory* (p.2162), *Main Memory DBMS* (p.2164), *I/O Model of
Computation* (p.1741), *Query Processor* (p.3058), *Staged DBMS* (p.3696),
*Column Stores* (p.518).
