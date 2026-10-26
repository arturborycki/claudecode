# Device cost models: disks, the memory hierarchy, tiers, power

Read this when you need numbers: how long an I/O costs on a given device,
why the engine must prefer large sequential transfers, how to pick an I/O
size, how a spun-down or tiered device changes the cost model, and how the
CPU-cache hierarchy obeys the same rules one level up.

---

## 1. The one formula

Every block device (and every memory level) can be approximated by

```
T(x) = t_pos + x / BW          t_pos = positioning cost, BW = streaming bandwidth
```

- HDD: `t_pos = t_seek + t_rot` (milliseconds), BW = media rate of the zone.
- SSD: `t_pos` is the command latency (tens of microseconds for reads), but
  the device is *parallel*, so throughput is governed by queue depth (see
  `ssd-and-flash-for-db-engines.md`).
- DRAM / caches: `t_pos` is the miss latency, x is a cache line (section 5).
- Object store: `t_pos` is first-byte latency (tens of ms), BW is
  per-connection throughput (see `raid-and-storage-networks.md` section 7).

The **half-bandwidth transfer size** `x* = BW * t_pos` is the transfer at
which positioning and transfer cost are equal. Transfers much smaller than
x* waste the device; transfers much larger give diminishing returns and
hurt latency/fairness. Every "how big should my extent / merge buffer /
prefetch / row group be" question starts here.

## 2. HDD mechanics (EDBS: Disk; I/O Model of Computation)

Geometry: a stack of platters on one spindle, one head per surface, all
heads on a single actuator. A **track** is one radius on one surface; the
set of tracks at one radius across surfaces is a **cylinder**; a **sector**
is an angular segment of a track (512 B historically, 4 KiB on Advanced
Format drives). Because the head covers more linear distance per second on
outer tracks, modern drives use **zoned bit recording**: outer zones hold
more sectors per track and stream faster (often ~2x the inner-zone rate).

Access = seek (move arm to cylinder) + rotational latency (wait for sector)
+ transfer. Average rotational latency is half a revolution:

| RPM | full rev | avg rotational latency |
|---|---|---|
| 5,400 | 11.1 ms | 5.6 ms |
| 7,200 | 8.3 ms | 4.2 ms |
| 10,000 | 6.0 ms | 3.0 ms |
| 15,000 | 4.0 ms | 2.0 ms |

Seek time is not linear in distance: short seeks are dominated by
acceleration and settle time (roughly sqrt(distance)); long seeks approach a
linear coast phase (Ruemmler and Wilkes, IEEE Computer 1994). "Average seek"
on a spec sheet is for a random one-third-stroke seek; track-to-track is
under 1 ms. Consequence: *locality within a few cylinders is almost as good
as sequential*, which is what extent-based allocation and clustering buy.

### Historical trend and why it matters (synthesised from the EDBS Disk table)

| Year | RPM | Capacity | Seq BW | Random read latency | x* = BW * latency |
|---|---|---|---|---|---|
| 1983 | 3,600 | 0.03 GB | 0.6 MB/s | 48.3 ms | ~29 KB |
| 1994 | 7,200 | 4.3 GB | 9 MB/s | 12.7 ms | ~114 KB |
| 2003 | 15,000 | 73.4 GB | 86 MB/s | 5.7 ms | ~490 KB |

Capacity grew ~2,400x, bandwidth ~140x, latency improved only ~8.5x. The
break-even transfer size therefore grew ~17x: random I/O became relatively
*more* expensive every decade. A 2010s 7,200 RPM nearline drive (~8.5 ms
seek, ~150-250 MB/s) has x* around 2-3 MB. The engineering consequences
the entry draws, and that remain true: asynchronous I/O so the drive can
reorder many outstanding requests, striping across spindles for IOPS,
larger pages/extents, compression (fewer bytes per useful tuple),
clustered indexes, and cooperative/shared scans.

### Worked example (7,200 RPM, 8.5 ms avg seek, 150 MB/s)

