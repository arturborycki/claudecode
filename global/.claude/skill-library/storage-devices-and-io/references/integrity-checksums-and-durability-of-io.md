# Integrity and durability of I/O: checksums, torn writes, fsync, O_DIRECT

Read this when choosing or implementing a checksum, deciding what a page
checksum must cover, defending against torn/lost/misdirected writes,
writing the code that makes a commit durable, or building crash and
corruption tests.

The page layout of the checksum field itself is in `page-and-file-format`;
the logging protocol that relies on these primitives (WAL rule, ARIES) is
in `transactions-and-recovery` / `recovery-and-durability`.

---

## 1. Failure taxonomy below the page layer

| Failure | What happens | Detected by | Repaired by |
|---|---|---|---|
| Media bit errors | bits flip on platter/cell | in-drive ECC (Reed-Solomon, BCH/LDPC) | ECC, else becomes unreadable sector |
| Latent sector error | sector unreadable on demand | read error from device; scrubbing | RAID/replica |
| Whole-device loss | drive or path gone | I/O errors, timeouts | RAID, erasure code, replica |
| Torn write | multi-sector write partly persisted at power loss | page checksum; torn-page bits | full-page image, doublewrite, CoW |
| Lost write | device acknowledged, data never persisted (cache lie, firmware bug) | version/LSN check against an independent record; parent-pointer checksums | redo from log, replica |
| Misdirected write | correct data written to wrong LBA | self-identifying page header (page id) in checksum | redo / replica; *two* pages damaged |
| Misdirected read | wrong LBA returned | page id check | retry, replica |
| Silent corruption in transit/DRAM/controller | data changed between host memory and media | end-to-end checksum, T10 PI | retry, replica |
| RAID write hole | data and parity disagree after crash | parity scrub; page checksum after reconstruction | resync, replica |
| Stale data after failover | an old replica/path serves old version | LSN/epoch checks | fencing |
| Operator or malicious alteration | intended-looking writes | audit, WORM, cryptographic MACs | backup |

Field data (Beyond EDBS): Bairavasundaram et al. measured latent sector
errors across a large fleet (SIGMETRICS 2007) and silent checksum
mismatches (FAST 2008); both are rare per disk but certain at fleet scale,
cluster spatially and temporally, and are more common on nearline drives.
Krioukov et al. ("Parity lost and parity regained", FAST 2008) show how
RAID schemes without per-block checksums propagate such errors.

## 2. Checksums and CRCs (EDBS: Checksum and Cyclic Redundancy Check Mechanism; Storage Protection)

**Checksum**: a fixed-width function of the data, stored with it and
recomputed on read. The simplest is XOR-folding fixed-size chunks; it is
weak - it misses any error that flips the same bit position an even number
of times and any reordering of chunks. Position-dependent sums (Fletcher,
Adler) catch reorderings but have weaker burst guarantees than CRCs.

**CRC** treats the message as a polynomial M(x) over GF(2). With generator
G(x) of degree m:

```
R(x) = (M(x) * x^m) mod G(x)          (m-bit remainder; polynomial division = shift + XOR)
T(x) = M(x) * x^m + R(x)              (transmitted/stored codeword; divisible by G)
check: T'(x) mod G(x) == 0 ?
```

Worked example (own numbers): G = x^3 + x + 1 = `1011`, M = `1101`.
`M * x^3 = 1101000`; dividing by `1011` leaves `001`; stored codeword
`1101001`. Flipping bits 1-2 (`0000110`) gives remainder `110` -> detected.
An error pattern equal to a multiple of G (e.g. `1011000`) leaves remainder
0 -> undetected. That is the general rule: a CRC misses exactly the error
polynomials divisible by G.

Guarantees for a well-chosen degree-m generator:

- every single-bit error; every burst of length <= m (EDBS stresses this:
  storage and links produce bursts more than independent bit errors);
- every odd number of bit errors if (x + 1) divides G;
- a random larger error escapes with probability ~2^-m;
- the minimum Hamming distance at a given message length depends on the
  polynomial (Koopman, DSN 2002, tabulates 32-bit CRCs).

