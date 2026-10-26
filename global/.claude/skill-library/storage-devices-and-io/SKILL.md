---
name: storage-devices-and-io
description: "Use when engine behaviour depends on the device and I/O stack beneath the page layer: HDD seek/rotation cost, SSD internals (FTL, erase blocks, garbage collection, write amplification, wear, queue depth), NVMe, RAID levels and the small-write penalty, SAN/NAS/DAS, LUNs, LVM, multipathing, object storage, checksums and torn/lost writes, fsync/O_DIRECT/io_uring semantics, tiering, MAID, WORM, and I/O-model costing. Triggers on seek time, rotational latency, IOPS, queue depth, FTL, TRIM, overprovisioning, DWPD, ZNS, RAID-5 write hole, parity, erasure coding, iSCSI, Fibre Channel, LUN, LVM, S3, CRC32C, T10 PI, torn page, doublewrite, fsync, fdatasync, O_DIRECT, io_uring, persistent memory, five-minute rule, external sort fan-in, external memory model. Apply even when phrased as 'why is the disk slow', 'is this commit really durable', 'what page size for NVMe', or 'why did throughput fall after an hour'."
---

# Storage Devices and the I/O Stack

This skill covers everything between the engine's page I/O call and the
storage medium: device physics and cost models, the flash translation
layer, RAID and storage networks, the OS durability primitives, and the
external-memory model used to cost algorithms. The single most important
idea: **a device is a (positioning cost, bandwidth, concurrency) triple
plus a durability contract**. Size I/Os from the first two, issue them to
match the third, and never assume more of the fourth than was verified.

## Mental model

- `T(x) = t_pos + x/BW`. The half-bandwidth size `x* = BW * t_pos` sets
  extent, prefetch, merge-buffer and row-group sizes: ~2-3 MB for a modern
  HDD, tens of KB per request on NVMe (but many requests in flight),
  several MiB for an object store.
- HDD positioning is mechanical (ms) and grew relatively worse every decade
  (capacity ~2,400x, bandwidth ~140x, latency ~8x from 1983 to 2003).
  SSD positioning is cheap but writes are out-of-place: every overwrite
  costs garbage collection later. NVMe throughput is Little's law:
  `IOPS = in_flight / latency`.
- The stack is a chain of caches and remappers (buffer pool, page cache,
  FS, LVM, RAID, controller, FTL) - each can reorder, merge, split,
  amplify, or lose writes. Durability exists only where a flush crossed
  every volatile layer.
- Integrity is end-to-end: hop-by-hop CRCs/ECC protect hops; only a
  checksum computed and verified by the engine, covering page identity and
  version, catches torn and misdirected writes - and lost writes only when
  compared against an independent version record (parent pointer, WAL).
- Algorithm cost = block transfers (Aggarwal-Vitter: scan n, sort
  n log_m n, search log_B N), refined by positioning events, read/write
  asymmetry, and parallelism.

## Core invariants

1. A write is durable only after a successful fsync/fdatasync (or
   O_DSYNC/FUA write) that returned *after* the write completed; a newly
   created or renamed file additionally needs its directory fsynced.
2. An fsync/fdatasync error (or EIO/ENOSPC during write-back) is fatal for
   that file: the engine stops trusting its cached state and recovers from
   the log or a replica. It never retries fsync and continues.
3. No ordering is assumed between in-flight writes: B that depends on A is
   submitted only after A completed (and was flushed if A must be durable).
4. Every page read from storage is checksum-verified before any field is
   used; the checksum covers the whole page and its identity (page/file
   id) and the page carries a version (LSN).
5. A page larger than the verified atomic write unit of the *whole* stack
   has a torn-write defence with an independent full copy (full-page image,
   doublewrite, CoW); detection alone is insufficient.
6. O_DIRECT I/O uses buffers, offsets and lengths aligned to the device
   logical block size, and is never treated as a durability mechanism.
7. Data and log volumes of one database are snapshotted/replicated as one
   consistency group with dependent-write order preserved.
8. Log blocks containing acknowledged commits are never overwritten in a
   way a torn write could destroy; recovery stops at the first record
   failing CRC/LSN continuity and distinguishes "end" from "damage".
9. Writes destined for parity RAID or flash are aligned to stripe width /
   flash indirection unit when they are large and sequential (log,
   bulk load, compaction output).
