# RAID, erasure coding, storage networks, virtualization, object storage

Read this when the engine sits on a RAID set, a SAN/NAS volume, an LVM or
virtualized volume, a distributed or SAN file system, or an object store,
and you need to know what the layer below does to write cost, ordering,
atomicity, failure behaviour and visibility.

---

## 1. RAID (EDBS: Redundant Arrays of Independent Disks; Storage Protection)

RAID combines disks with control software that spends part of the capacity
on redundancy so that data survive a disk or path failure. Two mechanisms:
**striping** (cut the logical address space into fixed-size *stripe units*
laid round-robin across disks) and **redundancy** (mirroring or parity).
The name comes from Patterson, Gibson and Katz, SIGMOD 1988 ("Inexpensive"
then, "Independent" now); EDBS notes a 1978 patent (Ouchi) already covered
the parity-recovery idea behind level 5.

| Level | Layout | Usable fraction (n disks) | Survives | Small random write cost | Notes |
|---|---|---|---|---|---|
| 0 | striping only | 1 | nothing | 1 write | pure parallelism |
| 1 | mirror | 1/2 (or 1/k) | 1 per pair | 2 writes | reads can go to either copy |
| 2 | bit-striped + Hamming ECC | low | 1 | full-array | historical; drives already have ECC |
| 3 | small stripe unit + parity disk | (n-1)/n | 1 | full-array | every I/O touches all disks: high BW, one I/O at a time |
| 4 | large stripe unit + dedicated parity disk | (n-1)/n | 1 | 4 I/Os, parity disk hot | parity disk serialises small writes |
| 5 | large stripe unit, rotated parity | (n-1)/n | 1 | 4 I/Os | standard parity RAID |
| 6 (Beyond EDBS) | two parities (P+Q, Reed-Solomon) | (n-2)/n | 2 | 6 I/Os | needed for large drives |
| 10 (Beyond EDBS) | stripe over mirrors | 1/2 | 1 per mirror | 2 writes | OLTP default when budget allows |

The stripe-unit size decision is what separates 3 from 4/5: small units
spread *each* request over all disks (high bandwidth per request, no
concurrency); large units let *independent* small requests proceed on
different disks in parallel (high IOPS).

### The small-write penalty

Updating one stripe unit D on RAID-5 must keep `P = D1 xor D2 xor ... xor Dk`
correct. Two ways:

```
read-modify-write:   read D_old, read P_old           (2 reads)
                     P_new = P_old xor D_old xor D_new
                     write D_new, write P_new          (2 writes)  -> 4 I/Os
reconstruct-write:   read the other k-1 data units     (k-1 reads)
                     P_new = xor of all data
                     write D_new, write P_new          (2 writes)
full-stripe write:   compute P from the k new units; write k+1 units, 0 reads
```

Controllers choose the cheaper; for wide stripes RMW wins for single-unit
updates. RAID-6 RMW is 3 reads + 3 writes. Effective random-write IOPS:

```
IOPS_write ~ n * IOPS_disk / penalty      penalty: RAID0=1, RAID1/10=2, RAID5=4, RAID6=6
```

Example: 8 x 200-IOPS disks. RAID-10: 800 random write IOPS; RAID-5: 400;
RAID-6: ~267. Reads: ~1,600 for all.

Engine implications: (1) WAL and sequential bulk writes should be
full-stripe sized and aligned (stripe width = stripe unit x data disks) so
parity RAID costs nothing extra; (2) random page write-back on parity RAID
costs 2-3x a mirror; (3) a controller write-back cache with battery/flash
backing absorbs the penalty and can coalesce partial stripes - but only if
it is genuinely non-volatile.

> **Beyond EDBS - the write hole.** If power fails after the data unit is
> written but before parity (or vice versa), the stripe's parity is wrong.
> Nothing notices until a disk fails and reconstruction silently produces
> garbage for an *unrelated* block in that stripe. Defences: non-volatile
> controller cache, a parity/stripe journal (e.g. Linux md journal or
> partial parity log), copy-on-write full-stripe writes (ZFS RAID-Z), and a
> parity resync after unclean shutdown. Engine-level page checksums detect
> the result but cannot repair it unless another replica exists.

### Degraded mode, rebuild, reliability

- With one disk failed, each read of the missing disk becomes reads of all
  survivors in the stripe: read load on survivors roughly doubles for
  RAID-5. Plan capacity for degraded mode, not for the healthy array.
- Rebuild time ~ disk capacity / rebuild rate, now hours to days for
  multi-TB drives; during it a second failure or an unreadable sector on a
  survivor loses data. This is why RAID-6 or erasure codes replaced RAID-5
  for large drives, and why background scrubbing (read-verify) matters:
  it finds latent sector errors while redundancy still exists.
