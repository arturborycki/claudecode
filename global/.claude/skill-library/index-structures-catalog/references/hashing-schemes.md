# External hashing: static, extendible, linear

Disk-resident hash indexes for equality lookup. In-memory hash tables for
joins and aggregation are covered by `join-algorithms` and
`query-execution-advanced`; this file is about persistent, growing hash files
and the invariants that keep them addressable.

## 1. Common model

* Bucket = one primary page (or a fixed number of pages) holding up to B
  entries, plus an optional overflow chain.
* Hash function h maps a key to a large integer; the scheme chooses which
  bits/modulus of h(k) select the bucket.
* Expected cost: 1 page read for a lookup (plus chain length), 1-2 writes
  for an insert. Worst case: linear in N if many keys collide (skew,
  duplicates, adversarial input).
* No order: hash indexes answer `=` and `IN` only. They cannot provide
  interesting orders, range scans, prefix matches, or MIN/MAX.
* Space is linear in N; utilisation = N / (buckets x B), the load factor.

Design question that decides everything: what happens when a bucket fills?

| Scheme | Overflow response | Directory | Growth unit |
|---|---|---|---|
| Static | chain an overflow page | none (bucket = h(k) mod M) | none; rebuild to grow |
| Extendible (Fagin et al. 1979) | split the full bucket; maybe double the directory | 2^d pointers | one bucket (directory doubles occasionally) |
| Linear (Litwin 1980) | chain an overflow page; split the bucket at the split pointer | none | one bucket, in fixed order |

## 2. Static external hashing

M buckets fixed at creation. Insert computes h(k) mod M; if the primary page
is full, the record goes to a chained overflow page. Lookups read the
primary page and the whole chain.

* Chain length grows linearly once N exceeds M x B, so performance decays
  smoothly but without bound; the only remedy is a rebuild with a larger M.
* Choose M prime (or use a well-mixed hash and a power of two). Identity
  hashing modulo a power of two is a classic trap: keys that are multiples of
  2^j all land in the same 1/2^j fraction of the buckets.
* Static hashing is the hash-side twin of ISAM: both are static, both rely on
  overflow areas, ISAM additionally answers ranges.
* Still useful when N is known up front (bulk-built read-only lookup files,
  hash-partitioned spill files, perfect-hash dictionaries).

## 3. Extendible hashing

### Structure

* Directory: array of 2^d bucket pointers; d is the **global depth**.
* Each bucket has a **local depth** d' <= d: all keys in it agree on the
  same d' low-order bits of h(k) (EDBS uses the last d bits; using the high
  bits works equally well, see below).
* A bucket with local depth d' is referenced by exactly 2^(d - d') directory
  entries, all sharing those d' bits.

```
lookup(k):  return dir[ h(k) & (2^d - 1) ]          # one directory probe + one bucket read
```

The directory is small (8 bytes per entry) and normally memory-resident, so
a lookup is one I/O.

### Split

```
insert(k):
  b = dir[h(k) mod 2^d]
  if b has room: put; return
  if b.local == d:                                   # not enough bits to separate
      double directory: for i in 0..2^d-1: dir[i + 2^d] = dir[i];  d += 1
  b2 = new bucket; b.local += 1; b2.local = b.local
  for every directory slot j that pointed to b:
      if bit (b.local - 1) of j is 1: dir[j] = b2
  redistribute b's entries by bit (b.local - 1) of h
  retry insert(k)                                    # may split again
```

Only the overflowing bucket is physically split; the directory doubling is a
pure in-memory copy (with low-order bits the new half is a duplicate of the
old half; with high-order bits each entry i becomes entries 2i and 2i+1,
which keeps the directory in key-hash order and helps range-partitioned
directories).

### Delete and shrink