10. Freed extents on flash are eventually discarded (TRIM/deallocate), in
    batches, never synchronously on the critical path.
11. Steady-state performance claims for SSDs come from preconditioned
    devices; claims for durability come from power-cut tests.

## Design space & trade-offs

| Decision | Option | When it wins | Cost / risk |
|---|---|---|---|
| Page size | 4-8 KiB | SSD point lookups, OLTP | more pages, inner-node memory |
| | 16-64 KiB | HDD, scans, compression | read amplification on point reads |
| I/O path | buffered + fsync | simplicity, small DBs | double buffering, fsync error semantics, no control of write-back |
| | O_DIRECT + own buffer pool | predictable memory, high IOPS | alignment, must implement read-ahead/write-behind |
| | SPDK / user-space NVMe | maximum IOPS per core | owns device, polling burns CPU |
| Submission | thread pool + pread | portability | QD limited by threads |
| | io_uring batches | NVMe at high QD, few syscalls | kernel-version features, buffered ops may punt |
| Torn-page defence | full-page images in WAL | simple, no extra files | WAL bursts after checkpoint |
| | doublewrite | bounded WAL | ~2x page writes |
| | CoW / log-structured pages | no torn pages by construction | GC, write amplification |
| Write structure on flash | in-place B+-tree | read-heavy, PLP SSD | small random writes, endurance |
| | LSM / log-structured | write-heavy, ZNS fit | compaction WA, read amplification |
| Redundancy | RAID-10 | random-write OLTP | 50% capacity |
| | RAID-5/6 | read-mostly, sequential writes | 4/6-I/O small writes, write hole, long rebuilds |
| | erasure code across nodes | scale-out, cold data | repair traffic, small-write cost |
| Storage attach | DAS / local NVMe | latency, simple semantics | no sharing, node loss = data loss without replication |
| | SAN (FC, iSCSI, NVMe-oF) | shared block, array features | multipath stalls, fencing, layered caches |
| | NAS (NFS/SMB) | shared files, ops tooling | lock/sync semantics vary; verify before WAL on it |
| | object store | capacity, durability, elastic scans | no update in place, tens-of-ms latency, per-request cost |
| Tiering | engine-owned temperature placement | predictable cost model | complexity |
| | array/hypervisor auto-tiering | zero engine work | invisible latency variance |

## Algorithms that matter

**HDD access time.** `T = seek(d) + 0.5 * 60/RPM + x/BW_zone`; 7,200 RPM:
4.17 ms rotation; random 8 KiB ~12.7 ms (~79 IOPS); 4 MiB ~41 ms (~69% of
peak bandwidth). Schedule with batches sorted by LBA (SCAN/C-SCAN) or let
NCQ reorder a deep queue.

**SSD write amplification.** Out-of-place write -> invalidate old page ->
GC victim (greedy or cost-benefit) -> copy valid pages -> erase.
`WA ~ 1/(1-u)` at victim validity u; reduce with OP, TRIM, hot/cold
separation, large lifetime-grouped writes. Total WA multiplies across
engine x FS x device.

**RAID-5 small write.** `P' = P xor D_old xor D_new`: 2 reads + 2 writes;
reconstruct-write when cheaper; full-stripe write needs no reads. Random
write IOPS ~ `n * IOPS_disk / {1,2,4,6}` for RAID 0/1/5/6.

**CRC.** `R = (M * x^m) mod G` over GF(2); detects all bursts <= m bits;
misses error patterns divisible by G. CRC-32C with hardware instructions
for pages and log records.

**Durable atomic file replace.** write tmp -> fsync tmp -> rename ->
fsync dir. **Durable commit.** append log records -> one fdatasync per
group -> acknowledge all commits in the group.

**External sort.** runs = n/m; fan-in F = m/b - 1 with per-run buffer b
sized to the device's x*; passes = 1 + ceil(log_F runs); I/O = 2nP.

**Index vs scan crossover.** `s* ~ scan_cost_per_row / random_fetch_cost`:
~0.004% on HDD QD1, ~0.03% on NVMe QD1, ~1% on NVMe with deep queues.
Executor I/O concurrency is part of the cost model.

**Spin-down break-even.** `T_be ~ (E_down + E_up)/(P_idle - P_standby)`;
threshold = T_be is 2-competitive on energy, but adds seconds of latency.