- Patterson et al.'s independent-failure estimate for n disks in groups of
  G with repair time MTTR is roughly `MTTDL ~ MTTF^2 / (n * (G-1) * MTTR)`.
  It is optimistic: failures correlate (same batch, same enclosure, same
  firmware, rebuild stress).
- Parity declustering (Holland and Gibson, ASPLOS 1992) spreads stripes
  over more disks than the stripe width so rebuild load is shared; HP
  AutoRAID (Wilkes et al., TOCS 1996) migrated data between mirrored and
  RAID-5 storage by activity. Survey: Chen, Lee, Gibson, Katz, Patterson,
  ACM Computing Surveys 1994.

### Erasure coding in scale-out storage (EDBS: Object Storage Protocol)

EDBS notes scale-out object stores replace RAID-5 with newer erasure codes.

> **Beyond EDBS:** A (k, m) Reed-Solomon code stores k data and m parity
> fragments on k+m nodes, survives any m losses, costs (k+m)/k space, but
> repairing one fragment reads k fragments (repair traffic is the
> bottleneck). Local Reconstruction Codes (Huang et al., USENIX ATC 2012,
> Azure) add local parities so common single failures repair from a small
> group. Erasure-coded writes are expensive for small objects, so systems
> replicate small/hot data and erasure-code large/cold data.

### Layered protection (EDBS: Storage Protection)

| Layer | Protects against | Does not protect against |
|---|---|---|
| Sector ECC (Reed-Solomon in the drive) + CRC | bit errors on media | whole-drive loss, misdirected/lost writes |
| RAID / erasure code | device loss | logical corruption, operator error, site loss, write hole |
| Volume/LVM/FS replication, snapshots | device and some logical errors | site loss (if local) |
| Remote replication (sync/async) | site loss | logical corruption (replicated faithfully) |
| DBMS replication (primary/standby, multi-master) | server + storage loss | application bugs |
| Backup / point-in-time copy / WORM | logical corruption, ransomware | recent data (RPO) |

EDBS notes that IBM's 3990 controller (1980s) already kept dual copies on
separate media. Every layer is necessary; none subsumes another.

## 2. Storage network architectures (EDBS: Storage Network Architectures; DAS; NAS; SAN; Storage Protocols; IP Storage; Storage Consolidation)

**Server-centric** systems attach storage to one server (parallel SCSI bus:
at most ~25 m and 15 devices per bus); other servers reach it only through
that server over the LAN, so management is duplicated and capacity cannot
be pooled. **Storage-centric** systems put storage on a network every
server can reach, enabling consolidation, shared backup, and offloaded
copy functions.

| | DAS | SAN | NAS | Object store |
|---|---|---|---|---|
| Abstraction | block | block (SCSI LUN) | file (POSIX-ish) | object (whole-object GET/PUT) |
| Typical protocols | SAS, SATA, NVMe | FCP (Fibre Channel), iSCSI, NVMe-oF | NFS, SMB/CIFS | HTTP REST (S3-style) |
| Who owns FS metadata | host | host (or SAN FS cluster) | NAS server | the store |
| Sharing granularity | none | LUN (block namespace) | file namespace | bucket/key namespace |
| DB concerns | simplest semantics | multipath, fencing, ordering on failover | locking, cache coherence, sync semantics, O_DIRECT support | no in-place update, request latency/cost |

Protocol details worth knowing:

- **Fibre Channel** layers: FC-0 media, FC-1 8b/10b encoding and link
  control, FC-2 framing, sequences/exchanges and flow control, FC-3 common
  services, FC-4 mappings such as FCP (SCSI over FC). Credit-based
  (reservation) flow control means frames are not dropped, unlike TCP's
  loss-and-retry; HBAs offload protocol processing.
- **iSCSI** carries SCSI commands in TCP; the host side is the *initiator*,
  the storage side the *target*. Cheap, routable, and uses existing IP
  security and management; overhead reduced by offload NICs, interrupt
  coalescing, zero-copy and RDMA extensions (iSER, iWARP).
- **iFCP / FCIP** tunnel FC frames over IP to join remote "SAN islands".
- Parallel SCSI/ATA gave way to serial SAS/SATA. Keep the *command set*
  (SCSI vs ATA) separate from the *transport*. Historic ATA gaps that SCSI
  lacked - no command queueing, few devices per channel, no data
  checksums, no hot-plug, no bus-master DMA - were closed by later
  revisions and SATA.
