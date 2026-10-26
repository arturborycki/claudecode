# SSDs, flash and NVMe for database engines

Read this when designing page size, WAL layout, index structure, buffer
management or the I/O submission path for flash/NVMe, or when explaining
an SSD performance cliff, endurance burn, or tail-latency spike.

EDBS's own coverage is short (Solid State Drive; Storage Devices; Data
Center Energy Efficiency): flash must be erased before rewrite, survives a
limited number of erase cycles, SLC outlasts and outperforms MLC, the drive
contains a controller that does wear leveling and block allocation, SSDs
can be accessed via SCSI, NVMe, or key-value interfaces, random access is
far better than on HDD, and HDD still wins on $/GB for latency-insensitive
data. Almost everything below is established post-EDBS practice and is
marked accordingly.

---

## 1. NAND organisation and primitive costs

> **Beyond EDBS** (whole section).

```
channel --- package --- die --- plane --- block (erase unit) --- page (program/read unit)
                                           e.g. hundreds of pages,      e.g. 4-16 KiB + spare
                                           several MiB                  area for ECC/metadata
```

| Operation | Unit | Relative cost | Constraint |
|---|---|---|---|
| Read | page | tens of microseconds | read disturb accumulates on neighbours |
| Program | page | several times a read (hundreds of us for TLC/QLC) | pages in a block programmed in order; no overwrite |
| Erase | block | milliseconds | wears the cells; finite P/E cycles |

- Bits per cell trade endurance and speed for density: SLC > MLC > TLC >
  QLC in endurance (from ~10^5 P/E cycles for SLC down to ~10^3 or fewer
  for QLC; treat vendor datasheets as authoritative).
- Cells leak (retention) and are disturbed by reads/programs of neighbours;
  the controller applies strong ECC (BCH, LDPC) and refreshes data. Raw bit
  error rates rise with wear, so read latency can rise with age as ECC
  retries kick in.
- Many TLC/QLC drives run part of the media in SLC mode as a write cache;
  sustained writes beyond it hit a **write cliff** at native TLC/QLC speed.

## 2. The flash translation layer (FTL)

