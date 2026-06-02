---
name: sql-frontend
description: "Use when building or extending the SQL front end of a query engine: tokenizer/lexer, parser, operator precedence, or the binder/analysis pass that turns a parse tree into a validated logical plan. Triggers on tokenizing, lexer, Pratt parser, precedence climbing, parsing SELECT, name resolution, binding, semantic analysis, GROUP BY/aggregate planning. Reach for this whenever someone is turning SQL text into a plan, even if they just say 'parse SQL' or 'handle operator precedence'."
---

# SQL Front End

Turning SQL text into a validated logical plan is three stages: tokenize,
parse to a syntax tree, then plan/bind the tree into a logical plan. The
parser is the easy part; planning is the hard part.

## Tokenizing

Scan characters into tokens: keywords, identifiers, literals (number,
string), operators, punctuation. Keep it dumb and total — it should never
fail on valid SQL and should produce precise spans for error messages.
Handle: quoted identifiers, string escaping, numeric literals (int vs
float), and multi-char operators (`<=`, `<>`, `||`).

## Parse expressions with a Pratt parser

SQL expression grammars are dominated by precedence and associativity
(`a + b * c`, `NOT a AND b`, `a = b OR c`). A **Pratt parser**
(precedence climbing) handles this far more cleanly than a hand-rolled
recursive-descent grammar with one function per precedence level.

Core idea: each token has a **binding power**. Parse a prefix
("null denotation"), then keep consuming infix operators
("left denotation") while the next operator's binding power exceeds the
current minimum. Right-associative operators recurse with a slightly
lower minimum.

Maintain one precedence table — adding an operator is one table entry, not
a new grammar level. Typical SQL precedence, lowest to highest: `OR`,
`AND`, `NOT`, comparison (`= < > <= >= <>`), `+ -`, `* / %`, unary minus,
`.`/function-call.

## Parsing SELECT

Build a syntax tree with the clauses (projection list, FROM, WHERE,
GROUP BY, HAVING, ORDER BY, LIMIT). Parsing is mechanical; do not try to
resolve names or types here.

## Planning is the hard part

Turning the syntax tree into a logical plan is where the real work lives:

- **Name/scope resolution** — resolve column references against the
  schemas of FROM sources; report ambiguous or unknown columns.
- **`SELECT *` expansion** — replace with the concrete columns.
- **Clause ordering** — the logical plan order is *not* the SQL text
  order. SQL `SELECT proj FROM t WHERE p GROUP BY g HAVING h` plans as
  Scan → Filter(p) → Aggregate(g) → Filter(h) → Projection(proj). Get
  this order right or results are wrong.
- **Aggregate handling** — split the projection into grouping expressions
  and aggregate expressions; the aggregate node produces those, and a
  projection on top selects/reorders. `HAVING` becomes a filter *after*
  the aggregate.
- **Type checking** — verify operand types for binary expressions and
  insert casts per the engine's coercion rules.

## Why build your own parser

Reusing a SQL parser library is fine to start, but owning the front end
lets you control dialect, error quality, and the exact plan you build.
The planning logic is yours regardless of who wrote the parser.

## Language notes (C/C++/Rust)

- **Rust**: `enum Token`, `enum Expr`, `enum Statement`; the Pratt loop is
  a clean `fn parse_expr(&mut self, min_bp: u8) -> Result<Expr>`. The
  `sqlparser` crate is a reasonable starting parser if you want to focus
  on planning.
- **C++**: a `std::variant` token/AST or a class hierarchy; watch lifetime
  of string views into the source buffer — own the strings in tokens if
  the source buffer may not outlive the AST.
- Fuzz the tokenizer and parser early (see `query-engine-testing`) — they
  are the most exposed surface in the engine.

## Grounding
HQEW *SQL Support* (tokenizing, Pratt parsers, precedence, parsing SELECT,
SQL planning, aggregate queries). DBMS §16.1 (parsing and preprocessing).
