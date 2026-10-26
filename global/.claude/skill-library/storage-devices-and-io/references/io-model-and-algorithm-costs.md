# The external-memory I/O model and how to cost algorithms with it

Read this when you must predict or compare the I/O cost of an access
method or operator (index vs scan, sort/merge fan-in, hash-join partition
count, B-tree vs LSM vs B^epsilon), when choosing block/buffer sizes from
device parameters, or when reviewing a cost model's assumptions.

---

## 1. The model (EDBS: I/O Model of Computation)

For data-intensive work the meaningful cost is the number of block
transfers between a small fast memory and a large slow store, because a
transfer's positioning cost (seek + rotation on disk) dwarfs both the
per-byte transfer and the CPU work: reading a few bytes costs about as
much as reading a block. Hence data are stored and moved in **blocks
(pages)**, and an algorithm is charged one unit per block read or written.

Parameters (Aggarwal and Vitter, CACM 1988):

| Symbol | Meaning |
|---|---|
| N | problem size (items) |
| M | internal memory (items), M < N |
| B | items per block, 1 <= B <= M/2 |
| n = N/B, m = M/B | sizes in blocks |
| D | independent disks (parallel disk model, Vitter and Shriver 1994) |
| K | output size (items) |

Three engine levers fall straight out of the model (EDBS lists them):
**buffer** recently used pages so re-references are free; **transfer runs
of consecutive pages** ("buckets", read-ahead) because neighbours are
likely next; and **organise data into page-sized index nodes** so a search
touches few pages.

## 2. Fundamental bounds

| Problem | I/O complexity | Engine counterpart |
|---|---|---|
| Scan | Theta(n) | sequential scan, aggregation, filter |
| Sort | Theta(n log_m n) | external merge sort, sort-merge join, index build |
| Permute | Theta(min(N, n log_m n)) | unclustered fetch of all rows in some order |
| Search (point) | Theta(log_B N) | B+-tree lookup |
| Range query | Theta(log_B N + K/B) | B+-tree range scan on clustered data |
| Batched updates (buffer tree, Arge 1995/2003) | O((1/B) log_m n) amortised per op | bulk loading, batched index maintenance, LSM-like buffering |
| Priority queue | O((1/B) log_m n) amortised | external top-k, event simulation |

Notes:

- `n log_m n` is "a small constant times n" in practice: with m in the
  thousands, log_m n is 1-3 for any realistic table. Sorting is "a few
  scans", which is why sort-based plans stay competitive.
- Permuting is as hard as sorting unless N < n log_m n, i.e. unless blocks
  are tiny; fetching rows one at a time in arbitrary order costs N, which
  is the unclustered-index disaster.
- The binary-tree vs B-tree contrast in EDBS: a balanced binary tree over a
  million records laid on disk costs about log2(10^6) = 20 page reads per
  search; a B+-tree with ~100 entries per node needs 3.

### Worked sizing: B+-tree height

16 KiB pages, 16-byte (key, pointer) entries -> 1,024 slots, ~700 at 70%
fill. For 10^9 keys: ~1.43M leaves, ~2,040 level-2 nodes, 3 level-1 nodes,
1 root: height 4. All inner levels together are ~33 MB, so they stay
cached and a point lookup costs **one** random I/O. Fanout matters mostly
for how much inner-node memory you need, not for height. (Prefix/suffix
truncation raises fanout - `storage-and-indexing`.)

## 3. Costing classic operators

Notation: `n_R`, `n_S` blocks; m memory blocks; one I/O = one block. Use the
device file to convert block counts to time.

**External merge sort.**

```
runs      r0 = ceil(n / m)              (replacement selection: ~ n / 2m runs on random input)
fan-in    F  = floor(m_io / b) - 1      b = blocks per run buffer (b > 1 for sequential prefetch)
passes    P  = 1 + ceil(log_F r0)
I/O       2 n P   (read + write per pass; drop the final write if pipelined)
```