## Failure modes & classic bugs

| Bug | Symptom / detection |
|---|---|
| fsync retried after error ("fsyncgate") | second fsync succeeds, data gone; inject EIO |
| no directory fsync after create/rename | WAL segment or SSTable missing after crash |
| O_DIRECT treated as durable | loss on power cut; drive cache, unwritten extents |
| lying drive / no PLP | acknowledged commits lost; power-cut rig |
| torn page without a full copy; all-zero page accepted as "new" | detected-but-unrepairable / silently hidden lost write |
| checksum omits page id; hint bits set after checksumming | misdirected write passes; spurious mismatches |
| RAID write hole; data and log LUNs snapshotted separately | garbage after rebuild; torn database from "consistent" snapshot |
| misalignment (FS/LVM/RAID/512e/IU) or stacked striping | 2x device writes, RAID RMW, one hot spindle |
| multipath double-visibility; failover stalls | corruption; tens-of-seconds I/O hangs |
| SSD write cliff, GC read p99, fresh-drive benchmarks | throughput collapse after minutes; optimistic numbers |
| synchronous discard; mmap write path | stalls on free; WAL ordering violated, SIGBUS |
| background jobs waking cold tiers; thin-pool ENOSPC as transient | multi-second outliers; lost write-back

## Implementation checklist (C/C++/Rust)

- Probe per device: logical/physical block size, DIO alignment (`statx`
  STATX_DIOALIGN), rotational flag, NVMe AWUPF, volatile write cache, max QD.
- Aligned buffers (`posix_memalign`, Rust `std::alloc::Layout` 4 KiB) behind
  a page-buffer type that cannot be built unaligned; no plain `Vec<u8>`.
- One I/O ring per worker, bounded in-flight per device, completions resume
  coroutines; no global lock on submit.
- Typed I/O errors: retryable (EAGAIN/EINTR), transient (one re-read on
  checksum mismatch), fatal (write-back EIO/ENOSPC, fsync error) -> crash.
- CRC-32C (hardware + fallback) on a private copy at write time, covering
  page id; verify before parsing.
- Log: per-record CRC + LSN, preallocated zero-filled segments, one
  fdatasync per group commit, no in-place overwrite of acknowledged blocks.
- One `durable_create`/`durable_rename` helper that fsyncs file and directory.
- Flash: batched TRIM, IU-aligned large writes, hot/cold file separation,
  DWPD budget check; export latency histograms and host-vs-media writes.
- Derive cost constants (random/sequential, concurrency) from calibration.

## How to test it

- **Crash consistency**: record writes/flushes (dm-log-writes), replay every
  flush-consistent prefix, recover, check invariants (ALICE/CrashMonkey style).
- **Error injection**: dm-flakey or a fault VFS returning EIO/ENOSPC from
  write and fsync; assert controlled crash and correct recovery.
- **Corruption injection**: bit flips, zeroed, swapped (misdirected), stale
  (lost write) and torn pages at every sector boundary, torn log tail;
  assert detection, no wrong results, repair from redundancy.
- **Power-cut rig** per platform with a remote ledger of acknowledged commits.
- **Checksum vectors**: CRC-32C("123456789") = 0xE3069283; all single-bit
  flips detected; combine equals concatenation.
- **Device benchmarks**: fio at engine block sizes and QDs, preconditioned,
  mixed read/write, past SLC-cache/GC transitions; report p99/p99.9.
- **Cost-model oracle**: predicted vs measured block I/O (blktrace), cold cache.

## Expert review questions

1. What is the verified atomic write unit of the full stack, and how does
   the design recover a torn page and a torn log tail?
2. Walk "commit requested" to "acknowledged": which syscalls, flushes and
   device cache settings make it durable?
3. What happens on the first fsync error? On ENOSPC from a thin pool?
4. Does the checksum cover page identity and version? Against what
   independent record are lost and misdirected writes detected?
5. What QD does the executor sustain on index probes, and does the
   optimizer's random-I/O constant assume the same?
6. Total write amplification (engine x FS x device) vs the drives' DWPD?
7. Are large writes aligned to stripe width and flash IU through FS/LVM?
8. Were SSD numbers steady-state, mixed, with compaction/checkpoint running?
9. On parity RAID, how is the write hole closed; degraded/rebuild speed?
10. Are data and log volumes one consistency group for snapshot/replication?
11. Which background tasks can wake cold tiers or spun-down drives?
12. On object storage: request size, concurrency, request cost, and the
    atomic commit primitive (catalog CAS vs conditional PUT)?
