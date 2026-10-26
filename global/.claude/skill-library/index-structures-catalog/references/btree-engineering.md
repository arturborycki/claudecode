# B+-tree engineering: structure, operations, compression, bulk and online build

Implementation-depth notes for the ordered index every engine ships. The
`storage-and-indexing` skill covers the textbook split/merge story; this file
covers the decisions that separate a toy B+-tree from a production one.
Latch protocols and key-range locking belong to `concurrency-control-theory`;
logging of structure modifications belongs to `recovery-and-durability`;
byte layout of nodes belongs to `page-and-file-format`.

## 1. Structure and the invariants you must assert

Terminology: in the original Bayer–McCreight B-tree records may sit in
interior nodes. Practically every DBMS and every concurrency/recovery paper
assumes the B+ form (Comer's B+-tree, Bayer–Schkolnick's B*-tree naming):
records (or record pointers) only in leaves, interior nodes hold separators
that carry no logical content, leaves chained in key order.

Node contents:

```
interior: [low fence][P0 K1 P1 K2 P2 ... Kq Pq][high fence]
          subtree(Pi) holds keys k with K_i <= k < K_{i+1}   (one convention; pick one, assert it)
leaf:     [low fence][(k1,v1) ... (kr,vr)][high fence][prev][next]
```

Invariants (each is an assertion in a `verify()` routine):

| # | Invariant | How to check |
|---|---|---|
| B1 | All leaves at the same depth | DFS records depth of first leaf; compare |
| B2 | Keys within a node strictly sorted (or sorted with a unique tiebreaker) | linear scan |
| B3 | Every key in subtree(Pi) lies in [K_i, K_{i+1}) of its parent | pass bounds down the DFS |
| B4 | Fence keys of a child equal the bracketing separators in the parent | compare on descent |
| B5 | Occupancy: non-root nodes >= minimum (count or bytes, per policy); root interior node has >= 2 children | per node |
| B6 | Leaf chain visits every leaf exactly once in key order; prev/next are mutual | walk chain, compare with DFS leaf order |
| B7 | Separator need not exist as a data key, but must separate | implied by B3 |
| B8 | (B-link) every node's high key >= all its keys; right link points to the node whose low fence equals this high key | per node |

Fence keys (a copy of the separators that bound the node, stored in the node
itself) cost a little space but make B3/B4 checkable locally, enable prefix
truncation relative to the fences, and let a reader that arrived via a stale
pointer detect it landed in the wrong node. Recommend them.

## 2. Cost model

Let N = records, L = leaf capacity (records), F = interior fan-out (pointers),
f = fill fraction. Height h = 1 + ceil(log_{fF}(N / (fL))).

Worked example: 8 KiB pages, 16-byte separator+pointer gives F ~ 500; with
f = 0.7 effective fan-out ~ 350. 100-byte leaf entries give L ~ 80, ~56 at
f = 0.7. For N = 10^9: leaves ~ 1.8x10^7; levels above leaves: 350^3 = 4.3x10^7,
so h = 4. The top two levels (~ 1 + 350 pages) always fit in the buffer pool,
so a cold point lookup is ~2 I/Os.

| Operation | I/O |
|---|---|
| exact match | h (minus cached levels) |
| range returning t records | h + ceil(t / (fL)) leaf pages (+ t heap fetches if secondary and unclustered) |
| insert / delete without SMO | h reads + 1 write |
| insert with splits | worst case 2h + 1 writes (split every level + new root) |
| space | ~ N / (fL) leaf pages x (1 + 1/(fF) + ...) |

Under random insertion the steady-state leaf occupancy of a B-tree is about
ln 2 ~ 69% (Yao 1978), which is why "fill factor" for random workloads is
moot after a while and matters mainly for bulk-loaded or append-mostly trees.

## 3. Search inside a node

* Binary search over a slot array of offsets is the default. With
  variable-length keys each probe dereferences an offset: cache-miss bound.
* Poor man's normalized keys (Graefe): store the first 2-4 bytes of each
  order-preserving normalized key inline in the slot array; compare those
  first, fall back to the full key only on a tie. Most probes then stay within
  the slot array.
* Order-preserving normalization (memcmp-comparable encoding of composite
  keys: big-endian integers with sign bit flipped, NULL ordering byte,
  escaped/terminated strings, collation keys for text) makes every comparison
  a memcmp and is a prerequisite for prefix truncation and for radix-style
  structures (ART, tries).
* Interpolation search helps only for near-uniform integer keys; keep it as
  an optional path.
* For in-memory trees, node size of a few cache lines and SIMD key compare
  (e.g. 16 x 1-byte or 4 x 4-byte) beat page-sized nodes.