The crucial device interaction: the merge reads F runs *interleaved*, so
each buffer refill is a random positioning event. Per-run buffers must be
large enough to amortise positioning (HDD: MiB-scale; SSD: hundreds of KiB
with several outstanding reads; object store: several MiB with many
concurrent ranged GETs). Bigger buffers lower F, which may add a pass.
Example: 1 TiB input, 16 GiB memory -> 64 runs; F = 64 with 256 MiB per run
is one merge pass, total I/O 4 TiB of transfer at near-sequential speed.
Using 8 KiB buffers instead keeps F huge but turns the merge into random
8 KiB reads - on one HDD about 0.6 MB/s, roughly 250x slower.

**Grace / hybrid hash join.** Partition both inputs into k <= m - 1
buckets, then build/probe each bucket pair. Cost ~3(n_R + n_S) (read,
write partitions, read again) if each build partition fits: needs roughly
`m > sqrt(f * n_S)` blocks (f = hash-table fudge factor, n_S the build
side). For a 1 TiB build side with 1 MiB I/O units that is about 1,000
blocks (~1 GiB) of memory. Recursive partitioning adds 2(n_R + n_S) per
extra level; hybrid hash keeps one partition in memory and saves its I/O.

**Block nested loops.** `n_R + ceil(n_R / (m - 2)) * n_S`; only for small
outer inputs or non-equi joins.

**Index nested loops / unclustered index fetch.** One random I/O per
matching row (minus buffer hits). Expected distinct blocks touched when
fetching k rows scattered uniformly over m_t blocks (Cardenas):
`m_t * (1 - (1 - 1/m_t)^k)`; Yao (CACM 1977) gives the exact
without-replacement form. Sorting the RIDs first (bitmap heap scan) turns
this into one ordered pass over the touched blocks.

**Index vs scan crossover** (selectivity s* where an unclustered index stops
paying):

```
s* ~ (cost to scan one row sequentially) / (cost of one random row fetch)
```

| Device / mode | random fetch | scan cost per row (8 KiB page, 100 rows) | s* |
|---|---|---|---|
| 7,200 RPM HDD, QD1 | 12.7 ms | ~0.55 us (150 MB/s) | ~0.004% |
| NVMe SSD, QD1 | ~80 us | ~0.03 us (3 GB/s) | ~0.03% |
| NVMe SSD, deep queue (~500k IOPS) | ~2 us amortised | ~0.03 us | ~1.4% |

The device, *and how many I/Os the executor keeps in flight*, move the
crossover by orders of magnitude. Optimizer cost constants (e.g.
PostgreSQL `random_page_cost` = 4 vs `seq_page_cost` = 1 by default,
commonly lowered toward ~1.1-1.5 on SSD) encode exactly this and are
wrong whenever the executor's I/O concurrency differs from what the
constant assumed. Buffer hit ratios reduce the random term further.

## 4. Write-optimised structures in the same model

Costs per operation, L = number of levels, T = size ratio/fanout:

| Structure | Insert/update | Point query | Range (K results) |
|---|---|---|---|
| B+-tree (in place) | O(log_B N) random I/Os (inner levels cached: ~1 read + 1 write) | O(log_B N) | O(log_B N + K/B) |
| B^epsilon-tree (Brodal and Fagerberg SODA 2003) | O(log_B N / (epsilon B^(1-epsilon))) amortised | O(log_B N / epsilon) | O(log_B N / epsilon + K/B) |
| Buffer tree (Arge) | O((1/B) log_m n) amortised, batched | batched only | batched |
| LSM, leveling | O(T L / B) amortised | O(L) runs probed; ~1 I/O with Bloom filters | O(L + K/B) |
| LSM, tiering | O(L / B) amortised | O(T L) runs probed | O(T L + K/B) |

epsilon = 1 recovers the B-tree; epsilon = 1/2 gives inserts ~sqrt(B)
times cheaper for a constant-factor slower query. Bloom-filter allocation
across LSM levels (Monkey, Dayan, Athanassoulis, Idreos SIGMOD 2017)
changes the point-query term. The model counts *block transfers*; on flash
add the device-level multiplier (`ssd-and-flash-for-db-engines.md`), and on
parity RAID the small-write penalty (`raid-and-storage-networks.md`).
Details of compaction policy belong to `lsm-storage`.

## 5. Refinements that matter in practice

