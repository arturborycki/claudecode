---
name: columnar-arrow-layout
description: "Use when working with columnar in-memory data and vectorized execution: Apache Arrow record batches, column vectors/arrays, validity (null) bitmaps, offsets buffers, dictionary encoding, zero-copy slicing, the type system, or batch-at-a-time expression evaluation. Triggers on Arrow, RecordBatch, ArrayData, validity bitmap, null buffer, offsets buffer, dictionary encoding, vectorized execution, SIMD over columns, columnar vs row. Apply this whenever someone touches the in-memory data representation an operator reads or writes."
---

# Columnar / Arrow Memory Layout

The in-memory data format is the substrate every operator reads and writes.
Columnar layout is what makes analytical engines fast — and its byte-level
invariants are exactly where `unsafe`/manual-memory code goes wrong.

## Why columnar

Row layout interleaves all columns of a row; columnar stores each column
contiguously. For analytics this wins because you: touch only the columns a
query needs, scan each column sequentially (cache- and prefetch-friendly),
apply SIMD across many values at once, and compress far better (adjacent
values share type and often range).

The unit of work is a **record batch** (a.k.a. column chunk / vector): a
fixed-ish number of rows for a set of columns. Operators process whole
batches, not rows — this amortizes per-call overhead and unlocks
vectorization.

## The Arrow physical layout (know these exactly)

A **primitive array** (e.g., `int64`) is:
- a **validity bitmap** — 1 bit per slot, 1 = valid, 0 = null (LSB-first
  within each byte); omitted entirely if there are no nulls
- a **values buffer** — the packed fixed-width values

A **variable-length array** (e.g., `utf8`/`binary`) adds:
- an **offsets buffer** — N+1 offsets; value i occupies
  `values[offsets[i] .. offsets[i+1]]`
- a values buffer of the concatenated bytes

**Invariants that `unsafe` code must uphold** (violating these is UB or
silent corruption):
- offsets are monotonically non-decreasing; `offsets[N]` == values length
- validity bitmap length covers all N slots; null_count matches the bitmap
- buffers are correctly aligned (typically 64-byte) for SIMD
- a "null" slot's value bytes are unspecified — never read them as data

**Dictionary encoding** stores values once in a dictionary and the column as
indices into it — great for low-cardinality strings; the operator must
follow the indirection or operate on indices directly.

## Vectorized execution

A `PhysicalExpr.evaluate(batch)` returns a whole column vector, not a
scalar. Implement binary ops, comparisons, and filters to process the
values buffer in a tight loop the compiler can auto-vectorize (or with
explicit SIMD). Apply the validity bitmap to compute the result's null
mask. Type coercion rules decide the output type of mixed-type binary ops.

## Language notes (C/C++/Rust)

- **Rust**: use the `arrow` (arrow-rs) crate rather than reinventing layout
  — it gets the invariants right. Buffers are `Arc`-shared so slicing is
  zero-copy. Wrap any manual buffer reinterpretation in `unsafe` with a
  `// SAFETY:` comment citing the invariant above.
- **C++**: use the Arrow C++ library or the **Arrow C Data Interface** for
  zero-copy interop across language/library boundaries. Mind alignment when
  allocating buffers yourself.
- Zero-copy is the whole point: slice and share buffers, ref-count them,
  and pass column views down the operator tree instead of copying rows.

## Grounding
HQEW *Apache Arrow* (why columnar, memory layout, record batches, schemas/
types) and *Type System* (column vectors, literals, type coercion).