> **Beyond EDBS - practical choices.**
>
> | Function | Width | Speed | Use |
> |---|---|---|---|
> | CRC-32C (Castagnoli) | 32 | very fast with SSE4.2 `crc32` / ARMv8 CRC instructions | iSCSI, ext4/Btrfs metadata, RocksDB/LevelDB blocks, most new engines |
> | CRC-32 (IEEE) | 32 | fast with carry-less multiply (PCLMULQDQ) | zlib/gzip, Ethernet |
> | xxHash64 / XXH3 | 64/128 | faster than CRC in software | RocksDB option, zstd frames; no burst guarantees, good randomness |
> | SHA-256 / BLAKE3 | 256 | slow / moderate | content addressing, dedup, adversarial settings (ZFS optional) |
> | CRC-16 (T10-DIF) | 16 | hardware | T10 PI guard tag |
>
> Implementation notes: use hardware instructions with 3-way interleaving
> for large buffers; software fallback slicing-by-8 tables; CRCs of
> concatenated buffers can be combined (zlib's `crc32_combine` idea) so
> pages can be checksummed in parallel pieces; standard CRC-32C uses an
> initial value and final XOR of 0xFFFFFFFF, which makes leading zero
> bytes matter. RocksDB/LevelDB store a *masked* CRC (rotated plus a
> constant) so that computing a CRC over data containing embedded CRCs
> stays robust.

### What a page checksum must cover

1. **The whole page except the checksum field** (or compute with the
   field zeroed). Checksumming only the header misses body corruption.
2. **The page's identity**: page number (and file/tablespace id) either
   stored in the header and covered, or mixed into the checksum seed.
   PostgreSQL mixes the block number into its page checksum, so a page
   written to the wrong block fails verification. Without this a
   misdirected write is a perfectly valid page in the wrong place.
3. **A version (page LSN)** so a stale-but-valid page can be recognised by
   comparing with an independent source (WAL, parent pointer, replica).
4. **Format version**, so a reader never interprets a future layout.

Pitfalls:

- *All-zero pages*: engines often treat an all-zero page as "newly
  allocated" and skip verification (PostgreSQL does). A lost write that
  leaves zeros, or a truncated file, is then accepted. Distinguish
  "allocated and never written" by metadata (free-space map/extent map),
  not by content.
- *Checksum computed before the last header mutation* (e.g. setting a hint
  bit or LSN after checksumming): every such page fails later. Compute the
  checksum on the exact bytes handed to the write call, on a private copy
  if other threads can still modify hint bits in the buffer.
- *Verifying after use*: verify before parsing any field; a corrupt slot
  array is an out-of-bounds read (see `page-and-file-format`).
- *Silently "fixing"*: on mismatch, retry the read once (transient path
  errors exist), then fail the page, report it, and repair from a replica
  or backup; never return its contents.

### End-to-end protection

> **Beyond EDBS:** The end-to-end argument (Saltzer, Reed, Clark, TOCS
> 1984) says only the endpoints can guarantee integrity; every hop's own
> CRC (link, controller, drive ECC) protects only that hop. T10 Protection
> Information (DIF) appends 8 bytes to each 512-byte or 4 KiB sector: a
> 16-bit guard CRC, a 16-bit application tag, and a 32-bit reference tag
> (low bits of the LBA) - so HBA, array and drive can each verify data
> *and* placement; DIX extends the guard to host memory. NVMe offers the
> same through per-LBA metadata. ZFS stores each block's checksum in its
> **parent** block pointer, forming a Merkle tree: lost and misdirected
> writes are detected because the parent expects a different checksum,
> something a checksum stored inside the block itself can never detect.
> Database analogues: store child page LSN or checksum in the parent node,
> or compare page LSNs against the WAL during replay and on standby (Oracle
> `DB_LOST_WRITE_PROTECT` compares block versions recorded in redo).

### Scrubbing

Background read-and-verify of all pages (and RAID parity) finds latent
errors while redundancy still exists. Rate-limit it against foreground
latency, persist its progress, and make it skip spun-down/cold media on a
policy, not on a timer that wakes them (`device-cost-models.md` section 6).

## 3. Torn writes and the atomic write unit

The device guarantees atomicity only for its **atomic write unit**: a
sector (512 B or 4 KiB) on most HDDs and SSDs (NVMe reports AWUPF; many
drives report one LBA). A database page of 8-32 KiB spans several units,
so a power loss mid-write can leave a mix of old and new sectors: a
**torn page**. Every layer between (FS, RAID, virtualization) can shrink,
never enlarge, the effective unit.

| Defence | How | Cost | Used by |
|---|---|---|---|
| Full-page image in WAL on first modification after a checkpoint | redo restores the whole page, then applies later records | WAL volume spikes after checkpoints | PostgreSQL `full_page_writes` |
| Doublewrite buffer | write dirty pages to a doublewrite area, fsync, then to home locations; on recovery repair torn home pages from it | ~2x page writes (sequential for the first copy) | InnoDB |
| Copy-on-write / shadow paging | never overwrite; switch a root pointer atomically | write amplification of path to root, GC | LMDB, ZFS, WAFL, Btrfs |
| Log-structured page store | pages appended, mapping table updated | GC | LLAMA/Bw-tree, LSMs |
| Torn-page detection bits | per-sector marker bits compared on read | detects only; needs separate repair | historical SQL Server option (now page CHECKSUM) |
| Device atomic writes of page size | rely on AWUPF >= page, aligned | only with a verified device and stack | some MySQL deployments disable doublewrite |

Detection is not repair: a checksum tells you the page is torn; you still
need an independent full copy (image in log, doublewrite copy, old CoW
version) to recover.

**Torn log tail.** WAL writes can tear too. Give each record (or log
block) its own CRC and an LSN/sequence; recovery scans forward and stops at
the first record whose CRC fails or whose LSN breaks continuity. Never
overwrite a log block that already contains acknowledged commits unless a
torn overwrite cannot destroy them: either write each flush to a fresh
block (padding the old one) or alternate between two copies of the last
block (ping-pong). Distinguish "end of log" from "corruption in the middle"
(a valid record found after a bad one means real damage - stop and alert,
do not truncate).

## 4. Durability semantics of the I/O stack

> **Beyond EDBS** (whole section; Linux unless stated).

Volatile places a "written" byte can sit: engine buffer -> OS page cache
-> file system journal/metadata -> block layer queue -> controller cache
(safe only if battery/flash-backed) -> drive write cache (safe only with
power-loss protection) -> media.

| Call | Guarantees on return | Does not guarantee |
|---|---|---|
| `write`/`pwrite` (buffered) | bytes copied to page cache | anything after a crash |
| `fsync(fd)` | file data and metadata durable, device cache flushed (barriers on) | the directory entry of a new or renamed file |
| `fdatasync(fd)` | data plus metadata needed to read it (e.g. size, block map) durable | timestamps |
| `O_DSYNC` / `O_SYNC` open flags | each write behaves like write + fdatasync / fsync | batching (each write pays a flush; use group commit) |
| `sync_file_range` | starts/waits for writeback of a range | durability: no metadata, no cache flush |
| `msync(MS_SYNC)` | dirty mapped pages written | control over *when* pages were written earlier |
| macOS `fsync` | data to drive | drive cache flush - needs `fcntl(F_FULLFSYNC)` |

Rules engines get wrong:

1. **New files and renames need a directory fsync.** Atomic replace is:
   write temp, fsync temp, rename over target, fsync the directory.
   Creating a WAL segment or SSTable without fsyncing the directory can
   lose the whole file after a crash although its contents were fsynced.
2. **fsync failure is not retryable.** After a writeback error Linux may
   mark the dirty pages clean (or drop them) and report the error once per
   file description (errseq-based since 4.13); a second fsync can then
   succeed although data are lost ("fsyncgate", 2018). PostgreSQL
   responded by PANICking on fsync failure and recovering from WAL
   (`data_sync_retry = off`); Rebello et al. ("Can applications recover
   from fsync failures?", USENIX ATC 2020) found the same bug class across
   many systems. Treat any fsync/fdatasync error, ENOSPC from thin
   provisioning, or EIO on write-back as fatal for that file: crash, then
   redo from the log or a replica.
3. **O_DIRECT is not durability.** It bypasses the page cache (no double
   buffering, predictable memory), but the data can still be in the drive
   cache and allocation metadata may be uncommitted. Still call
   fdatasync (or open with O_DSYNC, or use FUA writes via a raw device).
   Preallocate *and* zero-fill log files so later overwrites change no
   metadata; writing into fallocated "unwritten" extents converts them on
   first write, which is a metadata update requiring fdatasync.
4. **O_DIRECT alignment.** Buffer address, file offset and length must be
   multiples of the logical block size (commonly 512 or 4096; query it,
   e.g. `statx` with `STATX_DIOALIGN` on recent kernels or the device's
   logical block size). Misalignment returns EINVAL or silently falls back
   to buffered I/O on some file systems. Never mix buffered and direct I/O
   on the same file region without understanding the coherency rules.
5. **No ordering without waiting.** The kernel and device may reorder
   in-flight writes. To make A durable before B is written (WAL before
   data page, data before commit record pointing to it), wait for A's
   completion *and* flush if A must be durable, then submit B. io_uring's
   linked SQEs order *submission*, not persistence; add an explicit fsync
   op in the chain.
6. **mmap for writing breaks WAL.** The OS can write a dirty mapped page
   at any time, before its log record is durable, and I/O errors surface
   as SIGBUS. See Crotty, Leis, Pavlo, "Are you sure you want to use MMAP
   in your database management system?" (CIDR 2022).
7. **The device can lie.** Without PLP, a drive with write cache enabled
   needs real flushes; some consumer devices acknowledge flushes early.
   Validate with power-cut testing before trusting a platform.

Commit latency follows: one log flush per group commit. HDD: rotational
latency-bound (ms) unless a non-volatile controller cache absorbs it; PLP
SSD: tens of microseconds; consumer SSD: flush can take milliseconds;
remote/replicated storage: a network round trip or quorum.

## 5. WORM, retention, and secure deletion

Physical WORM (write-once media) vs logical WORM (controller-enforced
immutability with keys/retention clocks) - see `device-cost-models.md`
section 8. Integrity implications: WORM guarantees non-alteration only of
what reached it; pair it with cryptographic hashes or MACs computed at
ingest for evidentiary use. Persistent media (flash, PCM) retain data after
logical deletion: the FTL keeps old copies until GC, so "delete" is not
"erase" - use encryption with key destruction (crypto-erase) or the
device's sanitize command.

## 6. Testing integrity and durability

- **Corruption injection**: flip random bits, zero whole pages, swap two
  pages (misdirected write), replace a page with an older valid version
  (lost write), truncate files, tear pages at every sector boundary.
  Assert the engine detects each case, never returns wrong data, and
  repairs where a redundant copy exists.
- **Crash-consistency recording and replay**: record the block-level
  write/flush stream (Linux `dm-log-writes`) and replay every prefix
  consistent with flush ordering, then run recovery and invariant checks.
  ALICE (Pillai et al., OSDI 2014) and CrashMonkey (Mohan et al., OSDI
  2018) systematise this for file-system-level persistence assumptions.
- **Error injection**: `dm-flakey`/`dm-error` or a fault-injecting VFS shim
  to return EIO/ENOSPC from write and fsync; assert the engine crashes and
  recovers instead of continuing.
- **Real power cuts** on each hardware/firmware platform, with a client
  that logs acknowledged commits to another machine and a verifier that
  checks every acknowledged commit survived.
- **Model checks**: checksum unit tests against published CRC-32C test
  vectors (`"123456789"` -> `0xE3069283`), CRC combine equals CRC of
  concatenation, page round trip preserves checksum, verification fails
  for every single-bit flip of a sample page.

---

Sources: EDBS entries Checksum and Cyclic Redundancy Check Mechanism
(p.423), Storage Protection (p.3754), Redundant Arrays of Independent Disks
(p.3135), Storage Protocols (p.3756), Write Once Read Many (p.4732), Data
Center Energy Efficiency (p.735), Storage Access Models (p.3722). Sections
marked Beyond EDBS draw on the papers and system documentation named
inline.
