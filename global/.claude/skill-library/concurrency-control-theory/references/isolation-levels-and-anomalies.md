# Isolation levels and anomalies: ANSI, Berenson et al., Adya, products, checkers

Isolation levels trade correctness for concurrency. Three formalisations
coexist and engine builders need all three: the ANSI phenomena (what the
standard says), the lock-duration definitions (what locking engines
implement), and Adya's dependency-graph phenomena (implementation-neutral,
what checkers test).

## 1. ANSI SQL-92 phenomena and levels

Phenomena as the standard words them (paraphrased):
- **P1 dirty read**: T2 reads a row written by T1 before T1 terminates; if T1
  aborts, T2 saw a value that never existed.
- **P2 non-repeatable (fuzzy) read**: T1 reads a row, T2 modifies or deletes it
  and commits, T1 re-reads and gets a different value or nothing.
- **P3 phantom**: T1 reads the rows satisfying predicate P, T2 inserts/updates/
  deletes rows so the set satisfying P changes, T1 re-evaluates P and gets a
  different set.

| Level | P1 | P2 | P3 |
|---|---|---|---|
| READ UNCOMMITTED | possible | possible | possible |
| READ COMMITTED | prevented | possible | possible |
| REPEATABLE READ | prevented | prevented | possible |
| SERIALIZABLE | prevented | prevented | prevented (and "serializable") |

Each transaction picks its own level; a SERIALIZABLE transaction may still read
data written by a READ COMMITTED writer, so guarantees are per-transaction,
not global. Gray's degrees of consistency (1976) are the ancestors: degree 0
(short write locks), 1 (long write locks = RU), 2 (long write + short read
locks = RC), 3 (long read and write locks incl. predicates = serializable).
A simulation study (Bober and Carey 1992) reported RC throughput 2.5–3x that
of serializable under contention, which is why RC is the de facto default.

## 2. The Berenson et al. critique (SIGMOD 1995)

Key points, each of which has a design consequence:

1. **The English is ambiguous.** Each phenomenon has a *strict* (anomaly)
   reading requiring the bad outcome to materialise, and a *broad*
   (phenomenon) reading that forbids the risky interleaving pattern itself.
   Notation (`...` = anything, `c/a` = terminal):
   ```
   A1 (strict dirty read)   w1[x] ... r2[x] ... (a1 and c2)
   P1 (broad dirty read)    w1[x] ... r2[x] ... (c1 or a1)
   A2 (strict fuzzy read)   r1[x] ... w2[x] ... c2 ... r1[x] ... c1
   P2 (broad fuzzy read)    r1[x] ... w2[x] ... (c1 or a1)
   A3 (strict phantom)      r1[P] ... w2[y in P] ... c2 ... r1[P] ... c1
   P3 (broad phantom)       r1[P] ... w2[y in P] ... (c1 or a1)
   ```
   Strict readings are too weak: e.g. `r1[x=50] w1[x=10] r2[x=10] r2[y=50] c2
   r1[y=50] w1[y=90] c1` violates the invariant `x+y=100` as seen by T2 yet
   matches no A1 pattern (T1 commits). Only the broad readings, combined with
   P0, characterise locking-based levels.
2. **P0 dirty write is missing** and must be forbidden at *every* level:
   `w1[x] ... w2[x] ... (c1 or a1)`. With dirty writes, before-image undo is
   incorrect (strictness lost) and constraints spanning items break even in
   serial-looking executions.
3. **Locking definitions** (the "real" levels in locking engines):

   | Level | Write locks | Item read locks | Predicate read locks |
   |---|---|---|---|
   | Degree 0 | well-formed, short | none | none |
   | READ UNCOMMITTED | long | none | none |
   | READ COMMITTED | long | short (per read) | short |
   | CURSOR STABILITY | long | held on current cursor row until it moves | short |
   | REPEATABLE READ | long | long | short |
   | SERIALIZABLE | long | long | long |

4. **Missing anomalies** that the levels actually differ on:
   ```
   P4  lost update        r1[x] ... w2[x] ... w1[x] ... c1
   P4C cursor lost update rc1[x] ... w2[x] ... w1[x] ... c1   (rc = cursor read)
   A5A read skew          r1[x] ... w2[x] ... w2[y] ... c2 ... r1[y] ... (c1 or a1)
   A5B write skew         r1[x] ... r2[y] ... w1[y] ... w2[x] ... (c1 and c2)
   ```
   Cursor Stability prevents P4C but not P4; RC allows both.
5. **Snapshot isolation is a distinct level**, incomparable with REPEATABLE
   READ: SI forbids A3 (and A5A, P4) but allows A5B; locking RR forbids A5B
   (long item read locks) but allows P3/A3. Both are strictly weaker than
   SERIALIZABLE.