## 4. Insertion and splits

```
insert(k, v):
  leaf = descend(k)                      # remember path or use B-link
  if fits(leaf, k, v): put; return
  (left, right, sep) = split(leaf)       # leaf: sep is COPIED up (stays in right as data)
  post(parent, sep, right)               # interior split: middle key MOVES up (push-up)
  # cascade; if root splits, allocate new root -> height + 1
```

Split-point choice matters more than textbooks admit:

| Policy | When it wins | Risk |
|---|---|---|
| Middle by count | fixed-size keys | with variable keys, halves can be very unequal in bytes |
| Middle by bytes | variable-length keys | must still respect min-occupancy in count if you assert it |
| Shortest separator in a window around the middle | suffix truncation (see 6) | slightly unbalanced halves |
| Rightmost / append split: put only the new key in the new right page | monotone keys (timestamps, sequences) | if the workload is not actually monotone, leaves stay 50% (or worse) full |
| B*-style: shift entries to a sibling first; split 2 nodes into 3 | raises guaranteed occupancy to ~2/3 | touches an extra sibling per overflow; more latching |

Detect monotone insertion by remembering whether the last split in this
leaf was at the right edge and the new key is greater than the high key; many
engines split 90/10 or 100/0 in that case.

Interior-node split pushes the middle separator up (it is removed from both
halves); leaf split copies the first key of the right half (or a truncated
separator) up. Mixing these up yields duplicated or lost separators that B3
catches.

## 5. Deletion, underflow and merge policy

Textbook: delete, if below half, borrow from an adjacent sibling; if the
sibling is at minimum, merge and delete the separator from the parent
(reverse of copy-up at leaf level, "drag-down" of the separator at interior
level), possibly cascading.

Production reality:

| Policy | Notes |
|---|---|
| Merge-at-half | textbook; risks thrashing (split/merge oscillation) when inserts and deletes alternate at the boundary |
| Merge at a lower threshold (e.g. 25-50% by bytes) with hysteresis | common; reduces oscillation |
| Free-at-empty (never rebalance, reclaim only empty pages) | Johnson & Shasha showed that for workloads with more inserts than deletes, utilization stays acceptable and the code is far simpler; many systems do this plus offline/online reorg |
| Ghost (pseudo-deleted) records | delete only flips a bit; physical removal happens later by a system transaction or opportunistically when the page needs space. Simplifies rollback (the key and its lock anchor remain) and key-range locking. See concurrency-control-theory |
| Lazy page removal | empty pages unlinked from the chain only when no reader can hold a pointer (epoch or "drain" technique) |

Whatever the policy, the verify routine must state it so B5 is testable.

## 6. Key compression and fan-out

Fan-out is the lever: height is logarithmic in fan-out, and interior-node
cache residency depends on interior size.

* Prefix truncation: all keys in a node share the prefix common to its low
  and high fence keys; store it once (or derive it from the fences) and keep
  only suffixes. Recompute on split (the halves have longer common prefixes).