- **NAS**: NFS (IETF; NFSv4 is stateful, merges the old lock/mount/status
  side protocols into one, and adds delegations that let clients cache
  aggressively), SMB/CIFS (Windows; Samba implements it on Unix). A *NAS
  gateway/head* is a diskless file server that exports files from SAN
  block storage. Clustered NAS removed the old scalability gap with SAN.

> **Beyond EDBS:** NVMe over Fabrics (RDMA, TCP, FC transports) is the
> modern block-network protocol for flash, keeping per-core queues
> end-to-end and cutting latency well below iSCSI.

### Storage-side functions (EDBS: Storage Network Architectures; Intelligent Storage Systems)

LAN-free backup (backup server copies over the SAN), server-free backup /
third-party copy (array or switch copies directly), snapshots/point-in-time
copies, synchronous and asynchronous remote replication, data-format/code
conversion between mainframe and open systems.

- **Synchronous remote replication** acknowledges a write only after the
  remote array has it: zero data loss, but every write pays the WAN round
  trip. **Asynchronous** acknowledges locally: no latency penalty, but the
  remote copy lags and may lose recent writes, and *write order across
  volumes* must be preserved or the remote database is unrecoverable.
- Engine rule: a database spanning several LUNs (data, WAL, temp) must be
  replicated or snapshotted as one **consistency group**, preserving
  dependent-write order across all of them; snapshotting the data LUN and
  the log LUN at different instants yields a torn database even though
  each LUN is crash-consistent.

## 3. SCSI targets, LUNs, masking, multipathing (EDBS: SCSI Target; LUN; LUN Mapping; Multi-pathing)

- A **SCSI target** (array controller, JBOD, virtualization appliance)
  exposes one or more logical units; the host OS maps each to a **LUN**.
  The same array volume can have different LUN numbers on different hosts;
  the transport defines initiator/target identifiers.
- **LUN mapping** assigns LUN numbers to volumes (some applications need
  specific numbers); **LUN masking** on the controller restricts which
  initiators see which volumes; FC switch **zoning** restricts which ports
  can talk at all.
- **Multipathing**: several initiator-target paths for fault tolerance and
  throughput, configured *active-active* (all paths carry I/O, optionally
  load-balanced) or *active-standby*. The multipath driver must collapse
  paths so a volume is not seen as two devices; mounting the "two" devices
  independently corrupts the volume. Drivers were historically
  vendor-specific; generic multi-vendor drivers followed.

> **Beyond EDBS:** On Linux, dm-multipath with ALUA (asymmetric logical
> unit access) path priorities is standard. Path failover can stall I/O
> for tens of seconds while timeouts expire; writes in flight on the failed
> path are retried on another, so the engine must never assume an order
> between writes it has not waited for. Shared-disk clusters need **I/O
> fencing** (e.g. SCSI-3 persistent reservations) so a node that lost
> cluster membership cannot keep writing.

## 4. Volume management and storage virtualization (EDBS: Logical Volume Manager; Storage Virtualization; Software-Defined Storage)

LVM vocabulary: physical volumes (PV, disks or partitions) are cut into
physical extents (PE); one or more PEs form a logical extent (LE), which
may be a plain mapping or striped/mirrored across PEs; LEs pool into a
volume group (VG); a logical volume (LV) is a set of LEs, again possibly
striped, and can often be grown or shrunk online.

SNIA's shared storage model puts **block aggregation** (concatenate,
stripe, mirror) in three possible places: host (LVM), network (switch or
appliance), device (array). Virtualization can be stacked at all three,
can span sites for disaster recovery, and can merge fast and cheap devices
into one volume with automatic migration (tiering).

Engine implications of stacked virtualization:

1. **Alignment**: engine extent -> FS block -> LV stripe -> array stripe
   unit -> device sector/IU. One misaligned layer turns every page write
   into two device writes or a RAID RMW. Verify end to end.
2. **Stacked striping** (engine striping over LVM striping over RAID
   striping) can correlate badly: every logical stripe lands on the same
   physical disk. Stripe at one layer, or choose coprime widths.
3. **Thin provisioning** promises capacity it does not have; the array can
   fail a write with an out-of-space error long after the engine allocated
   the extent. Treat such errors like fsync failure (fatal, see the
   integrity file).
4. **Copy-on-write snapshots** make the first write to each region after a
   snapshot slower (copy-out) and fragment sequential layout.
5. **Observability**: physical location is several mappings away. Storage
   management tools (EDBS: Storage Management, Storage Resource Management)
   discover devices, build physical and logical topology (HBA ports, switch
   ports, LUNs, zones), collect performance counters (SNMP, SMI-S), and
   map applications to devices. An engine should export per-file and
   per-tablespace I/O latency so this mapping can be closed.