Summary table (Berenson et al. Table 4, condensed):

| Level | P0 | P1 | P4C | P4 | P2 | P3 | A5A | A5B |
|---|---|---|---|---|---|---|---|---|
| READ UNCOMMITTED | no | yes | yes | yes | yes | yes | yes | yes |
| READ COMMITTED | no | no | yes | yes | yes | yes | yes | yes |
| CURSOR STABILITY | no | no | no | sometimes | sometimes | yes | yes | sometimes |
| REPEATABLE READ | no | no | no | no | no | yes | no | no |
| SNAPSHOT | no | no | no | no | no | sometimes | no | yes |
| SERIALIZABLE | no | no | no | no | no | no | no | no |

("sometimes" = the broad phenomenon pattern can occur but some of its harmful
instances are prevented; for SI and P3, strict phantoms A3 cannot occur but
predicate-based write skew can.) Hierarchy: `RU << RC << CS << RR <<
SERIALIZABLE`, `RC << SI`, `SI <<>> RR`.

6. **Phenomena do not define serializability for multiversion systems.** A
   system that prevents all of P0–P3 in their single-version reading may
   still not be serializable if it is multiversion (SI prevents A3, P1, P2 in
   effect yet admits write skew). The standard's SERIALIZABLE is defined as
   "serializable", which is the only reliable part.

## 3. Adya's generalised isolation (Adya PhD 1999; Adya, Liskov, O'Neil ICDE 2000)

Implementation-neutral definitions over histories with explicit version
orders, valid for locking, OCC and MVCC alike.

**Direct Serialization Graph (DSG).** Nodes = committed transactions. Edges:
- `Ti -ww-> Tj` (write-depends): Ti installs `xi`, Tj installs the *next*
  version of x;
- `Ti -wr-> Tj` (read-depends): Tj reads a version Ti installed (item), or
  Ti's write changes the matches of a predicate Tj read (predicate
  read-depends);
- `Ti -rw-> Tj` (anti-depends): Ti reads a version of x and Tj installs the
  next version (item), or Tj's write changes the matches of a predicate Ti
  read (predicate anti-dependency).

**Phenomena.**

| Phenomenon | Definition | Prohibited by |
|---|---|---|
| G0 write cycles | DSG cycle of ww edges only | PL-1 (≈ READ UNCOMMITTED; forbids P0) |
| G1a aborted reads | a committed Tj reads a version written by an aborted Ti | PL-2 |
| G1b intermediate reads | committed Tj reads a non-final version of x written by Ti | PL-2 |
| G1c circular information flow | DSG cycle of ww and wr edges only | PL-2 |
| G1 | G1a ∨ G1b ∨ G1c | PL-2 (≈ READ COMMITTED) |
| G-single | DSG cycle with exactly one rw edge | PL-2+ (consistent view; "no read skew") |
| G2-item | DSG cycle with ≥1 item rw edge | PL-2.99 (≈ REPEATABLE READ) |
| G2 | DSG cycle with ≥1 rw edge (item or predicate) | PL-3 (serializable) |
| G-SI (G-SIa interference, G-SIb missed effects) | defined on the start-ordered serialization graph (SSG) adding start edges | PL-SI (snapshot isolation) |
| G-cursor | cycle involving a cursor-read anti-dependency on one item | PL-CS (cursor stability) |

Why this matters for builders:
- These are checkable from observed histories without knowing the engine.
- PL-3 = "no G1, no G2": serializability is exactly the absence of cycles,
  in particular the absence of rw-containing cycles once G1 is excluded. SI
  permits G2 cycles that have ≥2 rw edges (write skew), consistent with the
  Fekete theorem (consecutive rw pair).
- Strict serializability (PL-3 plus real time) adds real-time edges
  (Ti committed before Tj began) to the graph: cycles through real-time
  edges are violations (e.g. stale reads after a committed write).

## 4. What products actually ship (verify against current docs before relying on details)

| Product | READ COMMITTED | REPEATABLE READ | SERIALIZABLE |
|---|---|---|---|
| PostgreSQL | per-statement snapshot | SI (FCW-style aborts) | SSI (9.1+) |
| Oracle | per-statement snapshot | n/a | SI ("serializable" name) |
| SQL Server | locking RC, or RCSI (statement snapshots) | locking RR | locking SERIALIZABLE (key-range locks); separate SNAPSHOT level = SI |
| MySQL InnoDB | per-statement consistent read; locking reads lock latest | transaction snapshot for plain reads; locking reads/writes use latest version with next-key locks (lost update possible, not SI) | locking (plain SELECTs become shared locking reads) |
| DB2 | CS (cursor stability) default | RS (read stability, ≈ ANSI RR) | RR (≈ serializable, next-key locking) |