* Suffix truncation (Bayer & Unterauer's prefix B-tree, 1977): a separator
  only needs to discriminate between the last key of the left node and the
  first of the right node, so post the shortest string s with
  last_left < s <= first_right. For "Smith, J" | "Smythe, A" the separator
  "Smy" suffices. Applies to interior levels only; leaves keep full keys.
  With composite keys, truncate whole trailing columns (PostgreSQL 12 does this
  with its heap-TID tiebreaker column).
* Duplicate handling:
  - make every key unique by appending the row identifier as a final key
    column; this gives deterministic position for delete, makes key-range
    locks per row, and keeps the tree logic uniform;
  - or store key -> posting list of RIDs (dedup): far smaller for
    low-cardinality columns; PostgreSQL 13 added this as B-tree
    deduplication. Posting lists need their own split logic once one key
    overflows a page.
* Per-page compression of values (dictionary, delta for integers) is
  possible but turns in-place updates into rewrites; most OLTP engines limit
  themselves to prefix/suffix truncation.
* Microindex / slot-prefix tricks (section 3) are a compression of the search
  path, not of storage.

## 7. Fill factor

Fill factor is the occupancy target applied when *building* pages (bulk load,
rebuild, sometimes splits). 100% is optimal for read-only or append-only
indexes; random inserts into a 100%-full bulk-loaded tree trigger a split on
nearly every first insert per page (split storm, then 50% occupancy).
Typical leaf defaults are 90% (PostgreSQL B-tree) with interior pages fuller.
Expose it per index; record the value in the catalog so REINDEX reproduces it.

## 8. ISAM and why B+-trees replaced it

ISAM (IBM, 1960s) builds the same multi-level directory over a sorted data
file but never changes it: inserts go to overflow pages chained off the data
page where the record belongs; deletes leave holes. Search is
O(log_B(n/B)), range O(log_B(n/B) + a/B), index space ~ n/B^2 + n/B^3 + ...
pages. It degrades with overflow chain length until a periodic reorganisation
merges the overflow area and rebuilds the index. VSAM replaced it by
introducing splits of data (control interval) and index pages, and B+-trees
generalised that with guaranteed occupancy and height balance. ISAM-style
static structure is still the right answer for immutable sorted runs:
SSTable block indexes, Parquet page indexes, and bulk-built read-only
B+-trees are ISAM in spirit.

## 9. B-link trees (structure only)

Lehman & Yao (1981): every node carries a high key and a right-sibling link.
A split is two independent steps:

1. Half-split: create the right sibling, move the upper half, set the old
   node's high key and right link. One node is modified; the tree is already
   consistent for readers.
2. Post the separator and new-node pointer into the parent, later, as a
   separate atomic action (can even survive a crash and be completed lazily).

Search rule: if search key > node.high_key, follow the right link
("move right"). Consequences for implementers: searches tolerate concurrent
splits without latch coupling on the way down; verification must accept
nodes not yet referenced from their parent; heavy insert bursts can create
long right-link chains, so complete step 2 promptly (Jaluta, Sippu &
Soisalon-Soininen give a design that bounds this). Deletion/merge is the hard
part of B-link trees; many implementations never merge. Protocol details:
`concurrency-control-theory`.

> **Beyond EDBS:** Graefe's *foster B-trees* (2012) keep at most one
> "foster child" per node instead of arbitrary right chains, restoring a
> single incoming pointer per node and simplifying verification.

## 10. Bulk loading (sort-based index build)

```
bulk_load(rows, fill):
  runs  = external_sort(extract (key, rid) from rows)      # see query-execution-advanced for sort
  level = []; page = new_leaf()
  for (k, rid) in merged(runs):
      if bytes(page) + entry > fill * PAGE: emit(page); level.append(first_key(page)); page = new_leaf(); link
      append(page, k, rid)
  emit(page)
  while len(level) > 1:                                    # build parents bottom-up
      level = pack_interior(level, fill)                    # separators = (truncated) first keys
  set_root(level[0])
```

* Cost: sort + one sequential write of the leaf level + tiny interior
  levels; versus N random insertions with N x h random reads. Bulk loading
  wins by orders of magnitude for anything beyond a few percent of the table.
* Keep only the right edge of each level in memory (one page per level);
  pages are written once, sequentially, so a fresh file can be preallocated.
* Leaves come out physically contiguous in key order, which makes range
  scans sequential until the first splits happen.
* Separators: use suffix truncation between consecutive leaves while
  building.
* Logging: a fresh index can be logged as page images or not at all
  (force pages, then log one "index created" record); either way the
  recovery story must be explicit (`recovery-and-durability`).
* Bulk *insertion* into an existing tree: sort the batch and apply it leaf by
  leaf in key order, so each leaf is read and written once.

## 11. Online index build

Goal: build an index while the table accepts writes, then switch it on
without a long exclusive lock. Mohan & Narang (SIGMOD 1992) define the two
families:

| Approach | Mechanism | Trade-off |
|---|---|---|
| Side-file (SF) | builder scans + sorts + bulk-loads; concurrent writers append their index changes to a side file; builder replays the side file, then briefly blocks writers to drain the tail and publish | bulk-load efficiency; replay must be idempotent and ordered |
| No-side-file (NSF) | index is visible to writers from the start; writers insert directly; builder inserts scanned keys, and conflicts between builder and writer insertions/deletes are reconciled (pseudo-deleted entries, ignore duplicate inserts) | no replay, but builder inserts are random, not a bulk load |

Correctness checklist:
1. A write that happens after the builder scanned its row must reach the
   index through the writer path; a write before must reach it through the
   scan. Define the cut (a snapshot/LSN) and prove both sides are covered.
2. Deletes racing with the builder: the builder must not resurrect a key
   deleted after the scan point (use the side file or a tombstone/pseudo-delete).
3. Uniqueness: a unique index cannot be declared valid until all
   conflicting versions are resolved; duplicates found late abort the build
   and leave an invalid index that must be dropped or be invisible to the
   planner.
4. The planner must not use the index until it is complete and valid, and
   writers must maintain it from the moment it becomes visible to them.

> **Beyond EDBS:** PostgreSQL `CREATE INDEX CONCURRENTLY` registers the index
> as not-ready, waits for transactions that could miss it, scans and builds,
> then runs a second validation scan to add rows inserted meanwhile, waits
> again, and only then marks it valid. A failure leaves an INVALID index the
> user must drop. It is a practical NSF/SF hybrid worth reading before
> designing your own.

## 12. Variants worth knowing

| Variant | Idea | When to reach for it |
|---|---|---|
| Prefix B-tree (Bayer & Unterauer 1977) | suffix-truncated separators in interior nodes | always, for string keys |
| String B-tree (Ferragina & Grossi 1999) | B-tree whose nodes hold Patricia tries over suffix pointers; optimal external-memory substring search | external-memory full-text / dictionary search |
| Copy-on-write B-tree | never update in place; new root per commit | single-writer embedded stores (see storage-and-indexing) |
| Multiversion / temporal B-trees | key x time | `temporal-databases` |
| UB-tree (Bayer), R-tree, k-d-B-tree | B-tree machinery over multidimensional keys | `multidimensional-and-similarity-indexing` |

> **Beyond EDBS: Bw-tree.** Levandoski, Lomet & Sengupta (ICDE 2013): nodes
> are logical page ids resolved through a mapping table; updates prepend
> delta records installed with a single compare-and-swap on the mapping
> entry; periodic consolidation replaces a delta chain with a new base page;
> memory is reclaimed with epochs; SMOs are multi-step with help-along.
> Latch-free, and pairs naturally with log-structured storage (LLAMA). Wang
> et al. (SIGMOD 2018, "Building a Bw-Tree Takes More Than Just Buzz Words")
> reported that a carefully engineered Bw-tree was still outperformed by
> optimistic-lock-coupling B+-trees and ART in memory, so treat it as one
> option, not the default.

> **Beyond EDBS: learned indexes.** Kraska et al. (SIGMOD 2018) replace the
> interior levels with a model that predicts a key's position in a sorted
> array plus a bounded "last-mile" search (recursive model index). Successors
> handle updates and guarantee error bounds: ALEX (Ding et al., SIGMOD 2020),
> PGM-index (Ferragina & Vinciguerra, VLDB 2020), RadixSpline (Kipf et al.,
> 2020); the SOSD benchmark compares them. They win on read-mostly, sorted,
> integer-like keys with smooth CDFs; they lose on string keys, adversarial
> distributions, and heavy writes. A learned index is essentially an ISAM
> whose directory is a function; reason about it the same way.

## 13. Classic bugs

* Separator convention mismatch (< vs <=) between search and split: keys
  equal to a separator become unreachable. B3 with boundary-equal keys finds it.
* Split of variable-length keys by count leaves one half unable to absorb the
  incoming key; the insert retries forever or overflows the page.
* Posting a full-length separator larger than the parent's free space;
  suffix truncation hides this until a pathological key appears. Test with
  maximum-size keys.
* Leaf chain not updated on merge, leaving a dangling next pointer; range
  scans read a freed page.
* Root split races with a reader that cached the old root id. Store root in
  a meta page and re-read under latch, or never move the root: on a root
  split, move the root's contents into two new children and keep the root
  page id fixed (SQLite does this).
* Reverse scans: prev-pointer maintenance is usually less tested than next.
* Duplicates spanning multiple leaves: a search for the first duplicate must
  descend to the leftmost candidate, not the first hit.
* Bulk load with 100% fill followed by OLTP inserts: split storm and
  latency spike.
* Unique check done on the leaf where the key would be inserted, but
  duplicates of that key may live in the left sibling when the key equals the
  separator. With unique-by-RID keys, check the whole key range [k, k+RIDmax].

## 14. Testing

* Model-based test against `BTreeMap`/`std::map` with random ops, including
  deletes heavy enough to trigger merges; run `verify()` (B1-B8) after every
  SMO in debug builds.
* Adversarial key sets: all equal keys; strictly increasing; strictly
  decreasing; alternating insert/delete at a page boundary; maximum-length
  keys; keys sharing a long prefix (stress prefix truncation); keys that
  differ only in the last byte (stress suffix truncation).
* Bulk-load equivalence: tree from bulk load and tree from sequential
  insertion of the same multiset must answer every range query identically.
* Online build: concurrent writer threads + builder; at the end compare index
  contents with a full scan under a snapshot.
* Crash tests at every SMO step (see recovery-and-durability).

Sources: EDBS "B+-Tree" (p.247), "B-Tree Locking" (p.345), "Indexed Sequential
Access Method" (p.1854), "Tree-Based Indexing" (p.4217), "Index Creation and
File Structures" (p.1842, for the sort-and-merge build pattern), "Indexing
Compressed Text" (p.1861, String B-tree reference).
