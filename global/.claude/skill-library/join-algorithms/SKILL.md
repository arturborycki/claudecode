---
name: join-algorithms
description: "Use when implementing, choosing between, or tuning join operators: nested-loop, block-nested-loop, sort-merge, hash join, grace/partitioned hash join, index nested-loop, bloom-filter joins, and semi/anti/outer join semantics. Triggers on join algorithm, hash join, build/probe side, sort-merge join, nested loop, grace hash, partitioned join, bloom filter join, spill. Reach for this whenever join performance or correctness is in play, even if the user just says 'my join is slow' or 'joins return wrong rows with nulls'."
---

# Join Algorithms

Joins are where engines spend most of their time and where most
correctness bugs hide (nulls, duplicates, empty sides). Pick the algorithm
from the predicate and the data, and get the semantics exactly right.

## Choosing an algorithm

| Situation | Algorithm |
|---|---|
| Equality predicate, build side fits in memory | **Hash join** (default) |
| Equality predicate, build side too big | **Grace / partitioned hash join** (spill) |
| Inputs already sorted, or range/inequality join | **Sort-merge join** |
| One side small, indexed on join key | **Index nested-loop** |
| No equality predicate, tiny inputs | **(Block) nested-loop** (last resort) |

## Hash join in detail

Two phases:
1. **Build** — scan the *smaller* input, hash on the join key, populate a
   hash table keyed by join key → matching rows.
2. **Probe** — scan the larger input, hash each row's key, look up the
   table, emit matches.

Cost when both fit in memory ≈ `B(R) + B(S)` I/Os. When the build side
exceeds memory, switch to **grace hash join**: partition *both* inputs by
`hash(key) mod n` into n partitions that each fit in memory, then hash-join
partition-by-partition. Two-pass cost ≈ `3(B(R) + B(S))`.

Always build on the smaller side — it minimizes hash-table memory and
probe misses.

## Sort-merge join

Sort both inputs on the join key (skip the sort for an already-sorted
input), then merge with two cursors. Wins when inputs are pre-sorted (e.g.,
clustered index order) or for range joins where hashing doesn't apply.
Two-pass cost is dominated by the external sort.

## Bloom filters

Build a bloom filter on the build-side keys and apply it to the probe side
*before* the hash lookup (or push it down to the probe-side scan). It
cheaply discards probe rows that cannot match, cutting probe work — and in
distributed joins, cutting network shuffle. Tune false-positive rate vs
size.

## Semantics — the bug factory

- **Inner**: emit only matching pairs.
- **Left/right outer**: preserve unmatched rows from the preserved side,
  padding the other side with NULLs.
- **Full outer**: preserve unmatched from both sides.
- **Semi join**: emit a left row if *any* match exists (no duplication).
- **Anti join**: emit a left row if *no* match exists.
- **NULL handling**: `NULL = NULL` is *not* true — NULL keys never match in
  an equi-join. Decide and test this explicitly; it is the single most
  common join bug.
- **Duplicate keys**: a key appearing m times on the left and n on the
  right yields m·n output rows in an inner join. Make sure the hash table
  stores *all* rows per key, not just one.

## Test matrix (build these)

Empty left, empty right, both empty; NULL keys on each side; duplicate keys
on each side; build side larger than memory (forces spill — test at the
threshold, not just below it); all of inner/left/right/full/semi/anti.

## Language notes (C/C++/Rust)

- **Rust**: `HashMap<Key, SmallVec<RowRef>>` for the build table; consider
  `hashbrown` (the std backend) directly and a fast hasher (`ahash`) on the
  hot path. Store row references/indices into the build batches, not cloned
  rows, to stay zero-copy.
- **C++**: an open-addressing hash table (e.g., robin-hood / flat) beats
  `std::unordered_map` for join build tables. Watch for rehash cost; size
  the table from the build-side cardinality estimate.
- Vectorize the probe: hash a batch of keys, then gather — don't probe
  row-at-a-time. See `columnar-arrow-layout`.

## Grounding
DBMS §15.3 (nested-loop), §15.4 (two-pass sort-based), §15.5 (two-pass
hash-based), §15.6 (index-based). HQEW *Joins*.