A bucket that empties (or two buddies whose combined contents fit) can merge
with its **buddy**: the bucket whose directory slots differ only in bit
(d' - 1). Both must have the same local depth. If after merges every local
depth is < d, the directory can be halved.

### Pathologies

* Duplicate keys or a cluster of keys sharing many hash bits: splitting
  never separates them; a single insert can double the directory repeatedly
  (EDBS example: keys 1, 17, 33, 49, 65 share the last four bits). Remedy:
  allow overflow pages for a bucket whose local depth hits a cap, and double
  only when overflowing buckets exceed a small fraction (EDBS suggests
  around 1%).
* Directory growth is super-linear in N for small B (asymptotically about
  N^(1 + 1/B); Flajolet 1983). With large pages (B in the hundreds) this is
  negligible; with tiny buckets it is not.
* Directory doubling is a stop-the-world event in a naive concurrent
  implementation. Use a directory latch with readers taking it shared, or
  segment the directory.

## 4. Linear hashing

### State

```
N0  = initial bucket count (m)
lvl = current round i          # buckets 0..N0*2^i - 1 exist at round start
p   = next bucket to split     # 0 <= p < N0 * 2^i
h_i(k) = f(k) mod (N0 * 2^i)   # family; h_{i+1} refines h_i
```

The refinement property is the whole trick: if h_i(k) = j then
h_{i+1}(k) is either j or j + N0 x 2^i. Any family with that property works
(modulus by doubling sizes, or taking one more low bit).

### Addressing

```
addr(k):
  a = h_i(k)
  if a < p: a = h_{i+1}(k)       # bucket a already split this round
  return a
```

Total buckets at any time: N0 x 2^i + p.

### Split

```
on trigger:
  create bucket p + N0*2^i (appended at the end of the file)
  rehash entries of bucket p (and its overflow chain) with h_{i+1}
  p += 1
  if p == N0*2^i: i += 1; p = 0         # round complete
```

The bucket that splits is the one at p, not necessarily the one that
overflowed; the overflowing bucket temporarily uses an overflow page and is
fixed when p reaches it. Buckets split in strict linear order, so the file
grows one bucket at a time and no directory is needed: bucket b lives at a
computable address.

### Trigger policy and load control

| Policy | Typical utilisation | Notes |
|---|---|---|
| Uncontrolled: split on every overflow | ~50-70% | depends on B and distribution (Litwin) |
| Controlled: split when load factor > upper threshold | up to ~95% | the standard choice |
| Controlled + overflow: split only if both hold | between the two | fewer splits under skew |
| Shrink: merge last pair when load < lower threshold | thresholds such as 0.7 / 0.9 in practice | merges proceed in reverse linear order |

### Physical addressing without a directory

Buckets must be locatable by number. Options: one contiguous file grown by
appending (simple; bucket b at offset b x bucketsize); or a small table of
segments whose sizes double, so bucket b is found by its high bit (avoids
moving data and keeps the "table" to ~log N entries). The second is the
practical choice for an engine with fixed-size extents.

### Pathologies

* Skewed keys: the hot bucket keeps growing its overflow chain until the
  split pointer comes round to it; with heavy skew lookups degrade to chain
  scans. Monitor max chain length.
* Rounds double the address space: at round boundaries you switch hash
  functions; a mistake in the `a < p` rule (e.g. `<=`) misroutes exactly the
  keys of the bucket just split.
* Splitting bucket p must hold a latch on p and on the new bucket and update
  (i, p) atomically with respect to readers that compute addresses; readers
  that computed an address with stale (i, p) must re-validate (store the
  bucket's own "split generation" in its header and retry on mismatch).

> **Beyond EDBS:** LH* (Litwin, Neimat & Schneider, SIGMOD 1993) distributes
> linear hashing across servers: clients keep a possibly stale image of
> (i, p), servers forward misaddressed requests and send image adjustment
> messages. It is a clean template for scalable partitioned hash stores.

## 5. Comparison with B+-trees

| Criterion | Extendible | Linear | B+-tree |
|---|---|---|---|
| Point lookup (expected) | 1 I/O (+directory, in memory) | 1 I/O + chain | h I/Os, ~1-2 with cached upper levels |
| Worst-case lookup | bounded by bucket + overflow (if allowed) | chain length, unbounded | O(log N), guaranteed |
| Range / ordered scan | no | no | yes |
| Growth | split one bucket; occasional directory doubling | one bucket at a time, predictable | local splits |
| Utilisation | ~69% typical (no overflow pages) | tunable to ~90%+ | ~69% random, ~100% bulk |
| Concurrency hot spots | directory doubling | split pointer state | root/right edge |

In practice the cached-upper-levels B+-tree is within a factor of ~1-2 I/Os
of hashing for point lookups and is far more versatile, which is why many
engines omit persistent hash indexes or treat them as niche. Hash indexes win
when keys are long (no key comparisons along a path, bucket stores only the
hash), when the working set of B-tree interior pages does not fit in memory,
or for equality-only workloads with very high lookup rates.

> **Beyond EDBS:** PostgreSQL's hash index became crash-safe (WAL-logged) only
> in version 10; before that it was explicitly discouraged. If you ship a hash
> index, ship its WAL story at the same time.

## 6. Engineering checklist

* Persist the hash function identity and seed in the index metadata; a
  library upgrade that changes the hash silently breaks every existing
  index. Version it.
* Use a 64-bit, well-mixed hash. Store the full hash value in each entry: it
  speeds bucket search (compare hashes before keys), makes splits possible
  without re-reading or re-hashing keys, and supports hash-only indexes for
  long keys (with key recheck at the heap).
* Hash flooding: if keys can be attacker-controlled, use a keyed hash or cap
  overflow behaviour.
* NULLs: decide whether they are indexed (usually not for hash indexes);
  `IS NULL` predicates then cannot use the index.
* Unique hash indexes: the uniqueness check is a bucket (plus chain) scan
  under the bucket latch; easy to get right compared with B-trees.
* Collation: equality under a case-insensitive collation must hash the
  collation key, not the raw bytes.

## 7. Tests

* Model test against an in-memory map with random insert/delete/lookup,
  verifying after every split: every key is found at addr(k); bucket local
  depths and directory pointer multiplicities agree (extendible); bucket
  count = N0 x 2^i + p (linear).
* Adversarial: all-equal keys; keys equal modulo 2^j; monotone integers with
  identity hash; deletes that shrink to empty and grow back (merge/halve
  paths are rarely exercised).
* Crash during split: either the old bucket or both new buckets must be
  consistent after recovery; no key lost or duplicated.
* Upgrade test: open an index file created by the previous release and look
  up every key.

Sources: EDBS "Hash-Based Indexing" (p.1683), "Extendible Hashing" (p.1429),
"Linear Hashing" (p.2093), "B+-Tree" (p.247, comparison), "Indexed Sequential
Access Method" (p.1854, static-structure parallel).
