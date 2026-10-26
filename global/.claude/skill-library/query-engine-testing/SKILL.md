---
name: query-engine-testing
description: "Use when testing or benchmarking any database/query-engine component: unit tests for operators and optimizer rules, SQL parse tests, golden/snapshot tests (sqllogictest-style), property/fuzz testing, deterministic simulation testing for distributed/concurrent code, integration tests, and performance/scalability benchmarks (TPC-H/TPC-DS, criterion/google-benchmark). Triggers on golden test, snapshot test, sqllogictest, fuzzing, property test, deterministic simulation, TPC-H, TPC-DS, benchmark harness, plan assertion, query correctness, regression test. Reach for this whenever correctness or performance of engine code needs verifying — engines are unusually hard to test, so apply it proactively."
---

# Query Engine Testing and Benchmarking

Query engines resist testing: the input space (queries × data × plans) is
effectively infinite, "correct" output for a query is itself defined by a
spec you're implementing, and parallel/distributed execution is
nondeterministic. Layer the strategy accordingly.

## The layered strategy

1. **Unit tests per operator** — feed known batches, assert exact output.
   Cover the adversarial cases from each operator's skill (e.g., the join
   NULL/empty/duplicate/spill matrix in `join-algorithms`).
2. **Golden / snapshot tests** — store query → expected result (and query →
   expected *plan*). **sqllogictest** is the standard format: a query plus
   its expected rows; run thousands cheaply and diff on change. This is the
   workhorse for end-to-end correctness.
3. **Property-based testing** — assert invariants over generated inputs:
   e.g., a result is invariant under an optimizer rule; `sort` output is
   ordered and a permutation of input; an aggregate matches a naive
   reference. (Rust: `proptest`; C++: rapidcheck.)
4. **Fuzzing** — point a fuzzer at the **parser** and **expression
   evaluator** (the most exposed, untrusted-input surfaces). They should
   never panic/crash/UB on any input — only return clean errors. (Rust:
   `cargo-fuzz`/libFuzzer; C++: libFuzzer + ASan/UBSan.)
5. **Integration tests** — real datasets, real queries, end to end.

## Testing the optimizer — assert plan shape

A rule that produces correct results but **never fires** is a silent
performance regression that result-only tests miss entirely. Snapshot the
`explain` output and assert the expected operator appears (e.g.,
"filter pushed below join"). Test that rewrites preserve results *and* shape.

## Testing parallel and distributed code

Nondeterministic output and timing make ordinary tests flaky. Use:
- **Deterministic simulation testing** — run the system on a simulated,
  seeded scheduler/network so a failing run is exactly reproducible; inject
  partitions, delays, reordering, and node crashes. This is how robust
  distributed databases (e.g., FoundationDB-style) are tested.
- Assert *set* equality (not row order) for unordered results; sort or
  canonicalize before comparing.

## Benchmarking — measure honestly

- **Isolate the stage** you mean to measure; **exclude planning time** from
  execution numbers (and vice versa) unless that's the point.
- **Warm up** and measure steady state; report cold-cache separately if it
  matters. Pin CPU frequency / disable turbo for stable numbers.
- Use a real harness — **Criterion** (Rust) or **Google Benchmark** (C++) —
  for microbenchmarks with statistical confidence intervals, not a stopwatch.
- Use **TPC-H / TPC-DS** for standardized end-to-end analytics benchmarks;
  measure **scalability** (does throughput grow with cores/nodes?) and
  **concurrency** (behavior under many simultaneous queries), not just
  single-query latency.
- **Common pitfalls**: measuring the wrong thing (cold cache, JIT warmup,
  including I/O setup), tiny datasets that fit in L2, comparing across
  different hardware, and benchmark-driven "optimizations" that change
  results — correctness tests gate first, always.

## Gate changes

Every performance-sensitive change carries a **before/after benchmark** in
its review; every change passes the golden suite first. No exceptions on the
correctness gate.

## Grounding
HQEW *Testing* (why engines are hard to test, unit/integration/fuzz/golden
testing, testing optimizations, testing parallel/distributed execution, CI)
and *Benchmarks* (measuring performance/scalability, concurrency, TPC
benchmarks, common pitfalls).

## EDBS grounding & deeper skills
EDBS 2e entries (pull full text with `edbs-reference`: `python3 <edbs-reference>/scripts/edbs.py show "<Entry>"`):
*Database Benchmarks* (p.936); *Microbenchmark* (p.2255); *Application Benchmark* (p.122); *Benchmark Frameworks* (p.267); *Data Generation* (p.772); *Real and Synthetic Test Datasets* (p.3110).
Go deeper with: `tuning-and-benchmarking`, `sql-semantics-and-active-rules`.
