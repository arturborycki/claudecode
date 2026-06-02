# Engine internals — project rules (installed by skill picker)

This repository implements database / query-engine internals in
**C/C++/Rust**. Work is governed by the skill library in `skills/` (the
SKILL.md files alongside this config) and by the engine-dev agent in
`agents/engine-dev.md`.

## The spine
SQL → parse → logical plan → optimize → physical plan → execute over
columnar batches, on a storage engine (B-tree or LSM) over slotted pages,
with transactions/recovery underneath and parallelism/replication/consensus
on top. Map every task to a point on this spine and load the matching
skill(s) before writing code.

## Hard rules (non-negotiable)
1. **Correctness gates before performance.** Never change observable query
   results to win a benchmark. The golden suite passes first.
2. **Test-first.** Write the golden/unit/property tests (per
   `query-engine-testing`) before the implementation, including adversarial
   cases (nulls, empty inputs, spill thresholds, injected crashes).
3. **Every `unsafe` / manual-allocation block carries a written invariant**
   traceable to a skill (e.g., the Arrow buffer invariants in
   `columnar-arrow-layout`, page-bounds checks in `page-and-file-format`).
4. **Optimizer rules preserve schema and semantics**; prove the equivalence
   in the change description and assert plan *shape*, not just results.
5. **Persist durable state before acking** in any recovery/commit/consensus
   path; test every failure-path boundary.
6. **No performance-sensitive change merges without a before/after
   benchmark** (Criterion / Google Benchmark).

## Per-change loop
locate the box → spec the operator contract → write tests → implement →
verify safety (clippy+miri / ASan+UBSan+TSan) → verify speed (bench) →
report the delta.