**Software-defined storage** separates the control plane (policy-driven
provisioning via APIs) from a data plane running on commodity servers,
often as VMs under a cloud orchestrator, trading a little hypervisor
overhead for agility and lower hardware margins.

> **Beyond EDBS:** Ceph (Weil et al., OSDI 2006) is the canonical
> open-source SDS: a RADOS object layer with CRUSH pseudo-random placement
> so clients compute object locations without a lookup service, exposing
> block (RBD), file (CephFS) and object (RGW) interfaces.

## 5. How a DBMS consumes storage (EDBS: Storage Access Models)

Tables live in tablespaces; tablespaces draw space from **containers**
(files, directories, or raw devices); separate tablespaces for data,
indexes, temp, log, and catalog.

| Model | What it is | Wins | Costs |
|---|---|---|---|
| System-managed (files in a file system) | FS allocates on demand | just-in-time space (good for temp), FS backup/migration tools | FS journaling, fragmentation as FS ages, double buffering, per-file concurrency limits |
| Database-managed raw devices | engine owns block devices | no FS overhead, no double buffering, dedicated space, add containers dynamically | operational tooling, harder backup |
| Hybrid: database-managed files | engine manages preallocated files with direct I/O | nearly raw performance, FS tools still work | size bounded by the file |

> **Beyond EDBS:** Mainstream practice today is the hybrid: large
> preallocated files (fallocate) on XFS/ext4 opened with O_DIRECT, or a
> volume manager owned by the database (Oracle ASM). PostgreSQL is a
> notable exception: buffered I/O through the OS page cache, with
> asynchronous/direct I/O work arriving in recent releases.

## 6. Distributed and SAN file systems (EDBS: Distributed File Systems; SAN File System; NASD; Active/Intelligent Storage)

- **Architectures**: client-server (a "single" server abstraction, maybe
  backed by several servers) vs **parallel** (files striped across many
  servers and their disks - RAID over the network - for parallel
  bandwidth and faster recovery).
- **Naming**: location transparency (name reveals no location) is weaker
  than location independence (file can move without renaming). Most DFSs
  give only transparency; AFS gives independence.
- **Access**: syscalls intercepted in the kernel and turned into RPCs
  (TCP/UDP). **Caching** (block size, total size, memory vs local disk)
  saves network and disk I/O but raises the same consistency trade-off as
  replication. AFS caches whole files locally, writes back on close, and
  uses server *callbacks* to invalidate client caches; NFS was stateless
  until NFSv4.
- **Design for failure as the norm**: replication (sync or async),
  locality-aware scheduling of computation onto replicas (GFS, HDFS).
- Systems: NFS (Sandberg et al. 1985), AFS (Howard et al. 1988), Lustre
  (2003), GPFS (Schmuck and Haskin, FAST 2002: shared-disk, POSIX,
  distributed metadata and locking), Frangipani (Thekkath et al. SOSP
  1997), GFS (Ghemawat et al. SOSP 2003: 64 MB chunks, write-once
  read-many, sequential reads), HDFS (Shvachko et al. MSST 2010:
  single NameNode metadata server), MapR-FS and GPFS-FPO (POSIX,
  distributed metadata, HDFS-compatible).
- **SAN (shared-disk) file systems** let many servers read/write blocks of
  one volume directly over the SAN with no data-path server. They need
  cross-server coherency: cache invalidation messages and distributed
  mutual exclusion on writes.
- **NASD / OSD** (Gibson et al., SIGMETRICS 1997; standardised as ANSI T10
  SCSI OSD, INCITS 400-2004): devices store variable-size *objects* with
  attributes; a central policy server handles namespace and authorization
  (issuing capabilities), and clients move data directly to/from devices,
  scaling bandwidth past the controller bottleneck. Object storage is the
  third abstraction beside block and file; content-addressable storage is
  another object interface.
- **Active storage / intelligent disks** (Riedel, Gibson, Faloutsos VLDB
  1998; Keeton, Patterson, Hellerstein SIGMOD Record 1998; Acharya, Uysal,
  Saltz ASPLOS 1998) run filtering, aggregation, or sort phases on
  processors in the drives, reducing interconnect traffic for scans. They
  descend from 1970s-80s database machines (CASSM, RAP filter processors;
  GRACE, GAMMA parallel machines), which lost to commodity hardware.