```
random 8 KiB read  = 8.5 + 4.17 + 0.05 = 12.7 ms  -> ~79 IOPS -> 0.63 MB/s
sequential          = 150 MB/s
ratio               ~ 240x per byte
1 MiB random read   = 8.5 + 4.17 + 7.0 = 19.7 ms  -> 53 MB/s (35% of peak)
4 MiB random read   = 12.7 + 28 ms     = 40.7 ms  -> 103 MB/s (69% of peak)
```

So an external-sort merge with 1 MiB per-run buffers reading from one HDD
gets about a third of the disk; 4 MiB gets two thirds. That is the number
that sets merge fan-in, not "pages".

### Request scheduling and queue depth

With several requests outstanding, the drive (tagged/native command
queueing, which EDBS Storage Protocols notes was SCSI-only until ATA gained
it) or the OS reorders them: SSTF (shortest seek first; starves edges),
SCAN/elevator, C-SCAN (one direction, uniform wait), and in-drive
rotational-position-aware ordering. Throughput on random reads rises
noticeably from QD1 to QD32 because the expected positioning cost per
request falls. The engine-side lesson: issue reads asynchronously in batches
(prefetch lists sorted by page number, bitmap heap scans, sorted RID fetch)
rather than one synchronous read per tuple.

> **Beyond EDBS:** (1) Drives have a volatile write cache; a write
> acknowledged from it is lost on power failure unless the host issues a
> cache flush (ATA FLUSH CACHE / SCSI SYNCHRONIZE CACHE) or uses FUA writes
> - see `integrity-checksums-and-durability-of-io.md`. (2) 4Kn and 512e
> Advanced Format drives: a 512-byte-aligned but not 4 KiB-aligned write on
> 512e forces a read-modify-write inside the drive; align partitions,
> extents and O_DIRECT buffers to 4 KiB. (3) Shingled magnetic recording
> (SMR) drives overlap tracks; random writes either go through a
> drive-managed translation layer (with flash-like garbage-collection
> stalls) or, for host-managed/zoned drives, must be written sequentially
> per zone - the same model as NVMe ZNS.

## 3. Other media, as a database sees them (EDBS: Storage Devices)

| Medium | Access | Strength | Weakness | Engine role |
|---|---|---|---|---|
| Tape (LTO etc.) | sequential only; robot mount + wind = tens of s | lowest $/GB, densest, portable, WORM variants | no random access; media must be re-copied every few years | archive, backup, compliance copies; put a disk cache in front for bursts |
| Optical (CD/DVD/BD) | random, slow; jukeboxes | physical WORM | small, slow, consumer-oriented | legacy archive |
| HDD | random but mechanical | $/GB for online data | IOPS-limited, power-hungry | capacity tier, logs on spindles, scans |
| Flash SSD | random, parallel, erase-before-write | IOPS, latency | endurance, write asymmetry, $/GB | primary OLTP, caches, indexes |
| NVM (PCM, STT-MRAM, Optane) | byte-addressable or block | near-DRAM latency, persistence | cost, wear (PCM), product availability | log, metadata, persistent indexes |

EDBS (Storage Devices) also notes NAND vs NOR: NAND programs and erases
faster and is dense (data); NOR reads faster with random byte access
(code). SLC endures more erase cycles and is faster than MLC.

## 4. Economic rules for caching vs fetching

> **Beyond EDBS:** The *five-minute rule* (Gray and Putzolu, SIGMOD 1987;
> revisited by Gray and Graefe 1997 and Graefe 2007/2009) turns the device
> model into a buffer-pool policy. A page re-referenced every T seconds is
> worth caching if
>
> ```
> T < (pages_per_MB_of_RAM / IOPS_per_device) * (price_per_device / price_per_MB_RAM)
> ```
>
> With HDDs the interval was minutes for 4-8 KiB pages; with SSDs (100x+
> IOPS per dollar) it shrinks toward seconds-to-a-minute for small pages,
> which is why SSD-era engines run smaller DRAM buffer pools backed by an
> SSD tier, and why the optimal page size for a flash tier is smaller than
> for disk. Recompute it with your own prices; never hard-code the
> conclusion.

