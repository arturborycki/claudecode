---
name: storage-and-indexing
description: "Use when working on the storage layer or access methods of a database: buffer pool/buffer manager, B-tree/B+-tree implementation (search, split, merge, rebalance), hash indexes, bitmap indexes, index selection, or B-tree variants (copy-on-write, Bw-trees). Triggers on buffer pool, page cache, eviction, B-tree, B+tree, node split/merge, rebalancing, hash index, bitmap index, secondary index, index scan, fanout. Apply this for any access-method or buffer-management work; for byte-level page layout use page-and-file-format, and for log-structured storage use lsm-storage."
---

# Storage and Indexing

The storage engine decides how data lives on disk and how fast you can find
it. Everything here is governed by one fact: **block/page I/O dominates
cost**, so the cost model counts pages touched, not rows.

## Buffer pool / buffer manager

The buffer pool caches disk pages in memory and is the boundary between
volatile and durable state. Core responsibilities:
- a page table mapping page-id → frame; **pin/unpin** so in-use pages
  aren't evicted; a **dirty** flag so only modified pages are written back
- an eviction policy: **LRU** is the baseline; **CLOCK** (second-chance)
  approximates LRU cheaply; LRU-K / 2Q reduce scan pollution
- it interacts with recovery: under write-ahead logging a dirty page may not
  be flushed before its log record (see `transactions-and-recovery`)

Operators draw their memory budget from the buffer pool; two-pass join/sort
algorithms assume a known number of available frames.

## B-trees / B+-trees

The default ordered index. A B+-tree keeps all data/pointers in leaves and
only keys in internal nodes; leaves are linked for range scans. Properties
to implement and test:
- **high fanout** (hundreds) → shallow tree → 3–4 page reads to any key
- **search**: binary search within a node, descend by key range
- **insert**: descend, insert in leaf; if the node overflows, **split** and
  propagate the split key upward (which may cascade to the root, growing
  height)
- **delete**: remove; if a node underflows, **rebalance** (borrow from a
  sibling) or **merge** siblings, propagating upward
- **right-only appends**: monotonic insert keys (timestamps, sequences) hit
  the rightmost leaf; special-case this to avoid pathological splitting
- **maintenance**: prefix/suffix key compression to raise fanout; vacuum/
  compaction to reclaim space from deletes

## B-tree variants (when the classic isn't enough)

- **Copy-on-write B-trees** (e.g., LMDB): never modify a page in place;
  write new versions and atomically swap the root. Gives lock-free readers
  and crash safety without a separate WAL, at the cost of write
  amplification.
- **Bw-trees / lazy B-trees**: append in-memory delta records to nodes and
  consolidate later, reducing in-place update contention (latch-free).
- Reach for these when write contention or in-place-update cost is the
  bottleneck; otherwise the classic B+-tree is the right default.

## Hash and bitmap indexes

- **Hash index**: O(1) equality lookup, no range support. Use **extensible**
  or **linear hashing** so the structure grows without a full rebuild.
- **Bitmap index**: one bitmap per distinct value; superb for
  low-cardinality columns and for combining predicates with bitwise AND/OR.
  Compress the bitmaps (e.g., Roaring).

## Index selection

More indexes speed reads but slow writes and cost space. Choose indexes for
the actual predicate/join columns and ordering needs; a cost-based advisor
weighs query benefit against update overhead.

## Language notes (C/C++/Rust)

- **Rust**: the borrow checker fights tree structures with parent pointers —
  prefer arena/slab allocation with node indices, or `Arc`/`Rc` for COW
  variants. The buffer pool frame array is naturally an arena.
- **C++**: RAII page guards (pin in constructor, unpin in destructor)
  prevent the classic "forgot to unpin" leak; smart pointers for node
  ownership.
- Page layout itself (headers, slots, cells) is the province of
  `page-and-file-format`.

## Grounding
DBMS Ch 13 (storage), Ch 14 (index structures: B-trees, hashing, bitmap),
§15.7 (buffer management). Petrov Ch 2, 4 (B-tree basics & implementation),
Ch 6 (variants), Ch 5 (buffer management).