DB2's names are shifted relative to ANSI (DB2 "RR" is ANSI SERIALIZABLE).
Mixed-level workloads: a SERIALIZABLE transaction's guarantees hold only with
respect to other SERIALIZABLE transactions in SSI-style engines (the
tracking is not done for weaker-level transactions).

## 5. Anomaly catalogue with minimal reproductions

Use these as engine regression tests (two sessions, explicit interleaving).

```
Lost update (P4):     T1: r(x=10)           T2: r(x=10)
                      T1: w(x=11) c          T2: w(x=11) c      -> x=11, expected 12
Read skew (A5A):      T1: r(x=50)  T2: w(x=25) w(y=75) c  T1: r(y=75)   -> sum 125
Write skew (A5B):     both read x,y; T1 writes x, T2 writes y; both commit
Predicate write skew: both run SELECT count(*) WHERE room=1 AND overlaps(t)
                      -> 0; both INSERT a booking; both commit
Phantom (A3):         T1: SELECT ... WHERE dept='Toy'   T2: INSERT dept='Toy' c
                      T1: same SELECT -> extra row
Read-only anomaly:    see mvcc-si-ssi.md section 4
Dirty write (P0):     T1: w(x=1)  T2: w(x=2)  T1: abort -> undo restores x0,
                      wiping T2's write (or T2 commits a state depending on T1)
```

Hermitage (Kleppmann) is a public suite of exactly these interleavings run
against many products; a good template for an engine's own isolation tests.

## 6. Checking isolation from the outside

> **Beyond EDBS: Elle (Kingsbury and Alvaro, VLDB 2020).** Black-box checker
> used by Jepsen. Workloads use *traceable* objects (append-only lists, or
> registers with unique writes), so every read reveals the full version order
> of the object; from observed reads Elle infers ww, wr and rw edges (and
> real-time / process-order edges), builds Adya's DSG, and reports cycles
> classified as G0, G1a, G1b, G1c, G-single, G2-item, and their real-time
> variants, plus non-cyclic anomalies (aborted reads, duplicated or garbage
> values, internal inconsistency). Because version orders are recovered
> rather than guessed, checking is roughly linear in history size, unlike
> general serializability checking. Engine builders can reuse the method:
> list-append workload + DSG + cycle search (Tarjan SCC) as an oracle in
> randomized/deterministic simulation tests.

> **Beyond EDBS: Jepsen practice.** Linearizability checks (Knossos/Porcupine
> style) are for single-object registers; Elle for multi-object
> transactional isolation. Failure injection (partitions, clock skew, process
> pauses) is what surfaces most real violations, typically G-single or
> G2-item from stale snapshots, lost updates in "REPEATABLE READ", and
> G1a/G1b from read-your-uncommitted-writes bugs in distributed commit.

## 7. Choosing and documenting levels: review heuristics

- Every update transaction that maintains a multi-row invariant needs
  SERIALIZABLE (or a proof via SDG analysis that SI suffices for the
  workload).
- Under RC, "read then write" logic must use atomic `UPDATE ... SET x = x +
  d`, `SELECT ... FOR UPDATE`, or constraints; otherwise P4.
- Under SI, uniqueness and exclusion invariants must be enforced by unique
  indexes / exclusion constraints (which take real locks), not by
  check-then-insert.
- Long read-only reports: snapshot (SI or SSI deferrable read-only) instead of
  serializable locking.
- Name the level semantics precisely in docs: statement-level vs transaction
  snapshot, FCW vs first-updater-wins, whether locking reads see the latest
  version, whether serializable is SI.

## Key papers
- Gray, Lorie, Putzolu, Traiger 1976 (degrees of consistency).
- ANSI X3.135-1992 (SQL-92).
- Berenson, Bernstein, Gray, Melton, O'Neil, O'Neil, SIGMOD 1995.
- Adya, MIT PhD thesis 1999 (MIT/LCS/TR-786); Adya, Liskov, O'Neil, ICDE 2000.
- Fekete, "Allocating isolation levels to transactions", PODS 2005.
- Bernstein, Lewis, Lu, "Semantic conditions for correctness at different
  isolation levels", ICDE 2000.
- Kingsbury and Alvaro, "Elle", PVLDB 14(3) 2020.

Sources: EDBS "SQL Isolation Levels" (p.3681), "Snapshot Isolation"
(p.3513), "Serializable Snapshot Isolation" (p.3476), "Tuning Concurrency
Control" (p.4252), "Locking Granularity and Lock Types" (p.2131), "Two-Phase
Locking" (p.4270, phantoms).