## 5. The memory hierarchy is the same problem (EDBS: Memory Hierarchy)

Each level i is characterised by capacity C_i, block (line) size Z_i,
number of lines C_i/Z_i, associativity A_i, and separate **sequential**
and **random** miss latency/bandwidth. Miss latency and miss bandwidth are
linked by `l_i = Z_i / b_i`. Total memory cost of an operator is

```
T_mem = sum_i ( Misses_seq_i * l_seq_i + Misses_rand_i * l_rand_i )
```

(Manegold, Boncz, Kersten, "Generic database cost models for hierarchical
memory systems", VLDB 2002.) The TLB is treated as one more level whose
"line" is the OS page and whose capacity is entries x page size; TLBs are
fully associative and have no seq/random distinction. Manegold's
*Calibrator* tool measures these parameters empirically.

Miss taxonomy (Hill and Smith 1989), with what the engine does about each:

| Miss | Cause | Remedy in engine code |
|---|---|---|
| Compulsory | first touch | prefetch (software prefetch, sequential layout) |
| Capacity | working set > C | partition (radix-cluster joins), blocking/tiling, compression |
| Conflict | set-mapping collisions | avoid power-of-two strides, pad arrays, partition fan-out below #TLB entries and #lines |
| Coherence | another core wrote the line | per-core state, avoid false sharing (pad hot counters/latches to a line) |

Inclusive vs exclusive cache hierarchies change effective capacity (largest
level vs sum of levels). Sequential access gets more effective bandwidth
because hardware prefetch and burst transfers hide latency, exactly as with
disk read-ahead. EDBS records that by the late 1990s memory stalls could
account for up to ~90% of query time (Ailamaki et al., VLDB 1999; Boncz,
Manegold, Kersten, VLDB 1999), which launched cache-conscious data
structures (Shatdal, Kant, Naughton VLDB 1994; CSB+-trees, Rao and Ross
SIGMOD 2000) and column stores.

Design rule: a DBMS manages its own buffer pool rather than trusting OS
virtual memory, because it knows access patterns (scans vs index probes),
must control write-back order for WAL, and can choose replacement policies
(see `storage-and-indexing`). The same reasoning applies to choosing
O_DIRECT over the page cache (`integrity-checksums-and-durability-of-io.md`).

## 6. Power: modes, break-even time, MAID (EDBS: Disk Power Saving; Storage Power Management; MAID; Data Center Energy Efficiency)

- The spindle motor dominates HDD power (one study cited by EDBS: 81%).
  Ideal motor power scales with the square of angular velocity; air drag
  pushes the real exponent to cubic or more. Fast spindles are expensive.
- Modes, from cheapest-to-wake to deepest: *active* (servicing), *idle*
  (ready), *unloaded* (heads parked, platters spinning), *low-RPM*, and
  *standby* (spindle stopped, heads parked, only controller alive).
  Waking from standby costs several to tens of seconds and on the order of
  tens to hundreds of joules.
- **Break-even time** T_be: the minimum idle period for which spinning down
  saves energy. Ignoring transition time,
  `T_be ~ (E_down + E_up) / (P_idle - P_standby)`.
  An oracle that knows future idle periods spins down only for gaps longer
  than T_be and pre-spins before the next request. Practical policies use a
  fixed or adaptive idleness threshold.

> **Beyond EDBS:** setting the threshold equal to T_be is the classic
> ski-rental strategy and is 2-competitive against the oracle on energy;
> it says nothing about the latency penalty, which is what a database
> cares about.

- DRPM (Gurumurthi et al., IEEE Computer 2003) varies spindle speed instead
  of stopping; only prototypes exist.
- **MAID** (Colarelli and Grunwald, SC 2002): a large array in which most
  drives are spun down; a few always-on drives cache hot blocks so the
  passive drives see long idle gaps. **Popular Data Concentration** migrates
  hot blocks onto a subset of drives so the rest can sleep (EDBS cites
  Carrera, Pinheiro, Bianchini, ICS 2003, for this line of work). MAID is
  for archive and nearline, replacing or fronting tape.
- Energy proportionality: servers and much of the facility draw ~50% of
  peak power at ~1% load, so consolidation plus switching off idle units is
  the main lever; PUE = facility power / IT power, with best-in-class
  ~1.1-1.3.

Engine implications: a spun-down device turns a millisecond I/O into a
multi-second one, so (1) the optimizer/executor must know which partitions
are on sleepy media, (2) background work (checkpoint, statistics,
scrubbing, compaction, vacuum) must not wake cold drives on a timer, (3)
lay out data by temperature (time partitioning) so cold partitions stay
cold, and (4) client timeouts must tolerate spin-up.

## 7. Multitier storage, HSM and ILM (EDBS: Multitier Storage Systems; ILM; Storage Virtualization)

- **HSM** started on IBM mainframes in the 1970s: active data on disk,
  inactive data on tape, transparent recall with longer latency, migration
  driven by inactivity and thresholds (DFSMShsm lineage).
- The 2000s added nearline (high-capacity, slower) disks, giving the
  three-tier enterprise layout fast disk / nearline disk / tape; flash then
  became a tier above (or a cache in front of) disk, and automated
  sub-volume tiering moves extents dynamically.
- **ILM** generalises HSM: classify data by business value, define service
  levels per class, classify storage by performance/availability/cost, and
  migrate when value changes (e.g. current transactions online, last year
  on cheaper disks, older years kept only for compliance on tape).
- Storage virtualization can present a fast and a cheap device as one
  logical volume with automatic migration underneath.

Engine implications:

1. Tiering below the engine is invisible to the cost model; a "random read"
   may cost 100 us or 10 ms depending on where the extent lives. Prefer the
   engine to own placement (temperature-aware partitions) or at least to
   observe per-I/O latency and feed it back.
2. Block-level tiering tracks heat per extent, not per row; mixing hot and
   cold rows on a page defeats it. Cluster by access temperature (time
   partitioning, separate hot/cold column groups, separate index from heap).
3. Recall from tape/archive takes minutes; queries must be able to fail
   fast or be queued, never hold latches across a recall.

> **Beyond EDBS:** Cloud warehouses implement the same hierarchy in
> software: object storage as the capacity tier, local NVMe SSD as a cache
> of immutable files, DRAM above that (Snowflake, Dageville et al. SIGMOD
> 2016; Redshift RA3 managed storage). Teradata Virtual Storage migrates
> data between SSD and HDD by measured temperature. Because cached objects
> are immutable, cache coherence reduces to invalidating by file identity.

## 8. WORM and compliance storage (EDBS: Write Once Read Many; Storage Devices)

- **Physical WORM**: media that can only be written once (CD-R/DVD-R, WORM
  tape).
- **Logical WORM**: ordinary disks behind a controller or firmware that
  refuses overwrite/delete until a retention period expires; driven by
  regulation for financial records, e-mail, certificates; content-addressed
  storage (CAS) is a common implementation.
- Engine consequences: data on WORM cannot be vacuumed, compacted, or
  updated in place; design archive formats as append-only, immutable,
  self-describing files with their own index and checksums; deletion means
  retention expiry, so "right to be forgotten" style requirements need
  per-record encryption with key destruction instead.

> **Beyond EDBS:** S3 Object Lock offers governance and compliance
> retention modes and legal holds on object versions, which is the cloud
> form of logical WORM.

---

Sources: EDBS entries Disk (p.1143), I/O Model of Computation (p.1741),
Storage Devices (p.3726), Memory Hierarchy (p.2222), Disk Power Saving
(p.1144), Storage Power Management (p.3752), Massive Array of Idle Disks
(p.2211), Data Center Energy Efficiency (p.735), Multitier Storage Systems
(p.2446), Information Lifecycle Management (p.1946), Storage Virtualization
(p.3762), Write Once Read Many (p.4732), Storage Protocols (p.3756).
