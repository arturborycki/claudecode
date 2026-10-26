# Bloom filters, their variants, and signature files

Approximate membership: answer "definitely not in the set" or "possibly in
the set" from a compact bit structure. Bloom filters gate expensive probes
(SSTable reads, remote join partners, differential files); signature files
apply the same superimposed coding to text blocks. The LSM read path that
consumes the filters is `lsm-storage`; runtime join filters inside the
executor are `query-execution-advanced` / `join-algorithms`.

## 1. Definition and the one invariant

Set S of n keys, bit array of m bits (all zero), k hash functions
h_1..h_k : U -> [0, m).

```
insert(x):  for i in 1..k: bits[h_i(x)] = 1
query(y):   return AND over i of bits[h_i(y)]       # false => y not in S, guaranteed
```

**Invariant: no false negatives.** Every bit an inserted key set stays set
(standard filter: bits never clear). Any change that can clear a bit
(deletion, rebuild over a different key set, hashing a different
representation of the key) breaks the invariant and corrupts query
results, not just performance.

False positives: y not in S but all k of its bits were set by other keys.

## 2. False-positive math

Assume ideal, independent, uniform hashing.

* Probability a given bit is still 0 after n insertions:
  p' = (1 - 1/m)^(kn) ~ e^(-kn/m) =: p.
* False-positive rate (the fraction of zero bits concentrates sharply
  around p, so this is accurate for realistic m):
  f ~ (1 - e^(-kn/m))^k.
* Optimal number of hashes for given m/n: minimise over k ->
  k* = (m/n) ln 2, at which half the bits are set and
  f = 2^(-k*) ~ 0.6185^(m/n).
* Bits per key for target rate eps: m/n = log2(1/eps) / ln 2
  ~ 1.44 log2(1/eps). Any approximate membership structure needs at least
  log2(1/eps) bits per key, so the Bloom filter pays ~44% over the bound.

| Target FPR | bits/key (optimal k) | k* | Practical choice |
|---|---|---|---|
| 10% | 4.8 | 3.3 | 5 bits, k = 3 |
| 1% | 9.6 | 6.6 | 10 bits, k = 7 gives ~0.82% |
| 0.1% | 14.4 | 10 | 15 bits, k = 10 |
| 0.01% | 19.2 | 13.3 | 20 bits, k = 14 |

Sensitivity worth knowing: at 8 bits/key with k = 6 the rate is ~2.2%; at
16 bits/key with k = 11 it is ~0.05%. Each extra ~4.8 bits/key divides the
FPR by 10.

Overfill: if the true n exceeds the design n by factor r, the FPR becomes
(1 - e^(-k r n/m))^k. At r = 2 a filter designed for ~1% (10 bits/key,
k = 7) runs at ~14%. Size
from an upper bound of n, or rebuild/scale (section 5).

Integer k: round to the nearest integer and re-evaluate; using fewer hashes
than optimal also saves CPU and memory accesses, often a good trade for
in-memory probes.

## 3. Hashing in practice

* Double hashing: g_i(x) = h1(x) + i x h2(x) mod m gives the same asymptotic
  FPR as k independent hashes (Kirsch & Mitzenmacher 2006). One 64- or
  128-bit hash per key, split into h1 and h2, is the standard engine
  approach. Make h2 odd (or nonzero mod m) so the probe sequence does not
  collapse.
* Use a strong, seeded, version-pinned hash; persist hash id and seed with
  the filter. Weak hashes on structured keys (sequential integers) produce
  correlated bit patterns and FPRs far above the formula.
* Hash the exact byte representation used at query time (normalised key,
  user key without sequence number, chosen prefix). Mismatches here produce
  false negatives.
* For m that is not a power of two, map with a multiply-shift reduction
  ((h x m) >> 64) rather than modulo.

## 4. Memory-hierarchy-aware layouts

| Layout | Idea | Effect |
|---|---|---|
| Standard | k bits anywhere in m | k cache misses per probe |
| Partitioned | m split into k slices of m/k bits; hash i sets one bit in slice i | slightly higher FPR than standard at the same m; independent slices parallelise |
| Blocked (Putze, Sanders & Singler 2007) | first hash picks a cache-line (or page) block; all k bits inside it | 1 cache miss / 1 I/O per probe; FPR somewhat worse because block loads vary, compensated by a few extra bits/key |
| Split-block / register-blocked | block of 8 x 32-bit words, set one bit per word using SIMD | Parquet's Bloom filter format uses this; branch-free probe |

