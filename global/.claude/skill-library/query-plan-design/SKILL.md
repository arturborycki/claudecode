---
name: query-plan-design
description: "Use when defining or changing the plan layer of a query engine: logical/physical plan node types, operator interfaces, plan printing/explain output, expression trees, or the logical→physical lowering step. Triggers on LogicalPlan, PhysicalPlan, ExecutionPlan, operator tree, plan node, explain output, adding a new operator, or the logical-vs-physical split. Apply this whenever someone is shaping the contract every operator must implement, even if they don't say 'plan' explicitly."
---

# Query Plan Design

The plan layer is the backbone every other component plugs into. Get the
two interfaces (logical and physical) right and the rest of the engine
composes cleanly; get them wrong and every operator leaks complexity.

## Separate logical from physical — always

A **logical plan** describes *what* result is wanted (relational intent):
scan, projection, selection, aggregate, join. It carries a schema and
children but no execution strategy. A **physical plan** describes *how*:
a specific algorithm (hash join vs sort-merge), a specific access path,
and an executable iterator.

Keep them as distinct type hierarchies. The optimizer rewrites logical
plans; the query planner lowers a logical plan to a physical one; only
physical plans execute. Mixing the two means the optimizer has to reason
about execution details and the planner has nowhere to make cost-based
choices.

## The minimal interfaces

Logical plan node:
- `schema() -> Schema` — output schema (the optimizer and planner depend on this)
- `children() -> [LogicalPlan]` — for tree traversal and rewrites
- pretty-print support (see below)

Physical plan node:
- `schema() -> Schema`
- `children() -> [PhysicalPlan]`
- `execute() -> Stream<RecordBatch>` — the **pull/iterator model**: each
  operator pulls batches from its children on demand. This is what makes
  pipelining and back-pressure possible.

Expressions get their own parallel split: `LogicalExpr` (column refs,
literals, binary ops, aggregates, aliases, casts) each expose
`to_field(input_schema) -> Field` so the engine can type-check and build
output schemas before execution. `PhysicalExpr` expose
`evaluate(batch) -> ColumnVector`.

## Make plans printable from day one

A plan you cannot read is a plan you cannot debug. Implement indented
tree printing where each level adds two spaces:

```
Projection: #id, #name
  Filter: #age > 21
    Scan: users; projection=[id, name, age]
```

This `explain` output is the single most valuable debugging tool you will
build. Wire it before you wire execution.

## Adding a new operator — the checklist

1. Logical node (type + `schema()` + `children()` + printing)
2. Planner rule that lowers it to one or more physical nodes
3. Physical node implementing `execute()`
4. Optimizer rules that apply to it (push-down compatibility, etc.)
5. Golden tests for both the plan shape and the result

## Language notes (C/C++/Rust)

- **Rust**: model nodes as an `enum LogicalPlan { Scan(..), Filter(..), .. }`
  or as a `trait LogicalPlan` with boxed children (`Arc<dyn LogicalPlan>`).
  `Arc` over children enables cheap sharing during rewrites. Streams of
  record batches map naturally to `Stream<Item = Result<RecordBatch>>`.
- **C++**: a polymorphic base class with `std::vector<std::unique_ptr<Node>>`
  children; an iterator/`Next()`-style interface for physical execution.
  Prefer `unique_ptr` ownership down the tree, raw pointers for non-owning
  back-references.
- Keep nodes immutable where possible; rewrites produce new trees rather
  than mutating in place, which makes the optimizer far easier to reason
  about and test.

## Grounding
HQEW *Logical Plans and Expressions*, *Physical Plans and Expressions*,
*Query Planner*. DBMS §15.1 (physical-query-plan operators), §16.3 (parse
trees → logical query plans).