> **Beyond EDBS:** the idea won at the storage-server level rather than in
> drives: Oracle Exadata storage cells evaluate predicates and keep
> per-region min/max "storage indexes"; cloud warehouses push filters and
> projection into the scan of object-store files; SNIA's computational
> storage work standardises drive-side compute. Database-on-DFS rules:
> verify locking and sync semantics before running a WAL on NFS; on
> HDFS-like stores (append-only, no random write) use immutable files and
> LSM-style organisation.

## 7. Object storage protocols and the cloud warehouse substrate (EDBS: Object Storage Protocol; Storage Grid)

EDBS: object protocols are RESTful (GET/PUT), objects are normally not
updated (an update creates a new object), no POSIX semantics, key-value is
a special case; small-object and large-object stores need different
architectures; scale-out object stores run on clusters of servers with
directly attached disks, use erasure coding, and keep metadata eventually
consistent.

> **Beyond EDBS** (S3 behaviour as of 2026; check current documentation
> before relying on limits):
>
> - Consistency: S3 provides strong read-after-write consistency for PUTs
>   and DELETEs and for LIST since December 2020. Conditional writes
>   (If-None-Match create-only, and If-Match on ETag) were added in 2024,
>   enabling atomic "create if absent" commits without an external lock.
> - No in-place update, no append on standard buckets, no atomic rename
>   (rename = copy + delete; S3 Express One Zone directory buckets add
>   append and rename, standard buckets do not). Multipart upload: parts of
>   5 MiB to 5 GiB (last part may be smaller), up to 10,000 parts; maximum
>   object size was 5 TB until December 2025, when it rose to 50 TB; ranged
>   GET reads any byte range.
> - Latency and throughput: first-byte latency is tens of milliseconds;
>   a single connection gives far less than a NIC's bandwidth, so engines
>   issue many concurrent ranged GETs of several MiB each (Durner, Leis,
>   Neumann, "Exploiting cloud object storage for high-performance
>   analytics", PVLDB 2023, found ~8-16 MiB requests and many in flight
>   saturate high-bandwidth instances).
> - Request rate scales per key prefix (documented as thousands of
>   GET/HEAD and PUT/POST/DELETE per second per prefix); requests cost
>   money, so the cost model counts requests as well as bytes.
>
> Engine designs built on these semantics:
>
> - **Immutable files + atomic metadata swap**: table formats (Iceberg,
>   Delta Lake - Armbrust et al., PVLDB 2020; Hudi) write new data and
>   manifest files, then commit by atomically replacing one pointer (a
>   catalog compare-and-swap or a conditional PUT). Snapshot isolation
>   falls out of immutability; garbage collection of unreferenced files is
>   a separate, delayed process.
> - **Columnar files sized to the store**: row groups/stripes of tens to
>   hundreds of MiB, footers read first with one ranged GET, column chunks
>   coalesced into large ranged reads.
> - **Caching tier**: local NVMe and DRAM caches keyed by immutable file
>   identity (Snowflake, Dageville et al. SIGMOD 2016).
> - **Log-is-the-database** designs put the WAL, not pages, on a
>   replicated storage service (Aurora, Verbitski et al. SIGMOD 2017: six
>   copies across three AZs, 4/6 write and 3/6 read quorums; Socrates,
>   Antonopoulos et al. SIGMOD 2019) and materialise pages there.

Storage grids (EDBS: Storage Grid; Venugopal, Buyya, Ramamohanarao, ACM
Computing Surveys 2006) generalise this to wide-area federations:
hierarchical, monadic or federated organisation; bulk transfer with
GridFTP-style parallel/striped streams and restartable transfers; replica
placement driven by response-time, load or consistency objectives; and
moving computation to data when the data are too big to copy.

---

Sources: EDBS entries Redundant Arrays of Independent Disks (p.3135),
Storage Protection (p.3754), Storage Network Architectures (p.3741), Direct
Attached Storage (p.1119), Network Attached Storage (p.2490), Storage Area
Network (p.3724), Storage Protocols (p.3756), IP Storage (p.2041), Storage
Consolidation (p.3725), SCSI Target (p.3326), Logical Unit Number
(p.2152), Logical Unit Number Mapping (p.2153), Multi-pathing (p.2419),
Logical Volume Manager (p.2153), Storage Virtualization (p.3762),
Software-Defined Storage (p.3545), Storage Management (p.3730), Storage
Resource Management (p.3759), Storage Access Models (p.3722), Distributed
File Systems (p.1186), SAN File System (p.3274), Network Attached Secure
Device (p.2489), Intelligent Storage Systems (p.2009), Active Storage
(p.37), Object Storage Protocol (p.2539), Storage Grid (p.3728).
