---
name: page-and-file-format
description: "Use when designing or implementing the on-disk byte layout of a storage engine: page structure, slotted pages, cell layout, record/tuple encoding, variable-size data management, fixed vs variable encoding, endianness, alignment, versioning, and checksumming. Triggers on slotted page, page header, cell, tuple format, record layout, binary encoding, serialization format, page checksum, on-disk format, free space management. Reach for this whenever bytes are being laid out on disk or wire — it is the foundation B-trees and LSM SSTables are built on."
---

# Page and File Format

This is the byte layer: how records become bytes on a page, and pages
become a file. It underlies B-trees (`storage-and-indexing`) and LSM
SSTables (`lsm-storage`). In C/C++/Rust this is where most corruption and
UB bugs originate, so precision matters.

## Binary encoding principles

- **Fixed-size fields** are trivial: a known offset and width. Pack them at
  the front of a record.
- **Variable-size fields** (strings, blobs) need either a length prefix or
  an offset/length pair stored elsewhere in the record.
- **Endianness**: pick one (big-endian/network order makes keys
  memcmp-comparable; little-endian matches most hardware) and enforce it at
  the (de)serialization boundary. Never assume the reader's native order.
- **Alignment**: align fields you will read as native integers, or read
  through unaligned-safe accessors. Misaligned reads are UB in C/C++ and
  require `read_unaligned` in Rust.
- Booleans/flags pack into bitfields; favor explicit widths (`u32`, not
  `int`) so the format is portable.

## Page structure

Storage is organized into fixed-size **pages** (commonly 4–16 KB, matching
or multiplying the OS/disk block). A page has a **header** (page id/type,
record count, free-space pointers, optional checksum and version) followed
by the page body.

## Slotted pages — the standard for variable-size records

The problem: variable-size records create fragmentation; you can't reuse a
freed m-byte slot for an n-byte record unless sizes line up. The solution
is the **slotted page**:

- A **slot directory** (array of offsets/lengths) grows from the *start* of
  the page body downward.
- The **cells** (the actual record bytes) grow from the *end* of the page
  upward.
- Free space is the gap in the middle; the header tracks its bounds.
- A record is addressed by `(page id, slot index)` — the **slot is stable**
  even when the cell moves during in-page compaction, so external pointers
  (and indexes) don't break.

This separation lets you reclaim space by compacting cells without changing
any record's logical address.

## Cell layout

A **cell** holds one record (or one key + child-pointer for an internal
B-tree node). Distinguish key cells from key-value cells. Store the key
length and value length so the reader can navigate without external schema
where needed.

## Versioning and checksumming

- **Versioning**: put a format version in the page/file header. Readers
  check it and refuse or adapt. This is how you evolve the format without
  breaking old files.
- **Checksumming**: store a checksum (CRC32C is fast and common) over the
  page contents. Verify on read to catch silent corruption (bit rot, torn
  writes) *before* it propagates into query results. Decide what the
  checksum covers and whether it lives in the header or trailer.

## Torn writes

A page write may be interrupted (power loss) leaving a half-written page.
Defend with checksums plus one of: double-write buffer, copy-on-write
pages, or full-page logging on first write after checkpoint.

## Language notes (C/C++/Rust)

- **Rust**: define page access over a `&[u8]`/`&mut [u8]`; use
  `read_unaligned`/explicit `from_le_bytes`/`from_be_bytes` rather than
  casting a `&[u8]` to `&Header` (which is UB without `repr(C)` +
  alignment + `bytemuck`/`zerocopy`). The `zerocopy` and `bytemuck` crates
  give safe, checked reinterpretation.
- **C++**: a `#pragma pack`/`alignas` `struct` mapped over the buffer works
  but is endianness- and alignment-fragile across platforms; prefer
  explicit byte (de)serialization for portable formats. Validate the
  checksum before trusting any header field.
- Treat every byte read from disk as untrusted: validate lengths and
  offsets against page bounds before indexing, or a corrupt page becomes an
  out-of-bounds read.

## Grounding
Petrov Ch 3 (file formats: binary encoding, page structure, slotted pages,
cell layout, variable-size data, versioning, checksumming), Ch 4 (page
header, implementing B-trees). DBMS Ch 13 (arranging data on disk,
block/record addresses, variable-length records).

## EDBS grounding & deeper skills
EDBS 2e entries (pull full text with `edbs-reference`: `python3 <edbs-reference>/scripts/edbs.py show "<Entry>"`):
*Storage Manager* (p.3736); *Index Creation and File Structures* (p.1842); *Checksum and Cyclic Redundancy Check Mechanism* (p.423); *Disk* (p.1143).
Go deeper with: `storage-devices-and-io`, `recovery-and-durability`.