For on-disk filters (per SSTable, per Parquet row group) blocked layouts
mean one page read per negative probe instead of k.

## 5. Variants

| Variant | Adds | Notes |
|---|---|---|
| Counting Bloom (Fan et al. 2000) | deletion: counters instead of bits; increment on insert, decrement on delete | ~4-bit counters suffice in practice; 4x space; deleting a key never inserted creates false negatives, so deletions must be of known members |
| Compressed Bloom (Mitzenmacher 2002) | smaller transmission size by choosing a sparser filter and compressing it | for shipping filters over a network (distributed joins, cache digests) |
| Spectral Bloom (Cohen & Matias 2003) | multiset counts | frequency queries with one-sided error |
| Count-min sketch (Cormode & Muthukrishnan 2005) | approximate counts per item in streams | d rows x w counters; overestimates only |
| Bloomier filter (Chazelle et al. 2004) | returns an associated value from a small domain | static |
| Approximate concurrent state machines (Bonomi et al. 2006) | values that change over time plus insert/delete | networking origin |
| Scalable Bloom (Almeida et al. 2007) | unknown n: chain filters of growing size with tightening FPRs | bounded overall FPR |

> **Beyond EDBS:** Cuckoo filters (Fan, Andersen, Kaminsky & Mitzenmacher,
> CoNEXT 2014) store short fingerprints in a cuckoo hash table, support
> deletion, and beat Bloom filters in space for FPRs below a few percent.
> Quotient filters (Bender et al., VLDB 2012) store fingerprints in a
> compact, mergeable, cache-friendly table, suitable for flash. For static
> sets, xor filters (Graf & Lemire 2020; about 1.23 log2(1/eps) bits/key)
> and ribbon filters (Dillinger & Walzer 2021; closer still to the bound)
> beat Bloom's 1.44 factor; RocksDB offers a Ribbon filter as an alternative to its Bloom filter.
> Range filters such as SuRF (Zhang et al., SIGMOD 2018) answer "any key in
> [a, b]?" for LSM range scans; RocksDB also supports prefix Bloom filters
> keyed on a configured key prefix.

## 6. Set algebra and estimation

* Union: OR of two filters built with identical m, k and hash functions is
  exactly the filter of the union.
* Intersection: AND is a valid filter for the intersection (no false
  negatives) but has more set bits than one built from scratch, so a higher
  FPR.
* Halving: OR the two halves of a power-of-two filter to get a smaller
  filter (doubles the load).
* Cardinality from set bits X: n_hat ~ -(m/k) ln(1 - X/m). The same applied
  to an AND-ed or OR-ed filter estimates intersection/union sizes, usable for
  semijoin size estimation (Mullin 1993) in a distributed optimizer
  (`cardinality-and-statistics`).

## 7. Database uses

### Bloomjoin / semijoin reduction

Site A builds a Bloom filter over its join keys and ships it (m bits instead
of n keys) to site B; B filters its relation and ships only probable
matches; A finishes the join and discards false matches. Communication drops
from |R_B| tuples to roughly (selectivity + FPR) x |R_B|. Evaluated for
distributed joins in R* (Mackert & Lohman 1986); bit-vector filtering in
hash joins goes back to Babb (1979) and was used in parallel engines such as
Gamma.

### Runtime join filters (sideways information passing)

Build the filter from the hash join's build side, push it down to the probe
side scan (or across the exchange in MPP), possibly further into storage
(skip row groups whose min/max or Bloom filter rules them out). Decide
adaptively: abandon the filter if its observed pass rate is near 1.
Correctness rule: the filter may only remove rows that cannot join under the
join's semantics; never apply a build-side filter to the preserved side of an
outer join.

### LSM-trees

One filter per SSTable (or per block / partition of an SSTable) over user
keys. A point lookup that misses the memtable checks filters newest to
oldest; expected wasted I/Os for a key that does not exist = sum of the
per-run FPRs. Rule of thumb: 10 bits/key, ~1% per run.

> **Beyond EDBS:** Monkey (Dayan, Athanassoulis & Idreos, SIGMOD 2017)
> shows that equal bits/key per level is suboptimal: minimising the sum of
> FPRs for a fixed memory budget sets each level's FPR proportional to its
> number of entries, i.e. fewer bits per key for the largest level and more
> for small upper levels, removing most of the per-level lookup penalty.

