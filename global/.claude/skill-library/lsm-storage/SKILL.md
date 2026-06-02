---
name: lsm-storage
description: "Use when implementing or tuning a log-structured / LSM storage engine: memtables, SSTables, compaction strategies (size-tiered, leveled), the read/write/space amplification tradeoff, tombstones and deletes, bloom filters for SSTable reads, write-ahead log for the memtable, and merge/reconciliation on read. Triggers on LSM, LSM tree, memtable, SSTable, compaction, size-tiered, leveled compaction, write amplification, space amplification, tombstone, RocksDB/LevelDB-style storage. Reach for this for any write-optimized or log-structured storage work; for B-trees use storage-and-indexing."
---

# Log-Structured (LSM) Storage

LSM-trees optimize for write throughput by never updating in place: writes
go to an in-memory structure and are flushed as immutable sorted files,
which are later merged. This is the engine behind RocksDB, LevelDB,
Cassandra, ScyllaDB, and many others.

## The write path

1. Append the write to a **write-ahead log** (durability for the memtable).
2. Insert into the **memtable** — an in-memory sorted structure (skip list
   or balanced tree) keyed by row key.
3. When the memtable fills, **freeze** it and flush it to disk as an
   immutable, sorted **SSTable** (Sorted String Table); start a fresh
   memtable. The WAL segment for the flushed memtable can now be discarded.

Because SSTables are immutable and sorted, flushes are large sequential
writes — the source of LSM's write throughput.

## The read path

A key may live in the memtable or any SSTable, and newer versions shadow
older ones. A read must **reconcile**: check the memtable, then SSTables
newest-to-oldest, merging to find the current value. To avoid touching
every SSTable:
- **bloom filter per SSTable** — cheaply rules out SSTables that cannot
  contain the key (the single most important LSM read optimization)
- **sparse index / block index per SSTable** — locate the block within a
  hit SSTable without scanning it

## Deletes and tombstones

You cannot modify an immutable SSTable to remove a key, so a delete writes a
**tombstone** — a marker that shadows older values. Tombstones are removed
only during compaction once no older value can exist. Watch for
**tombstone buildup** causing read slowdowns (range scans over many
tombstones).

## Compaction and the amplification triangle

Compaction merges SSTables: it discards shadowed/duplicate values and
tombstones, reduces the number of files a read must consult, and reclaims
space. Every design trades off three quantities, and you cannot minimize all
three at once:

- **Write amplification** — bytes written to disk per byte of user data
  (re-writing during merges)
- **Read amplification** — extra reads per query (more SSTables to consult)
- **Space amplification** — extra disk used by redundant/obsolete records

Two strategies anchor the tradeoff:
- **Size-tiered compaction** — merge SSTables of similar size; *lower write
  amplification*, but *higher read and space amplification* (many overlapping
  files). Good for write-heavy workloads.
- **Leveled compaction** — keep non-overlapping SSTables within each level,
  each level ~10× the previous; *lower read and space amplification*, but
  *higher write amplification* (constant re-leveling). Good for read-heavy
  workloads.

There is no universal winner; choose from the workload, and expose it as a
tunable.

## LSM vs B-tree

Roughly: B-trees favor reads and in-place updates; LSM favors high write
throughput and sequential I/O. Whether LSM or B-tree has lower write
amplification is workload-dependent and genuinely contested — don't assert a
blanket winner.

## Language notes (C/C++/Rust)

- **Rust**: a skip list or `BTreeMap` makes a fine memtable; SSTables are
  append-only files with a block index + bloom filter footer. Immutability
  suits Rust ownership well — flushed SSTables are `Arc`-shared, read-only,
  and need no locking. Consider building on RocksDB (`rust-rocksdb`) if you
  don't need to own the engine.
- **C++**: study/leuse RocksDB or LevelDB directly. Mind compaction running
  on background threads contending with foreground reads — see concurrency
  notes in the book.
- The merge iterator (a k-way merge across memtable + SSTables, newest wins)
  is the heart of both reads and compaction — build and test it carefully,
  especially tombstone handling and version ordering.

## Grounding
Petrov Ch 7 (LSM trees, read/write/space amplification, implementation
details, unordered LSM storage, concurrency, log stacking, LLAMA). Petrov
Ch 1 (buffering, immutability, ordering).