> **Beyond EDBS** (EDBS only says "the controller performs wear leveling
> and block allocation").

Because pages cannot be overwritten, every logical write goes **out of
place**: the FTL writes the new version to a free page, updates the
logical-to-physical (L2P) map, and marks the old page invalid.

Mapping schemes:

| Scheme | Map granularity | DRAM need | Random-write behaviour |
|---|---|---|---|
| Page-mapped | page / indirection unit (IU) | ~4 bytes per 4 KiB, i.e. ~1 GB DRAM per TB | best; standard in enterprise SSDs |
| Block-mapped | erase block | tiny | terrible: small update rewrites a block |
| Hybrid log-block (BAST, FAST) | blocks + page-mapped log blocks | small | good until log blocks must merge |
| Demand-paged map (DFTL, Gupta et al. ASPLOS 2009) | page map cached in DRAM | bounded | depends on map locality |

High-capacity QLC drives often use 16-64 KiB indirection units to cut DRAM;
then any host write smaller than the IU becomes a read-modify-write inside
the drive. **Know your IU and write at least IU-sized, IU-aligned chunks.**

### Garbage collection and write amplification

GC picks a victim block, copies its still-valid pages elsewhere, then
erases it. If the victim has valid fraction u, reclaiming (1-u) of a block
costs writing u of a block, so

```
WA_device = NAND bytes written / host bytes written  ~  1 / (1 - u)
```

Victim choice: greedy (lowest u) or cost-benefit (age-weighted, from LFS,
Rosenblum and Ousterhout, SOSP 1991/TOCS 1992). Under uniform random
writes u at the victim rises as the drive fills, so WA explodes near full
logical utilisation. Levers:

- **Over-provisioning (OP)**: spare physical capacity the host cannot
  address. Enterprise drives ship more OP than consumer drives; leaving
  part of the LBA space never written (after a secure erase) adds OP.
- **TRIM / UNMAP / NVMe Deallocate**: tells the FTL a range is dead so GC
  need not copy it. The engine should discard freed extents (batched,
  asynchronously; synchronous discard on every free is a known latency
  hazard).
- **Hot/cold separation**: if data with similar lifetimes share erase
  blocks, victims are either almost all invalid or all valid and WA tends
  to 1. Multi-stream, Flexible Data Placement (FDP), and zoned namespaces
  let the host express this (section 6).
- **Sequential, large writes** with similar lifetime (log segments, LSM
  SSTables, append-only column files deleted as a unit) give WA ~ 1.

**Wear leveling**: dynamic (direct new writes to least-worn free blocks)
and static (periodically move cold data off low-wear blocks so they join
the rotation). Static leveling itself costs writes.

**Total write amplification is multiplicative**:

```
WA_total = WA_engine (LSM compaction, B-tree page rewrites, full-page images, doublewrite)
         x WA_filesystem (journal, metadata, CoW)
         x WA_device (GC)
```

Endurance budgets are given as TBW or DWPD (drive writes per day over the
warranty). Compute `host_write_rate * WA_engine * WA_fs * WA_device` against
it during design, not after deployment.

### Power-loss behaviour

Enterprise SSDs carry capacitors (power-loss protection, PLP) that let the
drive flush its DRAM write buffer and map updates on power failure, so
flushes are cheap and acknowledged writes survive. Consumer drives may not,
and some have historically acknowledged cache flushes without persisting,
or corrupted unrelated data on power cut (Zheng et al., "Understanding the
robustness of SSDs under power fault", FAST 2013). Test, do not trust
(`integrity-checksums-and-durability-of-io.md` section 6).

## 3. Performance model for an engine builder

> **Beyond EDBS** (EDBS gives one 2008 SSD data point: ~0.3 ms read
> latency, 80 MB/s, against ~5.7 ms for a 15k RPM disk).

1. **Parallelism, not seek, is the resource.** A drive has many channels x
   dies x planes. Throughput follows Little's law:
   `IOPS = outstanding_requests / latency`. At ~80-100 us read latency,
   QD1 yields ~10-12k IOPS; reaching ~1M IOPS needs on the order of 100
   requests in flight. Synchronous one-at-a-time reads (a classic B-tree
   descent, an index nested-loop join) leave >95% of the device idle.
2. **Read/write asymmetry.** Program is slower than read and triggers GC;
   mixed workloads raise read tail latency because reads queue behind
   programs/erases on the same die. Separate latency SLOs for reads in the
   presence of writes; throttle background writes (compaction, checkpoint)
   by observed read p99, not by bandwidth alone.
3. **Random vs sequential reads** differ little once QD is high and
   requests are >= the page/IU size; random vs sequential *writes* differ a
   lot in steady state because of GC.
4. **Fresh-out-of-box vs steady state.** A new or freshly trimmed drive is
   much faster for writes than one that has been filled and overwritten.
   Benchmarks must precondition (fill, then random-overwrite until
   throughput stabilises; SNIA's Solid State Storage Performance Test
   Specification codifies this).
5. **Small writes are expensive twice**: device RMW when below the IU, and
   lifetime consumed. A 100-byte update that rewrites a 16 KiB page costs
   >160x amplification at the engine level alone.
6. **CPU becomes the bottleneck.** With several NVMe drives, the kernel
   I/O path, interrupts, page-cache copies, and buffer-manager latching
   dominate. Haas and Leis, "What modern NVMe storage can do, and how to
   exploit it" (PVLDB 2023), show that an engine must use asynchronous,
   batched, many-in-flight I/O and a lightweight buffer manager to approach
   array line rate.

## 4. Implications for page size, logging and index design

### Page size

| Device | Pressure toward | Reason |
|---|---|---|
| HDD | large pages/extents (16-64 KiB pages, MiB extents) | amortise ms positioning |
| SSD reads | small pages (4-8 KiB) | read amplification per point lookup; positioning is cheap |
| SSD writes | page >= IU, aligned; avoid in-place small updates | device RMW + endurance |
| Object store | MiB-scale blocks | ~10s of ms first-byte latency, per-request cost |

A common resolution is decoupling: small logical pages for the buffer pool
and index nodes, written out in larger aligned batches (log-structured
page store, or grouping dirty pages per extent at checkpoint). Compressed
pages become variable-size, which forces either out-of-place writing or
slack space; do not compress into a fixed slot and then pad to the device
block - you lose the I/O saving.

### Logging

- The WAL is small, sequential, and fsync-bound. Commit latency = flush
  latency; on PLP drives flush is cheap, on others it costs a full
  internal flush (can be ms).
- Avoid re-programming the same partial log page on every group commit
  (each fsync of a partially filled 4 KiB block rewrites it). Options: pad
  and move on to a new block per flush, or write log in IU-sized chunks
  with group commit; preallocate and pre-zero log files so overwrites do
  not change file metadata.
- Full-page images / doublewrite (torn-page defences) double write volume;
  on devices with guaranteed atomic writes of the page size (NVMe AWUPF
  covering the page) they can be disabled - only after verifying the
  guarantee and the whole stack (FS, RAID, virtualization) preserves it.
- Put the log on the lowest-latency persistent medium available (PLP SSD,
  NVDIMM/PMem); data files can live on capacity media.

> In-page logging (Lee and Moon, SIGMOD 2007) co-locates small log records
> with the data page's erase block to avoid page rewrites on flash; it
> required raw-flash control and is mostly of historical interest, but the
> idea (keep update deltas, merge lazily) lives on in Bw-tree/LLAMA.

### Index and structure design

- **In-place B+-trees** turn random updates into random small page writes:
  fine on a PLP SSD at moderate write rates, costly in endurance at high
  rates. Mitigations: larger leaf write batching, delta records (Bw-tree;
  LLAMA log-structured page store, Levandoski et al. ICDE/VLDB 2013),
  write-optimized trees (B^epsilon), or LSM.
- **LSM trees** convert random writes into large sequential writes that
  match the device's preference (WA_device ~ 1) at the price of engine
  WA from compaction; on flash the engine WA is usually the larger term.
  See `lsm-storage`.
- **Exploit parallelism in lookups**: issue sibling/next-level prefetches,
  batch probes from a join (sort probe keys, submit many in flight), and
  use parallel I/O inside index range scans.
- **Buffer management**: flash makes misses cheaper and writes relatively
  dearer. Clean-first eviction (CFLRU, Park et al. 2006) prefers evicting
  clean pages; an SSD second-level cache under a DRAM buffer pool
  (Canim et al. VLDB 2010; Do et al. SIGMOD 2011) extends the five-minute
  rule's economics. LeanStore (Leis et al. ICDE 2018) shows pointer
  swizzling plus a lightweight replacement strategy gets in-memory speed
  when the data fit and graceful degradation when they do not.
- **Spill files** (hash join, sort): random reads of partitions are cheap
  on SSD, so partition fan-out can be higher and spill buffers smaller than
  on HDD; still write spill files sequentially and discard them.

## 5. NVMe as a protocol (what the engine can rely on)

> **Beyond EDBS** (EDBS mentions NVMe only by name).

- Up to 64K I/O submission/completion queue pairs, each up to 64K entries;
  map one queue pair per core to avoid cross-core locking. Doorbell writes
  submit, completion entries carry a phase bit; interrupts (MSI-X) or
  polling.
- Commands relevant to engines: Read, Write (with FUA bit), Flush
  (meaningful only if the Volatile Write Cache feature is present),
  Dataset Management/Deallocate (TRIM), Write Zeroes, Compare, and
  optional fused Compare-and-Write.
- Atomicity: the Identify data reports AWUN (atomic write unit, normal)
  and AWUPF (atomic write unit across power fail); many drives report one
  LBA, i.e. only sector atomicity. Do not assume a 16 KiB write is atomic.
- LBA formats: 512 B or 4 KiB, optionally with per-LBA metadata used for
  end-to-end protection information (T10-style PI).
- NVMe over Fabrics (RDMA, TCP, FC) extends the same queue model across a
  network, replacing iSCSI/FCP for low-latency disaggregated flash.

## 6. Host-managed placement: ZNS, FDP, open-channel

> **Beyond EDBS.**

- **Zoned Namespaces (ZNS)**: the namespace is split into zones that must
  be written sequentially and reset as a whole; *zone append* lets many
  writers append without coordinating the write pointer (the device
  returns the LBA). The device needs little OP or map DRAM and has WA ~ 1;
  the host now does GC. A natural fit for LSM SSTables and log segments
  (RocksDB with ZenFS; Bjorling et al., "ZNS: Avoiding the block interface
  tax", USENIX ATC 2021). Open-channel SSD / LightNVM (Bjorling et al.,
  FAST 2017) was the predecessor.
- **Flexible Data Placement (FDP)** keeps the random-write block interface
  but lets the host tag writes with placement handles so data with
  similar lifetimes share erase blocks; earlier "multi-stream" SSDs had
  the same goal.
- **Key-value SSDs** (NVMe KV command set; EDBS mentions KV interfaces)
  move the index into the drive; useful only if the drive's KV semantics
  match the engine's.

Engine design rule: if the engine already writes in large, append-only,
lifetime-grouped units (LSM, log-structured column files), host-managed
placement removes a whole layer of WA; if it updates pages in place, it
does not help without a log-structured page store on top.

## 7. I/O submission paths

> **Beyond EDBS.**

| Path | Mechanism | When it wins | Caveats |
|---|---|---|---|
| Blocking pread/pwrite + thread pool | one thread per outstanding I/O | simple, portable | threads/context switches cap IOPS; QD = #threads |
| POSIX AIO (glibc) | user-space threads | portability only | effectively a thread pool |
| Linux AIO (io_submit) | kernel async | O_DIRECT data files | only truly async with O_DIRECT; can block on metadata/allocation |
| io_uring (Linux 5.1+, 2019) | shared SQ/CQ rings | batched async I/O for files and sockets | buffered I/O may punt to kernel workers; feature set depends on kernel version; some hardened environments disable it |
| SPDK | user-space polled NVMe driver | max IOPS per core, dedicated devices | owns the device (no FS), polling burns cores |

io_uring features that matter: batching many SQEs per `io_uring_enter`,
registered files and fixed buffers (avoid per-I/O fd lookup and page
pinning), `IORING_SETUP_IOPOLL` (polled completions for O_DIRECT on NVMe),
`IORING_SETUP_SQPOLL` (kernel thread polls the SQ; zero syscalls in steady
state), linked SQEs (`IOSQE_IO_LINK`) for ordered submission, and
`IORING_OP_FSYNC` for asynchronous durability points. A typical engine
pattern: one ring per worker thread, an in-flight cap per device, fibers or
coroutines suspended on I/O completion, completions reaped in the worker's
scheduling loop.

## 8. Persistent memory

> **Beyond EDBS** except where noted.

- EDBS (Data Center Energy Efficiency) flags PCM: non-volatile and denser
  than DRAM, but cells wear under repeated high-current writes; mitigations
  are remapping (wear leveling), DRAM/SRAM write caching, rest periods and
  slower writes. It also warns that pervasive persistence changes semantics:
  stale or inconsistent data survives crashes, and residual data is a
  security concern.
- Intel Optane DC Persistent Memory (2019; product line discontinued in
  2022) provided byte-addressable persistence on the memory bus. Lessons
  that carry over to CXL-attached persistent or far memory:
  - Persistence domain: with ADR, stores are durable once they reach the
    memory controller's write-pending queue, so software must flush cache
    lines (`clwb`/`clflushopt`) and fence (`sfence`); with eADR the caches
    are inside the domain and only fences are needed.
  - Failure atomicity is 8 bytes (aligned store); anything larger needs a
    log, copy-on-write, or a checksum plus version scheme.
  - Media access granularity was 256 bytes, so small random writes were
    internally amplified; read latency was a few times DRAM; bandwidth,
    especially write bandwidth, was far below DRAM (Yang et al., "An
    empirical guide to the behavior and use of scalable persistent
    memory", FAST 2020).
  - Access via DAX file systems with `MAP_SYNC` mappings or via libraries
    (PMDK). Persistent pointers must be position-independent (offsets).
- Best engine uses: WAL tail / commit log (removes the fsync from commit),
  persistent index inner nodes, or metadata; full persistent-memory-native
  engines must solve allocation leaks on crash and recovery of volatile
  state.

## 9. Flash-specific failure modes to test for

| Symptom | Likely cause | Detection |
|---|---|---|
| Write throughput collapses after minutes | SLC cache exhausted or GC steady state | precondition + long-run fio |
| Read p99 spikes during compaction/checkpoint | read/program/erase interference on dies | latency histograms tagged by background activity |
| Endurance exhausted early | multiplicative WA, small in-place writes | SMART/NVMe log: host vs media writes |
| Data loss after power cut despite fsync | no PLP, flush ignored, firmware bug | power-cut test rig, `diskchecker`-style verifier |
| Slow reads on old drive | ECC retries on worn cells | per-device latency trend |
| Latency stalls on free | synchronous discard on every deallocation | batch and rate-limit discards |

---

Sources: EDBS entries Solid State Drive (SSD) (p.3545), Storage Devices
(p.3726), Data Center Energy Efficiency (p.735), Disk (p.1143), Object
Storage Protocol (p.2539). Everything marked Beyond EDBS draws on the
papers and specifications named inline.