13. With mmap or buffered I/O, how are WAL ordering and write-back errors handled?

## Go deeper

- `references/device-cost-models.md` - HDD timing with worked numbers,
  trends, scheduling, media, five-minute rule, memory-hierarchy model,
  power/MAID, tiering/ILM, WORM. Read for "what does this I/O cost".
- `references/ssd-and-flash-for-db-engines.md` - NAND, FTL, GC/WA, wear,
  PLP, NVMe, ZNS/FDP, io_uring/SPDK, persistent memory, page/log/index
  implications. Read before designing for flash.
- `references/raid-and-storage-networks.md` - RAID penalty and write hole,
  erasure codes, SAN/NAS/DAS, LUN/multipath, LVM, DFS/OSD, object stores
  and cloud-warehouse substrates. Read when storage is shared or networked.
- `references/integrity-checksums-and-durability-of-io.md` - failure
  taxonomy, CRC practice, page-checksum coverage, T10 PI, torn writes,
  fsync/O_DIRECT/ordering, crash testing. Read before persisting anything.
- `references/io-model-and-algorithm-costs.md` - external-memory bounds,
  operator costing, write-optimised structures, refined models, review
  recipe. Read when predicting or comparing I/O costs.
- `references/edbs-entries.md` - all 39 source entries with pages.

## Related skills

- `page-and-file-format` - page byte layout and checksum field; here: what it must cover.
- `storage-and-indexing` - buffer pool, B-trees; here: device costs, I/O sizing, flash-aware eviction.
- `lsm-storage` - compaction policy; here: device WA, ZNS/FDP, TRIM.
- `transactions-and-recovery`, `recovery-and-durability` - WAL/ARIES built on the flush/ordering primitives here.
- `index-structures-catalog`, `multidimensional-and-similarity-indexing` - structures costed with the I/O model here.
- `query-execution-advanced` - spilling operators; here: buffer sizes and fan-in.
- `query-optimizer`, `cardinality-and-statistics` - random/sequential/concurrency cost constants.
- `dbms-architecture` - storage-manager placement, raw vs file storage.
- `parallel-database-systems`, `parallel-distributed-execution` - declustering, shared-disk vs shared-nothing.
- `replication-protocols`, `replication-and-consistency`, `distributed-dbms-design` - DB-level replication above storage replication.
- `olap-and-warehouse-engines` - columnar engines; here: the object-store substrate.
- `temporal-databases`, `database-security-internals` - WORM retention; encryption at rest, crypto-erase.
- `tuning-and-benchmarking`, `query-engine-testing` - fio/TPC methodology; crash/corruption harnesses.

## Grounding

EDBS entries (printed pages): Disk (1143), I/O Model of Computation (1741),
Memory Hierarchy (2222), Storage Devices (3726), Solid State Drive (3545),
Redundant Arrays of Independent Disks (3135), Storage Protection (3754),
Checksum and Cyclic Redundancy Check Mechanism (423), Storage Access Models
(3722), Storage Protocols (3756), Storage Network Architectures (3741),
Object Storage Protocol (2539), Distributed File Systems (1186), SAN File
System (3274), Network Attached Secure Device (2489), Storage Power
Management (3752), Multitier Storage Systems (2446), Write Once Read Many
(4732); full list in `references/edbs-entries.md`.
Seminal work: RAID (Patterson, Gibson, Katz, SIGMOD 1988); I/O complexity
(Aggarwal, Vitter, CACM 1988); disk modeling (Ruemmler, Wilkes 1994);
five-minute rule (Gray, Putzolu 1987); LFS (Rosenblum, Ousterhout 1991);
Active Storage (Riedel et al. VLDB 1998); NASD (Gibson et al. 1997); MAID
(Colarelli, Grunwald 2002); memory cost models (Manegold et al. VLDB 2002);
end-to-end arguments (Saltzer et al. 1984); storage corruption studies
(Bairavasundaram et al. 2007/2008); ALICE (OSDI 2014); fsync failures (ATC
2020); ZNS (ATC 2021); NVMe and object-store engines (Haas, Leis; Durner,
Leis, Neumann; PVLDB 2023).