### Differential files

Batch-updated databases keep changes in a differential file until the next
merge (Severance & Lohman 1976). A Bloom filter over changed record keys
lets a read skip the differential file for unchanged records; a false
positive costs one extra lookup (Gremillion 1982). This is the ancestor of
the LSM filter.

### Others

Approximate bitmap encoding (Apaydin et al. 2006) stores bitmap-index rows
in a Bloom filter; distributed caches exchange Bloom summaries of their
contents (Fan et al. 2000); deduplication and "seen before" checks in
ingestion pipelines.

## 8. Signature files (superimposed coding for text)

Divide the text into blocks T_i of b terms (after stop-word removal). Each
term hashes to a B-bit signature with n bits set; a block's signature is the
OR of its terms' signatures. Query term Q with signature h(Q):

```
candidate(T_i)  <=>  (S(T_i) AND h(Q)) == h(Q)
```

Non-candidates are certainly free of Q; candidates must be verified against
the text (false drops). This is a Bloom filter per block with m = B,
b keys, k = n; choosing n = B ln 2 / b gives a false-drop rate of 2^(-n),
the same optimum as section 2.

Limitations, all consequences of OR-ing:
* no term order inside a block, so phrase queries cannot be answered from
  signatures, and phrases that straddle a block boundary are missed if
  verification checks blocks independently;
* negation queries: non-candidates definitely satisfy NOT Q; candidates still
  need verification;
* refinement dominates cost when signatures are too short or blocks too
  large; longer signatures erode the storage advantage.

Layouts:

| Layout | Query I/O | Trade-off |
|---|---|---|
| Sequential signature file | read all signatures (sequential) | simplest; cheap appends |
| Bit-sliced signature file (transpose: one bit-vector per signature bit position over all blocks) | read only the slices for bits set in h(Q), AND them | few slices per query, but random reads, and appends must touch every slice |
| Signature tree / S-tree (Deppisch 1986) | descend B+-tree-like nodes whose entries are the OR of child signatures; prune entries failing the test | pruning degrades as upper-level signatures saturate; cluster similar (low combined weight) signatures together when building nodes |

Bit-sliced signature files are bit-sliced indexes (bitmap-and-join-indexes.md)
applied to superimposed codes.

Verdict from the IR literature: for natural-language text with word queries,
inverted files beat signature files on space and speed once posting
compression is used (Zobel, Moffat & Ramamohanarao, TODS 1998). Signature
techniques survive as per-block Bloom filters in storage formats, as
set-valued attribute indexes, and for streams of short documents with
append-only ingestion.

## 9. Implementation checklist

* Filter metadata: format version, m, k, hash id, seed, key-extraction
  rule (whole key / prefix / normalised form), layout (standard / blocked).
* Size from expected n with a safety margin; record actual n and observed
  fill fraction (fraction of ones ~ 1 - e^(-kn/m); far above 0.5 at optimal
  k signals overfill).
* Serialisation: fixed endianness for bit-array words; a checksum, because a
  flipped bit from 1 to 0 creates false negatives.
* Concurrent inserts into a shared in-memory filter: atomic fetch-or on
  words; queries need no synchronisation beyond publication of the array.
* Building per SSTable/file: build at write time from the sorted key stream;
  never mutate after the file is sealed.

## 10. Tests

* Property: for random sets, query(x) is true for every inserted x (no false
  negatives), across serialisation round trips and version upgrades.
* Statistical: measure FPR over >= 10^6 non-members; assert it is within a
  tolerance of (1 - e^(-kn/m))^k. Run with sequential integer keys and
  keys sharing long prefixes to catch weak hashing.
* Counting filter: insert/delete sequences never produce false negatives for
  current members; counter saturation behaviour is defined (stick at max).
* Join filter: plans with and without the runtime filter return identical
  results, including outer, semi and anti joins and NULL join keys.
* Signature file: random documents and queries versus brute-force search,
  including phrases across block boundaries (expected misses must be handled
  by verification design).

Sources: EDBS "Bloom Filters" (p.320), "Signature Files" (p.3491),
"Bitmap-Based Index Structures" (p.316, approximate bitmap encoding),
"Hash-Based Indexing" (p.1683).
