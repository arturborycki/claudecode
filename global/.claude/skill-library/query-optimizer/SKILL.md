---
name: query-optimizer
description: "Use when implementing or reviewing query optimization: rewrite rules (predicate push-down, projection push-down, constant folding, common-subexpression elimination), cardinality/cost estimation, or cost-based plan and join-order selection. Triggers on optimizer, rewrite rule, push down, plan rewrite, cardinality estimate, selectivity, cost model, join ordering, plan cost. Apply this whenever a change could alter the chosen plan, even when phrased as 'make this query faster' rather than 'optimize'."
---

# Query Optimizer

Optimization has two tiers that must not be confused. **Rule-based**
rewrites are transformations that are (almost) always wins and need no
statistics. **Cost-based** choices need statistics and a cost model to
pick among semantically equivalent alternatives.

## Rule-based rewrites

Each rule matches a plan pattern and produces an equivalent one. The
non-negotiable invariant: **a rule must preserve the output schema and
semantics**. State the equivalence argument for every rule you add.

High-value rules:

- **Predicate push-down** — move selections as close to the scan as
  possible so less data flows upward. Pushing a selection through a binary
  operator follows three rules:
  - **Union**: the selection *must* be pushed to *both* arguments.
  - **Difference**: *must* push to the first argument; *optionally* to the
    second.
  - **Join / product / intersection**: push to the argument(s) whose
    columns the predicate references; for a join it is only required to
    push to one side, and pushing a single-table predicate to that side is
    a clear win.
- **Projection push-down** — drop columns early; only carry columns some
  ancestor actually needs. Compute required-column sets top-down.
- **Constant folding** — evaluate constant subexpressions at plan time.
- **Common-subexpression elimination** — compute a repeated expression
  once.

Rule-authoring template: `match pattern → guard (when is it legal) →
rewrite → note why output schema + semantics are preserved`.

## Cost-based selection

When several equivalent physical plans exist (which join algorithm, which
join order, which index), pick by estimated cost.

- **Cardinality/selectivity estimation** — estimate rows out of each
  operator. Common heuristics: equality predicate selectivity ≈ 1/V(A) (V
  = number of distinct values); range ≈ 1/3 as a default; join output ≈
  T(R)·T(S)/max(V(R,a),V(S,a)). These are rough — **estimation error is
  the dominant source of bad plans**, so prefer plans that are robust to
  misestimation, not just cheapest on paper.
- **Cost model** — cost is dominated by I/O (blocks read/written) plus CPU.
  Use the per-operator cost formulas from `join-algorithms` and
  `storage-and-indexing`.
- **Join ordering** — the search space is huge (Catalan-number many
  shapes). Use **dynamic programming** over subsets (System-R style) to
  find the best order, and in practice restrict to **left-deep** trees to
  keep the search tractable and to keep one build side small at a time.
  Bushy trees can win but explode the search space.

## Where optimization fits

Optimize the *logical* plan with rules first, then let the planner make
cost-based physical choices. Some engines interleave them; keep the phases
conceptually distinct so each rule/choice is testable in isolation.

## Testing optimizers (critical)

Assert on **plan shape**, not just results. A rule that produces correct
results but doesn't actually fire is a silent regression. See
`query-engine-testing` for plan-snapshot tests.

## Language notes (C/C++/Rust)

- Represent the rule set as a list of `trait OptimizerRule { fn optimize(&self, plan) -> Plan }`
  (Rust) / abstract `Rule` class (C++) applied to a fixpoint or a fixed
  pass order.
- Immutable plan trees (see `query-plan-design`) make rewrites safe:
  produce a new tree, never mutate.
- Keep statistics in a separate catalog object passed to the cost model so
  the optimizer stays testable with synthetic stats.

## Grounding
DBMS §16.2 (algebraic laws), §16.4 (cost estimation), §16.5 (cost-based
plan selection), §16.6 (join ordering). HQEW *Query Optimizations*
(rule-based vs cost-based, projection/predicate push-down, CSE).

## EDBS grounding & deeper skills
EDBS 2e entries (pull full text with `edbs-reference`: `python3 <edbs-reference>/scripts/edbs.py show "<Entry>"`):
*Query Optimization (in Relational Databases)* (p.3009); *System R (R*) Optimizer* (p.3866); *Join Order* (p.2051); *Cost Estimation* (p.647); *Selectivity Estimation* (p.3371); *Query Rewriting* (p.3060).
Go deeper with: `cardinality-and-statistics`, `relational-theory`, `materialized-views-ivm`.