**Random vs sequential (affine / seek-plus-transfer model).** EDBS notes a
more accurate model must charge random and sequential I/O differently.
Charge a k-block transfer as `s + k t` (setup s, per-block t). Then:
choose transfer sizes near the half-bandwidth point `k* ~ s/t`; count
*positioning events*, not blocks. Bender et al. ("Small refinements to the
DAM can have large consequences for data-structure design", SPAA 2019)
show in such an affine model that B-tree node size is a genuine trade-off
(large nodes waste transfer on point queries) while B^epsilon-trees stay
efficient with large nodes - consistent with engines using big LSM/B^e
buffers and modest B-tree pages.

**Asymmetric read/write costs.** On flash and PCM, charge writes w > 1
times reads (and include device WA). Algorithms that trade extra reads for
fewer writes (write-limited sorts, lazy merges) can win.

**Parallelism.** Parallel disk model: D disks, one block from each per
step. Plain striping makes D disks behave as one disk with block size DB,
which is optimal for scans but loses a factor in sorting when D is large
(the log base becomes M/(DB)); independent-disk algorithms (distribution
sort with careful bucket placement, randomized cycling) recover the bound.
For SSDs the analogue is queue depth: cost of k independent random reads
~ ceil(k / QD) * latency, so batching independent probes is as important
as reducing their number.

**Memory hierarchy as another level (EDBS: Memory Hierarchy).** Apply the
same model with B = cache line (64 B typical) or OS page (TLB level) and M
= cache capacity; misses come in sequential and random flavours with
different latencies. Cache-conscious algorithms (radix-partitioned hash
joins with fan-out bounded by TLB entries and cache lines; CSB+-trees with
node = few cache lines) are I/O-model algorithms one level up. See
`device-cost-models.md` section 5 for the cost formula.

**Cache-oblivious algorithms** (Frigo, Leiserson, Prokop, Ramachandran,
FOCS 1999) achieve the optimal bounds for every (M, B) simultaneously
without knowing them: van Emde Boas tree layout gives O(log_B N) search;
funnelsort matches the sorting bound under a tall-cache assumption
(M = Omega(B^2)); cache-oblivious B-trees (Bender, Demaine, Farach-Colton,
FOCS 2000). Attractive for multi-level hierarchies, but tuned
cache-aware code usually wins on constants; use the idea (recursive
layouts) where the hierarchy is deep and unknown.

**Object storage as a level.** Treat an object store as a device with
s ~ tens of ms, high aggregate bandwidth only under high concurrency, and
a per-request price: block size in the model becomes several MiB, and the
cost function is `requests * price_req + bytes * price_byte + time`.

## 6. A review recipe

1. Fix N, M (per operator, after concurrency: memory is shared across
   queries), and per device the triple (positioning cost, bandwidth,
   useful concurrency).
2. Count transfers, separating reads/writes and random/sequential, and
   count *positioning events* explicitly.
3. Apply device multipliers: RAID small-write penalty, flash WA, replication
   factor, full-page images/doublewrite.
4. Convert to time with Little's law: for a device that sustains Q
   outstanding requests at latency l, time ~ events * l / Q_effective,
   where Q_effective is what the executor actually keeps in flight.
5. Sanity-check against measured device parameters (fio at the same block
   size and queue depth, preconditioned for SSDs) and the CPU cost per
   tuple: with fast NVMe arrays and cached data many operators become
   CPU-bound and the I/O model stops predicting runtime.

## 7. Pitfalls when using the model

- Counting pages instead of positioning events (a 1 MiB read is not 128
  random 8 KiB reads).
- Assuming memory M is private to one operator.
- Ignoring writes in plans that spill (sort, hash join, materialisation).
- Assuming uniform, independent access when real access is skewed and
  correlated (hot sets live in the buffer pool; the model then overstates
  I/O).
- Using one random-I/O constant for both QD1 and deep-queue execution.
- Forgetting the log: commit cost is a flush, not a block transfer.

---

Sources: EDBS entries I/O Model of Computation (p.1741), Memory Hierarchy
(p.2222), Disk (p.1143). Bounds and later models from Aggarwal and Vitter
(CACM 1988), Vitter and Shriver (1994), Arge (buffer tree), Brodal and
Fagerberg (SODA 2003), Frigo et al. (FOCS 1999), Bender et al. (FOCS 2000;
SPAA 2019), Dayan et al. (SIGMOD 2017), Yao (CACM 1977).
